"""
services/analysis_service.py

Orchestrates all static analyzers across a repository, persists issues,
invokes Bob Shell for root-cause explanation, and streams progress.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Callable, Awaitable

from sqlmodel import Session

from database import engine
from models import Issue, Repository
from analyzers.python_analyzer import analyze_file as py_analyze, find_untested_functions, RawIssue
from analyzers.js_analyzer import analyze_file as js_analyze
from services import bob_service

# File extensions handled by each analyzer
_PY_EXTS = {".py"}
_JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "target",
}


# ── Health-score helpers ──────────────────────────────────────────────────────

_SEVERITY_PENALTY = {"critical": 20, "high": 15, "medium": 8, "low": 3}


def compute_health_score(issues: list[RawIssue]) -> int:
    penalty = sum(_SEVERITY_PENALTY.get(i.severity, 0) for i in issues)
    return max(0, 100 - penalty)


# ── Main analysis orchestrator ────────────────────────────────────────────────

async def run_analysis(
    repo_id: str,
    repo_path: Path,
    tech_stack: str,
    progress_cb: Callable[[dict], Awaitable[None]] | None = None,
) -> list[Issue]:
    """
    Run full analysis on repo_path.
    progress_cb receives WebSocket-style event dicts.
    Returns persisted Issue objects.
    """

    async def emit(event: dict) -> None:
        if progress_cb:
            await progress_cb(event)

    await emit({"event": "progress", "step": "starting", "pct": 5,
                "message": "Starting analysis..."})

    raw_issues: list[RawIssue] = []

    # ── Python analysis ───────────────────────────────────────────────────
    if tech_stack in ("python", "unknown"):
        await emit({"event": "progress", "step": "python_scan", "pct": 15,
                    "message": "Scanning Python files..."})
        py_files = _collect_files(repo_path, _PY_EXTS)
        for abs_path, rel_path in py_files:
            raw_issues.extend(py_analyze(abs_path, rel_path))

        await emit({"event": "progress", "step": "missing_tests", "pct": 35,
                    "message": "Checking test coverage..."})
        raw_issues.extend(find_untested_functions(repo_path))

    # ── JS/TS analysis ────────────────────────────────────────────────────
    if tech_stack in ("javascript", "typescript", "unknown"):
        await emit({"event": "progress", "step": "js_scan", "pct": 45,
                    "message": "Scanning JS/TS files..."})
        js_files = _collect_files(repo_path, _JS_EXTS)
        for abs_path, rel_path in js_files:
            raw_issues.extend(js_analyze(abs_path, rel_path))

    await emit({"event": "progress", "step": "dedup", "pct": 55,
                "message": f"Found {len(raw_issues)} raw issues. Deduplicating..."})

    raw_issues = _deduplicate(raw_issues)

    # ── Persist issues + call Bob for root-cause ──────────────────────────
    await emit({"event": "progress", "step": "bob_analysis", "pct": 60,
                "message": "IBM Bob is analyzing root causes..."})

    persisted: list[Issue] = []
    total = len(raw_issues)

    for idx, raw in enumerate(raw_issues):
        pct = 60 + int((idx / max(total, 1)) * 30)
        await emit({
            "event": "progress", "step": "bob_analysis", "pct": pct,
            "message": f"Bob analyzing issue {idx + 1}/{total}: {raw.title}",
        })

        # Call Bob for root-cause (async, mock or real)
        root_cause_data = await bob_service.explain_root_cause(
            issue_id="",
            category=raw.category,
            title=raw.title,
            description=raw.description,
            evidence=raw.evidence,
            file_path=raw.file_path,
            repo_path=repo_path,
        )

        issue = _persist_issue(repo_id, raw, root_cause_data)
        persisted.append(issue)

        await emit({
            "event": "issue_found",
            "issue": _issue_to_dict(issue),
        })

    # ── Update repo health score ──────────────────────────────────────────
    await emit({"event": "progress", "step": "scoring", "pct": 92,
                "message": "Computing health score..."})
    _update_repo_health(repo_id, raw_issues)

    await emit({"event": "done", "total_issues": len(persisted)})

    return persisted


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_files(
    repo_path: Path, extensions: set[str]
) -> list[tuple[Path, str]]:
    """Return (abs_path, rel_path) tuples for matching files, skipping skip-dirs."""
    result = []
    for f in repo_path.rglob("*"):
        if not f.is_file():
            continue
        # Skip directories by checking parents
        if any(part in _SKIP_DIRS for part in f.parts):
            continue
        if f.suffix.lower() in extensions:
            rel = str(f.relative_to(repo_path)).replace("\\", "/")
            result.append((f, rel))
    return result


def _deduplicate(issues: list[RawIssue]) -> list[RawIssue]:
    """Remove duplicate issues with the same file_path + line_number + title."""
    seen: set[tuple] = set()
    unique = []
    for iss in issues:
        key = (iss.file_path, iss.line_number, iss.title)
        if key not in seen:
            seen.add(key)
            unique.append(iss)
    return unique


def _persist_issue(repo_id: str, raw: RawIssue, root_cause_data: dict) -> Issue:
    issue = Issue(
        id=str(uuid.uuid4()),
        repo_id=repo_id,
        severity=raw.severity,
        category=raw.category,
        title=raw.title,
        description=raw.description,
        file_path=raw.file_path,
        line_number=raw.line_number,
        evidence=raw.evidence,
        suggested_fix=raw.suggested_fix,
        confidence=raw.confidence,
        root_cause=json.dumps(root_cause_data) if root_cause_data else None,
        affected_files=json.dumps([raw.file_path]),
        status="open",
    )
    with Session(engine) as session:
        session.add(issue)
        session.commit()
        session.refresh(issue)
    return issue


def _update_repo_health(repo_id: str, raw_issues: list[RawIssue]) -> None:
    score = compute_health_score(raw_issues)
    with Session(engine) as session:
        repo = session.get(Repository, repo_id)
        if repo:
            repo.health_score_before = score
            session.add(repo)
            session.commit()


def _issue_to_dict(issue: Issue) -> dict:
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
        "status": issue.status,
    }
