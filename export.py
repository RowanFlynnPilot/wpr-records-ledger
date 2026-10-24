"""Nightly export: database -> law.validate -> metrics -> site artifact.

Connects as the read-only role ledger_export (SUPABASE_DB_URL), validates
every request against law.py, computes the agency scorecard and writes the
site plus JSON and CSV into --out. The workflow deploys --out to GitHub Pages
as an Actions artifact; nothing here is ever committed.

Every rule comes from law.py. This file only decides which fields leave the
database, and the whitelists below are the whole of it.

Run: python export.py --out site [--as-of YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

import law

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
NEWSROOM_TZ = ZoneInfo("America/Chicago")
EXPORT_ROLE = "ledger_export"

# ── Whitelists: the only fields that reach an output file, in CSV column order ─
SCORECARD_FIELDS = (
    "agency", "requests", "open", "simple_n", "complex_n", "unclassified_n",
    "median_held_wd_simple", "median_n", "benchmark_met_share", "benchmark_n",
    "denials", "denials_without_reasons", "denials_missing_remedy_notice", "denials_reversed", "no_records",
    "location_fee_under_50", "subject_notice_n", "appeals",
)
REQUEST_FIELDS = (
    "ref", "agency", "filed_on", "public_subject", "audit_round", "channel", "status", "held_wd",
    "benchmark_result",
    "fees_quoted_cents", "fees_paid_cents", "denial_reason", "remedy_notice",
)
# Listed requests' timelines: no notes, links or itemizations.
EVENT_FIELDS = ("ref", "event_on", "event_type", "amount_cents")
META_FIELDS = ("generated_at", "as_of", "earliest_filed_on", "law")

# Private requests never leave the database, and the columns that must never
# be published (records_sought, filed_by, complexity_set_by, note,
# document_url, custodian_email) are never selected.
AGENCIES_SQL = "select id, name from agencies"
REQUESTS_SQL = """
    select id, agency_id, filed_on, channel::text as channel, public_subject,
           visibility::text as visibility, complexity::text as complexity, audit_round
    from requests
    where visibility <> 'private'
    order by id"""
EVENTS_SQL = """
    select e.request_id, e.event_type::text as event_type, e.event_on, e.amount_cents,
           e.location_cents, e.reproduction_cents, e.other_cents, e.denial_reason, e.remedy_notice
    from request_events e
    join requests r on r.id = e.request_id
    where r.visibility <> 'private'
    order by e.id"""


class ExportError(RuntimeError):
    pass


def fetch(conn: psycopg.Connection) -> list[dict]:
    """Every non-private request with its agency name and events, in one snapshot."""
    with conn.cursor(row_factory=dict_row) as cur:
        role = cur.execute("select current_user as role").fetchone()["role"]
        if role != EXPORT_ROLE:
            raise ExportError(f"connected as {role}; the export must connect as {EXPORT_ROLE}")
        agencies = {a["id"]: a["name"] for a in cur.execute(AGENCIES_SQL)}
        requests = {r["id"]: {**r, "agency": agencies[r["agency_id"]], "events": []}
                    for r in cur.execute(REQUESTS_SQL)}
        for e in cur.execute(EVENTS_SQL):
            requests[e.pop("request_id")]["events"].append(e)
    return list(requests.values())


def validate_all(requests: list[dict], as_of: date, name_requests: bool) -> None:
    """Raise one ExportError if law.validate rejects any request.

    Actions logs on a public repo are public, and a failing request may be a
    fresh, embargoed one: its id (which also counts private requests) or its
    rule ("denied follows an unanswered fee_quoted") would reveal it. So the
    error gives only a count, unless name_requests asks for ids and rules,
    which staff run locally with --name-requests.
    """
    errors = []
    for r in requests:
        try:
            law.validate(r["filed_on"], r["events"], as_of)
        except law.InvalidRequest as e:
            errors.append(f"request {r['id']}: {e}")
    if not errors:
        return
    if not name_requests:
        raise ExportError(f"{len(errors)} request(s) failed validation; nothing was exported. To see which, "
                          f"run locally: python export.py --dry-run --name-requests")
    raise ExportError(f"{len(errors)} request(s) failed validation; nothing was exported:\n  "
                      + "\n  ".join(errors))


def latest_quote_cents(events: list[dict]) -> int | None:
    """The most recent quote; a revised quote replaces the one before it."""
    quotes = sorted((e for e in events if e["event_type"] == "fee_quoted"), key=lambda e: e["event_on"])
    return quotes[-1]["amount_cents"] if quotes else None


def paid_cents(events: list[dict]) -> int | None:
    payments = [e["amount_cents"] for e in events if e["event_type"] == "fee_paid"]
    return sum(payments) if payments else None


def derive(r: dict, as_of: date) -> dict:
    """One request's measured values, all from law.py.

    A request the metrics don't count yet is measured not at all, so an agency
    needs a holiday list only once one of its requests is published.
    """
    events = r["events"]
    if not law.counts_in_metrics(r["visibility"], r["filed_on"], events, as_of):
        return {**r, "counted": False}
    agency, final = r["agency"], law.final_event(events)
    return {
        **r,
        "counted": True,
        "final": final,
        "status": law.status(events),
        "held_wd": law.held_working_days(agency, r["filed_on"], events, as_of),
        "benchmark_result": law.benchmark_result(agency, r["complexity"], r["filed_on"], events, as_of),
        "in_median": law.counts_in_median(agency, r["complexity"], r["filed_on"], events, as_of),
        "denial": final if final and final["event_type"] in law.DENIALS else None,
    }


def whitelisted(row: dict, fields: tuple[str, ...]) -> dict:
    if tuple(row) != fields:
        raise ExportError(f"output row fields {tuple(row)} differ from the whitelist {fields}")
    return row


def agency_row(agency: str, rows: list[dict]) -> dict:
    held = [d["held_wd"] for d in rows if d["in_median"]]
    judged = [d["benchmark_result"] for d in rows if d["benchmark_result"] is not None]
    return whitelisted({
        "agency": agency,
        "requests": len(rows),
        "open": sum(d["status"] == "open" for d in rows),
        "simple_n": sum(d["complexity"] == "simple" for d in rows),
        "complex_n": sum(d["complexity"] == "complex" for d in rows),
        "unclassified_n": sum(d["complexity"] is None for d in rows),
        "median_held_wd_simple": statistics.median(held) if law.shows_rate(len(held)) else None,
        "median_n": len(held),
        "benchmark_met_share": round(sum(judged) / len(judged), 3) if law.shows_rate(len(judged)) else None,
        "benchmark_n": len(judged),
        "denials": sum(d["denial"] is not None for d in rows),
        "denials_without_reasons": sum(law.denial_lacks_reasons(d["channel"], d["final"]) for d in rows),
        "denials_missing_remedy_notice": sum(law.denial_lacks_remedy_notice(d["channel"], d["final"])
                                             for d in rows),
        "denials_reversed": sum(d["status"] == law.DENIAL_REVERSED for d in rows),
        "no_records": sum(d["status"] == "no_records" for d in rows),
        "location_fee_under_50": sum(any(law.location_fee_below_threshold(e) for e in d["events"])
                                     for d in rows),
        "subject_notice_n": sum(any(e["event_type"] == "subject_notice_sent" for e in d["events"])
                                for d in rows),
        "appeals": sum(e["event_type"] in law.REMEDY_EVENTS for d in rows for e in d["events"]),
    }, SCORECARD_FIELDS)


def scorecard(derived: list[dict]) -> list[dict]:
    """One row per agency with a counted request, alphabetical: nothing is ranked."""
    by_agency: dict[str, list[dict]] = {}
    for d in derived:
        if d["counted"]:
            by_agency.setdefault(d["agency"], []).append(d)
    return [agency_row(agency, rows) for agency, rows in sorted(by_agency.items())]


def _listed(derived: list[dict]) -> list[dict]:
    """Public requests, newest first."""
    return sorted((d for d in derived if d["visibility"] == "public" and d["counted"]),
                  key=lambda d: (-d["filed_on"].toordinal(), d["agency"], d["public_subject"]))


def request_refs(listed: list[dict]) -> dict[int, str]:
    """A key joining each listed request to its timeline: filing date, agency, and
    its place among that agency's listed requests that day. Database ids are never
    published, since they count every request, private ones included."""
    refs: dict[int, str] = {}
    seen: dict[str, int] = {}
    for d in sorted(listed, key=lambda d: d["id"]):
        stem = f"{d['filed_on'].isoformat()}-{re.sub(r'[^a-z0-9]+', '-', d['agency'].lower()).strip('-')}"
        seen[stem] = seen.get(stem, 0) + 1
        refs[d["id"]] = f"{stem}-{seen[stem]}"
    return refs


def request_row(d: dict, ref: str) -> dict:
    denial = d["denial"]
    return whitelisted({
        "ref": ref,
        "agency": d["agency"],
        "filed_on": d["filed_on"].isoformat(),
        "public_subject": d["public_subject"],
        "audit_round": d["audit_round"],
        "channel": d["channel"],
        "status": d["status"],
        "held_wd": d["held_wd"],
        "benchmark_result": d["benchmark_result"],
        "fees_quoted_cents": latest_quote_cents(d["events"]),
        "fees_paid_cents": paid_cents(d["events"]),
        "denial_reason": denial["denial_reason"] if denial else None,
        "remedy_notice": denial["remedy_notice"] if denial else None,
    }, REQUEST_FIELDS)


def public_requests(derived: list[dict]) -> list[dict]:
    listed = _listed(derived)
    refs = request_refs(listed)
    return [request_row(d, refs[d["id"]]) for d in listed]


def public_events(derived: list[dict]) -> list[dict]:
    """Every event of the listed requests, in request-list order, each in law.py's order."""
    listed = _listed(derived)
    refs = request_refs(listed)
    return [whitelisted({"ref": refs[d["id"]], "event_on": e["event_on"].isoformat(),
                         "event_type": e["event_type"], "amount_cents": e["amount_cents"]}, EVENT_FIELDS)
            for d in listed for e in law.in_order(d["events"])]


