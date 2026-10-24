# Backfill templates

Copy both files into `backfill/` (gitignored) or anywhere outside the repo, fill them in, then check and load them with `backfill.py`. Never commit a filled-in file: it holds `records_sought` and notes.

**requests.csv**, one row per request:
- `key`: any label unique in the file, such as `W-2024-07`. It links the replies to the request and is not stored.
- `agency`: exactly as in the `agencies` table. Add new agencies there first.
- `filed_on`: `YYYY-MM-DD`.
- `channel`: `email`, `portal`, `mail`, `hand_delivered` or `oral`.
- `filed_by`, `records_sought`: required.
- `visibility`: `public`, `stats_only` or `private`, required. `public` needs a `public_subject` that names no individual.
- `complexity` (`simple` or `complex`) and `complexity_set_by`: both or neither, and not the filer.
- `audit_round`: `YYYY-Qn` for a quarterly audit request, else blank.

**events.csv**, one row per reply or action, dated the day it arrived or was sent:
- `request_key`: the request's `key`.
- `event_type`: as in CLAUDE.md, for example `acknowledged`, `fee_quoted`, `fee_paid`, `fulfilled`, `denied`.
- `amount`, `location`, `reproduction`, `other`: in dollars, such as `61.25`. A quote needs `amount`; the split is all three or none, and must add up. `fee_paid` with `0` means waived.
- `denial_reason`: as stated, or blank if none was given. `remedy_notice`: `yes` or `no`, required on a denial.
- `note`, `document_url`: optional; never published.

```
$env:LEDGER_WRITE_DB_URL = "<owner connection string>"
python backfill.py backfill/requests.csv backfill/events.csv --dry-run
python backfill.py backfill/requests.csv backfill/events.csv
```
The dry run checks everything, including the database's own rules, and inserts nothing. Any error inserts nothing.
