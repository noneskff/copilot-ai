"""
utils.py — Utility helpers.

Intentional issues for CodePilot AI demo:
  6. SECURITY: insecure subprocess with shell=True
  7. UNUSED VARIABLE: 'tmp' is assigned but never used
"""
import subprocess


def run_command(cmd: str) -> str:
    """
    SECURITY ISSUE: shell=True with user-supplied cmd enables command injection.
    """
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # noqa: S602
    return result.stdout


def summarize(data: list) -> dict:
    """Return basic statistics. Intentional unused variable."""
    tmp = "this variable is never used"  # unused variable — issue #7
    total = sum(data)
    count = len(data)
    return {
        "total": total,
        "count": count,
        "average": total / count if count else 0,
    }
