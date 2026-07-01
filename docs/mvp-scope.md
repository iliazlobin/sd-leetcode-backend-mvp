# LeetCode — MVP Scope (the contract for what we build NOW)

This file is the **contract**. The architect turns it into `design.md` + the executable
`verify/acceptance/` suite; the verifier gates against the Acceptance Criteria below. Be concrete.

## Stack
Python 3.12 · FastAPI · PostgreSQL 16 · Redis 7 · pytest · httpx · Docker Compose · Alembic

## Scope
**In (build now):**
- Problem CRUD: create, list, search, get by ID
- Submission flow: submit code → queue → judge → verdict
- Judge worker: run Python code in Docker sandbox, compare output against test cases
- Submission history: list user's submissions by problem
- Basic leaderboard: sorted by problems solved
- REST API with JWT auth

**Out (later phases):**
- 20+ language support (Python only for MVP)
- Contest system (registration, timer, contest-scoped submissions)
- Real-time WebSocket updates (REST polling for MVP)
- Firecracker microVMs (Docker sandbox for MVP)
- S3 test case storage (PostgreSQL for MVP)
- Kafka judge queue (PostgreSQL-backed polling queue for MVP)
- User registration/management (seed data for MVP)

## Functional Requirements

- **FR-1** — **Create problem.** Admin creates a coding problem with title, description, difficulty, tags, constraints, and test cases (input + expected output pairs). `POST /problems` → `201` with problem resource; missing required fields → `422`.
- **FR-2** — **List/search problems.** User browses problems with pagination and optional filtering by difficulty and tag. `GET /problems?page=1&limit=20&difficulty=easy&tag=arrays` → `200` with paginated results; invalid difficulty → `422`.
- **FR-3** — **Get problem.** User fetches a single problem by ID with its description, constraints, code stub, and public test cases. `GET /problems/{problem_id}` → `200` with full problem resource; unknown ID → `404`.
- **FR-4** — **Submit solution.** User submits source code for a problem. The system validates the problem exists, enqueues the submission, and returns a submission ID with `verdict=Pending`. `POST /submissions {problem_id, language, source_code}` → `201` with submission resource; unknown problem → `404`; missing fields → `422`.
- **FR-5** — **Get submission verdict.** User polls for their submission result. The system returns the verdict (Accepted / Wrong Answer / Time Limit Exceeded / Runtime Error), runtime in ms, and memory in KB. `GET /submissions/{submission_id}` → `200` with verdict details; unknown submission → `404`; user can only view their own submissions → `403`.
- **FR-6** — **Judge execution.** A background worker dequeues pending submissions, executes the user's code in a sandboxed Docker container against the problem's test cases, and writes the verdict back. The worker stops on first failing test case (fail-fast). Accepted only if ALL test cases pass. Idempotent: re-processing an already-judged submission is a no-op.
- **FR-7** — **Submission history.** User views their submission history for a problem, ordered by most recent first. `GET /submissions?problem_id={id}&page=1&limit=50` → `200` with paginated list; missing auth → `401`.
- **FR-8** — **Leaderboard.** User views a global leaderboard ranked by number of distinct problems solved (highest first). `GET /leaderboard?page=1&limit=100` → `200` with usernames and solved counts; pagination support.

## Acceptance Criteria

- **AC-1 (FR-1)** — `POST /problems` with valid body → `201` with `{problem_id, title, difficulty, tags, ...}`. Missing `title` → `422`. Duplicate title → `409`. Unauthenticated → `401`.
- **AC-2 (FR-2)** — `GET /problems?page=1&limit=20` → `200` with `{items: [...], total, page, limit}`. `GET /problems?difficulty=hard&tag=dp` → `200` with filtered results. `?difficulty=invalid` → `422`.
- **AC-3 (FR-3)** — `GET /problems/{valid_id}` → `200` with `{problem_id, title, description, difficulty, tags, constraints, test_cases: [{input, expected_output, is_public: true}]}`. `GET /problems/{nonexistent}` → `404`.
- **AC-4 (FR-4)** — `POST /submissions {problem_id, language: "python3", source_code}` → `201` with `{submission_id, verdict: "Pending"}`. `POST /submissions {problem_id, language: "brainfuck"}` → `422` (unsupported language). `POST /submissions {problem_id: nonexistent}` → `404`.
- **AC-5 (FR-5)** — `GET /submissions/{pending_id}` → `200` with `verdict: "Pending"`. After judge runs: `GET /submissions/{id}` → `200` with `verdict: "Accepted"` and `runtime_ms`/`memory_kb` populated. `GET /submissions/{other_user_id}` → `403`.
- **AC-6 (FR-6)** — Submit correct solution → verdict = `Accepted`, all test cases passed. Submit solution with wrong output → verdict = `Wrong Answer` on first failing case. Submit infinite loop → verdict = `Time Limit Exceeded` after 5-second timeout. Submit syntax error → verdict = `Runtime Error`. Idempotent: re-submit identical code → new submission, but judge worker re-processing an already-judged submission is a no-op.
- **AC-7 (FR-7)** — `GET /submissions?problem_id={id}&page=1` → `200` with paginated list of user's submissions for that problem, ordered by `submitted_at DESC`. Unauthenticated → `401`. No submissions for problem → `200` with empty items.
- **AC-8 (FR-8)** — `GET /leaderboard?page=1&limit=100` → `200` with `{entries: [{username, problems_solved: N}, ...], total, page, limit}`. Multiple users with same count → tie-broken by earlier last-accepted timestamp. Pagination: page 2 returns next 100.

## Build Plan

> architect (design.md + verify/acceptance/ suite) → senior-engineer (scaffold + healthz) →
> staff-engineer (implement FRs, unit + functional tests) → verifier (GATE: all three layers green + ruff clean) →
> sre (compose + manifest.env + CI workflows) → writer (README + DESIGN.md + cleanup)
