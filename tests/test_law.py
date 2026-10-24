"""Tests for law.py. Run: python -m pytest tests"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import law  # noqa: E402

# Test-only holiday list: Thanksgiving and the day after, 2026.
A = "Test Agency"
law.HOLIDAYS[A] = {2026: frozenset({date(2026, 11, 26), date(2026, 11, 27)})}
LATER = date(2026, 12, 15)


def ev(event_type, m, d):
    return {"event_type": event_type, "event_on": date(2026, m, d)}


def test_working_days_basic():
    assert law.working_days(A, date(2026, 10, 19), date(2026, 10, 20)) == 1   # Mon -> Tue
    assert law.working_days(A, date(2026, 10, 16), date(2026, 10, 19)) == 1   # Fri -> Mon
    assert law.working_days(A, date(2026, 11, 25), date(2026, 11, 30)) == 1   # over Thanksgiving + Friday


def test_missing_holiday_year_fails_fast():
    with pytest.raises(KeyError, match="No 2027 holiday list for Test Agency"):
        law.working_days(A, date(2027, 1, 4), date(2027, 1, 5))
    with pytest.raises(KeyError, match="No holiday list for Unlisted Agency"):
        law.working_days("Unlisted Agency", date(2026, 10, 19), date(2026, 10, 20))


def test_each_agency_skips_its_own_holidays(monkeypatch):
    # Same request, same days: an agency open the day after Thanksgiving held it one day longer.
    monkeypatch.setitem(law.HOLIDAYS, "Open Friday", {2026: frozenset({date(2026, 11, 26)})})
    assert law.working_days(A, date(2026, 11, 23), date(2026, 11, 30)) == 3
    assert law.working_days("Open Friday", date(2026, 11, 23), date(2026, 11, 30)) == 4


def test_clarification_pause_is_not_counted():
    # Filed Mon 10/19; agency asks Tue 10/20; WPR answers Thu 10/22; fulfilled Mon 10/26.
    events = [ev("clarification_requested", 10, 20), ev("clarification_sent", 10, 22), ev("fulfilled", 10, 26)]
    assert law.held_working_days(A, date(2026, 10, 19), events, LATER) == 3   # Mon 19, Thu 22, Fri 23


def test_fee_pause_ends_at_payment_or_dispute():
    paid = [ev("fee_quoted", 10, 21), ev("fee_paid", 10, 28), ev("fulfilled", 10, 29)]
    assert law.held_working_days(A, date(2026, 10, 19), paid, LATER) == 3      # Mon 19, Tue 20, Wed 28
    disputed = [ev("fee_quoted", 10, 21), ev("fee_disputed", 10, 22), ev("fulfilled", 11, 13)]
    # Paused only Wed 10/21; counts 10/19-20 and 10/22-11/12
    assert law.held_working_days(A, date(2026, 10, 19), disputed, LATER) == 18


def test_interim_release_does_not_stop_the_clock():
    events = [ev("records_released", 10, 21), ev("fulfilled", 11, 30)]
    assert law.held_working_days(A, date(2026, 10, 19), events, LATER) > law.SIMPLE_REQUEST_BENCHMARK_WD
    assert law.benchmark_result(A, "simple", date(2026, 10, 19), events, LATER) is False


def test_withdrawn_stops_the_clock():
    events = [ev("withdrawn", 10, 21)]
    assert law.held_working_days(A, date(2026, 10, 19), events, LATER) == 2
    assert law.benchmark_result(A, "simple", date(2026, 10, 19), events, LATER) is None
    late = [ev("withdrawn", 11, 20)]                                        # withdrawn after a month of silence
    assert law.benchmark_result(A, "simple", date(2026, 10, 19), late, LATER) is False


def test_benchmark_rules():
    filed = date(2026, 10, 1)
    assert law.benchmark_result(A, "simple", filed, [ev("fulfilled", 10, 8)], LATER) is True
    assert law.benchmark_result(A, "simple", filed, [ev("fulfilled", 10, 30)], LATER) is False
    assert law.benchmark_result(A, "simple", filed, [ev("denied", 10, 8)], LATER) is True     # a denial is a response
    assert law.benchmark_result(A, "complex", filed, [ev("fulfilled", 10, 30)], LATER) is None
    assert law.benchmark_result(A, None, filed, [ev("fulfilled", 10, 30)], LATER) is None
    # open: not judged inside the benchmark, a miss past it
    assert law.benchmark_result(A, "simple", filed, [], as_of=date(2026, 10, 6)) is None
    assert law.benchmark_result(A, "simple", filed, [], as_of=date(2026, 10, 30)) is False


def test_subject_notice():
    filed = date(2026, 10, 1)
    early = [ev("subject_notice_sent", 10, 5), ev("fulfilled", 10, 30)]
    assert law.benchmark_result(A, "simple", filed, early, LATER) is None       # statute bars release; not judged
    late = [ev("subject_notice_sent", 10, 26), ev("fulfilled", 11, 13)]
    assert law.benchmark_result(A, "simple", filed, late, LATER) is False       # already past 10 days at the notice
    # A notice before a batch released after the final response doesn't bear on it.
    after_final = [ev("partially_denied", 10, 5), ev("subject_notice_sent", 11, 2), ev("records_released", 11, 20)]
    assert law.benchmark_result(A, "simple", filed, after_final, LATER) is True
    assert law.counts_in_median(A, "simple", filed, after_final, LATER) is True
    same_day = [ev("fulfilled", 10, 26), ev("subject_notice_sent", 10, 26)]
    assert law.benchmark_result(A, "simple", filed, same_day, LATER) is False   # notice sorts first: 17 days in


def test_validate():
    filed = date(2026, 10, 1)
    law.validate(filed, [ev("fee_quoted", 10, 2), ev("fee_paid", 10, 3), ev("fulfilled", 10, 5)], LATER)
    law.validate(filed, [ev("denied", 10, 5), ev("appealed_da", 10, 9)], LATER)
    law.validate(filed, [ev("fulfilled", 10, 5), ev("records_released", 10, 9)], LATER)
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [ev("fee_quoted", 10, 2), ev("fulfilled", 10, 5)], LATER)           # unanswered quote
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [ev("clarification_requested", 10, 2), ev("denied", 10, 5)], LATER)  # unanswered question
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [ev("withdrawn", 10, 2), ev("fulfilled", 10, 5)], LATER)
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [{"event_type": "acknowledged", "event_on": date(2026, 9, 30)}], LATER)
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [ev("partially_denied", 10, 5), ev("denied", 10, 20)], LATER)       # a second final response
    with pytest.raises(law.InvalidRequest):
        law.validate(filed, [ev("fulfilled", 12, 20)], LATER)                                   # dated after the export day
    with pytest.raises(law.InvalidRequest):
        law.validate(date(2026, 12, 16), [], LATER)                                             # filed after the export day


def test_each_pause_must_be_answered_even_when_both_are_open():
    filed = date(2026, 10, 1)
    clarification_left_open = [ev("clarification_requested", 10, 2), ev("fee_quoted", 10, 5),
                               ev("fee_paid", 10, 6), ev("fulfilled", 11, 30)]
    with pytest.raises(law.InvalidRequest, match="unanswered clarification_requested"):
        law.validate(filed, clarification_left_open, LATER)
    quote_left_open = [ev("fee_quoted", 10, 2), ev("clarification_requested", 10, 5),
                       ev("clarification_sent", 10, 6), ev("fulfilled", 11, 30)]
    with pytest.raises(law.InvalidRequest, match="unanswered fee_quoted"):
        law.validate(filed, quote_left_open, LATER)
    both_answered = [ev("clarification_requested", 10, 2), ev("fee_quoted", 10, 5),
                     ev("fee_paid", 10, 6), ev("clarification_sent", 10, 7), ev("fulfilled", 10, 9)]
    law.validate(filed, both_answered, LATER)
    assert law.held_working_days(A, filed, both_answered, LATER) == 3    # 10/1, 10/7, 10/8; paused 10/2-10/6


def test_answer_and_new_ask_on_the_same_day():
    # WPR answers and the agency asks again the same day: the answer closes the
    # old pause and the new ask opens another, whatever order they were logged in.
    filed = date(2026, 10, 1)
    requote = [ev("fee_quoted", 10, 5), ev("fee_quoted", 10, 2), ev("fee_disputed", 10, 5),
               ev("fee_paid", 10, 20), ev("fulfilled", 10, 21)]
    law.validate(filed, requote, LATER)
    assert law.held_working_days(A, filed, requote, LATER) == 2          # 10/1, 10/20
    asked_twice = [ev("clarification_requested", 10, 2), ev("clarification_requested", 10, 9),
                   ev("clarification_sent", 10, 9), ev("clarification_sent", 10, 16), ev("fulfilled", 10, 19)]
    law.validate(filed, asked_twice, LATER)
    assert law.held_working_days(A, filed, asked_twice, LATER) == 2      # 10/1, 10/16


def test_same_day_events_sort_in_logical_order():
    # Logged in the wrong order on the same day: the payment still answers the
    # quote before the release, and the appeal follows the denial.
    filed = date(2026, 10, 1)
    paid_same_day = [ev("fulfilled", 10, 5), ev("fee_paid", 10, 5), ev("fee_quoted", 10, 5)]
    law.validate(filed, paid_same_day, LATER)
    assert law.held_working_days(A, filed, paid_same_day, LATER) == 2
    law.validate(filed, [ev("appealed_da", 10, 5), ev("denied", 10, 5)], LATER)
    assert law.status([ev("appealed_da", 10, 5), ev("denied", 10, 5)]) == "denied"


def test_status_and_final_event():
    assert law.status([]) == "open"
    assert law.status([ev("records_released", 10, 5)]) == "open"
    assert law.status([ev("no_records", 10, 9), ev("acknowledged", 10, 2)]) == "no_records"
    assert law.final_event([ev("withdrawn", 10, 9)])["event_type"] == "withdrawn"


def test_counts_in_median():
    filed = date(2026, 10, 1)
    assert law.counts_in_median(A, "simple", filed, [ev("fulfilled", 10, 30)], LATER) is True
    assert law.counts_in_median(A, "simple", filed, [ev("withdrawn", 10, 30)], LATER) is False     # not a response
    assert law.counts_in_median(A, "simple", filed, [], LATER) is False                            # still open
    assert law.counts_in_median(A, "complex", filed, [ev("fulfilled", 10, 8)], LATER) is False
    early_notice = [ev("subject_notice_sent", 10, 5), ev("fulfilled", 10, 30)]
    assert law.counts_in_median(A, "simple", filed, early_notice, LATER) is False                  # not judged
    late_notice = [ev("subject_notice_sent", 10, 26), ev("fulfilled", 11, 13)]
    assert law.counts_in_median(A, "simple", filed, late_notice, LATER) is True


def denial(kind, reason, notice):
    return {"event_type": kind, "event_on": date(2026, 10, 5), "denial_reason": reason, "remedy_notice": notice}


def test_denial_rules_apply_to_written_requests_only():
    bare = denial("partially_denied", None, False)
    assert law.denial_lacks_reasons("email", bare) is True
    assert law.denial_lacks_remedy_notice("email", bare) is True
    assert law.denial_lacks_reasons("oral", bare) is False
    assert law.denial_lacks_remedy_notice("oral", bare) is False
    proper = denial("denied", "Ongoing investigation", True)
    assert law.denial_lacks_reasons("mail", proper) is False
    assert law.denial_lacks_remedy_notice("mail", proper) is False
    assert law.denial_lacks_reasons("email", None) is False
    assert law.denial_lacks_reasons("email", {"event_type": "fulfilled", "event_on": date(2026, 10, 5)}) is False


def quote(location):
    return {"event_type": "fee_quoted", "event_on": date(2026, 10, 5), "location_cents": location}


def test_location_fee_below_threshold():
    assert law.location_fee_below_threshold(quote(4999)) is True
    assert law.location_fee_below_threshold(quote(5000)) is False      # $50 or more may be charged
    assert law.location_fee_below_threshold(quote(0)) is False         # no location fee
    assert law.location_fee_below_threshold(quote(None)) is False      # not itemized


def test_small_sample_floor():
    assert law.shows_rate(law.MIN_N_FOR_RATES) is True
    assert law.shows_rate(law.MIN_N_FOR_RATES - 1) is False


def test_published_values():
    values = law.published_values()
    assert values["SIMPLE_REQUEST_BENCHMARK_WD"] == 10
    assert values["HOLIDAYS"][A] == {"2026": ["2026-11-26", "2026-11-27"]}


def test_stats_only_embargo():
    filed = date(2026, 10, 1)
    assert law.counts_in_metrics("stats_only", filed, [], as_of=date(2026, 10, 2)) is False
    # Closed in four days, still held back: a fast close would reveal a fresh request.
    assert law.counts_in_metrics("stats_only", filed, [ev("fulfilled", 10, 5)], as_of=date(2026, 10, 6)) is False
    assert law.counts_in_metrics("stats_only", filed, [], as_of=date(2026, 12, 29)) is False   # 89 days
    assert law.counts_in_metrics("stats_only", filed, [], as_of=date(2026, 12, 30)) is True    # 90 days
    assert law.counts_in_metrics("public", filed, [], as_of=date(2026, 10, 2)) is True
    assert law.counts_in_metrics("private", filed, [ev("fulfilled", 10, 5)], as_of=LATER) is False
