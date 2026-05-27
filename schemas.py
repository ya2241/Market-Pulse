"""
Pydantic v2 schemas for request validation and response serialization.
Keeps API contracts separate from database models.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Auth ───────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only once at creation — includes the raw key."""
    raw_key: str


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    is_admin: bool
    is_active: bool
    created_at: datetime


# ── Stocks ─────────────────────────────────────────────────────────────────────

class StockResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    ticker: str
    name: str | None
    last_fetched_at: datetime | None
    created_at: datetime


class PriceLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class StockHistoryResponse(BaseModel):
    ticker: str
    data: list[PriceLogResponse]
    count: int


class FetchJobResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    status: str
    created_at: datetime
    completed_at: datetime | None
    error_message: str | None


class FetchRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.upper().strip()


class CompareRequest(BaseModel):
    tickers: list[str] = Field(min_length=2, max_length=5)

    @field_validator("tickers")
    @classmethod
    def uppercase_tickers(cls, v: list[str]) -> list[str]:
        return [t.upper().strip() for t in v]


# ── Analytics ──────────────────────────────────────────────────────────────────

class StockSummary(BaseModel):
    ticker: str
    current_price: float
    change_30d_pct: float
    period_high: float
    period_low: float
    avg_daily_return_pct: float
    volatility_pct: float
    avg_daily_volume: int
    best_day_pct: float
    worst_day_pct: float
    up_days: int
    down_days: int
    win_rate_pct: float
    data_points: int


class ComparisonResponse(BaseModel):
    summaries: list[StockSummary]
    best_performer: str
    best_performer_return: float
    most_volatile: str
    most_volatile_pct: float
    most_stable: str
    most_stable_pct: float
    highest_win_rate: str
    highest_win_rate_pct: float


class LatencyStats(BaseModel):
    path: str
    p50_ms: float
    p95_ms: float
    p99_ms: float
    total_requests: int
    period_hours: int


class UsageStats(BaseModel):
    api_key_id: str
    total_requests: int
    error_requests: int
    error_rate_pct: float
    period_hours: int


# ── Rate Limits ────────────────────────────────────────────────────────────────

class RateLimitUpdate(BaseModel):
    requests_per_window: int = Field(gt=0, le=10000)
    window_seconds: int = Field(gt=0, le=3600)


class RateLimitResponse(BaseModel):
    model_config = {"from_attributes": True}

    requests_per_window: int
    window_seconds: int
    updated_at: datetime


# ── Generic ────────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
