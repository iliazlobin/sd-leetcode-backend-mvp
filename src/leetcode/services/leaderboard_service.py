"""Leaderboard service: compute global ranking from accepted submissions."""

import json

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.submission import Submission
from ..models.user import User

LEADERBOARD_CACHE_KEY = "leaderboard:global"
LEADERBOARD_CACHE_TTL = 30  # seconds


async def get_leaderboard(
    session: AsyncSession,
    redis_client,
    *,
    page: int = 1,
    limit: int = 100,
) -> dict:
    """Get global leaderboard ranked by distinct problems solved.

    Tie-break: earlier last_solved_at ranks higher.
    Uses Redis cache-aside with 30s TTL.
    """
    # Try cache first
    if redis_client is not None:
        try:
            cached = await redis_client.get(LEADERBOARD_CACHE_KEY)
            if cached is not None:
                try:
                    data = json.loads(cached)
                    entries = data["entries"]
                    total = data["total"]
                    # Slice for pagination
                    offset = (page - 1) * limit
                    paged_entries = entries[offset : offset + limit]
                    return {
                        "entries": paged_entries,
                        "total": total,
                        "page": page,
                        "limit": limit,
                    }
                except (json.JSONDecodeError, KeyError):
                    pass
        except Exception:
            # Redis may be unavailable; fall through to DB query
            pass

    # Compute leaderboard from DB
    query = (
        select(
            User.username,
            func.count(func.distinct(Submission.problem_id)).label("solved"),
            func.max(Submission.completed_at).label("last_solved"),
        )
        .join(Submission, User.user_id == Submission.user_id)
        .where(Submission.verdict == "Accepted")
        .group_by(User.user_id, User.username)
        .order_by(desc("solved"), "last_solved")
    )

    result = await session.execute(query)
    rows = result.all()

    all_entries = [
        {
            "username": row.username,
            "problems_solved": row.solved,
            "last_solved_at": row.last_solved.isoformat() if row.last_solved else None,
        }
        for row in rows
    ]
    total = len(all_entries)

    # Cache full result
    if redis_client is not None:
        try:
            cache_data = json.dumps({"entries": all_entries, "total": total})
            await redis_client.setex(LEADERBOARD_CACHE_KEY, LEADERBOARD_CACHE_TTL, cache_data)
        except Exception:
            pass

    # Slice for pagination
    offset = (page - 1) * limit
    paged_entries = all_entries[offset : offset + limit]

    return {
        "entries": paged_entries,
        "total": total,
        "page": page,
        "limit": limit,
    }


async def invalidate_leaderboard_cache(redis_client) -> None:
    """Invalidate the leaderboard cache (called after an Accepted verdict)."""
    if redis_client is not None:
        try:
            await redis_client.delete(LEADERBOARD_CACHE_KEY)
        except Exception:
            pass
