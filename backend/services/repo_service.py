"""
repo_service.py — Repository ingestion, extraction, detection, and scanning.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

# Must be set before importing gitpython so it doesn't raise ImportError
# when git is not on PATH (e.g. in test environments or Docker without git).
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

import git

from config import WORKSPACE_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ZIP_SIZE = 100 * 1024 * 1024        # 100 MB
MAX_CLONE_DEPTH = 1                     # shallow clone
MAX_FILES_SCAN = 5000                   # cap recursive scan

LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JavaScript", ".tsx": "TypeScript", ".java": "Java",
    ".go": "Go", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".cpp": "C++", ".c": "C", ".rs": "Rust", ".kt": "Kotlin",
    ".swift": "Swift", ".sh": "Shell", ".html": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".json": "JSON",
    ".yaml": "YAML", ".yml": "YAML", ".md": "Markdown",
}

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".env", "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff",
    ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".zip", ".tar",
    ".gz", ".lock", ".min.js", ".min.css",
}

GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:\.git|/)?$"
)


# ---------------------------------------------------------------------------
# GitHub URL validation
# ---------------------------------------------------------------------------

def validate_github_url(url: str) -> str:
    """Return a clean HTTPS clone URL or raise ValueError."""
    url = url.strip().rstrip("/")
    if not url:
        raise ValueError("URL must not be empty.")
    if not GITHUB_URL_RE.match(url):
        raise ValueError(
            f"Invalid GitHub URL: '{url}'. "
            "Expected format: https://github.com/owner/repo"
        )
    if not url.endswith(".git"):
        url = url + ".git"
    return url


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------

def clone_github_repo(url: str, repo_id: str) -> Path:
    """
    Shallow-clone a public GitHub repo into workspaces/<repo_id>/.
    Returns the destination Path.
    """
    dest = Path(WORKSPACE_DIR) / repo_id
    dest.mkdir(parents=True, exist_ok=True)
    try:
        git.Repo.clone_from(url, str(dest), depth=MAX_CLONE_DEPTH)
    except git.exc.GitCommandError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(f"Git clone failed: {exc}") from exc
    return dest


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------

def safe_extract_zip(zip_bytes: bytes, repo_id: str) -> Path:
    """
    Extract a ZIP archive into workspaces/<repo_id>/ with path-traversal protection.
    Returns the destination Path (may be a sub-folder if ZIP has a single root dir).
    Raises ValueError on invalid/corrupt ZIP or traversal attempt.
    """
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise ValueError(
            f"ZIP file exceeds maximum allowed size of {MAX_ZIP_SIZE // (1024*1024)} MB."
        )

    dest = Path(WORKSPACE_DIR) / repo_id
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            if zf.testzip() is not None:
                raise ValueError("ZIP file is corrupt.")

            for member in zf.infolist():
                # Reject unsafe names
                if member.filename.startswith("/") or ".." in member.filename:
                    raise ValueError(
                        f"Unsafe path in ZIP: '{member.filename}'. Aborting extraction."
                    )
                target = (dest / member.filename).resolve()
                # Ensure resolved path stays inside dest
                if not str(target).startswith(str(dest_resolved)):
                    raise ValueError(
                        f"Path traversal detected in ZIP: '{member.filename}'. Aborting."
                    )
                zf.extract(member, path=str(dest))
    except zipfile.BadZipFile as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError("Uploaded file is not a valid ZIP archive.") from exc
    except ValueError:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    # If ZIP extracted a single top-level directory, use that as the root
    children = [c for c in dest.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest


# ---------------------------------------------------------------------------
# Tech-stack and framework detection
# ---------------------------------------------------------------------------

def detect_tech_stack(repo_path: Path) -> str:
    """Return primary language/stack of the repo."""
    indicators: list[tuple[str, str]] = [
        ("requirements.txt", "python"),
        ("pyproject.toml", "python"),
        ("setup.py", "python"),
        ("setup.cfg", "python"),
        ("Pipfile", "python"),
        ("package.json", "javascript"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
        ("Cargo.toml", "rust"),
        ("go.mod", "go"),
        ("Gemfile", "ruby"),
        ("composer.json", "php"),
    ]
    for filename, stack in indicators:
        if (repo_path / filename).exists():
            # Distinguish TS projects
            if stack == "javascript" and (repo_path / "tsconfig.json").exists():
                return "typescript"
            return stack

    # Fall back to most common source file extension
    counts: Counter[str] = Counter()
    for f in repo_path.rglob("*"):
        if f.is_file() and f.suffix in LANGUAGE_MAP:
            counts[LANGUAGE_MAP[f.suffix]] += 1
    if counts:
        return counts.most_common(1)[0][0].lower()
    return "unknown"


def detect_test_framework(repo_path: Path, tech_stack: str) -> str:
    """Return the most likely test framework used in the repo."""
    # Pytest
    if (
        (repo_path / "pytest.ini").exists()
        or (repo_path / "conftest.py").exists()
        or _file_contains(repo_path / "pyproject.toml", "pytest")
        or _file_contains(repo_path / "setup.cfg", "pytest")
    ):
        return "pytest"
    # Jest / Vitest
    if (repo_path / "package.json").exists():
        pkg = (repo_path / "package.json").read_text(errors="ignore")
        if "vitest" in pkg:
            return "vitest"
        if "jest" in pkg:
            return "jest"
        if "mocha" in pkg:
            return "mocha"
    # Java
    if any((repo_path).rglob("*Test.java")) or any((repo_path).rglob("*Spec.java")):
        return "junit"
    # Default per stack
    defaults = {
        "python": "pytest",
        "javascript": "jest",
        "typescript": "vitest",
        "java": "junit",
        "go": "go_test",
        "rust": "cargo_test",
    }
    return defaults.get(tech_stack, "unknown")


def _file_contains(path: Path, text: str) -> bool:
    try:
        return text in path.read_text(errors="ignore")
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Repository file-tree scan
# ---------------------------------------------------------------------------

def build_file_tree(repo_path: Path) -> dict[str, Any]:
    """
    Recursively walk repo_path and return a tree dict plus summary metadata.
    """
    root_name = repo_path.name
    tree = _walk_dir(repo_path, repo_path, depth=0)

    # Aggregate stats
    lang_counts: Counter[str] = Counter()
    file_count = 0
    total_size = 0

    def _count(node: dict) -> None:
        nonlocal file_count, total_size
        if node["type"] == "file":
            file_count += 1
            total_size += node.get("size", 0)
            lang = node.get("language")
            if lang:
                lang_counts[lang] += 1
        for child in node.get("children", []):
            _count(child)

    _count(tree)

    return {
        "root": root_name,
        "tree": tree,
        "file_count": file_count,
        "total_size_bytes": total_size,
        "language_counts": dict(lang_counts),
    }


def _walk_dir(base: Path, current: Path, depth: int) -> dict[str, Any]:
    name = current.name
    if current.is_file():
        ext = current.suffix.lower()
        return {
            "type": "file",
            "name": name,
            "size": current.stat().st_size,
            "language": LANGUAGE_MAP.get(ext),
        }

    children = []
    try:
        entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        entries = []

    for entry in entries:
        if entry.name in SKIP_DIRS:
            continue
        ext = entry.suffix.lower()
        if entry.is_file() and ext in SKIP_EXTENSIONS:
            continue
        if depth < 6:  # cap tree depth to avoid huge payloads
            children.append(_walk_dir(base, entry, depth + 1))

    return {"type": "dir", "name": name, "children": children}


# ---------------------------------------------------------------------------
# Baseline git commit (so diffs work after fixes)
# ---------------------------------------------------------------------------

def create_baseline_commit(repo_path: Path) -> None:
    """
    Ensure the workspace has a git repo with a baseline commit so
    fix diffs can be computed later.
    """
    git_dir = repo_path / ".git"
    if git_dir.exists():
        # Already a git repo (e.g. cloned); nothing to do
        return
    try:
        repo = git.Repo.init(str(repo_path))
        repo.git.add("-A")
        repo.index.commit("baseline: initial snapshot for CodePilot AI")
    except Exception:
        # Not fatal — diffs will gracefully degrade
        pass


# ---------------------------------------------------------------------------
# Workspace cleanup
# ---------------------------------------------------------------------------

def cleanup_workspace(repo_id: str) -> None:
    """Remove the workspace directory for a repo_id."""
    dest = Path(WORKSPACE_DIR) / repo_id
    shutil.rmtree(dest, ignore_errors=True)
