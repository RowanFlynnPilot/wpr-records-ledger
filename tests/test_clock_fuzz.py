"""Fuzz law.py's clock rules against tests/reference_clock.py.

Each example is a request's true history, built step by step the way it could
really unfold, then shuffled the way staff might log a day's events in any
order. law.py sees only the shuffled log and must infer the order; the
reference is handed the truth. Every measured value must agree.

More examples: $env:HYPOTHESIS_PROFILE = "deep"; python -m pytest tests/test_clock_fuzz.py
"""
import sys
from datetime import date, timedelta
from itertools import product
from pathlib import Path

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import law  # noqa: E402
from tests import reference_clock as ref  # noqa: E402

AGENCY = "Fuzz Agency"
HOLIDAYS = {
    2026: frozenset(date.fromisoformat(d) for d in ("2026-09-07", "2026-11-26", "2026-11-27",
                                                    "2026-12-24", "2026-12-25", "2026-12-31")),
    2027: frozenset(date.fromisoformat(d) for d in ("2027-01-01", "2027-04-02", "2027-05-31",
                                                    "2027-07-05", "2027-09-06")),
}
ALL_HOLIDAYS = set().union(*HOLIDAYS.values())
GAPS = (0, 0, 0, 0, 1, 1, 2, 3, 6, 11, 17)   # same-day events are where the ordering bugs live
REMEDIES = ("appealed_da", "appealed_ag", "mandamus_filed")


@pytest.fixture(autouse=True)
def fuzz_holidays(monkeypatch):
    monkeypatch.setattr(law, "HOLIDAYS", {AGENCY: HOLIDAYS})


def _event(kind, day):
    return {"event_type": kind, "event_on": day, "amount_cents": None, "location_cents": None,
            "reproduction_cents": None, "other_cents": None, "denial_reason": None, "remedy_notice": None}


def _next_options(open_asks, final, notice_sent, reversed_, bill_open, today):
    """What could happen next. `today`: this day's asks and answers so far, by
    kind, so they alternate (no second ask before an answer, no answer twice)."""
    def last(kind):
        return today[kind][-1] if today.get(kind) else None

    if final is None:
        options = ["acknowledged", "delay_notified", "records_released", "withdrawn"]
        if not notice_sent:
            options.append("subject_notice_sent")
        for ask in sorted(ref.ASKS):
            if last(ask) != "ask":
                options.append(ask)
        if "clarification_requested" in open_asks and last("clarification_requested") != "answer":
            options.append("clarification_sent")
        if "fee_quoted" in open_asks and last("fee_quoted") != "answer":
            options += ["fee_paid", "fee_disputed"]
        if not open_asks:                       # a final response only once nothing is unanswered
            options += sorted(ref.AGENCY_FINAL)
        return options
    if final == "withdrawn":
        return list(REMEDIES)
    options = [*REMEDIES, "records_released", "bill"]   # a bill: a fee quoted with or after the response
    if final in ref.DENIALS and not reversed_:
        options.append("denial_reversed")
    if last("fee_quoted") == "ask":
        options.remove("bill")
    if bill_open and last("fee_quoted") != "answer":
        options += ["fee_paid", "fee_disputed"]
    return options


def _stray_free(open_start, run):
    """Walk one kind's run for a day; the end state, or None if WPR answers nothing."""
    open_now = open_start
    for step in run:
        if step == "answer" and not open_now:
            return None
        open_now = step == "ask"
    return open_now


def _alternation(first, n_first, second, n_second):
    run = []
    for i in range(max(n_first, n_second)):
        run += [first] * (i < n_first) + [second] * (i < n_second)
    return run


