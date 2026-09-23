#!/usr/bin/env bash
# Run the Playwright fixture spec against the local API and worker.
# Requires Postgres, applied migrations, and generated fixtures. No paid credentials.
set -euo pipefail
set -m

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

export TRW_MODE=fixture
export LLM_PROVIDER=recorded
export VITE_USE_MSW=false
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:8000}"
unset OPENAI_API_KEY DATABENTO_API_KEY ALPACA_API_KEY_ID ALPACA_API_SECRET_KEY || true
unset TAVILY_API_KEY FRED_API_KEY EIA_API_KEY USDA_NASS_API_KEY || true
unset COINBASE_API_KEY COINBASE_API_SECRET SUPABASE_JWT_SECRET || true

log_dir="${TMPDIR:-/tmp}/trw-e2e"
mkdir -p "$log_dir"
api_log="$log_dir/api.log"
worker_log="$log_dir/worker.log"
web_log="$log_dir/web.log"

pids=()
cleanup() {
  local pid
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT

start_group() {
  local log=$1
  shift
  "$@" >"$log" 2>&1 &
  pids+=("$!")
}

wait_for() {
  local url=$1
  local log=$2
  local attempt
  for attempt in $(seq 1 90); do
    if curl -sf "$url" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "timed out waiting for $url" >&2
  tail -n 120 "$log" >&2 || true
  return 1
}

start_group "$api_log" uv run trading-api serve
start_group "$worker_log" uv run trading-worker
start_group "$web_log" pnpm --filter @trw/web dev

wait_for "http://127.0.0.1:8000/health" "$api_log"
wait_for "http://127.0.0.1:5173/" "$web_log"

set +e
pnpm --filter @trw/web test:e2e
status=$?
set -e
if [[ "$status" -ne 0 ]]; then
  echo "--- api ---" >&2
  tail -n 120 "$api_log" >&2 || true
  echo "--- worker ---" >&2
  tail -n 120 "$worker_log" >&2 || true
  echo "--- web ---" >&2
  tail -n 80 "$web_log" >&2 || true
  exit "$status"
fi
