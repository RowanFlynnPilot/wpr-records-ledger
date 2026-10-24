-- wpr-records-ledger — Supabase schema
-- One row per agency, one row per request WPR files, and one row per thing
-- that happens to a request afterward. Status and timing are derived from the
-- events by export.py (rules in law.py); nothing here stores a duplicate status.
--
-- Access: RLS is on. anon and authenticated get nothing. Staff log requests in
-- the Supabase Table Editor (as the project owner). The nightly export connects
-- as ledger_export, which can only read. Public readers only ever see the
-- deployed JSON.

-- public:     counted in agency metrics AND listed with public_subject
-- stats_only: counted in agency metrics once 90 days old (closed or not), never listed.
--             The default — protects requests tied to unpublished stories.
-- private:    excluded from the export entirely
create type request_visibility as enum ('public', 'stats_only', 'private');

-- DOJ's 10-working-day guideline applies only to simple requests
-- ("a limited number of easily identifiable records").
create type request_complexity as enum ('simple', 'complex');

-- 'oral' is the only channel without a written request; s. 19.35(4)(b)'s
-- written-denial rule applies to every other channel.
create type request_channel as enum ('email', 'portal', 'mail', 'hand_delivered', 'oral');

create type request_event_type as enum (
  -- agency actions
  'acknowledged',
  'clarification_requested',   -- clock pauses until clarification_sent
  'delay_notified',
  'fee_quoted',                -- clock pauses until fee_paid or fee_disputed
  'subject_notice_sent',       -- s. 19.356 notice; release barred 12 days
  'records_released',          -- an interim batch; request stays open, clock keeps running
  'fulfilled',                 -- terminal: everything provided
  'partially_denied',          -- terminal: provided with records withheld or redacted
  'denied',                    -- terminal: nothing provided
  'no_records',                -- terminal: agency says no responsive records exist
  'denial_reversed',           -- after a denial, everything withheld is released (on review, appeal or court order)
  -- WPR actions
  'clarification_sent',
  'fee_paid',                  -- amount_cents 0 = fee waived
  'fee_disputed',              -- WPR contests the quote; the clock resumes
  'withdrawn',                 -- terminal
  'appealed_da',
  'appealed_ag',
  'mandamus_filed'
);

create table agencies (
  id              bigint generated always as identity primary key,
  name            text not null unique,
  custodian_email text,
  created_at      timestamptz not null default now()
);

create table requests (
  id                bigint generated always as identity primary key,
  agency_id         bigint not null references agencies (id),
  filed_on          date not null,
  channel           request_channel not null,
  filed_by          text not null,       -- reporter initials
  records_sought    text not null,       -- internal wording, never exported
  public_subject    text,                -- what readers see when visibility = public; never names individuals
  visibility        request_visibility not null default 'stats_only',
  complexity        request_complexity, -- null until classified; unclassified requests skip simple/complex metrics
  complexity_set_by text,                -- initials; must not be the filer
  audit_round       text,                -- quarterly audit round, e.g. '2026-Q3'; null for reporting requests
  public_ref        text unique,         -- set once, by trigger, the first time the request is public; never changes
  created_at        timestamptz not null default now(),
  constraint audit_round_format
    check (audit_round is null or audit_round ~ '^[0-9]{4}-Q[1-4]$'),
  constraint public_needs_subject
    check (visibility <> 'public'
           or (public_subject is not null and length(trim(public_subject)) > 0)),
  constraint complexity_set_by_someone_else
    check ((complexity is null and complexity_set_by is null)
           or (complexity is not null and complexity_set_by is not null
               and length(trim(complexity_set_by)) > 0
               and lower(trim(complexity_set_by)) <> lower(trim(filed_by))))
);

create table request_events (
  id                 bigint generated always as identity primary key,
  request_id         bigint not null references requests (id),
  event_type         request_event_type not null,
  event_on           date not null,
  -- fee_quoted: the quoted total; fee_paid: the amount paid (0 = waived)
  amount_cents       integer,
  -- fee_quoted only, optional: the itemization when the agency gives one.
  -- All three or none, and they must add up to amount_cents.
  location_cents     integer,
  reproduction_cents integer,
  other_cents        integer,
  -- denied / partially_denied only. denial_reason null = no reason stated.
  denial_reason      text,
  remedy_notice      boolean,
  note               text,
  document_url       text,
  created_at         timestamptz not null default now(),

  constraint fee_amount check (
    (event_type in ('fee_quoted', 'fee_paid') and amount_cents is not null and amount_cents >= 0)
    or
    (event_type not in ('fee_quoted', 'fee_paid') and amount_cents is null)
  ),
  constraint fee_itemization check (
    (location_cents is null and reproduction_cents is null and other_cents is null)
    or
    (event_type = 'fee_quoted'
      and location_cents is not null and location_cents >= 0
      and reproduction_cents is not null and reproduction_cents >= 0
      and other_cents is not null and other_cents >= 0
      and location_cents + reproduction_cents + other_cents = amount_cents)
  ),
  constraint denial_details check (
    (event_type in ('denied', 'partially_denied') and remedy_notice is not null)
    or
    (event_type not in ('denied', 'partially_denied')
      and denial_reason is null and remedy_notice is null)
  ),
  -- No reason stated is null, never a blank string, so it is counted as one.
  constraint denial_reason_not_blank check (
    denial_reason is null or length(trim(denial_reason)) > 0
  )
);

