# System Design: LeetCode — Online Code Judge Platform

> Full target design from `System Design: LeetCode (v2026.06.30.1)` — Notion row 38fd8650-05a8-8153-8614-e0b53039e116

## 1. Problem

LeetCode serves ~300,000 registered users who practice coding on ~4,000 problems across 20+ languages. The platform also hosts weekly coding competitions drawing 100,000 concurrent contestants — a 30× traffic spike over baseline that lands in the first 60 seconds. The hard part is running untrusted user code inside a secure sandbox, at scale, returning a verdict (pass/fail/runtime) within 5 seconds, while keeping contest scoring fair regardless of queue depth.

### Architecture overview

```
flowchart LR
    subgraph Clients
        WEB[Web App — Monaco Editor]
        CLI[CLI / API clients]
    end
    subgraph Edge
        LB[Load Balancer — TLS termination]
        GW[API Gateway — auth + rate limit]
    end
    subgraph Core
        PS[Problem Service — CRUD + search]
        SS[Submission Service — validate + enqueue]
        CS[Contest Service — registration + timer]
    end
    subgraph Stores
        DB[(PostgreSQL — problems, users, history)]
        K[Kafka — judge queue RF=3]
        R[(Redis — leaderboard + session)]
    end
    WEB -->|HTTPS| LB
    CLI -->|HTTPS| LB
    LB --> GW
    GW --> PS
    GW --> SS
    GW --> CS
    PS --> DB
    SS --> K
    SS --> DB
    CS --> R
    CS --> DB
```

## 2. Requirements

### Functional

- **FR1:** Browse and search ~4,000 problems by difficulty, tags, and acceptance rate.
- **FR2:** View problem description, examples, constraints, and language-specific code stubs.
- **FR3:** Submit solution in 20+ languages; receive verdict within 5 seconds.
- **FR4:** Join timed coding contests; submit solutions under contest rules with live standings.
- **FR5:** View per-contest leaderboard ranked by problems solved then total penalty time.
- **FR6:** Browse personal submission history with verdict, runtime, memory, and timestamp.

### Non-functional

- **NFR1:** Untrusted code must run in full kernel isolation with zero host access.
- **NFR2:** p95 submission-to-verdict latency ≤ 5 seconds at steady state.
- **NFR3:** Handle 100K concurrent contestants at 200+ submissions/sec burst.
- **NFR4:** Contest scoring uses server-side submission timestamp; queue wait never penalizes rank.

### Out of scope (MVP)

- 20+ language support → MVP supports Python 3 only
- Kafka judge queue → MVP uses PostgreSQL-backed queue
- Firecracker microVMs → MVP uses Docker containers with resource limits
- Contest live WebSocket leaderboard → MVP uses REST polling
- S3 test case storage → MVP stores test cases in PostgreSQL

## 3. Back of the envelope

- **Peak submission rate:** 200 submissions/sec × 60 sec burst = 12,000 submissions in first minute
- **Daily submission storage:** 30 submissions/sec avg × 86,400 sec × 1 KB/submission ≈ 2.6 GB/day
- **Leaderboard memory:** 100K users × (64-bit score + 32-bit user_id) ≈ 1.2 MB per contest

## 4. Entities & API

### Data Model

```sql
User {
  user_id:       uuid PK
  username:      text    ← unique
  email:         text    ← unique
  password_hash: text
  created_at:    timestamp
}

Problem {
  problem_id:    uuid PK
  title:         text    ← indexed
  difficulty:    enum    ← Easy/Medium/Hard
  tags:          text[]  ← GIN-indexed
  description:   text
  constraints:   text
  acceptance:    float
  created_at:    timestamp
}

Submission {
  submission_id: uuid PK
  user_id:       uuid FK → User
  problem_id:    uuid FK → Problem
  language:      text
  source_code:   text
  verdict:       enum    ← Pending/Running/Accepted/Wrong Answer/TLE/RE/CE
  runtime_ms:    integer
  memory_kb:     integer
  submitted_at:  timestamp
  completed_at:  timestamp
}

TestCase {
  test_case_id:  uuid PK
  problem_id:    uuid FK → Problem
  input:         text
  expected_output: text
  is_public:     boolean
}

Contest {
  contest_id:    uuid PK
  title:         text
  start_time:    timestamp
  end_time:      timestamp
  problems:      uuid[]  ← FK → Problem
}

ContestRegistration {
  registration_id: uuid PK
  user_id:       uuid FK → User
  contest_id:    uuid FK → Contest
  registered_at: timestamp
}

LeaderboardEntry {
  contest_id:    uuid FK → Contest
  user_id:       uuid FK → User
  problems_solved: integer
  penalty_time:  integer   ← minutes
  last_submitted: timestamp
}
```

### API

- `GET /problems?page=1&limit=100&difficulty=medium&tags=dp` — browse/search problems
- `GET /problems/{problem_id}?language=python3` — view problem with code stub
- `POST /submissions` — submit solution `{problem_id, language, source_code}`
- `GET /submissions/{submission_id}` — poll verdict + result
- `GET /contests/{contest_id}/leaderboard?page=1&limit=100` — view leaderboard
- `POST /contests/{contest_id}/register` — register for contest
- `WS /submissions/{submission_id}/updates` — real-time verdict push (full design; MVP: polling)

