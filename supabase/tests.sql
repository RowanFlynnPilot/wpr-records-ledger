-- wpr-records-ledger — schema tests
-- Runs in one transaction and rolls back, so it is safe to paste into the
-- Supabase SQL editor even after real data exists. Test rows use the marker
-- 'ZZTEST' and every count is limited to them.
-- Any failure raises "TEST FAILED: ..." and stops the run.

begin;

-- ── Happy path ───────────────────────────────────────────────────────────────
insert into agencies (name, custodian_email)
values ('ZZTEST Agency', 'clerk@example.gov');

-- A: simple, classified by someone other than the filer
insert into requests (agency_id, filed_on, channel, filed_by, records_sought,
                      visibility, complexity, complexity_set_by)
select id, '2026-10-01', 'email', 'ZZTEST', 'request A', 'stats_only', 'simple', 'ZZREV'
from agencies where name = 'ZZTEST Agency';

-- B: public, not yet classified
insert into requests (agency_id, filed_on, channel, filed_by, records_sought,
                      public_subject, visibility)
select id, '2026-10-02', 'hand_delivered', 'ZZTEST', 'request B', 'Flock camera audit logs', 'public'
from agencies where name = 'ZZTEST Agency';

insert into request_events (request_id, event_type, event_on, amount_cents,
                            location_cents, reproduction_cents, other_cents,
                            denial_reason, remedy_notice)
select r.id, v.event_type::request_event_type, v.event_on::date, v.amount_cents,
       v.location_cents, v.reproduction_cents, v.other_cents, v.denial_reason, v.remedy_notice
from requests r
join (values
  ('acknowledged',            '2026-10-02', null::int, null::int, null::int, null::int, null::text, null::boolean),
  ('clarification_requested', '2026-10-05', null, null, null, null, null, null),
  ('clarification_sent',      '2026-10-06', null, null, null, null, null, null),
  ('fee_quoted',              '2026-10-07', 6125, 6000, 125, 0, null, null),
  ('fee_paid',                '2026-10-08', 6125, null, null, null, null, null),
  ('subject_notice_sent',     '2026-10-09', null, null, null, null, null, null),
  ('records_released',        '2026-10-26', null, null, null, null, null, null),
  ('partially_denied',        '2026-10-27', null, null, null, null, null, false),   -- no reason stated
  ('appealed_da',             '2026-10-30', null, null, null, null, null, null),
  ('denial_reversed',         '2026-11-06', null, null, null, null, null, null)
) as v(event_type, event_on, amount_cents, location_cents, reproduction_cents, other_cents, denial_reason, remedy_notice)
  on true
where r.records_sought = 'request A' and r.filed_by = 'ZZTEST';

-- C: open, acknowledged only (the target of the event constraint cases below)
-- D: withdrawn
insert into requests (agency_id, filed_on, channel, filed_by, records_sought)
select id, '2026-10-01', 'email', 'ZZTEST', v.r
from agencies, (values ('request C'), ('request D')) as v(r) where name = 'ZZTEST Agency';

insert into request_events (request_id, event_type, event_on)
select id, 'withdrawn', '2026-10-05' from requests where records_sought = 'request D' and filed_by = 'ZZTEST';

insert into request_events (request_id, event_type, event_on)
select id, 'acknowledged', '2026-10-06' from requests where records_sought = 'request C' and filed_by = 'ZZTEST';

insert into request_events (request_id, event_type, event_on, amount_cents)
select id, 'fee_quoted', '2026-10-05', 2500 from requests where records_sought = 'request B' and filed_by = 'ZZTEST';

insert into request_events (request_id, event_type, event_on)
select id, 'fee_disputed', '2026-10-06' from requests where records_sought = 'request B' and filed_by = 'ZZTEST';

insert into request_events (request_id, event_type, event_on)
select id, 'no_records', '2026-10-09' from requests where records_sought = 'request B' and filed_by = 'ZZTEST';

-- public_ref: B was public at filing; A gets one when published and keeps it when unlisted.
update requests set visibility = 'public', public_subject = 'Request A subject'
where records_sought = 'request A' and filed_by = 'ZZTEST';
update requests set visibility = 'stats_only' where records_sought = 'request A' and filed_by = 'ZZTEST';
do $$ begin
  if (select public_ref from requests where records_sought = 'request B' and filed_by = 'ZZTEST')
       is distinct from '2026-10-02-zztest-agency-1'
     or (select public_ref from requests where records_sought = 'request A' and filed_by = 'ZZTEST')
       is distinct from '2026-10-01-zztest-agency-1'
     or (select public_ref from requests where records_sought = 'request C' and filed_by = 'ZZTEST') is not null then
    raise exception 'TEST FAILED: public_ref not assigned once, on first publication';
  end if;
