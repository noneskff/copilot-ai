"""
services/test_service.py

Runs the repository's test suite and parses the results.
Supports pytest (Python) and jest/vitest (JavaScript/TypeScript).
"""
from __future__ import annotations

import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from database import engine
from models import TestRun


# ── Public API ────────────────────────────────────────────────────────────────

def run_tests(
    repo_id: str,
    repo_path: Path,
    tech_stack: str,
    fix_job_id: str | None = None,
) -> TestRun:
    """
    Run the test suite for the given repository and persist results.
    Returns the persisted TestRun record.
    """
    test_framework = _detect_framework(repo_path, tech_stack)
    output, passed, total, passed_count, failed_count = _execute(repo_path, test_framework)

    test_run = TestRun(
        id=str(uuid.uuid4()),
        repo_id=repo_id,
        fix_job_id=fix_job_id,
        output=output,
        passed=passed,
        tests_total=total,
        tests_passed=passed_count,
        tests_failed=failed_count,
        ran_at=datetime.now(timezone.utc),
    )
    with Session(engine) as session:
        session.add(test_run)
        session.commit()
        session.refresh(test_run)
    return test_run


def parse_pytest_output(output: str) -> tuple[int, int, int]:
    """
    Parse pytest stdout and return (total, passed, failed).
    """
    # e.g. "5 passed, 2 failed, 1 error in 0.42s"
    # or   "7 passed in 0.55s"
    passed = failed = total = 0
    m_passed = re.search(r"(\d+) passed", output)
    m_failed = re.search(r"(\d+) failed", output)
    m_error  = re.search(r"(\d+) error", output)

    if m_passed:
        passed = int(m_passed.group(1))
    if m_failed:
        failed += int(m_failed.group(1))
    if m_error:
        failed += int(m_error.group(1))
    total = passed + failed
    return total, passed, failed


# ── Framework detection ────────────────────────────────────────────────────────

def _detect_framework(repo_path: Path, tech_stack: str) -> str:
    """Return the test command to run."""
    if (repo_path / "pytest.ini").exists() or (repo_path / "conftest.py").exists():
        return "pytest"
    if tech_stack in ("javascript", "typescript"):
        pkg = repo_path / "package.json"
        if pkg.exists():
            content = pkg.read_text(errors="replace")
            if "vitest" in content:
                return "vitest"
            if "jest" in content:
                return "jest"
    # Default: pytest for python projects
    if tech_stack == "python":
        return "pytest"
    return "pytest"


# ── Execution ─────────────────────────────────────────────────────────────────

def _execute(
    repo_path: Path,
    framework: str,
) -> tuple[str, bool, int, int, int]:
    """
    Run the test command. Returns (output, overall_passed, total, passed, failed).
    """
    cmd_map = {
        "pytest":  ["python", "-m", "pytest", "--tb=short", "-q"],
        "jest":    ["npx", "jest", "--no-coverage"],
        "vitest":  ["npx", "vitest", "run"],
    }
    cmd = cmd_map.get(framework, ["python", "-m", "pytest", "--tb=short", "-q"])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        total, passed_count, failed_count = parse_pytest_output(output)
        overall_passed = result.returncode == 0
        return output, overall_passed, total, passed_count, failed_count
    except FileNotFoundError:
        # python not found — try py
        if cmd[0] == "python":
            try:
                alt_cmd = ["py"] + cmd[1:]
                result = subprocess.run(
                    alt_cmd,
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                output = result.stdout + result.stderr
                total, passed_count, failed_count = parse_pytest_output(output)
                overall_passed = result.returncode == 0
                return output, overall_passed, total, passed_count, failed_count
            except Exception as exc:
                output = f"[test runner error] {exc}"
                return output, False, 0, 0, 0
        output = f"[test runner not found] {cmd[0]}"
        return output, False, 0, 0, 0
    except subprocess.TimeoutExpired:
        output = "[test runner timeout] Tests took longer than 120 seconds."
        return output, False, 0, 0, 0
    except Exception as exc:
        output = f"[test runner error] {exc}"
        return output, False, 0, 0, 0
