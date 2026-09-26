"""
tests/test_analyzers.py — Unit tests for Phase 3 static analyzers.
"""
from __future__ import annotations

import ast
import io
import zipfile
from pathlib import Path

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from analyzers.python_analyzer import (
    analyze_file, find_untested_functions, RawIssue,
    _check_broad_except, _check_eval_exec, _check_hardcoded_secrets,
    _check_imports, _check_subprocess_shell, _check_unused_variables,
)
from analyzers.js_analyzer import analyze_file as js_analyze_file
from services.analysis_service import compute_health_score, _deduplicate


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_py_file(tmp_path: Path, name: str, content: str) -> tuple[Path, str]:
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f, name


def _parse(source: str):
    return ast.parse(source)


# ── Python analyzer — individual checks ──────────────────────────────────────

class TestUnusedImport:
    def test_detects_unused_import(self, tmp_path):
        f, rel = _make_py_file(tmp_path, "a.py", "import os\nx = 1\n")
        issues = analyze_file(f, rel)
        assert any(i.title == "Unused Import" and "os" in i.description for i in issues)

    def test_used_import_not_flagged(self, tmp_path):
        f, rel = _make_py_file(tmp_path, "b.py", "import os\nprint(os.getcwd())\n")
        issues = analyze_file(f, rel)
        assert not any(i.title == "Unused Import" for i in issues)

    def test_unused_from_import(self, tmp_path):
        f, rel = _make_py_file(tmp_path, "c.py", "from pathlib import Path\nx = 1\n")
        issues = analyze_file(f, rel)
        assert any(i.title == "Unused Import" and "Path" in i.description for i in issues)

    def test_used_from_import_not_flagged(self, tmp_path):
        f, rel = _make_py_file(tmp_path, "d.py", "from pathlib import Path\np = Path('.')\n")
        issues = analyze_file(f, rel)
        assert not any(i.title == "Unused Import" for i in issues)


class TestBroadExcept:
    def test_bare_except_detected(self, tmp_path):
        src = "def f():\n    try:\n        pass\n    except:\n        pass\n"
        f, rel = _make_py_file(tmp_path, "e.py", src)
        issues = analyze_file(f, rel)
        assert any(i.title == "Broad Exception Silenced" for i in issues)

    def test_except_exception_pass_detected(self, tmp_path):
        src = "def f():\n    try:\n        pass\n    except Exception:\n        pass\n"
        f, rel = _make_py_file(tmp_path, "f.py", src)
        issues = analyze_file(f, rel)
        assert any(i.title == "Broad Exception Silenced" for i in issues)

    def test_specific_except_not_flagged(self, tmp_path):
        src = "def f():\n    try:\n        pass\n    except ValueError:\n        pass\n"
        f, rel = _make_py_file(tmp_path, "g.py", src)
        issues = analyze_file(f, rel)
        assert not any(i.title == "Broad Exception Silenced" for i in issues)

    def test_except_with_body_not_flagged(self, tmp_path):
        src = "def f():\n    try:\n        pass\n    except Exception as e:\n        print(e)\n"
        f, rel = _make_py_file(tmp_path, "h.py", src)
        issues = analyze_file(f, rel)
        assert not any(i.title == "Broad Exception Silenced" for i in issues)


class TestEvalExec:
    def test_eval_with_variable_detected(self, tmp_path):
        src = "def f(x):\n    return eval(x)\n"
        f, rel = _make_py_file(tmp_path, "i.py", src)
        issues = analyze_file(f, rel)
        assert any("eval" in i.title for i in issues)

    def test_eval_with_constant_not_flagged(self, tmp_path):
        src = "result = eval('1 + 2')\n"
        f, rel = _make_py_file(tmp_path, "j.py", src)
        issues = analyze_file(f, rel)
        assert not any("eval" in i.title for i in issues)

    def test_exec_detected(self, tmp_path):
        src = "def run(code):\n    exec(code)\n"
        f, rel = _make_py_file(tmp_path, "k.py", src)
        issues = analyze_file(f, rel)
        assert any("exec" in i.title for i in issues)

    def test_eval_severity_is_high(self, tmp_path):
        src = "def f(x):\n    return eval(x)\n"
        f, rel = _make_py_file(tmp_path, "l.py", src)
        issues = analyze_file(f, rel)
        eval_issues = [i for i in issues if "eval" in i.title]
        assert eval_issues[0].severity == "high"


