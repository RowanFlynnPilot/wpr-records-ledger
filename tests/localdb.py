"""A throwaway local Postgres database set up like the Supabase project.

For tests and local previews only. Needs a local Postgres 16 server and an
admin connection string, for example from Docker:
  docker run -d --name wpr-records-ledger-pg -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:54330:5432 postgres:16
  $env:LEDGER_TEST_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54330/postgres"
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
EXPORT_PASSWORD = "local-test-only"   # the throwaway database's ledger_export password, never a real one
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _require_local(admin_url: str) -> None:
    host = conninfo_to_dict(admin_url).get("host")
    if host not in LOCAL_HOSTS:
        raise RuntimeError(f"refusing to create and drop databases on {host}: local Postgres only")


def _drop(admin: psycopg.Connection, name: str) -> None:
    admin.execute(f'drop database if exists "{name}" with (force)')
    admin.execute("drop role if exists ledger_export")


def run_sql_file(conn: psycopg.Connection, path: Path) -> list[str]:
    """Run a whole SQL file and return the NOTICE messages it raised."""
    notices: list[str] = []
    conn.add_notice_handler(lambda d: notices.append(d.message_primary))
    conn.execute(path.read_text(encoding="utf-8"))
    return notices


@contextmanager
def ledger_database(admin_url: str, name: str = "ledger_e2e"):
    """Yield (owner_url, export_url) for a fresh database with Supabase-style
    roles and supabase/schema.sql applied, and ledger_export able to log in.
    The database and the cluster-wide ledger_export role are dropped after."""
    _require_local(admin_url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        _drop(admin, name)
        admin.execute(f'create database "{name}"')
        owner_url = make_conninfo(admin_url, dbname=name)
        try:
            with psycopg.connect(owner_url, autocommit=True) as owner:
                run_sql_file(owner, ROOT / "tests" / "supabase_roles.sql")
                run_sql_file(owner, ROOT / "supabase" / "schema.sql")
                owner.execute(f"alter role ledger_export with login password '{EXPORT_PASSWORD}'")
            yield owner_url, make_conninfo(owner_url, user="ledger_export", password=EXPORT_PASSWORD)
        finally:
            _drop(admin, name)
