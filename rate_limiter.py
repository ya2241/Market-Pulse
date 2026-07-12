"""
Rate limiter using the sliding window log algorithm.

Implemented as a Redis Lua script so the entire check-and-increment is
atomic — no race condition is possible even under heavy concurrent load.

The script:
  1. Removes all request timestamps older than the window.
  2. Counts how many remain.
  3. If under the limit, adds the current timestamp and sets TTL.
  4. Returns (current_count, is_allowed).
"""

import time
import redis.asyncio as aioredis

from app.core.config import settings

# One connection pool shared across the app
_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


# The Lua script runs atomically on the Redis server side.
SLIDING_WINDOW_SCRIPT = """
local key       = KEYS[1]
local now       = tonumber(ARGV[1])
local window    = tonumber(ARGV[2])
local limit     = tonumber(ARGV[3])
local window_start = now - window

-- Remove timestamps outside the window
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- Count requests still inside the window
local count = redis.call('ZCARD', key)

if count < limit then
    -- Record this request (score = timestamp, member = timestamp+random for uniqueness)
    redis.call('ZADD', key, now, now .. '-' .. math.random(1, 1000000))
    redis.call('EXPIRE', key, window)
    return {count + 1, 1}
else
    return {count, 0}
end
"""


class RateLimiter:
    def __init__(self):
        self._script_sha: str | None = None

    async def _load_script(self, redis: aioredis.Redis) -> str:
        """Load the Lua script once and cache its SHA for EVALSHA."""
        if self._script_sha is None:
            self._script_sha = await redis.script_load(SLIDING_WINDOW_SCRIPT)
        return self._script_sha

    async def check(
        self,
        identifier: str,
        limit: int | None = None,
        window_seconds: int | None = None,
    ) -> dict:
        """
        Check whether this identifier is within its rate limit.

        Returns a dict with:
          allowed     bool   - whether the request should proceed
          count       int    - requests made in current window
          limit       int    - max allowed
          remaining   int    - how many left
          reset_at    int    - unix timestamp when window resets
        """
        r = get_redis()
        limit = limit or settings.DEFAULT_RATE_LIMIT_REQUESTS
        window = window_seconds or settings.DEFAULT_RATE_LIMIT_WINDOW_SECONDS

        now_ms = int(time.time() * 1000)
        window_ms = window * 1000
        key = f"ratelimit:{identifier}"

        sha = await self._load_script(r)
        count, allowed = await r.evalsha(sha, 1, key, now_ms, window_ms, limit)

        reset_at = int(time.time()) + window

        return {
            "allowed": bool(allowed),
            "count": int(count),
            "limit": limit,
            "remaining": max(0, limit - int(count)),
            "reset_at": reset_at,
        }


rate_limiter = RateLimiter()
