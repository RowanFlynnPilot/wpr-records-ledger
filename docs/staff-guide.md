# Logging records requests: the staff guide

Everything the Records Ledger publishes comes from what we log. Log each request the day you file it, and each reply the day it arrives. This guide covers the Supabase Table Editor, which is where logging happens for now.

## The two rules that matter most

1. **When the agency asks you something, log your answer.** If they quote a fee, log the payment, the waiver or your dispute. If they ask for clarification, log that you sent it. Skip this and the nightly update stops, and the site goes stale until someone fixes it.
2. **Keep unpublished work unlisted.** A request stays `stats_only` until its story runs, and even then only the editor makes it public. The subject line written for readers, and any denial reason on a public request, must never name a person.

## Filing a request: one row in `requests`

| Column | What to enter |
|---|---|
| `agency_id` | Pick the agency. If it isn't there, add it to `agencies` first, using its exact official name. |
| `filed_on` | The day you sent or handed in the request. |
| `channel` | `email`, `portal`, `mail`, `hand_delivered` or `oral`. Use `oral` only for a request made aloud: the law treats its denial differently. |
| `filed_by` | Your initials. |
| `records_sought` | What you asked for, in your words. Never published. |
| `public_subject` | Leave blank until the request goes public. Then a short, plain description a reader would understand, with no names of individuals. |
| `visibility` | Leave it as `stats_only`. The editor changes it to `public` once the story runs, or to `private` to keep it out of the figures entirely. |
| `complexity`, `complexity_set_by` | Leave blank. **Someone other than you** sets `simple` or `complex` and enters their own initials. Simple means a limited number of easily identifiable records, the Justice Department's wording. |
| `audit_round` | Only for a quarterly audit request: the round, written `2026-Q3`. Blank otherwise. |

Don't touch `id`, `public_ref` or `created_at`. The database fills them in.

## Logging a reply: one row in `request_events`

One row per thing that happened, dated **the day it arrived** (or the day you sent your answer). Pick the request, the `event_type` and the date, then fill in only the columns that event needs.

### What the agency does

| Event | Use it when | Also fill in |
|---|---|---|
| `acknowledged` | The agency confirms it got the request. | |
| `delay_notified` | The agency says it needs more time. | |
| `clarification_requested` | The agency asks you to narrow or explain the request. **You must log your answer.** | |
| `fee_quoted` | The agency quotes a fee. **You must log your answer.** | `amount_cents`: the total in cents ($61.25 is `6125`). If the agency itemized it, also `location_cents`, `reproduction_cents` and `other_cents`: all three, adding up to the total. |
| `subject_notice_sent` | The agency tells you it has notified the employee or person the records are about (s. 19.356). | |
| `records_released` | A batch of records arrives, but more are still coming. | |
| `fulfilled` | The agency says it has provided everything. | |
| `partially_denied` | Records arrive, but some are withheld or redacted, and that's the agency's final answer. | `denial_reason` and `remedy_notice` (below) |
| `denied` | The agency refuses the whole request. | `denial_reason` and `remedy_notice` (below) |
| `no_records` | The agency says no records exist. | |
| `denial_reversed` | After a denial, the agency releases **everything** it withheld, on its own, after an appeal, or by court order. If it releases only some, log `records_released` instead. | |

`fulfilled`, `partially_denied`, `denied` and `no_records` are the agency's **final response**. A request gets exactly one, and the clock stops on it. Anything that arrives afterward is `records_released` (or `denial_reversed`).

### What WPR does

| Event | Use it when | Also fill in |
|---|---|---|
| `clarification_sent` | You answer the agency's question. | |
| `fee_paid` | You pay a quoted fee, or the agency waives it. | `amount_cents`: what you paid, in cents. **`0` means the fee was waived.** |
| `fee_disputed` | You push back on a quote. If the agency then sends a new quote, log that as another `fee_quoted`. | |
| `withdrawn` | You drop the request. After this, only an appeal or lawsuit can be logged. | |
| `appealed_da`, `appealed_ag` | You ask the district attorney or the attorney general to review a denial. | |
| `mandamus_filed` | You sue for the records. | |

### Denials

On a `denied` or `partially_denied` row:

- **`denial_reason`:** paste the reason exactly as the agency stated it. If the letter gave no reason, **leave it empty**, not a dash or "none". Empty is how the ledger counts a denial with no stated reason. On a public request, the reason is published, so it must not name a person: edit a name out and put `[name]`.
- **`remedy_notice`:** `true` if the letter said the denial can be reviewed by a court (mandamus) or by the district attorney or attorney general; `false` if it didn't.

### Letters and notes

Put the agency's letter, and any records, in Drive, and paste the link into `document_url`. Anything you want to remember goes in `note`. Neither is ever published.

## Things the Table Editor will refuse

These are blocked as you type, with a message saying why:

- **An event dated before the request was filed.** Check the date, or the request's `filed_on`.
- **A second final response.** Log later records as `records_released`.
- **Anything after `withdrawn` except an appeal or lawsuit.**
- **Deleting a request that has ever been public.** Its reference number may have been cited. To take one down, set `visibility` to `private`.
- A public request with no `public_subject`; `complexity` set by the filer; a blank `denial_reason` (leave it empty instead); a fee with no amount; an itemization that doesn't add up; `audit_round` not written like `2026-Q3`.

One mistake the Table Editor can't catch as you type: **a final response logged while a fee quote or clarification question is still unanswered.** The nightly update stops on it, and the site shows a "may be out of date" banner after two days. The weekly report lists it, so fix it by logging the missing answer, dated the day it really happened.

## Fixing a mistake

- **Wrong date, amount or event type:** edit the row.
- **An event logged on the wrong request:** delete that event row and log it again on the right one.
- **A request filed twice by mistake:** delete the duplicate's events first, then the duplicate itself. If it was ever public, it can't be deleted: set it `private` instead.

## Same-day events

If several things happen on one day, log each as its own row with that day's date, in any order. The ledger works out the order that must have happened: the agency's question before your answer, a payment before the release it unlocked, and so on.

## Weekly: the staff report

Once a week, whoever keeps the ledger runs:

```
$env:SUPABASE_DB_URL = "<the ledger_export connection string>"; python staff_report.py
```

It lists, by request number, agency and filer:

- logs that would stop the nightly update
- requests that will stop it because their agency has no holiday list yet
- questions and quotes waiting on our answer
- simple requests open past 10 working days
- open requests with nothing logged in 30 days, to chase
- requests nobody has classified as simple or complex
- unlisted requests about to enter the public figures (they enter at 90 days old)

The report names unlisted and private requests, so never paste it anywhere public.

## For the editor

- **Making a request public:** set `visibility` to `public` and write the `public_subject`. It gets a permanent reference number at that moment.
- **Holiday lists:** each agency's office closures live in `holidays.toml`, one list per year, so working days are counted correctly. Every agency needs next year's dates **before Jan. 1**. From Dec. 1, the nightly update warns about any agency that's missing them.
- **Before a story built on an agency's numbers runs,** the reporter asks that agency for comment.
