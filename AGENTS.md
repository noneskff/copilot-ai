# CodePilot AI — Project Root

## Project Overview

CodePilot AI is an autonomous software repair agent built for the IBM Bob 2.0 Hackathon.

It accepts a GitHub repository URL or ZIP upload, analyzes the code for bugs, security issues, code quality problems, and missing tests, then uses IBM Bob Shell as the core implementation agent to apply approved fixes, run tests, and produce a before/after health report.

**Tagline:** Find. Fix. Test. Verify.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + TypeScript + TailwindCSS + Zustand + React Router v6 |
| Backend | Python 3.11 + FastAPI + SQLModel + SQLite |
| Agent | IBM Bob Shell CLI (non-interactive mode with `--yolo` for file modifications) |
| Communication | REST API + WebSocket (live streaming of Bob output) |

---

## Repository Structure

```
codepilot-ai/
├── frontend/               React + Vite frontend
│   └── src/
│       ├── pages/          Route-level page components
│       ├── components/     Reusable UI components
│       ├── store/          Zustand state (useAppStore.ts)
│       └── api/            Axios client + WebSocket helper
│
├── backend/                Python FastAPI backend
│   ├── main.py             App entry point, lifespan, CORS
│   ├── config.py           Environment variable config
│   ├── database.py         SQLite engine + session dependency
│   ├── models.py           SQLModel table definitions
│   ├── routers/            FastAPI router modules
│   ├── services/           Business logic services
│   └── analyzers/          Per-language static analysis modules
│
├── demo_repo/              Self-contained Python project used as hackathon demo target
│                           Contains intentional bugs, a security issue, and a missing test
│
├── AGENTS.md               This file — project context for IBM Bob
└── .bob/                   Bob mode-specific rule files
    └── rules-agent/
        └── AGENTS-agent.md Agent-mode rules for this project
```

---

## Key Conventions

- All Bob Shell invocations go through `backend/services/bob_service.py`
- `BOB_MODE` env var controls real vs mock: `mock` = canned responses, `real` = actual `bob` CLI
- Bob is always invoked from within the target repo's workspace directory, never the backend directory
- WebSocket job streams are keyed by `job_id` (UUID); frontend subscribes via `/ws/{job_id}`
- All database access uses SQLModel ORM — no raw SQL
- The `workspaces/` directory holds cloned/extracted repos — gitignored

---

## IBM Bob Integration Points

Bob Shell is used at 5 distinct stages visible to the developer:

1. **Root cause explanation** — `bob --chat-mode ask` analyzes a detected issue
2. **Fix plan generation** — `bob --chat-mode plan` produces a step-by-step fix plan
3. **Fix implementation** — `bob --yolo` applies the approved fix to the repo
4. **Test failure repair** — `bob --yolo` debugs and repairs failing tests (max 2 retries)
5. **Code review** — `bob --chat-mode ask` reviews the final diff and rates quality

---

## Development Setup

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev    # runs on port 5173
```

## Environment Variables (backend/.env)

```
BOB_MODE=mock             # or "real" when Bob Shell is available
BOBSHELL_API_KEY=         # required when BOB_MODE=real
GITHUB_TOKEN=             # optional, increases GitHub rate limit
DATABASE_URL=sqlite:///./codepilot.db
WORKSPACE_DIR=./workspaces
```
