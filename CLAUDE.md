# CLAUDE.md — The Records Ledger (`wpr-records-ledger`)

## What this is
A public record of how central Wisconsin agencies answer Wausau Pilot & Review's public records requests: how long they hold a request, what they charge, what they deny, and whether their denials follow the law. Every request WPR files is logged, and so is every response it gets.

It is pitched to funders together with the Closed Door Ledger as one transparency project. The link between them is a **quarterly audit**: each quarter, WPR files the same simple request with each records custodian the Closed Door Ledger covers. Those requests are logged here, which gives this ledger comparable numbers.

## Stack, repos and licensing
- **Database.** Supabase (Postgres) holds the log. Staff work in the Supabase Table Editor in v1.
- **Export.** `export.py` runs nightly in GitHub Actions (`cron: "37 10 * * *"`, 10:37 UTC).
  - It connects as the read-only role `ledger_export` through the Supabase **session pooler** (port 5432), using the `SUPABASE_DB_URL` secret. Supabase pooler user names take the form `ledger_export.<project-ref>`; confirm the role can connect before relying on it.
  - It validates the data, computes the metrics and deploys the site plus JSON and CSV to GitHub Pages **as an Actions artifact**. Data is never committed.
- **Licensing.** The repo is public. Code is MIT-licensed and published data is CC BY 4.0.

**Built and tested (`python -m pytest tests`, plus `supabase/tests.sql`):**
- `supabase/schema.sql`: tables, enums, check constraints, RLS, and the `ledger_export` role
- `supabase/tests.sql`: one transaction that rolls back, touching only rows marked `ZZTEST`
- `law.py`: every statutory value and clock rule. The methodology page prints it.
- `tests/test_law.py`

**To build:**
- `export.py`: DB → `law.validate` → metrics → site artifact
- `tests/test_export.py`
- `web/`
- `.github/workflows/export.yml`

## Data model (see `supabase/schema.sql`)
- **agencies:** one row per records custodian.
- **requests:** one row per request WPR files. The row itself is the filing.
  - `channel` is `email`, `portal`, `mail`, `hand_delivered` or `oral`. Only `oral` is an unwritten request.
  - `visibility`:
    - `public`: listed and counted. Requires a non-blank `public_subject`, which never names individuals.
    - `stats_only` (the default): counted once closed or 90 days old, never listed.
    - `private`: left out of the export.
  - `complexity` is `simple`, `complex`, or null until classified.
    - `complexity_set_by` must differ from `filed_by`, compared case- and space-insensitively.
    - The rubric: simple means a limited number of easily identifiable records, which is DOJ's wording.
- **request_events:** everything after filing.
  - **Agency events:** `acknowledged`, `clarification_requested`, `delay_notified`, `fee_quoted`, `subject_notice_sent` (s. 19.356), `records_released` (an interim batch), `fulfilled`, `partially_denied`, `denied`, `no_records`.
  - **WPR events:** `clarification_sent`, `fee_paid` (0 means waived), `fee_disputed`, `withdrawn`, and the remedies `appealed_da`, `appealed_ag`, `mandamus_filed`.
- **Check constraints:**
  - Fees require `amount_cents`. A quote's itemization is optional, all-or-none, and must add up to the total.
  - Denials require `remedy_notice`. `denial_reason` is nullable, and null means no reason was stated.
- **RLS.** anon and authenticated see and write nothing. `ledger_export` can only read.

**Tests.** `supabase/tests.sql` passed on Postgres 16 with Supabase-style roles and real rows present (Oct 23, 2026). It was mutation-checked: dropping the complexity rule, letting the export role insert, or removing its read policy each make it fail.

## The law (verified Oct 23, 2026)
- **Timing, s. 19.35(4)(a):** "As soon as practicable and without delay." There is no fixed deadline. DOJ's position is that about 10 working days is generally reasonable for a simple request.
- **Denials, s. 19.35(4)(b):**
  - A written request gets a written denial.
  - The denial must give specific reasons.
  - It must give notice that it can be reviewed by mandamus (s. 19.37(1)) or by application to the district attorney or the Attorney General.
- **Fees, s. 19.35(3):**
  - Only actual, necessary and direct costs may be charged.
  - A location fee is allowed only if the location cost alone is $50 or more.
  - Redaction generally can't be charged, except for certain law enforcement audio and video.
- **Record-subject notice, s. 19.356:** For certain employee records, the agency must notify the employee and may not release within 12 days of sending that notice. That was the 2011 text; confirm the current statute.
- **Fees after a lawsuit:** *Friends of Frame Park v. City of Waukesha* (Wis. 2022) allows attorney fees only when a court orders release.

