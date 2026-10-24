# CLAUDE.md — The Records Ledger (`wpr-records-ledger`)

## What this is
A public record of how central Wisconsin agencies answer Wausau Pilot & Review's public records requests: how long they hold a request, what they charge, what they deny, and whether their denials follow the law. Every request WPR files is logged, and so is every response it gets.

It is pitched to funders together with the Closed Door Ledger as one transparency project. The link between them is a **quarterly audit**: each quarter, WPR files the same simple request with each records custodian the Closed Door Ledger covers. Those requests are logged here, which gives this ledger comparable numbers.

## Stack, repos and licensing
- **Database.** Supabase (Postgres) holds the log. Staff work in the Supabase Table Editor in v1.
- **Export.** `export.py` runs nightly in GitHub Actions (`cron: "37 10 * * *"`, 10:37 UTC).
  - It connects as the read-only role `ledger_export` through the Supabase **session pooler** (port 5432), using the `SUPABASE_DB_URL` secret. Supabase pooler user names take the form `ledger_export.<project-ref>`; confirm the role can connect before relying on it.
  - It validates the data, computes the metrics and deploys the site plus JSON and CSV to GitHub Pages **as an Actions artifact**. Data is never committed.
  - It refuses to run unless `current_user` is `ledger_export`, reads in one read-only repeatable-read transaction, and never selects a private request or a never-exported column.
  - `--out` must not exist; the export writes a fresh directory. `--dry-run` reads, validates and computes but writes nothing. `--as-of` defaults to today in America/Chicago.
  - **Actions logs are public.** The export prints only published counts (a count of all requests read would reveal a fresh embargoed one). A validation failure prints only how many requests failed: an id (which also counts private requests) or a rule ("denied follows an unanswered fee_quoted") could reveal a fresh embargoed request. To see which, run `python export.py --dry-run --name-requests` locally with the `ledger_export` URL.
  - **Quarterly frozen copies.** After the export, a separate `snapshot` job (the only one with `contents: write`) publishes the exported CSVs and JSON as the GitHub Release `data-YYYY-Qn` for the quarter that last ended, if it doesn't exist yet and the export day is within the new quarter's first 14 days (`snapshot.py`), so a late first run can't label November's data as Q3: the first successful export in that window freezes it, so a figure cited in a story can be checked later. A release is not a commit; it is permanent public data, so correcting a request after its quarter is frozen means editing or deleting that release by hand.
  - GitHub disables a public repo's scheduled workflows after 60 days with no repository activity, and this repo commits no data. Watch for GitHub's warning email and re-enable the workflow, or push a commit, before then.
- **Backups** (`backup.py`). The log is the only copy, and Supabase's free tier keeps no point-in-time backups.
  - `python backup.py dump --to <private folder>` reads every table, private requests and never-published columns included, through the read-only `ledger_export` login (`SUPABASE_DB_URL`), in one snapshot, and writes `ledger-YYYYMMDD-HHMMSS/` with a CSV per table and a manifest of row counts and checksums. It refuses a folder inside the repo. A backup holds everything the export never publishes: keep it on a private drive.
  - `python backup.py restore <folder>` (as the owner, `LEDGER_WRITE_DB_URL`) loads a backup into an empty database with `schema.sql` applied, in one transaction: it checks every checksum, sets the triggers aside while loading (the rows passed them once, and `public_ref` must come back unchanged), resets the id sequences, and checks the row counts. `--dry-run` does it all and rolls back.
  - `tests/test_backup.py` round-trips the synthetic ledger: every row and column comes back, the exported site is byte-for-byte the same, the triggers are on again, and a tampered backup is refused.
  - Schedule it nightly on the newsroom machine (your call; it stores the `ledger_export` URL in your user environment):
    ```
    [Environment]::SetEnvironmentVariable("SUPABASE_DB_URL", "<ledger_export URL>", "User")
    $run = New-ScheduledTaskAction -Execute "<repo>\.venv\Scripts\python.exe" -Argument "backup.py dump --to D:\ledger-backups" -WorkingDirectory "<repo>"
    Register-ScheduledTask -TaskName "Records Ledger backup" -Action $run -Trigger (New-ScheduledTaskTrigger -Daily -At 6am)
    ```
    Nothing prunes old backups; each is small. Test a restore into a scratch project now and then.
