from datetime import datetime

import pytest

from main import calculator, get_time, run_tool


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2", 3),
        ("(2 + 3) * 4", 20),
        ("2 + 3 * 4", 14),
        ("7 // 2", 3),
        ("7 % 4", 3),
        ("-2 ** 2", -4),
        ("1234 * 5678 + 2**10", 7007676),
        ("1 / 4", 0.25),
    ],
)
def test_calculator_computes(expression, expected):
    assert calculator(expression) == {"expression": expression, "result": expected}


@pytest.mark.parametrize(
    "expression",
    ["__import__('os')", "abs(-1)", "x + 1", "'a' * 3", "True + 1", "1 +"],
)
def test_calculator_rejects_non_arithmetic(expression):
    assert "error" in calculator(expression)


def test_calculator_division_by_zero():
    assert calculator("1 / 0")["error"] == "division by zero"


def test_calculator_limits_exponent():
    assert "Exponent" in calculator("9 ** 9 ** 9")["error"]


def test_get_time_returns_utc_iso():
    result = get_time()
    assert datetime.fromisoformat(result["utc"]).utcoffset().total_seconds() == 0
    assert datetime.fromisoformat(result["server_local"]).tzinfo is not None


def test_run_tool_dispatches():
    assert run_tool("calculator", {"expression": "6 * 7"})["result"] == 42


def test_run_tool_unknown_tool():
    assert run_tool("nope", {}) == {"error": "Unbekanntes Tool: nope"}


def test_run_tool_bad_arguments():
    assert run_tool("calculator", {"x": 1})["error"].startswith("TypeError")
