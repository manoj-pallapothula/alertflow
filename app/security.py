from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from app.config import settings

# Looks for the key in the X-API-Key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """
    Checks the X-API-Key header against the configured API key.
    If no API_KEY is set in .env, auth is disabled (dev mode).
    If API_KEY is set, the header must match exactly.
    """
    # No key configured — skip auth (useful for local development)
    if not settings.api_key:
        return True

    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. "
                   "Include X-API-Key header with your request.",
        )
    return True