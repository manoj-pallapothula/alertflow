import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_new_alert_is_not_duplicate():
    """First time we see a fingerprint — should return False."""
    with patch("app.services.dedup.get_redis") as mock_get_redis:
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)  # SET NX succeeded = new key
        mock_get_redis.return_value = mock_client

        from app.services.dedup import check_and_mark_duplicate
        result = await check_and_mark_duplicate("abc123")

        assert result is False  # not a duplicate
        mock_client.set.assert_called_once_with(
            "alertflow:dedup:abc123", "1", ex=300, nx=True
        )


@pytest.mark.asyncio
async def test_repeat_alert_is_duplicate():
    """Same fingerprint within window — should return True."""
    with patch("app.services.dedup.get_redis") as mock_get_redis:
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=None)  # SET NX failed = key exists
        mock_get_redis.return_value = mock_client

        from app.services.dedup import check_and_mark_duplicate
        result = await check_and_mark_duplicate("abc123")

        assert result is True  # duplicate


@pytest.mark.asyncio
async def test_different_fingerprints_not_duplicate():
    """Different fingerprints should never be duplicates of each other."""
    with patch("app.services.dedup.get_redis") as mock_get_redis:
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)
        mock_get_redis.return_value = mock_client

        from app.services.dedup import check_and_mark_duplicate
        result1 = await check_and_mark_duplicate("fingerprint-aaa")
        result2 = await check_and_mark_duplicate("fingerprint-bbb")

        assert result1 is False
        assert result2 is False


@pytest.mark.asyncio
async def test_clear_fingerprint_returns_true_when_key_exists():
    """Clearing an existing fingerprint should return True."""
    with patch("app.services.dedup.get_redis") as mock_get_redis:
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=1)  # 1 key deleted
        mock_get_redis.return_value = mock_client

        from app.services.dedup import clear_fingerprint
        result = await clear_fingerprint("abc123")

        assert result is True


@pytest.mark.asyncio
async def test_clear_fingerprint_returns_false_when_key_missing():
    """Clearing a non-existent fingerprint should return False."""
    with patch("app.services.dedup.get_redis") as mock_get_redis:
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=0)  # 0 keys deleted
        mock_get_redis.return_value = mock_client

        from app.services.dedup import clear_fingerprint
        result = await clear_fingerprint("doesnotexist")

        assert result is False