-- Secure Analytics Pro: core schema for the Supabase backend.
--
-- Design:
--   * Users, sessions and refresh-token rotation are owned by Supabase Auth (auth.*).
--   * Application data lives in the private `sap` schema, which is NOT exposed through the
--     Data API. Browsers never query it; only the analytics engine does.
--   * The engine connects as `sap_engine`: no superuser, no BYPASSRLS, no inherited roles.
--     Every transaction sets `request.jwt.claims` to the caller's verified JWT, and every
--     policy keys on `sap.uid()`, so a query can only ever see the caller's rows.

create schema if not exists sap;
revoke all on schema sap from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------
-- Engine role (password is set out of band, never in a migration)
-- ---------------------------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'sap_engine') then
    create role sap_engine login noinherit nosuperuser nobypassrls nocreatedb nocreaterole;
  end if;
end
$$;
alter role sap_engine set statement_timeout = '30s';
alter role sap_engine set idle_in_transaction_session_timeout = '60s';
grant usage on schema sap to sap_engine;

-- The caller's user id, taken from the JWT claims the engine sets per transaction.
create or replace function sap.uid()
returns uuid
language sql
stable
set search_path = ''
as $$
  select nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', '')::uuid
$$;
revoke all on function sap.uid() from public;
grant execute on function sap.uid() to sap_engine;

