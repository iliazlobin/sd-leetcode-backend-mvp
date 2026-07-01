"""Functional tests for Leaderboard (FR-8)."""


import pytest

CORRECT_CODE = "x = input().split()\nprint(int(x[0]) + int(x[1]))\n"


@pytest.mark.asyncio
async def test_fr8_leaderboard_empty(client, unique_suffix):
    """FR-8: GET /leaderboard → 200 with entries (may be empty)."""
    r = await client.get("/leaderboard")
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body
    assert isinstance(body["entries"], list)


@pytest.mark.asyncio
async def test_fr8_leaderboard_pagination(client, unique_suffix):
    """FR-8: GET /leaderboard?page=1&limit=1 → pagination works."""
    r = await client.get("/leaderboard", params={"page": 1, "limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["limit"] == 1
    assert len(body["entries"]) <= 1
