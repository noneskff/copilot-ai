import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import WORKSPACE_DIR
from database import create_db_and_tables
from routers import repo, analysis, issues, fix, tests, report, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    yield
    # Shutdown — nothing to clean up for now


app = FastAPI(
    title="CodePilot AI",
    description="Autonomous Software Repair Agent powered by IBM Bob Shell",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(repo.router)
app.include_router(analysis.router)
app.include_router(issues.router)
app.include_router(fix.router)
app.include_router(tests.router)
app.include_router(report.router)
app.include_router(ws.router)


@app.get("/api/health", tags=["health"])
async def health_check():
    """Basic health check — verifies the backend is running."""
    return {"status": "ok", "service": "codepilot-ai"}
