import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class TestCase(Base):
    __tablename__ = "test_cases"

    test_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("problems.problem_id", ondelete="CASCADE"), nullable=False
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_output: Mapped[str] = mapped_column(Text, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
