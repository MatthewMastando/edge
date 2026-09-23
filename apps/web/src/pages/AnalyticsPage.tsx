import { useState } from "react";

import { useImportedFills, useTradingSummary } from "../api/queries";
import { formatInstant, stanceLabel } from "../lib/format";
import { formatDecimal, provenanceLabel } from "../lib/provenance";
import { useWorkspace } from "../workspace/useWorkspace";

type Panel = "trading" | "outcomes" | "agent";

const FAMILIES = [
  { id: "", label: "All families" },
  { id: "fx_futures", label: "FX futures" },
  { id: "metals_futures", label: "Metals futures" },
  { id: "commodity_futures", label: "Commodity futures" },
  { id: "index_futures", label: "Index futures" },
  { id: "equity", label: "Equities" },
  { id: "etf", label: "ETFs" },
  { id: "crypto_spot", label: "Spot crypto" },
];

export function AnalyticsPage() {
  const { state } = useWorkspace();
  const [panel, setPanel] = useState<Panel>("trading");
  return (
    <div className="page">
      <header className="page-head">
        <h2>Analytics</h2>
        <div className="subnav" role="tablist" aria-label="Analytics">
          <Tab id="trading" current={panel} onSelect={setPanel} label="My Trading" />
          <Tab id="outcomes" current={panel} onSelect={setPanel} label="Research Outcomes" />
          <Tab id="agent" current={panel} onSelect={setPanel} label="Agent Trading" />
        </div>
      </header>
      {panel === "trading" ? <MyTrading /> : null}
      {panel === "outcomes" ? <Outcomes /> : null}
      {panel === "agent" ? <AgentTrading /> : null}
      <p className="sr-only">{state.artifacts.length} artifacts in the workspace</p>
    </div>
  );
}

function Tab({
  id,
  label,
  current,
  onSelect,
}: {
  id: Panel;
  label: string;
  current: Panel;
  onSelect: (panel: Panel) => void;
}) {
  return (
    <button type="button" role="tab" aria-selected={current === id} className={current === id ? "is-selected" : ""} onClick={() => { onSelect(id); }}>
      {label}
    </button>
  );
}

function MyTrading() {
  const [family, setFamily] = useState("");
  const assetClass = family.length > 0 ? family : null;
  const fills = useImportedFills(assetClass);
  const summary = useTradingSummary(assetClass);

  return (
    <section aria-labelledby="my-trading">
      <h3 id="my-trading">My Trading</h3>
      <p className="hint">
        Reconciled realized P&amp;L and fees from imported fills. Incomplete rows are excluded from trusted totals. Portfolio return is not shown without balances and cash flows.
      </p>

      <div className="field-row">
        <label htmlFor="family-filter">Instrument family</label>
        <select
          id="family-filter"
          value={family}
          onChange={(e) => {
            setFamily(e.target.value);
          }}
        >
          {FAMILIES.map((f) => (
            <option key={f.id || "all"} value={f.id}>{f.label}</option>
          ))}
        </select>
      </div>

      {summary.data ? (
        <dl className="meta-grid summary-strip">
          <div>
            <dt>Realized P&amp;L</dt>
            <dd className="num">{formatDecimal(summary.data.total_realized_pnl)}</dd>
          </div>
          <div>
            <dt>Fees</dt>
            <dd className="num">{formatDecimal(summary.data.total_fees)}</dd>
          </div>
          <div>
            <dt>Net</dt>
            <dd className="num">{formatDecimal(summary.data.total_net_pnl)}</dd>
          </div>
          <div>
            <dt>Trusted fills</dt>
            <dd className="num">{summary.data.trusted_fill_count}</dd>
          </div>
          {summary.data.incomplete_fill_count > 0 ? (
            <div>
              <dt>Incomplete (excluded)</dt>
              <dd className="num">{summary.data.incomplete_fill_count}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}

      {summary.data && !summary.data.portfolio_return_available ? (
        <p className="hint">Portfolio return unavailable — import account snapshots with cash flows to enable that view later.</p>
      ) : null}

      <table>
        <thead>
          <tr>
            <th>Instrument</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Price</th>
            <th>Fees</th>
            <th>When</th>
            <th>Source row</th>
          </tr>
        </thead>
        <tbody>
          {fills.isLoading ? (
            <tr><td colSpan={7}>Loading…</td></tr>
          ) : null}
          {fills.data && fills.data.length === 0 ? (
            <tr><td colSpan={7}>No fills. Import CSV under Integrations.</td></tr>
          ) : null}
          {fills.data?.map((fill) => (
            <tr key={fill.id} className={fill.is_complete ? "" : "row-flagged"}>
              <td>
                {fill.instrument_symbol ?? fill.symbol_raw}
                {fill.contract_code ? ` ${fill.contract_code}` : ""}
                {!fill.is_complete ? " (incomplete)" : ""}
              </td>
              <td>{fill.side}</td>
              <td className="num">{formatDecimal(fill.quantity)}</td>
              <td className="num">{formatDecimal(fill.price)}</td>
              <td className="num">{formatDecimal(fill.fees)}</td>
              <td>{formatInstant(fill.fill_time)}</td>
              <td className="num">{fill.source_row_number}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Outcomes() {
  const { state } = useWorkspace();
  const frozen = state.revisions;
  return (
    <section aria-labelledby="outcomes">
      <h3 id="outcomes">Research Outcomes</h3>
      <p className="hint">
        Each row is a frozen revision. Simulated P&amp;L is not computed here and would be labeled separately from real fills. The TA tools are not a strategy.
      </p>
      <ul className="artifact-list">
        {frozen.map((revision) => {
          const artifact = state.artifacts.find((item) => item.id === revision.artifactId);
          if (!artifact) return null;
          const label = provenanceLabel(revision.provenance);
          const triggered = revision.structured.entry !== "";
          return (
            <li key={revision.id}>
              <div>
                <strong>
                  {artifact.thesis.symbol}
                  {artifact.thesis.contract_code ? ` ${artifact.thesis.contract_code}` : ""} · revision {revision.revisionNumber}
                </strong>
                {label.isDemonstration ? <div className="banner banner-inline">{label.text}</div> : null}
                <p className="hint">
                  {stanceLabel(revision.structured.stance)} · {triggered ? "entry set" : "untriggered"} · invalidation{" "}
                  {revision.structured.invalidation || "unset"} · frozen {formatInstant(revision.createdAt)}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function AgentTrading() {
  return (
    <section className="empty-state" aria-labelledby="agent-trading">
      <h3 id="agent-trading">Agent Trading</h3>
      <p>Execution comes in V1. This workspace researches and records. It does not submit, modify, or cancel orders.</p>
    </section>
  );
}
