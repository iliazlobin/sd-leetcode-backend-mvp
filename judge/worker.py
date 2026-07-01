"""Judge worker: polling loop that claims and judges Pending submissions."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from leetcode.services.judge_service import run_judge_cycle

logger = logging.getLogger("judge.worker")


async def run_judge_loop(
    session_factory: async_sessionmaker,
    redis_client=None,
    poll_interval: float = 0.5,
    max_polls: int | None = None,
) -> None:
    """Run the judge polling loop.

    Continuously polls the submissions table for Pending submissions,
    executes them, and writes verdicts back. Runs forever unless max_polls
    is set (for testing).

    Args:
        session_factory: SQLAlchemy async session factory.
        redis_client: Redis client for cache invalidation.
        poll_interval: Seconds between polls when idle.
        max_polls: If set, stop after this many polls (for testing).
    """
    polls = 0
    while max_polls is None or polls < max_polls:
        try:
            work_done = await run_judge_cycle(session_factory, redis_client)
            if not work_done:
                await asyncio.sleep(poll_interval)
        except Exception:
            logger.exception("Judge cycle failed; retrying after interval")
            await asyncio.sleep(poll_interval)

        polls += 1
