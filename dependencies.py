"""
FastAPI dependency functions.

These are injected into route handlers via Depends().
Keeps route handlers clean and all auth/rate-limit logic in one place.
"""

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limiter import rate_limiter
from app.core.security import decode_access_token, hash_api_key
from app.db.session import get_db
from app.models.models import ApiKey, RateLimitPolicy, User

bearer_scheme = HTTPBearer(auto_error=False)


# ── Current user from JWT ──────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ── API key auth + rate limiting ───────────────────────────────────────────────

async def get_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """
    Validates the X-Api-Key header, then enforces the sliding window rate limit.
    Attaches rate limit info to request.state so the middleware can write headers.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Api-Key header",
        )

    key_hash = hash_api_key(x_api_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    # Fetch custom rate limit policy if one exists
    policy_result = await db.execute(
        select(RateLimitPolicy).where(RateLimitPolicy.api_key_id == api_key.id)
    )
    policy = policy_result.scalar_one_or_none()

    limit = policy.requests_per_window if policy else None
    window = policy.window_seconds if policy else None

    rl = await rate_limiter.check(
        identifier=str(api_key.id),
        limit=limit,
        window_seconds=window,
    )

    # Stash result so response middleware can write X-RateLimit-* headers
    request.state.rate_limit = rl

    if not rl["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(rl["reset_at"]),
                "X-RateLimit-Limit": str(rl["limit"]),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(rl["reset_at"]),
            },
        )

    return api_key


# ── Optional API key (for endpoints that work with or without auth) ─────────────

async def get_optional_api_key(
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiKey | None:
    if not x_api_key:
        return None
    key_hash = hash_api_key(x_api_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    return result.scalar_one_or_none()
