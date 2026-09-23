-- Stage 4 automation: TA-trigger decisions and the hypothesis ledger.
-- New file only; earlier migrations stay as applied history.

create table public.trigger_decisions (
  id uuid primary key default gen_random_uuid(),
  routine_id uuid not null references public.routines (id) on delete cascade,
  event_id uuid not null references public.ta_events (id) on delete cascade,
  instrument_id uuid not null references public.instruments (id) on delete cascade,
  detector text not null,
  confirmation_time timestamptz not null,
  decision text not null check (decision in
    ('enqueued', 'cooldown', 'daily_cap', 'allowlist', 'closed_market')),
  job_id uuid references public.jobs (id) on delete set null,
  created_at timestamptz not null default now(),
  unique (routine_id, event_id)
);

comment on table public.trigger_decisions is
  'One row per confirmed TA event considered by a routine. Research jobs are the enqueued subset.';

create index trigger_decisions_cooldown_idx
  on public.trigger_decisions (routine_id, instrument_id, detector, confirmation_time desc)
  where decision = 'enqueued';

create index trigger_decisions_daily_idx
  on public.trigger_decisions (routine_id, created_at)
  where decision = 'enqueued';

alter table public.hypotheses
  add column entry_state text not null default 'untriggered'
    check (entry_state in ('triggered', 'untriggered')),
  add column subsequent_move numeric,
  add column simulated_pnl numeric,
  add column simulated_pnl_currency text,
  add column pnl_label text not null default 'simulated'
    check (pnl_label = 'simulated');

comment on column public.hypotheses.simulated_pnl is
  'Hypothetical P&L from explicit fill, exit and cost assumptions. Never a real fill.';
comment on column public.hypotheses.pnl_label is
  'Always simulated. Real fills stay in imported_fills.';

create unique index hypotheses_revision_uidx on public.hypotheses (artifact_revision_id);

create unique index hypothesis_observations_revision_uidx
  on public.hypothesis_observations (hypothesis_id, event, data_revision);
