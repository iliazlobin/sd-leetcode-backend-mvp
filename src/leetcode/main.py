import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from .database import Base, _get_engine, _get_redis, _get_session_factory
from .routers import auth, health, leaderboard, problems, submissions


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Any:
    # Create tables for dev convenience (PostgreSQL — models use postgresql.UUID/ARRAY).
    # Production uses Alembic migrations via docker compose.
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Start judge worker as background task
    from judge.worker import run_judge_loop
    session_factory = _get_session_factory()
    redis_client = _get_redis()
    judge_task = asyncio.create_task(run_judge_loop(session_factory, redis_client))
    
    yield
    
    # Shutdown judge worker
    judge_task.cancel()
    try:
        await judge_task
    except asyncio.CancelledError:
        pass
    
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="LeetCode MVP",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(problems.router)
    app.include_router(submissions.router)
    app.include_router(leaderboard.router)
    return app


app = create_app()