- **Licensing.** The repo is public. Code is MIT-licensed and published data is CC BY 4.0.

**Built and tested (`python -m pytest tests`, plus `supabase/tests.sql`):**
- `supabase/schema.sql`: tables, enums, check constraints, RLS, and the `ledger_export` role
- `supabase/tests.sql`: one transaction that rolls back, touching only rows marked `ZZTEST`
- `law.py`: every statutory value and clock rule. The methodology page prints it.
- `export.py`: DB → `law.validate` → metrics → site artifact. It decides only which fields leave the database; every rule comes from `law.py`.
- `tests/test_law.py`, `tests/test_export.py` (no database), `tests/test_export_e2e.py` (local Postgres)
- `tests/test_clock_fuzz.py`, `tests/reference_clock.py` and `tests/conftest.py`: the Hypothesis fuzzer for the clock rules (see Fuzzing).
- `tests/test_privacy_fuzz.py`: fuzzes the privacy rules. Random ledgers (agencies; requests with random visibility, age, outcome, fees, denials, and stale refs on unlisted ones) mark everything that must never be published, and every output file, CSV included, must hold none of it: no unlisted request's subject or denial reason, no agency whose requests are all uncounted. Counts are checked against an independent 90-day rule, the list must be exactly the public requests, and timelines must join only to it. A second property runs the real export (SQL, `ledger_export`, files on disk) on 25 random ledgers in local Postgres, with `NEVEROUT` in every never-selected column. Mutation-checked: the old close-counts embargo, an off-by-one at 90 days, listing every counted request, a scorecard ignoring the embargo, and an earliest date over every request are each caught.
- `tests/worst_case.py` and `tests/test_worst_case.py`: the site's stress data (worst case: 44 real Marathon County custodians, an 86-character agency name, a URL subject, a 2,000-character pasted denial reason, typed markup, $12,345.67 fees, a 30-event timeline, six audit rounds, 271 listed requests; empty: launch night; one: every count at 1), kept in the export's exact shapes.
- `tests/synthetic.py`: the synthetic agencies, requests and events, with every expected value worked out by hand. Never-published columns carry `SENTINEL`, and the e2e test searches every output file for it.
- `web/`: static HTML/CSS/JS, no build step
- `backfill.py` and `tests/test_backfill.py`: loads past requests from two CSVs (templates and a column guide in `backfill_templates/`). Local only, as the owner (`LEDGER_WRITE_DB_URL`).
- `staff_report.py` and `tests/test_staff_report.py`: the staff's private to-do list (see Logging). Refuses to run in Actions.
- `backup.py` and `tests/test_backup.py`: CSV backups and a verified restore (see Backups).
- `snapshot.py` and `tests/test_snapshot.py`: names the frozen data release (`data-YYYY-Qn`) for the quarter that last ended.
- `.github/workflows/test.yml`: on every push, the whole suite on Python 3.12 with a Postgres 16 service (job `test`), and the site stress test in Chromium (job `site`, Playwright pinned in `requirements-dev.txt`; screenshots uploaded on a failure). Both first passed Oct 24, 2026.

**On branch `workflow`, not merged:** `.github/workflows/export.yml`. It runs the tests (the e2e test against a Postgres 16 service container), then the export, then deploys to Pages.

**Local database for tests.** Postgres 16 in Docker. `tests/localdb.py` creates a throwaway database with Supabase-style roles (`tests/supabase_roles.sql`: anon, authenticated, service_role, plus Supabase's default grants, so RLS is what's tested), applies `schema.sql`, and afterwards drops the database and the cluster-wide `ledger_export` role. It refuses any host but localhost.
```
docker run -d --name wpr-records-ledger-pg -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:54330:5432 postgres:16
$env:LEDGER_TEST_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54330/postgres"; python -m pytest tests
```
Use `127.0.0.1`, not `localhost`: on this machine `localhost` tries IPv6 first and psycopg stalls. Without `LEDGER_TEST_DB_URL` the e2e tests skip, and pytest prints why.

