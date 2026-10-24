"""Back the log up to CSV, and restore it. Run locally, never in Actions.

The log is the newsroom's only copy of every request, and Supabase's free tier
keeps no point-in-time backups. `dump` reads every table, private requests and
never-published columns included, through the read-only ledger_export role and
writes a timestamped folder of CSVs with a manifest of row counts and checksums.
A backup holds everything the export never publishes: keep it on a private
drive, never in the repo (dump refuses a folder inside it) or anywhere public.

`restore` loads a backup into an empty database that has supabase/schema.sql
applied, in one transaction, then checks the row counts against the manifest.
It runs as the owner (LEDGER_WRITE_DB_URL) and sets the triggers aside while it
loads, since the rows already passed them once (and public_ref, which a trigger
assigns, must come back unchanged). --dry-run does everything, then rolls back.

Run: $env:SUPABASE_DB_URL = "<ledger_export URL>"; python backup.py dump --to D:\\ledger-backups
     $env:LEDGER_WRITE_DB_URL = "<owner URL of an empty database>"; python backup.py restore D:\\ledger-backups\\ledger-20261024-0530 --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent
TABLES = ("agencies", "requests", "request_events")   # in load order: each refers only to the ones before it
MANIFEST = "manifest.json"


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute("""select column_name from information_schema.columns
                           where table_schema = 'public' and table_name = %s order by ordinal_position""",
                        (table,)).fetchall()
    return [name for (name,) in rows]


def dump(conninfo: str, to: Path, dry_run: bool) -> Path | None:
    """Every table to CSV in a new timestamped folder under `to`, with a manifest."""
    target = to.resolve()
    if target == ROOT or ROOT in target.parents:
        raise BackupError(f"{to} is inside the repo; a backup holds unpublished data, so keep it elsewhere")
    with psycopg.connect(conninfo) as conn:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ   # one consistent snapshot
        counts = {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in TABLES}
        if dry_run:
            print(f"would back up {', '.join(f'{n} {t}' for t, n in counts.items())} to {target}")
            return None
        folder = target / f"ledger-{datetime.now():%Y%m%d-%H%M%S}"
        folder.mkdir(parents=True)
        files = {}
        for table in TABLES:
            columns = _columns(conn, table)
            path = folder / f"{table}.csv"
            with conn.cursor().copy(f"copy (select {', '.join(columns)} from {table} order by id) "
                                    f"to stdout with (format csv, header)") as copy, open(path, "wb") as f:
                for chunk in copy:
                    f.write(chunk)
            files[table] = {"rows": counts[table], "columns": columns, "sha256": _sha256(path)}
    manifest = {"made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "schema_sha256": _sha256(ROOT / "supabase" / "schema.sql"), "tables": files}
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"backed up {', '.join(f'{f['rows']} {t}' for t, f in files.items())} to {folder}")
    return folder


def _check(folder: Path) -> dict:
    """The manifest, once every file matches its checksum."""
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    for table in TABLES:
        if _sha256(folder / f"{table}.csv") != manifest["tables"][table]["sha256"]:
            raise BackupError(f"{table}.csv doesn't match its checksum; this backup is damaged")
    return manifest


def restore(conninfo: str, folder: Path, dry_run: bool) -> None:
    """Load a backup into an empty database with the schema applied; check the counts."""
    manifest = _check(folder)
    if manifest["schema_sha256"] != _sha256(ROOT / "supabase" / "schema.sql"):
        print("note: schema.sql has changed since this backup was made; columns are matched by name")
    with psycopg.connect(conninfo) as conn:
        with conn.transaction() as tx:
            for table in TABLES:
                if conn.execute(f"select exists (select 1 from {table})").fetchone()[0]:
                    raise BackupError(f"{table} isn't empty; restore only into a fresh database")
            for table in TABLES:
                conn.execute(f"alter table {table} disable trigger user")
            for table in TABLES:
                columns = manifest["tables"][table]["columns"]
                with conn.cursor().copy(f"copy {table} ({', '.join(columns)}) from stdin with (format csv, header)") \
                        as copy, open(folder / f"{table}.csv", "rb") as f:
                    while chunk := f.read(1 << 16):
                        copy.write(chunk)
                conn.execute(f"select setval(pg_get_serial_sequence('{table}', 'id'), "
                             f"coalesce((select max(id) from {table}), 0) + 1, false)")
            for table in TABLES:
                conn.execute(f"alter table {table} enable trigger user")
            for table in TABLES:
                got = conn.execute(f"select count(*) from {table}").fetchone()[0]
                if got != manifest["tables"][table]["rows"]:
                    raise BackupError(f"{table}: restored {got} rows, the backup has {manifest['tables'][table]['rows']}")
            counts = ", ".join(f"{manifest['tables'][t]['rows']} {t}" for t in TABLES)
            if dry_run:
                print(f"would restore {counts}; dry run, rolled back")
                raise psycopg.Rollback(tx)
    print(f"restored {counts} from {folder}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Back the log up to CSV, or restore a backup.")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("dump", help="back up every table (reads as ledger_export, SUPABASE_DB_URL)")
    d.add_argument("--to", type=Path, required=True, help="private folder outside the repo")
    d.add_argument("--dry-run", action="store_true", help="count the rows; write nothing")
    r = sub.add_parser("restore", help="load a backup into an empty database (as the owner, LEDGER_WRITE_DB_URL)")
    r.add_argument("folder", type=Path)
    r.add_argument("--dry-run", action="store_true", help="load and check, then roll back")
    args = parser.parse_args(argv)
    try:
        if args.command == "dump":
            dump(os.environ["SUPABASE_DB_URL"], args.to, args.dry_run)
        else:
            restore(os.environ["LEDGER_WRITE_DB_URL"], args.folder, args.dry_run)
    except BackupError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
