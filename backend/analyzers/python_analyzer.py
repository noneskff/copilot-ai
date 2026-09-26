"""
analyzers/python_analyzer.py

Pure-AST static analysis for Python files. No subprocess required.
Detects: unused imports, unused variables, broad exceptions, eval/exec,
         hardcoded secrets, insecure subprocess shell=True, syntax errors.
"""
from __future__ import annotations

import ast
import re
import tokenize
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Issue data class (raw, pre-persistence) ──────────────────────────────────

@dataclass
class RawIssue:
    file_path: str
    line_number: int
    category: str           # bug | code_quality | security | missing_test
    severity: str           # critical | high | medium | low
    title: str
    description: str
    evidence: str
    suggested_fix: str
    confidence: float       # 0.0–1.0


# ── Severity helpers ──────────────────────────────────────────────────────────

_SECRET_PATTERNS = re.compile(
    r'(?i)(password|passwd|secret|api[_-]?key|auth[_-]?token|access[_-]?token'
    r'|private[_-]?key|client[_-]?secret|db[_-]?pass)\s*=\s*["\'][^"\']{4,}["\']'
)


# ── Main entry point ──────────────────────────────────────────────────────────

def analyze_file(abs_path: Path, rel_path: str) -> list[RawIssue]:
    """Run all checks on a single Python file. Returns list of RawIssue."""
    issues: list[RawIssue] = []

    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues

    # 1. Syntax check
    try:
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError as exc:
        issues.append(RawIssue(
            file_path=rel_path,
            line_number=exc.lineno or 1,
            category="bug",
            severity="high",
            title="Syntax Error",
            description=f"Python syntax error: {exc.msg}",
            evidence=exc.text or "",
            suggested_fix="Fix the syntax error on this line.",
            confidence=1.0,
        ))
        return issues  # further AST analysis impossible

    lines = source.splitlines()

    # 2–6: AST-based checks
    issues.extend(_check_imports(tree, rel_path, lines))
    issues.extend(_check_broad_except(tree, rel_path, lines))
    issues.extend(_check_eval_exec(tree, rel_path, lines))
    issues.extend(_check_subprocess_shell(tree, rel_path, lines))
    issues.extend(_check_unused_variables(tree, rel_path, lines))

    # 7. Regex-based secret detection (works even if AST parse fails)
    issues.extend(_check_hardcoded_secrets(source, rel_path, lines))

    return issues


# ── Individual checkers ───────────────────────────────────────────────────────

def _get_line(lines: list[str], lineno: int) -> str:
    """Return source line (1-based), stripped."""
    idx = lineno - 1
    if 0 <= idx < len(lines):
        return lines[idx].strip()
    return ""


