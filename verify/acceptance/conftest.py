"""Shared fixtures and helpers for the LeetCode MVP black-box acceptance suite.

These tests do NOT import `src.leetcode`. They talk to the running system
via HTTP at API_BASE_URL. The system must be fully running — API + judge worker —
for the full suite to pass.

Test isolation: each test creates unique problems and submissions via the API.
Pre-seeded users provide auth tokens.
"""

import os
import time
import uuid

import httpx
import pytest

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Credentials from environment (must match alembic seed migration)
# ---------------------------------------------------------------------------
TEST_ADMIN_USERNAME = os.environ.get("TEST_ADMIN_USERNAME", "admin")
TEST_ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "admin123")
TEST_USER_USERNAME = os.environ.get("TEST_USER_USERNAME", "alice")
TEST_USER_PASSWORD = os.environ.get("TEST_USER_PASSWORD", "alice123")
TEST_USER2_USERNAME = os.environ.get("TEST_USER2_USERNAME", "bob")
TEST_USER2_PASSWORD = os.environ.get("TEST_USER2_PASSWORD", "bob123")
TEST_USER3_USERNAME = os.environ.get("TEST_USER3_USERNAME", "charlie")
TEST_USER3_PASSWORD = os.environ.get("TEST_USER3_PASSWORD", "bob123")
TEST_USER4_USERNAME = os.environ.get("TEST_USER4_USERNAME", "dave")
TEST_USER4_PASSWORD = os.environ.get("TEST_USER4_PASSWORD", "bob123")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url():
    return API_BASE_URL


@pytest.fixture(scope="session")
def client(base_url):
    """Session-scoped httpx client for the entire acceptance run."""
    with httpx.Client(base_url=base_url, timeout=30) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    """Obtain admin JWT token once per session."""
    r = client.post("/auth/token", json={
        "username": TEST_ADMIN_USERNAME,
        "password": TEST_ADMIN_PASSWORD,
    })
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    """Authorization header dict for admin requests."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def user_token(client):
    """Obtain regular user JWT token once per session."""
    r = client.post("/auth/token", json={
        "username": TEST_USER_USERNAME,
        "password": TEST_USER_PASSWORD,
    })
    assert r.status_code == 200, f"User login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def user_headers(user_token):
    """Authorization header dict for user requests."""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture(scope="session")
def user2_token(client):
    """Obtain second regular user JWT token once per session."""
    r = client.post("/auth/token", json={
        "username": TEST_USER2_USERNAME,
        "password": TEST_USER2_PASSWORD,
    })
    assert r.status_code == 200, f"User2 login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def user2_headers(user2_token):
    """Authorization header dict for second user requests."""
    return {"Authorization": f"Bearer {user2_token}"}


@pytest.fixture(scope="session")
def user3_token(client):
    """Obtain third regular user JWT token once per session."""
    r = client.post("/auth/token", json={
        "username": TEST_USER3_USERNAME,
        "password": TEST_USER3_PASSWORD,
    })
    assert r.status_code == 200, f"User3 login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def user3_headers(user3_token):
    """Authorization header dict for third user requests."""
    return {"Authorization": f"Bearer {user3_token}"}


@pytest.fixture(scope="session")
def user4_token(client):
    """Obtain fourth regular user JWT token once per session."""
    r = client.post("/auth/token", json={
        "username": TEST_USER4_USERNAME,
        "password": TEST_USER4_PASSWORD,
    })
    assert r.status_code == 200, f"User4 login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def user4_headers(user4_token):
    """Authorization header dict for fourth user requests."""
    return {"Authorization": f"Bearer {user4_token}"}


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_status(r, expected_status):
    """Assert status and return parsed JSON."""
    assert r.status_code == expected_status, \
        f"Expected {expected_status}, got {r.status_code}: {r.text}"
    return r.json()


def assert_200(r):
    return assert_status(r, 200)


def assert_201(r):
    return assert_status(r, 201)


def assert_401(r):
    assert r.status_code == 401, \
        f"Expected 401, got {r.status_code}: {r.text}"
    return r.json()


def assert_403(r):
    assert r.status_code == 403, \
        f"Expected 403, got {r.status_code}: {r.text}"
    return r.json()


def assert_404(r):
    assert r.status_code == 404, \
        f"Expected 404, got {r.status_code}: {r.text}"
    return r.json()


def assert_409(r):
    assert r.status_code == 409, \
        f"Expected 409, got {r.status_code}: {r.text}"
    return r.json()


def assert_422(r):
    assert r.status_code == 422, \
        f"Expected 422, got {r.status_code}: {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# Setup helpers — create resources via HTTP
# ---------------------------------------------------------------------------


def create_problem(client, headers, title=None, difficulty="Easy", tags=None,
                   description="Solve this.", constraints="N/A",
                   code_stub="def solve():\n    pass\n",
                   test_cases=None):
    """Create a problem. Returns parsed 201 response body."""
    if title is None:
        title = f"Problem-{uuid.uuid4().hex[:12]}"
    # If title is provided, use it AS-IS (no additional suffix)
    if tags is None:
        tags = ["arrays"]
    if test_cases is None:
        test_cases = [
            {"input": "1 2", "expected_output": "3", "is_public": True},
            {"input": "5 5", "expected_output": "10", "is_public": False},
        ]
    r = client.post("/problems", json={
        "title": title,
        "difficulty": difficulty,
        "tags": tags,
        "description": description,
        "constraints": constraints,
        "code_stub": code_stub,
        "test_cases": test_cases,
    }, headers=headers)
    return assert_201(r)


def submit_solution(client, headers, problem_id, source_code, language="python3"):
    """Submit a solution. Returns parsed 201 response body."""
    r = client.post("/submissions", json={
        "problem_id": problem_id,
        "language": language,
        "source_code": source_code,
    }, headers=headers)
    return assert_201(r)


def poll_verdict(client, headers, submission_id, timeout_seconds=15, poll_interval=0.3):
    """Poll GET /submissions/{id} until verdict is no longer Pending/Running.
    Returns the final submission body. Raises TimeoutError if not resolved."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        r = client.get(f"/submissions/{submission_id}", headers=headers)
        assert r.status_code == 200, \
            f"GET /submissions/{submission_id} failed: {r.status_code} {r.text}"
        body = r.json()
        if body["verdict"] not in ("Pending", "Running"):
            return body
        time.sleep(poll_interval)
    raise TimeoutError(
        f"Submission {submission_id} did not reach final verdict within {timeout_seconds}s"
    )
