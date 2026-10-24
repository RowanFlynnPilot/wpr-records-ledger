"""Synthetic agencies, requests and events for the export tests and the site preview.

Every expected value below was worked out by hand from the calendar, not by
running the code. Fields that must never be published carry the marker
SENTINEL, so a test can search every output file for it.
"""
from __future__ import annotations

from datetime import date

AS_OF = date(2026, 12, 15)   # a Tuesday

CITY = "City of Testville"
DISTRICT = "Testville School District"
VILLAGE = "Village of Sample (SENTINEL)"   # only private and embargoed requests: never published
COUNTY = "Sample County (SENTINEL)"        # no requests: never published
AGENCIES = (CITY, DISTRICT, VILLAGE, COUNTY)


def _days(*isos: str) -> frozenset[date]:
    return frozenset(date.fromisoformat(d) for d in isos)


# Test-only holiday lists, not the editor's. The district's differ from the
# city's: Good Friday off, the day after Thanksgiving open. The village and
# county have none, since nothing of theirs is counted.
TEST_HOLIDAYS = {
    CITY: {
        2025: _days("2025-01-01", "2025-05-26", "2025-07-04", "2025-09-01",
                    "2025-11-27", "2025-11-28", "2025-12-24", "2025-12-25"),
        2026: _days("2026-01-01", "2026-05-25", "2026-07-03", "2026-09-07",
                    "2026-11-26", "2026-11-27", "2026-12-24", "2026-12-25"),
    },
    DISTRICT: {
        2025: _days("2025-01-01", "2025-04-18", "2025-05-26", "2025-07-04", "2025-09-01",
                    "2025-11-27", "2025-12-24", "2025-12-25"),
        2026: _days("2026-01-01", "2026-04-03", "2026-05-25", "2026-07-03", "2026-09-07",
                    "2026-11-26", "2026-12-24", "2026-12-25"),
    },
}


def holiday_lists(*extra_agencies: str) -> dict:
    """A fresh copy of TEST_HOLIDAYS, with extra agencies given the city's list."""
    holidays = {agency: dict(years) for agency, years in TEST_HOLIDAYS.items()}
    for agency in extra_agencies:
        holidays[agency] = dict(TEST_HOLIDAYS[CITY])
    return holidays

DENIAL_REASON = "Records are part of an open investigation; the public interest in nondisclosure outweighs disclosure."


def d(m: int, day: int) -> date:
    return date(2026, m, day)


def ev(event_type: str, m: int, day: int, **fields) -> dict:
    return {"event_type": event_type, "event_on": d(m, day), "amount_cents": None,
            "location_cents": None, "reproduction_cents": None, "other_cents": None,
            "denial_reason": None, "remedy_notice": None, **fields}


def req(key, agency, filed_on, channel, visibility, complexity, events, public_subject=None,
        audit_round=None):
    return {"key": key, "agency": agency, "filed_on": filed_on, "channel": channel,
            "visibility": visibility, "complexity": complexity, "events": events,
            "public_subject": public_subject or f"SENTINEL subject {key}", "audit_round": audit_round}