create index requests_agency_id_idx on requests (agency_id);
create index request_events_request_id_idx on request_events (request_id);

-- Entry checks: the Table Editor rejects the plainest logging mistakes as they
-- are typed, instead of the nightly export stopping on them. They mirror three
-- of law.validate()'s rules, which stays the authority (it also checks fee and
-- clarification answers, and dates after the export day); the e2e tests check
-- that the two agree.
create function check_request_event() returns trigger
language plpgsql set search_path = public as $$
declare
  filed date;
  withdrawn_on date;
begin
  select filed_on into filed from requests where id = new.request_id;
  if new.event_on < filed then
    raise exception '% on % is dated before the request was filed on %', new.event_type, new.event_on, filed
      using errcode = 'check_violation';
  end if;
  if new.event_type in ('fulfilled', 'partially_denied', 'denied', 'no_records', 'withdrawn')
     and exists (select 1 from request_events
                 where request_id = new.request_id and id is distinct from new.id
                   and event_type in ('fulfilled', 'partially_denied', 'denied', 'no_records', 'withdrawn')) then
    raise exception 'this request already has its final event; log a later batch as records_released'
      using errcode = 'check_violation';
  end if;
  select min(event_on) into withdrawn_on from request_events
  where request_id = new.request_id and id is distinct from new.id and event_type = 'withdrawn';
  if new.event_type not in ('appealed_da', 'appealed_ag', 'mandamus_filed') and new.event_on > withdrawn_on then
    raise exception 'the request was withdrawn on %; only an appeal or suit may follow', withdrawn_on
      using errcode = 'check_violation';
  end if;
  if new.event_type = 'withdrawn'
     and exists (select 1 from request_events
                 where request_id = new.request_id and id is distinct from new.id and event_on > new.event_on
                   and event_type not in ('appealed_da', 'appealed_ag', 'mandamus_filed')) then
    raise exception 'events are logged after % ; a withdrawal must be the last event but appeals', new.event_on
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

create trigger request_events_check before insert or update on request_events
  for each row execute function check_request_event();

create function check_request_filed_on() returns trigger
language plpgsql set search_path = public as $$
begin
  if exists (select 1 from request_events where request_id = new.id and event_on < new.filed_on) then
    raise exception 'filed_on % is after events already logged for this request', new.filed_on
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

create trigger requests_filed_on_check before update of filed_on on requests
  for each row execute function check_request_filed_on();

-- public_ref: the published key for a listed request and its timeline. Set the
-- first time the request is public, as filing date, agency slug, and its place
-- among that agency's refs for that day; kept for good even if the request is
-- later unlisted, so a cited ref never points somewhere else. Never typed by hand.
create function assign_public_ref() returns trigger
language plpgsql set search_path = public as $$
declare
  stem text;
begin
  if (tg_op = 'INSERT' and new.public_ref is not null)
     or (tg_op = 'UPDATE' and new.public_ref is distinct from old.public_ref) then
    raise exception 'public_ref is set automatically and never changes'
      using errcode = 'check_violation';
  end if;
  if new.visibility = 'public' and new.public_ref is null then
    select to_char(new.filed_on, 'YYYY-MM-DD') || '-'
             || trim(both '-' from regexp_replace(lower(a.name), '[^a-z0-9]+', '-', 'g'))
      into stem from agencies a where a.id = new.agency_id;
    new.public_ref := stem || '-' || (
      select coalesce(max(substring(public_ref from '-([0-9]+)$')::int), 0) + 1
      from requests where public_ref ~ ('^' || stem || '-[0-9]+$'));
  end if;
  return new;
end $$;

create trigger requests_public_ref before insert or update on requests
  for each row execute function assign_public_ref();

-- A request that has ever been public can't be deleted: its ref may be cited, and
-- a freed number could be handed to another request. To take one down, set it private.
create function keep_published_requests() returns trigger
language plpgsql set search_path = public as $$
begin
  if old.public_ref is not null then
    raise exception 'request % was public (ref %); set visibility to private instead of deleting it',
      old.id, old.public_ref using errcode = 'check_violation';
  end if;
  return old;
end $$;

create trigger requests_keep_published before delete on requests
  for each row execute function keep_published_requests();

alter table agencies       enable row level security;
alter table requests       enable row level security;
alter table request_events enable row level security;

-- Read-only role for the nightly export. Give it a password and login in the
-- SQL editor (never commit the password):
--   alter role ledger_export with login password '<generate one>';
create role ledger_export nologin;
grant usage on schema public to ledger_export;
grant select on agencies, requests, request_events to ledger_export;
create policy export_reads_agencies on agencies       for select to ledger_export using (true);
create policy export_reads_requests on requests       for select to ledger_export using (true);
create policy export_reads_events   on request_events for select to ledger_export using (true);
