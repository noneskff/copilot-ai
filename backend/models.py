from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class Repository(SQLModel, table=True):
    """A repository submitted for analysis."""
    id: str = Field(primary_key=True)
    name: str
    source_url: Optional[str] = Field(default=None)
    local_path: str
    tech_stack: Optional[str] = Field(default=None)   # e.g. "python", "javascript"
    test_framework: Optional[str] = Field(default=None)  # e.g. "pytest", "jest"
    status: str = Field(default="pending")             # pending|analyzing|done|error
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    health_score_before: Optional[int] = Field(default=None)
    health_score_after: Optional[int] = Field(default=None)
    scan_metadata: Optional[str] = Field(default=None)  # JSON: file_count, language_counts, tree


class Issue(SQLModel, table=True):
    """A detected code issue in a repository."""
    id: str = Field(primary_key=True)
    repo_id: str = Field(foreign_key="repository.id", index=True)
    severity: str = Field(default="medium")            # low|medium|high|critical
    category: str = Field(default="code_quality")      # bug|code_quality|security|missing_test
    title: str
    description: str
    file_path: Optional[str] = Field(default=None)     # relative path in repo
    line_number: Optional[int] = Field(default=None)   # line where issue starts
    evidence: Optional[str] = Field(default=None)      # short code snippet
    suggested_fix: Optional[str] = Field(default=None) # one-line fix suggestion
    confidence: Optional[float] = Field(default=None)  # 0.0–1.0
    root_cause: Optional[str] = Field(default=None)    # JSON string from Bob
    affected_files: Optional[str] = Field(default=None)  # JSON array string
    fix_plan: Optional[str] = Field(default=None)      # JSON string from Bob
    status: str = Field(default="open")                # open|approved|fixed|rejected
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FixJob(SQLModel, table=True):
    """A fix job created when a developer approves a fix."""
    id: str = Field(primary_key=True)
    issue_id: str = Field(foreign_key="issue.id", index=True)
    repo_id: str = Field(foreign_key="repository.id", index=True)
    bob_prompt: Optional[str] = Field(default=None)
    bob_output: Optional[str] = Field(default=None)
    diff: Optional[str] = Field(default=None)
    status: str = Field(default="pending")             # pending|running|succeeded|failed|retrying
    attempt_number: int = Field(default=0)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    # Note: started_at / completed_at set explicitly with datetime.now(timezone.utc)


class TestRun(SQLModel, table=True):
    """A test suite execution result."""
    id: str = Field(primary_key=True)
    repo_id: str = Field(foreign_key="repository.id", index=True)
    fix_job_id: Optional[str] = Field(default=None, foreign_key="fixjob.id")
    output: Optional[str] = Field(default=None)
    passed: bool = Field(default=False)
    tests_total: int = Field(default=0)
    tests_passed: int = Field(default=0)
    tests_failed: int = Field(default=0)
    ran_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
