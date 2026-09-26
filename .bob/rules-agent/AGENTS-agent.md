# CodePilot AI — Agent Mode Rules

## Agent Mode Role

In Agent mode, you are implementing features for CodePilot AI — an autonomous software repair agent. Your job is to write clean, minimal, working code that follows the patterns already established in the codebase.

---

## Critical Rules

### Bob Shell Bridge
- All Bob Shell invocations MUST go through `backend/services/bob_service.py`
- Never call the `bob` CLI directly from a router or analyzer
- Always check `config.BOB_MODE` — if `"mock"`, return pre-canned responses; if `"real"`, invoke the CLI
- Bob Shell must be invoked with `cwd=repo_path` (the target workspace dir), never from the backend dir

### Bob Shell Invocation Pattern (real mode)
```python
# Non-interactive with file modifications
bob -p "{prompt}" --yolo --auth-method api-key --hide-intermediary-output

# Non-interactive read-only (ask/plan modes)
bob -p "{prompt}" --chat-mode ask --auth-method api-key --hide-intermediary-output
```
- `BOBSHELL_API_KEY` must be set as an environment variable
- Output is parsed from stdout — always ask Bob to return structured JSON

### Database
- Use `Session` from `database.get_session()` — never create engine directly in a service
- All models are in `models.py` — do not create model files elsewhere
- Use UUIDs (`str(uuid.uuid4())`) as primary keys

### WebSocket Streaming
- Use `routers/ws.broadcast(job_id, message_dict)` to push events to connected clients
- Event schema: `{"event": "<type>", "job_id": "<id>", ...payload}`
- Event types: `progress`, `issue_found`, `bob_output`, `fix_complete`, `fix_failed`, `test_result`, `done`

### File Safety
- Repos live in `WORKSPACE_DIR/{repo_id}/` — never reference paths outside this directory
- ZIP extraction must use path traversal protection (see Phase 2 repo_service.py)
- Before every Bob fix invocation, run `git stash` as a rollback snapshot

---

## Code Style
- Python: type hints on all function signatures, docstrings on public methods
- TypeScript: strict mode, no `any` types unless unavoidable
- Tailwind: use utility classes only — no custom CSS except in `index.css` for base styles
- Prefer `async/await` everywhere in both Python (asyncio) and TypeScript

---

## Project Phases
The plan is in `codepilot-ai-plan.md` at the repo root. Implement one phase at a time. Check the plan for expected outcomes before starting each phase.
