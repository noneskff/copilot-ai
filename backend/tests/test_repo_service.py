"""
tests/test_repo_service.py — Unit tests for Phase 2 repo_service.

Covers:
  - GitHub URL validation (valid, invalid, edge cases)
  - ZIP extraction (normal, single-root-dir, path traversal, corrupt, size limit)
  - Tech stack detection
  - Test framework detection
  - File tree build + language counts
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

# Make sure we can import from backend root
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.repo_service import (
    validate_github_url,
    safe_extract_zip,
    detect_tech_stack,
    detect_test_framework,
    build_file_tree,
    MAX_ZIP_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_zip(files: dict[str, str], traversal_name: str | None = None) -> bytes:
    """
    Build an in-memory ZIP.
    files: {archive_name: content}
    traversal_name: if set, adds a member with that name (e.g. "../evil.py")
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        if traversal_name:
            zf.writestr(traversal_name, "evil content")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# GitHub URL validation
# ---------------------------------------------------------------------------

class TestValidateGithubUrl:
    def test_valid_url_plain(self):
        result = validate_github_url("https://github.com/owner/repo")
        assert result == "https://github.com/owner/repo.git"

    def test_valid_url_with_git(self):
        result = validate_github_url("https://github.com/owner/repo.git")
        assert result == "https://github.com/owner/repo.git"

    def test_valid_url_trailing_slash(self):
        result = validate_github_url("https://github.com/owner/repo/")
        assert result == "https://github.com/owner/repo.git"

    def test_valid_url_with_dots_and_dashes(self):
        result = validate_github_url("https://github.com/my-org/my.repo-name")
        assert result == "https://github.com/my-org/my.repo-name.git"

    def test_invalid_not_github(self):
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            validate_github_url("https://gitlab.com/owner/repo")

    def test_invalid_no_repo_name(self):
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            validate_github_url("https://github.com/owner")

    def test_invalid_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_github_url("   ")

    def test_invalid_http_allowed(self):
        # http:// is technically accepted by the regex
        result = validate_github_url("http://github.com/owner/repo")
        assert result.endswith(".git")

    def test_invalid_random_string(self):
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            validate_github_url("not-a-url")

    def test_invalid_bitbucket(self):
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            validate_github_url("https://bitbucket.org/owner/repo")


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------