## 5. High-Level Design

### FR1: Problem browsing & search

- API Gateway validates JWT and rate limits (10 req/s per user)
- Problem Service queries PostgreSQL read replica with GIN index on `tags`
- Response includes pagination metadata
- Read replicas handle browse traffic (99% of requests, <10ms p99)

### FR2: Problem view with code stub

- Problem Service fetches problem metadata from PostgreSQL
- Code stub extracted from `code_stubs` JSON column: `{"python3": "class Solution:\n    def ..."}`
- Full test cases remain in object storage (or DB); only stub and metadata returned to client
- Monaco Editor renders the stub in-browser with syntax highlighting

### FR3: Code submission & judging

- Submission flow:
  1. Client `POST /submissions {problem_id, language, source_code}`
  2. Submission Service validates: problem exists, language supported, rate limit (1 per 5s outside contest)
  3. Inserts submission row with `verdict=Pending`, returns `submission_id`
  4. Judge Worker dequeues submission (Kafka partition keyed by `problem_id` in full design; DB poll in MVP)
  5. Worker acquires warm sandbox (Firecracker microVM in full; Docker container in MVP)
  6. Worker writes source code to sandbox, runs against test cases
  7. Each test case: pipe input to stdin, capture stdout, compare with expected; stop on first WA (fail-fast)
  8. Worker writes final verdict to PostgreSQL and publishes to Redis pub/sub
  9. Client polls `GET /submissions/{id}` for verdict

- Submission service uses `idempotency_key = hash(user_id + problem_id + source_code)` to detect duplicates
  within a 30-second window

### FR4: Timed contests

- Contest Service validates: contest exists, registration open, user not already registered
- At contest start, Redis stores active contest metadata with TTL
- During contest, submissions include `contest_id` and are validated against the contest window
- At contest end: finalize leaderboard to PostgreSQL

### FR5: Contest leaderboard

- Judge Worker writes accepted verdict
- Redis ZSET stores composite score: `64-bit float = problems_solved * 1e9 - penalty_time`
- Clients poll leaderboard via REST (MVP); WebSocket push in full design
- Composite score encoding packs two-dimensional ranking into a single 64-bit float

### FR6: Submission history

- Submission Service queries PostgreSQL with composite index on `(user_id, submitted_at DESC)`
- Weekly range partitioning on `submissions` table
- Problem titles resolved via JOIN on `problems`

## 6. Deep Dives

### DD1: Secure code execution

**Decision — layered defense:**
1. Outer layer: Firecracker microVM (full design) / Docker container with resource limits (MVP)
2. Middle layer: seccomp-BPF syscall filtering (~30-call allowlist)
3. Inner layer: cgroups v2 (256 MB memory, 5-second CPU cap, empty network namespace)

Each layer assumes the one above it has failed. The KVM boundary is the primary isolation guarantee;
seccomp and cgroups are cheap defense-in-depth.

### DD2: Live competition leaderboard

**Decision — Redis ZSET with Lua atomicity:**
- Single Redis ZSET per contest: `ZADD contest:<id>:leaderboard <composite_score> <user_id>`
- Lua script runs atomically: checks duplicate problem, updates score
- PostgreSQL `contest_results` is the durable source of truth

### DD3: Competition traffic scaling

**Decision — scheduled pre-warming with lag-based pod scaling:**
- Pre-provision nodes 15 minutes before contest
- Scale pods to 30% of max (180 workers)
- Kafka consumer lag >100 → scale up pods on pre-warmed nodes
- Post-contest: scale back down after queue drains

## 7. Trade-offs

| Decision | Choice | Alternative | Why |
|---|---|---|---|
| Judge isolation | Firecracker microVM | Docker/gVisor | Kernel-level isolation, sub-25ms restore |
| Contest leaderboard | Redis ZSET | PostgreSQL | Atomic updates, 1ms reads, no write contention |
| Traffic scaling | Scheduled pre-warm | Reactive HPA | 60s cold start vs 5s pod ready on existing node |
| Queue | Kafka | RabbitMQ/SQS | Replay, consumer groups, RF=3 durability |
| Search | PostgreSQL GIN | Elasticsearch | Operational simplicity at 4K problem scale |
| Session store | Redis | JWT only | Contest timer precision + leaderboard caching |

## 8. References

1. Firecracker: Lightweight Virtualization for Serverless Applications (NSDI 2020)
2. CrackingWalnuts: LeetCode System Design
3. HLDI Handbook: Online Code Judge
4. HackerRank Engineering: Parallel Execution of Test Cases
5. Redis Leaderboard Documentation
6. Codeforces Creator AMA (Mike Mirzayanov)
7. CodeSignal: What We Learned When 10,000 Users Hit Our Platform
8. AtCoder New Judge System (November 2025)
