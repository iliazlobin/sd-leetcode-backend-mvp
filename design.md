# LeetCode MVP — Architecture Design

> Adapts the full [System Design: LeetCode](docs/system-design.md) to the MVP scope defined in
> [docs/mvp-scope.md](docs/mvp-scope.md). This document is the concrete build contract —
> it specifies every entity, endpoint, and service decision the implementation must follow.
> It contains zero app code; the acceptance suite in `verify/acceptance/` enforces the FRs.

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

    subgraph judge["Judge Worker — separate process"]
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

**Layers:** Router (HTTP parse/validate/serialize, no business logic) → Service (business logic + data access) → Model (ORM, DB session). This is the standard FastAPI three-layer split from `SYSTEM-DESIGN-MVP-STANDARDS.md`.

**Judge worker** is a separate process that shares the PostgreSQL database with the API. It polls `submissions` for `verdict='Pending'`, executes user code in a sandboxed subprocess with a 5-second timeout, and writes the verdict back. The acceptance tests expect the judge to be running alongside the API.

**No Kafka, no Firecracker, no multi-language support, no WebSocket** — those are out of MVP scope per `docs/mvp-scope.md`. This MVP implements: problem CRUD → submit code → judge execution → poll verdict → submission history → leaderboard.

**Redis** serves one purpose in the MVP: caching the leaderboard (TTL 30s) to avoid a full GROUP BY scan on every poll. The full design's Redis ZSET leaderboard is the future path; MVP uses a simple cache-aside pattern.

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
                                        # ← "Pending" | "Running" | "Accepted" | "Wrong Answer" | "TLE" | "RE" | "CE"
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
| `verdict` as a string enum on Submission | The submission row IS the queue entry — no separate `judge_queue` table. The judge worker polls `SELECT ... WHERE verdict = 'Pending' ORDER BY submitted_at LIMIT 1 FOR UPDATE SKIP LOCKED`. This is the MVP's PostgreSQL-backed queue (replaces Kafka from the full design). |
| GIN index on `problems.tags` | Enables efficient `@>` (array-contains) queries for tag filtering: `WHERE tags @> ARRAY['dp']`. |
| No `LeaderboardEntry` table | The MVP leaderboard is computed on the fly from the `submissions` table: `SELECT user_id, COUNT(DISTINCT problem_id) ... WHERE verdict = 'Accepted' GROUP BY user_id`. Cached in Redis for 30 seconds. A materialized view or denormalized table is a future optimization. |
| `code_stub` on Problem | The Python function template the client renders in the editor. The judge prepends this stub to the user's source code before execution. |

### Redis key patterns

| Key | Type | Purpose | TTL |
|---|---|---|---|
| `leaderboard:global` | String → JSON | Cached leaderboard result | 30s |
| `idempotency:{key}` | String → submission_id | Fast dedup check for submission idempotency | 30s |

## 3. API Contracts

All endpoints are mounted on the FastAPI app. Request/response bodies are JSON. Authentication is via JWT Bearer token (except `/healthz` and `/auth/token`).

### 3.1 Health

`GET /healthz` — Liveness probe.

```
Response 200:
  {"status": "ok"}
```

Used by compose healthcheck. No auth required.

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

**Supporting endpoint** — not an FR, used by acceptance tests to obtain auth tokens. Users are pre-seeded via Alembic migration (admin + regular users).

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
    "verdict":       "Pending" | "Running" | "Accepted" | "Wrong Answer" | "TLE" | "RE" | "CE",
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

`GET /leaderboard` — Global leaderboard ranked by distinct problems solved. Public (no auth required per FR-8 spec; auth not mentioned in AC-8).

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

The judge worker runs as a separate process that shares the database. It is NOT mounted as a FastAPI route — it is an independent polling loop.

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
            └─ If sandbox raises TimeoutError → verdict = 'TLE', break.
            └─ If sandbox raises RuntimeError → verdict = 'RE', break.
            └─ Strip stdout, compare with test_case.expected_output.
            └─ If mismatch → verdict = 'Wrong Answer', break.
       └─ If all passed → verdict = 'Accepted'.
       └─ UPDATE submission SET verdict, runtime_ms, memory_kb, completed_at = now().
       └─ Invalidate Redis leaderboard cache.
       └─ COMMIT.

