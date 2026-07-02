# LeetCode Backend MVP — Design

A minimal online code-judge platform backend: users browse coding problems, submit Python
solutions, and receive automated verdicts from a background judge that executes their code
against stored test cases. This document describes the architecture, data model, API, and
key design decisions of this build, and maps every functional requirement to the test that
proves it.

The MVP is deliberately scoped down from a full-scale LeetCode-style system design (Kafka
judge queue, Firecracker microVM sandboxes, 20+ languages, contests, real-time WebSocket
updates, S3 test-case storage). This build keeps the same core flow — problem CRUD → submit
→ judge → verdict → leaderboard — on a smaller, operationally simple stack: FastAPI,
PostgreSQL 16, Redis 7, and a subprocess-based judge.

**In scope:** problem CRUD (create/list/search/get), code submission with background judging
(Python only), submission history, a global leaderboard ranked by distinct problems solved,
JWT authentication, and Docker Compose deployment.

**Out of scope (future phases):** multi-language support, contests, WebSocket updates,
microVM isolation, user self-registration (users are seeded via migration), and a frontend.

## 1. Architecture Overview

```mermaid
graph TB
    subgraph api["FastAPI App — port 8000"]
        R_PROB[Problems Router]
        R_SUB[Submissions Router]
        R_LB[Leaderboard Router]
        R_AUTH[Auth Router]
        HZ[/healthz]
    end

    subgraph services["Service Layer"]
        PS[ProblemService]
        SS[SubmissionService]
        LS[LeaderboardService]
        AS[AuthService]
    end

    subgraph data["Data Layer"]
        PG[(PostgreSQL<br/>SQLAlchemy 2.0)]
        RD[(Redis<br/>leaderboard cache)]
    end

    subgraph judge["Judge Worker — background task"]
        JW[JudgeWorker<br/>polling loop]
        SB[Sandbox<br/>subprocess<br/>timeout=5s]
    end

    R_PROB --> PS
    R_SUB --> SS
    R_LB --> LS
    R_AUTH --> AS
    PS --> PG
    SS --> PG
    LS --> PG
    LS --> RD
    AS --> PG
    JW --> PG
    JW --> SB

    classDef edge  fill:#fff3bf,stroke:#f08c00,color:#1a1a1a
    classDef svc   fill:#d0ebff,stroke:#1c7ed6,color:#1a1a1a
    classDef store fill:#d3f9d8,stroke:#2f9e44,color:#1a1a1a
    classDef rt    fill:#ffe8cc,stroke:#e8590c,color:#1a1a1a

    class R_PROB,R_SUB,R_LB,R_AUTH,HZ svc
    class PS,SS,LS,AS svc
    class PG,RD store
    class JW,SB rt
```

**Layers:** Router (HTTP parse/validate/serialize, no business logic) → Service (business
logic + data access) → Model (ORM, DB session). The standard FastAPI three-layer split.

**Judge worker** lives in the `judge/` package and runs as an asyncio background task
started by the app's lifespan (it can also run standalone via `python -m judge.runner`).
It polls `submissions` for `verdict='Pending'`, executes user code in a sandboxed
subprocess with a 5-second timeout, and writes the verdict back to the shared PostgreSQL
database.

**No Kafka, no Firecracker, no multi-language support, no WebSocket** — those belong to
the full-scale design, not the MVP. The MVP implements: problem CRUD → submit code →
judge execution → poll verdict → submission history → leaderboard.

**Redis** serves two purposes: caching the leaderboard (TTL 30s) to avoid a full GROUP BY
scan on every poll, and a fast idempotency check for duplicate submissions. The full
design's Redis ZSET leaderboard is the future path; the MVP uses a simple cache-aside
pattern.

## 2. Data Model (SQLAlchemy ORM)

```python
# models/user.py
class User(Base):
    __tablename__ = "users"

    user_id:      Mapped[uuid.UUID] = Column(UUID, primary_key=True, default=uuid.uuid4)
    username:     Mapped[str]       = Column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str]      = Column(String(256), nullable=False)
    role:         Mapped[str]       = Column(String(16), nullable=False, default="user")
                                      # "admin" | "user"
    created_at:   Mapped[datetime]  = Column(DateTime(timezone=True), server_default=func.now())
```

```python
# models/problem.py
class Problem(Base):
    __tablename__ = "problems"

    problem_id:  Mapped[uuid.UUID] = Column(UUID, primary_key=True, default=uuid.uuid4)
    title:       Mapped[str]       = Column(String(256), unique=True, nullable=False)
    difficulty:  Mapped[str]       = Column(String(16), nullable=False)  # "Easy" | "Medium" | "Hard"
    tags:        Mapped[list[str]] = Column(ARRAY(String), nullable=False, default=[])
                                      # ← GIN-indexed for array-contains queries
    description: Mapped[str]       = Column(Text, nullable=False)
    constraints: Mapped[str]       = Column(Text, nullable=False)
    code_stub:   Mapped[str]       = Column(Text, nullable=False)
                                      # ← Python function template, e.g. "def twoSum(nums, target):\n    "
    created_by:  Mapped[uuid.UUID] = Column(ForeignKey("users.user_id"), nullable=False)
    created_at:  Mapped[datetime]  = Column(DateTime(timezone=True), server_default=func.now())
```

