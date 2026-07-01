#!/usr/bin/env python3
"""Judge runner: entry point for the judge worker process.

Usage:
    python -m judge.runner

The judge runner reads DATABASE_URL and REDIS_URL from environment
and starts the polling loop.
"""

import asyncio
import logging
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from judge.worker import run_judge_loop
from leetcode.config import settings
from leetcode.database import _get_engine, _get_session_factory


def _get_redis():
    """Create a Redis client if available, else None."""
    try:
        import redis.asyncio as aioredis
        return aioredis.from_url(settings.redis_url)
    except Exception:
        return None


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger = logging.getLogger("judge.runner")

    logger.info("Starting judge worker...")
    logger.info(f"Database: {settings.database_url}")
    logger.info(f"Redis: {settings.redis_url}")

    session_factory = _get_session_factory()
    redis_client = _get_redis()

    try:
        await run_judge_loop(session_factory, redis_client)
    except KeyboardInterrupt:
        logger.info("Judge worker stopped by signal.")
    finally:
        engine = _get_engine()
        await engine.dispose()
        if redis_client:
            await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
