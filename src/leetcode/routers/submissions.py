"""Submissions router: POST /submissions, GET /submissions/{id}, GET /submissions."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_session
from ..models.user import User
from ..schemas.submission import (
    CreateSubmissionRequest,
    SubmissionListResponse,
    SubmissionResponse,
)
from ..services import submission_service

router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.post("", response_model=SubmissionResponse, status_code=201)
async def create_submission(
    body: CreateSubmissionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Submit a solution for a problem."""
    return await submission_service.create_submission(
        session,
        user,
        problem_id=body.problem_id,
        language=body.language,
        source_code=body.source_code,
    )


@router.get("/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Get submission verdict and details (own submissions only)."""
    try:
        sid = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        ) from None

    result = await submission_service.get_submission(session, sid, user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )
    return result


@router.get("", response_model=SubmissionListResponse)
async def list_submissions(
    problem_id: str = Query(...),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """List user's submissions for a specific problem."""
    try:
        pid = uuid.UUID(problem_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid problem_id",
        ) from None

    return await submission_service.list_submissions(
        session,
        user,
        problem_id=pid,
        page=page,
        limit=limit,
    )
