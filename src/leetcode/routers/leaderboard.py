"""Leaderboard router: GET /leaderboard."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import _get_redis, get_session
from ..schemas.leaderboard import LeaderboardResponse
from ..services import leaderboard_service

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("", response_model=LeaderboardResponse)
async def get_leaderboard(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Get global leaderboard ranked by distinct problems solved."""
    redis_client = _get_redis()
    return await leaderboard_service.get_leaderboard(
        session,
        redis_client,
        page=page,
        limit=limit,
    )
