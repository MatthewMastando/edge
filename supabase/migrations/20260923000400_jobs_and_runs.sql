-- Durable jobs, runs, tool calls, routines and notifications.

create table public.routines (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid,
  name text not null,
  kind text not null check (kind in ('scheduled_briefing', 'ta_trigger', 'manual')),
  enabled boolean not null default true,
  schedule_cron text,                   -- for scheduled_briefing
  schedule_timezone text not null default 'America/New_York',
  watchlist_id uuid references public.watchlists (id) on delete set null,
  instrument_ids uuid[] not null default '{}',
  config jsonb not null default '{}'::jsonb,  -- event allowlist, research tier, prompt version
  cooldown_seconds integer not null default 14400 check (cooldown_seconds >= 0),
  daily_cap integer not null default 6 check (daily_cap >= 0),
  last_run_at timestamptz,
  next_run_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index routines_due_idx on public.routines (enabled, next_run_at);

create trigger routines_set_updated_at
  before update on public.routines
  for each row execute function public.set_updated_at();

-- Job state machine: queued -> running -> {partial, completed, failed, cancelled, budget_exceeded}
--                    running -> queued (lease expired, requeued)   partial -> running (resume)
create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in
    ('research', 'ta_scan', 'snapshot_capture', 'scheduled_briefing', 'hypothesis_check',
     'csv_import', 'maintenance')),
  state text not null default 'queued' check (state in
    ('queued', 'running', 'partial', 'completed', 'failed', 'cancelled', 'budget_exceeded')),
  priority integer not null default 0,
  payload jsonb not null default '{}'::jsonb,
  idempotency_key text not null unique,
  routine_id uuid references public.routines (id) on delete set null,
  conversation_id uuid references public.conversations (id) on delete set null,
  scheduled_for timestamptz not null default now(),
  scheduled_tz text not null default 'UTC',
  lease_until timestamptz,
  leased_by text,
  checkpoint jsonb not null default '{}'::jsonb,
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 3 check (max_attempts >= 1),
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  check (state <> 'running' or lease_until is not null),
  check (leased_by is null or lease_until is not null)
);

comment on column public.jobs.idempotency_key is
  'Deduplicates routine/instrument/feature/confirmation-time combinations across restarts.';
comment on column public.jobs.checkpoint is
  'Per-stage outputs (snapshot ids, feature ids, evidence ids) so a run resumes after restart.';

-- Workers lease with: select ... where state in ('queued','partial') and scheduled_for <= now()
--   and (lease_until is null or lease_until < now()) order by priority desc, scheduled_for
--   for update skip locked limit 1
create index jobs_leasable_idx
  on public.jobs (priority desc, scheduled_for)
  where state in ('queued', 'partial');
create index jobs_running_lease_idx on public.jobs (lease_until) where state = 'running';
create index jobs_routine_idx on public.jobs (routine_id, created_at desc);

create trigger jobs_set_updated_at
  before update on public.jobs
  for each row execute function public.set_updated_at();

create or replace function public.jobs_enforce_transition()
returns trigger
language plpgsql
as $$
begin
  if old.state = new.state then
    return new;
  end if;
  if old.state in ('completed', 'failed', 'cancelled', 'budget_exceeded') then
    raise exception 'job % is terminal (%), cannot move to %', old.id, old.state, new.state
      using errcode = 'check_violation';
  end if;
  if old.state = 'queued' and new.state not in ('running', 'cancelled') then
    raise exception 'invalid job transition % -> %', old.state, new.state
      using errcode = 'check_violation';
  end if;
  if old.state = 'partial' and new.state not in
      ('running', 'completed', 'failed', 'cancelled', 'budget_exceeded') then
    raise exception 'invalid job transition % -> %', old.state, new.state
      using errcode = 'check_violation';
  end if;
  -- running may move to any non-running state, including back to queued on lease expiry.
  if new.state = 'running' and old.state <> 'running' then
    new.started_at := coalesce(new.started_at, now());
    new.attempts := old.attempts + 1;
  end if;
  if new.state in ('completed', 'failed', 'cancelled', 'budget_exceeded') then
    new.finished_at := coalesce(new.finished_at, now());
    new.lease_until := null;
    new.leased_by := null;
  end if;
  if new.state = 'queued' then
    new.lease_until := null;
    new.leased_by := null;
  end if;
  return new;
end;
$$;

create trigger jobs_enforce_transition
  before update of state on public.jobs
  for each row execute function public.jobs_enforce_transition();

create table public.runs (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs (id) on delete cascade,
  conversation_id uuid references public.conversations (id) on delete set null,
  artifact_revision_id uuid references public.artifact_revisions (id) on delete set null,
  status text not null default 'running' check (status in
    ('queued', 'running', 'partial', 'completed', 'failed', 'cancelled', 'budget_exceeded')),
  current_stage text check (current_stage in
    ('resolve_instrument', 'capture_snapshot', 'deterministic_ta', 'gather_context',
     'synthesize', 'critique', 'validate', 'repair', 'persist', 'notify')),
  stages_completed text[] not null default '{}',
  provider text not null,
  model text,
  prompt_version text,
  provenance text not null check (provenance in ('fixture', 'recorded', 'live')),
  usage jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  error text,
  created_at timestamptz not null default now(),
  unique (artifact_revision_id)         -- a run produces at most one artifact revision
);

create index runs_job_idx on public.runs (job_id, started_at desc);
create index runs_conversation_idx on public.runs (conversation_id, started_at desc);

alter table public.messages
  add constraint messages_run_fk foreign key (run_id) references public.runs (id) on delete set null;
alter table public.artifact_revisions
  add constraint artifact_revisions_run_fk foreign key (run_id) references public.runs (id) on delete set null;
alter table public.artifact_proposed_edits
  add constraint artifact_proposed_edits_run_fk foreign key (run_id) references public.runs (id) on delete set null;

create table public.run_events (
  id bigint generated always as identity primary key,
  run_id uuid not null references public.runs (id) on delete cascade,
  sequence integer not null check (sequence >= 0),
  at timestamptz not null default now(),
  stage text,
  level text not null default 'info' check (level in ('debug', 'info', 'warning', 'error')),
  message text not null,
  data jsonb not null default '{}'::jsonb,
  unique (run_id, sequence)
);

create table public.tool_calls (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.runs (id) on delete cascade,
  sequence integer not null check (sequence >= 0),
  tool_name text not null,
  tool_version text not null,
  arguments jsonb not null default '{}'::jsonb,
  output jsonb,
  is_error boolean not null default false,
  counts_as_external_retrieval boolean not null default false,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  duration_ms integer,
  created_at timestamptz not null default now(),
  unique (run_id, sequence),
  -- No tool may write broker orders, run shell commands or make unrestricted HTTP requests.
  check (tool_name !~* '(order|execute|submit|shell|exec|http_request)')
);

create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid,
  kind text not null check (kind in
    ('new_research', 'material_change', 'run_failed', 'budget', 'source_failure', 'import')),
  severity text not null default 'info' check (severity in ('info', 'warning', 'error')),
  title text not null,
  body text,
  run_id uuid references public.runs (id) on delete set null,
  artifact_id uuid references public.artifacts (id) on delete set null,
  dedupe_key text unique,
  read_at timestamptz,
  created_at timestamptz not null default now()
);

create index notifications_unread_idx on public.notifications (owner_id, created_at desc)
  where read_at is null;

-- Realtime: the web app subscribes to job/run/notification changes. The publication exists only
-- inside Supabase, so guard it for plain Postgres (CI).
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    alter publication supabase_realtime add table public.jobs, public.runs, public.notifications;
  end if;
end
$$;
