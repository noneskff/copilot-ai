"""
routers/tests.py — Test execution endpoint.

POST /api/repo/{repo_id}/run-tests   — run the test suite, return results
GET  /api/repo/{repo_id}/test-runs   — list test runs for a repo
GET  /api/test-runs/{run_id}         — get a single test run
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session, engine
from models import Repository, TestRun
from services import test_service
from routers.ws import broadcast

router = APIRouter(prefix="/api", tags=["tests"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/repo/{repo_id}/run-tests")
async def run_tests(
    repo_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    fix_job_id: str | None = None,
) -> dict[str, Any]:
    """
    Trigger the test suite for a repository.
    Runs in background; streams results via WebSocket job_id.
    """
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found.")
    if repo.status not in ("ready", "analyzing"):
        raise HTTPException(status_code=400, detail="Repository is not ready for test execution.")

    background_tasks.add_task(
        _run_tests_bg,
        repo_id=repo_id,
        repo_path_str=repo.local_path,
        tech_stack=repo.tech_stack or "python",
        fix_job_id=fix_job_id,
    )

    return {
        "repo_id": repo_id,
        "status": "running",
        "message": "Test run started.",
    }


@router.get("/repo/{repo_id}/test-runs")
async def list_test_runs(
    repo_id: str,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all test runs for a repository, newest first."""
    stmt = (
        select(TestRun)
        .where(TestRun.repo_id == repo_id)
        .order_by(TestRun.ran_at.desc())  # type: ignore[arg-type]
    )
    runs = session.exec(stmt).all()
    return [_test_run_to_dict(r) for r in runs]


@router.get("/test-runs/{run_id}")
async def get_test_run(
    run_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Get a single test run by ID."""
    run = session.get(TestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"TestRun '{run_id}' not found.")
    return _test_run_to_dict(run)


# ── Background task ───────────────────────────────────────────────────────────

def _run_tests_bg(
    repo_id: str,
    repo_path_str: str,
    tech_stack: str,
    fix_job_id: str | None,
) -> None:
    import asyncio

    async def _inner() -> None:
        run = test_service.run_tests(
            repo_id=repo_id,
            repo_path=Path(repo_path_str),
            tech_stack=tech_stack,
            fix_job_id=fix_job_id,
        )
        event_type = "test_result"
        await broadcast(repo_id, {
            "event": event_type,
            "repo_id": repo_id,
            "fix_job_id": fix_job_id,
            "run_id": run.id,
            "passed": run.passed,
            "tests_total": run.tests_total,
            "tests_passed": run.tests_passed,
            "tests_failed": run.tests_failed,
        })

    asyncio.run(_inner())


# ── Serialiser ────────────────────────────────────────────────────────────────

def _test_run_to_dict(run: TestRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "repo_id": run.repo_id,
        "fix_job_id": run.fix_job_id,
        "passed": run.passed,
        "tests_total": run.tests_total,
        "tests_passed": run.tests_passed,
        "tests_failed": run.tests_failed,
        "output": run.output,
        "ran_at": run.ran_at.isoformat(),
    }
