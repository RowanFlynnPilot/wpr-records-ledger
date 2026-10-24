"""Tests for export.py on the synthetic data, without a database.
The end-to-end run against Postgres is in test_export_e2e.py."""
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export  # noqa: E402
import law  # noqa: E402
from tests import synthetic  # noqa: E402
from tests.synthetic import AS_OF, ev  # noqa: E402


@pytest.fixture(autouse=True)
def test_holidays(monkeypatch):
    monkeypatch.setattr(law, "HOLIDAYS", synthetic.holiday_lists("Floor Agency", "Fee Agency"))


def derived(requests=synthetic.REQUESTS, as_of=AS_OF):
    return [export.derive(r, as_of) for r in synthetic.as_fetched(requests)]


def test_scorecard_matches_hand_counts():
    assert export.scorecard(derived()) == synthetic.EXPECTED_SCORECARD


def test_public_request_list_matches_hand_counts():
    assert export.public_requests(derived()) == synthetic.EXPECTED_REQUESTS


def test_output_rows_carry_only_whitelisted_fields():
    for row in export.scorecard(derived()):
        assert tuple(row) == export.SCORECARD_FIELDS
    for row in export.public_requests(derived()):
        assert tuple(row) == export.REQUEST_FIELDS
    with pytest.raises(export.ExportError):
        export.whitelisted({"agency": "x", "records_sought": "y"}, ("agency",))


def test_meta():
    doc = export.meta(derived(), AS_OF, datetime(2026, 12, 15, 10, 37, tzinfo=timezone.utc))
    assert tuple(doc) == export.META_FIELDS
    assert doc["generated_at"] == "2026-12-15T10:37:00+00:00"
    assert doc["as_of"] == "2026-12-15"
    assert doc["earliest_filed_on"] == synthetic.EXPECTED_EARLIEST_FILED_ON
    assert doc["law"]["MIN_N_FOR_RATES"] == 5
    assert doc["law"]["HOLIDAYS"][synthetic.CITY]["2026"][4:6] == ["2026-11-26", "2026-11-27"]
    assert "2026-11-27" not in doc["law"]["HOLIDAYS"][synthetic.DISTRICT]["2026"]


def test_embargoed_and_private_requests_count_nowhere():
    published = json.dumps([export.scorecard(derived()), export.public_requests(derived())])
    assert "SENTINEL" not in published   # embargoed/private subjects and their agencies
    assert synthetic.VILLAGE not in published and synthetic.COUNTY not in published
    # The embargoed stats_only request R12 enters the count the day it closes.
    closed = [dict(r, events=r["events"] + [ev("fulfilled", 12, 14)]) if r["key"] == "R12" else r
              for r in synthetic.REQUESTS]
    city = export.scorecard(derived(closed))[0]
    assert city["requests"] == synthetic.EXPECTED_SCORECARD[0]["requests"] + 1


def test_embargo_lifts_at_90_days(monkeypatch):
    monkeypatch.setitem(law.HOLIDAYS[synthetic.CITY], 2027, frozenset())
    r12 = next(r for r in synthetic.REQUESTS if r["key"] == "R12")   # filed 12/7, open
    inside = export.scorecard(derived([r12], as_of=date(2027, 3, 6)))   # 89 days
    past = export.scorecard(derived([r12], as_of=date(2027, 3, 7)))     # 90 days
    assert inside == [] and past[0]["requests"] == 1


def simple_requests(n):
    return [synthetic.req(f"F{i}", "Floor Agency", date(2026, 10, 5), "email", "stats_only", "simple",
                          [ev("fulfilled", 10, 6 + i)]) for i in range(n)]


def test_small_sample_floor_applies_to_each_rate_separately():
    below = export.scorecard(derived(simple_requests(law.MIN_N_FOR_RATES - 1)))[0]
    assert below["median_held_wd_simple"] is None and below["benchmark_met_share"] is None
    assert below["median_n"] == below["benchmark_n"] == 4
    at = export.scorecard(derived(simple_requests(law.MIN_N_FOR_RATES)))[0]
    assert at["median_held_wd_simple"] == 3 and at["benchmark_met_share"] == 1.0   # held 1..5
    # Five judged but only four answered: the share shows, the median doesn't.
    four_closed = simple_requests(4) + [synthetic.req("F-open", "Floor Agency", date(2026, 10, 5),
                                                      "email", "public", "simple", [], "Open request")]
    row = export.scorecard(derived(four_closed))[0]
    assert row["benchmark_n"] == 5 and row["benchmark_met_share"] == 0.8
    assert row["median_n"] == 4 and row["median_held_wd_simple"] is None


