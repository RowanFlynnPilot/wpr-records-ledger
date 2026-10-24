"""Statutory values and clock rules for the Records Ledger.

Everything the scorecard measures against lives here, and the methodology
page prints it. Change a rule here, nowhere else.
"""
from __future__ import annotations

from datetime import date, timedelta

# ── Benchmarks ────────────────────────────────────────────────────────────────
# DOJ guidance, not a statutory deadline: ~10 working days is generally
# reasonable for a simple request (Public Records Law Compliance Guide, June 2025).
SIMPLE_REQUEST_BENCHMARK_WD = 10
LOCATION_FEE_THRESHOLD_CENTS = 5000   # s. 19.35(3)(c): location fees only if location cost >= $50
MIN_N_FOR_RATES = 5                   # below this n, show the count only, no median or share
STATS_ONLY_EMBARGO_DAYS = 90          # stats_only requests count once closed or this old

# Days agency offices are closed, set by the editor and printed on the
# methodology page. working_days() refuses any year missing from this map, so
# 2024, 2025 and 2026 must be filled in before the backfill export.
HOLIDAYS: dict[int, frozenset[date]] = {}

# ── Event classes ─────────────────────────────────────────────────────────────
AGENCY_TERMINAL = frozenset({"fulfilled", "partially_denied", "denied", "no_records"})
TERMINAL = AGENCY_TERMINAL | {"withdrawn"}
REMEDY_EVENTS = frozenset({"appealed_da", "appealed_ag", "mandamus_filed"})
DENIALS = frozenset({"denied", "partially_denied"})
# s. 19.35(4)(b): a written request gets a written denial with specific reasons
# and notice of review by mandamus or the DA or AG. Only an oral request is unwritten.
UNWRITTEN_CHANNELS = frozenset({"oral"})
# The agency's clock stops while it waits on WPR: (pause starts, events that end it).
PAUSES = (
    ("clarification_requested", ("clarification_sent",)),
    ("fee_quoted", ("fee_paid", "fee_disputed")),
)
# Events logged on the same day sort in the order they must have happened: the
# agency asks, WPR answers, the request closes, WPR seeks a remedy.
_SAME_DAY_ORDER = {
    **{kind: 1 for _, ends in PAUSES for kind in ends},
    **{kind: 2 for kind in TERMINAL},
    **{kind: 3 for kind in REMEDY_EVENTS},
}


class InvalidRequest(ValueError):
    pass


def _require_holidays(start: date, end: date) -> None:
    for year in range(start.year, end.year + 1):
        if year not in HOLIDAYS:
            raise KeyError(f"No holiday list for {year}: set law.HOLIDAYS[{year}]")


def working_days(start: date, end: date, excluded: frozenset[date] = frozenset()) -> int:
    """Working days from `start` up to, not including, `end`."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    _require_holidays(start, end)
    count, day = 0, start
    while day < end:
        if day.weekday() < 5 and day not in HOLIDAYS[day.year] and day not in excluded:
            count += 1
        day += timedelta(days=1)
    return count


def _sorted(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: (e["event_on"], _SAME_DAY_ORDER.get(e["event_type"], 0)))


def validate(filed_on: date, events: list[dict], as_of: date) -> None:
    """Raise InvalidRequest for an event log the clock rules can't measure."""
    if filed_on > as_of:
        raise InvalidRequest(f"filed on {filed_on}, after {as_of}")
    events = _sorted(events)
    withdrawn = False
    closed_by: str | None = None
    open_pause: str | None = None
    for e in events:
        kind = e["event_type"]
        if e["event_on"] < filed_on:
            raise InvalidRequest(f"{kind} on {e['event_on']} is before filing on {filed_on}")
        if e["event_on"] > as_of:
            raise InvalidRequest(f"{kind} on {e['event_on']} is after {as_of}")
        if closed_by and kind in TERMINAL:
            raise InvalidRequest(f"{kind} on {e['event_on']} follows the request's final event, "
                                 f"{closed_by}; log a later batch as records_released")
        if withdrawn and kind not in REMEDY_EVENTS:
            raise InvalidRequest(f"{kind} on {e['event_on']} comes after withdrawn")
        if open_pause and kind in AGENCY_TERMINAL:
            raise InvalidRequest(f"{kind} on {e['event_on']} follows an unanswered {open_pause}; "
                                 f"log WPR's reply (or fee_paid with 0 for a waived fee) first")
        for start, ends in PAUSES:
            if kind == start:
                open_pause = start
            elif kind in ends and open_pause == start:
                open_pause = None
        withdrawn = withdrawn or kind == "withdrawn"
        closed_by = closed_by or (kind if kind in TERMINAL else None)


def final_event(events: list[dict]) -> dict | None:
    """The first terminal event: the agency's final response, or WPR withdrawing."""
    return next((e for e in _sorted(events) if e["event_type"] in TERMINAL), None)


def clock_stop(events: list[dict]) -> date | None:
    """Date of the first terminal event (the agency's, or WPR withdrawing)."""
    final = final_event(events)
    return final["event_on"] if final else None


