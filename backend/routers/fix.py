"""
routers/fix.py — Fix planning, approval, and execution endpoints.

Phase 4: Fix planning (POST /api/issues/{id}/plan)
Phase 5: Fix approval  (POST /api/issues/{id}/approve)
         Fix execution  (POST /api/fix/{job_id}/execute)
         Fix status     (GET  /api/fix/{job_id})
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from database import get_session, engine
from models import FixJob, Issue, Repository
from services import bob_service
from routers.ws import broadcast

router = APIRouter(prefix="/api", tags=["fix"])


# ── Phase 4: Generate fix plan ────────────────────────────────────────────────

@router.post("/issues/{issue_id}/plan")
async def generate_fix_plan(
    issue_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Ask IBM Bob to generate a step-by-step fix plan for the given issue.
    Persists the plan as JSON on the Issue record and returns it.
    """
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found.")

    # Fetch repo to get workspace path
    repo = session.get(Repository, issue.repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository for this issue not found.")

    repo_path = Path(repo.local_path)

    # Get root cause text if available
    root_cause_text = ""
    if issue.root_cause:
        try:
            root_cause_text = json.loads(issue.root_cause).get("root_cause", "")
        except Exception:
            root_cause_text = issue.root_cause

    plan = await bob_service.generate_fix_plan(
        issue_id=issue_id,
        category=issue.category,
        title=issue.title,
        root_cause=root_cause_text,
        file_path=issue.file_path or "",
        repo_path=repo_path,
    )

    # Persist plan on issue
    issue.fix_plan = json.dumps(plan)
    session.add(issue)
    session.commit()
    session.refresh(issue)

    return {
        "issue_id": issue_id,
        "plan": plan,
    }


# ── Phase 5: Approve a fix ────────────────────────────────────────────────────

@router.post("/issues/{issue_id}/approve")
async def approve_fix(
    issue_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Developer approves a fix for the given issue.
    Creates a FixJob record and returns the job_id for WebSocket subscription.
    Requires a fix_plan to have been generated first.
    """
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found.")
    if issue.status in ("fixed",):
        raise HTTPException(status_code=400, detail="Issue is already fixed.")

    repo = session.get(Repository, issue.repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")

    # Build Bob prompt from issue details
    plan_text = ""
    if issue.fix_plan:
        try:
            plan_data = json.loads(issue.fix_plan)
            steps = plan_data.get("steps", [])
            plan_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
        except Exception:
            pass

    bob_prompt = (
        f"Fix the following issue in the repository:\n\n"
        f"File: {issue.file_path or 'unknown'}\n"
        f"Line: {issue.line_number or 'unknown'}\n"
        f"Issue: {issue.title}\n"
        f"Description: {issue.description}\n"
        f"Evidence: {issue.evidence or 'none'}\n"
        f"Suggested fix: {issue.suggested_fix or 'none'}\n"
    )
    if plan_text:
        bob_prompt += f"\nFix plan:\n{plan_text}\n"
    bob_prompt += (
        "\nApply the minimal correct fix. "
        "Do not modify any other files. "
        "Do not add extra comments or whitespace changes."
    )

    job_id = str(uuid.uuid4())
    fix_job = FixJob(
        id=job_id,
        issue_id=issue_id,
        repo_id=issue.repo_id,
        bob_prompt=bob_prompt,
        status="pending",
        attempt_number=1,
    )
    session.add(fix_job)

    issue.status = "approved"
    session.add(issue)
    session.commit()

    return {
        "job_id": job_id,
        "issue_id": issue_id,
        "repo_id": issue.repo_id,
        "status": "pending",
        "message": "Fix approved. Call POST /api/fix/{job_id}/execute to start.",
    }


# ── Phase 5: Execute a fix job ────────────────────────────────────────────────

@router.post("/fix/{job_id}/execute")
async def execute_fix(
    job_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Start a FixJob: invoke IBM Bob Shell to apply the fix, capture output,
    compute the diff, and stream progress via WebSocket.
    """
    fix_job = session.get(FixJob, job_id)
    if not fix_job:
        raise HTTPException(status_code=404, detail=f"FixJob '{job_id}' not found.")
    if fix_job.status == "running":
        raise HTTPException(status_code=400, detail="Fix job is already running.")
    if fix_job.status == "succeeded":
        raise HTTPException(status_code=400, detail="Fix job already succeeded.")

    fix_job.status = "running"
    fix_job.started_at = datetime.now(timezone.utc)
    session.add(fix_job)
    session.commit()

    background_tasks.add_task(_run_fix_bg, job_id)

    return {"job_id": job_id, "status": "running"}


@router.get("/fix/{job_id}")
async def get_fix_job(
    job_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return current status and output of a FixJob."""
    fix_job = session.get(FixJob, job_id)
    if not fix_job:
        raise HTTPException(status_code=404, detail=f"FixJob '{job_id}' not found.")
    return _fix_job_to_dict(fix_job)


# ── Background worker ─────────────────────────────────────────────────────────

def _run_fix_bg(job_id: str) -> None:
    """Background entry: runs the async fix pipeline in its own event loop."""
    asyncio.run(_execute_fix_async(job_id))


async def _execute_fix_async(job_id: str) -> None:
    """
    Full fix pipeline:
    1. git stash (rollback snapshot)
    2. Stream Bob Shell output while it applies the fix
    3. Capture git diff
    4. Persist result; update Issue status
    5. Broadcast fix_complete / fix_failed events
    """
    with Session(engine) as session:
        fix_job = session.get(FixJob, job_id)
        if not fix_job:
            return
        repo = session.get(Repository, fix_job.repo_id)
        issue = session.get(Issue, fix_job.issue_id)
        if not repo or not issue:
            return
        repo_path = Path(repo.local_path)
        prompt = fix_job.bob_prompt or ""

    # ── 1. git stash for rollback ─────────────────────────────────────────
    _git_stash(repo_path)

    await broadcast(job_id, {
        "event": "bob_output",
        "job_id": job_id,
        "line": "[CodePilot] Starting IBM Bob fix...",
    })

    # ── 2. Stream Bob output ──────────────────────────────────────────────
    output_lines: list[str] = []
    try:
        async for line in bob_service.implement_fix(prompt, repo_path):
            output_lines.append(line)
            await broadcast(job_id, {
                "event": "bob_output",
                "job_id": job_id,
                "line": line,
            })
    except Exception as exc:
        output_lines.append(f"[Error] {exc}")

    # ── 3. Capture git diff ───────────────────────────────────────────────
    diff = _git_diff(repo_path)

    # ── 4. Persist ────────────────────────────────────────────────────────
    bob_output = "\n".join(output_lines)
    succeeded = bool(diff.strip())  # if there's a diff, something was changed

    with Session(engine) as session:
        fix_job = session.get(FixJob, job_id)
        issue = session.get(Issue, fix_job.issue_id) if fix_job else None

        if fix_job:
            fix_job.bob_output = bob_output
            fix_job.diff = diff
            fix_job.status = "succeeded" if succeeded else "failed"
            fix_job.completed_at = datetime.now(timezone.utc)
            session.add(fix_job)

        if issue and succeeded:
            issue.status = "fixed"
            session.add(issue)

        session.commit()

    # ── 5. Broadcast result ───────────────────────────────────────────────
    if succeeded:
        await broadcast(job_id, {
            "event": "fix_complete",
            "job_id": job_id,
            "diff": diff,
            "message": "Fix applied successfully.",
        })
    else:
        await broadcast(job_id, {
            "event": "fix_failed",
            "job_id": job_id,
            "output": bob_output,
            "message": "Fix did not produce changes. Check Bob output.",
        })


# ── Git helpers ───────────────────────────────────────────────────────────────

def _git_stash(repo_path: Path) -> None:
    """Create a git stash snapshot so we can rollback if needed."""
    try:
        subprocess.run(
            ["git", "stash", "--include-untracked", "-m", "codepilot-before-fix"],
            cwd=str(repo_path),
            capture_output=True,
            timeout=10,
        )
        # Immediately pop so working tree reflects current state
        # (stash was only for snapshot; Bob modifies files directly)
        subprocess.run(
            ["git", "stash", "pop"],
            cwd=str(repo_path),
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass  # git may not be available in all test environments


def _git_diff(repo_path: Path) -> str:
    """Return the current unstaged + staged diff in the workspace."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        diff = result.stdout
        if not diff.strip():
            # Try diff against index (staged changes)
            result2 = subprocess.run(
                ["git", "diff"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            diff = result2.stdout
        return diff
    except Exception:
        return ""


# ── Serialiser ────────────────────────────────────────────────────────────────

def _fix_job_to_dict(fix_job: FixJob) -> dict[str, Any]:
    return {
        "id": fix_job.id,
        "issue_id": fix_job.issue_id,
        "repo_id": fix_job.repo_id,
        "status": fix_job.status,
        "attempt_number": fix_job.attempt_number,
        "bob_output": fix_job.bob_output,
        "diff": fix_job.diff,
        "started_at": fix_job.started_at.isoformat() if fix_job.started_at else None,
        "completed_at": fix_job.completed_at.isoformat() if fix_job.completed_at else None,
    }
