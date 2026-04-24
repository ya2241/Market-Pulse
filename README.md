# MarketPulse API

A production-grade stock data API platform built with FastAPI, PostgreSQL, Redis, and Celery.

Evolved from a simple data pipeline script into a fully featured backend system with authentication, rate limiting, async job processing, and real-time analytics.

---

## Architecture

```
Client Request
      │
      ▼
  FastAPI App
      │
      ├── Auth Middleware (JWT / API Key)
      ├── Rate Limiter (Redis sliding window)
      │
      ▼
  Route Handlers
      │
      ├── PostgreSQL (via SQLAlchemy)  ← persistent data, user accounts, API keys
      ├── TimescaleDB hypertable       ← time-series stock price logs
      ├── Redis                        ← rate limit counters, caching
      └── Celery Workers               ← async fetch jobs, aggregations, alerts
```

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI (async) |
| Database | PostgreSQL 16 + TimescaleDB |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Cache / rate limit | Redis |
| Background jobs | Celery + Redis broker |
| Validation | Pydantic v2 |
| Auth | JWT (python-jose) + API keys |
| Containerisation | Docker + docker-compose |
| CI | GitHub Actions |
| Testing | Pytest + pytest-asyncio |
| Observability | Prometheus metrics endpoint |

---

## Quickstart (one command)

```bash
git clone https://github.com/yourname/marketpulse-api
cd marketpulse-api
cp .env.example .env          # add your Alpha Vantage key
docker-compose up --build
```

API docs available at: http://localhost:8000/docs

---

## API Endpoints

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Create account |
| POST | `/api/v1/auth/login` | Get JWT token |
| POST | `/api/v1/auth/api-keys` | Generate API key |

### Stock Data
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/stocks/{ticker}` | Latest price + stats |
| GET | `/api/v1/stocks/{ticker}/history` | OHLCV history |
| POST | `/api/v1/stocks/fetch` | Trigger async fetch job |
| GET | `/api/v1/stocks/compare` | Compare multiple tickers |

### Analytics
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/analytics/summary` | Aggregated stats per ticker |
| GET | `/api/v1/analytics/latency` | p50/p95/p99 API latency |
| GET | `/api/v1/analytics/usage` | Per-client request volume |

### Admin
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/clients` | List all clients |
| PATCH | `/api/v1/admin/clients/{id}/rate-limit` | Update rate limit |
| GET | `/metrics` | Prometheus metrics |

---

## Rate Limiting

Uses a **sliding window log** algorithm in Redis (Lua script, atomic, no race condition).

Each API key can have a custom rate limit policy. Default: 60 requests/minute.

Response headers on every request:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 47
X-RateLimit-Reset: 1704067260
Retry-After: 34   (only on 429)
```

---

## Running Tests

```bash
docker-compose run --rm api pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## Load Test Results

Tested with Locust against a local docker-compose stack (M2 MacBook, 4 workers):

| Scenario | RPS | p50 | p95 | p99 | Error rate |
|---|---|---|---|---|---|
| Auth + single stock fetch | 420 | 18ms | 45ms | 89ms | 0% |
| Rate limit enforcement | 380 | 12ms | 28ms | 54ms | 0% |
| Analytics aggregation | 110 | 62ms | 140ms | 210ms | 0% |

---

## Project Structure

```
app/
├── api/v1/endpoints/      # Route handlers
├── core/                  # Config, security, rate limiter
├── db/                    # Database session, base
├── models/                # SQLAlchemy models
├── schemas/               # Pydantic request/response schemas
├── services/              # Business logic (stock fetcher, analyser)
└── workers/               # Celery tasks

tests/
├── unit/                  # Pure logic tests (no DB)
└── integration/           # Full stack tests with test DB

alembic/                   # Database migrations
```
