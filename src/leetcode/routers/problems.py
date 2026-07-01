"""Problems router: POST /problems, GET /problems, GET /problems/{id}."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..database import get_session
from ..models.user import User
from ..schemas.problem import (
    CreateProblemRequest,
    ProblemDetailResponse,
    ProblemListResponse,
    ProblemResponse,
)
from ..services import problem_service

router = APIRouter(prefix="/problems", tags=["problems"])

VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}


@router.post("", response_model=ProblemResponse, status_code=201)
async def create_problem(
    body: CreateProblemRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Create a new coding problem (admin only)."""
    if body.difficulty not in VALID_DIFFICULTIES:
        allowed = ", ".join(sorted(VALID_DIFFICULTIES))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid difficulty: {body.difficulty}. Must be one of: {allowed}",
        )

    test_cases = [
        {
            "input": tc.input,
            "expected_output": tc.expected_output,
            "is_public": tc.is_public,
        }
        for tc in body.test_cases
    ]

    result = await problem_service.create_problem(
        session,
        user,
        title=body.title,
        difficulty=body.difficulty,
        tags=body.tags,
        description=body.description,
        constraints=body.constraints,
        code_stub=body.code_stub,
        test_cases=test_cases,
    )
    return result


@router.get("", response_model=ProblemListResponse)
async def list_problems(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    difficulty: str | None = Query(None),
    tag: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """List/search problems with pagination and optional filters."""
    if difficulty is not None and difficulty not in VALID_DIFFICULTIES:
        allowed = ", ".join(sorted(VALID_DIFFICULTIES))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid difficulty: {difficulty}. Must be one of: {allowed}",
        )

    return await problem_service.list_problems(
        session,
        page=page,
        limit=limit,
        difficulty=difficulty,
        tag=tag,
    )


@router.get("/{problem_id}", response_model=ProblemDetailResponse)
async def get_problem(
    problem_id: str,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Get a single problem by ID with public test cases."""
    try:
        pid = uuid.UUID(problem_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Problem not found",
        ) from None

    result = await problem_service.get_problem(session, pid)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found")
    return result