def _check_imports(tree: ast.Module, rel_path: str, lines: list[str]) -> list[RawIssue]:
    """Detect imported names that are never referenced in the module."""
    issues: list[RawIssue] = []

    # Collect all imported names with their line numbers
    imported: dict[str, int] = {}  # name -> lineno
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                imported[local_name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                imported[local_name] = node.lineno

    # Collect all Name usages outside of import statements
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # e.g. os.path — the root "os" counts as used
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used.add(root.id)

    for name, lineno in imported.items():
        if name not in used and not name.startswith("_"):
            issues.append(RawIssue(
                file_path=rel_path,
                line_number=lineno,
                category="code_quality",
                severity="low",
                title="Unused Import",
                description=f"'{name}' is imported but never used in this module.",
                evidence=_get_line(lines, lineno),
                suggested_fix=f"Remove the import of '{name}' or use it.",
                confidence=0.85,
            ))
    return issues


def _check_broad_except(tree: ast.Module, rel_path: str, lines: list[str]) -> list[RawIssue]:
    """Detect bare `except:` or `except Exception:` with only `pass`."""
    issues: list[RawIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            is_bare = handler.type is None
            is_base = (
                isinstance(handler.type, ast.Name)
                and handler.type.id in ("Exception", "BaseException")
            )
            if is_bare or is_base:
                body_stmts = [s for s in handler.body if not isinstance(s, ast.Pass)]
                if not body_stmts:
                    issues.append(RawIssue(
                        file_path=rel_path,
                        line_number=handler.lineno,
                        category="bug",
                        severity="medium",
                        title="Broad Exception Silenced",
                        description=(
                            "Bare `except:` or `except Exception: pass` silently swallows "
                            "all errors, masking bugs."
                        ),
                        evidence=_get_line(lines, handler.lineno),
                        suggested_fix="Catch a specific exception type and log or handle it.",
                        confidence=0.9,
                    ))
    return issues


def _check_eval_exec(tree: ast.Module, rel_path: str, lines: list[str]) -> list[RawIssue]:
    """Detect calls to eval() or exec() with non-constant arguments."""
    issues: list[RawIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name not in ("eval", "exec"):
            continue
        # Check if argument is a literal constant (safe)
        if node.args and isinstance(node.args[0], ast.Constant):
            continue
        issues.append(RawIssue(
            file_path=rel_path,
            line_number=node.lineno,
            category="security",
            severity="high",
            title=f"Dangerous {name}() Call",
            description=(
                f"`{name}()` executes arbitrary code. If the argument comes from user "
                "input this is a Remote Code Execution vulnerability."
            ),
            evidence=_get_line(lines, node.lineno),
            suggested_fix=f"Replace `{name}()` with a safe alternative (e.g. ast.literal_eval for data).",
            confidence=0.95,
        ))
    return issues


def _check_subprocess_shell(tree: ast.Module, rel_path: str, lines: list[str]) -> list[RawIssue]:
    """Detect subprocess calls with shell=True."""
    issues: list[RawIssue] = []
    _SUBPROCESS_FUNCS = {"run", "call", "check_call", "check_output", "Popen"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fn_name = None
        if isinstance(func, ast.Attribute) and func.attr in _SUBPROCESS_FUNCS:
            fn_name = func.attr
        elif isinstance(func, ast.Name) and func.id in _SUBPROCESS_FUNCS:
            fn_name = func.id

        if not fn_name:
            continue

        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                issues.append(RawIssue(
                    file_path=rel_path,
                    line_number=node.lineno,
                    category="security",
                    severity="high",
                    title="Insecure subprocess shell=True",
                    description=(
                        f"`subprocess.{fn_name}(..., shell=True)` enables shell injection. "
                        "Attackers can inject arbitrary shell commands if the command includes user input."
                    ),
                    evidence=_get_line(lines, node.lineno),
                    suggested_fix="Pass a list of arguments instead and remove shell=True.",
                    confidence=0.9,
                ))
    return issues


def _check_unused_variables(tree: ast.Module, rel_path: str, lines: list[str]) -> list[RawIssue]:
    """
    Detect local variables assigned but never read within the same function.
    Only flags simple Name assignments (not augmented assignments, not underscore names).
    """
    issues: list[RawIssue] = []

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._check_func(node)
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def _check_func(self, func: ast.FunctionDef) -> None:
            assigned: dict[str, int] = {}   # name -> lineno
            used: set[str] = set()

            for stmt in ast.walk(func):
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and not target.id.startswith("_"):
                            assigned[target.id] = stmt.lineno
                elif isinstance(stmt, ast.Name) and isinstance(stmt.ctx, ast.Load):
                    used.add(stmt.id)

            for name, lineno in assigned.items():
                if name not in used:
                    issues.append(RawIssue(
                        file_path=rel_path,
                        line_number=lineno,
                        category="code_quality",
                        severity="low",
                        title="Unused Variable",
                        description=f"Variable '{name}' is assigned but never used.",
                        evidence=_get_line(lines, lineno),
                        suggested_fix=f"Remove the assignment or use '{name}'.",
                        confidence=0.75,
                    ))

    _Visitor().visit(tree)
    return issues


def _check_hardcoded_secrets(source: str, rel_path: str, lines: list[str]) -> list[RawIssue]:
    """Regex-based detection of hardcoded secrets and API keys."""
    issues: list[RawIssue] = []
    for lineno, line in enumerate(lines, start=1):
        if _SECRET_PATTERNS.search(line):
            issues.append(RawIssue(
                file_path=rel_path,
                line_number=lineno,
                category="security",
                severity="critical",
                title="Hardcoded Secret Detected",
                description=(
                    "A password, API key, or secret token appears to be hardcoded in source code. "
                    "This exposes credentials to anyone with repository access."
                ),
                evidence=_redact(line.strip()),
                suggested_fix="Move secrets to environment variables or a secrets manager.",
                confidence=0.88,
            ))
    return issues


def _redact(line: str) -> str:
    """Replace the value portion of a secret line with [REDACTED]."""
    return re.sub(r'(=\s*["\'])[^"\']+(["\'])', r'\1[REDACTED]\2', line)


# ── Missing-test detector ─────────────────────────────────────────────────────

def find_untested_functions(repo_path: Path) -> list[RawIssue]:
    """
    Compare public functions/classes in source files against test files.
    Returns RawIssue entries for each function with no corresponding test.
    """
    issues: list[RawIssue] = []

    # Collect all public functions defined in non-test source files
    source_funcs: list[tuple[str, str, int]] = []  # (rel_path, func_name, lineno)
    test_names: set[str] = set()

    for py_file in repo_path.rglob("*.py"):
        rel = str(py_file.relative_to(repo_path)).replace("\\", "/")
        is_test = "test_" in py_file.name or "/tests/" in rel or "\\tests\\" in rel
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if is_test:
                    test_names.add(name)  # e.g. "test_process_all"
                    if name.startswith("test_"):
                        test_names.add(name[5:])  # e.g. "process_all"
                elif not name.startswith("_"):
                    source_funcs.append((rel, name, node.lineno))

    for rel_path, func_name, lineno in source_funcs:
        # covered if test_<name> exists or <name> (stripped from test_<name>) exists
        if func_name not in test_names and f"test_{func_name}" not in test_names:
            issues.append(RawIssue(
                file_path=rel_path,
                line_number=lineno,
                category="missing_test",
                severity="low",
                title=f"No Test for '{func_name}'",
                description=f"Function '{func_name}' in {rel_path} has no corresponding test.",
                evidence=f"def {func_name}(...)",
                suggested_fix=f"Add a test function named 'test_{func_name}' in the tests/ directory.",
                confidence=0.7,
            ))
    return issues
