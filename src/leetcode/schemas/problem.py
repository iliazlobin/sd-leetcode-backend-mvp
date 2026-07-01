"""Problem request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class TestCaseInput(BaseModel):
    input: str
    expected_output: str
    is_public: bool = False


class CreateProblemRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    difficulty: str = Field(..., pattern=r"^(Easy|Medium|Hard)$")
    tags: list[str] = Field(default_factory=list)
    description: str
    constraints: str
    code_stub: str
    test_cases: list[TestCaseInput] = Field(..., min_length=1)


class ProblemResponse(BaseModel):
    problem_id: str
    title: str
    difficulty: str
    tags: list[str]
    description: str
    constraints: str
    code_stub: str
    test_case_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ProblemListItem(BaseModel):
    problem_id: str
    title: str
    difficulty: str
    tags: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ProblemListResponse(BaseModel):
    items: list[ProblemListItem]
    total: int
    page: int
    limit: int


class PublicTestCase(BaseModel):
    test_case_id: str
    input: str
    expected_output: str
    order_index: int

    model_config = {"from_attributes": True}


class ProblemDetailResponse(BaseModel):
    problem_id: str
    title: str
    difficulty: str
    tags: list[str]
    description: str
    constraints: str
    code_stub: str
    test_cases: list[PublicTestCase]
    created_at: datetime

    model_config = {"from_attributes": True}