def status(events: list[dict]) -> str:
    """'open', or the type of the request's final event."""
    final = final_event(events)
    return final["event_type"] if final else "open"


def agency_working_days(filed_on: date, events: list[dict], until: date) -> int:
    """Working days the agency held the request between filing and `until`,
    minus the days it was waiting on WPR."""
    events = _sorted(events)
    paused: set[date] = set()
    for start_type, end_types in PAUSES:
        for start in (e["event_on"] for e in events if e["event_type"] == start_type):
            resume = next((e["event_on"] for e in events
                           if e["event_type"] in end_types and e["event_on"] >= start), until)
            day = start
            while day < min(resume, until):
                paused.add(day)
                day += timedelta(days=1)
    return working_days(filed_on, until, frozenset(paused))


def held_working_days(filed_on: date, events: list[dict], as_of: date) -> int:
    """Working days held: to the first terminal event, or to `as_of` while open."""
    return agency_working_days(filed_on, events, clock_stop(events) or as_of)


def benchmark_result(complexity: str | None, filed_on: date, events: list[dict],
                     as_of: date) -> bool | None:
    """Did a request meet the 10-working-day benchmark?

    Measured to the agency's final response, not an interim batch. None means
    the benchmark can't judge it (yet):
    - complex or unclassified requests
    - a s. 19.356 subject notice sent within the first 10 working days
      (release is then barred by statute)
    - withdrawn, or still open, within the first 10 working days
    """
    if complexity != "simple":
        return None
    events = _sorted(events)
    benchmark = SIMPLE_REQUEST_BENCHMARK_WD
    notice = next((e["event_on"] for e in events if e["event_type"] == "subject_notice_sent"), None)
    if notice is not None:
        return False if agency_working_days(filed_on, events, notice) > benchmark else None
    stop = next((e for e in events if e["event_type"] in TERMINAL), None)
    held = agency_working_days(filed_on, events, stop["event_on"] if stop else as_of)
    if stop is None or stop["event_type"] == "withdrawn":
        return False if held > benchmark else None
    return held <= benchmark


def counts_in_median(complexity: str | None, filed_on: date, events: list[dict],
                     as_of: date) -> bool:
    """Whether a request's held days enter the simple-request median.

    Only simple requests the agency answered (not withdrawn or open) and that
    the benchmark judges, so the median sits beside the benchmark on the same
    footing: an early s. 19.356 notice, whose 12-day bar is the statute's
    delay and not the agency's, keeps a request out of both.
    """
    final = final_event(events)
    return (complexity == "simple" and final is not None
            and final["event_type"] in AGENCY_TERMINAL
            and benchmark_result(complexity, filed_on, events, as_of) is not None)


def denial_lacks_reasons(channel: str, response: dict | None) -> bool:
    """A denial of a written request that states no reason, s. 19.35(4)(b)."""
    return (response is not None and response["event_type"] in DENIALS
            and channel not in UNWRITTEN_CHANNELS and response["denial_reason"] is None)


def denial_lacks_remedy_notice(channel: str, response: dict | None) -> bool:
    """A denial of a written request without notice of mandamus or DA/AG review, s. 19.35(4)(b)."""
    return (response is not None and response["event_type"] in DENIALS
            and channel not in UNWRITTEN_CHANNELS and response["remedy_notice"] is False)


def location_fee_below_threshold(event: dict) -> bool:
    """An itemized quote charging a location fee smaller than s. 19.35(3)(c) allows."""
    return (event["event_type"] == "fee_quoted" and event["location_cents"] is not None
            and 0 < event["location_cents"] < LOCATION_FEE_THRESHOLD_CENTS)


def shows_rate(n: int) -> bool:
    """Whether a median or share built on n requests is published."""
    return n >= MIN_N_FOR_RATES


def published_values() -> dict:
    """The values the methodology page prints."""
    return {
        "SIMPLE_REQUEST_BENCHMARK_WD": SIMPLE_REQUEST_BENCHMARK_WD,
        "LOCATION_FEE_THRESHOLD_CENTS": LOCATION_FEE_THRESHOLD_CENTS,
        "MIN_N_FOR_RATES": MIN_N_FOR_RATES,
        "STATS_ONLY_EMBARGO_DAYS": STATS_ONLY_EMBARGO_DAYS,
        "HOLIDAYS": {str(year): sorted(d.isoformat() for d in days)
                     for year, days in sorted(HOLIDAYS.items())},
    }


def counts_in_metrics(visibility: str, filed_on: date, events: list[dict], as_of: date) -> bool:
    """Whether a request enters agency metrics today.

    stats_only requests wait until closed or STATS_ONLY_EMBARGO_DAYS old, so a
    nightly count can't reveal a fresh request tied to an unpublished story.
    """
    if visibility == "private":
        return False
    if visibility == "public":
        return True
    return clock_stop(events) is not None or (as_of - filed_on).days >= STATS_ONLY_EMBARGO_DAYS
