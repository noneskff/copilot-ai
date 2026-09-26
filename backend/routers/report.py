"""
routers/report.py — Before/after health report endpoint.

GET  /api/repo/{repo_id}/report  — generate and return the full report
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from database import get_session
from models import Repository
from services import report_service

router = APIRouter(prefix="/api", tags=["report"])


@router.get("/repo/{repo_id}/report")
async def get_report(
    repo_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Generate (or regenerate) the before/after health report for a repository.
    Returns full JSON report including health scores, issue counts, fix summary,
    test results, and per-issue details.
    """
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found.")

    report = report_service.generate_report(repo_id)
    if "error" in report:
        raise HTTPException(status_code=500, detail=report["error"])

    return report
