"""002_seed_users

Seed admin and regular users with known passwords for acceptance tests.

Revision ID: 002
Revises: 001
Create Date: 2026-06-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO users (username, password_hash, role) VALUES
        ('admin', '$2b$12$Xk4/Zsei//ufzbDQhb/5I.HP/DL4M36Zu2hfNoMQQZ73E5wLGqJrG', 'admin'),
        ('alice', '$2b$12$IYuqeuIilqvjOfLFSftJL.rUxrBNsXbhl9CTQKlU8.eZZx2ljAutG', 'user'),
        ('bob',   '$2b$12$0BuwWf70uDDmctGES6laAukIlwSrSkxIxaYl5DI8Iz8u5p8VFA/qW', 'user')
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE username IN ('admin', 'alice', 'bob')")
