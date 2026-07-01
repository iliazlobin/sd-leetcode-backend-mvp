import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Submission(Base):
    __tablename__ = "submissions"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id"), nullable=False, index=True
    )
    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("problems.problem_id"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(
        String(32), nullable=False, default="Pending"
    )
    runtime_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
