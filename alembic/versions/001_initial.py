"""001_initial

Create all MVP entities: users, problems, test_cases, submissions.

Revision ID: 001
Revises: None
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # --- problems ---
    op.create_table(
        "problems",
        sa.Column(
            "problem_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(256), unique=True, nullable=False),
        sa.Column("difficulty", sa.String(16), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=False),
        sa.Column("code_stub", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_problems_tags",
        "problems",
        ["tags"],
        postgresql_using="gin",
    )

    # --- test_cases ---
    op.create_table(
        "test_cases",
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "problem_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("problems.problem_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=False),
        sa.Column(
            "is_public", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "order_index", sa.Integer(), nullable=False, server_default="0"
        ),
    )

    # --- submissions ---
    op.create_table(
        "submissions",
        sa.Column(
            "submission_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "problem_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("problems.problem_id"),
            nullable=False,
        ),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column(
            "verdict", sa.String(32), nullable=False, server_default="Pending"
        ),
        sa.Column("runtime_ms", sa.Integer(), nullable=True),
        sa.Column("memory_kb", sa.Integer(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
    )
    op.create_index("ix_submissions_user_id", "submissions", ["user_id"])
    op.create_index("ix_submissions_problem_id", "submissions", ["problem_id"])
    op.create_index(
        "ix_submissions_idempotency_key", "submissions", ["idempotency_key"]
    )
    op.create_index(
        "ix_submissions_user_submitted",
        "submissions",
        ["user_id", "submitted_at"],
    )


def downgrade() -> None:
    op.drop_table("submissions")
    op.drop_table("test_cases")
    op.drop_index("ix_problems_tags", table_name="problems")
    op.drop_table("problems")
    op.drop_table("users")
