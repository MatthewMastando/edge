import { useState } from "react";

import { formatInstant, stanceLabel } from "../lib/format";
import { provenanceLabel } from "../lib/provenance";
import { useWorkspace } from "../workspace/useWorkspace";

type Panel = "trading" | "outcomes" | "agent";

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
  return (
    <section aria-labelledby="my-trading">
      <h3 id="my-trading">My Trading</h3>
      <p className="hint">
        No imported fills. CSV import starts under Integrations. Incomplete history is excluded from trusted totals, and this view will not fabricate portfolio returns without balances and cash flows.
      </p>
      <table>
        <thead>
          <tr>
            <th>Instrument</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Price</th>
            <th>Fees</th>
            <th>When</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colSpan={6}>No fills.</td>
          </tr>
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
