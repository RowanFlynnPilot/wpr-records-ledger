"""Tests for snapshot.py."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import snapshot  # noqa: E402


def test_last_quarter():
    assert snapshot.last_quarter(date(2026, 10, 1)) == "2026-Q3"
    assert snapshot.last_quarter(date(2026, 12, 31)) == "2026-Q3"
    assert snapshot.last_quarter(date(2027, 1, 1)) == "2026-Q4"
    assert snapshot.last_quarter(date(2027, 3, 31)) == "2026-Q4"
    assert snapshot.last_quarter(date(2027, 4, 1)) == "2027-Q1"
    assert snapshot.last_quarter(date(2027, 7, 15)) == "2027-Q2"


def test_prints_the_tag(capsys):
    snapshot.main(["--as-of", "2027-01-02"])
    assert capsys.readouterr().out == "data-2026-Q4\n"