```python
# models/test_case.py
class TestCase(Base):
    __tablename__ = "test_cases"

    test_case_id:    Mapped[uuid.UUID] = Column(UUID, primary_key=True, default=uuid.uuid4)
    problem_id:      Mapped[uuid.UUID] = Column(ForeignKey("problems.problem_id", ondelete="CASCADE"), nullable=False)
    input_text:      Mapped[str]       = Column(Text, nullable=False)
    expected_output: Mapped[str]       = Column(Text, nullable=False)
    is_public:       Mapped[bool]      = Column(Boolean, nullable=False, default=False)
    order_index:     Mapped[int]       = Column(Integer, nullable=False, default=0)
                                         # ← deterministic execution order
```

```python
# models/submission.py
class Submission(Base):
    __tablename__ = "submissions"

    submission_id: Mapped[uuid.UUID]  = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id:       Mapped[uuid.UUID]  = Column(ForeignKey("users.user_id"), nullable=False, index=True)
    problem_id:    Mapped[uuid.UUID]  = Column(ForeignKey("problems.problem_id"), nullable=False, index=True)
    language:      Mapped[str]        = Column(String(16), nullable=False)  # "python3"
    source_code:   Mapped[str]        = Column(Text, nullable=False)
    verdict:       Mapped[str]        = Column(String(32), nullable=False, default="Pending")
                                        # ← "Pending" | "Running" | "Accepted" | "Wrong Answer"
                                        #   | "Time Limit Exceeded" | "Runtime Error"
    runtime_ms:    Mapped[int | None] = Column(Integer, nullable=True)
    memory_kb:     Mapped[int | None] = Column(Integer, nullable=True)
    submitted_at:  Mapped[datetime]   = Column(DateTime(timezone=True), server_default=func.now())
    completed_at:  Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None]    = Column(String(128), nullable=True, index=True)
                                              # ← hash(user_id + problem_id + source_code), 30s window
```

### Key design decisions for the data model

| Decision | Rationale |
|---|---|
| `idempotency_key` on Submission | Detects duplicate submissions within a 30-second window. Computed as `SHA256(user_id + problem_id + source_code)` on insert. The API checks for an existing row with the same key and `submitted_at > now() - 30s`; if found, returns 409 Conflict. |
| `TestCase.is_public` boolean | Separation of public (visible in problem view) and hidden test cases. The judge runs ALL test cases; `GET /problems/{id}` returns only `is_public=true` entries. |
| `TestCase.order_index` | Guarantees deterministic execution order. The judge runs test cases ascending by `order_index`. |
| `verdict` as a string enum on Submission | The submission row IS the queue entry — no separate `judge_queue` table. The judge worker polls `SELECT ... WHERE verdict = 'Pending' ORDER BY submitted_at LIMIT 1 FOR UPDATE SKIP LOCKED`. This is the MVP's PostgreSQL-backed queue (in place of a dedicated message broker). |
| GIN index on `problems.tags` | Enables efficient `@>` (array-contains) queries for tag filtering: `WHERE tags @> ARRAY['dp']`. |
| No `LeaderboardEntry` table | The MVP leaderboard is computed on the fly from the `submissions` table: `SELECT user_id, COUNT(DISTINCT problem_id) ... WHERE verdict = 'Accepted' GROUP BY user_id`. Cached in Redis for 30 seconds. A materialized view or denormalized table is a future optimization. |
| `code_stub` on Problem | The Python function template the client renders in the editor. The judge prepends this stub to the user's source code before execution. |

### Redis key patterns

| Key | Type | Purpose | TTL |
|---|---|---|---|
| `leaderboard:global` | String → JSON | Cached leaderboard result | 30s |
| `idempotency:{key}` | String → submission_id | Fast dedup check for submission idempotency | 30s |

## 3. API Contracts

All endpoints are mounted on the FastAPI app. Request/response bodies are JSON.
Authentication is via JWT Bearer token (except `/healthz`, `/auth/token`, and
`/leaderboard`).

### 3.1 Health

`GET /healthz` — Liveness probe.

```
Response 200:
  {"status": "ok"}
```

Used by the compose healthcheck. No auth required.

### 3.2 Authentication (supporting)

`POST /auth/token` — Login, returns JWT access token.

```
Request:
  {
    "username": str,
    "password": str
  }

Response 200:
  {
    "access_token": str,
    "token_type": "bearer",
    "user_id": "uuid",
    "role": "admin" | "user"
  }

Errors:
  401 — invalid username or password
```

**Supporting endpoint** — not an FR of its own; every authenticated flow obtains its
token here. Users are pre-seeded via Alembic migration (admin + regular users).

### 3.3 Problems (FR-1, FR-2, FR-3)

`POST /problems` — Create a coding problem. Admin only.

