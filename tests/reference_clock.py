"""A second, deliberately plain implementation of the clock rules, for the fuzzer.

It reads CLAUDE.md's rules, not law.py, and shares no code with it. Above all it
is handed the events in the order they truly happened, so it never has to infer
a same-day order: that inference is what law.py does and what the fuzzer tests.
It is slow and obvious on purpose; never import it outside tests.
"""
from __future__ import annotations

from datetime import date, timedelta

BENCHMARK_WD = 10
AGENCY_FINAL = {"fulfilled", "partially_denied", "denied", "no_records"}
FINAL = AGENCY_FINAL | {"withdrawn"}
DENIALS = {"denied", "partially_denied"}
ASK_OF_ANSWER = {"clarification_sent": "clarification_requested",
                 "fee_paid": "fee_quoted", "fee_disputed": "fee_quoted"}
ASKS = set(ASK_OF_ANSWER.values())


def final_step(true_events: list[tuple[str, date]]) -> tuple[str, date] | None:
    return next((e for e in true_events if e[0] in FINAL), None)


def paused_days(true_events: list[tuple[str, date]], until: date) -> set[date]:
    """Each ask opens a pause of its kind unless one is open; the next answer of
    that kind closes it. A pause covers its opening day up to, not including,
    the closing day (or `until`)."""
    opened: dict[str, date] = {}
    days: set[date] = set()

    def cover(start: date, end: date) -> None:
        d = start
        while d < min(end, until):
            days.add(d)
            d += timedelta(days=1)

    for kind, day in true_events:
        if kind in ASKS and kind not in opened:
            opened[kind] = day
        elif kind in ASK_OF_ANSWER and ASK_OF_ANSWER[kind] in opened:
            cover(opened.pop(ASK_OF_ANSWER[kind]), day)
    for start in opened.values():
        cover(start, until)
    return days


def held_to(filed: date, true_events, until: date, holidays: set[date]) -> int:
    paused = paused_days(true_events, until)
    count, d = 0, filed
    while d < until:
        if d.weekday() < 5 and d not in holidays and d not in paused:
            count += 1
        d += timedelta(days=1)
    return count


def held(filed: date, true_events, as_of: date, holidays: set[date]) -> int:
    final = final_step(true_events)
    return held_to(filed, true_events, final[1] if final else as_of, holidays)


def status(true_events) -> str:
    final = final_step(true_events)
    if final is None:
        return "open"
    if any(kind == "denial_reversed" for kind, _ in true_events):
        return "denial_reversed"
    return final[0]


def benchmark(filed: date, true_events, as_of: date, holidays: set[date]) -> bool | None:
    """For a simple request (the fuzzer only makes simple ones)."""
    final = final_step(true_events)
    notice = next((day for kind, day in true_events if kind == "subject_notice_sent"
                   and (final is None or day <= final[1])), None)
    if notice is not None:
        return False if held_to(filed, true_events, notice, holidays) > BENCHMARK_WD else None
    days = held(filed, true_events, as_of, holidays)
    if final is None or final[0] == "withdrawn":
        return False if days > BENCHMARK_WD else None
    return days <= BENCHMARK_WD


def waiting_on_wpr(true_events) -> set[str]:
    if final_step(true_events) is not None:
        return set()
    open_asks: set[str] = set()
    for kind, _ in true_events:
        if kind in ASKS:
            open_asks.add(kind)
        elif kind in ASK_OF_ANSWER:
            open_asks.discard(ASK_OF_ANSWER[kind])
    return open_asks