class TestSubprocessShell:
    def test_shell_true_detected(self, tmp_path):
        src = "import subprocess\nsubprocess.run(cmd, shell=True)\n"
        f, rel = _make_py_file(tmp_path, "m.py", src)
        issues = analyze_file(f, rel)
        assert any("shell=True" in i.title for i in issues)

    def test_shell_false_not_flagged(self, tmp_path):
        src = "import subprocess\nsubprocess.run(['ls', '-l'], shell=False)\n"
        f, rel = _make_py_file(tmp_path, "n.py", src)
        issues = analyze_file(f, rel)
        assert not any("shell=True" in i.title for i in issues)

    def test_subprocess_popen_shell_true(self, tmp_path):
        src = "import subprocess\nsubprocess.Popen(cmd, shell=True)\n"
        f, rel = _make_py_file(tmp_path, "o.py", src)
        issues = analyze_file(f, rel)
        assert any("shell=True" in i.title for i in issues)


class TestHardcodedSecrets:
    def test_api_key_detected(self, tmp_path):
        src = 'API_KEY = "abc123secretvalue"\n'
        f, rel = _make_py_file(tmp_path, "p.py", src)
        issues = analyze_file(f, rel)
        assert any(i.title == "Hardcoded Secret Detected" for i in issues)

    def test_password_detected(self, tmp_path):
        src = 'password = "hunter2demo"\n'
        f, rel = _make_py_file(tmp_path, "q.py", src)
        issues = analyze_file(f, rel)
        assert any(i.title == "Hardcoded Secret Detected" for i in issues)

    def test_short_value_not_flagged(self, tmp_path):
        src = 'pw = "hi"\n'
        f, rel = _make_py_file(tmp_path, "r.py", src)
        issues = analyze_file(f, rel)
        assert not any(i.title == "Hardcoded Secret Detected" for i in issues)

    def test_secret_severity_is_critical(self, tmp_path):
        src = 'API_KEY = "sk-real1234567890abc"\n'
        f, rel = _make_py_file(tmp_path, "s.py", src)
        issues = analyze_file(f, rel)
        secret_issues = [i for i in issues if i.title == "Hardcoded Secret Detected"]
        assert secret_issues[0].severity == "critical"

    def test_evidence_is_redacted(self, tmp_path):
        src = 'API_KEY = "sk-real1234567890abc"\n'
        f, rel = _make_py_file(tmp_path, "t.py", src)
        issues = analyze_file(f, rel)
        secret_issues = [i for i in issues if i.title == "Hardcoded Secret Detected"]
        assert "REDACTED" in secret_issues[0].evidence
        assert "sk-real1234567890abc" not in secret_issues[0].evidence


class TestUnusedVariable:
    def test_unused_var_detected(self, tmp_path):
        src = "def f():\n    tmp = 'never used'\n    return 42\n"
        f, rel = _make_py_file(tmp_path, "u.py", src)
        issues = analyze_file(f, rel)
        assert any(i.title == "Unused Variable" and "tmp" in i.description for i in issues)

    def test_used_var_not_flagged(self, tmp_path):
        src = "def f():\n    tmp = 'used'\n    return tmp\n"
        f, rel = _make_py_file(tmp_path, "v.py", src)
        issues = analyze_file(f, rel)
        assert not any(i.title == "Unused Variable" for i in issues)


class TestSyntaxError:
    def test_syntax_error_detected(self, tmp_path):
        src = "def broken(\n"
        f, rel = _make_py_file(tmp_path, "w.py", src)
        issues = analyze_file(f, rel)
        assert any(i.title == "Syntax Error" for i in issues)
        assert issues[0].category == "bug"
        assert issues[0].severity == "high"


# ── Missing test detector ─────────────────────────────────────────────────────

class TestMissingTests:
    def test_untested_function_detected(self, tmp_path):
        (tmp_path / "app.py").write_text("def my_func(): pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_other.py").write_text("def test_something(): pass\n")
        issues = find_untested_functions(tmp_path)
        assert any("my_func" in i.title for i in issues)

    def test_tested_function_not_flagged(self, tmp_path):
        (tmp_path / "app.py").write_text("def my_func(): pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test_my_func(): pass\n")
        issues = find_untested_functions(tmp_path)
        assert not any("my_func" in i.title for i in issues)

    def test_private_functions_ignored(self, tmp_path):
        (tmp_path / "app.py").write_text("def _private(): pass\n")
        issues = find_untested_functions(tmp_path)
        assert not any("_private" in i.title for i in issues)


# ── JS analyzer ───────────────────────────────────────────────────────────────

