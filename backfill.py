"""Load past requests and their replies from two CSVs into the database.

For the Phase 1 backfill, run locally, never in Actions. The files hold
records_sought and notes, so keep them in backfill/ (gitignored) or outside
the repo, never committed. Blank templates: backfill_templates/.

Every request must pass law.validate, and then every row is inserted inside one
transaction, so the schema's constraints and entry triggers check it too. Any
error anywhere rolls the whole batch back. --dry-run does all of that and then
rolls back. A request already in the database (same agency, filing date and
records_sought) is refused, so a rerun can't double-load.

Run: $env:LEDGER_WRITE_DB_URL = "<owner connection string>"
     python backfill.py backfill/requests.csv backfill/events.csv --dry-run
"""
from __future__ import annotations

import argparse
import csv
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

import law

NEWSROOM_TZ = ZoneInfo("America/Chicago")

REQUEST_COLUMNS = ("key", "agency", "filed_on", "channel", "filed_by", "records_sought", "public_subject",
                   "visibility", "complexity", "complexity_set_by", "audit_round")
EVENT_COLUMNS = ("request_key", "event_type", "event_on", "amount", "location", "reproduction", "other",
                 "denial_reason", "remedy_notice", "note", "document_url")
REQUIRED = {"key", "agency", "filed_on", "channel", "filed_by", "records_sought", "visibility",
            "request_key", "event_type", "event_on"}
DOLLAR_COLUMNS = {"amount": "amount_cents", "location": "location_cents",
                  "reproduction": "reproduction_cents", "other": "other_cents"}


class BackfillError(RuntimeError):
    pass


def _cents(text: str) -> int:
    try:
        cents = Decimal(text.replace("$", "").replace(",", "")) * 100
    except InvalidOperation:
        raise ValueError(f"{text!r} is not a dollar amount") from None
    if cents != cents.to_integral_value():
        raise ValueError(f"{text!r} has fractions of a cent")
    return int(cents)


def _yes_no(text: str) -> bool:
    if text.lower() not in ("yes", "no"):
        raise ValueError(f"{text!r} is not yes or no")
    return text.lower() == "yes"


def _cell(column: str, text: str):
    """One CSV cell as the value it stands for; blank is null."""
    text = text.strip()
    if not text:
        if column in REQUIRED:
            raise ValueError(f"{column} is required")
        return None
    if column in ("filed_on", "event_on"):
        return date.fromisoformat(text)
    if column in DOLLAR_COLUMNS:
        return _cents(text)
    if column == "remedy_notice":
        return _yes_no(text)
    return text


def read_rows(path: Path, columns: tuple[str, ...]) -> list[dict]:
    """Rows of a CSV whose header is exactly `columns`, parsed; one error lists every bad cell."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != columns:
            raise BackfillError(f"{path.name}: the header must be exactly {','.join(columns)}")
        rows, errors = [], []
        for line, raw in enumerate(reader, start=2):
            row = {}
            for column in columns:
                try:
                    row[column] = _cell(column, raw[column] or "")
                except ValueError as e:
                    errors.append(f"{path.name} line {line}, {column}: {e}")
            rows.append(row)
    if errors:
        raise BackfillError("\n".join(errors))
    return rows


def attach(requests: list[dict], events: list[dict]) -> list[dict]:
    """Each request with its events, by key."""
    by_key: dict[str, dict] = {}
    for r in requests:
        if r["key"] in by_key:
            raise BackfillError(f"request key {r['key']!r} appears twice")
        by_key[r["key"]] = {**r, "events": []}
    unknown = sorted({e["request_key"] for e in events} - set(by_key))
    if unknown:
        raise BackfillError(f"events name request keys not in the requests file: {', '.join(unknown)}")
    for e in events:
        by_key[e.pop("request_key")]["events"].append(
            {DOLLAR_COLUMNS.get(k, k): v for k, v in e.items()})
    return list(by_key.values())


def validate(requests: list[dict], as_of: date) -> None:
    """law.validate every request; one error lists every failure (a local run, so keys are fine)."""
    errors = []
    for r in requests:
        try:
            law.validate(r["filed_on"], r["events"], as_of)
        except law.InvalidRequest as e:
            errors.append(f"request {r['key']}: {e}")
    if errors:
        raise BackfillError("\n".join(errors))


def _insert(cur: psycopg.Cursor, r: dict, agency_ids: dict[str, int]) -> None:
    if r["agency"] not in agency_ids:
        raise BackfillError(f"agency {r['agency']!r} is not in the agencies table")
    agency_id = agency_ids[r["agency"]]
    if cur.execute("select 1 from requests where agency_id = %s and filed_on = %s and records_sought = %s",
                   (agency_id, r["filed_on"], r["records_sought"])).fetchone():
        raise BackfillError("already in the database")
    request_id = cur.execute(
        """insert into requests (agency_id, filed_on, channel, filed_by, records_sought, public_subject,
                                 visibility, complexity, complexity_set_by, audit_round)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (agency_id, r["filed_on"], r["channel"], r["filed_by"], r["records_sought"], r["public_subject"],
         r["visibility"], r["complexity"], r["complexity_set_by"], r["audit_round"])).fetchone()[0]
    for e in law.in_order(r["events"]):
        cur.execute(
            """insert into request_events (request_id, event_type, event_on, amount_cents, location_cents,
                                           reproduction_cents, other_cents, denial_reason, remedy_notice,
                                           note, document_url)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (request_id, e["event_type"], e["event_on"], e["amount_cents"], e["location_cents"],
             e["reproduction_cents"], e["other_cents"], e["denial_reason"], e["remedy_notice"],
             e["note"], e["document_url"]))


def load(conn: psycopg.Connection, requests: list[dict], dry_run: bool) -> None:
    """Insert every request in one transaction; any failure, or a dry run, rolls all of it back."""
    errors = []
    with conn.transaction() as tx:
        with conn.cursor() as cur:
            agency_ids = {name: id_ for id_, name in cur.execute("select id, name from agencies")}
            for r in requests:
                try:
                    with conn.transaction():   # a savepoint, so one bad row doesn't hide the next
                        _insert(cur, r, agency_ids)
                except (BackfillError, psycopg.Error) as e:
                    errors.append(f"request {r['key']}: {str(e).splitlines()[0]}")
        if errors or dry_run:
            raise psycopg.Rollback(tx)   # leaves the block without committing, and without an error
    if errors:
        raise BackfillError("\n".join(errors))


def run(conninfo: str, requests_csv: Path, events_csv: Path, as_of: date, dry_run: bool) -> None:
    requests = attach(read_rows(requests_csv, REQUEST_COLUMNS), read_rows(events_csv, EVENT_COLUMNS))
    validate(requests, as_of)
    with psycopg.connect(conninfo) as conn:
        load(conn, requests, dry_run)
    events = sum(len(r["events"]) for r in requests)
    verb = "checked; dry run, nothing inserted" if dry_run else "inserted"
    print(f"{len(requests)} requests and {events} events {verb}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill past requests and replies from two CSVs.")
    parser.add_argument("requests_csv", type=Path)
    parser.add_argument("events_csv", type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(NEWSROOM_TZ).date(),
                        help="no event may be dated after this day (default: today in Wausau)")
    parser.add_argument("--dry-run", action="store_true", help="check everything, insert nothing")
    args = parser.parse_args(argv)
    try:
        run(os.environ["LEDGER_WRITE_DB_URL"], args.requests_csv, args.events_csv, args.as_of, args.dry_run)
    except BackfillError as e:
        raise SystemExit(f"Nothing was inserted.\n{e}")


if __name__ == "__main__":
    main()
