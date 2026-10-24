"""End to end: seed a local Postgres set up like Supabase, run supabase/tests.sql
with those rows present, export as ledger_export and check every output file.

Needs LEDGER_TEST_DB_URL, an admin connection to a local Postgres 16 server
(see tests/localdb.py); skipped without it.
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export  # noqa: E402
import law  # noqa: E402
from tests import localdb, synthetic  # noqa: E402

ADMIN_URL = os.environ.get("LEDGER_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="LEDGER_TEST_DB_URL is not set (see tests/localdb.py)")


@pytest.fixture(scope="module")
def db():
    with localdb.ledger_database(ADMIN_URL) as (owner_url, export_url):
        with psycopg.connect(owner_url) as owner:
            synthetic.seed(owner)
        yield owner_url, export_url


@pytest.fixture(autouse=True)
def test_holidays(monkeypatch):
    monkeypatch.setattr(law, "HOLIDAYS", synthetic.holiday_lists())


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def as_csv_row(row):
    cell = lambda v: "" if v is None else ("true" if v else "false") if isinstance(v, bool) else str(v)  # noqa: E731
    return {k: cell(v) for k, v in row.items()}


def test_schema_tests_pass_with_rows_present(db):
    owner_url, _ = db
    with psycopg.connect(owner_url, autocommit=True) as owner:
        notices = localdb.run_sql_file(owner, export.ROOT / "supabase" / "tests.sql")
        assert "ALL SCHEMA TESTS PASSED" in notices
        # It rolled back: only the seeded rows remain.
        assert owner.execute("select count(*) from requests").fetchone()[0] == len(synthetic.REQUESTS)


def test_export_writes_every_file_as_expected(db, tmp_path, capsys):
    _, export_url = db
    out = tmp_path / "site"
    export.run(export_url, out, synthetic.AS_OF, dry_run=False)
    data = out / "data"

    assert read_json(data / "scorecard.json") == synthetic.EXPECTED_SCORECARD
    assert read_csv(data / "scorecard.csv") == [as_csv_row(r) for r in synthetic.EXPECTED_SCORECARD]
    assert list(read_csv(data / "scorecard.csv")[0]) == list(export.SCORECARD_FIELDS)
    assert read_json(data / "requests.json") == synthetic.EXPECTED_REQUESTS
    assert read_csv(data / "requests.csv") == [as_csv_row(r) for r in synthetic.EXPECTED_REQUESTS]
    assert list(read_csv(data / "requests.csv")[0]) == list(export.REQUEST_FIELDS)
    assert read_json(data / "request_events.json") == synthetic.EXPECTED_EVENTS
    assert read_csv(data / "request_events.csv") == [as_csv_row(r) for r in synthetic.EXPECTED_EVENTS]

    meta = read_json(data / "meta.json")
    assert list(meta) == list(export.META_FIELDS)
    assert meta["as_of"] == "2027-03-01"
    assert meta["earliest_filed_on"] == synthetic.EXPECTED_EARLIEST_FILED_ON
    assert meta["law"] == {
        "SIMPLE_REQUEST_BENCHMARK_WD": 10, "LOCATION_FEE_THRESHOLD_CENTS": 5000,
        "MIN_N_FOR_RATES": 5, "STATS_ONLY_EMBARGO_DAYS": 90,
        "HOLIDAYS": {agency: {str(y): sorted(d.isoformat() for d in days) for y, days in years.items()}
                     for agency, years in synthetic.TEST_HOLIDAYS.items()},
    }
    generated = datetime.fromisoformat(meta["generated_at"])
    assert timedelta(0) <= datetime.now(timezone.utc) - generated < timedelta(minutes=5)

    assert sorted(p.name for p in data.iterdir()) == [
        "meta.json", "request_events.csv", "request_events.json", "requests.csv", "requests.json",
        "scorecard.csv", "scorecard.json"]
    assert (out / "law.py").read_text("utf-8") == (export.ROOT / "law.py").read_text("utf-8")
    for page in ("index.html", "methodology.html"):
        assert (out / page).exists()

    # No never-published field, private request or embargoed request reaches any file.
    for path in out.rglob("*"):
        if path.is_file():
            assert b"SENTINEL" not in path.read_bytes(), path

    printed = capsys.readouterr().out
    print(printed)
    assert "SENTINEL" not in printed and "2 agencies, 22 counted requests, 11 public" in printed


def test_holiday_file_must_name_real_agencies(db, tmp_path, monkeypatch):
    _, export_url = db
    monkeypatch.setitem(law.HOLIDAYS, "City of Testvile", synthetic.TEST_HOLIDAYS[synthetic.CITY])
    with pytest.raises(export.ExportError, match="not in the agencies table: City of Testvile"):
        export.run(export_url, tmp_path / "site", synthetic.AS_OF, dry_run=True)


def test_dry_run_writes_nothing(db, tmp_path):
    _, export_url = db
    export.run(export_url, tmp_path / "site", synthetic.AS_OF, dry_run=True)
    assert not (tmp_path / "site").exists()


def test_export_refuses_any_role_but_ledger_export(db, tmp_path):
    owner_url, _ = db
    with pytest.raises(export.ExportError, match="must connect as ledger_export"):
        export.run(owner_url, tmp_path / "site", synthetic.AS_OF, dry_run=True)


def test_ledger_export_session_is_read_only(db):
    _, export_url = db
    with psycopg.connect(export_url) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into agencies (name) values ('nope')")


def test_invalid_event_log_in_the_database_stops_the_export(db, tmp_path):
    owner_url, export_url = db
    with psycopg.connect(owner_url) as owner:   # rolled back on exit below
        request_id = owner.execute(
            """insert into requests (agency_id, filed_on, channel, filed_by, records_sought, visibility)
               select id, '2026-10-01', 'email', 'SENTINEL-filer', 'bad', 'stats_only' from agencies
               where name = %s returning id""", (synthetic.CITY,)).fetchone()[0]
        owner.execute("""insert into request_events (request_id, event_type, event_on, amount_cents)
                         values (%s, 'fee_quoted', '2026-10-02', 100)""", (request_id,))
        owner.execute("""insert into request_events (request_id, event_type, event_on)
                         values (%s, 'fulfilled', '2026-10-05')""", (request_id,))
        owner.commit()
        try:
            with pytest.raises(export.ExportError, match="^1 request\\(s\\) failed validation") as err:
                export.run(export_url, tmp_path / "site", synthetic.AS_OF, dry_run=False)
            assert str(request_id) not in str(err.value)
            assert not (tmp_path / "site").exists()
            with pytest.raises(export.ExportError, match=f"request {request_id}: .*unanswered fee_quoted"):
                export.run(export_url, tmp_path / "site", synthetic.AS_OF, dry_run=True, name_requests=True)
        finally:
            owner.execute("delete from request_events where request_id = %s", (request_id,))
            owner.execute("delete from requests where id = %s", (request_id,))
            owner.commit()


# Each mistake the database rejects at entry, which law.validate must reject too.
ENTRY_CHECKS = [
    ("event dated before filing", [synthetic.ev("acknowledged", 9, 30)]),
    ("second final event", [synthetic.ev("fulfilled", 10, 5), synthetic.ev("no_records", 10, 9)]),
    ("event after withdrawn", [synthetic.ev("withdrawn", 10, 5), synthetic.ev("acknowledged", 10, 6)]),
    ("withdrawn dated before a logged event", [synthetic.ev("acknowledged", 10, 6), synthetic.ev("withdrawn", 10, 5)]),
]


@pytest.mark.parametrize("label, events", ENTRY_CHECKS, ids=[c[0] for c in ENTRY_CHECKS])
def test_entry_checks_agree_with_law_validate(db, label, events):
    owner_url, _ = db
    filed = synthetic.d(10, 1)
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, events, synthetic.AS_OF)
    with psycopg.connect(owner_url) as owner:   # never committed
        request_id = owner.execute(
            """insert into requests (agency_id, filed_on, channel, filed_by, records_sought)
               select id, %s, 'email', 'SENTINEL-filer', 'entry check' from agencies where name = %s
               returning id""", (filed, synthetic.CITY)).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            for e in events:
                owner.execute("insert into request_events (request_id, event_type, event_on) values (%s, %s, %s)",
                              (request_id, e["event_type"], e["event_on"]))
        owner.rollback()


def test_filed_on_cannot_move_past_logged_events(db):
    owner_url, _ = db
    with psycopg.connect(owner_url) as owner:   # never committed
        with pytest.raises(psycopg.errors.CheckViolation):
            owner.execute("update requests set filed_on = '2026-12-01' where public_subject = %s",
                          ("Police overtime records, 2025",))
        owner.rollback()