```
Request:
  {
    "title":       str,           // unique, 1-256 chars
    "difficulty":  "Easy" | "Medium" | "Hard",
    "tags":        [str, ...],    // e.g. ["arrays", "hash-table"]
    "description": str,
    "constraints": str,
    "code_stub":   str,           // Python function template
    "test_cases":  [              // at least 1 required
      {
        "input":     str,
        "expected_output": str,
        "is_public": bool
      }
    ]
  }

Response 201:
  {
    "problem_id":  "uuid",
    "title":       str,
    "difficulty":  str,
    "tags":        [str, ...],
    "description": str,
    "constraints": str,
    "code_stub":   str,
    "test_case_count": int,       // total test cases (public + hidden)
    "created_at":  "ISO8601"
  }

Errors:
  401 — missing or invalid JWT
  403 — authenticated but not admin
  409 — duplicate title
       Body: {"error": "Problem with this title already exists", "title": str}
  422 — missing required fields (title, difficulty, description, constraints, code_stub)
  422 — empty test_cases array
```

`GET /problems` — List/search problems with pagination and filtering.

```
Query params:
  page       int    (optional, default 1, min 1)
  limit      int    (optional, default 20, min 1, max 100)
  difficulty str    (optional: "Easy", "Medium", "Hard")
  tag        str    (optional: single tag filter, e.g. "arrays")

Response 200:
  {
    "items": [
      {
        "problem_id": "uuid",
        "title":      str,
        "difficulty": str,
        "tags":       [str, ...],
        "created_at": "ISO8601"
      }
    ],
    "total": int,
    "page":  int,
    "limit": int
  }

Errors:
  422 — invalid difficulty value (not one of Easy/Medium/Hard)
```

`GET /problems/{problem_id}` — Get a single problem by ID.

```
Response 200:
  {
    "problem_id":  "uuid",
    "title":       str,
    "difficulty":  str,
    "tags":        [str, ...],
    "description": str,
    "constraints": str,
    "code_stub":   str,
    "test_cases":  [                           // ← public test cases only
      {
        "test_case_id":    "uuid",
        "input":           str,
        "expected_output": str,
        "order_index":     int
      }
    ],
    "created_at":  "ISO8601"
  }

Errors:
  404 — problem not found
```

### 3.4 Submissions (FR-4, FR-5, FR-7)

`POST /submissions` — Submit solution for a problem. Auth required.

```
Request:
  {
    "problem_id":  "uuid",
    "language":    str,         // "python3" (MVP)
    "source_code": str
  }

Response 201:
  {
    "submission_id": "uuid",
    "problem_id":    "uuid",
    "language":      str,
    "verdict":       "Pending",
    "submitted_at":  "ISO8601"
  }

Errors:
  401 — missing or invalid JWT
  404 — problem not found
       Body: {"error": "Problem not found", "problem_id": str}
  409 — duplicate submission within 30s window (same user + problem + source_code)
       Body: {"error": "Duplicate submission", "submission_id": str}
  422 — unsupported language (MVP: only "python3" is valid)
       Body: {"error": "Unsupported language: <lang>", "supported_languages": ["python3"]}
  422 — missing required fields (problem_id, language, source_code)
```

**Internal flow:**
1. Validate JWT, extract user_id.
2. Validate language is "python3".
3. Validate problem exists.
4. Compute `idempotency_key = sha256(user_id + problem_id + source_code)`.
5. Check Redis `idempotency:{key}` → if hit, check DB for matching Submission within 30s → if found, 409.
6. INSERT Submission with `verdict='Pending'`, `idempotency_key`.
7. SET Redis `idempotency:{key} = submission_id EX 30`.
8. Return 201.

`GET /submissions/{submission_id}` — Poll for submission verdict. Auth required, own submissions only.

```
Response 200:
  {
    "submission_id": "uuid",
    "problem_id":    "uuid",
    "user_id":       "uuid",
    "language":      str,
    "verdict":       "Pending" | "Running" | "Accepted" | "Wrong Answer"
                     | "Time Limit Exceeded" | "Runtime Error",
    "runtime_ms":    int | null,         // populated when verdict is final
    "memory_kb":     int | null,         // populated when verdict is final
    "source_code":   str,
    "submitted_at":  "ISO8601",
    "completed_at":  "ISO8601" | null
  }

Errors:
  401 — missing or invalid JWT
  403 — submission belongs to a different user
       Body: {"error": "Not authorized to view this submission"}
  404 — submission not found
```

`GET /submissions?problem_id={id}` — List user's submissions for a problem (submission history). Auth required.

```
Query params:
  problem_id  uuid   (required)
  page        int    (optional, default 1, min 1)
  limit       int    (optional, default 50, min 1, max 100)

Response 200:
  {
    "items": [
      {
        "submission_id": "uuid",
        "problem_id":    "uuid",
        "language":      str,
        "verdict":       str,
        "runtime_ms":    int | null,
        "memory_kb":     int | null,
        "submitted_at":  "ISO8601"
      }
    ],
    "total": int,
    "page":  int,
    "limit": int
  }

Response 200 (empty):
  {"items": [], "total": 0, "page": 1, "limit": 50}

Errors:
  401 — missing or invalid JWT
  422 — missing problem_id query param
```

