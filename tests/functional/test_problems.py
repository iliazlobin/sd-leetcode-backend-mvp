"""Functional tests for Problems (FR-1, FR-2, FR-3)."""

import pytest

from tests.functional.conftest import (
    create_problem,
    get_admin_token,
    get_user_token,
)


@pytest.mark.asyncio
async def test_fr1_create_problem_success(client, unique_suffix):
    """FR-1: POST /problems → 201 with problem resource."""
    admin_token = await get_admin_token(client)
    body = await create_problem(
        client, admin_token, unique_suffix,
        title=f"Two Sum {unique_suffix}",
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
    assert body["title"] == f"Two Sum {unique_suffix}"
    assert body["difficulty"] == "Easy"
    assert body["test_case_count"] == 2
    assert "created_at" in body


@pytest.mark.asyncio
async def test_fr1_create_problem_missing_title_422(client, unique_suffix):
    """FR-1: Missing required field 'title' → 422."""
    admin_token = await get_admin_token(client)
    r = await client.post("/problems", json={
        "difficulty": "Easy",
        "tags": ["arrays"],
        "description": "desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [{"input": "1", "expected_output": "1", "is_public": True}],
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fr1_create_problem_empty_test_cases_422(client, unique_suffix):
    """FR-1: Empty test_cases → 422."""
    admin_token = await get_admin_token(client)
    r = await client.post("/problems", json={
        "title": f"No Tests {unique_suffix}",
        "difficulty": "Easy",
        "tags": ["arrays"],
        "description": "desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [],
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fr1_create_problem_duplicate_title_409(client, unique_suffix):
    """FR-1: Duplicate title → 409."""
    admin_token = await get_admin_token(client)
    title = f"Unique {unique_suffix}"
    await create_problem(client, admin_token, unique_suffix, title=title)
    r = await client.post("/problems", json={
        "title": title,
        "difficulty": "Hard",
        "tags": ["math"],
        "description": "x",
        "constraints": "x",
        "code_stub": "x",
        "test_cases": [{"input": "1", "expected_output": "1", "is_public": True}],
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_fr1_create_problem_unauthenticated_401(client, unique_suffix):
    """FR-1: No auth → 401."""
    r = await client.post("/problems", json={
        "title": f"No Auth {unique_suffix}",
        "difficulty": "Easy",
        "tags": ["arrays"],
        "description": "desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [{"input": "1", "expected_output": "1", "is_public": True}],
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_fr1_create_problem_non_admin_403(client, unique_suffix):
    """FR-1: Non-admin user → 403."""
    user_token = await get_user_token(client)
    r = await client.post("/problems", json={
        "title": f"User Create {unique_suffix}",
        "difficulty": "Easy",
        "tags": ["arrays"],
        "description": "desc",
        "constraints": "N/A",
        "code_stub": "def solve():\n    pass\n",
        "test_cases": [{"input": "1", "expected_output": "1", "is_public": True}],
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_fr2_list_problems_pagination(client, unique_suffix):
    """FR-2: GET /problems with pagination."""
    admin_token = await get_admin_token(client)
    await create_problem(client, admin_token, unique_suffix, title=f"LP1 {unique_suffix}")
    await create_problem(client, admin_token, unique_suffix + "2", title=f"LP2 {unique_suffix}")

    r = await client.get("/problems", params={"page": 1, "limit": 20})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert body["page"] == 1
    assert body["limit"] == 20


@pytest.mark.asyncio
async def test_fr2_list_problems_filter_by_difficulty(client, unique_suffix):
    """FR-2: Filter by difficulty."""
    admin_token = await get_admin_token(client)
    await create_problem(client, admin_token, unique_suffix, title=f"Easy {unique_suffix}", difficulty="Easy")
    await create_problem(client, admin_token, unique_suffix + "2", title=f"Hard {unique_suffix}", difficulty="Hard")

    r = await client.get("/problems", params={"difficulty": "Easy"})
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["difficulty"] == "Easy"


@pytest.mark.asyncio
async def test_fr2_list_problems_filter_by_tag(client, unique_suffix):
    """FR-2: Filter by tag."""
    admin_token = await get_admin_token(client)
    await create_problem(client, admin_token, unique_suffix, title=f"Arr {unique_suffix}", tags=["arrays"])

    r = await client.get("/problems", params={"tag": "arrays"})
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert "arrays" in item["tags"]


@pytest.mark.asyncio
async def test_fr2_list_problems_invalid_difficulty_422(client):
    """FR-2: Invalid difficulty → 422."""
    r = await client.get("/problems", params={"difficulty": "superhard"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fr3_get_problem_found(client, unique_suffix):
    """FR-3: GET /problems/{id} → 200 with public test cases."""
    admin_token = await get_admin_token(client)
    created = await create_problem(
        client, admin_token, unique_suffix,
        title=f"GetById {unique_suffix}",
        test_cases=[
            {"input": "hello", "expected_output": "olleh", "is_public": True},
            {"input": "world", "expected_output": "dlrow", "is_public": False},
        ],
    )
    r = await client.get(f"/problems/{created['problem_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == f"GetById {unique_suffix}"
    assert "test_cases" in body
    assert len(body["test_cases"]) == 1  # Only public


@pytest.mark.asyncio
async def test_fr3_get_problem_not_found_404(client):
    """FR-3: GET /problems/{nonexistent} → 404."""
    import uuid
    r = await client.get(f"/problems/{uuid.uuid4()}")
    assert r.status_code == 404
