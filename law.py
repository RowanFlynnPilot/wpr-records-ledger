"""Statutory values and clock rules for the Records Ledger.

Everything the scorecard measures against lives here, and the methodology
page prints it. Change a rule here, nowhere else.
"""
from __future__ import annotations

import tomllib
from datetime import date, timedelta
from pathlib import Path

# ── Benchmarks ────────────────────────────────────────────────────────────────
# DOJ guidance, not a statutory deadline: ~10 working days is generally
# reasonable for a simple request (Public Records Law Compliance Guide, June 2025).
SIMPLE_REQUEST_BENCHMARK_WD = 10
LOCATION_FEE_THRESHOLD_CENTS = 5000   # s. 19.35(3)(c): location fees only if location cost >= $50
MIN_N_FOR_RATES = 5                   # below this n, show the count only, no median or share
STATS_ONLY_EMBARGO_DAYS = 90          # stats_only requests count once this old, closed or not

# Days each agency's offices are closed, keyed by the agency's name exactly as
# in the agencies table, then by year. The editor sets them in holidays.toml,
# and the methodology page prints them. Agencies close on different days (Good
# Friday, New Year's Eve, MLK Day), so each has its own list. working_days()
# refuses an agency or year missing from this map: every agency with a counted
# request needs 2024, 2025 and 2026 before the backfill export, and each new
# year before Jan. 1.
HOLIDAYS_FILE = Path(__file__).with_name("holidays.toml")


class HolidayFileError(ValueError):
    pass


def load_holidays(path: Path) -> dict[str, dict[int, frozenset[date]]]:
    """holidays.toml as {agency: {year: dates}}, refusing anything that can't be a closure:
    a weekend (it is skipped anyway, so it's a typo), a date under the wrong year, a repeat."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    holidays: dict[str, dict[int, frozenset[date]]] = {}
    errors = []
    for agency, years in raw.items():
        holidays[agency] = {}
        if not isinstance(years, dict):
            errors.append(f"{agency!r} is not an agency table (write it as [\"Agency name\"])")
            continue
        for year_key, days in years.items():
            if not (len(year_key) == 4 and year_key.isdigit()):
                errors.append(f"{agency}: {year_key!r} is not a year")
                continue
            year = int(year_key)
            if not isinstance(days, list) or not days:
                errors.append(f"{agency} {year}: list the year's dates, or leave the year out until they're set")
                continue
            for d in days:
                if type(d) is not date:
                    errors.append(f"{agency} {year}: {d!r} is not a date (write it as {year}-MM-DD)")
                elif d.year != year:
                    errors.append(f"{agency} {year}: {d} is listed under the wrong year")
                elif d.weekday() >= 5:
                    errors.append(f"{agency} {year}: {d} is a {d:%A}; weekends are skipped anyway")
            if len(set(days)) != len(days):
                errors.append(f"{agency} {year}: a date is listed twice")
            holidays[agency][year] = frozenset(d for d in days if type(d) is date)
    if errors:
        raise HolidayFileError(f"{path.name}:\n  " + "\n  ".join(errors))
    return holidays


HOLIDAYS: dict[str, dict[int, frozenset[date]]] = load_holidays(HOLIDAYS_FILE)

# ── Event classes ─────────────────────────────────────────────────────────────
AGENCY_TERMINAL = frozenset({"fulfilled", "partially_denied", "denied", "no_records"})
TERMINAL = AGENCY_TERMINAL | {"withdrawn"}
REMEDY_EVENTS = frozenset({"appealed_da", "appealed_ag", "mandamus_filed"})
DENIALS = frozenset({"denied", "partially_denied"})
# After a denial, everything withheld is released, on the agency's own review,
# an appeal or a court order. It doesn't move the clock: the denial was the
# final response. A partial reversal is a records_released batch.
DENIAL_REVERSED = "denial_reversed"
# s. 19.35(4)(b): a written request gets a written denial with specific reasons
# and notice of review by mandamus or the DA or AG. Only an oral request is unwritten.
UNWRITTEN_CHANNELS = frozenset({"oral"})
# The agency's clock stops while it waits on WPR: (pause starts, events that end it).
PAUSES = (
    ("clarification_requested", ("clarification_sent",)),
    ("fee_quoted", ("fee_paid", "fee_disputed")),
)
_PAUSE_STARTS = frozenset(start for start, _ in PAUSES)
_PAUSE_OF_END = {end: start for start, ends in PAUSES for end in ends}
# Events logged on the same day sort in the order they must have happened. A
# date has no time of day, so this is a convention, stated exactly and fuzzed
# against a reference (tests/test_clock_fuzz.py):
# - By default: the agency's events, a new ask among them; then WPR's answers;
#   then the final event; then remedies; then a reversal.
# - Asks and answers of one kind on one day alternate: the agency doesn't ask
#   the same thing twice before WPR replies, and WPR answers only an open ask.
# - Each day is read so that WPR never answers something that isn't open, that
#   day or on any later day. Where both readings of a day work (the agency asks
#   again on a day WPR answers an ask open since an earlier day), the agency's
#   ask comes first, unless WPR's answer is a fee dispute: a dispute prompts the
#   revised quote.
# - On the day of the agency's final response, one fee answer goes before the
#   response if a quote was open that morning (it must be answered first); every
#   other fee quote and answer that day goes after it, quote first, alternating:
#   a quote in the same letter as the final response is a bill for what came
#   with it. Every reading of such a day gives the same held days.
_BILLED_WITH_RESPONSE = 2.5
_SAME_DAY_ORDER = {
    **{kind: 1 for kind in _PAUSE_OF_END},
    **{kind: 2 for kind in TERMINAL},
    **{kind: 3 for kind in REMEDY_EVENTS},
    DENIAL_REVERSED: 4,
}


class InvalidRequest(ValueError):
    pass


def _holidays(agency: str, start: date, end: date) -> dict[int, frozenset[date]]:
    if agency not in HOLIDAYS:
        raise KeyError(f"No holiday list for {agency}: add it to holidays.toml")
    for year in range(start.year, end.year + 1):
        if year not in HOLIDAYS[agency]:
            raise KeyError(f"No {year} holiday list for {agency}: add it to holidays.toml")
    return HOLIDAYS[agency]


def has_holiday_list(agency: str, year: int) -> bool:
    return year in HOLIDAYS.get(agency, {})


def working_days(agency: str, start: date, end: date, excluded: frozenset[date] = frozenset()) -> int:
    """The agency's working days from `start` up to, not including, `end`."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    holidays = _holidays(agency, start, end)
    count, day = 0, start
    while day < end:
        if day.weekday() < 5 and day not in holidays[day.year] and day not in excluded:
            count += 1
        day += timedelta(days=1)
    return count