### 3.5 Leaderboard (FR-8)

`GET /leaderboard` — Global leaderboard ranked by distinct problems solved. Public (no auth required).

```
Query params:
  page   int   (optional, default 1, min 1)
  limit  int   (optional, default 100, min 1, max 500)

Response 200:
  {
    "entries": [
      {
        "username":        str,
        "problems_solved": int,
        "last_solved_at":  "ISO8601"
      }
    ],
    "total": int,
    "page":  int,
    "limit": int
  }
```

**Ranking:** Ordered by `problems_solved DESC`, tie-broken by `last_solved_at ASC` (earlier timestamp ranks higher). `last_solved_at` is the user's most recent `Accepted` `completed_at` timestamp.

**Internal flow:**
1. Check Redis `leaderboard:global` — if hit, return cached JSON.
2. Execute `SELECT u.username, COUNT(DISTINCT s.problem_id) as solved, MAX(s.completed_at) as last_solved FROM users u JOIN submissions s ON u.user_id = s.user_id WHERE s.verdict = 'Accepted' GROUP BY u.user_id, u.username ORDER BY solved DESC, last_solved ASC LIMIT ? OFFSET ?`.
3. Cache result in Redis with 30s TTL.
4. Return paginated slice.

## 4. Service Layer Design

### ProblemService (`services/problem_service.py`)

```
create_problem(db, user_id, title, difficulty, tags, description, constraints, code_stub, test_cases) → Problem
  └─ Verify user is admin (403 if not).
  └─ Validate title uniqueness. UNIQUE violation → 409.
  └─ INSERT Problem row.
  └─ INSERT TestCase rows (one per test_case in input).
  └─ Return 201 with problem + test_case_count.

list_problems(db, page, limit, difficulty, tag) → (items, total)
  └─ Build WHERE clause: optional difficulty filter, optional tag filter (tags @> ARRAY[tag]).
  └─ COUNT(*) for total.
  └─ SELECT with LIMIT/OFFSET, ordered by created_at DESC.
  └─ Return paginated response.

get_problem(db, problem_id) → Problem | None
  └─ SELECT Problem by ID.
  └─ Eager-load public TestCases (is_public=true) ordered by order_index.
  └─ Return problem with test_cases embedded, or 404.
```

### SubmissionService (`services/submission_service.py`)

```
create_submission(db, redis, user_id, problem_id, language, source_code) → Submission
  └─ Validate language is "python3" (422 if not).
  └─ Validate problem exists (404 if not).
  └─ Compute idempotency_key = sha256(user_id + problem_id + source_code).
  └─ Check Redis idempotency:{key}. On hit → check DB for existing within 30s → 409.
  └─ INSERT Submission (verdict="Pending", idempotency_key).
  └─ SET redis idempotency:{key} = submission_id EX 30.
  └─ Return 201.

get_submission(db, submission_id, requesting_user_id) → Submission
  └─ SELECT Submission by ID. Not found → 404.
  └─ If submission.user_id != requesting_user_id → 403.
  └─ Return submission with all fields.

list_submissions(db, user_id, problem_id, page, limit) → (items, total)
  └─ SELECT submissions WHERE user_id = ? AND problem_id = ?
     ORDER BY submitted_at DESC LIMIT ? OFFSET ?.
  └─ COUNT(*) for total.
  └─ Return paginated response.
```

### Judge Worker (`services/judge_service.py` and `judge/worker.py`)

The judge worker logic lives in the `judge/` package. In the shipped configuration it runs
as an asyncio background task started by the FastAPI app's lifespan, sharing the database;
it can also run as a standalone process via `python -m judge.runner`. It is not a FastAPI
route — it is an independent polling loop.

```
run_judge_loop(db_session_factory, poll_interval=0.5) → runs forever
  └─ LOOP:
       └─ SELECT submission_id, problem_id, source_code
          FROM submissions
          WHERE verdict = 'Pending'
          ORDER BY submitted_at
          LIMIT 1
          FOR UPDATE SKIP LOCKED
       └─ If none → sleep(poll_interval), continue.
       └─ UPDATE verdict = 'Running'.
       └─ SELECT test_cases WHERE problem_id = ? ORDER BY order_index.
       └─ For each test_case:
            └─ Execute source_code in sandbox subprocess (see §4.1).
            └─ If sandbox raises TimeoutError → verdict = 'Time Limit Exceeded', break.
            └─ If sandbox raises RuntimeError → verdict = 'Runtime Error', break.
            └─ Strip stdout, compare with test_case.expected_output.
            └─ If mismatch → verdict = 'Wrong Answer', break.
       └─ If all passed → verdict = 'Accepted'.
       └─ UPDATE submission SET verdict, runtime_ms, memory_kb, completed_at = now().
       └─ Invalidate Redis leaderboard cache.
       └─ COMMIT.

reprocess_submission(db, submission_id) → no-op if already final
  └─ SELECT verdict WHERE submission_id = ?.
  └─ If verdict is final (Accepted/Wrong Answer/TLE/RE) → skip (idempotent).
  └─ Otherwise proceed with judging.
```

