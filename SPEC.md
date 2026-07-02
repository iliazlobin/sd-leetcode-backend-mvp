# LeetCode MVP — Engineering Spec

## 1. Goal & scope

Build a minimal online code judge platform where users can browse coding problems, submit Python solutions,
and receive automated verdicts. The judge runs untrusted user code in a sandboxed Docker container, compares
output against stored test cases, and returns a verdict within 5 seconds. This is the MVP variant — a
working backend API with judge capability, deployable via Docker Compose.

**In scope:**
- Problem CRUD (create, list, search, get by ID)
- Code submission with background judging (Python only)
- Submission history per problem
- Global leaderboard ranked by distinct problems solved
- JWT-based authentication
- Docker Compose deployment with FastAPI + PostgreSQL + Redis

**Out of scope:**
- 20+ language support (Python only)
- Contest system (registrations, timers, contest-scoped submissions)
- Real-time WebSocket updates (REST polling)
- Firecracker microVMs (Docker sandbox)
- S3 test case storage (PostgreSQL)
- Kafka judge queue (DB polling)
- User registration (seed data)
- Frontend UI

## 2. Functional requirements

- **FR-1 — Create problem.** `POST /problems {title, description, difficulty, tags, constraints, test_cases}` → `201`; missing fields → `422`; duplicate title → `409`.
- **FR-2 — List/search problems.** `GET /problems?page=1&limit=20&difficulty=easy&tag=arrays` → `200` with paginated `{items, total, page, limit}`; invalid filter → `422`.
- **FR-3 — Get problem.** `GET /problems/{id}` → `200` with full problem + public test cases; unknown → `404`.
- **FR-4 — Submit solution.** `POST /submissions {problem_id, language, source_code}` → `201` with `{submission_id, verdict: "Pending"}`; unknown problem → `404`; unsupported language → `422`.
- **FR-5 — Get verdict.** `GET /submissions/{id}` → `200` with verdict + runtime/metrics; unknown → `404`; cross-user → `403`.
- **FR-6 — Judge execution.** Worker dequeues pending submissions, runs code in Docker sandbox against test cases, writes verdict. Fail-fast on first WA. Idempotent: re-processing judged submission = no-op. 5s timeout per submission.
- **FR-7 — Submission history.** `GET /submissions?problem_id={id}` → `200` paginated, most recent first; unauthenticated → `401`.
- **FR-8 — Leaderboard.** `GET /leaderboard?page=1&limit=100` → `200` with `{entries: [{username, problems_solved}], total, page, limit}`. Tie-break by earliest last-accepted.

## 3. Stack & deployment

- **Runtime:** Python 3.12, FastAPI, uvicorn
- **Datastore:** PostgreSQL 16 (problems, submissions, users) + Redis 7 (leaderboard)
- **Tests:** pytest, httpx (ASGI transport for functional tests)
- **Deploy:** Docker Compose — `db` + `redis` + `app` + `judge-worker` services
- **Port:** `app` publishes `${APP_PORT:-8010}:8000`; other services internal
- **Design →** [DESIGN.md](DESIGN.md)

## 4. Data model

```sql
User {
  user_id:       uuid PK
  username:      text     ← unique
  password_hash: text
  created_at:    timestamp
}

Problem {
  problem_id:    uuid PK
  title:         text     ← unique
  difficulty:    text     ← Easy/Medium/Hard
  tags:          text[]   ← GIN-indexed
  description:   text
  constraints:   text
  created_at:    timestamp
}

TestCase {
  test_case_id:  uuid PK
  problem_id:    uuid FK → Problem
  input:         text
  expected_output: text
  is_public:     boolean
}

Submission {
  submission_id: uuid PK
  user_id:       uuid FK → User
  problem_id:    uuid FK → Problem
  language:      text
  source_code:   text
  verdict:       text     ← Pending/Running/Accepted/Wrong Answer/TLE/RE
  runtime_ms:    integer
  memory_kb:     integer
  submitted_at:  timestamp
  completed_at:  timestamp
}

LeaderboardEntry {
  user_id:       uuid FK → User    ← stored in Redis ZSET
  problems_solved: integer
  last_accepted: timestamp
}
```

## 5. API

- `POST /problems` — create a coding problem
- `GET /problems` — browse/search problems (paginated, filterable)
- `GET /problems/{problem_id}` — get problem details + public test cases
- `POST /submissions` — submit solution
- `GET /submissions/{submission_id}` — poll submission verdict
- `GET /submissions` — list user's submissions (filterable by problem)
- `GET /leaderboard` — global leaderboard (paginated)

## 6. Test scenarios

- **Idempotency:** Duplicate problem title → 409. Re-submit identical code → new submission; re-judging already-judged submission → no-op.
- **Ordering:** Submissions returned most-recent-first. Leaderboard ordered by problems_solved DESC, then earliest last-accepted.
- **Pagination:** All list endpoints support `page` + `limit` with `total` count. Edge: page beyond range → empty items.
- **Auth & ownership:** Only authenticated users can submit. Users can only view their own submissions (403 on other user's).
- **Validation:** Missing required fields → 422 with detail. Invalid difficulty/tag filter → 422. Unsupported language → 422.
- **Error paths:** Nonexistent problem/submission → 404. Unauthenticated → 401.

## 7. Module layout

```
src/
  leetcode/
    __init__.py
    main.py              # FastAPI app factory + lifespan
    config.py             # pydantic-settings
    api/
      __init__.py
      router.py           # API router aggregation
      problems.py         # /problems endpoints
      submissions.py      # /submissions endpoints
      leaderboard.py      # /leaderboard endpoint
    services/
      __init__.py
      problem_service.py
      submission_service.py
      judge_service.py
      leaderboard_service.py
    models/
      __init__.py
      base.py             # SQLAlchemy Base + session
      user.py
      problem.py
      test_case.py
      submission.py
    schemas/
      __init__.py
      problem.py
      submission.py
      leaderboard.py
    judge/
      __init__.py
      worker.py           # background poll-loop worker
      sandbox.py           # Docker sandbox executor
    migrations/            # Alembic
tests/
  unit/
  functional/
verify/
  acceptance/
```

## 8. Run

```bash
docker compose up -d
curl http://localhost:8010/healthz
# → {"status": "ok"}

docker compose run app alembic upgrade head
docker compose run app python -m leetcode.seed  # seed problems + users

pytest tests/unit/ tests/functional/ -v
# → all green

pytest verify/acceptance/ -v --api-base-url http://localhost:8010
# → all green (8 FR acceptance cases)
```
