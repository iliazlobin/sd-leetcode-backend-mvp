"""Problem service: CRUD for coding problems."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.problem import Problem
from ..models.test_case import TestCase
from ..models.user import User


async def create_problem(
    session: AsyncSession,
    user: User,
    *,
    title: str,
    difficulty: str,
    tags: list[str],
    description: str,
    constraints: str,
    code_stub: str,
    test_cases: list[dict],
) -> dict:
    """Create a new problem with test cases. Admin only.

    Returns a dict with the created problem data.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    # Check for duplicate title
    existing = await session.execute(
        select(Problem).where(Problem.title == title)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Problem with this title already exists",
        )

    problem = Problem(
        title=title,
        difficulty=difficulty,
        tags=tags,
        description=description,
        constraints=constraints,
        code_stub=code_stub,
        created_by=user.user_id,
    )
    session.add(problem)
    await session.flush()

    for idx, tc in enumerate(test_cases):
        test_case = TestCase(
            problem_id=problem.problem_id,
            input_text=tc["input"],
            expected_output=tc["expected_output"],
            is_public=tc.get("is_public", False),
            order_index=idx,
        )
        session.add(test_case)

    await session.commit()
    await session.refresh(problem)

    return {
        "problem_id": str(problem.problem_id),
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": problem.tags,
        "description": problem.description,
        "constraints": problem.constraints,
        "code_stub": problem.code_stub,
        "test_case_count": len(test_cases),
        "created_at": problem.created_at,
    }


async def list_problems(
    session: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    difficulty: str | None = None,
    tag: str | None = None,
) -> dict:
    """List problems with pagination and optional filters."""
    query = select(Problem)
    count_query = select(func.count(Problem.problem_id))

    if difficulty is not None:
        query = query.where(Problem.difficulty == difficulty)
        count_query = count_query.where(Problem.difficulty == difficulty)

    if tag is not None:
        # Use PostgreSQL array-contains operator
        query = query.where(Problem.tags.contains([tag]))
        count_query = count_query.where(Problem.tags.contains([tag]))

    # Get total count
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    offset = (page - 1) * limit
    query = query.order_by(Problem.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    problems = result.scalars().all()

    items = [
        {
            "problem_id": str(p.problem_id),
            "title": p.title,
            "difficulty": p.difficulty,
            "tags": p.tags,
            "created_at": p.created_at,
        }
        for p in problems
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
    }


async def get_problem(session: AsyncSession, problem_id: uuid.UUID) -> dict | None:
    """Get a single problem by ID with public test cases only."""
    result = await session.execute(
        select(Problem).where(Problem.problem_id == problem_id)
    )
    problem = result.scalar_one_or_none()

    if problem is None:
        return None

    # Eager-load public test cases ordered by order_index
    tc_result = await session.execute(
        select(TestCase)
        .where(
            TestCase.problem_id == problem_id,
            TestCase.is_public == True,  # noqa: E712
        )
        .order_by(TestCase.order_index)
    )
    test_cases = tc_result.scalars().all()

    return {
        "problem_id": str(problem.problem_id),
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": problem.tags,
        "description": problem.description,
        "constraints": problem.constraints,
        "code_stub": problem.code_stub,
        "test_cases": [
            {
                "test_case_id": str(tc.test_case_id),
                "input": tc.input_text,
                "expected_output": tc.expected_output,
                "order_index": tc.order_index,
            }
            for tc in test_cases
        ],
        "created_at": problem.created_at,
    }