-- ---------------------------------------------------------------------------------------
-- Datasets
-- ---------------------------------------------------------------------------------------
create table if not exists sap.datasets (
  id              uuid primary key default gen_random_uuid(),
  owner_id        uuid not null default sap.uid() references auth.users (id) on delete cascade,
  name            text not null check (char_length(name) between 1 and 255),
  source_format   text not null default '',
  status          text not null default 'queued' check (status in ('queued', 'processing', 'ready', 'failed')),
  stage           text not null default 'queued',
  progress        double precision not null default 0,
  error           text,
  size_bytes      bigint not null default 0,
  stored_bytes    bigint not null default 0,
  sha256          text not null default '',
  row_count       bigint not null default 0,
  column_count    integer not null default 0,
  quality_score   double precision,
  processing_ms   integer,
  wrapped_key     bytea,
  storage_path    text,
  report          jsonb,
  privacy_policy  jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists datasets_owner_created_idx on sap.datasets (owner_id, created_at desc);
create index if not exists datasets_active_idx on sap.datasets (status) where status in ('queued', 'processing');

create or replace function sap.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end
$$;
drop trigger if exists datasets_touch on sap.datasets;
create trigger datasets_touch before update on sap.datasets
  for each row execute function sap.touch_updated_at();

alter table sap.datasets enable row level security;
alter table sap.datasets force row level security;

drop policy if exists datasets_select on sap.datasets;
drop policy if exists datasets_insert on sap.datasets;
drop policy if exists datasets_update on sap.datasets;
drop policy if exists datasets_delete on sap.datasets;
create policy datasets_select on sap.datasets for select to sap_engine
  using (owner_id = (select sap.uid()));
create policy datasets_insert on sap.datasets for insert to sap_engine
  with check (owner_id = (select sap.uid()));
create policy datasets_update on sap.datasets for update to sap_engine
  using (owner_id = (select sap.uid())) with check (owner_id = (select sap.uid()));
create policy datasets_delete on sap.datasets for delete to sap_engine
  using (owner_id = (select sap.uid()));

grant select, insert, update, delete on sap.datasets to sap_engine;

-- ---------------------------------------------------------------------------------------
-- Audit trail: append-only and hash-chained per user
-- ---------------------------------------------------------------------------------------
create table if not exists sap.audit_events (
  id          bigint generated always as identity primary key,
  owner_id    uuid not null default sap.uid() references auth.users (id) on delete cascade,
  seq         integer not null,
  action      text not null,
  target      text,
  ip          text not null default '',
  detail      jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  prev_hash   text not null,
  hash        text not null,
  unique (owner_id, seq)
);

create or replace function sap.audit_is_append_only()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'audit_events is append-only';
end
$$;
drop trigger if exists audit_append_only on sap.audit_events;
create trigger audit_append_only before update or delete on sap.audit_events
  for each row execute function sap.audit_is_append_only();

alter table sap.audit_events enable row level security;
alter table sap.audit_events force row level security;

drop policy if exists audit_select on sap.audit_events;
drop policy if exists audit_insert on sap.audit_events;
create policy audit_select on sap.audit_events for select to sap_engine
  using (owner_id = (select sap.uid()));
create policy audit_insert on sap.audit_events for insert to sap_engine
  with check (owner_id = (select sap.uid()));

grant select, insert on sap.audit_events to sap_engine;

-- ---------------------------------------------------------------------------------------
-- Session management on top of Supabase Auth. SECURITY DEFINER functions expose only the
-- caller's own sessions; sap_engine has no access to the auth schema otherwise.
-- ---------------------------------------------------------------------------------------
create or replace function sap.session_is_active(session_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from auth.sessions s
    where s.id = session_id
      and s.user_id = (select sap.uid())
      and (s.not_after is null or s.not_after > now())
  )
$$;

create or replace function sap.list_sessions()
returns table (id uuid, created_at timestamptz, last_used_at timestamptz, user_agent text, ip text, aal text)
language sql
stable
security definer
set search_path = ''
as $$
  select s.id, s.created_at, coalesce(s.refreshed_at::timestamptz, s.updated_at, s.created_at),
         coalesce(s.user_agent, ''), coalesce(host(s.ip), ''), s.aal::text
  from auth.sessions s
  where s.user_id = (select sap.uid())
  order by 3 desc
$$;

-- Deleting the session cascades to its refresh tokens, so it can never be refreshed again;
-- sap.session_is_active() makes outstanding access tokens fail on their next request.
create or replace function sap.revoke_session(session_id uuid)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  n integer;
begin
  delete from auth.sessions s where s.id = session_id and s.user_id = (select sap.uid());
  get diagnostics n = row_count;
  return n > 0;
end
$$;

-- Startup recovery for uploads cut off by a restart (raw files are memory-only).
create or replace function sap.fail_interrupted_jobs(older_than interval default interval '5 minutes')
returns integer
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  n integer;
begin
  update sap.datasets
     set status = 'failed', stage = 'failed',
         error = 'Interrupted by a server restart. Please upload again.'
   where status in ('queued', 'processing') and updated_at < now() - older_than;
  get diagnostics n = row_count;
  return n;
end
$$;

revoke all on function sap.session_is_active(uuid) from public;
revoke all on function sap.list_sessions() from public;
revoke all on function sap.revoke_session(uuid) from public;
revoke all on function sap.fail_interrupted_jobs(interval) from public;
grant execute on function sap.session_is_active(uuid) to sap_engine;
grant execute on function sap.list_sessions() to sap_engine;
grant execute on function sap.revoke_session(uuid) to sap_engine;
grant execute on function sap.fail_interrupted_jobs(interval) to sap_engine;

-- ---------------------------------------------------------------------------------------
-- Storage: private bucket for AES-256-GCM encrypted datasets. Objects live under
-- <user id>/<dataset id>.sap and each user can only touch their own folder. The engine
-- writes with the user's own access token, so it never needs the service-role key.
-- ---------------------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('datasets', 'datasets', false, 52428800, array['application/octet-stream'])
on conflict (id) do update
  set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "datasets: owner reads" on storage.objects;
drop policy if exists "datasets: owner writes" on storage.objects;
drop policy if exists "datasets: owner updates" on storage.objects;
drop policy if exists "datasets: owner deletes" on storage.objects;
create policy "datasets: owner reads" on storage.objects for select to authenticated
  using (bucket_id = 'datasets' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "datasets: owner writes" on storage.objects for insert to authenticated
  with check (bucket_id = 'datasets' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "datasets: owner updates" on storage.objects for update to authenticated
  using (bucket_id = 'datasets' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'datasets' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "datasets: owner deletes" on storage.objects for delete to authenticated
  using (bucket_id = 'datasets' and (storage.foldername(name))[1] = (select auth.uid())::text);
