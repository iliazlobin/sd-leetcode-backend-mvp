# LeetCode MVP

[![Lint](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/lint.yml/badge.svg)](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/lint.yml)
[![CI](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/ci.yml)
[![Functional](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/functional.yml/badge.svg)](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/functional.yml)

A minimal online code-judge platform backend. Browse coding problems, submit Python solutions,
and receive automated verdicts (Accepted, Wrong Answer, Time Limit Exceeded, Runtime Error)
from a background judge worker. Built with FastAPI, PostgreSQL, and Redis.

## Quickstart

Requires Docker and Git.

```bash
git clone https://github.com/iliazlobin/sd-leetcode-backend-mvp.git
cd sd-leetcode-backend-mvp

# Bring up the stack (builds image, starts postgres + redis + app + judge worker)
docker compose up --build -d

# Run migrations + seed data (admin + regular users)
docker compose exec app alembic upgrade head

# Verify it's alive
curl http://localhost:8010/healthz
# → {"status":"ok"}
```

Login with seeded credentials:

```bash
curl -X POST http://localhost:8010/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

## Architecture

Four Docker Compose services share a network. Only `app` publishes a host port.

| Service | Image | Role |
|---------|-------|------|
| `app` | Built from `Dockerfile` | FastAPI API on `:8000` + background judge worker in-process |
| `db` | postgres:16-alpine | Problems, submissions, users (SQLAlchemy async) |
| `redis` | redis:7-alpine | Leaderboard cache + submission idempotency |

The judge worker polls the `submissions` table for `Pending` entries, executes user code
in a subprocess against each problem's test cases (fail-fast), and writes the verdict back.
Python only in the MVP.

## API Reference

All endpoints return JSON. Auth is JWT Bearer (except `/healthz` and public endpoints).

### Health

`GET /healthz`
— Liveness probe, no auth required. Returns `{"status":"ok"}`.

### Auth

`POST /auth/token`
— Login. Body: `{"username": "alice", "password": "alice123"}`.
Returns `{"access_token": "...", "token_type": "bearer", "user_id": "...", "role": "user"}`.
Error codes: `401` invalid credentials.

### Problems

`POST /problems` — Create a coding problem. Admin only. Request body includes `title`
(unique), `difficulty` (Easy/Medium/Hard), `tags`, `description`, `constraints`,
`code_stub`, and `test_cases` (at least one `{input, expected_output, is_public}`).
Returns `201` with problem resource. Errors: `401` unauthenticated, `403` non-admin,
`409` duplicate title, `422` invalid/missing fields.

`GET /problems` — List/search problems with pagination and optional filters.
Query: `page` (default 1), `limit` (default 20, max 100), `difficulty`, `tag`.
Returns `200` with `{items: [...], total, page, limit}`. Errors: `422` invalid difficulty.

`GET /problems/{id}` — Get a single problem by ID with its public test cases.
Returns `200` with full problem + `test_cases` (public only; `is_public=false` are hidden).
Errors: `404` not found.

### Submissions

`POST /submissions` — Submit a solution. Auth required. Body: `{problem_id, language, source_code}`.
MVP supports `"python3"` only. Returns `201` with `{submission_id, verdict: "Pending"}`.
Duplicate submissions (same user + problem + code within 30s) return `409`.
Errors: `401` unauthenticated, `404` unknown problem, `422` unsupported language / missing fields.

`GET /submissions/{id}` — Poll for verdict. Own submissions only.
Returns `200` with `{verdict, runtime_ms, memory_kb, source_code, ...}`.
Final verdicts: `Accepted`, `Wrong Answer`, `Time Limit Exceeded`, `Runtime Error`.
Errors: `401` unauthenticated, `403` cross-user access, `404` not found.

`GET /submissions` — List submission history for a problem. Auth required.
Query: `problem_id` (required), `page`, `limit`. Ordered most-recent-first.
Returns `200` with `{items: [...], total, page, limit}`.
Errors: `401` unauthenticated, `422` missing `problem_id`.

### Leaderboard

`GET /leaderboard` — Global leaderboard ranked by distinct problems solved.
Query: `page` (default 1), `limit` (default 100, max 500).
Returns `200` with `{entries: [{username, problems_solved, last_solved_at}, ...], total, page, limit}`.
Tie-break: earlier last-accepted timestamp ranks higher. No auth required.

## Data Model

Four core entities in PostgreSQL:

- **User** — `user_id` (UUID PK), `username` (unique), `password_hash`, `role` (admin/user)
- **Problem** — `problem_id`, `title` (unique), `difficulty`, `tags` (GIN-indexed), `description`, `constraints`, `code_stub`
- **TestCase** — `test_case_id`, `problem_id` (FK), `input_text`, `expected_output`, `is_public`, `order_index`
- **Submission** — `submission_id`, `user_id` (FK), `problem_id` (FK), `language`, `source_code`, `verdict`, `runtime_ms`, `memory_kb`, `idempotency_key` (SHA256 dedup)

Leaderboard entries are computed via SQL `GROUP BY` on the `submissions` table and cached in Redis (30s TTL).

## Testing

Three test layers:

| Layer | Command | Scope |
|-------|---------|-------|
| Unit | `pytest tests/unit/ -v` | Service-layer logic with mocked DB |
| Functional | `pytest tests/functional/ -v` | In-process `httpx.ASGITransport` against the real app |
| Acceptance | `API_BASE_URL=http://localhost:8010 pytest verify/acceptance/ -v` | Black-box HTTP against the running stack |

All three layers pass in CI — see status badges above.

## Project Layout

```
├── src/leetcode/          # FastAPI application package
│   ├── main.py            # App factory + lifespan + router mounting
│   ├── config.py          # pydantic-settings (DATABASE_URL, REDIS_URL, JWT_SECRET)
│   ├── database.py        # SQLAlchemy async engine + session factory + Redis
│   ├── auth.py            # JWT encode/decode + FastAPI auth dependencies
│   ├── models/            # SQLAlchemy ORM models (User, Problem, TestCase, Submission)
│   ├── schemas/           # Pydantic request/response DTOs
│   ├── routers/           # Thin FastAPI routers (problems, submissions, leaderboard, auth, health)
│   └── services/          # Business logic (problem, submission, judge, leaderboard, auth)
├── judge/                 # Judge worker (separate process, shares DB)
│   ├── runner.py          # Entry point: `python -m judge.runner`
│   ├── worker.py          # Polling loop: claim Pending → execute → write verdict
│   └── sandbox.py         # Subprocess executor with 5s timeout
├── alembic/               # Database migrations + seed data
├── tests/
│   ├── unit/              # White-box service-layer tests
│   └── functional/        # In-process integration tests (ASGITransport)
├── verify/
│   ├── manifest.env       # e2e verification contract (CI + host loop)
│   └── acceptance/        # Black-box acceptance tests (one per functional requirement)
├── Dockerfile             # Multi-stage Python 3.12 build
├── docker-compose.yml     # db + redis + app services
├── pyproject.toml         # Dependencies + tool config
├── DEPLOY.md              # Deploy walkthrough
├── SPEC.md                # Engineering spec (canonical source for Notion sync)
├── DESIGN.md              # This build's design + functional spec
└── .github/workflows/     # CI: lint (ruff 0.8.0), unit tests, functional tests
```

## Deploy

See [DEPLOY.md](DEPLOY.md) for full deployment instructions, environment variables, and
teardown steps.
