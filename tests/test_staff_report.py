"""Tests for staff_report.py on the synthetic data (at synthetic.AS_OF, 2027-03-01)."""
import os
import sys
from datetime import date
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import law  # noqa: E402
import staff_report  # noqa: E402
from tests import localdb, synthetic  # noqa: E402
from tests.synthetic import AS_OF, ev  # noqa: E402

EXTRA = [
    # waiting on WPR: a quote from Feb. 22 nobody answered
    synthetic.req("X1", synthetic.CITY, date(2027, 2, 15), "email", "stats_only", "complex",
                  [ev("fee_quoted", 1, 1, event_on=date(2027, 2, 22), amount_cents=500)]),
    # would stop the export
    synthetic.req("X2", synthetic.CITY, date(2026, 10, 1), "email", "stats_only", "simple",
                  [ev("fee_quoted", 10, 2, amount_cents=100), ev("fulfilled", 10, 5)]),
    # at an agency with no holiday list: an open public request, and a closed complex one counted at 90+ days
    synthetic.req("X3", synthetic.VILLAGE, date(2027, 2, 1), "email", "public", "simple",
                  [ev("acknowledged", 2, 1, event_on=date(2027, 2, 2))]),
    synthetic.req("X4", synthetic.VILLAGE, date(2026, 7, 1), "email", "stats_only", "complex",
                  [ev("fulfilled", 7, 9)]),
    # private at the same agency: never measured, so no list needed
    synthetic.req("X5", synthetic.VILLAGE, date(2026, 7, 1), "email", "private", "simple", []),
]


@pytest.fixture(autouse=True)
def test_holidays(monkeypatch):
    monkeypatch.setattr(law, "HOLIDAYS", synthetic.holiday_lists())


def staff_rows(requests):
    rows = synthetic.as_fetched(requests)
    for row, r in zip(rows, requests):
        row.update(filed_by="SH", records_sought=f"records for {r['key']}")
    return rows


def keys(lines):
    return sorted(line.split("records for ")[1].split()[0] for line in lines)


def test_findings_on_the_synthetic_log():
    found = staff_report.findings(staff_rows(synthetic.REQUESTS + EXTRA), AS_OF)
    assert keys(found["invalid"]) == ["X2"]
    assert "follows an unanswered fee_quoted" in found["invalid"][0]
    assert keys(found["no_holidays"]) == ["V2", "X3", "X4"]         # V2 enters the figures within 14 days
    assert keys(found["waiting"]) == ["X1"] and "unanswered: fee_quoted" in found["waiting"][0]
    # R11 80, R12 57, R13 123 and S4 61 working days held; the village's V2 is unclassified, not simple
    assert keys(found["late"]) == ["R11", "R12", "R13", "S4"]
    assert keys(found["quiet"]) == ["R11", "R12", "R13", "S4", "V2", "X5"]   # X1 and X3 logged within 30 days
    assert keys(found["unclassified"]) == ["R15", "V2"]
    assert keys(found["leaving_embargo"]) == ["R12", "V2"]              # 84 and 81 days old
    assert "enters the figures 2027-03-07" in next(x for x in found["leaving_embargo"] if "R12" in x)


def test_render_lists_every_section():
    text = staff_report.render(staff_report.findings(staff_rows(synthetic.REQUESTS), AS_OF), AS_OF)
    for _, title in staff_report.SECTIONS:
        assert title in text
    assert "Would stop the export (fix these first): none" in text


def test_refuses_to_run_in_actions(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(SystemExit, match="never run it in Actions"):
        staff_report.main([])


ADMIN_URL = os.environ.get("LEDGER_TEST_DB_URL")


@pytest.mark.skipif(not ADMIN_URL, reason="LEDGER_TEST_DB_URL is not set (see tests/localdb.py)")
def test_reads_every_request_as_ledger_export(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with localdb.ledger_database(ADMIN_URL, "ledger_staff_report") as (owner_url, export_url):
        with psycopg.connect(owner_url) as owner:
            synthetic.seed(owner)
        with psycopg.connect(export_url) as conn:
            requests = staff_report.fetch(conn)
    assert len(requests) == len(synthetic.REQUESTS)                 # private ones too
    found = staff_report.findings(requests, AS_OF)
    assert len(found["late"]) == 4 and found["invalid"] == []
