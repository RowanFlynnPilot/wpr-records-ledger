"""Worst-case, empty and one-of-everything data for the site, in the export's exact shapes.

Realistic, not random: Marathon County's real towns and custodians, subjects and
denial reasons the way staff actually paste them, and the sizes a few years of
logging would reach. scripts/stress_site.py renders the site with each set;
tests/test_worst_case.py keeps them in step with the export's whitelists.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import export

AS_OF = date(2027, 3, 1)
GENERATED_AT = datetime(2027, 3, 1, 10, 37, tzinfo=timezone.utc)

TOWNS = ["Bergen", "Berlin", "Bern", "Bevent", "Brighton", "Cassel", "Cleveland", "Day", "Easton", "Eau Pleine",
         "Elderon", "Emmet", "Frankfort", "Franzen", "Green Valley", "Guenther", "Halsey", "Hamburg", "Harrison",
         "Hewitt", "Holton", "Hull", "Johnson", "Knowlton", "Maine", "Marathon", "McMillan", "Mosinee", "Norrie",
         "Plover", "Reid", "Rib Falls", "Rietbrock", "Ringle", "Spencer", "Stettin", "Texas", "Wausau", "Weston",
         "Wien"]
LONG_AGENCY = "Marathon County Conservation, Planning and Zoning Department (Land Information Division)"
AGENCIES = [LONG_AGENCY, "Northcentral Technical College District Board", "UW–Stevens Point at Wausau",
            "Wausau Area Metropolitan Planning Organization"] + [f"Town of {t}" for t in TOWNS]

LONG_REASON = (
    "The requested records are exempt from disclosure under Wis. Stat. § 19.36(10)(b), and the custodian has "
    "conducted the public-interest balancing test as required under Wis. Stat. § 19.35(1)(a) and the common law, "
    "concluding that the public interest in nondisclosure outweighs the strong presumption favoring access. "
) * 7   # pasted from a letter: ~2,000 characters with no paragraph breaks
URL_SUBJECT = ("Records referenced at https://www.ci.wausau.wi.us/departments/public-works/projects/"
               "thomas-street-reconstruction-phase-2/change-orders?year=2025&status=approved")
SUBJECTS = [
    "Emails between the mayor's office and the Wausau Riverfront Development Corporation about the 2025–2026 "
    "Thomas Street reconstruction change orders",
    URL_SUBJECT,
    "Budget",
    "<script>alert(1)</script> & \"quoted\" <b>tags</b> as typed",
    "Hmong-language interpretation contracts (Daim ntawv cog lus txhais lus)",
    "Body-camera footage, Oct. 3 incident\nand the related use-of-force report",
    "Squad car GPS logs",
]
ROUNDS = ["2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]


def _card(agency, requests, open_=0, simple=0, complex_=0, unclassified=0, median=None, median_n=0,
          share=None, judged=0, denials=0, no_reason=0, no_notice=0, reversed_=0, no_records=0,
          location=0, notices=0, appeals=0):
    return export.whitelisted({
        "agency": agency, "requests": requests, "open": open_, "simple_n": simple, "complex_n": complex_,
        "unclassified_n": unclassified, "median_held_wd_simple": median, "median_n": median_n,
        "benchmark_met_share": share, "benchmark_n": judged, "denials": denials,
        "denials_without_reasons": no_reason, "denials_missing_remedy_notice": no_notice,
        "denials_reversed": reversed_, "no_records": no_records, "location_fee_under_50": location,
        "subject_notice_n": notices, "appeals": appeals,
    }, export.SCORECARD_FIELDS)


def _request(ref, agency, filed_on, subject, status, held, met, quoted=None, paid=None, reason=None,
             notice=None, audit=None, channel="email"):
    return export.whitelisted({
        "ref": ref, "agency": agency, "filed_on": filed_on.isoformat(), "public_subject": subject,
        "audit_round": audit, "channel": channel, "status": status, "held_wd": held, "benchmark_result": met,
        "fees_quoted_cents": quoted, "fees_paid_cents": paid, "denial_reason": reason, "remedy_notice": notice,
    }, export.REQUEST_FIELDS)


def _event(ref, on, kind, amount=None):
    return export.whitelisted({"ref": ref, "event_on": on.isoformat(), "event_type": kind,
                               "amount_cents": amount}, export.EVENT_FIELDS)


def _meta(holidays, earliest):
    return export.whitelisted({
        "generated_at": GENERATED_AT.isoformat(timespec="seconds"), "as_of": AS_OF.isoformat(),
        "earliest_filed_on": earliest,
        "law": {"SIMPLE_REQUEST_BENCHMARK_WD": 10, "LOCATION_FEE_THRESHOLD_CENTS": 5000, "MIN_N_FOR_RATES": 5,
                "STATS_ONLY_EMBARGO_DAYS": 90, "HOLIDAYS": holidays},
    }, export.META_FIELDS)


def _slug(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def worst() -> dict:
    """Every hard case at once, spread across the first rows the way real data is."""
    card = [
        _card(LONG_AGENCY, 1284, open_=312, simple=1001, complex_=270, unclassified=13, median=4.5,
              median_n=987, share=0.333, judged=1012, denials=148, no_reason=97, no_notice=121, reversed_=9,
              no_records=64, location=12, notices=31, appeals=27),
        _card("Northcentral Technical College District Board", 1),                 # one of everything, all zero
        _card("UW–Stevens Point at Wausau", 7, open_=7, simple=7, median=None, median_n=0, share=0.0, judged=7),
        _card("Wausau Area Metropolitan Planning Organization", 5, simple=5, median=10, median_n=5, share=1.0,
              judged=5),
    ] + [_card(f"Town of {t}", 2 + i % 9, open_=i % 3, simple=1 + i % 5, complex_=1, median=None,
               median_n=1 + i % 4, share=None, judged=1 + i % 4) for i, t in enumerate(TOWNS)]
    card.sort(key=lambda a: a["agency"])

    requests, events = [], []
    start = date(2025, 7, 7)
    statuses = [("open", 412, False), ("denied", 3, True), ("partially_denied", 11, False),
                ("denial_reversed", 9, True), ("no_records", 1, True), ("withdrawn", 0, None), ("fulfilled", 2, True)]
    for i, subject in enumerate(SUBJECTS):
        agency = AGENCIES[i % 4]
        filed = start + timedelta(days=37 * i)
        status, held, met = statuses[i]
        denial = status in ("denied", "partially_denied", "denial_reversed")
        ref = f"{filed.isoformat()}-{_slug(agency)}-{1 + i % 2}"
        requests.append(_request(
            ref, agency, filed, subject, status, held, met,
            quoted=1_234_567 if i == 0 else 0 if i == 6 else None, paid=1_234_567 if i == 0 else 0 if i == 6 else None,
            reason=(LONG_REASON if i == 1 else None) if denial else None, notice=(i == 1) if denial else None,
            channel="oral" if i == 2 else "hand_delivered" if i == 3 else "email"))
    # One request with a long history: 30 events, every kind.
    long_ref = requests[0]["ref"]
    kinds = ["acknowledged", "delay_notified", "clarification_requested", "clarification_sent", "fee_quoted",
             "fee_disputed", "fee_quoted", "fee_paid", "records_released", "subject_notice_sent"]
    day = start
    for j in range(30):
        kind = kinds[j % len(kinds)]
        day += timedelta(days=3)
        events.append(_event(long_ref, day, kind, 1_234_567 if kind in ("fee_quoted", "fee_paid") else None))
    # Six audit rounds across every agency, one agency missing a round, one with two requests in a round.
    for r, round_ in enumerate(ROUNDS):
        filed = date(2025 + (r + 2) // 4, 3 * ((r + 2) % 4) + 1, 6)
        for k, agency in enumerate(AGENCIES):
            if agency == "Town of Hewitt" and round_ == "2026-Q1":
                continue
            ref = f"{filed.isoformat()}-{_slug(agency)}-1"
            requests.append(_request(ref, agency, filed, "All complaints received about short-term rentals, "
                                     f"{round_}", ["fulfilled", "open", "denied"][(k + r) % 3], (k * 7 + r) % 40,
                                     [True, False, None][(k + r) % 3], audit=round_,
                                     notice=False if (k + r) % 3 == 2 else None))
            if agency == "Town of Day" and round_ == "2026-Q4":
                requests.append(_request(ref[:-1] + "2", agency, filed, "Second audit request, refiled", "open",
                                         3, None, audit=round_))
    requests.sort(key=lambda row: (row["filed_on"], row["agency"]), reverse=True)
    holidays = {a: {"2025": ["2025-01-01", "2025-05-26", "2025-07-04", "2025-09-01", "2025-11-27",
                             "2025-11-28", "2025-12-24", "2025-12-25", "2025-12-31"],
                    "2026": ["2026-01-01", "2026-04-03", "2026-05-25", "2026-07-03", "2026-09-07",
                             "2026-11-26", "2026-11-27", "2026-12-24", "2026-12-25", "2026-12-31"]}
                for a in AGENCIES}
    return {"scorecard": card, "requests": requests, "request_events": events,
            "meta": _meta(holidays, "2025-07-07")}


def empty() -> dict:
    """Launch night: the export has run, nothing is counted yet, no holidays set."""
    return {"scorecard": [], "requests": [], "request_events": [], "meta": _meta({}, None)}


def one() -> dict:
    """Exactly one of everything: every count at 1."""
    filed = date(2026, 10, 5)
    ref = f"{filed.isoformat()}-city-of-wausau-1"
    return {
        "scorecard": [_card("City of Wausau", 1, open_=1, simple=1, median_n=0, judged=1, denials=0)],
        "requests": [_request(ref, "City of Wausau", filed, "Police overtime records, 2025", "open", 1, None,
                              audit="2026-Q4")],
        "request_events": [_event(ref, filed + timedelta(days=1), "acknowledged")],
        "meta": _meta({"City of Wausau": {"2026": ["2026-12-25"]}}, filed.isoformat()),
    }
