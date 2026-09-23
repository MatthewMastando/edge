#!/usr/bin/env bash
# CI check: the committed OpenAPI document and TypeScript types must match the Python models.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

OPENAPI_OUT="$TMP/openapi.json" TS_OUT="$TMP/schema.d.ts" bash scripts/generate_contracts.sh >/dev/null

status=0
if ! diff -u contracts/openapi.json "$TMP/openapi.json"; then
  echo "::error::contracts/openapi.json is out of date" >&2
  status=1
fi
if ! diff -u apps/web/src/api/schema.d.ts "$TMP/schema.d.ts"; then
  echo "::error::apps/web/src/api/schema.d.ts is out of date" >&2
  status=1
fi

if [ "$status" -ne 0 ]; then
  echo "Run: pnpm contracts:generate  (then commit the result)" >&2
  exit 1
fi
echo "contracts are current"
