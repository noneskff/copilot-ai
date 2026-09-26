"""
tests/test_fix_api.py — Integration tests for Phase 4-6 fix, test, and report endpoints.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import sys
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("BOB_MODE", "mock")
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session

from database import engine, create_db_and_tables
from main import app
from models import Repository, Issue, FixJob, TestRun

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_db():
    SQLModel.metadata.drop_all(engine)
    create_db_and_tables()
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def repo_and_issue(tmp_path):
    """Seed a repo + one open issue, return (repo_id, issue_id)."""
    repo_id  = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Repository(
            id=repo_id,
            name="test-repo",
            local_path=str(tmp_path),
            status="ready",
            tech_stack="python",
            health_score_before=60,
        ))
        session.add(Issue(
            id=issue_id,
            repo_id=repo_id,
            severity="high",
            category="security",
            title="Eval With User Input",
            description="eval() called with user-controlled data",
            file_path="app.py",
            line_number=10,
            evidence="eval(user_input)",
            suggested_fix="Remove eval or use ast.literal_eval",
            confidence=0.95,
            status="open",
        ))
        session.commit()
    return repo_id, issue_id


@pytest.fixture
def approved_issue(tmp_path):
    """Seed a repo + issue with fix_plan, return (repo_id, issue_id, job_id)."""
    repo_id  = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    job_id   = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Repository(
            id=repo_id,
            name="test-repo",
            local_path=str(tmp_path),
            status="ready",
            tech_stack="python",
        ))
        session.add(Issue(
            id=issue_id,
            repo_id=repo_id,
            severity="medium",
            category="code_quality",
            title="Unused Import",
            description="os is imported but never used",
            file_path="app.py",
            line_number=1,
            status="approved",
            fix_plan=json.dumps({"steps": ["Remove unused import"], "risk_level": "low"}),
        ))
        session.add(FixJob(
            id=job_id,
            issue_id=issue_id,
            repo_id=repo_id,
            bob_prompt="Fix unused import",
            status="pending",
            attempt_number=1,
        ))
        session.commit()
    return repo_id, issue_id, job_id


# ── Phase 4: Fix planning ─────────────────────────────────────────────────────

class TestFixPlanEndpoint:
    def test_plan_unknown_issue_404(self):
        resp = client.post("/api/issues/does-not-exist/plan")
        assert resp.status_code == 404

    def test_plan_returns_steps(self, repo_and_issue):
        _repo_id, issue_id = repo_and_issue
        resp = client.post(f"/api/issues/{issue_id}/plan")
        assert resp.status_code == 200
        data = resp.json()
        assert "plan" in data
        assert "steps" in data["plan"]
        assert isinstance(data["plan"]["steps"], list)
        assert len(data["plan"]["steps"]) > 0

    def test_plan_persisted_on_issue(self, repo_and_issue):
        _repo_id, issue_id = repo_and_issue
        client.post(f"/api/issues/{issue_id}/plan")
        # Verify it's visible via GET /api/issues/{id}
        resp = client.get(f"/api/issues/{issue_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fix_plan"] is not None
        assert "steps" in data["fix_plan"]

    def test_plan_includes_risk_level(self, repo_and_issue):
        _repo_id, issue_id = repo_and_issue
        resp = client.post(f"/api/issues/{issue_id}/plan")
        assert resp.status_code == 200
        plan = resp.json()["plan"]
        assert "risk_level" in plan

    def test_plan_issue_id_in_response(self, repo_and_issue):
        _repo_id, issue_id = repo_and_issue
        resp = client.post(f"/api/issues/{issue_id}/plan")
        assert resp.json()["issue_id"] == issue_id


# ── Phase 5: Fix approval ─────────────────────────────────────────────────────

class TestApproveFixEndpoint:
    def test_approve_unknown_issue_404(self):
        resp = client.post("/api/issues/no-such-issue/approve")
        assert resp.status_code == 404

    def test_approve_returns_job_id(self, repo_and_issue):
        _repo_id, issue_id = repo_and_issue
        resp = client.post(f"/api/issues/{issue_id}/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["issue_id"] == issue_id
        assert data["status"] == "pending"

    def test_approve_sets_issue_status(self, repo_and_issue):
        _repo_id, issue_id = repo_and_issue
        client.post(f"/api/issues/{issue_id}/approve")
        resp = client.get(f"/api/issues/{issue_id}")
        assert resp.json()["status"] == "approved"

    def test_approve_creates_fix_job(self, repo_and_issue, tmp_path):
        _repo_id, issue_id = repo_and_issue
        approve_resp = client.post(f"/api/issues/{issue_id}/approve")
        job_id = approve_resp.json()["job_id"]
        job_resp = client.get(f"/api/fix/{job_id}")
        assert job_resp.status_code == 200
        job = job_resp.json()
        assert job["status"] == "pending"
        assert job["issue_id"] == issue_id

    def test_approve_already_fixed_issue_400(self, tmp_path):
        repo_id  = str(uuid.uuid4())
        issue_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.add(Issue(
                id=issue_id, repo_id=repo_id, severity="low", category="code_quality",
                title="T", description="d", status="fixed",
            ))
            session.commit()
        resp = client.post(f"/api/issues/{issue_id}/approve")
        assert resp.status_code == 400


# ── Phase 5: Fix job status ───────────────────────────────────────────────────

class TestGetFixJobEndpoint:
    def test_get_unknown_job_404(self):
        resp = client.get("/api/fix/no-such-job")
        assert resp.status_code == 404

    def test_get_job_returns_fields(self, approved_issue):
        _repo_id, _issue_id, job_id = approved_issue
        resp = client.get(f"/api/fix/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job_id
        assert data["status"] == "pending"
        assert "bob_output" in data
        assert "diff" in data
        assert "started_at" in data
        assert "completed_at" in data


# ── Phase 5: Execute fix ──────────────────────────────────────────────────────

class TestExecuteFixEndpoint:
    def test_execute_unknown_job_404(self):
        resp = client.post("/api/fix/no-such-job/execute")
        assert resp.status_code == 404

    def test_execute_returns_running(self, approved_issue):
        _repo_id, _issue_id, job_id = approved_issue
        resp = client.post(f"/api/fix/{job_id}/execute")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_execute_already_running_400(self, tmp_path):
        repo_id  = str(uuid.uuid4())
        issue_id = str(uuid.uuid4())
        job_id   = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.add(Issue(
                id=issue_id, repo_id=repo_id, severity="low", category="code_quality",
                title="T", description="d", status="approved",
            ))
            session.add(FixJob(
                id=job_id, issue_id=issue_id, repo_id=repo_id,
                bob_prompt="fix", status="running", attempt_number=1,
            ))
            session.commit()
        resp = client.post(f"/api/fix/{job_id}/execute")
        assert resp.status_code == 400


# ── Phase 6: Test runs ────────────────────────────────────────────────────────

class TestTestRunsEndpoints:
    def test_list_test_runs_empty(self, tmp_path):
        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.commit()
        resp = client.get(f"/api/repo/{repo_id}/test-runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_test_runs_returns_data(self, tmp_path):
        from datetime import datetime, timezone
        repo_id = str(uuid.uuid4())
        run_id  = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.add(TestRun(
                id=run_id,
                repo_id=repo_id,
                output="5 passed in 0.5s",
                passed=True,
                tests_total=5,
                tests_passed=5,
                tests_failed=0,
                ran_at=datetime.now(timezone.utc),
            ))
            session.commit()
        resp = client.get(f"/api/repo/{repo_id}/test-runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == run_id
        assert data[0]["passed"] is True
        assert data[0]["tests_total"] == 5

    def test_get_test_run_by_id(self, tmp_path):
        from datetime import datetime, timezone
        repo_id = str(uuid.uuid4())
        run_id  = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
            ))
            session.add(TestRun(
                id=run_id,
                repo_id=repo_id,
                output="1 failed in 0.1s",
                passed=False,
                tests_total=3,
                tests_passed=2,
                tests_failed=1,
                ran_at=datetime.now(timezone.utc),
            ))
            session.commit()
        resp = client.get(f"/api/test-runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == run_id
        assert data["passed"] is False
        assert data["tests_failed"] == 1

    def test_get_unknown_test_run_404(self):
        resp = client.get("/api/test-runs/does-not-exist")
        assert resp.status_code == 404

    def test_run_tests_unknown_repo_404(self):
        resp = client.post("/api/repo/no-such-repo/run-tests")
        assert resp.status_code == 404

    def test_run_tests_returns_running(self, tmp_path):
        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
                tech_stack="python",
            ))
            session.commit()
        resp = client.post(f"/api/repo/{repo_id}/run-tests")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"


# ── Phase 6: Test service unit tests ─────────────────────────────────────────

class TestParsePytestOutput:
    def test_all_passed(self):
        from services.test_service import parse_pytest_output
        output = "5 passed in 0.42s"
        total, passed, failed = parse_pytest_output(output)
        assert passed == 5
        assert failed == 0
        assert total == 5

    def test_mixed_results(self):
        from services.test_service import parse_pytest_output
        output = "3 passed, 2 failed in 0.55s"
        total, passed, failed = parse_pytest_output(output)
        assert passed == 3
        assert failed == 2
        assert total == 5

    def test_with_errors(self):
        from services.test_service import parse_pytest_output
        output = "4 passed, 1 failed, 1 error in 1.0s"
        total, passed, failed = parse_pytest_output(output)
        assert passed == 4
        assert failed == 2  # failed + error

    def test_empty_output(self):
        from services.test_service import parse_pytest_output
        total, passed, failed = parse_pytest_output("")
        assert total == 0
        assert passed == 0
        assert failed == 0


# ── Phase 6: Report ───────────────────────────────────────────────────────────

class TestReportEndpoint:
    def test_report_unknown_repo_404(self):
        resp = client.get("/api/repo/no-such-repo/report")
        assert resp.status_code == 404

    def test_report_returns_structure(self, tmp_path):
        repo_id  = str(uuid.uuid4())
        issue_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id,
                name="my-repo",
                local_path=str(tmp_path),
                status="ready",
                health_score_before=65,
            ))
            session.add(Issue(
                id=issue_id,
                repo_id=repo_id,
                severity="high",
                category="security",
                title="Eval Issue",
                description="d",
                status="fixed",
            ))
            session.commit()

        resp = client.get(f"/api/repo/{repo_id}/report")
        assert resp.status_code == 200
        data = resp.json()

        assert data["repo_id"] == repo_id
        assert data["repo_name"] == "my-repo"
        assert "generated_at" in data
        assert "health" in data
        assert data["health"]["before"] == 65
        assert "after" in data["health"]
        assert "issues" in data
        assert data["issues"]["total"] == 1
        assert data["issues"]["fixed"] == 1
        assert data["issues"]["remaining"] == 0
        assert data["issues"]["fix_rate_pct"] == 100

    def test_report_health_scores(self, tmp_path):
        """After fixing all issues, after score should improve vs before."""
        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id,
                name="r",
                local_path=str(tmp_path),
                status="ready",
                health_score_before=55,
            ))
            # All issues are fixed
            for i in range(3):
                session.add(Issue(
                    id=str(uuid.uuid4()),
                    repo_id=repo_id,
                    severity="critical",
                    category="security",
                    title=f"Issue {i}",
                    description="d",
                    status="fixed",
                ))
            session.commit()

        resp = client.get(f"/api/repo/{repo_id}/report")
        assert resp.status_code == 200
        data = resp.json()
        # All issues fixed → after score should be 100
        assert data["health"]["after"] == 100
        assert data["health"]["improvement"] > 0

    def test_report_includes_fix_list(self, tmp_path):
        repo_id  = str(uuid.uuid4())
        issue_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
                health_score_before=70,
            ))
            session.add(Issue(
                id=issue_id, repo_id=repo_id, severity="medium", category="bug",
                title="Off-by-one Error", description="d", status="fixed",
            ))
            session.commit()

        resp = client.get(f"/api/repo/{repo_id}/report")
        data = resp.json()
        assert any(i["id"] == issue_id for i in data["fixed_issue_list"])
        assert data["open_issue_list"] == []

    def test_report_severity_breakdown(self, tmp_path):
        repo_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(Repository(
                id=repo_id, name="r", local_path=str(tmp_path), status="ready",
                health_score_before=50,
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="critical", category="security",
                title="A", description="d", status="fixed",
            ))
            session.add(Issue(
                id=str(uuid.uuid4()), repo_id=repo_id,
                severity="high", category="bug",
                title="B", description="d", status="open",
            ))
            session.commit()

        resp = client.get(f"/api/repo/{repo_id}/report")
        data = resp.json()
        assert data["issues"]["severity_breakdown"]["critical"]["total"] == 1
        assert data["issues"]["severity_breakdown"]["critical"]["fixed"] == 1
        assert data["issues"]["severity_breakdown"]["high"]["total"] == 1
        assert data["issues"]["severity_breakdown"]["high"]["fixed"] == 0