end $$;

do $$ begin
  if (select count(*) from request_events e join requests r on r.id = e.request_id
      where r.filed_by = 'ZZTEST') <> 15 then
    raise exception 'TEST FAILED: expected 15 happy-path events';
  end if;
end $$;

-- ── Constraint violations that must be rejected ─────────────────────────────
-- Each statement must raise check_violation; a statement that succeeds fails the run.
create temporary table must_fail (label text, stmt text) on commit drop;
insert into must_fail values
  ('public request without public_subject',
   $s$insert into requests (agency_id, filed_on, channel, filed_by, records_sought, visibility)
      select id, '2026-10-01', 'email', 'ZZTEST', 'x', 'public' from agencies where name = 'ZZTEST Agency'$s$),
  ('public request with blank public_subject',
   $s$insert into requests (agency_id, filed_on, channel, filed_by, records_sought, public_subject, visibility)
      select id, '2026-10-01', 'email', 'ZZTEST', 'x', '   ', 'public' from agencies where name = 'ZZTEST Agency'$s$),
  ('complexity set by the filer',
   $s$insert into requests (agency_id, filed_on, channel, filed_by, records_sought, complexity, complexity_set_by)
      select id, '2026-10-01', 'email', 'ZZTEST', 'x', 'simple', 'ZZTEST' from agencies where name = 'ZZTEST Agency'$s$),
  ('complexity set by the filer, differing only in case and spaces',
   $s$insert into requests (agency_id, filed_on, channel, filed_by, records_sought, complexity, complexity_set_by)
      select id, '2026-10-01', 'email', 'ZZTEST', 'x', 'simple', ' zztest ' from agencies where name = 'ZZTEST Agency'$s$),
  ('complexity set by a blank name',
   $s$insert into requests (agency_id, filed_on, channel, filed_by, records_sought, complexity, complexity_set_by)
      select id, '2026-10-01', 'email', 'ZZTEST', 'x', 'simple', '  ' from agencies where name = 'ZZTEST Agency'$s$),
  ('complexity without complexity_set_by',
   $s$insert into requests (agency_id, filed_on, channel, filed_by, records_sought, complexity)
      select id, '2026-10-01', 'email', 'ZZTEST', 'x', 'complex' from agencies where name = 'ZZTEST Agency'$s$),
  ('malformed audit_round',
   $s$insert into requests (agency_id, filed_on, channel, filed_by, records_sought, audit_round)
      select id, '2026-10-01', 'email', 'ZZTEST', 'x', 'Q3 2026' from agencies where name = 'ZZTEST Agency'$s$),
  ('fee_quoted without amount',
   $s$insert into request_events (request_id, event_type, event_on)
      select id, 'fee_quoted', '2026-10-06' from requests where records_sought = 'request A'$s$),
  ('partial itemization',
   $s$insert into request_events (request_id, event_type, event_on, amount_cents, location_cents)
      select id, 'fee_quoted', '2026-10-06', 500, 500 from requests where records_sought = 'request A'$s$),
  ('itemization that does not add up',
   $s$insert into request_events (request_id, event_type, event_on, amount_cents, location_cents, reproduction_cents, other_cents)
      select id, 'fee_quoted', '2026-10-06', 500, 100, 100, 100 from requests where records_sought = 'request A'$s$),
  ('negative amount',
   $s$insert into request_events (request_id, event_type, event_on, amount_cents)
      select id, 'fee_paid', '2026-10-06', -1 from requests where records_sought = 'request A'$s$),
  ('itemization on fee_paid',
   $s$insert into request_events (request_id, event_type, event_on, amount_cents, location_cents, reproduction_cents, other_cents)
      select id, 'fee_paid', '2026-10-06', 100, 100, 0, 0 from requests where records_sought = 'request A'$s$),
  ('amount on a non-fee event',
   $s$insert into request_events (request_id, event_type, event_on, amount_cents)
      select id, 'acknowledged', '2026-10-06', 100 from requests where records_sought = 'request A'$s$),
  ('denial without remedy_notice',
   $s$insert into request_events (request_id, event_type, event_on, denial_reason)
      select id, 'denied', '2026-10-06', 'Ongoing investigation' from requests where records_sought = 'request C'$s$),
  ('blank denial_reason',
   $s$insert into request_events (request_id, event_type, event_on, denial_reason, remedy_notice)
      select id, 'denied', '2026-10-06', '  ', true from requests where records_sought = 'request C'$s$),
  ('denial_reason on fulfilled',
   $s$insert into request_events (request_id, event_type, event_on, denial_reason)
      select id, 'fulfilled', '2026-10-06', 'n/a' from requests where records_sought = 'request C'$s$),
  ('remedy_notice on no_records',
   $s$insert into request_events (request_id, event_type, event_on, remedy_notice)
      select id, 'no_records', '2026-10-06', true from requests where records_sought = 'request C'$s$),
  -- Entry checks (triggers)
  ('event dated before filing',
   $s$insert into request_events (request_id, event_type, event_on)
      select id, 'acknowledged', '2026-09-30' from requests where records_sought = 'request C'$s$),
  ('second final event',
   $s$insert into request_events (request_id, event_type, event_on)
      select id, 'fulfilled', '2026-11-02' from requests where records_sought = 'request A'$s$),
  ('event after withdrawn',
   $s$insert into request_events (request_id, event_type, event_on)
      select id, 'acknowledged', '2026-10-06' from requests where records_sought = 'request D'$s$),
  ('withdrawn dated before an event already logged',
   $s$insert into request_events (request_id, event_type, event_on)
      select id, 'withdrawn', '2026-10-05' from requests where records_sought = 'request C'$s$),
  ('public_ref typed by hand',
   $s$update requests set public_ref = '2026-10-01-zztest-agency-9' where records_sought = 'request C'$s$),
  ('public_ref changed',
   $s$update requests set public_ref = null where records_sought = 'request B' and filed_by = 'ZZTEST'$s$),
  ('filed_on moved after logged events',
   $s$update requests set filed_on = '2026-10-03' where records_sought = 'request A' and filed_by = 'ZZTEST'$s$);

