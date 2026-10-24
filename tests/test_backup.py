"""Tests for backup.py: a real round trip through local Postgres. Seed, dump as
ledger_export, restore into a fresh database, and check the tables and the
exported site come back identical. Skips without LEDGER_TEST_DB_URL."""
import os
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup  # noqa: E402
import export  # noqa: E402
import law  # noqa: E402
from tests import localdb, synthetic  # noqa: E402

ADMIN_URL = os.environ.get("LEDGER_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="LEDGER_TEST_DB_URL is not set (see tests/localdb.py)")


def tables(url):
    """Every row of every table, in id order."""
    with psycopg.connect(url) as conn:
        return {t: conn.execute(f"select * from {t} order by id").fetchall() for t in backup.TABLES}


def exported(export_url, out):
    export.run(export_url, out, synthetic.AS_OF, dry_run=False)
    return {p.name: p.read_bytes() for p in (out / "data").iterdir() if p.name != "meta.json"}


@pytest.fixture(autouse=True)
def test_holidays(monkeypatch):
    monkeypatch.setattr(law, "HOLIDAYS", synthetic.holiday_lists())


def test_a_backup_restores_exactly(tmp_path, capsys):
    store = tmp_path / "backups"
    with localdb.ledger_database(ADMIN_URL, "ledger_backup_source") as (owner_url, export_url):
        with psycopg.connect(owner_url) as owner:
            synthetic.seed(owner)
        before = tables(owner_url)
        site_before = exported(export_url, tmp_path / "site-before")
        assert backup.dump(export_url, store, dry_run=True) is None and not store.exists()
        folder = backup.dump(export_url, store, dry_run=False)
    assert f"backed up 4 agencies, {len(synthetic.REQUESTS)} requests" in capsys.readouterr().out

    with localdb.ledger_database(ADMIN_URL, "ledger_backup_target") as (owner_url, export_url):
        backup.restore(owner_url, folder, dry_run=True)
        assert all(rows == [] for rows in tables(owner_url).values())          # the dry run rolled back
        backup.restore(owner_url, folder, dry_run=False)
        assert tables(owner_url) == before                                      # every row and column, refs too
        assert exported(export_url, tmp_path / "site-after") == site_before     # the same site
        with pytest.raises(backup.BackupError, match="isn't empty"):
            backup.restore(owner_url, folder, dry_run=False)
        # The triggers are back on, and new rows number after the restored ones.
        with psycopg.connect(owner_url) as owner:
            new_id = owner.execute("""insert into requests (agency_id, filed_on, channel, filed_by, records_sought)
                                      values (1, '2026-10-01', 'email', 'SH', 'after restore') returning id""").fetchone()[0]
            assert new_id == len(before["requests"]) + 1
            with pytest.raises(psycopg.errors.CheckViolation):
                owner.execute("insert into request_events (request_id, event_type, event_on) values (%s, 'acknowledged', '2026-09-30')",
                              (new_id,))


def test_a_damaged_backup_is_refused(tmp_path):
    with localdb.ledger_database(ADMIN_URL, "ledger_backup_damaged") as (owner_url, export_url):
        with psycopg.connect(owner_url) as owner:
            synthetic.seed(owner)
        folder = backup.dump(export_url, tmp_path, dry_run=False)
        with open(folder / "requests.csv", "a", encoding="utf-8") as f:
            f.write("tampered\n")
        with pytest.raises(backup.BackupError, match="requests.csv doesn't match its checksum"):
            backup.restore(owner_url, folder, dry_run=True)


def test_a_backup_never_lands_in_the_repo():
    with pytest.raises(backup.BackupError, match="inside the repo"):
        backup.dump("postgresql://unused", backup.ROOT / "backups", dry_run=True)
