"""FR-5: Get submission verdict.

GET /submissions/{submission_id}
→ 200 with verdict details (verdict, runtime_ms, memory_kb).
Unknown submission → 404. Cross-user access → 403. Own submission → 200.
"""

import uuid

from verify.acceptance.conftest import (
    assert_200,
    assert_401,
    assert_403,
    assert_404,
    create_problem,
    poll_verdict,
    submit_solution,
)


def test_get_submission_own_pending(client, admin_headers, user_headers):
    """GET /submissions/{id} for own submission → 200 with verdict=Pending initially."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1 2", "expected_output": "3", "is_public": True},
        ],
    )
    sub = submit_solution(
        client, user_headers,
        problem_id=prob["problem_id"],
        source_code="x = input().split()\nprint(int(x[0]) + int(x[1]))\n",
    )

    r = client.get(f"/submissions/{sub['submission_id']}", headers=user_headers)
    body = assert_200(r)

    assert body["submission_id"] == sub["submission_id"]
    assert body["problem_id"] == prob["problem_id"]
    assert body["language"] == "python3"
    assert body["verdict"] in ("Pending", "Running", "Accepted")
    assert body["user_id"] is not None
    assert "source_code" in body
    assert "submitted_at" in body


def test_get_submission_own_final_verdict(client, admin_headers, user_headers):
    """After judge runs, GET /submissions/{id} → 200 with final verdict and runtime_ms/memory_kb."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1 2", "expected_output": "3", "is_public": True},
        ],
    )
    sub = submit_solution(
        client, user_headers,
        problem_id=prob["problem_id"],
        source_code="x = input().split()\nprint(int(x[0]) + int(x[1]))\n",
    )

    # Poll until judge finishes
    final = poll_verdict(client, user_headers, sub["submission_id"], timeout_seconds=15)

    assert final["verdict"] not in ("Pending", "Running"), \
        f"Expected final verdict, got {final['verdict']}"
    assert final["verdict"] == "Accepted"
    assert final["runtime_ms"] is not None
    assert final["memory_kb"] is not None
    assert final["completed_at"] is not None


def test_get_submission_unknown_404(client, user_headers):
    """GET /submissions/{nonexistent_id} → 404."""
    fake_id = str(uuid.uuid4())
    r = client.get(f"/submissions/{fake_id}", headers=user_headers)
    assert_404(r)


def test_get_submission_cross_user_403(client, admin_headers, user_headers, user2_headers):
    """User A cannot view User B's submission → 403."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1", "expected_output": "1", "is_public": True},
        ],
    )
    # User 1 submits
    sub = submit_solution(
        client, user_headers,
        problem_id=prob["problem_id"],
        source_code="print(1)\n",
    )

    # User 2 tries to view User 1's submission
    r = client.get(f"/submissions/{sub['submission_id']}", headers=user2_headers)
    assert_403(r)


def test_get_submission_unauthenticated_401(client, admin_headers, user_headers):
    """GET /submissions/{id} without auth → 401."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1", "expected_output": "1", "is_public": True},
        ],
    )
    sub = submit_solution(
        client, user_headers,
        problem_id=prob["problem_id"],
        source_code="print(1)\n",
    )

    r = client.get(f"/submissions/{sub['submission_id']}")
    assert_401(r)
