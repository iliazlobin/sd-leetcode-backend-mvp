"""FR-7: Submission history.

GET /submissions?problem_id={id}&page=1&limit=50
→ 200 with paginated list of user's submissions for that problem.
Ordered by submitted_at DESC. Unauthenticated → 401. No submissions → 200 with empty items.
"""


from verify.acceptance.conftest import (
    assert_200,
    assert_401,
    create_problem,
    submit_solution,
)


def test_submission_history_paginated(client, admin_headers, user_headers):
    """GET /submissions?problem_id={id} → 200 with paginated user's submissions."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1 2", "expected_output": "3", "is_public": True},
        ],
    )
    source = "x = input().split()\nprint(int(x[0]) + int(x[1]))\n"

    # Submit two solutions
    sub1 = submit_solution(client, user_headers, prob["problem_id"], source)

    source2 = "import sys\na, b = map(int, sys.stdin.readline().split())\nprint(a + b)\n"
    sub2 = submit_solution(client, user_headers, prob["problem_id"], source2)

    r = client.get("/submissions", params={
        "problem_id": prob["problem_id"],
        "page": 1,
        "limit": 50,
    }, headers=user_headers)
    body = assert_200(r)

    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body
    assert body["total"] >= 2
    assert len(body["items"]) >= 2

    # Should be ordered by submitted_at DESC → most recent first
    item_ids = [item["submission_id"] for item in body["items"]]
    # sub2 was submitted after sub1, so sub2 should appear first
    assert item_ids[0] == sub2["submission_id"], \
        f"Expected {sub2['submission_id']} first (most recent), got {item_ids[0]}"

    # Each item should have expected fields
    for item in body["items"]:
        assert "submission_id" in item
        assert "problem_id" in item
        assert item["problem_id"] == prob["problem_id"]
        assert "language" in item
        assert "verdict" in item
        assert "submitted_at" in item


def test_submission_history_empty(client, admin_headers, user_headers):
    """GET /submissions?problem_id={id} for problem with no submissions → 200 empty."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1", "expected_output": "1", "is_public": True},
        ],
    )
    # User has not submitted to this problem

    r = client.get("/submissions", params={
        "problem_id": prob["problem_id"],
    }, headers=user_headers)
    body = assert_200(r)

    assert body["items"] == []
    assert body["total"] == 0


def test_submission_history_other_user_not_visible(client, admin_headers, user_headers, user2_headers):
    """GET /submissions?problem_id={id} as user A → only shows user A's submissions."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1", "expected_output": "1", "is_public": True},
        ],
    )

    # User 1 submits
    submit_solution(client, user_headers, prob["problem_id"], "print(1)\n")

    # User 2 submits
    submit_solution(client, user2_headers, prob["problem_id"], "print(1)\n")

    # User 1 checks history → should only see their own
    r = client.get("/submissions", params={
        "problem_id": prob["problem_id"],
    }, headers=user_headers)
    body = assert_200(r)

    assert body["total"] == 1, \
        f"Expected 1 submission (own only), got {body['total']}"


def test_submission_history_unauthenticated_401(client, admin_headers, user_headers):
    """GET /submissions?problem_id={id} without auth → 401."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1", "expected_output": "1", "is_public": True},
        ],
    )
    # Submit so problem has submissions
    submit_solution(client, user_headers, prob["problem_id"], "print(1)\n")

    r = client.get("/submissions", params={"problem_id": prob["problem_id"]})
    assert_401(r)


def test_submission_history_missing_problem_id_422(client, user_headers):
    """GET /submissions without problem_id → 422."""
    r = client.get("/submissions", headers=user_headers)
    # Should return 422 for missing required query param
    assert r.status_code == 422, \
        f"Expected 422 for missing problem_id, got {r.status_code}: {r.text}"