#### 4.1 Sandbox (`judge/sandbox.py`)

```
execute_code(source_code, input_text, timeout_seconds=5) → (stdout, stderr, runtime_ms, memory_kb)
  └─ Write source_code + input_text to temp files.
  └─ Spawn subprocess: python3 -c "<source_code>" with stdin=input_text.
  └─ Set resource limits: timeout=5s (subprocess timeout).
  └─ Measure wall-clock runtime and peak memory (via resource.getrusage or /proc).
  └─ If timeout → raise TimeoutError.
  └─ If non-zero exit → raise RuntimeError(stderr).
  └─ Return (stdout, stderr, runtime_ms, memory_kb).
```

The `execute_code` interface abstracts the execution backend: the MVP ships a subprocess
executor with a hard 5-second timeout; a container-based sandbox (cgroups memory/CPU caps,
no network) is the production hardening path and slots in behind the same interface.

### LeaderboardService (`services/leaderboard_service.py`)

```
get_leaderboard(db, redis, page, limit) → (entries, total)
  └─ Check Redis leaderboard:global cache → if hit, return cached slice.
  └─ SELECT u.username, COUNT(DISTINCT s.problem_id) as solved,
          MAX(s.completed_at) as last_solved
     FROM users u
     JOIN submissions s ON u.user_id = s.user_id
     WHERE s.verdict = 'Accepted'
     GROUP BY u.user_id, u.username
     ORDER BY solved DESC, last_solved ASC
  └─ COUNT the full result set for total.
  └─ Cache full result in Redis with 30s TTL.
  └─ Slice for pagination, return.
```

### AuthService (`services/auth_service.py`)

```
authenticate_user(db, username, password) → (user, token) | None
  └─ SELECT User WHERE username = ?.
  └─ Verify password hash (bcrypt/argon2).
  └─ If valid → generate JWT (user_id, username, role, exp=24h). Return (user, token).
  └─ If invalid → None (401).

get_current_user(db, token) → User
  └─ Decode JWT, verify signature and expiry.
  └─ SELECT User by user_id from claims.
  └─ Return User or raise 401.

require_admin(user) → None
  └─ If user.role != "admin" → raise 403.
```

## 5. Key Decisions & Trade-offs

### D1: Judge queue — PostgreSQL polling vs. Redis-based queue

**Chosen:** PostgreSQL polling (`SELECT ... FOR UPDATE SKIP LOCKED` on the `submissions` table).

**Alternative:** Redis `BLPOP` on a `judge:queue` list. Faster dequeue, at-least-once semantics, persistent queue independent of the submissions table.

**Pro (chosen):** Single source of truth — the submission row IS the queue entry. No dual-write risk (insert submission + push to queue). No queue/schema drift. The verdict, runtime, and memory are updated in-place with one transaction. Operational simplicity — one database to back up, monitor, and restore.

