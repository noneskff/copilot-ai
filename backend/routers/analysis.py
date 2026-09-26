"""
routers/analysis.py — Analysis job endpoints.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import Repository, Issue
from services import analysis_service
from routers.ws import broadcast

router = APIRouter(prefix="/api", tags=["analysis"])


# ── Background task ────────────────────────────────────────────────────────

def _run_analysis_bg(repo_id: str, job_id: str) -> None:
    """Background entry point — runs asyncio analysis pipeline."""
    import asyncio
    from sqlmodel import Session
    from database import engine

    async def _inner():
        with Session(engine) as session:
            repo = session.get(Repository, repo_id)
            if not repo:
                return
            repo.status = "analyzing"
            session.add(repo)
            session.commit()
            repo_path = Path(repo.local_path)
            tech_stack = repo.tech_stack or "unknown"

        async def progress_cb(event: dict) -> None:
            event["job_id"] = job_id
            await broadcast(job_id, event)

        try:
            await analysis_service.run_analysis(
                repo_id=repo_id,
                repo_path=repo_path,
                tech_stack=tech_stack,
                progress_cb=progress_cb,
            )
            with Session(engine) as session:
                repo = session.get(Repository, repo_id)
                if repo:
                    repo.status = "ready"
                    session.add(repo)
                    session.commit()
        except Exception as exc:
            with Session(engine) as session:
                repo = session.get(Repository, repo_id)
                if repo:
                    repo.status = "error"
                    session.add(repo)
                    session.commit()
            await broadcast(job_id, {"event": "error", "message": str(exc), "job_id": job_id})

    asyncio.run(_inner())


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/repo/{repo_id}/analyze")
async def start_analysis(
    repo_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Start an analysis job for a ready repository."""
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found.")
    if repo.status not in ("ready", "analyzing"):
        raise HTTPException(
            status_code=400,
            detail=f"Repository must be in 'ready' state to analyze. Current: {repo.status}",
        )

    job_id = str(uuid.uuid4())

    # Store job_id in scan_metadata so frontend can connect to WS
    meta = {}
    if repo.scan_metadata:
        try:
            meta = json.loads(repo.scan_metadata)
        except Exception:
            pass
    meta["analysis_job_id"] = job_id
    repo.scan_metadata = json.dumps(meta)
    repo.status = "analyzing"
    session.add(repo)
    session.commit()

    background_tasks.add_task(_run_analysis_bg, repo_id, job_id)

    return {"repo_id": repo_id, "job_id": job_id, "status": "analyzing"}


@router.get("/repo/{repo_id}/analysis-status")
async def get_analysis_status(
    repo_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return analysis status and issue summary for a repository."""
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")

    issues = session.exec(select(Issue).where(Issue.repo_id == repo_id)).all()

    severity_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    category_counts: dict[str, int] = {}
    for iss in issues:
        severity_counts[iss.severity] = severity_counts.get(iss.severity, 0) + 1
        category_counts[iss.category] = category_counts.get(iss.category, 0) + 1

    # Extract job_id from metadata
    job_id = None
    if repo.scan_metadata:
        try:
            job_id = json.loads(repo.scan_metadata).get("analysis_job_id")
        except Exception:
            pass

    return {
        "repo_id": repo_id,
        "status": repo.status,
        "job_id": job_id,
        "total_issues": len(issues),
        "health_score": repo.health_score_before,
        "severity_counts": severity_counts,
        "category_counts": category_counts,
    }
