"""FR-1: Create problem.

POST /problems {title, difficulty, tags, description, constraints, code_stub, test_cases}
→ 201 with problem resource.
Missing required fields → 422. Duplicate title → 409. Unauthenticated → 401. Non-admin → 403.
"""

import uuid

from verify.acceptance.conftest import (
    assert_401,
    assert_403,
    assert_409,
    assert_422,
    create_problem,
)


def test_create_problem_success(client, admin_headers):
    """Create a problem with all required fields → 201 with problem resource."""
    title = f"Two Sum {uuid.uuid4().hex[:8]}"
    body = create_problem(
        client, admin_headers,
        title=title,
        difficulty="Easy",
        tags=["arrays", "hash-table"],
        description="Find two numbers that add up to target.",
        constraints="2 <= len(nums) <= 10^4",
        code_stub="def twoSum(nums, target):\n    pass\n",
        test_cases=[
            {"input": "2 7 11 15\n9", "expected_output": "0 1", "is_public": True},
            {"input": "3 2 4\n6", "expected_output": "1 2", "is_public": False},
        ],
    )
    assert "problem_id" in body
    assert body["title"] == title
    assert body["difficulty"] == "Easy"
    assert body["tags"] == ["arrays", "hash-table"]
    assert body["description"] == "Find two numbers that add up to target."
    assert body["constraints"] == "2 <= len(nums) <= 10^4"
    assert body["code_stub"] == "def twoSum(nums, target):\n    pass\n"
    assert body["test_case_count"] == 2
    assert "created_at" in body


def test_create_problem_missing_title_422(client, admin_headers):
    """Missing required field 'title' → 422."""
    r = client.post("/problems", json={
        "difficulty": "Easy",
        "tags": ["arrays"],
        "description": "desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [{"input": "1", "expected_output": "1", "is_public": True}],
    }, headers=admin_headers)
    assert_422(r)


def test_create_problem_missing_test_cases_422(client, admin_headers):
    """Empty test_cases array → 422."""
    r = client.post("/problems", json={
        "title": f"No Tests Problem {uuid.uuid4().hex[:8]}",
        "difficulty": "Easy",
        "tags": ["arrays"],
        "description": "desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [],
    }, headers=admin_headers)
    assert_422(r)


def test_create_problem_duplicate_title_409(client, admin_headers):
    """Same title twice → 409 Conflict."""
    dup_title = f"Unique Sum {uuid.uuid4().hex[:8]}"
    create_problem(client, admin_headers, title=dup_title)

    r = client.post("/problems", json={
        "title": dup_title,
        "difficulty": "Hard",
        "tags": ["math"],
        "description": "Different desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [{"input": "1", "expected_output": "1", "is_public": True}],
    }, headers=admin_headers)
    assert_409(r)


def test_create_problem_unauthenticated_401(client):
    """No auth token → 401."""
    r = client.post("/problems", json={
        "title": f"No Auth Problem {uuid.uuid4().hex[:8]}",
        "difficulty": "Easy",
        "tags": ["arrays"],
        "description": "desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [{"input": "1", "expected_output": "1", "is_public": True}],
    })
    assert_401(r)


def test_create_problem_non_admin_403(client, user_headers):
    """Regular user (not admin) → 403."""
    r = client.post("/problems", json={
        "title": f"User Tries To Create {uuid.uuid4().hex[:8]}",
        "difficulty": "Easy",
        "tags": ["arrays"],
        "description": "desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [{"input": "1", "expected_output": "1", "is_public": True}],
    }, headers=user_headers)
    assert_403(r)
