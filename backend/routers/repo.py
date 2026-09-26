"""
routers/repo.py — Repository ingestion endpoints.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, BackgroundTasks
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import Repository
from services import repo_service
from config import WORKSPACE_DIR

router = APIRouter(prefix="/api/repo", tags=["repo"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class GithubIngestRequest(BaseModel):
    url: str


class RepoResponse(BaseModel):
    repo_id: str
    name: str
    status: str
    source_url: str | None
    tech_stack: str | None
    test_framework: str | None
    file_count: int | None
    total_size_bytes: int | None
    language_counts: dict[str, int] | None
    file_tree: dict[str, Any] | None
    local_path: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _repo_to_response(repo: Repository) -> dict[str, Any]:
    lang_counts = None
    file_tree = None
    file_count = None
    total_size_bytes = None

    if repo.tech_stack:  # filled after scan
        try:
            meta_raw = getattr(repo, "scan_metadata", None)
            if meta_raw:
                meta = json.loads(meta_raw)
                lang_counts = meta.get("language_counts")
                file_count = meta.get("file_count")
                total_size_bytes = meta.get("total_size_bytes")
                file_tree = meta.get("tree")
        except Exception:
            pass

    return {
        "repo_id": repo.id,
        "name": repo.name,
        "status": repo.status,
        "source_url": repo.source_url,
        "tech_stack": repo.tech_stack,
        "test_framework": repo.test_framework,
        "file_count": file_count,
        "total_size_bytes": total_size_bytes,
        "language_counts": lang_counts,
        "file_tree": file_tree,
        "local_path": repo.local_path,
    }


# ---------------------------------------------------------------------------
# Background ingestion task
# ---------------------------------------------------------------------------

def _run_scan(repo_id: str, repo_path_str: str, session_factory) -> None:
    """Run file-tree scan + baseline commit in background."""
    from pathlib import Path
    from sqlmodel import Session
    from database import engine

    repo_path = Path(repo_path_str)
    with Session(engine) as session:
        repo = session.get(Repository, repo_id)
        if not repo:
            return
        try:
            # Detect stack
            tech_stack = repo_service.detect_tech_stack(repo_path)
            test_framework = repo_service.detect_test_framework(repo_path, tech_stack)

            # Build file tree + metadata
            scan = repo_service.build_file_tree(repo_path)

            # Baseline commit
            repo_service.create_baseline_commit(repo_path)

            # Persist
            repo.tech_stack = tech_stack
            repo.test_framework = test_framework
            repo.scan_metadata = json.dumps({
                "language_counts": scan["language_counts"],
                "file_count": scan["file_count"],
                "total_size_bytes": scan["total_size_bytes"],
                "tree": scan["tree"],
            })
            repo.status = "ready"
            session.add(repo)
            session.commit()
        except Exception as exc:
            repo.status = "error"
            repo.scan_metadata = json.dumps({"error": str(exc)})
            session.add(repo)
            session.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/github")
async def ingest_github(
    body: GithubIngestRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Clone a public GitHub repository and start scanning."""
    try:
        clean_url = repo_service.validate_github_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    repo_id = str(uuid.uuid4())
    # Extract a human-readable name from the URL
    parts = clean_url.rstrip(".git").rstrip("/").split("/")
    name = f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 else parts[-1]

    # Persist placeholder immediately so frontend can poll
    repo = Repository(
        id=repo_id,
        name=name,
        source_url=clean_url,
        local_path=str(Path(WORKSPACE_DIR) / repo_id),
        status="cloning",
    )
    session.add(repo)
    session.commit()

    # Clone + scan in background
    background_tasks.add_task(_clone_and_scan, repo_id, clean_url)

    return {"repo_id": repo_id, "name": name, "status": "cloning"}


@router.post("/upload")
async def upload_zip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Upload a ZIP archive and start scanning."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Uploaded file must be a .zip archive.")

    zip_bytes = await file.read()

    repo_id = str(uuid.uuid4())
    name = file.filename.replace(".zip", "")

    repo = Repository(
        id=repo_id,
        name=name,
        source_url=None,
        local_path=str(Path(WORKSPACE_DIR) / repo_id),
        status="extracting",
    )
    session.add(repo)
    session.commit()

    background_tasks.add_task(_extract_and_scan, repo_id, zip_bytes)

    return {"repo_id": repo_id, "name": name, "status": "extracting"}


@router.get("/{repo_id}")
async def get_repo(
    repo_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Get repository metadata, scan status, file tree, and language stats."""
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found.")
    return _repo_to_response(repo)


@router.get("")
async def list_repos(
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all ingested repositories."""
    repos = session.exec(select(Repository)).all()
    return [_repo_to_response(r) for r in repos]


# ---------------------------------------------------------------------------
# Background helpers (run outside request context)
# ---------------------------------------------------------------------------

def _clone_and_scan(repo_id: str, url: str) -> None:
    from pathlib import Path
    from sqlmodel import Session
    from database import engine

    with Session(engine) as session:
        repo = session.get(Repository, repo_id)
        if not repo:
            return
        try:
            dest = repo_service.clone_github_repo(url, repo_id)
            repo.local_path = str(dest)
            repo.status = "scanning"
            session.add(repo)
            session.commit()
        except RuntimeError as exc:
            repo.status = "error"
            repo.scan_metadata = json.dumps({"error": str(exc)})
            session.add(repo)
            session.commit()
            return

    _run_scan(repo_id, str(dest), None)


def _extract_and_scan(repo_id: str, zip_bytes: bytes) -> None:
    from pathlib import Path
    from sqlmodel import Session
    from database import engine

    with Session(engine) as session:
        repo = session.get(Repository, repo_id)
        if not repo:
            return
        try:
            dest = repo_service.safe_extract_zip(zip_bytes, repo_id)
            repo.local_path = str(dest)
            repo.status = "scanning"
            session.add(repo)
            session.commit()
        except ValueError as exc:
            repo.status = "error"
            repo.scan_metadata = json.dumps({"error": str(exc)})
            session.add(repo)
            session.commit()
            return

    _run_scan(repo_id, str(dest), None)