def _alternate(first: list[dict], second: list[dict]) -> list[dict]:
    run: list[dict] = []
    for i in range(max(len(first), len(second))):
        run += first[i:i + 1] + second[i:i + 1]
    return run


def _run_end(open_start: bool, asks: int, answers: int, answer_first: bool) -> bool | None:
    """Whether one kind's pause is open after a day's alternating run, or None if
    that reading would have WPR answer something that isn't open."""
    if answer_first:
        return answers == asks if open_start and answers in (asks, asks + 1) else None
    if not asks:
        return open_start if not answers else None
    return asks > answers if asks in (answers, answers + 1) else None


def _response_day_end(open_start: bool, quotes: int, answers: int) -> bool | None:
    """The fee run on the day of the final response: one answer first if a quote
    was open, then the rest after the response, quote first."""
    rest = answers - (1 if open_start else 0)
    if rest < 0 or quotes not in (rest, rest + 1):
        return None
    return quotes > rest


def _readings(pause: str, days: list[date], by_day: dict[date, list[dict]]) -> list[bool]:
    """For each day, whether that kind's run starts with WPR's answer: the first
    reading, in order of preference, that leaves every later day readable."""
    counts = []
    for day in days:
        todays = by_day[day]
        counts.append((sum(e["event_type"] == pause for e in todays),
                       sum(_PAUSE_OF_END.get(e["event_type"]) == pause for e in todays),
                       pause == "fee_quoted" and any(e["event_type"] in AGENCY_TERMINAL for e in todays),
                       pause == "fee_quoted" and any(e["event_type"] == "fee_disputed" for e in todays)))

    def options(i: int, open_start: bool) -> list[tuple[bool, bool | None]]:
        asks, answers, response_day, dispute = counts[i]
        if response_day:
            return [(False, _response_day_end(open_start, asks, answers))]
        prefer = (True, False) if dispute else (False, True)
        return [(first, _run_end(open_start, asks, answers, first)) for first in prefer]

    memo: dict[tuple[int, bool], bool] = {}

    def readable(i: int, open_start: bool) -> bool:
        if i == len(days):
            return True
        if (i, open_start) not in memo:
            memo[i, open_start] = any(end is not None and readable(i + 1, end) for _, end in options(i, open_start))
        return memo[i, open_start]

    readings, open_now = [], False
    for i in range(len(days)):
        ranked = options(i, open_now)
        first, end = next(((f, e) for f, e in ranked if e is not None and readable(i + 1, e)),
                          next(((f, e) for f, e in ranked if e is not None), (False, open_now)))
        readings.append(first)
        open_now = end if end is not None else open_now
    return readings