## Data model (see `supabase/schema.sql`)
- **agencies:** one row per records custodian.
- **requests:** one row per request WPR files. The row itself is the filing.
  - `channel` is `email`, `portal`, `mail`, `hand_delivered` or `oral`. Only `oral` is an unwritten request.
  - `visibility`:
    - `public`: listed and counted. Requires a non-blank `public_subject`, which never names individuals.
    - `stats_only` (the default): counted once 90 days old (closed or not), never listed.
    - `private`: left out of the export.
  - `public_ref` is set automatically the first time the request is public, and is permanent (see Outputs).
  - `audit_round` marks a quarterly audit request, as `YYYY-Qn` (e.g. `2026-Q3`); null for reporting requests. Its format is checked.
  - `complexity` is `simple`, `complex`, or null until classified.
    - `complexity_set_by` must differ from `filed_by`, compared case- and space-insensitively.
    - The rubric: simple means a limited number of easily identifiable records, which is DOJ's wording.
- **request_events:** everything after filing.
  - **Agency events:** `acknowledged`, `clarification_requested`, `delay_notified`, `fee_quoted`, `subject_notice_sent` (s. 19.356), `records_released` (an interim batch), `fulfilled`, `partially_denied`, `denied`, `no_records`, and `denial_reversed` (after a denial, everything withheld is released, on review, appeal or court order; a partial reversal is `records_released`).
  - **WPR events:** `clarification_sent`, `fee_paid` (0 means waived), `fee_disputed`, `withdrawn`, and the remedies `appealed_da`, `appealed_ag`, `mandamus_filed`.
- **Check constraints:**
  - Fees require `amount_cents`. A quote's itemization is optional, all-or-none, and must add up to the total.
  - Denials require `remedy_notice`. `denial_reason` is nullable, and null means no reason was stated. A blank `denial_reason` is rejected, so "no reason" is always null.
