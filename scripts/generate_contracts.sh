#!/usr/bin/env bash
# Regenerate the shared contracts:
#   Pydantic models -> contracts/openapi.json -> apps/web/src/api/schema.d.ts
# Run from anywhere after changing trading_core.domain or API routes. OPENAPI_OUT / TS_OUT may be
# relative to the repository root or absolute (the check script uses a temp directory).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

abs() { case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s/%s\n' "$ROOT" "$1" ;; esac; }

OPENAPI_OUT="$(abs "${OPENAPI_OUT:-contracts/openapi.json}")"
TS_OUT="$(abs "${TS_OUT:-apps/web/src/api/schema.d.ts}")"

# Export must not depend on generated fixture data or a database.
TRW_FIXTURES_ROOT="${TRW_FIXTURES_ROOT:-/nonexistent}" \
  uv run --quiet trading-api export-openapi --out "$OPENAPI_OUT" >/dev/null

pnpm --silent --filter @trw/web exec openapi-typescript "$OPENAPI_OUT" \
  -o "$TS_OUT" --alphabetize --export-type >/dev/null

echo "wrote $OPENAPI_OUT and $TS_OUT"
