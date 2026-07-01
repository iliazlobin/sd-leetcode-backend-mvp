"""Leaderboard request/response schemas."""

from datetime import datetime

from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    username: str
    problems_solved: int
    last_solved_at: datetime | None = None


class LeaderboardResponse(BaseModel):
    entries: list[LeaderboardEntry]
    total: int
    page: int
    limit: int
