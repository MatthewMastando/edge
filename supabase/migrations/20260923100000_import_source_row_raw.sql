-- Stage 4 (records): preserve original CSV cells per imported fill for source-row provenance.

alter table public.imported_fills
  add column if not exists source_row_raw jsonb;

comment on column public.imported_fills.source_row_raw is
  'Original CSV column values for this row (keys are file headers).';

-- Settlement / variation-margin cash. Kept out of imported_fills so FIFO on trades
-- cannot also book the same cash as a second realized result.
create table public.imported_cash_flows (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.import_batches (id) on delete cascade,
  source_row_number integer not null,
  source_row_hash text not null unique,
  instrument_id uuid references public.instruments (id) on delete set null,
  symbol_raw text not null,
  contract_code text,
  currency text not null,
  amount numeric not null,
  flow_time timestamptz not null,
  flow_tz text not null,
  flow_kind text not null check (flow_kind in ('settlement')),
  source_row_raw jsonb,
  created_at timestamptz not null default now()
);

create index imported_cash_flows_batch_idx
  on public.imported_cash_flows (batch_id, source_row_number);

comment on table public.imported_cash_flows is
  'Broker settlement cash from a mapped CSV. Excluded from FIFO realized P&L.';
