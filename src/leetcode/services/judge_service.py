"""Judge orchestration + sandbox: code execution and verdict management."""

import asyncio
import logging
import os
import resource
import tempfile
import time
from datetime import UTC, datetime

from sqlalchemy import select, update

from ..models.submission import Submission
from ..models.test_case import TestCase

logger = logging.getLogger("judge")


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


class SandboxError(Exception):
    """Raised when user code exits with non-zero status."""

    def __init__(self, stderr: str):
        self.stderr = stderr
        super().__init__(stderr)


class SandboxTimeout(Exception):
    """Raised when user code exceeds the time limit."""
    pass


async def execute_code(
    source_code: str,
    input_text: str,
    timeout_seconds: float = 5.0,
) -> tuple[str, str, int, int]:
    """Execute Python source code in a subprocess with the given stdin input.

    Returns:
        Tuple of (stdout, stderr, runtime_ms, memory_kb).

    Raises:
        SandboxTimeout: If execution exceeds timeout.
        SandboxError: If execution fails (non-zero exit).
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, prefix="leetcode_judge_"
    ) as f:
        f.write(source_code)
        tmp_path = f.name

    try:
        start_time = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            "python3",
            tmp_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_set_limits if os.name != "nt" else None,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=input_text.encode()),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise SandboxTimeout(
                f"Execution timed out after {timeout_seconds}s"
            ) from None

        end_time = time.monotonic()
        runtime_ms = int((end_time - start_time) * 1000)

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        memory_kb = _get_peak_memory()

        if proc.returncode != 0:
            raise SandboxError(stderr)

        return stdout, stderr, runtime_ms, memory_kb

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _set_limits() -> None:
    """Set resource limits for the child process (pre-exec)."""
    try:
        mem_limit = 256 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
    except (ValueError, resource.error):
        pass

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    except (ValueError, resource.error):
        pass


def _get_peak_memory() -> int:
    """Get peak memory usage in KB. Returns 0 if unavailable."""
    try:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        return usage.ru_maxrss
    except (AttributeError, resource.error):
        return 0


# ---------------------------------------------------------------------------
# Judge cycle
# ---------------------------------------------------------------------------


async def invalidate_leaderboard(redis_client) -> None:
    """Invalidate leaderboard cache after an Accepted verdict."""
    if redis_client is not None:
        try:
            await redis_client.delete("leaderboard:global")
        except Exception:
            pass


async def run_judge_cycle(
    session_factory,
    redis_client=None,
) -> bool:
    """Run one judge cycle: claim a Pending submission, execute, update verdict.

    Returns True if work was done, False if no Pending submissions found.
    Uses SELECT ... FOR UPDATE SKIP LOCKED for safe concurrent polling.
    """
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Submission)
                .where(Submission.verdict == "Pending")
                .order_by(Submission.submitted_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            submission = result.scalar_one_or_none()

            if submission is None:
                return False

            submission.verdict = "Running"
            await session.flush()

            tc_result = await session.execute(
                select(TestCase)
                .where(TestCase.problem_id == submission.problem_id)
                .order_by(TestCase.order_index)
            )
            test_cases = tc_result.scalars().all()

        await session.commit()

        verdict = "Accepted"
        runtime_ms = 0
        memory_kb = 0

        try:
            for tc in test_cases:
                try:
                    stdout, _stderr, rt_ms, mem_kb = await execute_code(
                        submission.source_code,
                        tc.input_text,
                        timeout_seconds=5,
                    )
                    runtime_ms = max(runtime_ms, rt_ms)
                    memory_kb = max(memory_kb, mem_kb)

                    actual = stdout.strip()
                    expected = tc.expected_output.strip()
                    if actual != expected:
                        verdict = "Wrong Answer"
                        break
                except SandboxTimeout:
                    verdict = "Time Limit Exceeded"
                    break
                except SandboxError:
                    verdict = "Runtime Error"
                    break
        except SandboxTimeout:
            verdict = "Time Limit Exceeded"
        except SandboxError:
            verdict = "Runtime Error"

        async with session_factory() as session:
            async with session.begin():
                stmt = (
                    update(Submission)
                    .where(Submission.submission_id == submission.submission_id)
                    .values(
                        verdict=verdict,
                        runtime_ms=runtime_ms,
                        memory_kb=memory_kb,
                        completed_at=datetime.now(UTC),
                    )
                )
                await session.execute(stmt)

        if verdict == "Accepted":
            await invalidate_leaderboard(redis_client)

        return True
