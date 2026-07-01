"""Submission request/response schemas."""

from datetime import datetime

from pydantic import BaseModel


class CreateSubmissionRequest(BaseModel):
    problem_id: str
    language: str
    source_code: str


class SubmissionResponse(BaseModel):
    submission_id: str
    problem_id: str
    user_id: str
    language: str
    verdict: str
    runtime_ms: int | None = None
    memory_kb: int | None = None
    source_code: str
    submitted_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class SubmissionListItem(BaseModel):
    submission_id: str
    problem_id: str
    language: str
    verdict: str
    runtime_ms: int | None = None
    memory_kb: int | None = None
    submitted_at: datetime

    model_config = {"from_attributes": True}


class SubmissionListResponse(BaseModel):
    items: list[SubmissionListItem]
    total: int
    page: int
    limit: int