def in_order(events: list[dict]) -> list[dict]:
    """Events in the order they must have happened (see _SAME_DAY_ORDER).
    The clock rules and the published timelines both use this order."""
    by_day: dict[date, list[dict]] = {}
    for e in events:
        by_day.setdefault(e["event_on"], []).append(e)
    days = sorted(by_day)
    readings = {pause: _readings(pause, days, by_day) for pause in _PAUSE_STARTS}
    ordered: list[dict] = []
    open_pauses: set[str] = set()
    for i, day in enumerate(days):
        todays = by_day[day]
        position: dict[int, float] = {}
        response_day = any(e["event_type"] in AGENCY_TERMINAL for e in todays)
        if response_day:
            quotes = [e for e in todays if e["event_type"] == "fee_quoted"]
            fee_answers = [e for e in todays if _PAUSE_OF_END.get(e["event_type"]) == "fee_quoted"]
            before = fee_answers[:1] if "fee_quoted" in open_pauses else []
            for e in before:
                position[id(e)] = 1
            for j, e in enumerate(_alternate(quotes, fee_answers[len(before):])):
                position[id(e)] = _BILLED_WITH_RESPONSE + j / 100
        for pause in _PAUSE_STARTS:
            if response_day and pause == "fee_quoted":
                continue
            asks = [e for e in todays if e["event_type"] == pause]
            answers = [e for e in todays if _PAUSE_OF_END.get(e["event_type"]) == pause]
            if not (asks and answers):
                continue
            run = _alternate(answers, asks) if readings[pause][i] else _alternate(asks, answers)
            for j, e in enumerate(run):
                position[id(e)] = 1 + j / 100

        def rank(e: dict) -> float:
            return position.get(id(e), _SAME_DAY_ORDER.get(e["event_type"], 0))
        for e in sorted(todays, key=rank):
            _track_pause(open_pauses, e["event_type"])
            ordered.append(e)
    return ordered


def _track_pause(open_pauses: set[str], kind: str) -> None:
    """Update the set of open pauses for one event."""
    if kind in _PAUSE_STARTS:
        open_pauses.add(kind)
    elif kind in _PAUSE_OF_END:
        open_pauses.discard(_PAUSE_OF_END[kind])


def validate(filed_on: date, events: list[dict], as_of: date) -> None:
    """Raise InvalidRequest for an event log the clock rules can't measure.

    Messages name event types, never dates: the export prints them to a public log.
    """
    if filed_on > as_of:
        raise InvalidRequest("filed after the export day")
    withdrawn = reversed_ = False
    closed_by: str | None = None
    open_pauses: set[str] = set()
    for e in in_order(events):
        kind = e["event_type"]
        if e["event_on"] < filed_on:
            raise InvalidRequest(f"{kind} is dated before filing")
        if e["event_on"] > as_of:
            raise InvalidRequest(f"{kind} is dated after the export day")
        if closed_by and kind in TERMINAL:
            raise InvalidRequest(f"{kind} follows the request's final event, {closed_by}; "
                                 f"log a later batch as records_released")
        if withdrawn and kind not in REMEDY_EVENTS:
            raise InvalidRequest(f"{kind} comes after withdrawn")
        if kind == DENIAL_REVERSED and (closed_by not in DENIALS or reversed_):
            raise InvalidRequest(f"{kind} must follow a denial, once")
        if open_pauses and kind in AGENCY_TERMINAL:
            raise InvalidRequest(f"{kind} follows an unanswered {' and '.join(sorted(open_pauses))}; "
                                 f"log WPR's reply (or fee_paid with 0 for a waived fee) first")
        _track_pause(open_pauses, kind)
        withdrawn = withdrawn or kind == "withdrawn"
        reversed_ = reversed_ or kind == DENIAL_REVERSED
        closed_by = closed_by or (kind if kind in TERMINAL else None)