def meta(derived: list[dict], as_of: date, generated_at: datetime) -> dict:
    counted = [d["filed_on"] for d in derived if d["counted"]]
    return whitelisted({
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "earliest_filed_on": min(counted).isoformat() if counted else None,
        "law": law.published_values(),
    }, META_FIELDS)


def _csv_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else v


def write_table(data_dir: Path, name: str, rows: list[dict], fields: tuple[str, ...]) -> None:
    (data_dir / f"{name}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    with open(data_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        writer.writerows([_csv_value(row[k]) for k in fields] for row in rows)


def write_site(out: Path, card: list[dict], listed: list[dict], events: list[dict], meta_doc: dict) -> None:
    """The site, law.py for the methodology page, and data/ with JSON and CSV."""
    if out.exists():
        raise ExportError(f"{out} already exists; the export writes a fresh directory")
    shutil.copytree(WEB, out)
    shutil.copy(ROOT / "law.py", out / "law.py")
    data_dir = out / "data"
    data_dir.mkdir()
    write_table(data_dir, "scorecard", card, SCORECARD_FIELDS)
    write_table(data_dir, "requests", listed, REQUEST_FIELDS)
    write_table(data_dir, "request_events", events, EVENT_FIELDS)
    (data_dir / "meta.json").write_text(json.dumps(meta_doc, indent=2) + "\n", encoding="utf-8")


def holiday_warning(card: list[dict], as_of: date) -> str | None:
    """From December on, name the published agencies with no list for next year:
    on Jan. 1 the export stops for each of them."""
    if as_of.month != 12:
        return None
    year = as_of.year + 1
    missing = [a["agency"] for a in card if not law.has_holiday_list(a["agency"], year)]
    if not missing:
        return None
    return f"No {year} holiday list for {', '.join(missing)}: set law.HOLIDAYS before Jan. 1 or the export stops"


def run(conninfo: str, out: Path, as_of: date, dry_run: bool, name_requests: bool = False) -> None:
    with psycopg.connect(conninfo) as conn:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        requests = fetch(conn)
    validate_all(requests, as_of, name_requests)
    derived = [derive(r, as_of) for r in requests]
    card = scorecard(derived)
    listed = public_requests(derived)
    meta_doc = meta(derived, as_of, datetime.now(timezone.utc))
    # Only published numbers are printed: a count of every request read would
    # reveal a fresh embargoed one in the public Actions log.
    print(f"as of {as_of}: {len(card)} agencies, {sum(a['requests'] for a in card)} counted requests, "
          f"{len(listed)} public")
    for a in card:
        print(f"  {a['agency']}: {a['requests']} requests, {a['open']} open")
    warning = holiday_warning(card, as_of)
    if warning:
        print(f"::warning::{warning}")   # an annotation on the Actions run
    if dry_run:
        print("dry run: nothing written")
        return
    write_site(out, card, listed, public_events(derived), meta_doc)
    print(f"wrote {out}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export the Records Ledger site and data.")
    parser.add_argument("--out", type=Path, default=ROOT / "site", help="directory to create (must not exist)")
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(NEWSROOM_TZ).date(),
                        help="day to measure open requests to (default: today in Wausau)")
    parser.add_argument("--dry-run", action="store_true", help="read, validate and compute; write nothing")
    parser.add_argument("--name-requests", action="store_true",
                        help="on a validation failure, print each request's id and rule (never in Actions)")
    args = parser.parse_args(argv)
    run(os.environ["SUPABASE_DB_URL"], args.out, args.as_of, args.dry_run, args.name_requests)


if __name__ == "__main__":
    main()
