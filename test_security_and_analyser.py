"""
Unit tests — pure logic, no database or network required.
These run instantly and should all pass in CI with no external services.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)
from app.services.stock_service import StockAnalyserService


# ── Security ───────────────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("mysecretpassword")
        assert hashed != "mysecretpassword"

    def test_verify_correct_password(self):
        hashed = hash_password("correctpassword")
        assert verify_password("correctpassword", hashed) is True

    def test_reject_wrong_password(self):
        hashed = hash_password("correctpassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_two_hashes_of_same_password_differ(self):
        # bcrypt uses a random salt — same input produces different output
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2


class TestJWT:
    def test_encode_decode_roundtrip(self):
        token = create_access_token("user-123")
        subject = decode_access_token(token)
        assert subject == "user-123"

    def test_invalid_token_returns_none(self):
        result = decode_access_token("this.is.not.a.valid.token")
        assert result is None

    def test_tampered_token_returns_none(self):
        token = create_access_token("user-123")
        tampered = token[:-5] + "XXXXX"
        assert decode_access_token(tampered) is None


class TestApiKeys:
    def test_generate_returns_raw_and_hash(self):
        raw, hashed = generate_api_key()
        assert raw.startswith("mp_")
        assert len(hashed) == 64  # SHA-256 hex digest

    def test_hash_is_deterministic(self):
        raw, _ = generate_api_key()
        assert hash_api_key(raw) == hash_api_key(raw)

    def test_different_keys_have_different_hashes(self):
        raw1, _ = generate_api_key()
        raw2, _ = generate_api_key()
        assert hash_api_key(raw1) != hash_api_key(raw2)

    def test_stored_hash_matches_computed_hash(self):
        raw, stored_hash = generate_api_key()
        assert hash_api_key(raw) == stored_hash


# ── Stock Analyser ─────────────────────────────────────────────────────────────

class TestStockAnalyserCompare:
    def setup_method(self):
        self.analyser = StockAnalyserService()

    def _make_summary(self, ticker, change_30d, volatility, win_rate):
        return {
            "ticker": ticker,
            "current_price": 100.0,
            "change_30d_pct": change_30d,
            "period_high": 110.0,
            "period_low": 90.0,
            "avg_daily_return_pct": 0.1,
            "volatility_pct": volatility,
            "avg_daily_volume": 1_000_000,
            "best_day_pct": 3.0,
            "worst_day_pct": -2.5,
            "up_days": 55,
            "down_days": 45,
            "win_rate_pct": win_rate,
            "data_points": 100,
        }

    def test_best_performer_identified_correctly(self):
        summaries = [
            self._make_summary("AAPL", change_30d=10.0, volatility=1.2, win_rate=60.0),
            self._make_summary("GOOG", change_30d=5.0, volatility=0.8, win_rate=55.0),
            self._make_summary("MSFT", change_30d=15.0, volatility=1.5, win_rate=65.0),
        ]
        result = self.analyser.compare(summaries)
        assert result["best_performer"] == "MSFT"
        assert result["best_performer_return"] == 15.0

    def test_most_volatile_identified_correctly(self):
        summaries = [
            self._make_summary("AAPL", change_30d=5.0, volatility=2.5, win_rate=55.0),
            self._make_summary("GOOG", change_30d=5.0, volatility=0.5, win_rate=55.0),
        ]
        result = self.analyser.compare(summaries)
        assert result["most_volatile"] == "AAPL"
        assert result["most_stable"] == "GOOG"

    def test_requires_at_least_two_tickers(self):
        summaries = [self._make_summary("AAPL", 5.0, 1.0, 55.0)]
        with pytest.raises(ValueError, match="at least 2"):
            self.analyser.compare(summaries)

    def test_comparison_includes_all_summaries(self):
        summaries = [
            self._make_summary("AAPL", 5.0, 1.0, 55.0),
            self._make_summary("GOOG", 8.0, 1.5, 60.0),
        ]
        result = self.analyser.compare(summaries)
        assert len(result["summaries"]) == 2

    def test_highest_win_rate_identified(self):
        summaries = [
            self._make_summary("AAPL", 5.0, 1.0, win_rate=70.0),
            self._make_summary("GOOG", 5.0, 1.0, win_rate=45.0),
        ]
        result = self.analyser.compare(summaries)
        assert result["highest_win_rate"] == "AAPL"
        assert result["highest_win_rate_pct"] == 70.0
