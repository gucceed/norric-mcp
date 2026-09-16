-- Lock server-only Norric/Sigvik tables exposed through Supabase PostgREST.
-- Runtime services use direct PostgreSQL DATABASE_URL connections; no browser
-- or anonymous client depends on these tables.

begin;

alter table public.brfs enable row level security;
alter table public.company_score_history enable row level security;
alter table public.alembic_version enable row level security;
alter table public.company_scores enable row level security;
alter table public.norric_entities enable row level security;
alter table public.norric_pipeline_runs enable row level security;

revoke all privileges on table
  public.brfs,
  public.company_score_history,
  public.alembic_version,
  public.company_scores,
  public.norric_entities,
  public.norric_pipeline_runs
from anon, authenticated;

-- Preserve privileged server-side PostgREST access. Direct PostgreSQL table
-- owners and BYPASSRLS roles continue to bypass RLS.
grant select, insert, update, delete on table
  public.brfs,
  public.company_score_history,
  public.company_scores,
  public.norric_entities,
  public.norric_pipeline_runs
to service_role;

commit;
