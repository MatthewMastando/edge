-- Hypothesis ledger, personal trading history, usage, budgets and settings.

create table public.hypotheses (
  id uuid primary key default gen_random_uuid(),
  artifact_revision_id uuid not null references public.artifact_revisions (id) on delete cascade,
  instrument_id uuid not null references public.instruments (id) on delete cascade,
  contract_code text,
  stance text not null check (stance in ('bullish', 'bearish', 'neutral', 'insufficient_evidence')),
  entry numeric,
  invalidation numeric,
  target numeric,
  horizon text not null,
  frozen_at timestamptz not null default now(),
  expires_at timestamptz,
  status text not null default 'open' check (status in
    ('open', 'triggered', 'invalidated', 'target_hit', 'expired', 'untriggered')),
  assumptions jsonb not null default '{}'::jsonb,   -- fill/exit/cost assumptions for simulated P&L
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.hypotheses is 'Frozen theses tracked for Research Outcomes; references an immutable revision.';

create index hypotheses_status_idx on public.hypotheses (status, expires_at);
create index hypotheses_instrument_idx on public.hypotheses (instrument_id, frozen_at desc);

create trigger hypotheses_set_updated_at
  before update on public.hypotheses
  for each row execute function public.set_updated_at();

create table public.hypothesis_observations (
  id uuid primary key default gen_random_uuid(),
  hypothesis_id uuid not null references public.hypotheses (id) on delete cascade,
  observed_at timestamptz not null,
  observed_tz text not null default 'UTC',
  price numeric not null,
  event text not null check (event in
    ('checkpoint', 'entry_triggered', 'invalidation_hit', 'target_hit', 'expired')),
  data_revision text not null,
  note text,
  created_at timestamptz not null default now()
);

create index hypothesis_observations_idx on public.hypothesis_observations (hypothesis_id, observed_at);

create table public.import_batches (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid,
  source text not null default 'csv',
  filename text not null,
  mapping_preset jsonb not null,        -- column mapping used (saved presets live in settings)
  row_count integer not null default 0,
  imported_count integer not null default 0,
  duplicate_count integer not null default 0,
  error_count integer not null default 0,
  status text not null default 'pending' check (status in ('pending', 'previewed', 'imported', 'failed')),
  created_at timestamptz not null default now()
);

create table public.imported_fills (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.import_batches (id) on delete cascade,
  source_row_number integer not null,
  source_row_hash text not null unique,  -- duplicate detection across re-imports
  instrument_id uuid references public.instruments (id) on delete set null,
  symbol_raw text not null,
  contract_code text,
  side text not null check (side in ('buy', 'sell')),
  quantity numeric not null check (quantity > 0),
  price numeric not null,
  fees numeric not null default 0,
  currency text not null,
  fill_time timestamptz not null,
  fill_tz text not null,
  venue text,
  multiplier numeric,                   -- contract multiplier at import time for futures P&L
  is_complete boolean not null default true,
  notes text,
  created_at timestamptz not null default now()
);

create index imported_fills_instrument_idx on public.imported_fills (instrument_id, fill_time);
create index imported_fills_batch_idx on public.imported_fills (batch_id, source_row_number);

create table public.account_snapshots (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid,
  as_of timestamptz not null,
  as_of_tz text not null,
  source text not null,
  currency text not null,
  cash_balance numeric,
  equity numeric,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index account_snapshots_idx on public.account_snapshots (owner_id, as_of desc);

create table public.usage_ledger (
  id bigint generated always as identity primary key,
  run_id uuid references public.runs (id) on delete set null,
  job_id uuid references public.jobs (id) on delete set null,
  category text not null check (category in ('llm', 'search', 'fetch', 'market_data', 'source')),
  provider text not null,
  units numeric not null default 0,
  unit_type text not null,              -- tokens, calls, bytes, records
  reserved_cost_usd numeric not null default 0,
  actual_cost_usd numeric,
  occurred_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index usage_ledger_period_idx on public.usage_ledger (category, occurred_at);
create index usage_ledger_run_idx on public.usage_ledger (run_id);

create table public.budgets (
  id uuid primary key default gen_random_uuid(),
  category text not null check (category in ('ai_search', 'market_data')),
  period text not null default 'monthly' check (period in ('monthly')),
  period_start date not null,
  limit_usd numeric not null check (limit_usd >= 0),
  alert_threshold_pct integer not null default 80 check (alert_threshold_pct between 0 and 100),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (category, period_start)
);

create trigger budgets_set_updated_at
  before update on public.budgets
  for each row execute function public.set_updated_at();

create table public.settings (
  key text primary key,
  value jsonb not null,
  description text,
  updated_at timestamptz not null default now()
);

comment on table public.settings is
  'Non-secret server settings (model name, display timezone, mapping presets). Secrets stay in environment variables.';

create trigger settings_set_updated_at
  before update on public.settings
  for each row execute function public.set_updated_at();