def follows_the_convention(true):
    """Whether the true history reads each mixed day the way the convention would
    (see the comment above law._SAME_DAY_ORDER), found here by brute force over
    every combination of readings rather than law.py's way."""
    days = sorted({d for _, d in true})
    for ask in ref.ASKS:
        day_runs = []   # per day: (asks, answers, response day, dispute, what truly came first)
        for day in days:
            todays = [k for k, d in true if d == day]
            run = [k for k in todays if k == ask or ref.ASK_OF_ANSWER.get(k) == ask]
            day_runs.append((run.count(ask), len(run) - run.count(ask),
                             ask == "fee_quoted" and any(k in ref.AGENCY_FINAL for k in todays),
                             "fee_disputed" in run, run[0] if run else None))
        mixed = [i for i, (asks, answers, response_day, _, _) in enumerate(day_runs)
                 if asks and answers and not response_day]
        prefs = [(True, False) if day_runs[i][3] else (False, True) for i in mixed]

        def walk(choice):
            open_now = False
            for i, (asks, answers, response_day, _, _) in enumerate(day_runs):
                if response_day:
                    rest = answers - open_now
                    if rest < 0 or asks not in (rest, rest + 1):
                        return False
                    open_now = asks > rest
                    continue
                answer_first = choice.get(i, asks == 0 and answers > 0)
                run = (_alternation("answer", answers, "ask", asks) if answer_first
                       else _alternation("ask", asks, "answer", answers))
                open_now = _stray_free(open_now, run)
                if open_now is None:
                    return False
            return True

        preferred = next((dict(zip(mixed, combo)) for combo in product(*prefs)
                          if walk(dict(zip(mixed, combo)))), None)
        truth = {i: day_runs[i][4] != ask for i in mixed}
        if preferred != truth:
            return False
    return True


@st.composite
def histories(draw):
    """(filed_on, true events in order, the log as staff entered it, as_of)."""
    filed = date(2026, 9, 1) + timedelta(days=draw(st.integers(0, 110)))
    day, true = filed, []
    open_asks: set[str] = set()
    final = None
    notice_sent = reversed_ = bill_open = False
    today: dict[str, list[str]] = {}
    for _ in range(draw(st.integers(0, 12))):
        gap = draw(st.sampled_from(GAPS))
        if gap:
            day += timedelta(days=gap)
            today = {}
        kind = draw(st.sampled_from(_next_options(open_asks, final, notice_sent, reversed_, bill_open, today)))
        if kind == "bill":
            kind, bill_open = "fee_quoted", True
            today.setdefault("fee_quoted", []).append("ask")
        elif kind in ref.ASKS:
            open_asks.add(kind)
            today.setdefault(kind, []).append("ask")
        elif kind in ref.ASK_OF_ANSWER:
            if final is None:
                open_asks.discard(ref.ASK_OF_ANSWER[kind])
                today.setdefault(ref.ASK_OF_ANSWER[kind], []).append("answer")
            else:
                bill_open = False
                today.setdefault("fee_quoted", []).append("answer")
        elif kind in ref.FINAL:
            final = kind
        notice_sent = notice_sent or kind == "subject_notice_sent"
        reversed_ = reversed_ or kind == "denial_reversed"
        true.append((kind, day))
    assume(follows_the_convention(true))
    as_of = day + timedelta(days=draw(st.integers(0, 40)))
    logged = [_event(kind, d) for kind, d in draw(st.permutations(true))]
    return filed, true, logged, as_of


def pinned(true, as_of):
    """A hand-built history, logged in reverse so no same-day order is given away."""
    return true[0][1], true, [_event(kind, d) for kind, d in reversed(true)], as_of


D = date(2026, 10, 5)   # a Monday


# Each convention clause, pinned: random histories reach some of them only rarely.
@example(pinned([("fee_quoted", D), ("fee_disputed", D + timedelta(3)), ("fee_quoted", D + timedelta(3))],
                D + timedelta(20)))                                   # a dispute, then the revised quote, unpaid
@example(pinned([("fee_quoted", D), ("fee_quoted", D + timedelta(3)), ("fee_paid", D + timedelta(3))],
                D + timedelta(20)))                                   # a revised quote paid the same day
