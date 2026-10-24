"""Keep the site's stress data (tests/worst_case.py) in step with the export: every
set must be writable by export.write_table with exactly the whitelisted fields."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export  # noqa: E402
from tests import worst_case  # noqa: E402


@pytest.mark.parametrize("build", [worst_case.worst, worst_case.empty, worst_case.one])
def test_stress_sets_match_the_export(build):
    data = build()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        export.write_table(out, "scorecard", data["scorecard"], export.SCORECARD_FIELDS)
        export.write_table(out, "requests", data["requests"], export.REQUEST_FIELDS)
        export.write_table(out, "request_events", data["request_events"], export.EVENT_FIELDS)
        assert json.loads((out / "scorecard.json").read_text("utf-8")) == data["scorecard"]
    assert tuple(data["meta"]) == export.META_FIELDS
    refs = {r["ref"] for r in data["requests"]}
    assert {e["ref"] for e in data["request_events"]} <= refs
    assert len(refs) == len(data["requests"])           # refs are unique, as the database makes them


def test_worst_case_is_actually_worst():
    data = worst_case.worst()
    assert len(data["scorecard"]) >= 40 and len({r["audit_round"] for r in data["requests"]} - {None}) == 6
    assert any(len(r["public_subject"]) > 120 for r in data["requests"])
    assert any(r["denial_reason"] and len(r["denial_reason"]) > 1500 for r in data["requests"])
