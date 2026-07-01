#!/usr/bin/env python3
"""Seed users directly into the database for sandbox testing."""

import asyncio
import sys

sys.path.insert(0, "src")

# Import models so Base.metadata knows about them
import leetcode.models  # noqa: F401
from leetcode.database import Base, _get_engine, _get_session_factory
from leetcode.models.user import User


async def seed():
    engine = _get_engine()

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = _get_session_factory()
    async with factory() as session:
        from sqlalchemy import func, select
        result = await session.execute(select(func.count(User.user_id)))
        count = result.scalar()
        if count > 0:
            print(f"Users already exist ({count} rows), skipping seed.")
            await engine.dispose()
            return

        session.add_all([
            User(
                username="admin",
                password_hash="$2b$12$Xk4/Zsei//ufzbDQhb/5I.HP/DL4M36Zu2hfNoMQQZ73E5wLGqJrG",
                role="admin",
            ),
            User(
                username="alice",
                password_hash="$2b$12$IYuqeuIilqvjOfLFSftJL.rUxrBNsXbhl9CTQKlU8.eZZx2ljAutG",
                role="user",
            ),
            User(
                username="bob",
                password_hash="$2b$12$0BuwWf70uDDmctGES6laAukIlwSrSkxIxaYl5DI8Iz8u5p8VFA/qW",
                role="user",
            ),
        ])
        await session.commit()

    print("Seed complete.")
    await engine.dispose()


asyncio.run(seed())
