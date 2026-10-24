"""Tests for backfill.py: parsing without a database, loading against local Postgres
(the loading tests skip without LEDGER_TEST_DB_URL, see tests/localdb.py)."""
import os
import sys
from datetime import date
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backfill  # noqa: E402
from tests import localdb  # noqa: E402

AS_OF = date(2026, 12, 15)
REQUESTS_HEADER = ",".join(backfill.REQUEST_COLUMNS)
EVENTS_HEADER = ",".join(backfill.EVENT_COLUMNS)
GOOD_REQUESTS = [
    "W-1,City of Wausau,2026-10-01,email,SH,Police overtime 2025,,stats_only,simple,RF,",
    "W-2,City of Wausau,2026-10-05,mail,SH,Use-of-force reports,Use-of-force reports 2025,public,complex,RF,2026-Q4",
]
GOOD_EVENTS = [
    "W-1,fee_quoted,2026-10-02,61.25,60.00,1.25,0,,,quote letter,https://drive.example/1",
    "W-1,fee_paid,2026-10-05,$61.25,,,,,,,",
    "W-1,fulfilled,2026-10-08,,,,,,,,",
    'W-2,denied,2026-10-09,,,,,"Open investigation, s. 19.35(1)(a)",no,,',
]


def write(tmp_path, requests, events):
    r, e = tmp_path / "requests.csv", tmp_path / "events.csv"
    r.write_text("\n".join([REQUESTS_HEADER, *requests]) + "\n", encoding="utf-8")
    e.write_text("\n".join([EVENTS_HEADER, *events]) + "\n", encoding="utf-8")
    return r, e


def parsed(tmp_path, requests=GOOD_REQUESTS, events=GOOD_EVENTS):
    r, e = write(tmp_path, requests, events)
    return backfill.attach(backfill.read_rows(r, backfill.REQUEST_COLUMNS),
                           backfill.read_rows(e, backfill.EVENT_COLUMNS))


# ── parsing ───────────────────────────────────────────────────────────────────
def test_parses_dollars_dates_and_yes_no(tmp_path):
    w1, w2 = parsed(tmp_path)
    assert w1["filed_on"] == date(2026, 10, 1) and w1["public_subject"] is None
    quote, paid, _ = w1["events"]
    assert (quote["amount_cents"], quote["location_cents"], quote["reproduction_cents"], quote["other_cents"]) \
        == (6125, 6000, 125, 0)
    assert paid["amount_cents"] == 6125                          # "$61.25"
    assert w2["events"][0]["denial_reason"] == "Open investigation, s. 19.35(1)(a)"
    assert w2["events"][0]["remedy_notice"] is False
    backfill.validate([w1, w2], AS_OF)


def test_a_bad_file_names_every_bad_cell(tmp_path):
    events = ["W-1,fee_quoted,2026-10-02,61.255,,,,,,,", "W-1,fulfilled,10/8/2026,,,,,,,,",
              "W-2,denied,2026-10-09,,,,,,maybe,,"]
    with pytest.raises(backfill.BackfillError) as err:
        parsed(tmp_path, events=events)
    message = str(err.value)
    assert "line 2, amount" in message and "fractions of a cent" in message
    assert "line 3, event_on" in message
    assert "line 4, remedy_notice" in message and "yes or no" in message


def test_header_must_match_the_template(tmp_path):
    r, e = write(tmp_path, GOOD_REQUESTS, GOOD_EVENTS)
    e.write_text("request,event_type,event_on\n", encoding="utf-8")
    with pytest.raises(backfill.BackfillError, match="header must be exactly"):
        backfill.read_rows(e, backfill.EVENT_COLUMNS)


def test_required_cells(tmp_path):
    with pytest.raises(backfill.BackfillError, match="visibility is required"):
        parsed(tmp_path, requests=["W-1,City of Wausau,2026-10-01,email,SH,x,,,,,"], events=[])


