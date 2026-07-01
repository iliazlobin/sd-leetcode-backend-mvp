"""FR-3: Get problem by ID.

GET /problems/{problem_id} → 200 with full problem resource including public test cases.
GET /problems/{nonexistent_id} → 404.
"""

import uuid

from verify.acceptance.conftest import (
    assert_200,
    assert_404,
    create_problem,
)


def test_get_problem_found(client, admin_headers):
    """GET /problems/{valid_id} → 200 with description, constraints, code_stub, and public test cases."""
    title = f"Get By ID Test {uuid.uuid4().hex[:8]}"
    created = create_problem(
        client, admin_headers,
        title=title,
        difficulty="Medium",
        tags=["strings"],
        description="Reverse a string.",
        constraints="1 <= len(s) <= 100",
        code_stub="def reverse(s):\n    pass\n",
        test_cases=[
            {"input": "hello", "expected_output": "olleh", "is_public": True},
            {"input": "world", "expected_output": "dlrow", "is_public": False},
        ],
    )
    problem_id = created["problem_id"]

    r = client.get(f"/problems/{problem_id}")
    body = assert_200(r)

    assert body["problem_id"] == problem_id
    assert body["title"] == title
    assert body["difficulty"] == "Medium"
    assert body["tags"] == ["strings"]
    assert body["description"] == "Reverse a string."
    assert body["constraints"] == "1 <= len(s) <= 100"
    assert body["code_stub"] == "def reverse(s):\n    pass\n"
    assert "created_at" in body

    # Only public test cases should be included
    assert "test_cases" in body
    assert len(body["test_cases"]) == 1, \
        f"Expected 1 public test case, got {len(body['test_cases'])}"
    tc = body["test_cases"][0]
    assert tc["input"] == "hello"
    assert tc["expected_output"] == "olleh"
    assert "test_case_id" in tc
    assert "order_index" in tc


def test_get_problem_not_found_404(client):
    """GET /problems/{nonexistent_id} → 404."""
    fake_id = str(uuid.uuid4())
    r = client.get(f"/problems/{fake_id}")
    assert_404(r)


def test_get_problem_all_test_cases_public(client, admin_headers):
    """When all test cases are public, all are returned."""
    created = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        tags=["basics"],
        description="Add two numbers.",
        constraints="N/A",
        code_stub="def add(a, b):\n    pass\n",
        test_cases=[
            {"input": "1 2", "expected_output": "3", "is_public": True},
            {"input": "5 5", "expected_output": "10", "is_public": True},
        ],
    )

    r = client.get(f"/problems/{created['problem_id']}")
    body = assert_200(r)

    assert len(body["test_cases"]) == 2
