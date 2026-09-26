"""
services/report_service.py

Generates a before/after health report for a repository after fixes are applied.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from database import engine
from models import FixJob, Issue, Repository, TestRun
from services import bob_service


def generate_report(repo_id: str) -> dict[str, Any]:
    """
    Build a comprehensive before/after report for the given repository.
    Includes health scores, fix summary, test results, and code review from Bob.
    """
    with Session(engine) as session:
        repo = session.get(Repository, repo_id)
        if not repo:
            return {"error": f"Repository '{repo_id}' not found."}

        issues = session.exec(
            select(Issue).where(Issue.repo_id == repo_id)
        ).all()

        fix_jobs = session.exec(
            select(FixJob).where(FixJob.repo_id == repo_id)
        ).all()

        test_runs = session.exec(
            select(TestRun)
            .where(TestRun.repo_id == repo_id)
            .order_by(TestRun.ran_at.desc())  # type: ignore[arg-type]
        ).all()

    # ── Issue summary ─────────────────────────────────────────────────────
    total_issues = len(issues)
    fixed_issues = [i for i in issues if i.status == "fixed"]
    open_issues  = [i for i in issues if i.status == "open"]

    severity_breakdown: dict[str, dict[str, int]] = {
        sev: {"total": 0, "fixed": 0}
        for sev in ("critical", "high", "medium", "low")
    }
    for iss in issues:
        sev = iss.severity
        if sev in severity_breakdown:
            severity_breakdown[sev]["total"] += 1
            if iss.status == "fixed":
                severity_breakdown[sev]["fixed"] += 1

    category_breakdown: dict[str, int] = {}
    for iss in issues:
        category_breakdown[iss.category] = category_breakdown.get(iss.category, 0) + 1

    # ── Fix job summary ────────────────────────────────────────────────────
    succeeded_jobs = [j for j in fix_jobs if j.status == "succeeded"]
    failed_jobs    = [j for j in fix_jobs if j.status == "failed"]

    # Collect all diffs
    combined_diff = "\n".join(
        j.diff for j in succeeded_jobs if j.diff
    )

    # ── Test run summary ───────────────────────────────────────────────────
    latest_run = test_runs[0] if test_runs else None
    first_run  = test_runs[-1] if len(test_runs) > 1 else None

    test_summary: dict[str, Any] = {}
    if latest_run:
        test_summary = {
            "passed": latest_run.passed,
            "tests_total": latest_run.tests_total,
            "tests_passed": latest_run.tests_passed,
            "tests_failed": latest_run.tests_failed,
            "ran_at": latest_run.ran_at.isoformat(),
        }

    # ── Compute after health score ─────────────────────────────────────────
    # Health score after = based only on still-open issues
    from services.analysis_service import compute_health_score
    from analyzers.python_analyzer import RawIssue

    open_raw = [
        RawIssue(
            file_path=i.file_path or "",
            line_number=i.line_number or 0,
            category=i.category,
            severity=i.severity,
            title=i.title,
            description=i.description,
            evidence=i.evidence or "",
            suggested_fix=i.suggested_fix or "",
            confidence=i.confidence or 0.5,
        )
        for i in open_issues
    ]
    health_score_after = compute_health_score(open_raw)

    # Persist health_score_after on repo
    with Session(engine) as session:
        repo_upd = session.get(Repository, repo_id)
        if repo_upd:
            repo_upd.health_score_after = health_score_after
            session.add(repo_upd)
            session.commit()

    # ── Assemble report ────────────────────────────────────────────────────
    report: dict[str, Any] = {
        "repo_id": repo_id,
        "repo_name": repo.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health": {
            "before": repo.health_score_before,
            "after": health_score_after,
            "improvement": (
                (health_score_after - (repo.health_score_before or 0))
                if repo.health_score_before is not None
                else None
            ),
        },
        "issues": {
            "total": total_issues,
            "fixed": len(fixed_issues),
            "remaining": len(open_issues),
            "fix_rate_pct": (
                round(len(fixed_issues) / total_issues * 100)
                if total_issues > 0 else 0
            ),
            "severity_breakdown": severity_breakdown,
            "category_breakdown": category_breakdown,
        },
        "fixes": {
            "total_jobs": len(fix_jobs),
            "succeeded": len(succeeded_jobs),
            "failed": len(failed_jobs),
            "diff_preview": combined_diff[:3000] if combined_diff else None,
        },
        "tests": test_summary,
        "fixed_issue_list": [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "category": i.category,
                "file_path": i.file_path,
                "line_number": i.line_number,
            }
            for i in fixed_issues
        ],
        "open_issue_list": [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "category": i.category,
                "file_path": i.file_path,
                "line_number": i.line_number,
            }
            for i in open_issues
        ],
    }

    return report