class TestJsAnalyzer:
    def test_eval_detected(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text('const result = eval(userInput);\n')
        issues = js_analyze_file(f, "app.js")
        assert any("eval" in i.title for i in issues)

    def test_hardcoded_secret_detected(self, tmp_path):
        f = tmp_path / "config.js"
        f.write_text('const API_KEY = "sk-demo123456789abc";\n')
        issues = js_analyze_file(f, "config.js")
        assert any(i.title == "Hardcoded Secret Detected" for i in issues)

    def test_inner_html_detected(self, tmp_path):
        f = tmp_path / "ui.js"
        f.write_text('element.innerHTML = userInput;\n')
        issues = js_analyze_file(f, "ui.js")
        assert any("innerHTML" in i.title for i in issues)

    def test_clean_file_no_issues(self, tmp_path):
        f = tmp_path / "clean.js"
        f.write_text('function add(a, b) { return a + b; }\n')
        issues = js_analyze_file(f, "clean.js")
        assert issues == []


# ── Severity and health score ─────────────────────────────────────────────────

class TestSeverityAndHealthScore:
    def test_critical_reduces_score_most(self):
        issues = [
            RawIssue("f.py", 1, "security", "critical", "T", "D", "E", "F", 1.0),
        ]
        score = compute_health_score(issues)
        assert score == 80  # 100 - 20

    def test_no_issues_perfect_score(self):
        assert compute_health_score([]) == 100

    def test_many_low_issues_floor_zero(self):
        issues = [
            RawIssue("f.py", i, "code_quality", "low", "T", "D", "E", "F", 0.5)
            for i in range(50)
        ]
        assert compute_health_score(issues) == 0

    def test_mixed_severity(self):
        issues = [
            RawIssue("f.py", 1, "security", "high", "T", "D", "E", "F", 1.0),  # -15
            RawIssue("f.py", 2, "bug", "medium", "T", "D", "E", "F", 1.0),     # -8
            RawIssue("f.py", 3, "code_quality", "low", "T", "D", "E", "F", 1.0), # -3
        ]
        assert compute_health_score(issues) == 74  # 100 - 26


# ── Deduplication ────────────────────────────────────────────────────────────

class TestDeduplication:
    def test_duplicates_removed(self):
        iss = RawIssue("f.py", 1, "security", "high", "Title", "Desc", "Ev", "Fix", 0.9)
        result = _deduplicate([iss, iss, iss])
        assert len(result) == 1

    def test_different_lines_kept(self):
        a = RawIssue("f.py", 1, "security", "high", "Title", "Desc", "Ev", "Fix", 0.9)
        b = RawIssue("f.py", 2, "security", "high", "Title", "Desc", "Ev", "Fix", 0.9)
        result = _deduplicate([a, b])
        assert len(result) == 2


# ── Demo repo analysis ───────────────────────────────────────────────────────

class TestDemoRepoAnalysis:
    """End-to-end analysis of the bundled demo repository."""

    @pytest.fixture
    def demo_path(self):
        p = Path(__file__).parent.parent.parent / "demo_repo"
        if not p.exists():
            pytest.skip("demo_repo not found")
        return p

    def test_demo_has_python_stack(self, demo_path):
        from services.repo_service import detect_tech_stack
        assert detect_tech_stack(demo_path) == "python"

    def test_demo_detects_unused_import(self, demo_path):
        issues = analyze_file(demo_path / "app.py", "app.py")
        assert any(i.title == "Unused Import" for i in issues)

    def test_demo_detects_broad_except(self, demo_path):
        issues = analyze_file(demo_path / "app.py", "app.py")
        assert any(i.title == "Broad Exception Silenced" for i in issues)

    def test_demo_detects_eval(self, demo_path):
        issues = analyze_file(demo_path / "auth.py", "auth.py")
        assert any("eval" in i.title for i in issues)

    def test_demo_detects_hardcoded_secret(self, demo_path):
        issues = analyze_file(demo_path / "auth.py", "auth.py")
        assert any(i.title == "Hardcoded Secret Detected" for i in issues)

    def test_demo_detects_subprocess_shell(self, demo_path):
        issues = analyze_file(demo_path / "utils.py", "utils.py")
        assert any("shell=True" in i.title for i in issues)

    def test_demo_detects_unused_variable(self, demo_path):
        issues = analyze_file(demo_path / "utils.py", "utils.py")
        assert any(i.title == "Unused Variable" for i in issues)

    def test_demo_total_issues_at_least_7(self, demo_path):
        all_issues = []
        for py_f in ["app.py", "auth.py", "utils.py"]:
            all_issues.extend(analyze_file(demo_path / py_f, py_f))
        all_issues.extend(find_untested_functions(demo_path))
        assert len(all_issues) >= 7, f"Expected >=7, got {len(all_issues)}"

    def test_demo_health_score_below_80(self, demo_path):
        all_issues = []
        for py_f in ["app.py", "auth.py", "utils.py"]:
            all_issues.extend(analyze_file(demo_path / py_f, py_f))
        score = compute_health_score(all_issues)
        assert score < 80, f"Expected score <80, got {score}"
