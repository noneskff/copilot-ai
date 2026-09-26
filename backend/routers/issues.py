"""
routers/issues.py — Issue retrieval endpoints.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from database import get_session
from models import Issue

router = APIRouter(prefix="/api/issues", tags=["issues"])


def _issue_to_dict(issue: Issue) -> dict[str, Any]:
    root_cause = None
    if issue.root_cause:
        try:
            root_cause = json.loads(issue.root_cause)
        except Exception:
            root_cause = {"root_cause": issue.root_cause}
    return {
        "id": issue.id,
        "repo_id": issue.repo_id,
        "severity": issue.severity,
        "category": issue.category,
        "title": issue.title,
        "description": issue.description,
        "file_path": issue.file_path,
        "line_number": issue.line_number,
        "evidence": issue.evidence,
        "suggested_fix": issue.suggested_fix,
        "confidence": issue.confidence,
        "root_cause": root_cause,
        "fix_plan": json.loads(issue.fix_plan) if issue.fix_plan else None,
        "status": issue.status,
        "detected_at": issue.detected_at.isoformat(),
    }


@router.get("")
async def list_issues(
    repo_id: str = Query(..., description="Repository ID"),
    severity: str | None = Query(None),
    category: str | None = Query(None),
    file_path: str | None = Query(None),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """List issues for a repository with optional filters."""
    stmt = select(Issue).where(Issue.repo_id == repo_id)
    if severity:
        stmt = stmt.where(Issue.severity == severity)
    if category:
        stmt = stmt.where(Issue.category == category)
    if file_path:
        stmt = stmt.where(Issue.file_path == file_path)

    issues = session.exec(stmt.order_by(Issue.severity, Issue.detected_at)).all()
    return [_issue_to_dict(i) for i in issues]


@router.get("/{issue_id}")
async def get_issue(
    issue_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Get full details for a single issue."""
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found.")
    return _issue_to_dict(issue)
