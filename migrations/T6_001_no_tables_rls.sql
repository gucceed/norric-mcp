-- T6-01: Lock Norway tables exposed through Supabase PostgREST (same pattern as T4_001).
-- Runtime services use direct PostgreSQL DATABASE_URL connections; no browser
-- or anonymous client depends on these tables.

begin;

alter table public.norric_no_entities enable row level security;
alter table public.norric_no_events enable row level security;
alter table public.norric_no_field_changes enable row level security;
alter table public.norric_no_ingest_state enable row level security;

revoke all privileges on table
  public.norric_no_entities,
  public.norric_no_events,
  public.norric_no_field_changes,
  public.norric_no_ingest_state
from anon, authenticated;

-- Preserve privileged server-side PostgREST access. Direct PostgreSQL table
-- owners and BYPASSRLS roles continue to bypass RLS.
grant select, insert, update, delete on table
  public.norric_no_entities,
  public.norric_no_events,
  public.norric_no_field_changes,
  public.norric_no_ingest_state
to service_role;

commit;
