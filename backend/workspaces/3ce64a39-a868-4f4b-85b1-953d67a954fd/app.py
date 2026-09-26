"""
app.py — Demo application module.

Intentional issues for CodePilot AI demo:
  1. BUG: off-by-one in get_item() returns wrong index
  2. UNUSED IMPORT: 'os' is imported but never used
  3. BROAD EXCEPTION: bare except catches everything including SystemExit
"""
import os  # unused import — issue #1

ITEMS = ["alpha", "beta", "gamma", "delta"]


def get_item(index: int) -> str:
    """Return item at the given 1-based index. BUG: off-by-one error."""
    # BUG: should be index - 1 for 1-based, but uses index + 1
    return ITEMS[index + 1]


def process_all(items: list) -> list:
    """Process every item, returning uppercased versions."""
    result = []
    for item in items:
        try:
            result.append(item.upper())
        except:  # broad exception — issue #3: should be 'except Exception'
            pass
    return result


def calculate_discount(price: float, pct: float) -> float:
    """Return discounted price. No issues here."""
    if pct < 0 or pct > 100:
        raise ValueError(f"Percentage must be 0-100, got {pct}")
    return price * (1 - pct / 100)