Sources: [DOJ Compliance Guide (June 2025)](https://www.wisdoj.gov/Open%20Government/PRL_guide.pdf); [DOJ fee schedule (June 2025)](https://www.wisdoj.gov/Open%20Government/Public%20Records%20Request%20Fee%20Schedule%20June%202025.pdf); [s. 19.356 (2011)](https://law.justia.com/codes/wisconsin/2011/19/19.356.html); [TMJ4 on Frame Park](https://www.tmj4.com/news/local-news/wisconsin-courts-open-records-ruling-decried-as-gutting-law).

## Clock and benchmark rules (`law.py`)
- **Working days.** `working_days(start, end)` counts weekdays from the filing day up to, but not including, the end day. It skips `HOLIDAYS[year]`, a list the editor sets and the page prints.
  - It raises for a missing year, so **2024, 2025 and 2026 must be set before the backfill export.**
  - Uses the standard library only.
- **Held working days.** `held_working_days()` counts from filing to the **first terminal event** (`fulfilled`, `partially_denied`, `denied`, `no_records` or `withdrawn`), or to today while open.
  - It skips the days the agency was waiting on WPR: from `clarification_requested` to `clarification_sent`, and from `fee_quoted` to `fee_paid` or `fee_disputed`.
  - An interim `records_released` does not stop the clock.
- **Benchmark.** `benchmark_result()` returns true or false only for **simple** requests:
  - final response within 10 held working days: met
  - past 10 days, whether still open or withdrawn: missed
  - a s. 19.356 notice sent after day 10: missed
  - a s. 19.356 notice sent within 10 days: not judged, since release is barred by statute
  - withdrawn or still open inside 10 days: not judged
- **Validation.** `validate()` raises when:
  - an event is dated before filing
  - anything but a remedy follows `withdrawn`
  - an agency's final response follows an unanswered fee quote or clarification request (log `fee_paid`, `fee_disputed` or `clarification_sent` first)
- **Embargo.** `counts_in_metrics()` holds `stats_only` requests out until they are closed or 90 days old, so a nightly count can't reveal a fresh request tied to an unpublished story.

## Metrics (`export.py`)
**Per agency**, over requests where `counts_in_metrics()` is true:
- counts: `requests`, `open`, `simple_n`, `complex_n`, `unclassified_n`
- `median_held_wd_simple`: closed simple requests only
- `benchmark_met_share`: over the simple requests `benchmark_result` judges, with that n shown
- `denials` (`denied` plus `partially_denied`), `denials_without_reasons`, `denials_missing_remedy_notice` (non-`oral` requests only), `no_records`
- `location_fee_under_50`: itemized quotes only, where 0 < `location_cents` < 5000
- `subject_notice_n`, `appeals` (the remedy events)

**Small samples:** each median or share appears only when **its own** n (closed simple requests for the median, judged requests for the share) is at least `MIN_N_FOR_RATES` (5). n always shows. **Nothing is ranked in v1.**

**Outputs:**
- `scorecard.json` and `.csv`: by agency
- `requests.json` and `.csv`: public requests only, with whitelisted fields `agency`, `filed_on`, `public_subject`, `status`, `held_wd`, `benchmark_result`, `fees_quoted_cents`, `fees_paid_cents`, `denial_reason`, `remedy_notice`. Never export `records_sought`, `note`, `document_url`, `filed_by` or `complexity_set_by`.
- `meta.json`: generated time, earliest `filed_on`, the `law.py` values and the holiday list

## Phases
0. **Size the history, then stop and report.** Count WPR's 2024–26 requests per agency from the sent mail of the editor@ inbox, Shereen's and Rowan's. Search terms: "public records request", "open records", "19.35".
   - Report the counts to Rowan before building anything else.
   - If most agencies fall under 5 simple requests, lead with the quarterly audit and a narrative story, not a scorecard.
1. **Stand up the database.**
   - Create a Supabase project, apply `schema.sql`, run `tests.sql`, and give `ledger_export` a login password.
   - Set `law.HOLIDAYS` for 2024–26.
   - Backfill the counted requests.
2. **Quarterly audit.** File the Q3 2026 round from the Closed Door Ledger's `audit.py` list, one request per custodian with identical wording.
3. **Export** (`export.py` and `tests/test_export.py`). Test fixtures must cover:
   - every `law.py` rule
   - a denial with no reason
   - an `oral` request
   - an itemized location fee under $50
   - an agency below the floor
   - a `stats_only` request inside the embargo
4. **Site:** agency cards with n, a public request list, CSV downloads, and a methodology page that prints `law.py` and the holiday list.
5. **Staff intake form**, only if Table Editor logging becomes a bottleneck.

## Logging, for staff (v1)
- **When filing:** add one `requests` row.
  - Leave `visibility` as `stats_only` unless the story is published.
  - Someone other than the filer sets `complexity`.
- **When the agency replies:** add one `request_events` row dated the day the reply arrived.
  - For a fee quote: enter the total, and the split only if the agency gave one.
  - **Answering a quote or question:** always log your answer (`fee_paid`, `fee_paid` with 0 if waived, `fee_disputed`, or `clarification_sent`), or the export will stop.
  - For a denial: paste the stated reason, or leave it empty if none was given, and record whether the letter mentioned mandamus or review by the DA or AG.
- Keep letters and records in Drive and paste the link into `document_url`. It never leaves the database.

## Escalation
The Wisconsin Transparency Project (Tom Kamenick) represents news outlets in records suits; it won a settlement with fees for The Badger Project against WisDOT in Aug 2025 ([Badger Project](https://thebadgerproject.org/2025/08/14/wisdot-releases-records-pays-legal-fees-after-lawsuit-from-the-badger-project/)). The Wisconsin Freedom of Information Council is the statewide advocacy group. Log every appeal and suit as an event.

## Editorial policy
- The page reports WPR's own experience, labeled as such. It is not a statewide measure of an agency.
- Requests are listed only after their story runs, or when the editor decides listing is safe.
- No automated characterizations ("stonewalling", "illegal"). Each metric sits next to its benchmark, and the methodology page explains the benchmark's limits: DOJ's 10 days is guidance for simple requests, not a deadline.
- Before publishing a story built on an agency's numbers, the reporter asks that agency for comment.

## Design system and conventions
- **Design system:** Same as the other Ledgers. Teal `#3A867C`, cream `#F6F2E9`; Fraunces for display, Public Sans for body, JetBrains Mono for data.
- **Code:** Python 3.12. Scripts use `argparse` and support `--dry-run`. Use `psycopg`.
- **Locally:** Windows, PowerShell 5.1, `python -m pip`, commands chained with semicolons.
- **Principles:** One correct path, no fallbacks, fail fast. Single-responsibility functions.
