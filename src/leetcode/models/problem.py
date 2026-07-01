import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Problem(Base):
    __tablename__ = "problems"

    problem_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # "Easy" | "Medium" | "Hard"
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[str] = mapped_column(Text, nullable=False)
    code_stub: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
