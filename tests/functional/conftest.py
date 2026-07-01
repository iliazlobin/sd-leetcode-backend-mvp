"""Functional tests conftest — ASGITransport in-process tests."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from leetcode.main import create_app


@pytest.fixture(scope="module")
async def client():
    """Module-scoped AsyncClient using ASGITransport."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def unique_suffix():
    """Generate a unique suffix for test entities."""
    return uuid.uuid4().hex[:8]


async def get_admin_token(client: AsyncClient) -> str:
    """Login as admin and return JWT token."""
    r = await client.post("/auth/token", json={
        "username": "admin",
        "password": "admin123",
    })
    assert r.status_code == 200
    return r.json()["access_token"]


async def get_user_token(client: AsyncClient, username="alice", password="alice123") -> str:
    """Login as a regular user and return JWT token."""
    r = await client.post("/auth/token", json={
        "username": username,
        "password": password,
    })
    assert r.status_code == 200
    return r.json()["access_token"]


async def create_problem(client: AsyncClient, admin_token: str, suffix: str, **kwargs) -> dict:
    """Create a problem via API. Returns the response body."""
    body = {
        "title": kwargs.get("title", f"Test Problem {suffix}"),
        "difficulty": kwargs.get("difficulty", "Easy"),
        "tags": kwargs.get("tags", ["arrays"]),
        "description": kwargs.get("description", "Solve this problem."),
        "constraints": kwargs.get("constraints", "N/A"),
        "code_stub": kwargs.get("code_stub", ""),
        "test_cases": kwargs.get("test_cases", [
            {"input": "1 2", "expected_output": "3", "is_public": True},
            {"input": "5 5", "expected_output": "10", "is_public": False},
        ]),
    }
    r = await client.post("/problems", json=body, headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 201, f"Create problem failed: {r.status_code} {r.text}"
    return r.json()
