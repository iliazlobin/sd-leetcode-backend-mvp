"""FR-4: Submit solution.

POST /submissions {problem_id, language, source_code}
→ 201 with submission resource and verdict="Pending".
Unknown problem → 404. Unsupported language → 422. Missing fields → 422. Unauthenticated → 401.
"""

import uuid

from verify.acceptance.conftest import (
    assert_401,
    assert_404,
    assert_409,
    assert_422,
    create_problem,
    submit_solution,
)


def test_submit_solution_success(client, admin_headers, user_headers):
    """POST /submissions with valid data → 201 Pending."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        code_stub="def twoSum(nums, target):\n    pass\n",
    )

    body = submit_solution(
        client, user_headers,
        problem_id=prob["problem_id"],
        source_code="def twoSum(nums, target):\n    return [0, 1]\n",
    )

    assert "submission_id" in body
    assert body["problem_id"] == prob["problem_id"]
    assert body["language"] == "python3"
    assert body["verdict"] == "Pending"
    assert "submitted_at" in body


def test_submit_solution_unknown_problem_404(client, user_headers):
    """POST /submissions with nonexistent problem_id → 404."""
    fake_problem_id = str(uuid.uuid4())
    r = client.post("/submissions", json={
        "problem_id": fake_problem_id,
        "language": "python3",
        "source_code": "print('hello')\n",
    }, headers=user_headers)
    assert_404(r)


def test_submit_solution_unsupported_language_422(client, admin_headers, user_headers):
    """POST /submissions with unsupported language → 422."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
    )

    r = client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "brainfuck",
        "source_code": "+++[>+++<-]>.",
    }, headers=user_headers)
    body = assert_422(r)
    # Should mention supported languages
    assert "supported_languages" in body or "python3" in str(body).lower()


def test_submit_solution_missing_fields_422(client, admin_headers, user_headers):
    """POST /submissions with missing required fields → 422."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
    )

    # Missing source_code
    r = client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
    }, headers=user_headers)
    assert_422(r)

    # Missing problem_id
    r = client.post("/submissions", json={
        "language": "python3",
        "source_code": "print('hi')\n",
    }, headers=user_headers)
    assert_422(r)

    # Missing language
    r = client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "source_code": "print('hi')\n",
    }, headers=user_headers)
    assert_422(r)


def test_submit_solution_unauthenticated_401(client, admin_headers):
    """POST /submissions without auth → 401."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
    )

    r = client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": "print('hi')\n",
    })
    assert_401(r)


def test_submit_solution_duplicate_409(client, admin_headers, user_headers):
    """POST /submissions with identical code within 30s → 409 Conflict."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
    )
    source = "def twoSum(nums, target):\n    return [0, 1]\n"

    # First submissions → 201
    first = submit_solution(client, user_headers, prob["problem_id"], source)
    assert first["verdict"] == "Pending"

    # Duplicate within 30s → 409
    r = client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": source,
    }, headers=user_headers)
    assert_409(r)
