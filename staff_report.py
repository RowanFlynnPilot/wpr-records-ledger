"""The staff's private to-do list from the log. Run locally, never in Actions.

It names requests (id, agency, filer, what was sought), private and embargoed
ones included, so it refuses to run where the output would be public. It reads
through the read-only ledger_export connection and writes nothing, so it has no
--dry-run.

Run: $env:SUPABASE_DB_URL = "<ledger_export session pooler URL>"; python staff_report.py
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

import law

NEWSROOM_TZ = ZoneInfo("America/Chicago")
QUIET_DAYS = 30            # an open request with no logged event this long needs a nudge
EMBARGO_NOTICE_DAYS = 14   # warn this far ahead of an unlisted request entering the figures

REQUESTS_SQL = """
    select r.id, a.name as agency, r.filed_on, r.channel::text as channel, r.visibility::text as visibility,
           r.complexity::text as complexity, r.filed_by, r.records_sought
    from requests r join agencies a on a.id = r.agency_id
    order by r.filed_on, r.id"""
EVENTS_SQL = """
    select request_id, event_type::text as event_type, event_on, amount_cents, location_cents,
           reproduction_cents, other_cents, denial_reason, remedy_notice
    from request_events order by id"""

SECTIONS = (
    ("invalid", "Would stop the export (fix these first)"),
    ("no_holidays", "Will stop the export: counted (or about to be) at an agency with no holiday list for a "
                    "year it spans"),
    ("waiting", "Waiting on WPR: answer the agency"),
    ("late", "Open simple requests past the 10-working-day benchmark"),
    ("quiet", f"Open, with nothing logged in {QUIET_DAYS} days: follow up"),
    ("unclassified", "Not yet classified simple or complex (someone other than the filer)"),
    ("leaving_embargo", f"Unlisted requests entering the public figures within {EMBARGO_NOTICE_DAYS} days"),
)


def fetch(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        requests = {r["id"]: {**r, "events": []} for r in cur.execute(REQUESTS_SQL)}
        for e in cur.execute(EVENTS_SQL):
            requests[e.pop("request_id")]["events"].append(e)
    return list(requests.values())


def _label(r: dict) -> str:
    sought = r["records_sought"] if len(r["records_sought"]) <= 60 else r["records_sought"][:57] + "..."
    return f"#{r['id']}  {r['agency']}  filed {r['filed_on']} by {r['filed_by']}  {sought}"


def _measurable(r: dict, as_of: date) -> bool:
    return all(law.has_holiday_list(r["agency"], year) for year in range(r["filed_on"].year, as_of.year + 1))


def findings(requests: list[dict], as_of: date) -> dict[str, list[str]]:
    """Each section's lines. An invalid log is reported once and not measured."""
    found: dict[str, list[str]] = {key: [] for key, _ in SECTIONS}
    for r in requests:
        events = r["events"]
        try:
            law.validate(r["filed_on"], events, as_of)
        except law.InvalidRequest as e:
            found["invalid"].append(f"{_label(r)}\n      {e}")
            continue
        is_open = law.status(events) == "open"
        if r["complexity"] is None:
            found["unclassified"].append(_label(r))
        age = (as_of - r["filed_on"]).days
        entering = r["visibility"] == "stats_only" and \
            law.STATS_ONLY_EMBARGO_DAYS - EMBARGO_NOTICE_DAYS <= age < law.STATS_ONLY_EMBARGO_DAYS
        if entering:
            enters = r["filed_on"] + timedelta(days=law.STATS_ONLY_EMBARGO_DAYS)
            found["leaving_embargo"].append(f"{_label(r)}\n      enters the figures {enters}")
        # The export measures every counted request, open or closed, of any complexity.
        counted = law.counts_in_metrics(r["visibility"], r["filed_on"], events, as_of)
        measurable = _measurable(r, as_of)
        if (counted or entering) and not measurable:
            found["no_holidays"].append(f"{_label(r)}\n      {'counted now' if counted else 'enters the figures soon'}")
        if not is_open:
            continue
        waiting = law.waiting_on_wpr(events)
        if waiting:
            found["waiting"].append(f"{_label(r)}\n      unanswered: {', '.join(sorted(waiting))}")
        last = max([r["filed_on"]] + [e["event_on"] for e in events])
        if (as_of - last).days >= QUIET_DAYS:
            found["quiet"].append(f"{_label(r)}\n      last logged {last}")
        if r["complexity"] == "simple" and measurable:
            if law.benchmark_result(r["agency"], "simple", r["filed_on"], events, as_of) is False:
                held = law.held_working_days(r["agency"], r["filed_on"], events, as_of)
                found["late"].append(f"{_label(r)}\n      {held} working days held")
    return found


def render(found: dict[str, list[str]], as_of: date) -> str:
    lines = [f"Records Ledger staff report, as of {as_of}. Private: don't paste it anywhere public.", ""]
    for key, title in SECTIONS:
        items = found[key]
        lines.append(f"{title}: {len(items) or 'none'}")
        lines.extend(f"  {item}" for item in items)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Print the staff's private to-do list from the log.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(NEWSROOM_TZ).date(),
                        help="day to measure to (default: today in Wausau)")
    args = parser.parse_args(argv)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise SystemExit("staff_report.py names private and embargoed requests; never run it in Actions")
    with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as conn:
        conn.read_only = True
        requests = fetch(conn)
    print(render(findings(requests, args.as_of), args.as_of))


if __name__ == "__main__":
    main()
