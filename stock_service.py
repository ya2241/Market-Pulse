"""
Stock data fetcher service.

Evolved from the original fetcher.py — now async, uses httpx,
stores results in PostgreSQL, and handles retries properly.
"""

import asyncio
from datetime import datetime, timezone

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import FetchJob, PriceLog, Stock


class StockFetcherService:
    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self):
        self.api_key = settings.ALPHA_VANTAGE_API_KEY

    async def fetch_and_store(self, ticker: str, db: AsyncSession) -> dict:
        """
        Fetches up to 100 days of daily OHLCV data for `ticker`
        and upserts it into the price_logs table.

        Returns a summary dict with how many rows were inserted/updated.
        """
        raw = await self._fetch_from_api(ticker)
        df = self._parse_response(raw, ticker)
        rows_saved = await self._upsert_price_logs(ticker, df, db)

        # Update the stock's last_fetched_at timestamp
        result = await db.execute(select(Stock).where(Stock.ticker == ticker))
        stock = result.scalar_one_or_none()
        if stock:
            stock.last_fetched_at = datetime.now(timezone.utc)
            db.add(stock)

        return {"ticker": ticker, "rows_saved": rows_saved, "data_points": len(df)}

    async def _fetch_from_api(self, ticker: str) -> dict:
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker,
            "apikey": self.api_key,
            "outputsize": "compact",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(3):
                try:
                    response = await client.get(self.BASE_URL, params=params)
                    response.raise_for_status()
                    data = response.json()

                    if "Error Message" in data:
                        raise ValueError(f"Unknown ticker: {ticker}")
                    if "Note" in data:
                        raise ValueError("Alpha Vantage rate limit hit. Please wait and retry.")
                    if "Information" in data:
                        raise ValueError("Alpha Vantage API limit reached for this key.")

                    return data

                except httpx.HTTPStatusError as e:
                    if attempt == 2:
                        raise RuntimeError(f"API request failed after 3 attempts: {e}") from e
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError("Failed to fetch data")

    def _parse_response(self, raw: dict, ticker: str) -> pd.DataFrame:
        """
        Parses the Alpha Vantage response into a clean DataFrame.
        Reuses the logic from the original processor.py.
        """
        time_series = raw.get("Time Series (Daily)", {})
        if not time_series:
            raise ValueError(f"No time series data in response for {ticker}")

        df = pd.DataFrame(time_series).T
        df.columns = ["open", "high", "low", "close", "volume"]
        df = df.astype(float)
        df.index = pd.to_datetime(df.index, utc=True)
        df = df.sort_index()
        df["ticker"] = ticker
        return df

    async def _upsert_price_logs(
        self, ticker: str, df: pd.DataFrame, db: AsyncSession
    ) -> int:
        """
        Inserts new price rows, skipping dates that already exist.
        Uses ON CONFLICT DO NOTHING logic via Python-side duplicate check.
        """
        # Get the stock record, create if it doesn't exist
        result = await db.execute(select(Stock).where(Stock.ticker == ticker))
        stock = result.scalar_one_or_none()
        if not stock:
            stock = Stock(ticker=ticker)
            db.add(stock)
            await db.flush()  # get the stock.id

        # Fetch existing dates to avoid duplicates
        existing_result = await db.execute(
            select(PriceLog.date).where(PriceLog.stock_id == stock.id)
        )
        existing_dates = {row[0].date() for row in existing_result.fetchall()}

        rows_inserted = 0
        for date, row in df.iterrows():
            if date.date() in existing_dates:
                continue

            log = PriceLog(
                stock_id=stock.id,
                date=date,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
            )
            db.add(log)
            rows_inserted += 1

        return rows_inserted


class StockAnalyserService:
    """
    Calculates statistics from stored price data.
    Reuses and extends the logic from the original analyser.py.
    """

    async def get_summary(self, ticker: str, db: AsyncSession) -> dict:
        result = await db.execute(
            select(Stock).where(Stock.ticker == ticker)
        )
        stock = result.scalar_one_or_none()
        if not stock:
            raise ValueError(f"Ticker {ticker} not found. Fetch it first.")

        logs_result = await db.execute(
            select(PriceLog)
            .where(PriceLog.stock_id == stock.id)
            .order_by(PriceLog.date.asc())
        )
        logs = logs_result.scalars().all()

        if len(logs) < 2:
            raise ValueError(f"Not enough data for {ticker}. Fetch more data first.")

        df = pd.DataFrame(
            [{"date": l.date, "close": l.close, "volume": l.volume} for l in logs]
        )
        df["daily_return"] = df["close"].pct_change() * 100
        returns = df["daily_return"].dropna()

        prices = df["close"]
        current_price = prices.iloc[-1]
        price_30d_ago = prices.iloc[-30] if len(prices) >= 30 else prices.iloc[0]
        change_30d = ((current_price - price_30d_ago) / price_30d_ago) * 100

        up_days = int((returns > 0).sum())
        down_days = int((returns < 0).sum())

        return {
            "ticker": ticker,
            "current_price": round(float(current_price), 2),
            "change_30d_pct": round(float(change_30d), 2),
            "period_high": round(float(prices.max()), 2),
            "period_low": round(float(prices.min()), 2),
            "avg_daily_return_pct": round(float(returns.mean()), 3),
            "volatility_pct": round(float(returns.std()), 3),
            "avg_daily_volume": int(df["volume"].mean()),
            "best_day_pct": round(float(returns.max()), 2),
            "worst_day_pct": round(float(returns.min()), 2),
            "up_days": up_days,
            "down_days": down_days,
            "win_rate_pct": round(float(up_days / len(returns) * 100), 1),
            "data_points": len(logs),
        }

    def compare(self, summaries: list[dict]) -> dict:
        if len(summaries) < 2:
            raise ValueError("Need at least 2 tickers to compare")

        best = max(summaries, key=lambda s: s["change_30d_pct"])
        most_vol = max(summaries, key=lambda s: s["volatility_pct"])
        most_stable = min(summaries, key=lambda s: s["volatility_pct"])
        best_wr = max(summaries, key=lambda s: s["win_rate_pct"])

        return {
            "summaries": summaries,
            "best_performer": best["ticker"],
            "best_performer_return": best["change_30d_pct"],
            "most_volatile": most_vol["ticker"],
            "most_volatile_pct": most_vol["volatility_pct"],
            "most_stable": most_stable["ticker"],
            "most_stable_pct": most_stable["volatility_pct"],
            "highest_win_rate": best_wr["ticker"],
            "highest_win_rate_pct": best_wr["win_rate_pct"],
        }


stock_fetcher = StockFetcherService()
stock_analyser = StockAnalyserService()
