"""
tests/test_analysis_api.py — Integration tests for Phase 3 analysis endpoints.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import pytest
import sys
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("BOB_MODE", "mock")

from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from database import engine, create_db_and_tables
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    SQLModel.metadata.drop_all(engine)
    create_db_and_tables()
    yield
    SQLModel.metadata.drop_all(engine)


def _make_demo_zip() -> bytes:
    """Build a ZIP of the demo_repo for upload."""
    demo = Path(__file__).parent.parent.parent / "demo_repo"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in demo.rglob("*"):
            if f.is_file() and ".git" not in str(f):
                zf.writestr(
                    str(f.relative_to(demo)).replace("\\", "/"),
                    f.read_bytes(),
                )
    return buf.getvalue()


def _upload_demo_repo() -> str:
    """Upload the demo ZIP and return repo_id."""
    zip_bytes = _make_demo_zip()
    boundary = b"----testboundary"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="demo.zip"\r\n'
        b"Content-Type: application/zip\r\n\r\n"
        + zip_bytes + b"\r\n"
        b"--" + boundary + b"--\r\n"
    )
    resp = client.post(
        "/api/repo/upload",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
    )
    assert resp.status_code == 200
    return resp.json()["repo_id"]


# ── Analysis endpoint validation ─────────────────────────────────────────────

class TestAnalysisEndpoint:
    def test_analyze_unknown_repo_returns_404(self):
        resp = client.post("/api/repo/nonexistent/analyze")
        assert resp.status_code == 404

    def test_analyze_ready_repo_returns_job_id(self, tmp_path, monkeypatch):
        """Monkeypatch repo state to 'ready' and verify analyze endpoint works."""
        import uuid
        from sqlmodel import Session
        from database import engine
        from models import Repository
        from datetime import datetime, timezone

        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            repo = Repository(
                id=repo_id, name="test", local_path=str(tmp_path), status="ready",
                tech_stack="python", scan_metadata=json.dumps({"file_count": 3}),
            )
            session.add(repo)
            session.commit()

        # Monkeypatch run_analysis to avoid real analysis
        import services.analysis_service as svc
        async def mock_run(repo_id, repo_path, tech_stack, progress_cb=None):
            if progress_cb:
                await progress_cb({"event": "done", "total_issues": 0})
            return []
        monkeypatch.setattr(svc, "run_analysis", mock_run)

        resp = client.post(f"/api/repo/{repo_id}/analyze")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "analyzing"

    def test_analyze_non_ready_repo_returns_400(self, tmp_path):
        import uuid
        from sqlmodel import Session
        from database import engine
        from models import Repository

        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            repo = Repository(
                id=repo_id, name="test", local_path=str(tmp_path), status="cloning",
            )
            session.add(repo)
            session.commit()

        resp = client.post(f"/api/repo/{repo_id}/analyze")
        assert resp.status_code == 400


# ── Issues endpoints ─────────────────────────────────────────────────────────

class TestIssuesEndpoints:
    def test_list_issues_empty(self):
        resp = client.get("/api/issues?repo_id=nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_issues_with_data(self, tmp_path):
        import uuid
        from sqlmodel import Session
        from database import engine
        from models import Repository, Issue

        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="high", category="security",
                title="Test Issue", description="Test desc",
                file_path="app.py", line_number=10,
                evidence="eval(x)", suggested_fix="Remove eval",
                confidence=0.9,
            ))
            session.commit()

        resp = client.get(f"/api/issues?repo_id={repo_id}")
        assert resp.status_code == 200
        issues = resp.json()
        assert len(issues) == 1
        assert issues[0]["title"] == "Test Issue"
        assert issues[0]["severity"] == "high"
        assert issues[0]["file_path"] == "app.py"
        assert issues[0]["line_number"] == 10
        assert issues[0]["evidence"] == "eval(x)"
        assert issues[0]["confidence"] == 0.9

    def test_get_issue_by_id(self, tmp_path):
        import uuid
        from sqlmodel import Session
        from database import engine
        from models import Repository, Issue

        repo_id = str(uuid.uuid4())
        issue_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.add(Issue(
                id=issue_id, repo_id=repo_id,
                severity="critical", category="security",
                title="Secret Found", description="hardcoded secret",
                file_path="auth.py", line_number=5,
            ))
            session.commit()

        resp = client.get(f"/api/issues/{issue_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == issue_id
        assert data["title"] == "Secret Found"

    def test_get_unknown_issue_404(self):
        resp = client.get("/api/issues/does-not-exist")
        assert resp.status_code == 404

    def test_filter_by_severity(self, tmp_path):
        import uuid
        from sqlmodel import Session
        from database import engine
        from models import Repository, Issue

        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="high", category="security",
                title="High Issue", description="d",
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="low", category="code_quality",
                title="Low Issue", description="d",
            ))
            session.commit()

        resp = client.get(f"/api/issues?repo_id={repo_id}&severity=high")
        assert resp.status_code == 200
        issues = resp.json()
        assert len(issues) == 1
        assert issues[0]["severity"] == "high"

    def test_filter_by_category(self, tmp_path):
        import uuid
        from sqlmodel import Session
        from database import engine
        from models import Repository, Issue

        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="high", category="security",
                title="A", description="d",
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="low", category="code_quality",
                title="B", description="d",
            ))
            session.commit()

        resp = client.get(f"/api/issues?repo_id={repo_id}&category=security")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["category"] == "security"


# ── Analysis status endpoint ──────────────────────────────────────────────────

class TestAnalysisStatus:
    def test_status_includes_issue_counts(self, tmp_path):
        import uuid
        from sqlmodel import Session
        from database import engine
        from models import Repository, Issue

        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
                health_score_before=65,
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="critical", category="security",
                title="A", description="d",
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="high", category="bug",
                title="B", description="d",
            ))
            session.commit()

        resp = client.get(f"/api/repo/{repo_id}/analysis-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_issues"] == 2
        assert data["severity_counts"]["critical"] == 1
        assert data["severity_counts"]["high"] == 1
        assert data["health_score"] == 65

    def test_status_unknown_repo_404(self):
        resp = client.get("/api/repo/nope/analysis-status")
        assert resp.status_code == 404