- **Two locks.** anon and authenticated hold no grants at all on the tables or their sequences (Supabase gives them every privilege by default and serves the tables through its REST API), and RLS would still hide every row from a role that had one. `ledger_export` can only read. `tests.sql` tests each lock on its own: the grants with `has_table_privilege` and real queries, RLS with a probe role that holds a grant but no policy. A table added later gets Supabase's default grants again, so revoke them there too.

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
- **Record-subject notice, s. 19.356:** For certain records (an employee's disciplinary-investigation records, records obtained by subpoena or search warrant, and records prepared by another employer about its employee), the agency must notify the record subject within 3 days of deciding to release. It may not release within 12 days of sending that notice, and not at all while the subject's suit to block release (allowed within 10 days of the notice) or any appeal is pending, s. 19.356(5). Verified Oct 23, 2026 against the current statute, last amended by 2011 Wis. Act 84.
  - That is why an early notice leaves a request **not judged** rather than judged after subtracting 12 days: the ledger logs no event for the subject's suit, so it can't tell a slow agency from one the law still bars.
- **Fees after a lawsuit:** *Friends of Frame Park v. City of Waukesha* (Wis. 2022) allows attorney fees only when a court orders release.

Sources: [DOJ Compliance Guide (June 2025)](https://www.wisdoj.gov/Open%20Government/PRL_guide.pdf); [DOJ fee schedule (June 2025)](https://www.wisdoj.gov/Open%20Government/Public%20Records%20Request%20Fee%20Schedule%20June%202025.pdf); [s. 19.356 (current)](https://docs.legis.wisconsin.gov/statutes/statutes/19/ii/356); [TMJ4 on Frame Park](https://www.tmj4.com/news/local-news/wisconsin-courts-open-records-ruling-decried-as-gutting-law).

## Clock and benchmark rules (`law.py`)
- **Working days.** `working_days(agency, start, end)` counts the agency's weekdays from the filing day up to, but not including, the end day. It skips `HOLIDAYS[agency][year]`, which `law.py` loads from **`holidays.toml`**, plain TOML dates the editor sets and the methodology page prints (the site also carries the file). Every clock function (`agency_working_days`, `held_working_days`, `benchmark_result`, `counts_in_median`) takes the agency first.
  - `load_holidays()` refuses a weekend date, a date under the wrong year, a repeated date, a non-date, an empty year (leave a year out until its dates are set: an empty list would silently count its holidays as working days and silence the December warning), and a year key that isn't four digits, and the export refuses an agency name not in the `agencies` table, so a typo stops the export instead of skipping the wrong day.
  - `HOLIDAYS` is keyed by the agency's name exactly as in the `agencies` table, then by year. The audit agencies disagree on 14+ dates in 2024–26 (Good Friday, New Year's Eve, MLK Day, Kronenwetter's 2025 swaps), so one shared list would miscount. Research and sources: `docs/holiday-research-2024-2026.md`.
  - It raises for a missing agency or year, so **every agency with a counted request needs 2024, 2025 and 2026 before the backfill export.**
  - Only counted requests are measured, so an agency needs a list once one of its requests is 90 days old or public, not before. That night's export stops until the list is set.
  - **Every agency in `HOLIDAYS` is published**, since the methodology page prints `law.py` in full. Adding an agency's list early can reveal a fresh request to it; for the audit custodians that's no risk.
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
- **Same-day order** (`law.in_order()`, also the published timeline's order). A date has no time of day, so this is a stated convention, fuzzed against an independent reference (see Fuzzing):
  - By default: the agency's events (a new ask among them), WPR's answers, the final event, remedies, a reversal.
  - Asks and answers of one kind on one day **alternate**: the agency doesn't ask the same thing twice before WPR replies, and WPR answers only an open ask.
  - Each day is read so that WPR never answers something that isn't open, that day or on any later day (`law._readings()` checks the days ahead). Where both readings of a day work (the agency asks again on a day WPR answers an ask open since an earlier day), the agency's ask comes first, unless WPR's answer is a `fee_disputed`: a dispute prompts the revised quote.
  - On the day of the agency's final response, one fee answer goes before the response if a quote was open that morning; every other fee quote and answer that day goes after it, quote first, alternating (a quote in the same letter as the response is a bill for what came with it). Every reading of such a day gives the same held days.
- **Fuzzing.** `tests/test_clock_fuzz.py` builds request histories step by step in their true order (asks, re-asks, answers, interim batches, notices, final responses, withdrawals, bills, remedies, reversals, many on the same day), shuffles each day the way staff might log it, and checks that `law.py` (seeing only the shuffle) agrees with `tests/reference_clock.py` (a plain second implementation handed the truth) on validity, held days, status, the benchmark and what's waiting on WPR, and that the timeline never shows an answer before its ask. A second property injects one real mistake per log and checks validation refuses it. Histories outside the convention above are discarded, since no date-only rule can recover them. Each convention clause is also pinned as an explicit example, since random histories reach some only rarely. CI runs 1,500 examples per property; `$env:HYPOTHESIS_PROFILE = "deep"` runs 50,000. The fuzzer was mutation-checked: dropping the dispute preference, the look-ahead, the response-day answer, alternation, the holiday skip or the pause count each makes it fail. It found three real ordering bugs (an ask, answer and second ask on one day; a chain of bills after the response; a fee dispute's preference leaking onto a clarification answered the same day), each now pinned as an example. Last deep run, Oct 24, 2026: 50,000 passing per property, about 1.2% of histories discarded as outside the convention.
- **Pairing.** Each answer ends the pause of its kind that was open when it arrived. A repeated ask while one is open extends that pause. Both kinds can be open at once, and each must be answered.
- **Validation.** `validate(filed_on, events, as_of)` raises when:
  - an event is dated before filing, or the request or any event is dated after the export day
  - anything but a remedy follows `withdrawn`
  - a second terminal event follows the first (a request has one final event; log a later batch as `records_released`)
  - an agency's final response follows an unanswered fee quote or clarification request, either kind (log `fee_paid`, `fee_disputed` or `clarification_sent` first)
  - Its messages name event types, never dates, because the export prints them to a public log.
- **Entry checks.** Triggers in `schema.sql` reject three of those mistakes as staff type them: an event dated before filing (or `filed_on` moved past logged events), a second final event, and anything but a remedy after `withdrawn`. They mirror `law.validate`, which stays the authority; `test_entry_checks_agree_with_law_validate` runs each case through both, and every trigger rule is mutation-checked in `tests.sql`.
- **s. 19.356 notice.** Only a notice dated on or before the final event bears on the benchmark; one sent before a later batch doesn't.
- **Waiting on WPR.** `waiting_on_wpr()`: the agency's unanswered asks on an open request (used by the staff report).
- **Final event and status.** `final_event()` is the first terminal event; `status()` is its type, or `open`, or `denial_reversed` once a reversal follows a denial.
- **Reversal.** `denial_reversed` must follow a denial, at most once, and sorts after remedies on the same day. It doesn't move the clock: the denial was the final response, and it still counts as a denial.
- **Median membership.** `counts_in_median()`: simple requests the agency answered (not withdrawn, not open) that `benchmark_result` judges. An early s. 19.356 notice keeps a request out of both the median and the share.
- **Denial checks.** `denial_lacks_reasons()` and `denial_lacks_remedy_notice()` apply to the final response of **written** requests only: s. 19.35(4)(b) requires reasons and the remedy notice for written requests, and an oral request's denial owes written reasons only on demand.
- **Location fee.** `location_fee_below_threshold()`: an itemized quote with 0 < `location_cents` < `LOCATION_FEE_THRESHOLD_CENTS`.
- **Floor.** `shows_rate(n)`: n >= `MIN_N_FOR_RATES`.
- **Holidays.** Each agency with a counted request needs its year in `holidays.toml` before the year's first export day: **set 2027 for every such agency before Jan. 1, 2027**, or the nightly export stops. From Dec. 1 the export puts a warning on each Actions run naming the published agencies with no list for the coming year.
- **Embargo.** `counts_in_metrics()` holds `stats_only` requests out until they are 90 days old, **even once closed**, so a nightly count can't reveal a fresh request tied to an unpublished story. (Until Oct. 2026 a close also let one in; a request filed Monday and denied Wednesday then showed up Thursday as +1 request and +1 denial.) Unlisted figures therefore lag by up to 90 days; public requests count at once.

## Metrics (`export.py`)
**Per agency**, over requests where `counts_in_metrics()` is true. An agency with no counted request is left out, so adding an agency for a fresh request reveals nothing. Rows are alphabetical.
- counts: `requests`, `open`, `simple_n`, `complex_n`, `unclassified_n`
- `median_held_wd_simple`: over requests where `counts_in_median()` is true, with that n as `median_n`
- `benchmark_met_share`: met / judged over the simple requests `benchmark_result` judges, rounded to 3 places, with that n as `benchmark_n`
- `denials`: requests whose final response is `denied` or `partially_denied`. `denials_without_reasons` and `denials_missing_remedy_notice`: of those, written requests only (`law.denial_lacks_*`). `denials_reversed`: of those, requests with a `denial_reversed` event. `no_records`: final response `no_records`.
- `location_fee_under_50`: requests with an itemized quote where `law.location_fee_below_threshold()` (a revised quote with the same fee counts once)
- `subject_notice_n`: requests with a `subject_notice_sent` event. `appeals`: remedy events.

**Small samples:** each median or share appears only when **its own** n (`median_n`: answered simple requests the benchmark judges; `benchmark_n`: judged requests) is at least `MIN_N_FOR_RATES` (5). n always shows. **Nothing is ranked in v1.**

**Outputs:**
The whitelists live in `export.py` (`SCORECARD_FIELDS`, `REQUEST_FIELDS`, `META_FIELDS`), and every row is checked against them before it is written.
- `scorecard.json` and `.csv`: by agency, with exactly these fields: `agency`, `requests`, `open`, `simple_n`, `complex_n`, `unclassified_n`, `median_held_wd_simple`, `median_n`, `benchmark_met_share`, `benchmark_n`, `denials`, `denials_without_reasons`, `denials_missing_remedy_notice`, `denials_reversed`, `no_records`, `location_fee_under_50`, `subject_notice_n`, `appeals`
- `requests.json` and `.csv`: public requests only, newest first, with whitelisted fields `ref`, `agency`, `filed_on`, `public_subject`, `audit_round`, `channel`, `status`, `held_wd`, `benchmark_result`, `fees_quoted_cents`, `fees_paid_cents`, `denial_reason`, `remedy_notice`. Never export `records_sought`, `note`, `document_url`, `filed_by`, `complexity_set_by` or `custodian_email`.
  - `channel` lets a reader see that an oral request's denial owed neither reasons nor the remedy notice.
  - `status`: `law.status()`: `open`, the final event's type, or `denial_reversed`. `fees_quoted_cents`: the latest quote (a revised quote replaces the earlier one), or null. `fees_paid_cents`: the sum of `fee_paid` amounts (0 = waived), or null. `denial_reason` and `remedy_notice`: from the final response when it is a denial, else null.
- `request_events.json` and `.csv`: every event of the listed requests, in `law.in_order()`, with whitelisted fields `ref`, `event_on`, `event_type`, `amount_cents` (never `note`, `document_url`, the fee itemization or denial fields, which the request row already carries).
  - `ref` (also the first field of `requests`) joins them. It is `requests.public_ref`, which the `assign_public_ref` trigger sets the first time a request is public: filing date, agency slug, and its place among that agency's refs that day. It never changes, even if the request is later unlisted or its `filed_on` is corrected, so a cited ref stays good; staff can't type or edit one. Numbering continues from the highest ref issued for that stem, the date is ISO whatever the session's DateStyle, and a request that has ever been public can't be deleted (set it `private` to take it down), so no number is ever reused. Agencies whose names slug alike share one sequence. (A gap, e.g. a `-2` with no `-1` listed, shows that a same-day request was once listed.) Database ids are never published, since they count every request, private ones included.
- `meta.json`: `generated_at`, `as_of` (the day open requests are measured to), `earliest_filed_on` (over counted requests only), and `law` (`law.published_values()`: `RULES_FINGERPRINT`, the four constants, and the holiday lists, by agency then year)
- **Rules fingerprint and changelog.** `law.fingerprint()` is the first 12 hex digits of the SHA-256 of `law.py`, line endings normalized so a Windows and a Linux checkout agree. It's published as `RULES_FINGERPRINT`. Whenever `law.py` changes, add an entry at the top of "Changes to the rules" in `web/methodology.html`: the date, the new fingerprint (`python -c "import law; print(law.fingerprint())"`) and what changed. `tests/test_methodology.py` fails until the current fingerprint is listed, so a rule can't change unannounced.
- **Data dictionary.** "The data files" on the methodology page describes every field of every download; `tests/test_methodology.py` checks it lists exactly the whitelisted fields, in order. A new field means a new row there.
- The site directory also carries `law.py` itself, which the methodology page prints.
- CSV: booleans `true`/`false`, null empty, UTF-8.

## Phases
0. **Size the history, then stop and report.** Count WPR's 2024–26 requests per agency from the sent mail of the editor@ inbox, Shereen's and Rowan's. Search terms: "public records request", "open records", "19.35".
   - Report the counts to Rowan before building anything else.
   - If most agencies fall under 5 simple requests, lead with the quarterly audit and a narrative story, not a scorecard.
1. **Stand up the database.**
   - Create a Supabase project, apply `schema.sql`, run `tests.sql`, and give `ledger_export` a login password.
   - Fill `holidays.toml` for 2024–26, one table per agency.
   - Backfill the counted requests with `backfill.py`:
     - Fill copies of `backfill_templates/*.csv` in `backfill/` (gitignored; the files hold `records_sought`), add any new agency in the Table Editor first, then run `--dry-run`, then the real load.
     - Every request must pass `law.validate`, and the rows go in inside one transaction, so the schema's constraints and triggers check them too. Any error anywhere inserts nothing; a request already in the database (same agency, `filed_on` and `records_sought`) is refused, so a rerun can't double-load.
     - Amounts are in dollars (commas only as thousands separators) and `remedy_notice` is `yes`/`no`; the file's `key` links replies to requests and isn't stored. A row with more or fewer cells than the header (usually an unquoted comma) is refused, as is the same request twice in one file.
2. **Quarterly audit.** File the Q3 2026 round from the Closed Door Ledger's `audit.py` list, one request per custodian with identical wording.
   - Log each with `audit_round` set. The site's audit section shows a round's **public** requests side by side, as counts (a round is too small for shares), so set the round's requests to `public` when it is published.
   - Once two or more rounds are published, the audit section adds a round-over-round table: each agency's working days held and benchmark result per round, with a dash where it wasn't in a round. It's built in the browser from `requests.json`, so it publishes nothing new.
3. **Export** (`export.py` and `tests/test_export.py`). Test fixtures must cover:
   - every `law.py` rule
   - a denial with no reason
   - an `oral` request
   - an itemized location fee under $50
   - an agency below the floor
   - a `stats_only` request inside the embargo
4. **Site:** agency cards with n, a public request list, CSV downloads, and a methodology page that prints `law.py` and each agency's holiday list.
   - Both pages show a banner when `meta.json` is more than 2 days old: the nightly export has stopped (a failed run, or GitHub disabling the schedule).
   - **Embed:** `embed.html?agency=<name>` shows one agency card for an iframe in an article (about 900px tall at phone width) and posts its height to the parent. Card markup lives in `web/cards.js`, shared with the home page.
   - **Sharing:** OG and Twitter tags and a schema.org `Dataset` block assume the Pages URL `https://rowanflynnpilot.github.io/wpr-records-ledger/`; change them if the site moves to a custom domain. `web/og-image.png` is rendered by `scripts/og_card.py` (Playwright, a local tool only) from `scripts/og_card.html`; rerun it when the branding changes and commit the PNG.
   - The home page's lead is one block in `web/leads/` (`scorecard.html` or `audit.html`), chosen by `LEAD` in `web/config.js`. Phase 0 decides it.
5. **Staff intake form**, only if Table Editor logging becomes a bottleneck.

## Logging, for staff (v1)
**`docs/staff-guide.md`** is the plain-language version for reporters: every column and event type, what the Table Editor refuses, fixing mistakes, and the weekly report. Keep it in step with this section and `schema.sql`.
- **When filing:** add one `requests` row.
  - Leave `visibility` as `stats_only` unless the story is published.
  - Someone other than the filer sets `complexity`.
  - For a quarterly audit request, set `audit_round` (e.g. `2026-Q3`). Its `public_subject` is the audit's wording.
- **When the agency replies:** add one `request_events` row dated the day the reply arrived.
  - The Table Editor refuses an event dated before filing, a second final event, or anything after a withdrawal but an appeal. Its message says why.
  - For a fee quote: enter the total, and the split only if the agency gave one.
  - **Answering a quote or question:** always log your answer (`fee_paid`, `fee_paid` with 0 if waived, `fee_disputed`, or `clarification_sent`), or the export will stop.
  - For a denial: paste the stated reason, or leave it empty if none was given, and record whether the letter mentioned mandamus or review by the DA or AG. **For a public request the reason is published**, so like `public_subject` it must not name individuals.
  - A request has one final response. Records that arrive after it are `records_released`.
  - If, after a denial, the agency releases everything it withheld (on its own, after an appeal, or by court order), log `denial_reversed` on the day it arrived.
- Keep letters and records in Drive and paste the link into `document_url`. It never leaves the database.
- **Weekly:** run `python staff_report.py` locally with the `ledger_export` URL. It lists, with ids, agencies and filers: logs that would stop the export, requests that will stop it for want of a holiday list (every counted request is measured, open or closed, of any complexity, so this covers those and unlisted ones entering the figures within 14 days), asks waiting on WPR, open simple requests past 10 working days, open requests quiet for 30 days, unclassified requests, and unlisted requests entering the public figures within 14 days. It names private and embargoed requests, so it refuses to run in Actions; never paste its output anywhere public. It writes nothing, so it has no `--dry-run`.

## Escalation
The Wisconsin Transparency Project (Tom Kamenick) represents news outlets in records suits; it won a settlement with fees for The Badger Project against WisDOT in Aug 2025 ([Badger Project](https://thebadgerproject.org/2025/08/14/wisdot-releases-records-pays-legal-fees-after-lawsuit-from-the-badger-project/)). The Wisconsin Freedom of Information Council is the statewide advocacy group. Log every appeal and suit as an event.

## Editorial policy
- The page reports WPR's own experience, labeled as such. It is not a statewide measure of an agency.
- Requests are listed only after their story runs, or when the editor decides listing is safe.
- No automated characterizations ("stonewalling", "illegal"). Each metric sits next to its benchmark, and the methodology page explains the benchmark's limits: DOJ's 10 days is guidance for simple requests, not a deadline.
- Before publishing a story built on an agency's numbers, the reporter asks that agency for comment.

## Design system and conventions
- **Design system:** Same as the other Ledgers. Teal `#3A867C`, cream `#F6F2E9`; Fraunces for display, Public Sans for body, JetBrains Mono for data.
- **Code:** Python 3.12 (CI pins it; the local `.venv` is 3.14, so use nothing newer than 3.12). Scripts use `argparse` and support `--dry-run`. Use `psycopg`.
- **Site:** no media-query range syntax (Safari before 16.4 ignores it). Every data value is set as text, never as HTML.
  - Fonts are self-hosted (`web/fonts.css`, `web/fonts/`, Fontsource variable builds, Latin subset, OFL licenses alongside): no request leaves the site, and headless renders never fall back.
  - Everything below the masthead stays hidden until the data has rendered (`main[data-loading]`, cleared by `doneLoading()`), so nothing visible shifts as the page fills in. A `<noscript>` style and an inline error listener reveal the page anyway if scripts are off or one fails to load or throws.
  - **Stress test:** `scripts/stress_site.py --check --axe <axe.min.js>` (local, Playwright) builds the site with the demo, worst-case, empty and one-of-everything data and checks every page at 1280, 390 and 320px for console errors, sideways page scroll, text overflowing its box, tables scrolling at desktop width, and axe violations, with screenshots in `site-stress/` (gitignored). Oct 24, 2026: 0 problems after fixing 11 (a URL subject pushing the fee columns off the desktop table; download links scrolling every page sideways at 320px; an unpaged list of 271 rows; the agency filter sized to its longest name; a pasted reason making a row 3,000px tall; a long agency name squeezed one word per line; a blank Agencies section and "since —" on launch night; "1 requests", "1 agencies", "1 days"; an unanchored trend table; scroll regions keyboard users couldn't reach).
  - The rules those fixes set: the request list shows 25 rows at a time ("Show 25 more"), and the filter resets it; a stated reason longer than 240 characters shows its start and "Read all"; every count of 1 reads singular; long names and URLs wrap anywhere rather than overflow; the trend table's agency column stays pinned; scrollable tables are focusable regions; an empty scorecard says why it's empty.
  - Checked Oct 24, 2026 on synthetic data: axe-core 4.14 (WCAG 2.1 A/AA plus best practice) reports no violations on any page at 1280 and 390px. Lighthouse 12.6 (simulated mobile, local server): performance 95/96, accessibility, best practices and SEO 100, CLS 0.024/0. The local server neither compresses nor caches; Pages does both.
- **Locally:** Windows, PowerShell 5.1, `python -m pip`, commands chained with semicolons.
- **Principles:** One correct path, no fallbacks, fail fast. Single-responsibility functions.
