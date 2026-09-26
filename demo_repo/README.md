# demo_repo — CodePilot AI Demo Target

This directory contains a self-contained Python project used as the primary demo repository for CodePilot AI.

It will be populated in **Phase 7** with intentional bugs, a security issue, and a missing test so that all four CodePilot issue categories are demonstrated during the hackathon demo.

## Planned contents (Phase 7)

- `app.py` — A Python module with an intentional bug (e.g. off-by-one error or unhandled None)
- `auth.py` — A module with a hardcoded credential (security issue)
- `utils.py` — A function with high cyclomatic complexity (code quality violation)
- `tests/test_app.py` — Tests covering only `app.py`, leaving `utils.py` untested (missing test)
- `requirements.txt` — Only `pytest` as a dependency
- `pytest.ini` — Minimal pytest configuration
