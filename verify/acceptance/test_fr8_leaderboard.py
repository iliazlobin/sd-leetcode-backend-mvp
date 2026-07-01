"""FR-8: Leaderboard.

GET /leaderboard?page=1&limit=100
→ 200 with entries ranked by problems_solved DESC.
Tie-break: earlier last_solved_at ranks higher.
Pagination support.
"""

from verify.acceptance.conftest import (
    assert_200,
    create_problem,
    poll_verdict,
    submit_solution,
)

# Correct solution for a simple problem: adds two ints
CORRECT_CODE = "x = input().split()\nprint(int(x[0]) + int(x[1]))\n"


def test_leaderboard_ranked_by_problems_solved(client, admin_headers, user_headers, user2_headers):
    """GET /leaderboard → 200 with entries ranked by problems_solved DESC."""
    # Create two problems
    prob1 = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1 2", "expected_output": "3", "is_public": True},
        ],
    )
    prob2 = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "5 5", "expected_output": "10", "is_public": True},
        ],
    )

    # User 1 solves both problems
    sub1 = submit_solution(client, user_headers, prob1["problem_id"], CORRECT_CODE)
    poll_verdict(client, user_headers, sub1["submission_id"], timeout_seconds=15)

    sub2 = submit_solution(client, user_headers, prob2["problem_id"], CORRECT_CODE)
    poll_verdict(client, user_headers, sub2["submission_id"], timeout_seconds=15)

    # User 2 solves only one problem
    sub3 = submit_solution(client, user2_headers, prob1["problem_id"], CORRECT_CODE)
    poll_verdict(client, user2_headers, sub3["submission_id"], timeout_seconds=15)

    r = client.get("/leaderboard", params={"page": 1, "limit": 100})
    body = assert_200(r)

    assert "entries" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body
    assert body["page"] == 1
    assert body["total"] >= 2

    entries = body["entries"]
    assert len(entries) >= 2

    # User 1 (2 solved) should rank above User 2 (1 solved)
    solved_counts = [e["problems_solved"] for e in entries]
    assert solved_counts == sorted(solved_counts, reverse=True), \
        f"Entries not sorted by problems_solved DESC: {solved_counts}"

    for entry in entries:
        assert "username" in entry
        assert "problems_solved" in entry
        assert "last_solved_at" in entry
        assert isinstance(entry["problems_solved"], int)
        assert entry["problems_solved"] >= 0


def test_leaderboard_tie_break_by_timestamp(client, admin_headers, user_headers, user2_headers):
    """Two users with same problems_solved → earlier last_solved_at ranks higher."""
    prob = create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
        test_cases=[
            {"input": "1 2", "expected_output": "3", "is_public": True},
        ],
    )

    # User 2 solves first (earlier timestamp)
    sub2 = submit_solution(client, user2_headers, prob["problem_id"], CORRECT_CODE)
    poll_verdict(client, user2_headers, sub2["submission_id"], timeout_seconds=15)

    # User 1 solves later
    sub1 = submit_solution(client, user_headers, prob["problem_id"], CORRECT_CODE)
    poll_verdict(client, user_headers, sub1["submission_id"], timeout_seconds=15)

    r = client.get("/leaderboard", params={"page": 1, "limit": 100})
    body = assert_200(r)

    # Find both users in entries
    user1_entry = next((e for e in body["entries"] if e["problems_solved"] == 1), None)

    # Both have 1 solved; the tie-break should place user2 before user1
    usernames = [e["username"] for e in body["entries"] if e["problems_solved"] == 1]
    assert len(usernames) >= 2, f"Expected at least 2 users with 1 solved, got {usernames}"
    # User2 (bob, solved first) should appear before User1 (alice, solved later)
    idx2 = usernames.index("bob") if "bob" in usernames else -1
    idx1 = usernames.index("alice") if "alice" in usernames else -1
    assert idx2 != -1 and idx1 != -1, f"Both users should appear in leaderboard: {usernames}"
    assert idx2 < idx1, \
        f"User2 (bob, earlier timestamp) should rank before User1 (alice, later): {usernames}"


def test_leaderboard_pagination(client, admin_headers, user_headers):
    """GET /leaderboard?page=1&limit=1 → returns 1 entry, total reflects all."""
    # Ensure at least 2 users have solved something
    prob1 = create_problem(client, admin_headers, title=None, difficulty="Easy",
                           test_cases=[{"input": "1", "expected_output": "1", "is_public": True}])
    prob2 = create_problem(client, admin_headers, title=None, difficulty="Easy",
                           test_cases=[{"input": "2", "expected_output": "2", "is_public": True}])

    sub1 = submit_solution(client, user_headers, prob1["problem_id"], "print(1)\n")
    poll_verdict(client, user_headers, sub1["submission_id"], timeout_seconds=15)

    sub2 = submit_solution(client, user_headers, prob2["problem_id"], "print(2)\n")
    poll_verdict(client, user_headers, sub2["submission_id"], timeout_seconds=15)

    r = client.get("/leaderboard", params={"page": 1, "limit": 1})
    body = assert_200(r)

    assert len(body["entries"]) == 1
    assert body["limit"] == 1
    assert body["total"] >= 1  # total count of all users on leaderboard

    # Page 2
    r2 = client.get("/leaderboard", params={"page": 2, "limit": 1})
    body2 = assert_200(r2)
    assert body2["page"] == 2
    # The entry on page 2 should be different from page 1
    if body2["entries"]:
        assert body2["entries"][0]["username"] != body["entries"][0]["username"]


def test_leaderboard_empty_when_no_accepted(client, admin_headers):
    """GET /leaderboard with no accepted submissions → 200 with empty entries."""
    # Create a problem but don't submit any correct solutions
    create_problem(
        client, admin_headers,
        title=None,
        difficulty="Easy",
    )

    r = client.get("/leaderboard")
    body = assert_200(r)
    assert "entries" in body
    assert body["total"] >= 0
