"""Tests for law.py. Run: python -m pytest tests"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import law  # noqa: E402

# Test-only holiday list: Thanksgiving and the day after, 2026.
law.HOLIDAYS[2026] = frozenset({date(2026, 11, 26), date(2026, 11, 27)})
LATER = date(2026, 12, 15)


def ev(event_type, m, d):
    return {"event_type": event_type, "event_on": date(2026, m, d)}


def test_working_days_basic():
    assert law.working_days(date(2026, 10, 19), date(2026, 10, 20)) == 1   # Mon -> Tue
    assert law.working_days(date(2026, 10, 16), date(2026, 10, 19)) == 1   # Fri -> Mon
    assert law.working_days(date(2026, 11, 25), date(2026, 11, 30)) == 1   # over Thanksgiving + Friday


def test_missing_holiday_year_fails_fast():
    with pytest.raises(KeyError):
        law.working_days(date(2027, 1, 4), date(2027, 1, 5))


def test_clarification_pause_is_not_counted():
    # Filed Mon 10/19; agency asks Tue 10/20; WPR answers Thu 10/22; fulfilled Mon 10/26.
    events = [ev("clarification_requested", 10, 20), ev("clarification_sent", 10, 22), ev("fulfilled", 10, 26)]
    assert law.held_working_days(date(2026, 10, 19), events, LATER) == 3   # Mon 19, Thu 22, Fri 23


def test_fee_pause_ends_at_payment_or_dispute():
    paid = [ev("fee_quoted", 10, 21), ev("fee_paid", 10, 28), ev("fulfilled", 10, 29)]
    assert law.held_working_days(date(2026, 10, 19), paid, LATER) == 3      # Mon 19, Tue 20, Wed 28
    disputed = [ev("fee_quoted", 10, 21), ev("fee_disputed", 10, 22), ev("fulfilled", 11, 13)]
    # Paused only Wed 10/21; counts 10/19-20 and 10/22-11/12
    assert law.held_working_days(date(2026, 10, 19), disputed, LATER) == 18


def test_interim_release_does_not_stop_the_clock():
    events = [ev("records_released", 10, 21), ev("fulfilled", 11, 30)]
    assert law.held_working_days(date(2026, 10, 19), events, LATER) > law.SIMPLE_REQUEST_BENCHMARK_WD
    assert law.benchmark_result("simple", date(2026, 10, 19), events, LATER) is False


def test_withdrawn_stops_the_clock():
    events = [ev("withdrawn", 10, 21)]
    assert law.held_working_days(date(2026, 10, 19), events, LATER) == 2
    assert law.benchmark_result("simple", date(2026, 10, 19), events, LATER) is None
    late = [ev("withdrawn", 11, 20)]                                        # withdrawn after a month of silence
    assert law.benchmark_result("simple", date(2026, 10, 19), late, LATER) is False


def test_benchmark_rules():
    filed = date(2026, 10, 1)
    assert law.benchmark_result("simple", filed, [ev("fulfilled", 10, 8)], LATER) is True
    assert law.benchmark_result("simple", filed, [ev("fulfilled", 10, 30)], LATER) is False
    assert law.benchmark_result("simple", filed, [ev("denied", 10, 8)], LATER) is True     # a denial is a response
    assert law.benchmark_result("complex", filed, [ev("fulfilled", 10, 30)], LATER) is None
    assert law.benchmark_result(None, filed, [ev("fulfilled", 10, 30)], LATER) is None
    # open: not judged inside the benchmark, a miss past it
    assert law.benchmark_result("simple", filed, [], as_of=date(2026, 10, 6)) is None
    assert law.benchmark_result("simple", filed, [], as_of=date(2026, 10, 30)) is False


def test_subject_notice():
    filed = date(2026, 10, 1)
    early = [ev("subject_notice_sent", 10, 5), ev("fulfilled", 10, 30)]
    assert law.benchmark_result("simple", filed, early, LATER) is None       # statute bars release; not judged
    late = [ev("subject_notice_sent", 10, 26), ev("fulfilled", 11, 13)]
    assert law.benchmark_result("simple", filed, late, LATER) is False       # already past 10 days at the notice


def test_validate():
    filed = date(2026, 10, 1)
    law.validate(filed, [ev("fee_quoted", 10, 2), ev("fee_paid", 10, 3), ev("fulfilled", 10, 5)])
    law.validate(filed, [ev("denied", 10, 5), ev("appealed_da", 10, 9)])
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [ev("fee_quoted", 10, 2), ev("fulfilled", 10, 5)])           # unanswered quote
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [ev("clarification_requested", 10, 2), ev("denied", 10, 5)])  # unanswered question
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [ev("withdrawn", 10, 2), ev("fulfilled", 10, 5)])
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [{"event_type": "acknowledged", "event_on": date(2026, 9, 30)}])


def test_stats_only_embargo():
    filed = date(2026, 10, 1)
    assert law.counts_in_metrics("stats_only", filed, [], as_of=date(2026, 10, 2)) is False
    assert law.counts_in_metrics("stats_only", filed, [ev("fulfilled", 10, 5)], as_of=date(2026, 10, 6)) is True
    assert law.counts_in_metrics("stats_only", filed, [], as_of=date(2026, 12, 30)) is True
    assert law.counts_in_metrics("public", filed, [], as_of=date(2026, 10, 2)) is True
    assert law.counts_in_metrics("private", filed, [ev("fulfilled", 10, 5)], as_of=LATER) is False
