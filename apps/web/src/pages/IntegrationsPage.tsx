import { useState } from "react";

import { useCapabilities, useHealth, useSnapshots } from "../api/queries";
import { Modal } from "../components/Modal";
import { formatDecimal } from "../lib/provenance";
import { formatInstant } from "../lib/format";
import { useWorkspace } from "../workspace/useWorkspace";

const SOURCES = [
  { name: "Fixture generator", access: "Local synthetic bars and trades", state: "Connected" },
  { name: "Databento", access: "Futures definitions, OHLCV, trades", state: "Not configured" },
  { name: "Alpaca", access: "Equities and ETFs. IEX versus consolidated is unknown until connected.", state: "Not configured" },
  { name: "Coinbase", access: "Spot crypto public trades", state: "Not configured" },
  { name: "FRED", access: "Macro series", state: "Not configured" },
  { name: "SEC EDGAR", access: "Filings. Needs a User-Agent.", state: "Not configured" },
  { name: "EIA", access: "Energy inventories", state: "Not configured" },
  { name: "Web search", access: "Bounded retrieval", state: "Not configured" },
];

export function IntegrationsPage() {
  const health = useHealth();
  const capabilities = useCapabilities();
  const snapshots = useSnapshots();
  const { state } = useWorkspace();
  const [importOpen, setImportOpen] = useState(false);
  const latest = snapshots.data?.[0];
  const usage = state.runs.reduce(
    (sum, run) => ({
      input: sum.input + run.usage.input_tokens,
      output: sum.output + run.usage.output_tokens,
      calls: sum.calls + run.usage.retrieval_calls,
      cost: sum.cost + Number(run.usage.actual_cost_usd ?? 0),
    }),
    { input: 0, output: 0, calls: 0, cost: 0 },
  );

  return (
    <div className="page">
      <header className="page-head">
        <h2>Integrations</h2>
        <p className="hint">Connections, what they are allowed to do, and how fresh the fixture feed is.</p>
      </header>

      <section aria-labelledby="access">
        <h3 id="access">Permitted access</h3>
        <ul>
          <li>Read instruments, contracts, bars, snapshots, and saved research.</li>
          <li>Broker order submission, modification, and cancellation are not available.</li>
          <li>
            Health reports order-write capability{" "}
            <strong>{health.data ? String(health.data.order_write_capability) : "unknown"}</strong>.
          </li>
        </ul>
      </section>

      <section aria-labelledby="sources">
        <h3 id="sources">Source connections</h3>
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>Access</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {SOURCES.map((source) => (
              <tr key={source.name}>
                <td>{source.name}</td>
                <td>{source.access}</td>
                <td>
                  <span className={source.state === "Connected" ? "status-ok" : "status-idle"}>{source.state}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-labelledby="feed">
        <h3 id="feed">Feed coverage and delay</h3>
        <dl className="meta-grid">
          <div>
            <dt>Provider</dt>
            <dd>{capabilities.data?.provider ?? "fixture"}</dd>
          </div>
          <div>
            <dt>Trades for volume profile</dt>
            <dd>{capabilities.data?.has_trades ? "Yes, in the fixture" : "Unavailable"}</dd>
          </div>
          <div>
            <dt>Consolidated equities</dt>
            <dd>{capabilities.data?.consolidated_equities ? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt>Delay</dt>
            <dd>n/a — generated data has no exchange delay</dd>
          </div>
          <div>
            <dt>Coverage</dt>
            <dd>{capabilities.data?.coverage_note ?? "Loading coverage…"}</dd>
          </div>
          <div>
            <dt>Last refresh</dt>
            <dd>{latest ? `${formatInstant(latest.as_of)} · ${latest.contract_code ?? latest.instrument_id}` : "No snapshot"}</dd>
          </div>
        </dl>
        {capabilities.isError || snapshots.isError ? <p role="alert">Feed status could not be loaded from the API.</p> : null}
      </section>

      <section aria-labelledby="failures">
        <h3 id="failures">Failures</h3>
        <p>No refresh failures. Unconfigured sources are listed above and are not treated as empty data.</p>
      </section>

      <section aria-labelledby="usage">
        <h3 id="usage">Usage</h3>
        <dl className="meta-grid">
          <div>
            <dt>Input tokens</dt>
            <dd className="num">{usage.input}</dd>
          </div>
          <div>
            <dt>Output tokens</dt>
            <dd className="num">{usage.output}</dd>
          </div>
          <div>
            <dt>Retrieval calls</dt>
            <dd className="num">{usage.calls}</dd>
          </div>
          <div>
            <dt>Recorded cost</dt>
            <dd className="num">{formatDecimal(usage.cost.toFixed(2))} USD</dd>
          </div>
          <div>
            <dt>AI and search ceiling</dt>
            <dd>100 USD / month. Market-data spend is a separate budget. This shell does not meter live calls.</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="csv">
        <h3 id="csv">CSV import</h3>
        <p className="hint">Mapping presets, validation, and duplicate detection land with the analytics work. This entry point only previews a local file.</p>
        <button
          type="button"
          className="primary"
          onClick={() => {
            setImportOpen(true);
          }}
        >
          Import CSV
        </button>
      </section>
      {importOpen ? (
        <CsvPreview
          onClose={() => {
            setImportOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function CsvPreview({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState<string | null>(null);
  const [header, setHeader] = useState<string | null>(null);
  const [rows, setRows] = useState<number | null>(null);

  return (
    <Modal title="CSV import" onClose={onClose}>
      <p className="hint">Nothing is uploaded and no fills are written. Drop a file to see its name, header, and row count.</p>
      <input
        aria-label="CSV file"
        type="file"
        accept=".csv,text/csv"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          setName(file.name);
          void file.text().then((text) => {
            const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
            setHeader(lines[0] ?? "(empty file)");
            setRows(Math.max(0, lines.length - 1));
          });
        }}
      />
      {name ? (
        <dl className="meta-grid">
          <div>
            <dt>File</dt>
            <dd>{name}</dd>
          </div>
          <div>
            <dt>Header</dt>
            <dd>{header}</dd>
          </div>
          <div>
            <dt>Data rows</dt>
            <dd className="num">{rows ?? "…"}</dd>
          </div>
        </dl>
      ) : null}
    </Modal>
  );
}