# Held working days are in the comments, counted from the filing day up to,
# not including, the final event (or AS_OF while open).
REQUESTS = [
    # 10/1-10/7: 5 days. Met.
    req("R1", CITY, d(10, 1), "email", "public", "simple",
        [ev("acknowledged", 10, 2), ev("fulfilled", 10, 8)], "Police overtime records, 2025",
        audit_round="2026-Q4"),
    # 10/1-10/29: 21 days. Missed.
    req("R2", CITY, d(10, 1), "email", "stats_only", "simple", [ev("fulfilled", 10, 30)]),
    # Clarification pause 10/20-10/21: 10/19, 10/22, 10/23 = 3. Met.
    req("R3", CITY, d(10, 19), "portal", "public", "simple",
        [ev("clarification_requested", 10, 20), ev("clarification_sent", 10, 22), ev("fulfilled", 10, 26)],
        "Snowplow GPS logs, January 2026"),
    # Fee pause 10/21-10/27: 10/19, 10/20, 10/28 = 3. Met. A $25 location fee: under the $50 floor.
    req("R4", CITY, d(10, 19), "email", "public", "simple",
        [ev("fee_quoted", 10, 21, amount_cents=3250, location_cents=2500, reproduction_cents=750, other_cents=0),
         ev("fee_paid", 10, 28, amount_cents=3250), ev("fulfilled", 10, 29)],
        "Building inspection reports, 500 block of Main St."),
    # Written (mail) denial with no reason and no remedy notice, then a DA appeal. 11/2-11/6: 5. Met.
    req("R5", CITY, d(11, 2), "mail", "public", "simple",
        [ev("denied", 11, 9, remedy_notice=False), ev("appealed_da", 11, 16)],
        "Council members' emails about the budget"),
    # Oral request, partially denied with no reason or notice: counted as a denial,
    # not against the written-denial rules. 11/2-11/3: 2. Met.
    req("R6", CITY, d(11, 2), "oral", "stats_only", "simple",
        [ev("partially_denied", 11, 4, remedy_notice=False)]),
    # Interim batch doesn't stop the clock; Thanksgiving and the Friday after are skipped:
    # 11/16-20 (5) + 11/23-25 (3) + 11/30 (1) = 9. Met (11 without the holidays).
    req("R7", CITY, d(11, 16), "email", "stats_only", "simple",
        [ev("records_released", 11, 18), ev("fulfilled", 12, 1)]),
    # Withdrawn inside 10 days: 2, not judged.
    req("R8", CITY, d(10, 5), "email", "public", "simple", [ev("withdrawn", 10, 7)],
        "Parking ticket totals by month"),
    # s. 19.356 notice on day 3: not judged, not in the median.
    req("R9", CITY, d(10, 1), "email", "stats_only", "simple",
        [ev("subject_notice_sent", 10, 5), ev("fulfilled", 10, 27)]),
    # Notice after 12 days held: missed. Held to release 10/1-11/6 = 22 + 5 = 27.
    req("R10", CITY, d(10, 1), "email", "stats_only", "simple",
        [ev("subject_notice_sent", 10, 19), ev("fulfilled", 11, 9)]),
    # Open since 11/2: 5+5+5+3+5+5+1 = 29 to AS_OF. Missed.
    req("R11", CITY, d(11, 2), "email", "public", "simple", [], "Contract with body-camera vendor"),
    # stats_only, open, 8 days old: inside the embargo, counted nowhere.
    req("R12", CITY, d(12, 7), "email", "stats_only", "simple", [ev("acknowledged", 12, 8)]),
    # stats_only, open, 105 days old: past the embargo, counted. Labor Day skipped:
    # Sep 21 + Oct 22 + Nov 19 + Dec 10 = 72. Missed.
    req("R13", CITY, d(9, 1), "email", "stats_only", "simple", [ev("acknowledged", 9, 2)]),
    # Complex, quote disputed then revised and paid. Paused 9/21 and 10/5:
    # 9/14-30 (12) + 10/1-2 (2) + 10/6-30 (19) + 11/2-25 (18) = 51. Latest quote $90.
    req("R14", CITY, d(9, 14), "email", "public", "complex",
        [ev("fee_quoted", 9, 21, amount_cents=15000), ev("fee_disputed", 9, 22),
         ev("fee_quoted", 10, 5, amount_cents=9000), ev("fee_paid", 10, 6, amount_cents=9000),
         ev("fulfilled", 11, 30)],
        "Fire department response times, 2024–2026"),
    # Unclassified, no records: 10/26-10/29 = 4.
    req("R15", CITY, d(10, 26), "email", "public", None, [ev("no_records", 10, 30)],
        "Lead service line inventory"),
    # Private: never exported, not even in earliest_filed_on.
    req("R16", CITY, date(2026, 8, 3), "email", "private", "simple", [ev("fulfilled", 8, 5)]),
    # Waived fee (paid 0) on a quote with no location charge. 10/12 + 10/14 = 2. Met.
    req("R17", CITY, d(10, 12), "email", "stats_only", "simple",
        [ev("fee_quoted", 10, 13, amount_cents=500, location_cents=0, reproduction_cents=500, other_cents=0),
         ev("fee_paid", 10, 14, amount_cents=0), ev("fulfilled", 10, 15)]),
    # A written denial that follows the law: reasons and remedy notice. 11/9-11/12 = 4.
    req("R18", CITY, d(11, 9), "email", "public", "complex",
        [ev("denied", 11, 13, denial_reason=DENIAL_REASON, remedy_notice=True)],
        "Use-of-force reports, 2025"),
    # Quote, payment and release all on 11/11, logged in the wrong order. 11/9-11/10 = 2. Met.
    req("R19", CITY, d(11, 9), "email", "stats_only", "simple",
        [ev("fulfilled", 11, 11), ev("fee_paid", 11, 11, amount_cents=1000),
         ev("fee_quoted", 11, 11, amount_cents=1000)]),

    # Below the small-sample floor: two simple requests.
    req("S1", DISTRICT, d(10, 5), "email", "public", "simple", [ev("fulfilled", 10, 9)], "Bus contract bids",
        audit_round="2026-Q4"),
    # Fee pause 10/6-10/11: 10/5 + 10/12-23 (10) = 11. Missed.
    req("S2", DISTRICT, d(10, 5), "hand_delivered", "stats_only", "simple",
        [ev("fee_quoted", 10, 6, amount_cents=1200), ev("fee_paid", 10, 12, amount_cents=1200),
         ev("fulfilled", 10, 26)]),
    req("S3", DISTRICT, d(10, 12), "email", "stats_only", "complex", [ev("fulfilled", 11, 20)]),
    req("S4", DISTRICT, d(12, 1), "email", "stats_only", "simple", []),   # embargoed

    req("V1", VILLAGE, d(10, 1), "email", "private", "simple", [ev("fulfilled", 10, 5)]),
    req("V2", VILLAGE, d(12, 10), "email", "stats_only", None, []),          # embargoed
]

