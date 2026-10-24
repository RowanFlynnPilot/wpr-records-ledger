"""Fuzz the export's privacy rules: whitelists, the embargo, and private requests.

Each example is a random ledger: agencies, and requests with random visibility,
age, outcome, fees and denials. Everything that must never be published carries
a unique marker: the subject and denial reason of every unlisted request, and
the code in every agency's name (an agency whose requests are all uncounted must
not appear). The properties check every output, CSV included, against an
independent count of what may be published.

The database property runs the real export, SQL included, as ledger_export
against local Postgres; it skips without LEDGER_TEST_DB_URL (see tests/localdb.py).
"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export  # noqa: E402
import law  # noqa: E402
from tests import localdb  # noqa: E402

AS_OF = date(2027, 3, 1)
HOLIDAY_YEARS = {
    2025: frozenset({date(2025, 12, 25)}),
    2026: frozenset({date(2026, 1, 1), date(2026, 11, 26), date(2026, 12, 25)}),
    2027: frozenset({date(2027, 1, 1)}),
}
AGENCY_WORDS = ["City of Wausau", "Marathon County", "Village of Weston", "D.C. Everest Area School District",
                "Wausau School District", "Village of Kronenwetter"]
NEVER = "NEVEROUT"   # in every column the export must never select


def counted(r) -> bool:
    """Independent of law.py: public counts at once; stats_only at 90 days, closed or not."""
    return r["visibility"] == "public" or (r["visibility"] == "stats_only"
                                           and (AS_OF - r["filed_on"]).days >= 90)


@st.composite
def history(draw, filed: date, reason: str | None):
    """A short, valid event log ending no later than AS_OF."""
    room = (AS_OF - filed).days
    offsets = sorted(draw(st.lists(st.integers(0, room), min_size=4, max_size=4)))
    ack, quote, paid, final_at = (filed + timedelta(days=o) for o in offsets)
    events = []
    if draw(st.booleans()):
        events.append(("acknowledged", ack, {}))
    if draw(st.booleans()):
        amount = draw(st.sampled_from([0, 2500, 1_234_567]))
        events += [("fee_quoted", quote, {"amount_cents": amount}), ("fee_paid", paid, {"amount_cents": amount})]
    final = draw(st.sampled_from([None, "fulfilled", "denied", "partially_denied", "no_records", "withdrawn"]))
    if final in law.DENIALS:
        events.append((final, final_at, {"denial_reason": draw(st.sampled_from([None, reason])),
                                         "remedy_notice": draw(st.booleans())}))
    elif final:
        events.append((final, final_at, {}))
    return [{"event_type": kind, "event_on": day, "amount_cents": None, "location_cents": None,
             "reproduction_cents": None, "other_cents": None, "denial_reason": None, "remedy_notice": None,
             **fields} for kind, day, fields in events]


@st.composite
def ledgers(draw):
    """(agency names, requests in export.fetch's shape)."""
    n_agencies = draw(st.integers(1, 5))
    agencies = [f"{draw(st.sampled_from(AGENCY_WORDS))} AGY{i:02d}" for i in range(n_agencies)]
    requests = []
    for i in range(draw(st.integers(0, 14))):
        visibility = draw(st.sampled_from(["public", "stats_only", "private"]))
        filed = AS_OF - timedelta(days=draw(st.integers(0, 400)))
        listed = visibility == "public"
        marker = f"MARK{i:03d}"                      # only ever in an unlisted request
        requests.append({
            "id": i + 1,
            "agency": draw(st.sampled_from(agencies)),
            "filed_on": filed,
            "channel": draw(st.sampled_from(["email", "portal", "mail", "hand_delivered", "oral"])),
            "public_subject": f"Listed subject {i}" if listed else draw(st.sampled_from([None, f"{marker} subject"])),
            "visibility": visibility,
            "complexity": draw(st.sampled_from([None, "simple", "complex"])),
            "audit_round": draw(st.sampled_from([None, "2026-Q4"])) if listed else None,
            # A request public once and later unlisted keeps its ref; the export must still drop it.
            "public_ref": f"REF{i:03d}" if listed else draw(st.sampled_from([None, f"{marker}-ref"])),
            "events": draw(history(filed, f"Listed reason {i}" if listed else f"{marker} reason")),
        })
    for r in requests:
        r["agency_id"] = agencies.index(r["agency"]) + 1
    return agencies, requests


def published(agencies, requests):
    """Every output the export writes, as the strings that land in its files."""
    derived = [export.derive(r, AS_OF) for r in requests]
    card, listed = export.scorecard(derived), export.public_requests(derived)
    events = export.public_events(derived)
    meta = export.meta(derived, AS_OF, datetime(2027, 3, 1, 10, 37, tzinfo=timezone.utc))
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        export.write_table(data, "scorecard", card, export.SCORECARD_FIELDS)
        export.write_table(data, "requests", listed, export.REQUEST_FIELDS)
        export.write_table(data, "request_events", events, export.EVENT_FIELDS)
        (data / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        files = {p.name: p.read_text(encoding="utf-8") for p in data.iterdir()}
    return card, listed, events, meta, files


def check_privacy(agencies, requests, card, listed, events, meta, files):
    everything = "\n".join(files.values())
    unlisted = [r for r in requests if r["visibility"] != "public"]
    for r in unlisted:
        assert f"MARK{r['id'] - 1:03d}" not in everything, f"request {r['id']} ({r['visibility']}) leaked"
    counted_agencies = {r["agency"] for r in requests if counted(r)}
    for agency in agencies:
        if agency not in counted_agencies:
            assert agency.split()[-1] not in everything, f"{agency} has no counted request but appears"
    assert NEVER not in everything

    # The scorecard counts exactly what may be counted.
    assert {a["agency"] for a in card} == counted_agencies
    for a in card:
        mine = [r for r in requests if r["agency"] == a["agency"] and counted(r)]
        assert a["requests"] == len(mine)
        assert a["open"] == sum(not any(e["event_type"] in law.TERMINAL for e in r["events"]) for r in mine)
    assert sum(a["requests"] for a in card) == sum(map(counted, requests))   # the lead's total

    # The list is exactly the public requests; timelines join only to it.
    public = [r for r in requests if r["visibility"] == "public"]
    assert sorted(row["ref"] for row in listed) == sorted(r["public_ref"] for r in public)
    assert {e["ref"] for e in events} <= {row["ref"] for row in listed}
    assert len(events) == sum(len(r["events"]) for r in public)

    # Every row carries exactly its whitelist.
    assert all(tuple(a) == export.SCORECARD_FIELDS for a in card)
    assert all(tuple(row) == export.REQUEST_FIELDS for row in listed)
    assert all(tuple(e) == export.EVENT_FIELDS for e in events)
    assert tuple(meta) == export.META_FIELDS
    earliest = min((r["filed_on"] for r in requests if counted(r)), default=None)
    assert meta["earliest_filed_on"] == (earliest.isoformat() if earliest else None)


def holidays_for(requests):
    """Lists for the agencies with a counted request, as staff would set them."""
    return {r["agency"]: dict(HOLIDAY_YEARS) for r in requests if counted(r)}


@settings(max_examples=500)   # each ledger counts days across 400-day spans: 500 takes ~20s
@given(ledgers())
def test_the_export_publishes_only_what_it_may(ledger):
    agencies, requests = ledger
    saved = law.HOLIDAYS
    law.HOLIDAYS = holidays_for(requests)
    try:
        check_privacy(agencies, requests, *published(agencies, requests))
    finally:
        law.HOLIDAYS = saved


# ── The same, end to end: SQL, ledger_export and the files on disk ────────────
ADMIN_URL = os.environ.get("LEDGER_TEST_DB_URL")


@pytest.fixture(scope="module")
def privacy_db():
    with localdb.ledger_database(ADMIN_URL, "ledger_privacy_fuzz") as urls:
        yield urls


def seed(owner_url, agencies, requests):
    """Load the ledger with NEVER in every column the export must never select."""
    with psycopg.connect(owner_url) as conn:
        conn.execute("truncate request_events, requests, agencies restart identity")
        for name in agencies:
            conn.execute("insert into agencies (name, custodian_email) values (%s, %s)", (name, f"{NEVER}@example.gov"))
        for r in requests:
            classified = r["complexity"] is not None
            request_id = conn.execute(
                """insert into requests (agency_id, filed_on, channel, filed_by, records_sought, public_subject,
                                         visibility, complexity, complexity_set_by, audit_round)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (r["agency_id"], r["filed_on"], r["channel"], f"{NEVER}-filer", f"{NEVER} sought",
                 r["public_subject"], r["visibility"], r["complexity"],
                 f"{NEVER}-reviewer" if classified else None, r["audit_round"])).fetchone()[0]
            for e in r["events"]:
                conn.execute(
                    """insert into request_events (request_id, event_type, event_on, amount_cents,
                                                   denial_reason, remedy_notice, note, document_url)
                       values (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (request_id, e["event_type"], e["event_on"], e["amount_cents"], e["denial_reason"],
                     e["remedy_notice"], f"{NEVER} note", f"https://drive.example/{NEVER}"))


@pytest.mark.skipif(not ADMIN_URL, reason="LEDGER_TEST_DB_URL is not set (see tests/localdb.py)")
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(ledgers())
def test_the_real_export_publishes_only_what_it_may(privacy_db, ledger):
    owner_url, export_url = privacy_db
    agencies, requests = ledger
    seed(owner_url, agencies, requests)
    saved = law.HOLIDAYS
    law.HOLIDAYS = holidays_for(requests)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            export.run(export_url, out, AS_OF, dry_run=False)
            for path in out.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    assert NEVER.encode() not in data, path
                    for r in requests:
                        if r["visibility"] != "public":
                            assert f"MARK{r['id'] - 1:03d}".encode() not in data, (path, r["visibility"])
            files = {p.name: p.read_text(encoding="utf-8") for p in (out / "data").iterdir()}
            card = json.loads(files["scorecard.json"])
            listed = json.loads(files["requests.json"])
            events = json.loads(files["request_events.json"])
            meta = json.loads(files["meta.json"])
    finally:
        law.HOLIDAYS = saved
    # The database assigned the refs; map them back so the same checks apply.
    public = [r for r in requests if r["visibility"] == "public"]
    assert len(listed) == len(public)
    for r in requests:
        r["public_ref"] = None
    by_subject = {row["public_subject"]: row["ref"] for row in listed}
    for r in public:
        r["public_ref"] = by_subject[r["public_subject"]]
    meta = {**meta, "generated_at": meta["generated_at"]}
    check_privacy(agencies, requests, card, listed, events, meta, files)
