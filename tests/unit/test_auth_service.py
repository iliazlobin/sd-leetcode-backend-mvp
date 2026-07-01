"""Unit tests for auth service."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from leetcode.models.user import User
from leetcode.services.auth_service import authenticate_user, hash_password, verify_password


def test_hash_and_verify_password():
    pw = "test123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed)
    assert not verify_password("wrong", hashed)


@pytest.mark.asyncio
async def test_authenticate_user_success():
    user_id = uuid.uuid4()
    pw = "secret123"
    pw_hash = hash_password(pw)
    user = User(
        user_id=user_id,
        username="testuser",
        password_hash=pw_hash,
        role="user",
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_session.execute.return_value = mock_result

    result = await authenticate_user(mock_session, "testuser", "secret123")
    assert result is not None
    returned_user, token = result
    assert returned_user.user_id == user_id
    assert returned_user.username == "testuser"
    assert token is not None
    assert len(token) > 0


@pytest.mark.asyncio
async def test_authenticate_user_wrong_password():
    pw_hash = hash_password("secret123")
    user = User(
        user_id=uuid.uuid4(),
        username="testuser",
        password_hash=pw_hash,
        role="user",
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_session.execute.return_value = mock_result

    result = await authenticate_user(mock_session, "testuser", "wrongpass")
    assert result is None


@pytest.mark.asyncio
async def test_authenticate_user_not_found():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    result = await authenticate_user(mock_session, "nonexistent", "password")
    assert result is None