**Con (chosen):** Polling overhead — the judge worker wakes every 0.5 seconds even when idle. At hundreds of submissions/sec (the full-scale design's ceiling), a DB-backed queue would hit contention on the index. Acceptable for MVP: the polling overhead is negligible at MVP traffic (tens of submissions per minute).

**Rationale:** A dedicated message queue (Kafka in the full-scale design) solves the throughput problem at 200+ submissions/sec with consumer groups and replay. The MVP has no such load — a single DB-backed polling worker is simpler. The `SKIP LOCKED` clause (Postgres 9.5+) allows multiple judge workers if needed, and the polling interval keeps idle CPU near zero.

### D2: Sandbox isolation — subprocess vs. Docker container vs. Firecracker

**Chosen (MVP):** Subprocess with timeout — `subprocess.run(timeout=5)`.

**Alternative (production):** Docker container with cgroups (256MB memory, no network, CPU limit). The full-scale design uses Firecracker microVMs for kernel-level isolation.

**Pro (chosen):** Zero infrastructure. Works without Docker daemon, kernel modules, or root. Fastest startup (no container/image pull). Deterministic timeout via `subprocess.run(timeout=5)` — the OS kills the process group on timeout.

**Con (chosen):** No isolation. Malicious code can read the filesystem, exhaust file descriptors, or fork-bomb. These risks are acceptable for an MVP with seeded admin users and no public registration. The `judge/sandbox.py` interface (`execute_code(source_code, input_text, timeout)`) abstracts the backend — swap to a container-based executor in production without changing the judge worker.

**Rationale:** A subprocess sandbox satisfies every FR-6 behavior (timeout, error capture, stdout comparison) and runs anywhere Python runs — including CI runners without Docker-in-Docker. The isolation upgrade path is an executor swap, not a redesign.

### D3: Leaderboard — computed query vs. materialized view vs. Redis ZSET

**Chosen:** Computed SQL query with Redis cache-aside (30s TTL).

**Alternative 1:** PostgreSQL materialized view (`CREATE MATERIALIZED VIEW leaderboard AS SELECT ...`). Refresh on schedule (`REFRESH MATERIALIZED VIEW CONCURRENTLY`). No cache layer needed.

**Alternative 2:** Redis ZSET (the full-scale design's approach). Judge worker calls `ZADD leaderboard <score> <user_id>` on every Accepted verdict. Client reads `ZREVRANGE` with `WITHSCORES`. True real-time, O(log N) writes, O(log N + M) reads.

**Pro (chosen):** Simplest to implement and reason about. The 30s cache means the leaderboard is at most 30 seconds stale — acceptable for REST polling (real-time push is a future phase). The SQL approach correctly handles tie-breaking (problems_solved DESC, last_solved_at ASC) with a single `ORDER BY`.

**Con (chosen):** Cache invalidation on every Accepted verdict means the next poll rebuilds the full leaderboard with a GROUP BY + JOIN across all submissions. At MVP scale (thousands of submissions, not millions), this is sub-100ms. The 30s TTL also means concurrent Accepted verdicts within a 30s window may show inconsistent rankings until the cache expires.

**Rationale:** The Redis ZSET approach is better for contest-scale traffic (100K users, real-time pushes) but overengineered for MVP. The cache-aside pattern with a 30s TTL is the smallest increment that works. When the cache is cold, the query runs fresh; when hot, reads are sub-1ms.

### D4: Submission idempotency — 30s window vs. hash-only vs. DB UNIQUE constraint

**Chosen:** Redis 30s cache + computed `idempotency_key` column with index.

**Alternative:** A UNIQUE constraint on `(user_id, problem_id, source_code_hash)`. Catches duplicates forever, no Redis dependency.

**Pro (chosen):** The 30-second window is the right UX: a user hammering "Submit" should see "Duplicate submission" within 30s, but after 30s they can intentionally resubmit (e.g., after fixing a typo). The Redis cache provides a sub-ms check before the DB insert. The `idempotency_key` index enables the 30s window query: `SELECT ... WHERE idempotency_key = ? AND submitted_at > now() - 30s`.

**Con (chosen):** Two sources of truth. If Redis is flushed, the idempotency check falls back to the DB query (slightly slower but correct). The 30s TTL means identical code resubmitted after 31 seconds creates a new submission — by design, not a bug.

**Rationale:** A short-lived dedup window matches how production judges behave. Permanent dedup (the alternative) would block a user from ever resubmitting code they wrote days ago, which is hostile UX.

### D5: Users — seed data vs. registration endpoint

**Chosen:** Pre-seeded users via Alembic data migration, plus a `POST /auth/token` login endpoint.

**Alternative:** Full registration endpoint `POST /users` with self-service signup. More complete, no pre-seeding required.

**Pro (chosen):** User registration is explicitly out of MVP scope. Pre-seeding keeps the scope tight — the database migration creates admin + regular users with known passwords. The login endpoint issues the JWT tokens every authenticated flow needs.

**Con (chosen):** Hardcoded seed data is not portable across environments. Adding a new test user requires a migration or seed script. Acceptable for MVP — the seed data is the single source of truth for the demo environment.

**Rationale:** Every authenticated flow needs a token. Rather than making user registration an untested dependency, the seed migration creates users with deterministic credentials; the acceptance suite reads these credentials from environment variables (`TEST_ADMIN_USERNAME`, `TEST_USER_PASSWORD`, etc.) and obtains tokens via `POST /auth/token`.

## 6. Module Layout

```
src/leetcode/                ← package name: leetcode (importable as leetcode.*)
├── __init__.py
├── main.py                  # create_app() factory + lifespan (starts judge task) + routers
├── config.py                # pydantic-settings: DATABASE_URL, REDIS_URL, JWT_SECRET
├── database.py              # SQLAlchemy async engine, get_session dependency
├── auth.py                  # JWT encode/decode, get_current_user dependency, require_admin
├── models/                  # SQLAlchemy ORM models
│   ├── user.py              # User
│   ├── problem.py           # Problem
│   ├── test_case.py         # TestCase
│   └── submission.py        # Submission
├── schemas/                 # Pydantic request/response DTOs
│   ├── auth.py              # TokenRequest, TokenResponse
│   ├── problem.py           # CreateProblemRequest, ProblemResponse, ProblemListItem
│   ├── submission.py        # CreateSubmissionRequest, SubmissionResponse, SubmissionListItem
│   └── leaderboard.py       # LeaderboardEntry, LeaderboardResponse
├── routers/                 # Thin HTTP layer
│   ├── auth.py              # POST /auth/token
│   ├── health.py            # GET /healthz
│   ├── problems.py          # POST /problems, GET /problems, GET /problems/{id}
│   ├── submissions.py       # POST /submissions, GET /submissions/{id}, GET /submissions
│   └── leaderboard.py       # GET /leaderboard
└── services/                # Business logic
    ├── auth_service.py      # authenticate_user, create_token, get_current_user
    ├── problem_service.py   # create_problem, list_problems, get_problem
    ├── submission_service.py # create_submission, get_submission, list_submissions
    ├── judge_service.py     # judging orchestration
    └── leaderboard_service.py # get_leaderboard, invalidate_cache

judge/                       ← judge worker package (asyncio task in-app, or standalone)
├── runner.py                # Standalone entry point: python -m judge.runner
├── worker.py                # Polling loop: claim → execute → update verdict
└── sandbox.py               # execute_code(source_code, input_text, timeout) → (stdout, err, ms, kb)

alembic/
└── versions/
    ├── 001_initial.py       # Creates users, problems, test_cases, submissions
    └── 002_seed_users.py    # Seeds admin + regular users with known passwords

tests/
├── conftest.py
├── test_health.py           # /healthz liveness
├── unit/                    # White-box service-layer tests
│   ├── test_auth_service.py
│   ├── test_problem_service.py
│   └── test_submission_service.py
└── functional/              # In-process integration tests (httpx ASGITransport)
    ├── conftest.py
    ├── test_problems.py
    ├── test_submissions.py
    └── test_leaderboard.py

verify/
├── manifest.env             # e2e verification configuration
└── acceptance/              # Black-box HTTP acceptance suite (one file per FR)
    ├── conftest.py
    ├── test_fr1_create_problem.py
    ├── test_fr2_list_problems.py
    ├── test_fr3_get_problem.py
    ├── test_fr4_submit_solution.py
    ├── test_fr5_get_verdict.py
    ├── test_fr6_judge_execution.py
    ├── test_fr7_submission_history.py
    └── test_fr8_leaderboard.py

DESIGN.md                    # This file
README.md                    # What it is, stack, quick start, API table
SPEC.md                      # Engineering spec
DEPLOY.md                    # Host run/teardown steps
Dockerfile
docker-compose.yml           # db + redis + app
pyproject.toml
.env.example
.github/workflows/           # lint.yml + ci.yml + functional.yml (see §9)
```

## 7. Functional Requirements → Acceptance Tests

Each FR maps to exactly one black-box acceptance test file in `verify/acceptance/`. The
suite runs over HTTP against the live, fully-migrated stack (API + judge + PostgreSQL +
Redis) and proves the externally observable contract.

| # | FR | Acceptance test | What it proves |
|---|----|-----------------|----------------|
| 1 | Create problem | `verify/acceptance/test_fr1_create_problem.py` | POST /problems → 201 with problem; missing title → 422; duplicate title → 409; unauthenticated → 401; non-admin → 403 |
| 2 | List/search problems | `verify/acceptance/test_fr2_list_problems.py` | GET /problems → 200 paginated; difficulty filter works; tag filter works; invalid difficulty → 422 |
| 3 | Get problem | `verify/acceptance/test_fr3_get_problem.py` | GET /problems/{id} → 200 with public test cases only; unknown ID → 404 |
| 4 | Submit solution | `verify/acceptance/test_fr4_submit_solution.py` | POST /submissions → 201 Pending; unsupported language → 422; unknown problem → 404; missing fields → 422; unauthenticated → 401 |
| 5 | Get verdict | `verify/acceptance/test_fr5_get_verdict.py` | GET /submissions/{id} → 200 with verdict + runtime/memory; cross-user → 403; unknown ID → 404 |
| 6 | Judge execution | `verify/acceptance/test_fr6_judge_execution.py` | Correct code → Accepted; wrong output → Wrong Answer; infinite loop → Time Limit Exceeded (5s); syntax error → Runtime Error; re-processing a judged submission is a no-op |
| 7 | Submission history | `verify/acceptance/test_fr7_submission_history.py` | GET /submissions?problem_id={id} → 200 paginated, most-recent-first, scoped to the requesting user; unauthenticated → 401; empty history → 200 [] |
| 8 | Leaderboard | `verify/acceptance/test_fr8_leaderboard.py` | GET /leaderboard → 200 ranked by problems_solved DESC; tie-break by earlier last-accepted timestamp; pagination works |

The acceptance suite reads its target and credentials from the environment:

| Variable | Purpose | Used by |
|----------|---------|---------|
| `API_BASE_URL` | Base URL of the running API | All tests |
| `TEST_ADMIN_USERNAME` / `TEST_ADMIN_PASSWORD` | Admin credentials (from seed data) | FR-1, FR-2, FR-3 |
| `TEST_USER_USERNAME` / `TEST_USER_PASSWORD` | Regular user credentials (from seed data) | FR-4, FR-5, FR-7 |
| `TEST_USER2_USERNAME` / `TEST_USER2_PASSWORD` | Second user (cross-user isolation, ranking) | FR-5, FR-8 |
| `TEST_USER3_USERNAME` / `TEST_USER3_PASSWORD` | Third user (leaderboard ranking) | FR-8 |

## 8. Test Scenarios

Beyond the per-FR acceptance contract, the important cross-cutting behaviors are pinned
by the in-process functional suite in `tests/functional/` (httpx `ASGITransport` against
the real app wired to real PostgreSQL + Redis):

| Behavior | Scenario | Functional test |
|----------|----------|-----------------|
| Idempotency | Duplicate problem title → 409 | `test_problems.py::test_fr1_create_problem_duplicate_title_409` |
| Idempotency | Identical code re-submitted within 30s → 409 duplicate | `test_submissions.py::test_fr4_submit_duplicate_409` |
| Authorization | Unauthenticated create/submit/history → 401 | `test_problems.py::test_fr1_create_problem_unauthenticated_401`, `test_submissions.py::test_fr4_submit_unauthenticated_401`, `test_submissions.py::test_fr7_submission_history_unauthenticated_401` |
| Authorization | Non-admin problem create → 403 | `test_problems.py::test_fr1_create_problem_non_admin_403` |
| Ownership | Reading another user's submission → 403; history is per-user | `test_submissions.py::test_fr5_get_submission_cross_user_403`, `test_submissions.py::test_fr7_submission_history_other_user_isolation` |
| Validation | Missing title / empty test_cases / missing fields / unsupported language → 422 | `test_problems.py::test_fr1_create_problem_missing_title_422`, `test_problems.py::test_fr1_create_problem_empty_test_cases_422`, `test_submissions.py::test_fr4_submit_missing_fields_422`, `test_submissions.py::test_fr4_submit_unsupported_language_422` |
| Validation | Invalid difficulty filter → 422; missing problem_id on history → 422 | `test_problems.py::test_fr2_list_problems_invalid_difficulty_422`, `test_submissions.py::test_fr7_submission_history_missing_problem_id_422` |
| Error paths | Unknown problem / submission → 404 | `test_problems.py::test_fr3_get_problem_not_found_404`, `test_submissions.py::test_fr4_submit_unknown_problem_404`, `test_submissions.py::test_fr5_get_submission_not_found_404` |
| Pagination | All list endpoints honor page/limit with total count | `test_problems.py::test_fr2_list_problems_pagination`, `test_submissions.py::test_fr7_submission_history_paginated`, `test_leaderboard.py::test_fr8_leaderboard_pagination` |
| Filtering | Difficulty and tag filters narrow results | `test_problems.py::test_fr2_list_problems_filter_by_difficulty`, `test_problems.py::test_fr2_list_problems_filter_by_tag` |
| Ordering | History most-recent-first; leaderboard solved DESC + earliest-tie-break | `test_submissions.py::test_fr7_submission_history_paginated`, `test_leaderboard.py` |
| Empty states | Empty history and empty leaderboard return 200 with empty items | `test_submissions.py::test_fr7_submission_history_empty`, `test_leaderboard.py::test_fr8_leaderboard_empty` |
| Liveness | `/healthz` returns `{"status": "ok"}` | `tests/test_health.py::test_healthz_returns_ok` |

The service-layer edge cases (idempotency-key computation, verdict transitions, tie-break
SQL, JWT validation) are additionally covered white-box in `tests/unit/`.

## 9. Test Results

All three suites run in GitHub Actions on every push to `main`, on every pull request,
and on a daily schedule. Current status:

[![Lint](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/lint.yml/badge.svg)](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/lint.yml)
[![CI](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/ci.yml)
[![Functional](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/functional.yml/badge.svg)](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/functional.yml)

| Workflow | Runs | What it verifies |
|----------|------|------------------|
| [Lint](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/lint.yml) | `ruff` 0.8.0 over the whole tree | Style + static checks are clean |
| [CI](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/ci.yml) | `unit` job: `pytest tests/unit/`; `e2e` job: Alembic migrations against PostgreSQL 16 + Redis 7 service containers, boots `uvicorn`, waits for `/healthz`, then runs the black-box acceptance suite `pytest verify/acceptance/` over HTTP | Service-layer logic, plus every FR-1…FR-8 acceptance contract against the live system (including judge execution) |
| [Functional](https://github.com/iliazlobin/sd-leetcode-backend-mvp/actions/workflows/functional.yml) | `pytest tests/functional/` in-process (ASGITransport) against PostgreSQL 16 + Redis 7 service containers | The HTTP contract and cross-cutting behaviors in §8 |

## 10. Run & Test Locally

```bash
# Start the stack (requires Docker)
docker compose up --build -d

# Run migrations + seed data (admin + regular users)
docker compose exec app alembic upgrade head

# Verify health
curl http://localhost:${APP_PORT:-8010}/healthz

# Obtain a token
curl -X POST http://localhost:${APP_PORT:-8010}/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# Run white-box tests
pip install -e ".[dev]"
pytest tests/unit/ tests/functional/ -v

# Run black-box acceptance against the running stack
API_BASE_URL=http://localhost:${APP_PORT:-8010} pytest verify/acceptance/ -v
```

See [README.md](README.md) for the quickstart and API reference, and
[DEPLOY.md](DEPLOY.md) for full deployment and teardown steps.