reprocess_submission(db, submission_id) → no-op if already final
  └─ SELECT verdict WHERE submission_id = ?.
  └─ If verdict is final (Accepted/WA/TLE/RE) → skip (idempotent).
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

**Production path:** The subprocess approach is for development/testing. In Docker Compose,
the judge worker runs code inside a Docker container with cgroups (256 MB memory, 5s CPU cap,
no network). The `judge/sandbox.py` `execute_code` function abstracts the execution backend
— swap subprocess for Docker SDK in production with the same interface.
```

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

**Con (chosen):** Polling overhead — the judge worker wakes every 0.5 seconds even when idle. At 200 submissions/sec (full design ceiling), a DB-backed queue would hit contention on the index. Acceptable for MVP: the polling overhead is negligible at MVP traffic (tens of submissions per minute).

**Rationale:** The full design's Kafka queue solves the throughput problem at 200+ submissions/sec with consumer groups and replay. MVP has no such load — a single DB-backed polling worker is simpler. The `SKIP LOCKED` clause (Postgres 9.5+) allows multiple judge workers if needed, and the polling interval keeps idle CPU near zero.

### D2: Sandbox isolation — subprocess vs. Docker container vs. Firecracker

**Chosen (MVP):** Subprocess with timeout — `subprocess.run(timeout=5)`.

**Alternative (production):** Docker container with cgroups (256MB memory, no network, CPU limit). The full design uses Firecracker microVMs for kernel-level isolation.

**Pro (chosen):** Zero infrastructure. Works without Docker daemon, kernel modules, or root. Fastest startup (no container/image pull). Directly runnable in the sandbox for dev/testing. Deterministic timeout via `subprocess.run(timeout=5)` — the O/S kills the process group on timeout.

**Con (chosen):** No isolation. Malicious code can read filesystem, exhaust file descriptors, or fork-bomb. These risks are acceptable for an MVP with seeded admin users and no public registration. The `judge/sandbox.py` interface (`execute_code(source_code, input_text, timeout)`) abstracts the backend — swap to Docker SDK in production without changing the judge worker.

**Rationale:** The acceptance suite needs the judge to run in the same process tree as the API (for sandbox CI testing). A subprocess approach satisfies all FR-6 acceptance criteria (timeout, error capture, stdout comparison) without requiring Docker in CI.

### D3: Leaderboard — computed query vs. materialized view vs. Redis ZSET

**Chosen:** Computed SQL query with Redis cache-aside (30s TTL).

**Alternative 1:** PostgreSQL materialized view (`CREATE MATERIALIZED VIEW leaderboard AS SELECT ...`). Refresh on schedule (`REFRESH MATERIALIZED VIEW CONCURRENTLY`). No cache layer needed.

**Alternative 2:** Redis ZSET (the full design's approach). Judge worker calls `ZADD leaderboard <score> <user_id>` on every Accepted verdict. Client reads `ZREVRANGE` with `WITHSCORES`. True real-time, O(log N) writes, O(log N + M) reads.

**Pro (chosen):** Simplest to implement and reason about. The 30s cache means the leaderboard is at most 30 seconds stale — acceptable for MVP REST polling (the full design uses WebSocket for real-time). The SQL approach correctly handles tie-breaking (problems_solved DESC, last_solved_at ASC) with a single `ORDER BY`.

**Con (chosen):** Cache invalidation on every Accepted verdict means the next poll rebuilds the full leaderboard with a GROUP BY + JOIN across all submissions. At MVP scale (thousands of submissions, not millions), this is sub-100ms. The 30s TTL also means concurrent Accepted verdicts within a 30s window may show inconsistent rankings until the cache expires.

**Rationale:** The full design's Redis ZSET approach is better for contest-scale traffic (100K users, real-time WebSocket pushes) but overengineered for MVP. The cache-aside pattern with a 30s TTL is the smallest increment that works. When the cache is cold, the query runs fresh; when hot, reads are sub-1ms.

### D4: Submission idempotency — 30s window vs. hash-only vs. DB UNIQUE constraint

**Chosen:** Redis 30s cache + computed `idempotency_key` column with index.

**Alternative:** A UNIQUE constraint on `(user_id, problem_id, source_code_hash)`. Catches duplicates forever, no Redis dependency.

**Pro (chosen):** The 30-second window is the right UX: a user hammering "Submit" should see "Duplicate submission" within 30s, but after 30s they can intentionally resubmit (e.g., after fixing a typo). The Redis cache provides a sub-ms check before the DB insert. The `idempotency_key` index enables the 30s window query: `SELECT ... WHERE idempotency_key = ? AND submitted_at > now() - 30s`.

**Con (chosen):** Two sources of truth. If Redis is flushed, the idempotency check falls back to the DB query (slightly slower but correct). The 30s TTL means identical code resubmitted after 31 seconds creates a new submission — by design, not a bug.

**Rationale:** LeetCode's production system does exactly this — a short-lived dedup window. Permanent dedup (the alternative) would block a user from ever resubmitting code they wrote days ago, which is hostile UX.

### D5: Users — seed data vs. registration endpoint

**Chosen:** Pre-seeded users via Alembic data migration, plus a `POST /auth/token` login endpoint.

**Alternative:** Full registration endpoint `POST /users` with self-service signup. More complete, no pre-seeding required.

**Pro (chosen):** User registration is explicitly out of MVP scope per `docs/mvp-scope.md`. Pre-seeding keeps the scope tight — the database migration creates admin + regular users with known passwords. The login endpoint provides the JWT token the acceptance tests need.

**Con (chosen):** Hardcoded seed data is not portable across environments. Adding a new test user requires a migration or seed script. Acceptable for MVP — the seed data is the single source of truth for the demo environment.

**Rationale:** Every acceptance test needs an auth token. Rather than making user registration an untested dependency, the seed migration creates users with deterministic credentials. The acceptance suite reads these credentials from environment variables (`TEST_ADMIN_USERNAME`, `TEST_USER_PASSWORD`, etc.) and obtains tokens via `POST /auth/token`.

## 6. Module Layout (implementation-ready)

```
src/leetcode/                ← package name: leetcode (importable as leetcode.*)
├── __init__.py
├── main.py                 # create_app() factory + lifespan + /healthz + mount routers
├── config.py               # pydantic-settings: DATABASE_URL, REDIS_URL, JWT_SECRET
├── database.py             # SQLAlchemy async engine, get_session dependency
├── auth.py                 # JWT encode/decode, get_current_user dependency, require_admin
├── models/
│   ├── __init__.py
│   ├── user.py             # User ORM model
│   ├── problem.py          # Problem ORM model
│   ├── test_case.py        # TestCase ORM model
│   └── submission.py       # Submission ORM model
├── schemas/
│   ├── __init__.py
│   ├── auth.py             # TokenRequest, TokenResponse
│   ├── problem.py          # CreateProblemRequest, ProblemResponse, ProblemListItem
│   ├── submission.py       # CreateSubmissionRequest, SubmissionResponse, SubmissionListItem
│   └── leaderboard.py      # LeaderboardEntry, LeaderboardResponse
├── routers/
│   ├── __init__.py
│   ├── auth.py             # POST /auth/token
│   ├── problems.py         # POST /problems, GET /problems, GET /problems/{id}
│   ├── submissions.py      # POST /submissions, GET /submissions/{id}, GET /submissions
│   └── leaderboard.py      # GET /leaderboard
└── services/
    ├── __init__.py
    ├── auth_service.py     # authenticate_user, create_token, get_current_user
    ├── problem_service.py  # create_problem, list_problems, get_problem
    ├── submission_service.py  # create_submission, get_submission, list_submissions
    ├── judge_service.py    # run_judge_loop, execute_and_verify (orchestration)
    └── leaderboard_service.py  # get_leaderboard, invalidate_cache

