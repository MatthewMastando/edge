# Fixtures

Everything under this directory is **synthetic demonstration data**. It is generated
deterministically from a seed so that TA, persistence and UI code can be exercised without paid
market data or API keys. Every row and every manifest carries `provenance: fixture`.

| Path | Contents |
|---|---|
| `contracts/instruments.yaml` | Instruments, listed futures contracts (real specifications), roll-map examples and generator parameters |
| `session_calendars/*.yaml` | Versioned session definitions referenced by instruments and TA features |
| `recorded/` | Recorded LLM responses replayed by `RecordedProvider` (always labeled demonstration) |
| `ta/` | Hand-calculated TA expectations for Stage 1A. Do not put those next to the generator inputs |
| `generated/` | Output of the generator: Parquet bars/trades plus `manifest.json` (git-ignored) |

Generate:

```bash
uv run trading-core fixtures generate            # default seed, 10 session days
uv run trading-core fixtures generate --seed 7   # different but equally deterministic data set
uv run trading-core fixtures verify              # re-hash Parquet files against manifest.json
```

The `data_revision` in the manifest is derived from the generator version, the seed and a hash of
the YAML inputs. Same inputs always yield the same revision and the same rows.
