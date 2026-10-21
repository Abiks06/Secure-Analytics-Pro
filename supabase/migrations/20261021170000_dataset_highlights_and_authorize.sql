-- Small per-dataset summary so list views never load the full analysis report.
alter table sap.datasets add column if not exists highlights jsonb not null default '{}'::jsonb;

update sap.datasets
   set highlights = jsonb_build_object(
         'insight_count', coalesce(jsonb_array_length(report -> 'insights'), 0),
         'pii_count', coalesce(jsonb_array_length(report -> 'privacy' -> 'findings'), 0),
         'top_insights', coalesce((
           select jsonb_agg(jsonb_build_object('title', i -> 'title', 'kind', i -> 'kind', 'severity', i -> 'severity'))
             from (select i from jsonb_array_elements(report -> 'insights') as i limit 3) t
         ), '[]'::jsonb))
 where report is not null;

-- One round trip per request: scope the transaction to the caller's claims and confirm their
-- Supabase session is still live (revoked sessions fail immediately, not at token expiry).
create or replace function sap.authorize(claims jsonb)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  perform set_config('request.jwt.claims', claims::text, true);
  return exists (
    select 1 from auth.sessions s
    where s.id = (claims ->> 'session_id')::uuid
      and s.user_id = (claims ->> 'sub')::uuid
      and (s.not_after is null or s.not_after > now())
  );
end
$$;
revoke all on function sap.authorize(jsonb) from public;
grant execute on function sap.authorize(jsonb) to sap_engine;
