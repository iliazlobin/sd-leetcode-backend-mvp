# Stage 1: Builder
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml ./
COPY src/ src/
COPY judge/ judge/

# Install the package WITH its dependencies (fastapi, uvicorn, sqlalchemy, redis, …).
# `--no-deps` previously skipped them, so `uvicorn` was absent from the venv and the
# runtime CMD failed with `exec: "uvicorn": not found`. asyncpg kept explicit in case
# it isn't a declared dependency.
RUN pip install . && pip install asyncpg

# Stage 2: Runtime
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

RUN addgroup --system app && adduser --system --ingroup app app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY alembic.ini ./
COPY alembic/ alembic/

USER app

HEALTHCHECK --interval=5s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "leetcode.main:app", "--host", "0.0.0.0", "--port", "8000"]
