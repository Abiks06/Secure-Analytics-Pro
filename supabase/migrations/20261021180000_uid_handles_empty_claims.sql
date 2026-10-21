-- After a transaction-local set_config, Postgres leaves the setting as '' (not NULL) for later
-- transactions on the same connection. Treat empty claims as "no user" instead of erroring.
create or replace function sap.uid()
returns uuid
language sql
stable
set search_path = ''
as $$
  select nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')::uuid
$$;
