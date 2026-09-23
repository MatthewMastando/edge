-- Market reference data, snapshots and deterministic TA records.

create table public.session_calendars (
  id text not null,
  version text not null check (version ~ '^\d+\.\d+\.\d+$'),
  name text not null,
  timezone text not null,
  exchange_calendar_code text,
  always_open boolean not null default false,
  definition jsonb not null,            -- SessionCalendar contract: trading_days, windows, holidays
  notes text,
  created_at timestamptz not null default now(),
  primary key (id, version)
);

comment on table public.session_calendars is
  'Versioned session definitions. Features and snapshots reference (id, version).';

create table public.instruments (
  id uuid primary key default gen_random_uuid(),
  symbol text not null,
  name text not null,
  asset_class text not null check (asset_class in
    ('futures', 'equity', 'etf', 'crypto_spot', 'crypto_futures', 'event_contract')),
  venue text not null,
  currency text not null,
  tick_size numeric not null check (tick_size > 0),
  tick_value numeric not null check (tick_value >= 0),
  multiplier numeric not null check (multiplier > 0),
  session_calendar_id text not null,
  base_asset text,
  quote_asset text,
  is_continuous boolean not null default false,
  provenance text not null default 'live' check (provenance in ('fixture', 'recorded', 'live')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (symbol, venue)
);

create trigger instruments_set_updated_at
  before update on public.instruments
  for each row execute function public.set_updated_at();

create table public.futures_contracts (
  id uuid primary key default gen_random_uuid(),
  instrument_id uuid not null references public.instruments (id) on delete cascade,
  root text not null,
  contract_code text not null unique,
  exchange text not null,
  contract_month text not null check (contract_month ~ '^\d{4}-\d{2}$'),
  expiry_date date not null,
  last_trade_date date not null,
  first_notice_date date,
  tick_size numeric not null check (tick_size > 0),
  tick_value numeric not null check (tick_value >= 0),
  point_multiplier numeric not null check (point_multiplier > 0),
  currency text not null,
  session_calendar_id text not null,
  settlement_type text not null check (settlement_type in ('cash', 'physical')),
  settlement_time_local time,
  is_active boolean not null default true,
  provenance text not null default 'live' check (provenance in ('fixture', 'recorded', 'live')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index futures_contracts_instrument_idx on public.futures_contracts (instrument_id, expiry_date);

create trigger futures_contracts_set_updated_at
  before update on public.futures_contracts
  for each row execute function public.set_updated_at();

create table public.roll_maps (
  id uuid primary key default gen_random_uuid(),
  instrument_id uuid not null references public.instruments (id) on delete cascade,
  root text not null,
  from_contract_code text not null,
  to_contract_code text not null,
  roll_date date not null,
  method text not null check (method in
    ('none', 'back_adjust_difference', 'back_adjust_ratio', 'calendar')),
  adjustment numeric,
  provenance text not null default 'live' check (provenance in ('fixture', 'recorded', 'live')),
  created_at timestamptz not null default now(),
  unique (instrument_id, from_contract_code, to_contract_code)
);

create table public.watchlists (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid,                        -- auth.users id; no FK so migrations run on plain Postgres
  name text not null,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger watchlists_set_updated_at
  before update on public.watchlists
  for each row execute function public.set_updated_at();

create table public.watchlist_items (
  id uuid primary key default gen_random_uuid(),
  watchlist_id uuid not null references public.watchlists (id) on delete cascade,
  instrument_id uuid not null references public.instruments (id) on delete cascade,
  contract_code text,
  position integer not null default 0,
  created_at timestamptz not null default now(),
  unique nulls not distinct (watchlist_id, instrument_id, contract_code)
);

create table public.market_snapshots (
  id uuid primary key default gen_random_uuid(),
  instrument_id uuid not null references public.instruments (id) on delete cascade,
  contract_code text,
  timeframe text check (timeframe in ('1m', '5m', '15m', '1h', '4h', '1d')),
  kind text not null check (kind in ('bars', 'trades')),
  range_start timestamptz not null,
  range_end timestamptz not null,
  as_of timestamptz not null,
  as_of_tz text not null default 'UTC',
  provider text not null,
  provenance text not null check (provenance in ('fixture', 'recorded', 'live')),
  data_revision text not null,
  storage_backend text not null check (storage_backend in ('local', 'supabase')),
  storage_key text not null unique,
  row_count integer not null check (row_count >= 0),
  content_hash text not null,
  coverage_note text,
  created_at timestamptz not null default now(),
  check (range_end >= range_start)
);

create index market_snapshots_instrument_idx
  on public.market_snapshots (instrument_id, kind, data_revision);

create table public.ta_features (
  id uuid primary key default gen_random_uuid(),
  detector text not null,
  calc_version text not null check (calc_version ~ '^\d+\.\d+\.\d+$'),
  instrument_id uuid not null references public.instruments (id) on delete cascade,
  contract_code text,
  timeframe text not null check (timeframe in ('1m', '5m', '15m', '1h', '4h', '1d')),
  session text not null,
  session_calendar_id text not null,
  session_calendar_version text not null,
  direction text not null check (direction in ('bullish', 'bearish', 'neutral')),
  state text not null check (state in
    ('pending', 'confirmed', 'touched', 'midpoint_touched', 'partially_filled', 'filled',
     'revisited', 'consumed', 'invalidated', 'expired')),
  origin_time timestamptz not null,
  origin_tz text not null,
  confirmation_time timestamptz,
  as_of timestamptz not null,
  levels jsonb not null default '[]'::jsonb,
  parameters jsonb not null default '{}'::jsonb,
  details jsonb not null default '{}'::jsonb,
  warnings jsonb not null default '[]'::jsonb,
  snapshot_id uuid not null references public.market_snapshots (id) on delete restrict,
  data_revision text not null,
  provenance text not null check (provenance in ('fixture', 'recorded', 'live')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (confirmation_time is null or confirmation_time >= origin_time)
);

create index ta_features_lookup_idx
  on public.ta_features (instrument_id, timeframe, detector, origin_time desc);
create index ta_features_revision_idx on public.ta_features (data_revision);

create trigger ta_features_set_updated_at
  before update on public.ta_features
  for each row execute function public.set_updated_at();

-- One row per detected feature per data revision. Re-running a detector on the same revision is
-- idempotent; later bars cannot rewrite an earlier log. Lifecycle changes after confirmation
-- (touch, fill, invalidation) are recorded in ta_feature_transitions.
create table public.ta_events (
  id uuid primary key default gen_random_uuid(),
  feature_id uuid not null references public.ta_features (id) on delete cascade,
  instrument_id uuid not null references public.instruments (id) on delete cascade,
  contract_code text,
  timeframe text not null check (timeframe in ('1m', '5m', '15m', '1h', '4h', '1d')),
  detector text not null,
  calc_version text not null check (calc_version ~ '^\d+\.\d+\.\d+$'),
  origin_time timestamptz not null,
  data_revision text not null,
  event_type text not null default 'confirmed' check (event_type in
    ('confirmed', 'touched', 'midpoint_touched', 'filled', 'revisited', 'consumed',
     'invalidated', 'expired')),
  event_time timestamptz not null,
  event_tz text not null,
  direction text not null check (direction in ('bullish', 'bearish', 'neutral')),
  levels jsonb not null default '[]'::jsonb,
  details jsonb not null default '{}'::jsonb,
  provenance text not null check (provenance in ('fixture', 'recorded', 'live')),
  created_at timestamptz not null default now(),
  constraint ta_events_idempotent_key unique nulls not distinct
    (instrument_id, contract_code, timeframe, detector, calc_version, origin_time, data_revision)
);

create index ta_events_feature_idx on public.ta_events (feature_id);
create index ta_events_recent_idx on public.ta_events (instrument_id, event_time desc);

create table public.ta_feature_transitions (
  id bigint generated always as identity primary key,
  feature_id uuid not null references public.ta_features (id) on delete cascade,
  from_state text not null,
  to_state text not null,
  bar_time timestamptz not null,        -- close time of the completed bar that caused the change
  data_revision text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (feature_id, to_state, bar_time, data_revision)
);
