import { stanceLabel } from "../lib/format";
import type { ProposalRecord, StructuredDraft } from "../workspace/types";

function levelLine(label: string, before: string, after: string) {
  if (before === after) return null;
  return (
    <li>
      {label}: {before || "unset"} → {after || "unset"}
    </li>
  );
}

export function ProposalCard({
  proposal,
  current,
  onAccept,
  onReject,
}: {
  proposal: ProposalRecord;
  current: StructuredDraft;
  onAccept: () => void;
  onReject: () => void;
}) {
  if (proposal.status !== "pending") {
    return (
      <p className="proposal-state" role="status">
        Proposal {proposal.status}.
      </p>
    );
  }
  const next = proposal.structured;
  return (
    <section className="proposal" aria-label="Agent proposal">
      <header>
        <h3>Agent proposal</h3>
        <p>{proposal.summary}</p>
      </header>
      <ul className="proposal-diff">
        {current.stance === next.stance ? null : (
          <li>
            Stance: {stanceLabel(current.stance)} → {stanceLabel(next.stance)}
          </li>
        )}
        {levelLine("Entry", current.entry, next.entry)}
        {levelLine("Invalidation", current.invalidation, next.invalidation)}
        {levelLine("Target", current.target, next.target)}
        {levelLine("Contracts", current.contracts, next.contracts)}
        {levelLine("Estimated costs", current.estimatedCosts, next.estimatedCosts)}
        <li>Narrative gains the agent’s caution. Accepting writes an immutable revision.</li>
      </ul>
      <div className="row-actions">
        <button type="button" className="primary" onClick={onAccept}>
          Accept proposal
        </button>
        <button type="button" onClick={onReject}>
          Reject proposal
        </button>
      </div>
    </section>
  );
}
