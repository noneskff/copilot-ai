"""
analyzers/js_analyzer.py

Regex-based static analysis for JavaScript and TypeScript files.
No external tools required. Detects eval, hardcoded secrets, and unsafe patterns.
"""
from __future__ import annotations

import re
from pathlib import Path
from analyzers.python_analyzer import RawIssue

_SECRET_PATTERNS = re.compile(
    r'(?i)(password|passwd|secret|api[_-]?key|auth[_-]?token|access[_-]?token'
    r'|private[_-]?key|client[_-]?secret)\s*[=:]\s*["\'][^"\']{4,}["\']'
)
_EVAL_PATTERN = re.compile(r'\beval\s*\(')
_DOCUMENT_WRITE = re.compile(r'\bdocument\.write\s*\(')
_INNER_HTML = re.compile(r'\.innerHTML\s*=')


def analyze_file(abs_path: Path, rel_path: str) -> list[RawIssue]:
    issues: list[RawIssue] = []
    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues

    lines = source.splitlines()

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("*"):
            continue

        if _SECRET_PATTERNS.search(line):
            issues.append(RawIssue(
                file_path=rel_path, line_number=lineno,
                category="security", severity="critical",
                title="Hardcoded Secret Detected",
                description="A secret/credential appears to be hardcoded in source.",
                evidence=_redact(stripped),
                suggested_fix="Move to environment variables (process.env.SECRET).",
                confidence=0.85,
            ))

        if _EVAL_PATTERN.search(line):
            issues.append(RawIssue(
                file_path=rel_path, line_number=lineno,
                category="security", severity="high",
                title="Dangerous eval() Usage",
                description="`eval()` executes arbitrary JS and is a security risk.",
                evidence=stripped,
                suggested_fix="Remove eval(); use JSON.parse() or a safe alternative.",
                confidence=0.9,
            ))

        if _DOCUMENT_WRITE.search(line):
            issues.append(RawIssue(
                file_path=rel_path, line_number=lineno,
                category="security", severity="medium",
                title="document.write() Usage",
                description="`document.write()` can enable XSS and is considered bad practice.",
                evidence=stripped,
                suggested_fix="Use DOM manipulation methods instead.",
                confidence=0.8,
            ))

        if _INNER_HTML.search(line):
            issues.append(RawIssue(
                file_path=rel_path, line_number=lineno,
                category="security", severity="medium",
                title="Potential XSS via innerHTML",
                description="Assigning to `.innerHTML` with unsanitized data enables XSS attacks.",
                evidence=stripped,
                suggested_fix="Use textContent or sanitize the input with DOMPurify.",
                confidence=0.75,
            ))

    return issues


def _redact(line: str) -> str:
    return re.sub(r'([=:]\s*["\'])[^"\']+(["\'])', r'\1[REDACTED]\2', line)
