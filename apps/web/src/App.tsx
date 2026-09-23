import { useEffect, useState } from "react";

import { api } from "./api/client";
import type { FuturesContract, HealthResponse, Instrument } from "./api/types";
import { formatDecimal, provenanceLabel } from "./lib/provenance";

interface FoundationState {
  health: HealthResponse | null;
  instruments: Instrument[];
  contracts: FuturesContract[];
  error: string | null;
}

const initialState: FoundationState = { health: null, instruments: [], contracts: [], error: null };

export function App() {
  const [state, setState] = useState<FoundationState>(initialState);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const health = await api.GET("/health");
      if (!health.response.ok || health.data === undefined) {
        throw new Error("API unreachable");
      }
      const [instruments, contracts] = await Promise.all([
        api.GET("/v1/instruments"),
        api.GET("/v1/futures-contracts"),
      ]);
      if (cancelled) return;
      setState({
        health: health.data,
        instruments: instruments.data ?? [],
        contracts: contracts.data ?? [],
        error: instruments.response.ok ? null : "Fixture data not generated (see README)",
      });
    }
    load().catch((err: unknown) => {
      if (!cancelled) {
        setState({ ...initialState, error: err instanceof Error ? err.message : String(err) });
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const label = state.health ? provenanceLabel(state.health.provenance) : null;

  return (
    <main className="shell">
      <h1>Trading Research Workspace</h1>
      <p className="muted">
        Stage 0 foundation. Research only — this application has no broker order-write capability.
      </p>
      {label?.isDemonstration ? <div className="banner">{label.text}</div> : null}

      <section className="panel" aria-labelledby="api-status">
        <h2 id="api-status">API</h2>
        {state.error ? <p role="alert">{state.error}</p> : null}
        {state.health ? (
          <p>
            <code>{state.health.service}</code> {state.health.version} · mode{" "}
            <code>{state.health.mode}</code> · data revision{" "}
            <code>{state.health.data_revision ?? "none"}</code>
          </p>
        ) : (
          <p className="muted">Connecting…</p>
        )}
      </section>

      <section className="panel" aria-labelledby="contracts">
        <h2 id="contracts">Listed futures contracts (fixture)</h2>
        <table>
          <thead>
            <tr>
              <th>Contract</th>
              <th>Exchange</th>
              <th>Expiry</th>
              <th>Last trade</th>
              <th>Tick</th>
              <th>Tick value</th>
              <th>Multiplier</th>
              <th>Settlement</th>
            </tr>
          </thead>
          <tbody>
            {state.contracts.map((c) => (
              <tr key={c.id}>
                <td>
                  <code>{c.contract_code}</code>
                </td>
                <td>{c.exchange}</td>
                <td>{c.expiry_date}</td>
                <td>{c.last_trade_date}</td>
                <td>{formatDecimal(c.tick_size)}</td>
                <td>
                  {formatDecimal(c.tick_value)} {c.currency}
                </td>
                <td>{formatDecimal(c.point_multiplier)}</td>
                <td>{c.settlement_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel" aria-labelledby="instruments">
        <h2 id="instruments">Instruments</h2>
        <ul>
          {state.instruments.map((i) => (
            <li key={i.id}>
              <code>{i.symbol}</code> — {i.name} · {i.asset_class} · {i.venue}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