@pytest.mark.parametrize("events, rule", [
    ([ev("fee_quoted", 10, 2, amount_cents=100), ev("fulfilled", 10, 5)], "unanswered fee_quoted"),
    ([ev("clarification_requested", 10, 2), ev("denied", 10, 5, remedy_notice=True)],
     "unanswered clarification_requested"),
    ([ev("withdrawn", 10, 2), ev("fulfilled", 10, 5)], "follows the request's final event"),
    ([ev("fulfilled", 10, 2), ev("denied", 10, 5, remedy_notice=True)], "follows the request's final event"),
    ([ev("acknowledged", 9, 30)], "before filing"),
    ([ev("fulfilled", 12, 16)], "dated after the export day"),
])
def test_invalid_event_log_stops_the_export(events, rule):
    bad = synthetic.req("BAD", synthetic.CITY, date(2026, 10, 1), "email", "stats_only", "simple", events)
    requests = synthetic.as_fetched(synthetic.REQUESTS + [bad])
    with pytest.raises(export.ExportError) as err:
        export.validate_all(requests, AS_OF)
    assert f"request {len(requests)}: " in str(err.value) and rule in str(err.value)
    assert synthetic.CITY not in str(err.value)   # public logs never name the agency...
    assert "2026-" not in str(err.value)          # ...or date an embargoed request


def test_valid_synthetic_data_passes_validation():
    export.validate_all(synthetic.as_fetched(), AS_OF)


def test_missing_holiday_year_stops_the_export(monkeypatch):
    monkeypatch.setattr(law, "HOLIDAYS", {agency: {2026: years[2026]}
                                          for agency, years in synthetic.TEST_HOLIDAYS.items()})
    with pytest.raises(KeyError, match="2027"):
        derived(as_of=date(2027, 1, 5))


def test_holiday_lists_are_needed_only_for_counted_requests():
    # The village has none, yet its private and embargoed requests export fine.
    assert synthetic.VILLAGE not in law.HOLIDAYS
    export.scorecard(derived())
    # The day one of its requests counts, the export stops until the editor sets one.
    closed = [dict(r, events=r["events"] + [ev("fulfilled", 12, 14)]) if r["key"] == "V2" else r
              for r in synthetic.REQUESTS]
    with pytest.raises(KeyError, match="No holiday list for Village of Sample"):
        derived(closed)


def test_location_fee_counts_requests_not_revised_quotes():
    requote = synthetic.req("Q", "Fee Agency", date(2026, 10, 5), "email", "public", "simple", [
        ev("fee_quoted", 10, 6, amount_cents=3000, location_cents=2500, reproduction_cents=500, other_cents=0),
        ev("fee_disputed", 10, 7),
        ev("fee_quoted", 10, 8, amount_cents=2700, location_cents=2500, reproduction_cents=200, other_cents=0),
        ev("fee_paid", 10, 9, amount_cents=2700), ev("fulfilled", 10, 12)], "Revised quote")
    assert export.scorecard(derived([requote]))[0]["location_fee_under_50"] == 1


def test_fees():
    events = [ev("fee_quoted", 9, 21, amount_cents=15000), ev("fee_disputed", 9, 22),
              ev("fee_quoted", 10, 5, amount_cents=9000), ev("fee_paid", 10, 6, amount_cents=4000),
              ev("fee_paid", 10, 9, amount_cents=5000)]
    assert export.latest_quote_cents(events) == 9000
    assert export.paid_cents(events) == 9000
    assert export.latest_quote_cents([]) is None and export.paid_cents([]) is None
    assert export.paid_cents([ev("fee_paid", 10, 6, amount_cents=0)]) == 0   # waived, not missing


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def as_csv_cell(v):
    return {True: "true", False: "false", None: ""}.get(v, str(v)) if not isinstance(v, (int, float)) \
        or isinstance(v, bool) else str(v)


def test_write_site(tmp_path):
    out = tmp_path / "site"
    card, listed = export.scorecard(derived()), export.public_requests(derived())
    doc = export.meta(derived(), AS_OF, datetime.now(timezone.utc))
    export.write_site(out, card, listed, doc)
    assert json.loads((out / "data" / "scorecard.json").read_text("utf-8")) == synthetic.EXPECTED_SCORECARD
    assert json.loads((out / "data" / "requests.json").read_text("utf-8")) == synthetic.EXPECTED_REQUESTS
    assert read_csv(out / "data" / "scorecard.csv") == [list(export.SCORECARD_FIELDS)] + [
        [as_csv_cell(row[k]) for k in export.SCORECARD_FIELDS] for row in synthetic.EXPECTED_SCORECARD]
    assert read_csv(out / "data" / "requests.csv") == [list(export.REQUEST_FIELDS)] + [
        [as_csv_cell(row[k]) for k in export.REQUEST_FIELDS] for row in synthetic.EXPECTED_REQUESTS]
    assert (out / "law.py").read_text("utf-8") == (export.ROOT / "law.py").read_text("utf-8")
    assert (out / "index.html").exists() and (out / "methodology.html").exists()
    with pytest.raises(export.ExportError):
        export.write_site(out, card, listed, doc)   # never writes over an existing directory