judge/                       ← judge worker — separate process, shares DB
├── __init__.py
├── runner.py               # Entry point: python -m judge.runner (polling loop + sandbox)
├── worker.py               # Polling loop: claim → execute → update verdict
└── sandbox.py              # execute_code(source_code, input_text, timeout) → (stdout, err, ms, kb)

alembic/
├── env.py
├── versions/
│   └── 001_initial.py      # Creates users (with seed data), problems, test_cases, submissions
│   └── 002_seed_users.py   # Seed admin + regular users with known passwords

tests/
├── conftest.py
├── unit/
│   ├── test_problem_service.py
│   ├── test_submission_service.py
│   ├── test_judge_service.py
│   ├── test_leaderboard_service.py
│   └── test_auth_service.py
└── functional/
    ├── conftest.py
    ├── test_problems.py
    ├── test_submissions.py
    └── test_leaderboard.py

verify/
├── manifest.env            # e2e-verify configuration (filled by SRE)
└── acceptance/             # Black-box HTTP contract (one per FR)
    ├── __init__.py
    ├── conftest.py
    ├── test_fr1_create_problem.py
    ├── test_fr2_list_problems.py
    ├── test_fr3_get_problem.py
    ├── test_fr4_submit_solution.py
    ├── test_fr5_get_verdict.py
    ├── test_fr6_judge_execution.py
    ├── test_fr7_submission_history.py
    └── test_fr8_leaderboard.py

