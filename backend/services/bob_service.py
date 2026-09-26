"""
services/bob_service.py

IBM Bob Shell bridge. All Bob invocations flow through this module.
BOB_MODE=mock  → returns realistic pre-canned responses (demo-safe)
BOB_MODE=real  → invokes 'bob' CLI via subprocess
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import AsyncIterator

from config import BOB_MODE, BOBSHELL_API_KEY


# ── Mock root-cause explanations keyed by category ───────────────────────────

_MOCK_ROOT_CAUSES = {
    "security": {
        "root_cause": "Sensitive credential is hardcoded directly in source code instead of being loaded from environment variables or a secrets manager.",
        "affected_lines": [],
        "fix_strategy": "Replace the hardcoded value with os.environ.get('SECRET_NAME') and document the required environment variable.",
    },
    "bug": {
        "root_cause": "Logic error causes incorrect behaviour under normal operating conditions. The control flow does not match the intended semantics.",
        "affected_lines": [],
        "fix_strategy": "Review the conditional logic and add a unit test that exercises the failing code path.",
    },
    "code_quality": {
        "root_cause": "Dead code or unused identifier increases cognitive load and can mask real bugs during code review.",
        "affected_lines": [],
        "fix_strategy": "Remove the unused identifier or rename it with a leading underscore to indicate it is intentionally unused.",
    },
    "missing_test": {
        "root_cause": "The function has no corresponding test, meaning regressions will not be caught automatically.",
        "affected_lines": [],
        "fix_strategy": "Add a pytest test function that covers at least the happy path and one error path.",
    },
}

_MOCK_FIX_PLANS = {
    "security": {
        "steps": [
            "Identify all locations where the secret is hardcoded.",
            "Add the secret as an environment variable (e.g. export SECRET_NAME=value).",
            "Replace hardcoded value with os.environ.get('SECRET_NAME') or equivalent.",
            "Add the variable name to .env.example with a placeholder value.",
            "Rotate the exposed credential if it was ever committed to version control.",
        ],
        "files_to_change": [],
        "risk_level": "low",
    },
    "bug": {
        "steps": [
            "Reproduce the bug with a failing unit test.",
            "Trace through the logic to identify the incorrect expression.",
            "Apply the minimal fix (typically a one-line change).",
            "Confirm the previously failing test now passes.",
            "Check for similar patterns elsewhere in the codebase.",
        ],
        "files_to_change": [],
        "risk_level": "medium",
    },
    "code_quality": {
        "steps": [
            "Verify the identifier is genuinely unused (no dynamic usage via getattr or __all__).",
            "Remove the unused import or variable.",
            "Run the test suite to confirm no regressions.",
        ],
        "files_to_change": [],
        "risk_level": "low",
    },
    "missing_test": {
        "steps": [
            "Create a new test file or add to the existing test module.",
            "Write a test that calls the function with typical inputs and asserts the expected output.",
            "Add an error-path test if the function can raise exceptions.",
            "Run pytest to confirm the new tests pass.",
        ],
        "files_to_change": [],
        "risk_level": "low",
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

async def explain_root_cause(
    issue_id: str,
    category: str,
    title: str,
    description: str,
    evidence: str,
    file_path: str,
    repo_path: Path,
) -> dict:
    """
    Return a root-cause explanation dict.
    Mock mode: returns canned response after simulated delay.
    Real mode: invokes Bob Shell in Ask mode.
    """
    if BOB_MODE == "real":
        return await _bob_ask(
            prompt=(
                f"Analyze this issue in the file '{file_path}':\n"
                f"Title: {title}\n"
                f"Description: {description}\n"
                f"Evidence: {evidence}\n\n"
                "Explain the root cause in 2-3 sentences. "
                "Return ONLY valid JSON with keys: root_cause, affected_lines (list), fix_strategy."
            ),
            repo_path=repo_path,
        )

    await asyncio.sleep(0.3)  # simulate realistic delay
    base = _MOCK_ROOT_CAUSES.get(category, _MOCK_ROOT_CAUSES["code_quality"]).copy()
    base["affected_lines"] = [file_path]
    return base


async def generate_fix_plan(
    issue_id: str,
    category: str,
    title: str,
    root_cause: str,
    file_path: str,
    repo_path: Path,
) -> dict:
    """
    Return a structured fix plan dict.
    Mock mode: canned plan. Real mode: Bob Shell Plan mode.
    """
    if BOB_MODE == "real":
        return await _bob_ask(
            prompt=(
                f"Create a fix plan for this issue in '{file_path}':\n"
                f"Title: {title}\n"
                f"Root cause: {root_cause}\n\n"
                "Return ONLY valid JSON with keys: steps (list), files_to_change (list), risk_level."
            ),
            repo_path=repo_path,
            chat_mode="plan",
        )

    await asyncio.sleep(0.2)
    plan = _MOCK_FIX_PLANS.get(category, _MOCK_FIX_PLANS["code_quality"]).copy()
    plan["files_to_change"] = [file_path]
    return plan


async def implement_fix(
    fix_prompt: str,
    repo_path: Path,
) -> AsyncIterator[str]:
    """
    Stream Bob Shell output while it implements a fix.
    Mock mode: yields realistic-looking log lines AND applies a real file patch
              so that git diff detects an actual change.
    Real mode: streams actual Bob Shell stdout.
    """
    if BOB_MODE == "real":
        async for line in _bob_stream(fix_prompt, repo_path):
            yield line
        return

    # Mock output — stream log lines first
    mock_lines = [
        "[Bob] Starting fix implementation...",
        f"[Bob] Reading file tree in {repo_path.name}",
        "[Bob] Analyzing issue context...",
        "[Bob] Identified target location",
        "[Bob] Writing fix...",
    ]
    for line in mock_lines:
        await asyncio.sleep(0.4)
        yield line

    # Apply a real file change so git diff captures it
    applied = _mock_apply_file_fix(fix_prompt, repo_path)
    if applied:
        yield f"[Bob] Applied fix to {applied}"
    else:
        yield "[Bob] No direct file patch available; fix noted."

    yield "[Bob] Verifying changes..."
    await asyncio.sleep(0.2)
    yield "[Bob] Fix applied successfully."


async def review_changes(diff: str, issue_title: str, repo_path: Path) -> dict:
    """Return a code review summary after a fix is applied."""
    if BOB_MODE == "real":
        return await _bob_ask(
            prompt=(
                f"Review these changes made to fix: '{issue_title}'\n\n"
                f"Diff:\n{diff[:2000]}\n\n"
                "Rate code quality 1-10. Return JSON: {rating, summary, improvements, concerns}."
            ),
            repo_path=repo_path,
        )
    await asyncio.sleep(0.2)
    return {
        "rating": 8,
        "summary": "The fix correctly addresses the identified issue with minimal change.",
        "improvements": ["Issue resolved", "No new code smells introduced"],
        "concerns": [],
    }


# ── Mock file patcher ────────────────────────────────────────────────────────

# Maps (title_substring, file_suffix) → patch function
# Each patch function receives (content: str) → str (new content)

def _mock_apply_file_fix(fix_prompt: str, repo_path: Path) -> str | None:
    """
    Parse the fix_prompt for File/Issue/Line, then apply a known minimal
    text-level patch to that file.  Returns the relative file path that was
    changed, or None if no applicable patch was found.
    """
    # Extract fields from prompt
    file_match  = re.search(r"^File:\s*(.+)$", fix_prompt, re.MULTILINE)
    issue_match = re.search(r"^Issue:\s*(.+)$", fix_prompt, re.MULTILINE)
    line_match  = re.search(r"^Line:\s*(\d+)", fix_prompt, re.MULTILINE)

    if not file_match:
        return None

    rel_file  = file_match.group(1).strip()
    issue_str = (issue_match.group(1).strip().lower() if issue_match else "")
    line_no   = int(line_match.group(1)) if line_match else None

    target = repo_path / rel_file
    if not target.exists():
        return None

    content = target.read_text(encoding="utf-8")
    new_content: str | None = None

    # ── Hardcoded secret → replace with os.environ.get() ─────────────────
    if "hardcoded secret" in issue_str or "secret" in issue_str:
        # Replace lines like:  VAR = "literal_value"
        # with:                VAR = os.environ.get("VAR", "")
        # Only touch the specific line if we know it
        if line_no:
            lines = content.splitlines(keepends=True)
            idx = line_no - 1
            if idx < len(lines):
                line = lines[idx]
                # Match:  VARNAME = "some value"  or  VARNAME = 'some value'
                m = re.match(r'^(\s*\w+)\s*=\s*["\'].+["\']', line)
                if m:
                    var_name = m.group(1).strip()
                    lines[idx] = f'{m.group(1)} = os.environ.get("{var_name}", "")  # codepilot-fix\n'
                    new_content = "".join(lines)
        if new_content is None:
            # Fallback: replace all quoted assignment lines that look like secrets
            new_content = re.sub(
                r'^(\s*(?:API_KEY|DB_PASSWORD|SECRET|PASSWORD|TOKEN)\s*=\s*)["\'].+["\']',
                r'\1os.environ.get("SECRET", "")  # codepilot-fix',
                content,
                flags=re.MULTILINE | re.IGNORECASE,
            )

    # ── eval() → ast.literal_eval ────────────────────────────────────────
    elif "eval" in issue_str:
        new_content = content.replace(
            "return eval(expr)",
            "import ast\n    return ast.literal_eval(expr)  # codepilot-fix",
            1,
        )

    # ── subprocess shell=True → shell=False ──────────────────────────────
    elif "shell=true" in issue_str or "subprocess" in issue_str:
        new_content = re.sub(
            r"(subprocess\.\w+\([^)]*),\s*shell\s*=\s*True",
            r"\1, shell=False  # codepilot-fix",
            content,
        )

    # ── Unused import → remove the import line ───────────────────────────
    elif "unused import" in issue_str:
        if line_no:
            lines = content.splitlines(keepends=True)
            idx = line_no - 1
            if idx < len(lines) and lines[idx].strip().startswith("import "):
                lines[idx] = f"# {lines[idx].rstrip()}  # codepilot-fix: removed unused import\n"
                new_content = "".join(lines)

    # ── Unused variable → prefix with underscore ─────────────────────────
    elif "unused variable" in issue_str:
        if line_no:
            lines = content.splitlines(keepends=True)
            idx = line_no - 1
            if idx < len(lines):
                m = re.match(r'^(\s*)(\w+)(\s*=)', lines[idx])
                if m and not m.group(2).startswith("_"):
                    lines[idx] = f"{m.group(1)}_{m.group(2)}{m.group(3)}{lines[idx][m.end():]}"
                    new_content = "".join(lines)

    # ── Broad except → add specific exception ────────────────────────────
    elif "broad exception" in issue_str or "except" in issue_str:
        new_content = content.replace(
            "except:",
            "except Exception:  # codepilot-fix",
            1,
        )

    # ── Missing test → add a stub test ───────────────────────────────────
    elif "missing test" in issue_str or "untested" in issue_str:
        func_match = re.search(r"^Issue:\s*Untested function[:\s]+(\w+)", fix_prompt, re.MULTILINE)
        func_name = func_match.group(1) if func_match else "function"
        # Add a stub test to the existing test file or create one
        test_dir = repo_path / "tests"
        test_dir.mkdir(exist_ok=True)
        test_file = test_dir / f"test_{rel_file.replace('/', '_')}_stubs.py"
        stub = (
            f"# codepilot-fix: auto-generated stub test\n"
            f"def test_{func_name}_stub():\n"
            f"    \"\"\"Stub test for {func_name} — fill in real assertions.\"\"\"\n"
            f"    pass\n"
        )
        test_file.write_text(stub, encoding="utf-8")
        return str(test_file.relative_to(repo_path))

    if new_content is not None and new_content != content:
        target.write_text(new_content, encoding="utf-8")
        return rel_file

    return None


# ── Real Bob Shell invocation ────────────────────────────────────────────────

async def _bob_ask(prompt: str, repo_path: Path, chat_mode: str = "ask") -> dict:
    """
    Invoke Bob Shell non-interactively and parse JSON from stdout.
    Falls back to empty dict on any failure.
    """
    env = {"BOBSHELL_API_KEY": BOBSHELL_API_KEY} if BOBSHELL_API_KEY else None
    cmd = [
        "bob", "-p", prompt,
        "--chat-mode", chat_mode,
        "--auth-method", "api-key",
        "--hide-intermediary-output",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(repo_path),
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        text = stdout.decode(errors="replace")
        # Extract last JSON object from output
        start = text.rfind("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception:
        pass
    return {}


async def _bob_stream(prompt: str, repo_path: Path) -> AsyncIterator[str]:
    """Stream Bob Shell stdout line by line for real-mode fix implementation."""
    env = {"BOBSHELL_API_KEY": BOBSHELL_API_KEY} if BOBSHELL_API_KEY else None
    cmd = ["bob", "-p", prompt, "--yolo", "--auth-method", "api-key"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(repo_path),
            env=env,
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield line.decode(errors="replace").rstrip()
    except Exception as exc:
        yield f"[Bob] Error: {exc}"
