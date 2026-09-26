"""Tests for app.py only — utils.py is intentionally untested (missing test demo)."""
import pytest
from app import calculate_discount, process_all


def test_calculate_discount_basic():
    assert calculate_discount(100.0, 10.0) == 90.0


def test_calculate_discount_zero():
    assert calculate_discount(50.0, 0.0) == 50.0


def test_calculate_discount_full():
    assert calculate_discount(80.0, 100.0) == 0.0


def test_calculate_discount_invalid():
    with pytest.raises(ValueError):
        calculate_discount(100.0, -5.0)


def test_process_all_strings():
    assert process_all(["hello", "world"]) == ["HELLO", "WORLD"]


def test_process_all_empty():
    assert process_all([]) == []
