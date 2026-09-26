"""
auth.py — Authentication helpers.

Intentional issues for CodePilot AI demo:
  4. SECURITY: hardcoded API key / secret  (never use real credentials here)
  5. SECURITY: eval() usage on user input
"""

# SECURITY ISSUE: hardcoded credential — never do this in real code
API_KEY = "sk-demo1234567890abcdefDEMOKEYNOTREAL"  # noqa: S105
DB_PASSWORD = "hunter2_demo_not_real"               # noqa: S105


def authenticate(token: str) -> bool:
    """Check token against hardcoded key. Insecure by design for demo."""
    return token == API_KEY


def evaluate_expression(expr: str) -> object:
    """
    SECURITY ISSUE: uses eval() on unvalidated user input.
    Attackers can execute arbitrary Python code.
    """
    return eval(expr)  # noqa: S307
