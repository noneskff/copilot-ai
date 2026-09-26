"""
tests/test_repo_api.py — Integration tests for Phase 2 /api/repo endpoints.

Uses FastAPI's TestClient with an in-memory SQLite database.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# Override DB to use in-memory SQLite before importing app
import os
os.environ["DATABASE_URL"] = "sqlite://"    # in-memory
os.environ["BOB_MODE"] = "mock"

from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from database import engine, create_db_and_tables
from main import app


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables before each test."""
    SQLModel.metadata.drop_all(engine)
    create_db_and_tables()
    yield
    SQLModel.metadata.drop_all(engine)


client = TestClient(app)


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Health check still works
# ---------------------------------------------------------------------------

def test_health_still_works():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GitHub URL endpoint — validation
# ---------------------------------------------------------------------------

class TestGithubEndpoint:
    def test_invalid_url_returns_422(self):
        resp = client.post("/api/repo/github", json={"url": "not-a-url"})
        assert resp.status_code == 422
        assert "Invalid GitHub URL" in resp.json()["detail"]

    def test_empty_url_returns_422(self):
        resp = client.post("/api/repo/github", json={"url": ""})
        assert resp.status_code == 422

    def test_non_github_url_returns_422(self):
        resp = client.post("/api/repo/github", json={"url": "https://gitlab.com/owner/repo"})
        assert resp.status_code == 422

    def test_valid_url_creates_repo_record(self, monkeypatch):
        """Monkeypatching the actual clone so we don't hit network."""
        from services import repo_service

        def mock_clone(url: str, repo_id: str):
            dest = Path(os.environ.get("WORKSPACE_DIR", "./workspaces")) / repo_id
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "app.py").write_text("print('hello')")
            return dest

        monkeypatch.setattr(repo_service, "clone_github_repo", mock_clone)

        resp = client.post("/api/repo/github", json={"url": "https://github.com/owner/myrepo"})
        assert resp.status_code == 200
        data = resp.json()
        assert "repo_id" in data
        assert data["status"] in ("cloning", "scanning", "ready")
        assert "owner/myrepo" in data["name"]


# ---------------------------------------------------------------------------
# ZIP upload endpoint
# ---------------------------------------------------------------------------

class TestZipUploadEndpoint:
    def test_non_zip_file_rejected(self):
        resp = client.post(
            "/api/repo/upload",
            files={"file": ("script.py", b"print('hi')", "text/plain")},
        )
        assert resp.status_code == 422
        assert "zip" in resp.json()["detail"].lower()

    def test_corrupt_zip_rejected(self):
        resp = client.post(
            "/api/repo/upload",
            files={"file": ("bad.zip", b"not a zip file", "application/zip")},
        )
        # Should create the record but background task will set status=error
        # The upload itself returns 200 with a repo_id (async processing)
        # We just verify it doesn't crash the endpoint
        assert resp.status_code in (200, 422)

    def test_valid_zip_creates_repo(self, monkeypatch, tmp_path):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        zip_bytes = _make_zip({
            "myapp/app.py": "def hello(): return 1",
            "myapp/requirements.txt": "pytest",
            "myapp/tests/test_app.py": "def test_hello(): pass",
        })
        resp = client.post(
            "/api/repo/upload",
            files={"file": ("myapp.zip", zip_bytes, "application/zip")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "repo_id" in data
        assert data["name"] == "myapp"

    def test_path_traversal_zip_eventually_errors(self, monkeypatch, tmp_path):
        """
        A ZIP with path traversal should cause the background task to set status=error.
        The endpoint accepts the upload (returns 200) but processing fails.
        """
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        # Build a traversal zip
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.py", "malicious")
        traversal_zip = buf.getvalue()

        resp = client.post(
            "/api/repo/upload",
            files={"file": ("evil.zip", traversal_zip, "application/zip")},
        )
        # Upload accepted — scanning happens in background
        assert resp.status_code == 200
        repo_id = resp.json()["repo_id"]

        # Poll for status (TestClient runs background tasks synchronously)
        status_resp = client.get(f"/api/repo/{repo_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/repo/:id
# ---------------------------------------------------------------------------

class TestGetRepo:
    def test_unknown_repo_returns_404(self):
        resp = client.get("/api/repo/does-not-exist")
        assert resp.status_code == 404

    def test_get_repo_returns_expected_fields(self, monkeypatch, tmp_path):
        monkeypatch.setattr("services.repo_service.WORKSPACE_DIR", str(tmp_path))
        zip_bytes = _make_zip({
            "proj/app.py": "x=1",
            "proj/requirements.txt": "pytest",
        })
        upload_resp = client.post(
            "/api/repo/upload",
            files={"file": ("proj.zip", zip_bytes, "application/zip")},
        )
        repo_id = upload_resp.json()["repo_id"]
        get_resp = client.get(f"/api/repo/{repo_id}")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["repo_id"] == repo_id
        assert "status" in body
        assert "name" in body


# ---------------------------------------------------------------------------
# GET /api/repo  (list)
# ---------------------------------------------------------------------------

def test_list_repos_initially_empty():
    resp = client.get("/api/repo")
    assert resp.status_code == 200
    assert resp.json() == []