@example(pinned([("fee_quoted", D), ("fee_paid", D + timedelta(3)), ("fee_quoted", D + timedelta(3)),
                 ("fee_paid", D + timedelta(8))], D + timedelta(20)))  # paid, re-quoted, paid days later
@example(pinned([("clarification_requested", D), ("clarification_sent", D), ("clarification_requested", D)],
                D + timedelta(20)))                                   # asked, answered, asked again
@example(pinned([("fee_quoted", D), ("fee_paid", D + timedelta(3)), ("fulfilled", D + timedelta(3)),
                 ("fee_quoted", D + timedelta(3)), ("fee_paid", D + timedelta(3))], D + timedelta(20)))  # deposit, bill
@example(pinned([("clarification_requested", D), ("fee_quoted", D), ("clarification_requested", D + timedelta(1)),
                 ("fee_disputed", D + timedelta(1)), ("clarification_sent", D + timedelta(1))],
                D + timedelta(2)))   # a fee dispute the day a clarification is re-asked and answered (found by the deep run)
@given(histories())
def test_law_agrees_with_the_reference(history):
    filed, true, logged, as_of = history
    law.validate(filed, logged, as_of)
    assert law.held_working_days(AGENCY, filed, logged, as_of) == ref.held(filed, true, as_of, ALL_HOLIDAYS)
    assert law.status(logged) == ref.status(true)
    assert law.benchmark_result(AGENCY, "simple", filed, logged, as_of) == \
        ref.benchmark(filed, true, as_of, ALL_HOLIDAYS)
    assert law.waiting_on_wpr(logged) == ref.waiting_on_wpr(true)


# A chain of bills after the response: a deposit paid, the balance billed with the
# records, that bill paid the next day as another arrives, paid days later.
@example(pinned([("fee_quoted", D), ("fee_paid", D + timedelta(3)), ("fulfilled", D + timedelta(3)),
                 ("fee_quoted", D + timedelta(3)), ("fee_paid", D + timedelta(4)), ("fee_quoted", D + timedelta(4)),
                 ("fee_paid", D + timedelta(9))], D + timedelta(20)))
@given(histories())
def test_the_published_order_never_answers_before_asking(history):
    # The timeline prints law.in_order(): an answer must never come before its ask.
    _, _, logged, _ = history
    open_asks: set[str] = set()
    for e in law.in_order(logged):
        kind = e["event_type"]
        if kind in ref.ASKS:
            open_asks.add(kind)
        elif kind in ref.ASK_OF_ANSWER:
            assert ref.ASK_OF_ANSWER[kind] in open_asks, [x["event_type"] for x in law.in_order(logged)]
            open_asks.discard(ref.ASK_OF_ANSWER[kind])


@st.composite
def broken_histories(draw):
    """A valid history with one real mistake added; validate must refuse it."""
    filed = date(2026, 10, 1)
    mistake = draw(st.sampled_from(["unanswered", "after_withdrawn", "second_final", "before_filing"]))
    ask = draw(st.sampled_from(sorted(ref.ASKS)))
    final = draw(st.sampled_from(sorted(ref.AGENCY_FINAL)))
    gap = timedelta(days=draw(st.integers(1, 20)))
    if mistake == "unanswered":          # asked on an earlier day, never answered, then a final response
        true = [(ask, filed), (final, filed + gap)]
    elif mistake == "after_withdrawn":   # anything but a remedy on a later day than the withdrawal
        later = draw(st.sampled_from(["acknowledged", "records_released", ask, final]))
        true = [("withdrawn", filed), (later, filed + gap)]
    elif mistake == "second_final":
        true = [(final, filed), (draw(st.sampled_from(sorted(ref.FINAL))), filed + gap)]
    else:
        true = [("acknowledged", filed - gap)]
    logged = [_event(kind, d) for kind, d in draw(st.permutations(true))]
    return filed, logged, mistake


@given(broken_histories())
def test_validate_refuses_each_mistake(history):
    filed, logged, mistake = history
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, logged, date(2027, 6, 1))