do $$
declare t record;
begin
  for t in select * from must_fail loop
    begin
      execute t.stmt;
      raise exception 'TEST FAILED: accepted %', t.label;
    exception when check_violation then null;
    end;
  end loop;
end $$;

-- ── RLS: anon and authenticated see and write nothing ───────────────────────
set local role anon;
do $$ begin
  if (select count(*) from agencies) <> 0
     or (select count(*) from requests) <> 0
     or (select count(*) from request_events) <> 0 then
    raise exception 'TEST FAILED: anon can read rows';
  end if;
  begin
    insert into agencies (name) values ('ZZTEST Anon Agency');
    raise exception 'TEST FAILED: anon inserted an agency';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;

set local role authenticated;
do $$ begin
  if (select count(*) from requests) <> 0 then
    raise exception 'TEST FAILED: authenticated can read requests';
  end if;
end $$;
update requests set public_subject = 'changed by authenticated';
reset role;

do $$ begin
  if exists (select 1 from requests where public_subject = 'changed by authenticated') then
    raise exception 'TEST FAILED: authenticated updated a request';
  end if;
end $$;

-- ── ledger_export: reads everything, writes nothing ─────────────────────────
set local role ledger_export;
do $$ begin
  if (select count(*) from requests where filed_by = 'ZZTEST') <> 4
     or (select count(*) from request_events e join requests r on r.id = e.request_id where r.filed_by = 'ZZTEST') <> 15 then
    raise exception 'TEST FAILED: ledger_export cannot read the test rows';
  end if;
  begin
    insert into agencies (name) values ('ZZTEST Export Agency');
    raise exception 'TEST FAILED: ledger_export inserted an agency';
  exception when insufficient_privilege then null;
  end;
  begin
    update requests set public_subject = 'changed by export' where filed_by = 'ZZTEST';
    raise exception 'TEST FAILED: ledger_export updated a request';
  exception when insufficient_privilege then null;
  end;
  begin
    delete from request_events;
    raise exception 'TEST FAILED: ledger_export deleted events';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;

do $$ begin raise notice 'ALL SCHEMA TESTS PASSED'; end $$;

rollback;