def waiting_on_wpr(events: list[dict]) -> set[str]:
    """The agency's asks WPR hasn't answered (clarification_requested, fee_quoted)
    on an open request. Once the request is closed the clock no longer waits."""
    if clock_stop(events) is not None:
        return set()
    open_pauses: set[str] = set()
    for e in in_order(events):
        _track_pause(open_pauses, e["event_type"])
    return open_pauses


def final_event(events: list[dict]) -> dict | None:
    """The first terminal event: the agency's final response, or WPR withdrawing."""
    return next((e for e in in_order(events) if e["event_type"] in TERMINAL), None)


def clock_stop(events: list[dict]) -> date | None:
    """Date of the first terminal event (the agency's, or WPR withdrawing)."""
    final = final_event(events)
    return final["event_on"] if final else None


def status(events: list[dict]) -> str:
    """'open', the type of the request's final event, or 'denial_reversed'
    once everything a denial withheld has been released."""
    final = final_event(events)
    if final is None:
        return "open"
    if any(e["event_type"] == DENIAL_REVERSED for e in events):
        return DENIAL_REVERSED
    return final["event_type"]


def agency_working_days(agency: str, filed_on: date, events: list[dict], until: date) -> int:
    """Working days the agency held the request between filing and `until`,
    minus the days it was waiting on WPR. Each answer ends the pause that was
    open when it arrived; a repeated ask while one is open extends that pause."""
    paused: set[date] = set()
    opened: dict[str, date] = {}

    def pause(start: date, end: date) -> None:
        day = start
        while day < min(end, until):
            paused.add(day)
            day += timedelta(days=1)

    for e in in_order(events):
        kind = e["event_type"]
        if kind in _PAUSE_STARTS:
            opened.setdefault(kind, e["event_on"])
        elif _PAUSE_OF_END.get(kind) in opened:
            pause(opened.pop(_PAUSE_OF_END[kind]), e["event_on"])
    for start in opened.values():
        pause(start, until)
    return working_days(agency, filed_on, until, frozenset(paused))


def held_working_days(agency: str, filed_on: date, events: list[dict], as_of: date) -> int:
    """Working days held: to the first terminal event, or to `as_of` while open."""
    return agency_working_days(agency, filed_on, events, clock_stop(events) or as_of)


def benchmark_result(agency: str, complexity: str | None, filed_on: date, events: list[dict],
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
    benchmark = SIMPLE_REQUEST_BENCHMARK_WD
    final = final_event(events)
    # A notice sent after the final response (before a later batch) doesn't bear on it.
    notice = next((e["event_on"] for e in in_order(events) if e["event_type"] == "subject_notice_sent"
                   and (final is None or e["event_on"] <= final["event_on"])), None)
    if notice is not None:
        return False if agency_working_days(agency, filed_on, events, notice) > benchmark else None
    held = agency_working_days(agency, filed_on, events, final["event_on"] if final else as_of)
    if final is None or final["event_type"] == "withdrawn":
        return False if held > benchmark else None
    return held <= benchmark


def counts_in_median(agency: str, complexity: str | None, filed_on: date, events: list[dict],
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
            and benchmark_result(agency, complexity, filed_on, events, as_of) is not None)


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
        "HOLIDAYS": {agency: {str(year): sorted(d.isoformat() for d in days)
                              for year, days in sorted(years.items())}
                     for agency, years in sorted(HOLIDAYS.items())},
    }


def counts_in_metrics(visibility: str, filed_on: date, events: list[dict], as_of: date) -> bool:
    """Whether a request enters agency metrics today.

    stats_only requests wait until STATS_ONLY_EMBARGO_DAYS old, even once
    closed, so a nightly count can't reveal a fresh request tied to an
    unpublished story: one filed Monday and denied Wednesday would otherwise
    show up Thursday as one more request and one more denial.
    """
    if visibility == "private":
        return False
    if visibility == "public":
        return True
    return (as_of - filed_on).days >= STATS_ONLY_EMBARGO_DAYS
