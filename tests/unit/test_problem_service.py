"""Unit tests for problem service."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from leetcode.models.problem import Problem
from leetcode.models.user import User
from leetcode.services import problem_service


def make_admin_user() -> User:
    return User(
        user_id=uuid.uuid4(),
        username="admin",
        password_hash="...",
        role="admin",
    )


def make_regular_user() -> User:
    return User(
        user_id=uuid.uuid4(),
        username="alice",
        password_hash="...",
        role="user",
    )


@pytest.mark.asyncio
async def test_create_problem_non_admin_403():
    user = make_regular_user()
    session = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await problem_service.create_problem(
            session, user,
            title="Test",
            difficulty="Easy",
            tags=["arrays"],
            description="desc",
            constraints="none",
            code_stub="def solve():\n    pass\n",
            test_cases=[{"input": "1", "expected_output": "1", "is_public": True}],
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_problem_duplicate_title_409():
    user = make_admin_user()
    session = AsyncMock()

    # Mock existing problem with same title
    existing = Problem(title="Test", difficulty="Easy", tags=[], description="x", constraints="x", code_stub="x", created_by=user.user_id)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    session.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await problem_service.create_problem(
            session, user,
            title="Test",
            difficulty="Easy",
            tags=["arrays"],
            description="desc",
            constraints="none",
            code_stub="def solve():\n    pass\n",
            test_cases=[{"input": "1", "expected_output": "1", "is_public": True}],
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_list_problems_pagination():
    session = AsyncMock()

    # Mock count
    mock_count = MagicMock()
    mock_count.scalar.return_value = 10
    mock_items = MagicMock()
    mock_items.all.return_value = []
    mock_items_result = MagicMock()
    mock_items_result.scalars.return_value = mock_items

    session.execute.side_effect = [mock_count, mock_items_result]

    result = await problem_service.list_problems(session, page=1, limit=20)
    assert result["total"] == 10
    assert result["page"] == 1
    assert result["limit"] == 20
    assert result["items"] == []


@pytest.mark.asyncio
async def test_list_problems_with_filters():
    session = AsyncMock()

    mock_count = MagicMock()
    mock_count.scalar.return_value = 3
    mock_items = MagicMock()
    mock_items.all.return_value = []
    mock_items_result = MagicMock()
    mock_items_result.scalars.return_value = mock_items

    session.execute.side_effect = [mock_count, mock_items_result]

    result = await problem_service.list_problems(
        session, page=1, limit=10, difficulty="Hard", tag="dp"
    )
    assert result["total"] == 3


@pytest.mark.asyncio
async def test_get_problem_not_found():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    result = await problem_service.get_problem(session, uuid.uuid4())
    assert result is None
