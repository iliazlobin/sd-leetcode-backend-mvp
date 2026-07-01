"""Functional tests for Submissions (FR-4, FR-5, FR-7)."""

import uuid

import pytest

from tests.functional.conftest import (
    create_problem,
    get_admin_token,
    get_user_token,
)

CORRECT_CODE = "x = input().split()\nprint(int(x[0]) + int(x[1]))\n"


@pytest.mark.asyncio
async def test_fr4_submit_solution_success(client, unique_suffix):
    """FR-4: POST /submissions → 201 with verdict=Pending."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"SubTest {unique_suffix}")

    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": CORRECT_CODE,
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 201
    body = r.json()
    assert "submission_id" in body
    assert body["verdict"] == "Pending"
    assert body["problem_id"] == prob["problem_id"]
    assert body["language"] == "python3"


@pytest.mark.asyncio
async def test_fr4_submit_unknown_problem_404(client, unique_suffix):
    """FR-4: Unknown problem → 404."""
    user_token = await get_user_token(client)
    r = await client.post("/submissions", json={
        "problem_id": str(uuid.uuid4()),
        "language": "python3",
        "source_code": "print(1)\n",
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_fr4_submit_unsupported_language_422(client, unique_suffix):
    """FR-4: Unsupported language → 422."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"Lang {unique_suffix}")

    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "brainfuck",
        "source_code": "++",
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 422
    body = r.json()
    # The detail may be nested
    detail = body.get("detail", body)
    assert "supported_languages" in str(detail) or "python3" in str(detail).lower()


@pytest.mark.asyncio
async def test_fr4_submit_missing_fields_422(client, unique_suffix):
    """FR-4: Missing required fields → 422."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"Miss {unique_suffix}")

    # Missing source_code
    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 422

    # Missing language
    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "source_code": "print(1)\n",
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fr4_submit_unauthenticated_401(client, unique_suffix):
    """FR-4: No auth → 401."""
    admin_token = await get_admin_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"NoAuth {unique_suffix}")

    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": "print(1)\n",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_fr4_submit_duplicate_409(client, unique_suffix):
    """FR-4: Duplicate submission within 30s → 409."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"Dedup {unique_suffix}")

    source = "print(42)\n"
    # First submission
    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": source,
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 201

    # Duplicate within 30s
    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": source,
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_fr5_get_submission_own(client, unique_suffix):
    """FR-5: GET /submissions/{id} own → 200."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"GetSub {unique_suffix}")

    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": CORRECT_CODE,
    }, headers={"Authorization": f"Bearer {user_token}"})
    sub_id = r.json()["submission_id"]

    r = await client.get(f"/submissions/{sub_id}", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["submission_id"] == sub_id
    assert body["verdict"] in ("Pending", "Running", "Accepted")
    assert "source_code" in body


@pytest.mark.asyncio
async def test_fr5_get_submission_cross_user_403(client, unique_suffix):
    """FR-5: Cross-user access → 403."""
    admin_token = await get_admin_token(client)
    alice_token = await get_user_token(client, "alice", "alice123")
    bob_token = await get_user_token(client, "bob", "bob123")
    prob = await create_problem(client, admin_token, unique_suffix, title=f"Cross {unique_suffix}")

    # Alice submits
    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": "print(1)\n",
    }, headers={"Authorization": f"Bearer {alice_token}"})
    sub_id = r.json()["submission_id"]

    # Bob tries to view
    r = await client.get(f"/submissions/{sub_id}", headers={"Authorization": f"Bearer {bob_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_fr5_get_submission_not_found_404(client, unique_suffix):
    """FR-5: Unknown submission → 404."""
    user_token = await get_user_token(client)
    r = await client.get(f"/submissions/{uuid.uuid4()}", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_fr5_get_submission_unauthenticated_401(client, unique_suffix):
    """FR-5: No auth → 401."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"NoAuthV {unique_suffix}")

    r = await client.post("/submissions", json={
        "problem_id": prob["problem_id"],
        "language": "python3",
        "source_code": "print(1)\n",
    }, headers={"Authorization": f"Bearer {user_token}"})
    sub_id = r.json()["submission_id"]

    r = await client.get(f"/submissions/{sub_id}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_fr7_submission_history_paginated(client, unique_suffix):
    """FR-7: GET /submissions?problem_id={id} → 200 paginated."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"Hist {unique_suffix}")

    # Submit twice
    await client.post("/submissions", json={
        "problem_id": prob["problem_id"], "language": "python3", "source_code": "print(1)\n",
    }, headers={"Authorization": f"Bearer {user_token}"})
    await client.post("/submissions", json={
        "problem_id": prob["problem_id"], "language": "python3", "source_code": "print(2)\n",
    }, headers={"Authorization": f"Bearer {user_token}"})

    r = await client.get("/submissions", params={
        "problem_id": prob["problem_id"], "page": 1, "limit": 50,
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    assert len(body["items"]) >= 2

    # Most recent first — verify that timestamps are in descending order
    import datetime
    timestamps = [
        datetime.datetime.fromisoformat(item["submitted_at"].replace("Z", "+00:00"))
        for item in body["items"]
    ]
    for i in range(len(timestamps) - 1):
        assert timestamps[i] >= timestamps[i + 1], \
            f"Expected descending timestamps, got {timestamps[i]} before {timestamps[i + 1]}"


@pytest.mark.asyncio
async def test_fr7_submission_history_empty(client, unique_suffix):
    """FR-7: No submissions → 200 with empty items."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"EmptyH {unique_suffix}")

    # Don't submit anything
    r = await client.get("/submissions", params={
        "problem_id": prob["problem_id"],
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_fr7_submission_history_other_user_isolation(client, unique_suffix):
    """FR-7: User A only sees their own submissions."""
    admin_token = await get_admin_token(client)
    alice_token = await get_user_token(client, "alice", "alice123")
    bob_token = await get_user_token(client, "bob", "bob123")
    prob = await create_problem(client, admin_token, unique_suffix, title=f"Isol {unique_suffix}")

    # Alice submits
    await client.post("/submissions", json={
        "problem_id": prob["problem_id"], "language": "python3", "source_code": "print(1)\n",
    }, headers={"Authorization": f"Bearer {alice_token}"})
    # Bob submits
    await client.post("/submissions", json={
        "problem_id": prob["problem_id"], "language": "python3", "source_code": "print(2)\n",
    }, headers={"Authorization": f"Bearer {bob_token}"})

    # Alice checks
    r = await client.get("/submissions", params={
        "problem_id": prob["problem_id"],
    }, headers={"Authorization": f"Bearer {alice_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1  # Only Alice's


@pytest.mark.asyncio
async def test_fr7_submission_history_unauthenticated_401(client, unique_suffix):
    """FR-7: No auth → 401."""
    admin_token = await get_admin_token(client)
    user_token = await get_user_token(client)
    prob = await create_problem(client, admin_token, unique_suffix, title=f"NoAuthH {unique_suffix}")

    await client.post("/submissions", json={
        "problem_id": prob["problem_id"], "language": "python3", "source_code": "print(1)\n",
    }, headers={"Authorization": f"Bearer {user_token}"})

    r = await client.get("/submissions", params={"problem_id": prob["problem_id"]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_fr7_submission_history_missing_problem_id_422(client, unique_suffix):
    """FR-7: Missing problem_id → 422."""
    user_token = await get_user_token(client)
    r = await client.get("/submissions", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 422
