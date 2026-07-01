# LeetCode MVP — Deploy Guide

## Prerequisites

- Docker & Docker Compose v2 (requires a running Docker daemon)
- Git
- Python 3.12+ (only if running acceptance tests on the host)

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url> && cd sd-leetcode-backend-mvp
cp .env.example .env          # edit if you need custom ports/secrets

# 2. Build the image, then start db + redis (NOT the app yet)
docker compose build
docker compose up -d db redis

# 3. Wait for PostgreSQL to be ready, then run migrations (schema + admin seed)
until docker compose exec -T db pg_isready -U leetcode; do sleep 1; done
docker compose run --rm -T app alembic -c /app/alembic.ini upgrade head

# 4. Start the app (now that the DB is migrated and seeded)
docker compose up -d app

# 5. Verify the API is responding
curl http://localhost:${APP_PORT:-8010}/healthz
# → {"status":"ok"}
```

> **Why the phased bring-up?** The app no longer calls `create_all()` on startup —
> Alembic owns the schema end-to-end. Migration `002_seed_users.py` seeds the admin
> user that acceptance tests need. Running `alembic upgrade head` BEFORE the app
> starts ensures the seed runs on a fresh DB and avoids `DuplicateTableError`.

## Architecture

| Service  | Image              | Host port    | Notes                        |
|----------|--------------------|--------------|------------------------------|
| `db`     | postgres:16-alpine | — (internal) | User: leetcode / leetcode    |
| `redis`  | redis:7-alpine     | — (internal) | Leaderboard cache            |
| `app`    | built from `.`     | 8010 → 8000  | FastAPI + judge worker       |

Only `app` publishes a port. `db` and `redis` are reachable only inside the compose network.

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable       | Default                                                    | Purpose                    |
|----------------|------------------------------------------------------------|----------------------------|
| `DATABASE_URL` | `postgresql+asyncpg://leetcode:leetcode@db:5432/leetcode`  | Async PG connection        |
| `REDIS_URL`    | `redis://redis:6379/0`                                     | Redis connection           |
| `JWT_SECRET`   | `change-me-in-production`                                  | JWT signing key            |
| `APP_PORT`     | `8010`                                                     | Host port for the API      |

## Testing

### Unit tests (white-box)

```bash
python -m pip install -e ".[dev]"
pytest tests/unit/ -v
```

### Functional tests (white-box, needs live PostgreSQL + Redis)

```bash
DATABASE_URL=postgresql+asyncpg://leetcode:leetcode@localhost:5432/leetcode \
REDIS_URL=redis://localhost:6379/0 \
JWT_SECRET=test-secret \
  pytest tests/functional/ -v
```

### Acceptance tests (black-box, against running stack)

```bash
# Stack must be up and healthy
API_BASE_URL=http://localhost:${APP_PORT:-8010} pytest verify/acceptance/ -v
```

## Logs

```bash
docker compose logs -f app      # API + judge worker
docker compose logs -f db       # PostgreSQL
docker compose logs -f redis    # Redis
```

## Teardown

```bash
docker compose down -v          # -v removes volumes (fresh DB next time)
```

## Healthchecks

All three services have Docker healthchecks:
- `db`: `pg_isready -U leetcode`
- `redis`: `redis-cli ping`
- `app`: Python urllib probe to `http://localhost:8000/healthz` (no curl in slim image)

## GitHub Copilot Code Review (advisory)

Enable in your repo: **Settings → Copilot → Code review → Enable**.
Copilot will automatically review new PRs with advisory comments.