docs/
├── system-design.md        # Full target design (from system-designs)
├── mvp-scope.md            # MVP contract (from build kickoff)
└── synthesis.md            # Writer's evidence-backed summary (added later)

design.md                   # This file
AGENTS.md                   # Agent workspace rules
KICKOFF.md                  # How to launch the build loop
README.md                   # What it is, stack, quick start, API table
DEPLOY.md                   # Host run/teardown steps
.gitignore
.env.example
pyproject.toml
Dockerfile
docker-compose.yml
```

### Tier assignments for implementation (per the kanban build plan)

| Task | Tier | Rationale |
|------|------|-----------|
| `models/*.py` (4 ORM models) | **staff** | Data model + migrations are load-bearing; wrong schema = broken system |
| `alembic/` migration (001_initial + 002_seed) | **staff** | Schema DDL must match models exactly; seed data must produce valid auth tokens |
| `services/submission_service.py` (create, dedup, idempotency) | **staff** | Core business logic: idempotency key computation, Redis cache interaction, 30s window dedup check |
| `services/judge_service.py` (orchestration) | **staff** | Correctness-critical: fail-fast logic, verdict transitions, atomic claim-and-update with SKIP LOCKED |
| `judge/worker.py` (polling loop) | **staff** | Concurrency-sensitive: FOR UPDATE SKIP LOCKED, transaction boundaries, idempotent reprocessing |
| `judge/sandbox.py` (code execution) | **staff** | Security boundary: subprocess isolation, timeout enforcement, stdout capture, error classification |
| `services/leaderboard_service.py` | **staff** | Core algorithm: GROUP BY + ORDER BY tie-breaking, Redis cache invalidation on verdict update |
| `services/auth_service.py` | **staff** | Security-sensitive: JWT signing/verification, password hashing, role-based access |
| `services/problem_service.py` | **senior** | CRUD with uniqueness check, array-contains filtering |
| `routers/*.py` (all 4) | **senior** | Thin HTTP glue: parse Pydantic, call service, serialize response |
| `schemas/*.py` (all 4) | **senior** | Pydantic DTOs: field validation, serialization config |
| `config.py` | **senior** | pydantic-settings boilerplate |
| `database.py` | **senior** | Engine + session factory |
| `main.py` | **senior** | App factory + lifespan + healthz + router mounting |
| `auth.py` (dependency callables) | **senior** | FastAPI dependencies: get_current_user, require_admin |
| `tests/unit/` | **senior** | Standard unit test scaffolding |
| `tests/functional/` | **senior** | ASGITransport integration tests |
| `Dockerfile` | **sre** | Multi-stage build |
| `docker-compose.yml` | **sre** | Service orchestration (db + redis + app + judge) |
| `.env.example` | **senior** | Documentation |
| `pyproject.toml` | **senior** | Dependency manifest |

## 7. Acceptance Criteria (build-gate checklist)

Each FR maps to exactly one black-box acceptance test in `verify/acceptance/`. All eight must pass against the running system for the build to ship.

| # | FR | Test file | What it proves |
|---|----|-----------|----------------|
| 1 | Create problem | `test_fr1_create_problem.py` | POST /problems → 201 with problem; missing title → 422; duplicate title → 409; unauthenticated → 401; non-admin → 403 |
| 2 | List problems | `test_fr2_list_problems.py` | GET /problems → 200 paginated; difficulty filter works; tag filter works; invalid difficulty → 422 |
| 3 | Get problem | `test_fr3_get_problem.py` | GET /problems/{id} → 200 with public test cases; unknown ID → 404 |
| 4 | Submit solution | `test_fr4_submit_solution.py` | POST /submissions → 201 Pending; unsupported language → 422; unknown problem → 404; missing fields → 422; unauth → 401 |
| 5 | Get verdict | `test_fr5_get_verdict.py` | GET /submissions/{id} → 200 with verdict; cross-user → 403; unknown ID → 404 |
| 6 | Judge execution | `test_fr6_judge_execution.py` | Correct code → Accepted; wrong output → WA; infinite loop → TLE; syntax error → RE; reprocessing is idempotent |
| 7 | Submission history | `test_fr7_submission_history.py` | GET /submissions?problem_id={id} → 200 paginated by user; unauth → 401; empty history → 200 [] |
| 8 | Leaderboard | `test_fr8_leaderboard.py` | GET /leaderboard → 200 ranked by problems_solved; tie-break by timestamp; pagination works |

## 8. Run & Test

```bash
# Start the stack (host-only, requires Docker)
docker compose up -d

# Run migrations + seed data
docker compose run app alembic upgrade head

# Start judge worker
docker compose run judge python -m judge.runner &

# Verify health
curl http://localhost:${APP_PORT:-8010}/healthz

# Obtain admin token (for acceptance tests)
curl -X POST http://localhost:${APP_PORT:-8010}/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# Run white-box tests (in sandbox)
pip install -e ".[dev]"
pytest tests/unit/ tests/functional/ -v

# Run black-box acceptance (against running system, judge worker must be running)
API_BASE_URL=http://localhost:${APP_PORT:-8010} \
TEST_ADMIN_USERNAME=admin \
TEST_ADMIN_PASSWORD=admin123 \
TEST_USER_USERNAME=alice \
TEST_USER_PASSWORD=alice123 \
pytest verify/acceptance/ -v
```

### Environment variables for acceptance tests

| Variable | Purpose | Used by |
|----------|---------|---------|
| `API_BASE_URL` | Base URL of the running API | All tests |
| `TEST_ADMIN_USERNAME` | Admin username (from seed data) | FR-1, FR-2, FR-3 |
| `TEST_ADMIN_PASSWORD` | Admin password (from seed data) | FR-1, FR-2, FR-3 |
| `TEST_USER_USERNAME` | Regular user username (from seed data) | FR-4, FR-5, FR-7 |
| `TEST_USER_PASSWORD` | Regular user password (from seed data) | FR-4, FR-5, FR-7 |
| `TEST_USER2_USERNAME` | Second regular user (from seed data) | FR-5 (cross-user isolation), FR-8 |
| `TEST_USER2_PASSWORD` | Second regular user password (from seed data) | FR-5, FR-8 |
