"""FR-2: List/search problems.

GET /problems?page=1&limit=20 → 200 with paginated results.
GET /problems?difficulty=Easy&tag=arrays → 200 with filtered results.
?difficulty=invalid → 422.
"""

from verify.acceptance.conftest import (
    assert_200,
    assert_422,
    create_problem,
)


def test_list_problems_pagination(client, admin_headers):
    """GET /problems with default pagination → 200 with items, total, page, limit."""
    # Create a few problems to ensure data exists
    create_problem(client, admin_headers, title=None, difficulty="Easy", tags=["arrays"])
    create_problem(client, admin_headers, title=None, difficulty="Medium", tags=["dp"])
    create_problem(client, admin_headers, title=None, difficulty="Hard", tags=["graphs"])

    r = client.get("/problems", params={"page": 1, "limit": 20})
    body = assert_200(r)

    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body
    assert body["page"] == 1
    assert body["limit"] == 20
    assert body["total"] >= 3
    assert len(body["items"]) >= 3

    # Each item should have expected fields
    for item in body["items"]:
        assert "problem_id" in item
        assert "title" in item
        assert "difficulty" in item
        assert "tags" in item
        assert "created_at" in item


def test_list_problems_filter_by_difficulty(client, admin_headers):
    """GET /problems?difficulty=Easy → only Easy problems returned."""
    create_problem(client, admin_headers, title=None, difficulty="Easy", tags=["arrays"])
    create_problem(client, admin_headers, title=None, difficulty="Hard", tags=["dp"])

    r = client.get("/problems", params={"difficulty": "Easy"})
    body = assert_200(r)

    for item in body["items"]:
        assert item["difficulty"] == "Easy", \
            f"Expected only Easy, got {item['difficulty']} for {item['title']}"
    assert body["total"] >= 1


def test_list_problems_filter_by_tag(client, admin_headers):
    """GET /problems?tag=arrays → only problems with 'arrays' tag returned."""
    create_problem(client, admin_headers, title=None, difficulty="Easy", tags=["arrays"])
    create_problem(client, admin_headers, title=None, difficulty="Medium", tags=["graphs"])

    r = client.get("/problems", params={"tag": "arrays"})
    body = assert_200(r)

    for item in body["items"]:
        assert "arrays" in item["tags"], \
            f"Expected 'arrays' in tags for {item['title']}, got {item['tags']}"
    assert body["total"] >= 1


def test_list_problems_combined_filters(client, admin_headers):
    """GET /problems?difficulty=Hard&tag=dp → both filters applied."""
    create_problem(client, admin_headers, title=None, difficulty="Hard", tags=["dp"])
    create_problem(client, admin_headers, title=None, difficulty="Hard", tags=["graphs"])
    create_problem(client, admin_headers, title=None, difficulty="Easy", tags=["dp"])

    r = client.get("/problems", params={"difficulty": "Hard", "tag": "dp"})
    body = assert_200(r)

    for item in body["items"]:
        assert item["difficulty"] == "Hard"
        assert "dp" in item["tags"]


def test_list_problems_invalid_difficulty_422(client):
    """GET /problems?difficulty=invalid → 422."""
    r = client.get("/problems", params={"difficulty": "superhard"})
    assert_422(r)


def test_list_problems_page_out_of_range(client, admin_headers):
    """GET /problems?page=999 → 200 with empty items."""
    r = client.get("/problems", params={"page": 999, "limit": 20})
    body = assert_200(r)
    assert body["items"] == []
    assert body["page"] == 999
