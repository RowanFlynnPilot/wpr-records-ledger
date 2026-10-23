# The Records Ledger

How central Wisconsin agencies answer [Wausau Pilot & Review](https://wausaupilotandreview.com)'s public records requests. For every request the newsroom files, the ledger logs every response it gets, then measures how long the agency held the request, what it charged and what it denied.

## What the numbers mean
- **Scope.** This is WPR's own experience with these agencies, labeled as such. It is not a statewide measure of any agency.
- **Response time.** It counts working days from filing to the agency's final response: records, a denial, or "no records". Days the agency spent waiting on WPR, for a clarification or a fee decision, are not counted. An interim batch of records doesn't stop the clock.
- **The 10-day benchmark.** It is DOJ guidance for simple requests, not a legal deadline. The person who filed a request never classifies it.
- **Not judged against the benchmark:**
  - complex or unclassified requests
  - requests involving a s. 19.356 notice to an employee within the first 10 working days, where the law bars release for 12 days
  - requests withdrawn or still open inside 10 working days
- **Small samples.** Medians and shares appear only when that statistic's own n is 5 or more, and n is always shown. Nothing is ranked.
- **Unpublished stories.** Requests tied to unpublished stories are counted only once they are closed or 90 days old.

Every rule and statutory value the page uses lives in [`law.py`](law.py), and the methodology page prints it.

## Development
```
python -m pip install -r requirements.txt
python -m pytest tests
```
Schema tests: apply `supabase/schema.sql`, then run `supabase/tests.sql` in the SQL editor. It runs in one transaction, rolls back and touches only rows marked `ZZTEST`.

## License
Code: MIT (see [LICENSE](LICENSE)). Published data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), credit Wausau Pilot & Review.