class TestSafeExtractZip:
    def test_normal_extraction(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        zip_bytes = make_zip({"app.py": "print('hello')", "README.md": "# hello"})
        dest = safe_extract_zip(zip_bytes, "test-repo-1")
        assert (dest / "app.py").exists()
        assert (dest / "README.md").exists()

    def test_single_root_dir_unwrapped(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        zip_bytes = make_zip({"myproject/app.py": "x=1", "myproject/README.md": "hi"})
        dest = safe_extract_zip(zip_bytes, "test-repo-2")
        # Should return the inner myproject/ dir directly
        assert dest.name == "myproject"
        assert (dest / "app.py").exists()

    def test_path_traversal_dotdot_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        zip_bytes = make_zip({"app.py": "ok"}, traversal_name="../evil.py")
        with pytest.raises(ValueError, match="[Uu]nsafe|[Tt]raversal"):
            safe_extract_zip(zip_bytes, "test-repo-3")

    def test_path_traversal_absolute_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        zip_bytes = make_zip({"/etc/passwd": "root:x:0:0"})
        with pytest.raises(ValueError, match="[Uu]nsafe|[Tt]raversal"):
            safe_extract_zip(zip_bytes, "test-repo-4")

    def test_corrupt_zip_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        with pytest.raises(ValueError, match="valid ZIP"):
            safe_extract_zip(b"this is not a zip", "test-repo-5")

    def test_oversized_zip_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        # Create bytes larger than MAX_ZIP_SIZE
        big_bytes = b"x" * (MAX_ZIP_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_extract_zip(big_bytes, "test-repo-6")

    def test_workspace_cleaned_on_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        with pytest.raises(ValueError):
            safe_extract_zip(b"not a zip", "cleanup-repo")
        # Workspace dir should be cleaned up after failure
        assert not (tmp_path / "cleanup-repo").exists()


# ---------------------------------------------------------------------------
# Tech stack detection
# ---------------------------------------------------------------------------

class TestDetectTechStack:
    def test_python_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n")
        assert detect_tech_stack(tmp_path) == "python"

    def test_python_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]\n")
        assert detect_tech_stack(tmp_path) == "python"

    def test_javascript_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name":"app"}')
        assert detect_tech_stack(tmp_path) == "javascript"

    def test_typescript_package_json_with_tsconfig(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name":"app"}')
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_tech_stack(tmp_path) == "typescript"

    def test_java_pom_xml(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        assert detect_tech_stack(tmp_path) == "java"

    def test_rust_cargo(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        assert detect_tech_stack(tmp_path) == "rust"

    def test_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/hello\n")
        assert detect_tech_stack(tmp_path) == "go"

    def test_fallback_extension_count(self, tmp_path):
        (tmp_path / "a.rb").write_text("puts 'hi'")
        (tmp_path / "b.rb").write_text("puts 'hello'")
        result = detect_tech_stack(tmp_path)
        assert result == "ruby"

    def test_unknown_empty_repo(self, tmp_path):
        result = detect_tech_stack(tmp_path)
        assert result == "unknown"


# ---------------------------------------------------------------------------
# Test framework detection
# ---------------------------------------------------------------------------

class TestDetectTestFramework:
    def test_pytest_ini(self, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        assert detect_test_framework(tmp_path, "python") == "pytest"

    def test_conftest(self, tmp_path):
        (tmp_path / "conftest.py").write_text("import pytest\n")
        assert detect_test_framework(tmp_path, "python") == "pytest"

    def test_jest_in_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"devDependencies":{"jest":"^29"}}')
        assert detect_test_framework(tmp_path, "javascript") == "jest"

    def test_vitest_in_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"devDependencies":{"vitest":"^1"}}')
        assert detect_test_framework(tmp_path, "typescript") == "vitest"

    def test_mocha_in_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"devDependencies":{"mocha":"^10"}}')
        assert detect_test_framework(tmp_path, "javascript") == "mocha"

    def test_default_python(self, tmp_path):
        assert detect_test_framework(tmp_path, "python") == "pytest"

    def test_default_javascript(self, tmp_path):
        assert detect_test_framework(tmp_path, "javascript") == "jest"


# ---------------------------------------------------------------------------
# File tree + language counts
# ---------------------------------------------------------------------------

class TestBuildFileTree:
    def test_basic_structure(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")
        (tmp_path / "utils.py").write_text("def f(): pass")
        (tmp_path / "README.md").write_text("# hi")
        subdir = tmp_path / "tests"
        subdir.mkdir()
        (subdir / "test_app.py").write_text("def test_x(): pass")

        result = build_file_tree(tmp_path)
        assert result["file_count"] == 4
        assert result["language_counts"]["Python"] == 3
        assert result["language_counts"]["Markdown"] == 1
        assert result["tree"]["type"] == "dir"

    def test_skip_dirs_excluded(self, tmp_path):
        (tmp_path / "app.py").write_text("x=1")
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        (node_modules / "lib.js").write_text("module.exports={}")

        result = build_file_tree(tmp_path)
        # node_modules children should not appear
        assert result["file_count"] == 1

    def test_empty_repo(self, tmp_path):
        result = build_file_tree(tmp_path)
        assert result["file_count"] == 0
        assert result["language_counts"] == {}

    def test_total_size(self, tmp_path):
        content = "x" * 100
        (tmp_path / "big.py").write_text(content)
        result = build_file_tree(tmp_path)
        assert result["total_size_bytes"] >= 100
