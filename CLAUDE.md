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
  - **Quarterly frozen copies.** After the export, a separate `snapshot` job (the only one with `contents: write`) publishes the exported CSVs and JSON as the GitHub Release `data-YYYY-Qn` for the quarter that last ended, if it doesn't exist yet: the first successful export after a quarter ends freezes it, so a figure cited in a story can be checked later. A release is not a commit; it is permanent public data, so correcting a request after its quarter is frozen means editing or deleting that release by hand.
  - GitHub disables a public repo's scheduled workflows after 60 days with no repository activity, and this repo commits no data. Watch for GitHub's warning email and re-enable the workflow, or push a commit, before then.
- **Licensing.** The repo is public. Code is MIT-licensed and published data is CC BY 4.0.

**Built and tested (`python -m pytest tests`, plus `supabase/tests.sql`):**
- `supabase/schema.sql`: tables, enums, check constraints, RLS, and the `ledger_export` role
- `supabase/tests.sql`: one transaction that rolls back, touching only rows marked `ZZTEST`
- `law.py`: every statutory value and clock rule. The methodology page prints it.
- `export.py`: DB → `law.validate` → metrics → site artifact. It decides only which fields leave the database; every rule comes from `law.py`.
- `tests/test_law.py`, `tests/test_export.py` (no database), `tests/test_export_e2e.py` (local Postgres)
- `tests/synthetic.py`: the synthetic agencies, requests and events, with every expected value worked out by hand. Never-published columns carry `SENTINEL`, and the e2e test searches every output file for it.
- `web/`: static HTML/CSS/JS, no build step
- `backfill.py` and `tests/test_backfill.py`: loads past requests from two CSVs (templates and a column guide in `backfill_templates/`). Local only, as the owner (`LEDGER_WRITE_DB_URL`).
- `staff_report.py` and `tests/test_staff_report.py`: the staff's private to-do list (see Logging). Refuses to run in Actions.
- `snapshot.py` and `tests/test_snapshot.py`: names the frozen data release (`data-YYYY-Qn`) for the quarter that last ended.
- `.github/workflows/test.yml`: the whole suite on Python 3.12 with a Postgres 16 service on every push; first passed Oct 24, 2026 (56 tests, none skipped).

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
- **Record-subject notice, s. 19.356:** For certain records (an employee's disciplinary-investigation records, records obtained by subpoena or search warrant, and records prepared by another employer about its employee), the agency must notify the record subject within 3 days of deciding to release. It may not release within 12 days of sending that notice, and not at all while the subject's suit to block release (allowed within 10 days of the notice) or any appeal is pending, s. 19.356(5). Verified Oct 23, 2026 against the current statute, last amended by 2011 Wis. Act 84.
  - That is why an early notice leaves a request **not judged** rather than judged after subtracting 12 days: the ledger logs no event for the subject's suit, so it can't tell a slow agency from one the law still bars.
- **Fees after a lawsuit:** *Friends of Frame Park v. City of Waukesha* (Wis. 2022) allows attorney fees only when a court orders release.

Sources: [DOJ Compliance Guide (June 2025)](https://www.wisdoj.gov/Open%20Government/PRL_guide.pdf); [DOJ fee schedule (June 2025)](https://www.wisdoj.gov/Open%20Government/Public%20Records%20Request%20Fee%20Schedule%20June%202025.pdf); [s. 19.356 (current)](https://docs.legis.wisconsin.gov/statutes/statutes/19/ii/356); [TMJ4 on Frame Park](https://www.tmj4.com/news/local-news/wisconsin-courts-open-records-ruling-decried-as-gutting-law).

## Clock and benchmark rules (`law.py`)
- **Working days.** `working_days(agency, start, end)` counts the agency's weekdays from the filing day up to, but not including, the end day. It skips `HOLIDAYS[agency][year]`, which `law.py` loads from **`holidays.toml`**, plain TOML dates the editor sets and the methodology page prints (the site also carries the file). Every clock function (`agency_working_days`, `held_working_days`, `benchmark_result`, `counts_in_median`) takes the agency first.
  - `load_holidays()` refuses a weekend date, a date under the wrong year, a repeated date or a non-date, and the export refuses an agency name not in the `agencies` table, so a typo stops the export instead of skipping the wrong day.
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
- **Same-day order** (`law.in_order()`, also the published timeline's order). Events on one day sort in the order they must have happened, whatever order staff logged them: the agency's events (a new ask among them), WPR's answers, the final event, remedies, a reversal. Two exceptions:
  - An ask still open from an earlier day, answered today while the agency asks again today: today's answer comes first when a later answer exists for the new ask; otherwise today's answer is to today's ask.
  - A quote in the same letter as the final response is a bill (see below).
- **Fee billed with the response.** A `fee_quoted` dated the same day as the agency's final response is a bill for what came with the response, unless that day carries more fee answers than an earlier open quote needs: it sorts after the response and pauses nothing. A quote on an earlier day must still be answered first.
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
  - `ref` (also the first field of `requests`) joins them. It is `requests.public_ref`, which the `assign_public_ref` trigger sets the first time a request is public: filing date, agency slug, and its place among that agency's refs that day. It never changes, even if the request is later unlisted, so a cited ref stays good; staff can't type or edit one. (A gap, e.g. a `-2` with no `-1` listed, shows that a same-day request was once listed.) Database ids are never published, since they count every request, private ones included.
- `meta.json`: `generated_at`, `as_of` (the day open requests are measured to), `earliest_filed_on` (over counted requests only), and `law` (`law.published_values()`: the four constants and the holiday lists, by agency then year)
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
     - Amounts are in dollars and `remedy_notice` is `yes`/`no`; the file's `key` links replies to requests and isn't stored.
2. **Quarterly audit.** File the Q3 2026 round from the Closed Door Ledger's `audit.py` list, one request per custodian with identical wording.
   - Log each with `audit_round` set. The site's audit section shows a round's **public** requests side by side, as counts (a round is too small for shares), so set the round's requests to `public` when it is published.
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
- **Weekly:** run `python staff_report.py` locally with the `ledger_export` URL. It lists, with ids, agencies and filers: logs that would stop the export, requests that can't be measured for want of a holiday list, asks waiting on WPR, open simple requests past 10 working days, open requests quiet for 30 days, unclassified requests, and unlisted requests entering the public figures within 14 days. It names private and embargoed requests, so it refuses to run in Actions; never paste its output anywhere public. It writes nothing, so it has no `--dry-run`.

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
  - Everything below the masthead stays hidden until the data has rendered (`main[data-loading]`, cleared by `doneLoading()`), so nothing visible shifts as the page fills in.
  - Checked Oct 24, 2026 on synthetic data: axe-core 4.14 (WCAG 2.1 A/AA plus best practice) reports no violations on any page at 1280 and 390px. Lighthouse 12.6 (simulated mobile, local server): performance 95/96, accessibility, best practices and SEO 100, CLS 0.024/0. The local server neither compresses nor caches; Pages does both.
- **Locally:** Windows, PowerShell 5.1, `python -m pip`, commands chained with semicolons.
- **Principles:** One correct path, no fallbacks, fail fast. Single-responsibility functions.
