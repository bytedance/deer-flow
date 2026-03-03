"""Tests for gateway authentication middleware and thread ownership verification."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.gateway.auth.middleware import get_current_user, get_optional_user
from src.gateway.auth.ownership import verify_thread_ownership


def _make_credentials(token: str = "valid-token"):
    """Create a mock HTTPAuthorizationCredentials object."""
    creds = MagicMock()
    creds.credentials = token
    return creds


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------
class TestGetCurrentUser:
    """Tests for the get_current_user dependency."""

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.get_user_by_id")
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_valid_token_returns_user(self, mock_decode, mock_get_user) -> None:
        mock_decode.return_value = {"type": "access", "sub": "user-1"}
        mock_get_user.return_value = {
            "id": "user-1",
            "email": "test@example.com",
            "display_name": "Test",
            "created_at": "2025-01-01T00:00:00Z",
        }
        result = await get_current_user(_make_credentials())
        assert result["id"] == "user-1"
        assert result["email"] == "test@example.com"

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_expired_token_raises_401(self, mock_decode) -> None:
        import jwt as pyjwt

        mock_decode.side_effect = pyjwt.ExpiredSignatureError()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(_make_credentials())
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_invalid_token_raises_401(self, mock_decode) -> None:
        import jwt as pyjwt

        mock_decode.side_effect = pyjwt.InvalidTokenError()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(_make_credentials())
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_wrong_token_type_raises_401(self, mock_decode) -> None:
        mock_decode.return_value = {"type": "refresh", "sub": "user-1"}
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(_make_credentials())
        assert exc_info.value.status_code == 401
        assert "type" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_missing_sub_raises_401(self, mock_decode) -> None:
        mock_decode.return_value = {"type": "access"}
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(_make_credentials())
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.get_user_by_id")
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_user_not_found_raises_401(self, mock_decode, mock_get_user) -> None:
        mock_decode.return_value = {"type": "access", "sub": "user-1"}
        mock_get_user.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(_make_credentials())
        assert exc_info.value.status_code == 401
        assert "not found" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# get_optional_user
# ---------------------------------------------------------------------------
class TestGetOptionalUser:
    """Tests for the get_optional_user dependency."""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_none(self) -> None:
        result = await get_optional_user(None)
        assert result is None

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_invalid_token_returns_none(self, mock_decode) -> None:
        import jwt as pyjwt

        mock_decode.side_effect = pyjwt.InvalidTokenError()
        result = await get_optional_user(_make_credentials())
        assert result is None

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_wrong_type_returns_none(self, mock_decode) -> None:
        mock_decode.return_value = {"type": "refresh", "sub": "user-1"}
        result = await get_optional_user(_make_credentials())
        assert result is None

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.get_user_by_id")
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_valid_token_returns_user(self, mock_decode, mock_get_user) -> None:
        mock_decode.return_value = {"type": "access", "sub": "user-1"}
        mock_get_user.return_value = {
            "id": "user-1",
            "email": "test@example.com",
            "display_name": "Test",
            "created_at": "2025-01-01T00:00:00Z",
        }
        result = await get_optional_user(_make_credentials())
        assert result is not None
        assert result["id"] == "user-1"

    @pytest.mark.asyncio
    @patch("src.gateway.auth.middleware.get_user_by_id")
    @patch("src.gateway.auth.middleware.decode_token")
    async def test_user_not_found_returns_none(self, mock_decode, mock_get_user) -> None:
        mock_decode.return_value = {"type": "access", "sub": "user-999"}
        mock_get_user.return_value = None
        result = await get_optional_user(_make_credentials())
        assert result is None


# ---------------------------------------------------------------------------
# verify_thread_ownership
# ---------------------------------------------------------------------------
class TestVerifyThreadOwnership:
    """Tests for the verify_thread_ownership helper."""

    @patch("src.gateway.auth.ownership.claim_thread")
    def test_owned_thread_succeeds(self, mock_claim) -> None:
        mock_claim.return_value = True
        verify_thread_ownership("thread-1", "user-1")  # Should not raise

    @patch("src.gateway.auth.ownership.claim_thread")
    def test_not_owned_raises_403(self, mock_claim) -> None:
        mock_claim.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            verify_thread_ownership("thread-1", "user-1")
        assert exc_info.value.status_code == 403

    @patch("src.gateway.auth.ownership.claim_thread")
    def test_lazy_claim_unclaimed(self, mock_claim) -> None:
        """claim_thread returns True for first claim (unclaimed thread)."""
        mock_claim.return_value = True
        verify_thread_ownership("new-thread", "user-1")
        mock_claim.assert_called_once_with("new-thread", "user-1")
