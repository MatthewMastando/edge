# Trading Research Workspace

Private, single-user trading research application: an agent harness that runs deterministic
technical analysis, gathers sourced market context, writes validated theses and revisits them on
schedules and TA triggers. **Research only — there is no broker order-write capability anywhere in
this repository, and CI enforces that.**

This is the Stage 0 foundation: monorepo, database schema, shared contracts, fixture data, local
startup and CI. Stage 1 builds the TA library, the harness/persistence layer and the web app on top.

## Layout

| Path | Contents |
|---|---|
| `apps/web` | React 18 + Vite + TypeScript app (pnpm). Typed API client from generated OpenAPI types |
| `services/api` | FastAPI service (`trading-api`). Owns every write; `/health`, `/openapi.json`, fixture market routes |
| `services/worker` | Worker process (`trading-worker`). Leases durable jobs from Postgres |
| `packages/trading_core` | Shared Python library: `domain`, `data`, `ta`, `research`, `harness`, `storage`, `fixtures` |
| `supabase/` | `config.toml` for `supabase start`, SQL migrations, seed |
| `fixtures/` | Contract definitions, session calendars, recorded model responses, generated Parquet (git-ignored) |
| `contracts/openapi.json` | Committed OpenAPI document; source of `apps/web/src/api/schema.d.ts` |
| `tests/` | pytest unit and smoke tests (`tests/smoke/test_migrations.py` needs Postgres) |
| `scripts/` | Migration runner for plain Postgres, contract generation and check |

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node 22 and pnpm 10 (`corepack enable`)
- Docker and the [Supabase CLI](https://supabase.com/docs/guides/cli) for `supabase start`
  (alternatively any Postgres 15+ and `scripts/apply_migrations.py`)

## Local startup

```bash
# 1. Install everything
uv sync --all-packages
pnpm install
cp .env.example .env            # defaults match `supabase start`; never commit .env

# 2. Start Postgres, Auth, Storage, Realtime and Studio
supabase start                  # prints API URL, anon key, service-role key, JWT secret
#   copy SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY / SUPABASE_JWT_SECRET into .env
#   Studio: http://127.0.0.1:54323   Postgres: postgresql://postgres:postgres@127.0.0.1:54322/postgres

# 3. Apply migrations (either)
supabase db reset               # drops, re-applies supabase/migrations/*.sql and seed.sql
uv run python scripts/apply_migrations.py --seed     # idempotent runner for plain Postgres / CI

# 4. Generate labeled fixture data (Parquet + manifest under fixtures/generated/)
uv run trading-core fixtures generate
uv run trading-core fixtures verify

# 5. Run the services (separate terminals)
uv run trading-api serve --reload        # http://127.0.0.1:8000  (/health, /docs, /openapi.json)
uv run trading-worker                    # add --once to poll a single time and exit
pnpm dev                                 # http://127.0.0.1:5173
```

Everything binds to localhost. In fixture mode with no `SUPABASE_JWT_SECRET` the API serves a
local development user; any other configuration refuses unauthenticated requests until JWT
verification lands in Stage 1B.

## Tests and checks

```bash
uv run ruff check && uv run ruff format --check     # lint + formatting
uv run mypy                                         # strict type checking (packages, services, tests, scripts)
uv run pytest                                       # unit + smoke tests
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run pytest tests/smoke   # includes migrations on a fresh DB
pnpm typecheck && pnpm lint && pnpm test            # web
pnpm contracts:check                                # committed OpenAPI + TS types match the Python models
```

The migration smoke test creates and drops a throwaway database, so `DATABASE_URL` must have
`CREATEDB` rights (the local Supabase `postgres` role does). Without `DATABASE_URL` it is skipped.

## Shared contracts

Pydantic v2 models in `trading_core.domain` are the single source of truth. They are published in
`/openapi.json` (every model in `CONTRACT_MODELS`, not only those a route returns) and generated
into TypeScript with `openapi-typescript`:

```bash
pnpm contracts:generate     # trading-api export-openapi -> contracts/openapi.json -> apps/web/src/api/schema.d.ts
pnpm contracts:check        # CI fails if the committed files are stale
```

Conventions: exact decimals are strings in JSON (`format: decimal`) and `numeric` in SQL; every
timestamp is UTC with an original-timezone column beside it; every object carries `provenance`
(`fixture`, `recorded`, `live`) and anything not live is labeled in the UI.

## Fixture data

`fixtures/contracts/instruments.yaml` defines 6E, GC, CL, ES roots with the listed contracts
**6EZ6, GCZ6, CLX6, ESZ6** (real tick sizes/values, multipliers, expiry, last-trade and notice
dates, settlement type, session calendar), plus **SPY** and **BTC-USD**. The generator produces
seeded, tick-aligned trade prints and aggregates 5-minute OHLCV bars from them so bars and
volume-at-price are always consistent. Output is Parquet through the same `LocalParquetStore` the
services use, plus `manifest.json` with a `data_revision`, content hashes and a fixture label.

```bash
uv run trading-core fixtures generate --seed 7 --days 5 --start 2026-08-31
uv run trading-core fixtures show
```

## Database conventions

- Timestamps: `timestamptz` (UTC) plus `*_tz` text for the original zone on user-facing instants.
- Money, prices, sizes: `numeric`. No floats anywhere in the schema (tested).
- `jobs.state` machine `queued → running → {partial, completed, failed, cancelled,
  budget_exceeded}` with `running → queued` on lease expiry, enforced by a trigger; leases via
  `lease_until`/`leased_by`, resumable `checkpoint`, unique `idempotency_key`.
- `ta_events` unique on `(instrument_id, contract_code, timeframe, detector, calc_version,
  origin_time, data_revision)` so re-detection is idempotent and later bars never rewrite an
  earlier log. Post-confirmation lifecycle (touch, fill, invalidation) goes to
  `ta_feature_transitions`.
- `tool_calls.tool_name` rejects order/shell/exec/http_request names at the database level.

## Environment variables

See [.env.example](.env.example); every variable read by the API, worker, web app and tooling is
listed there with its default. Provider credentials (Databento, Alpaca, OpenAI, Tavily, FRED, EIA,
NASS) are empty until Stage 3 and are never required for the fixture path or CI.

## Stage plan

See the implementation plan for the staged delivery: Stage 1A TA library, 1B persistence/harness/
API routes, 1C web app; Stage 2 vertical slice; Stage 3 live adapters and research; Stage 4
automation and analytics.