def test_keys_must_match(tmp_path):
    with pytest.raises(backfill.BackfillError, match="appears twice"):
        parsed(tmp_path, requests=GOOD_REQUESTS + GOOD_REQUESTS[:1])
    with pytest.raises(backfill.BackfillError, match="not in the requests file: W-9"):
        parsed(tmp_path, events=GOOD_EVENTS + ["W-9,fulfilled,2026-10-08,,,,,,,,"])


def test_law_validate_runs_before_anything_is_inserted(tmp_path):
    unanswered = ["W-1,fee_quoted,2026-10-02,10,,,,,,,", "W-1,fulfilled,2026-10-08,,,,,,,,"]
    with pytest.raises(backfill.BackfillError, match="request W-1: fulfilled follows an unanswered fee_quoted"):
        backfill.validate(parsed(tmp_path, requests=GOOD_REQUESTS[:1], events=unanswered), AS_OF)


# ── loading, against local Postgres ───────────────────────────────────────────
ADMIN_URL = os.environ.get("LEDGER_TEST_DB_URL")
needs_db = pytest.mark.skipif(not ADMIN_URL, reason="LEDGER_TEST_DB_URL is not set (see tests/localdb.py)")


@pytest.fixture(scope="module")
def owner_url():
    with localdb.ledger_database(ADMIN_URL, "ledger_backfill") as (url, _):
        with psycopg.connect(url) as owner:
            owner.execute("insert into agencies (name) values ('City of Wausau')")
        yield url


def counts(url):
    with psycopg.connect(url) as conn:
        return (conn.execute("select count(*) from requests").fetchone()[0],
                conn.execute("select count(*) from request_events").fetchone()[0])


@needs_db
def test_dry_run_checks_and_inserts_nothing(owner_url, tmp_path, capsys):
    backfill.run(owner_url, *write(tmp_path, GOOD_REQUESTS, GOOD_EVENTS), AS_OF, dry_run=True)
    assert "2 requests and 4 events checked; dry run, nothing inserted" in capsys.readouterr().out
    assert counts(owner_url) == (0, 0)


@needs_db
def test_load_inserts_everything_then_refuses_a_rerun(owner_url, tmp_path):
    files = write(tmp_path, GOOD_REQUESTS, GOOD_EVENTS)
    backfill.run(owner_url, *files, AS_OF, dry_run=False)
    assert counts(owner_url) == (2, 4)
    with psycopg.connect(owner_url) as conn:
        assert conn.execute("select amount_cents, location_cents, note from request_events "
                            "where event_type = 'fee_quoted'").fetchone() == (6125, 6000, "quote letter")
        assert conn.execute("select audit_round, visibility::text from requests where filed_on = '2026-10-05'"
                            ).fetchone() == ("2026-Q4", "public")
    with pytest.raises(backfill.BackfillError, match="request W-1: already in the database"):
        backfill.run(owner_url, *files, AS_OF, dry_run=False)
    assert counts(owner_url) == (2, 4)


@needs_db
def test_one_bad_row_in_the_database_rolls_back_the_batch(owner_url, tmp_path):
    before = counts(owner_url)
    requests = ["N-1,City of Wausau,2026-11-02,email,SH,New one,,stats_only,,,",
                "N-2,City of Wausau,2026-11-02,fax,SH,Faxed one,,stats_only,,,",          # no such channel
                "N-3,Village of Nowhere,2026-11-02,email,SH,Elsewhere,,stats_only,,,",     # no such agency
                "N-4,City of Wausau,2026-11-02,email,SH,Self-classified,,stats_only,simple,SH,"]  # filer classified
    with pytest.raises(backfill.BackfillError) as err:
        backfill.run(owner_url, *write(tmp_path, requests, []), AS_OF, dry_run=False)
    message = str(err.value)
    assert "request N-2:" in message and "request N-3: agency 'Village of Nowhere'" in message
    assert "request N-4:" in message and "request N-1" not in message
    assert counts(owner_url) == before                                   # N-1 was rolled back too
