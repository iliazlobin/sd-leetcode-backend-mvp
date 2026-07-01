"""Unit tests for submission service."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from leetcode.models.problem import Problem
from leetcode.models.submission import Submission
from leetcode.models.user import User
from leetcode.services import submission_service


def make_user() -> User:
    return User(
        user_id=uuid.uuid4(),
        username="alice",
        password_hash="...",
        role="user",
    )


def make_admin() -> User:
    return User(
        user_id=uuid.uuid4(),
        username="admin",
        password_hash="...",
        role="admin",
    )


def make_problem() -> Problem:
    return Problem(
        problem_id=uuid.uuid4(),
        title="Test",
        difficulty="Easy",
        tags=["arrays"],
        description="desc",
        constraints="none",
        code_stub="",
        created_by=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_create_submission_unsupported_language():
    user = make_user()
    session = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await submission_service.create_submission(
            session, user,
            problem_id=str(uuid.uuid4()),
            language="brainfuck",
            source_code="code",
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_submission_problem_not_found():
    user = make_user()
    session = AsyncMock()

    # Mock problem query returns None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await submission_service.create_submission(
            session, user,
            problem_id=str(uuid.uuid4()),
            language="python3",
            source_code="code",
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_submission_cross_user_403():
    user_a = User(user_id=uuid.uuid4(), username="alice", password_hash="...", role="user")
    user_b = User(user_id=uuid.uuid4(), username="bob", password_hash="...", role="user")

    submission = Submission(
        submission_id=uuid.uuid4(),
        user_id=user_a.user_id,
        problem_id=uuid.uuid4(),
        language="python3",
        source_code="code",
        verdict="Accepted",
    )

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = submission
    session.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await submission_service.get_submission(session, submission.submission_id, user_b)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_submission_not_found():
    user = make_user()
    session = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    result = await submission_service.get_submission(session, uuid.uuid4(), user)
    assert result is None


@pytest.mark.asyncio
async def test_list_submissions_empty():
    user = make_user()
    session = AsyncMock()

    mock_count = MagicMock()
    mock_count.scalar.return_value = 0
    mock_items = MagicMock()
    mock_items.all.return_value = []
    mock_items_result = MagicMock()
    mock_items_result.scalars.return_value = mock_items
    session.execute.side_effect = [mock_count, mock_items_result]

    result = await submission_service.list_submissions(
        session, user, problem_id=uuid.uuid4(), page=1, limit=50
    )
    assert result["total"] == 0
    assert result["items"] == []
