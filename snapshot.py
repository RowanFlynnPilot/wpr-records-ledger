"""Name the frozen data release for the quarter that last ended.

The nightly workflow publishes the exported CSVs and JSON as a GitHub Release
with this tag the first time an export succeeds after a quarter ends, so a
figure cited in a story can be checked later. A release is not a commit, so
"data is never committed" holds; it is permanent public data, like the site.
It prints a name and writes nothing, so it has no --dry-run.

Run: python snapshot.py [--as-of YYYY-MM-DD]   ->  data-2026-Q3, or nothing outside the window
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from zoneinfo import ZoneInfo

NEWSROOM_TZ = ZoneInfo("America/Chicago")
# Freeze a quarter only this early in the next one, so a first run in November
# can't publish November's data labeled as the quarter that ended in September.
SNAPSHOT_WINDOW_DAYS = 14


def last_quarter(as_of: date) -> str:
    """The quarter before the one `as_of` falls in, as YYYY-Qn."""
    quarter = (as_of.month - 1) // 3 + 1
    return f"{as_of.year - 1}-Q4" if quarter == 1 else f"{as_of.year}-Q{quarter - 1}"


def quarter_start(as_of: date) -> date:
    return date(as_of.year, 3 * ((as_of.month - 1) // 3) + 1, 1)


def snapshot_tag(as_of: date) -> str | None:
    """The release to freeze today, or None outside the window after a quarter ends."""
    if (as_of - quarter_start(as_of)).days >= SNAPSHOT_WINDOW_DAYS:
        return None
    return f"data-{last_quarter(as_of)}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Print the tag of the last ended quarter's data release.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(NEWSROOM_TZ).date())
    args = parser.parse_args(argv)
    print(snapshot_tag(args.as_of) or "")


if __name__ == "__main__":
    main()
