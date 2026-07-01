"""Submission service: create, retrieve, list submissions."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.problem import Problem
from ..models.submission import Submission
from ..models.user import User

SUPPORTED_LANGUAGES = {"python3"}


def _compute_idempotency_key(
    user_id: uuid.UUID, problem_id: uuid.UUID, source_code: str
) -> str:
    """Compute a deterministic idempotency key for submission dedup."""
    raw = f"{user_id}|{problem_id}|{source_code}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_submission(
    session: AsyncSession,
    user: User,
    *,
    problem_id: str,
    language: str,
    source_code: str,
) -> dict:
    """Create a new submission. Validates language and problem existence.

    Returns a dict with the created submission data (verdict=Pending).
    """
    # Validate language
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": f"Unsupported language: {language}",
                "supported_languages": sorted(SUPPORTED_LANGUAGES),
            },
        )

    # Validate problem exists
    try:
        problem_uuid = uuid.UUID(problem_id)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Problem not found", "problem_id": problem_id},
        ) from err

    prob_result = await session.execute(
        select(Problem).where(Problem.problem_id == problem_uuid)
    )
    problem = prob_result.scalar_one_or_none()
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Problem not found", "problem_id": problem_id},
        )

    # Check idempotency: same user + problem + source_code within 30s
    idempotency_key = _compute_idempotency_key(user.user_id, problem_uuid, source_code)
    window_start = datetime.now(UTC) - timedelta(seconds=30)

    existing_result = await session.execute(
        select(Submission).where(
            Submission.idempotency_key == idempotency_key,
            Submission.submitted_at >= window_start,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Duplicate submission",
                "submission_id": str(existing.submission_id),
            },
        )

    submission = Submission(
        user_id=user.user_id,
        problem_id=problem_uuid,
        language=language,
        source_code=source_code,
        verdict="Pending",
        idempotency_key=idempotency_key,
    )
    session.add(submission)
    await session.commit()
    await session.refresh(submission)

    return {
        "submission_id": str(submission.submission_id),
        "problem_id": str(submission.problem_id),
        "user_id": str(submission.user_id),
        "language": submission.language,
        "verdict": submission.verdict,
        "runtime_ms": submission.runtime_ms,
        "memory_kb": submission.memory_kb,
        "source_code": submission.source_code,
        "submitted_at": submission.submitted_at,
        "completed_at": submission.completed_at,
    }


async def get_submission(
    session: AsyncSession,
    submission_id: uuid.UUID,
    requesting_user: User,
) -> dict | None:
    """Get a submission by ID. Enforces ownership: 403 if not owner."""
    result = await session.execute(
        select(Submission).where(Submission.submission_id == submission_id)
    )
    submission = result.scalar_one_or_none()

    if submission is None:
        return None

    if submission.user_id != requesting_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this submission",
        )

    return {
        "submission_id": str(submission.submission_id),
        "problem_id": str(submission.problem_id),
        "user_id": str(submission.user_id),
        "language": submission.language,
        "verdict": submission.verdict,
        "runtime_ms": submission.runtime_ms,
        "memory_kb": submission.memory_kb,
        "source_code": submission.source_code,
        "submitted_at": submission.submitted_at,
        "completed_at": submission.completed_at,
    }


async def list_submissions(
    session: AsyncSession,
    user: User,
    *,
    problem_id: uuid.UUID,
    page: int = 1,
    limit: int = 50,
) -> dict:
    """List user's submissions for a specific problem, ordered by most recent first."""
    query = (
        select(Submission)
        .where(
            Submission.user_id == user.user_id,
            Submission.problem_id == problem_id,
        )
        .order_by(Submission.submitted_at.desc())
    )
    count_query = select(func.count(Submission.submission_id)).where(
        Submission.user_id == user.user_id,
        Submission.problem_id == problem_id,
    )

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    submissions = result.scalars().all()

    items = [
        {
            "submission_id": str(s.submission_id),
            "problem_id": str(s.problem_id),
            "language": s.language,
            "verdict": s.verdict,
            "runtime_ms": s.runtime_ms,
            "memory_kb": s.memory_kb,
            "submitted_at": s.submitted_at,
        }
        for s in submissions
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
    }