EXPECTED_SCORECARD = [
    {"agency": CITY, "requests": 17, "open": 2, "simple_n": 14, "complex_n": 2, "unclassified_n": 1,
     # R1 5, R2 21, R3 3, R4 3, R5 5, R6 2, R7 9, R10 27, R17 2, R19 2
     "median_held_wd_simple": 4.0, "median_n": 10,
     # met: R1 R3 R4 R5 R6 R7 R17 R19; missed: R2 R10 R11 R13
     "benchmark_met_share": 0.667, "benchmark_n": 12,
     "denials": 3, "denials_without_reasons": 1, "denials_missing_remedy_notice": 1, "no_records": 1,
     "location_fee_under_50": 1, "subject_notice_n": 2, "appeals": 1},
    {"agency": DISTRICT, "requests": 3, "open": 0, "simple_n": 2, "complex_n": 1, "unclassified_n": 0,
     "median_held_wd_simple": None, "median_n": 2,
     "benchmark_met_share": None, "benchmark_n": 2,
     "denials": 0, "denials_without_reasons": 0, "denials_missing_remedy_notice": 0, "no_records": 0,
     "location_fee_under_50": 0, "subject_notice_n": 0, "appeals": 0},
]


def _listed(agency, filed_on, subject, status, held, met, quoted=None, paid=None, reason=None, notice=None,
            audit=None):
    return {"agency": agency, "filed_on": filed_on, "public_subject": subject, "audit_round": audit,
            "status": status,
            "held_wd": held, "benchmark_result": met, "fees_quoted_cents": quoted,
            "fees_paid_cents": paid, "denial_reason": reason, "remedy_notice": notice}


EXPECTED_REQUESTS = [
    _listed(CITY, "2026-11-09", "Use-of-force reports, 2025", "denied", 4, None,
            reason=DENIAL_REASON, notice=True),
    _listed(CITY, "2026-11-02", "Contract with body-camera vendor", "open", 29, False),
    _listed(CITY, "2026-11-02", "Council members' emails about the budget", "denied", 5, True, notice=False),
    _listed(CITY, "2026-10-26", "Lead service line inventory", "no_records", 4, None),
    _listed(CITY, "2026-10-19", "Building inspection reports, 500 block of Main St.", "fulfilled", 3, True,
            quoted=3250, paid=3250),
    _listed(CITY, "2026-10-19", "Snowplow GPS logs, January 2026", "fulfilled", 3, True),
    _listed(CITY, "2026-10-05", "Parking ticket totals by month", "withdrawn", 2, None),
    _listed(DISTRICT, "2026-10-05", "Bus contract bids", "fulfilled", 4, True, audit="2026-Q4"),
    _listed(CITY, "2026-10-01", "Police overtime records, 2025", "fulfilled", 5, True, audit="2026-Q4"),
    _listed(CITY, "2026-09-14", "Fire department response times, 2024–2026", "fulfilled", 51, None,
            quoted=9000, paid=9000),
]

EXPECTED_EARLIEST_FILED_ON = "2026-09-01"   # R13; private R16 (Aug 3) is excluded


def as_fetched(requests: list[dict] = REQUESTS) -> list[dict]:
    """The requests in the shape export.fetch returns (private ones included,
    to show the metrics drop them even if a query didn't)."""
    names = list(AGENCIES) + sorted({r["agency"] for r in requests} - set(AGENCIES))
    agency_ids = {name: i + 1 for i, name in enumerate(names)}
    return [{"id": i + 1, "agency_id": agency_ids[r["agency"]], "agency": r["agency"],
             "filed_on": r["filed_on"], "channel": r["channel"], "public_subject": r["public_subject"],
             "visibility": r["visibility"], "complexity": r["complexity"], "audit_round": r["audit_round"],
             "events": [dict(e) for e in r["events"]]}
            for i, r in enumerate(requests)]


def seed(conn) -> None:
    """Insert everything, as the owner, with SENTINEL in every never-published column."""
    with conn.cursor() as cur:
        ids = {}
        for name in AGENCIES:
            ids[name] = cur.execute("insert into agencies (name, custodian_email) values (%s, %s) returning id",
                                    (name, "SENTINEL@clerk.example")).fetchone()[0]
        for r in REQUESTS:
            classified = r["complexity"] is not None
            request_id = cur.execute(
                """insert into requests (agency_id, filed_on, channel, filed_by, records_sought,
                                         public_subject, visibility, complexity, complexity_set_by, audit_round)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (ids[r["agency"]], r["filed_on"], r["channel"], "SENTINEL-filer",
                 f"SENTINEL records_sought {r['key']}", r["public_subject"], r["visibility"],
                 r["complexity"], "SENTINEL-reviewer" if classified else None,
                 r["audit_round"])).fetchone()[0]
            for e in r["events"]:
                cur.execute(
                    """insert into request_events (request_id, event_type, event_on, amount_cents,
                                                   location_cents, reproduction_cents, other_cents,
                                                   denial_reason, remedy_notice, note, document_url)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (request_id, e["event_type"], e["event_on"], e["amount_cents"], e["location_cents"],
                     e["reproduction_cents"], e["other_cents"], e["denial_reason"], e["remedy_notice"],
                     f"SENTINEL note {r['key']}", "https://drive.example/SENTINEL"))
