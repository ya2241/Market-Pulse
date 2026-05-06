"""
Database models.

Tables:
  users               - registered accounts (admin or regular)
  api_keys            - hashed API keys belonging to users
  rate_limit_policies - per-key or per-user rate limit overrides
  stocks              - known tickers with metadata
  price_logs          - TimescaleDB hypertable: OHLCV data per ticker per day
  request_logs        - TimescaleDB hypertable: every API request (for analytics)
  fetch_jobs          - background job tracking
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    BigInteger,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Users ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ── API Keys ───────────────────────────────────────────────────────────────────

class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")
    rate_limit_policy: Mapped["RateLimitPolicy | None"] = relationship(
        back_populates="api_key", uselist=False, cascade="all, delete-orphan"
    )


# ── Rate Limit Policies ────────────────────────────────────────────────────────

class RateLimitPolicy(Base):
    __tablename__ = "rate_limit_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    requests_per_window: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    api_key: Mapped["ApiKey"] = relationship(back_populates="rate_limit_policy")


# ── Stocks ─────────────────────────────────────────────────────────────────────

class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    price_logs: Mapped[list["PriceLog"]] = relationship(back_populates="stock", cascade="all, delete-orphan")
    fetch_jobs: Mapped[list["FetchJob"]] = relationship(back_populates="stock")


# ── Price Logs (TimescaleDB hypertable) ───────────────────────────────────────

class PriceLog(Base):
    """
    One row per ticker per trading day.
    After migration, this table is converted to a TimescaleDB hypertable
    partitioned on `date`. Time-range queries (e.g. last 30 days) are
    extremely fast — Postgres only scans the relevant chunks.
    """
    __tablename__ = "price_logs"
    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_price_log_stock_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)

    stock: Mapped["Stock"] = relationship(back_populates="price_logs")


# ── Request Logs (TimescaleDB hypertable) ─────────────────────────────────────

class RequestLog(Base):
    """
    One row per API request. Used for per-client analytics and latency tracking.
    Converted to a TimescaleDB hypertable on `timestamp` after migration.
    """
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=utcnow
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(10), nullable=True)


# ── Fetch Jobs ─────────────────────────────────────────────────────────────────

class FetchJob(Base):
    __tablename__ = "fetch_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # status: pending | running | success | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stock: Mapped["Stock"] = relationship(back_populates="fetch_jobs")
