import redis.asyncio as aioredis
from app.config import settings

# Single Redis client reused across all requests
_redis_client = None


async def get_redis():
    """
    Returns a Redis client.
    Creates it once and reuses it — no need to reconnect on every request.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def check_and_mark_duplicate(fingerprint: str) -> bool:
    """
    Returns True if this alert is a duplicate (seen within the dedup window).
    Returns False if this is a new alert.

    Uses Redis SET with NX (only set if not exists) and EX (expiry in seconds).
    This is atomic — no race conditions between check and set.
    """
    r = await get_redis()
    key = f"alertflow:dedup:{fingerprint}"

    # SET key "1" EX 300 NX
    # - EX 300 = expire after 300 seconds (from settings)
    # - NX     = only set if key does NOT already exist
    # Returns True if key was set (new alert)
    # Returns None if key already existed (duplicate)
    was_set = await r.set(
        key,
        "1",
        ex=settings.dedup_window_seconds,
        nx=True,
    )

    is_duplicate = was_set is None
    return is_duplicate


async def get_active_fingerprints() -> list[str]:
    """
    Returns all fingerprints currently in the dedup window.
    Useful for debugging and the dashboard.
    """
    r = await get_redis()
    keys = await r.keys("alertflow:dedup:*")
    # Strip the prefix to return just the fingerprints
    return [k.replace("alertflow:dedup:", "") for k in keys]


async def get_dedup_stats() -> dict:
    """
    Returns count of fingerprints currently in the dedup window.
    Used by the dashboard summary endpoint.
    """
    fingerprints = await get_active_fingerprints()
    return {
        "active_dedup_windows": len(fingerprints),
        "dedup_window_seconds": settings.dedup_window_seconds,
    }


async def clear_fingerprint(fingerprint: str) -> bool:
    """
    Manually removes a fingerprint from the dedup window.
    Useful when an alert is resolved — next occurrence should be treated as new.
    """
    r = await get_redis()
    key = f"alertflow:dedup:{fingerprint}"
    deleted = await r.delete(key)
    return deleted > 0