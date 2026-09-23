import { useCallback, useState } from "react";

import { useBars, useCapabilities, useInstruments } from "../api/queries";
import { CandleChart } from "../charts/CandleChart";
import { ResultMeta } from "../charts/ResultMeta";
import { formatInstant, stanceLabel } from "../lib/format";
import { provenanceLabel } from "../lib/provenance";
import { changeKindFor } from "../workspace/draft";
import { useWorkspace } from "../workspace/useWorkspace";
import type { ArtifactRecord, DraftRecord, RevisionRecord } from "../workspace/types";
import { downloadMarkdown, thesisToMarkdown } from "./exportMarkdown";
import { NarrativeEditor } from "./NarrativeEditor";
import { ProposalCard } from "./ProposalCard";
import { StructuredBlock } from "./StructuredBlock";

function draftStatusLabel(draft: DraftRecord): string {
  if (draft.saveState === "pending") return "Saving draft";
  if (draft.saveState === "saved") return "Draft saved";
  return "Draft";
}

export function ThesisCanvas() {
  const { state } = useWorkspace();
  const artifact = state.artifacts.find((item) => item.id === state.selectedArtifactId) ?? null;
  const draft = artifact ? state.drafts[artifact.id] : undefined;
  if (!artifact || !draft) {
    return <p className="hint">No artifact is open. Start from Agents to reopen one.</p>;
  }
  return <OpenThesis artifact={artifact} draft={draft} />;
}

function OpenThesis({ artifact, draft }: { artifact: ArtifactRecord; draft: DraftRecord }) {
  const { state, dispatch } = useWorkspace();
  const instruments = useInstruments();
  const capabilities = useCapabilities();
  const symbol = artifact.thesis.contract_code ?? artifact.thesis.symbol;
  const bars = useBars(symbol, "5m");
  const snapshot = state.snapshots.find((item) => item.id === artifact.snapshotId);
  const run = state.runs.find((item) => item.id === artifact.runId);
  const instrument = instruments.data?.find((item) => item.id === artifact.thesis.instrument_id);
  const revisions = state.revisions
    .filter((revision) => revision.artifactId === artifact.id)
    .sort((left, right) => left.revisionNumber - right.revisionNumber);
  const viewing = revisions.find((revision) => revision.id === state.viewingRevisionId) ?? null;
  const shownStructured = viewing?.structured ?? draft.structured;
  const shownMarkdown = viewing?.presentationMarkdown ?? draft.presentationMarkdown;
  const base = revisions.find((revision) => revision.id === draft.baseRevisionId) ?? null;
  const pendingKind = !viewing && base ? changeKindFor(base, draft) : null;
  const proposal = state.proposals.find((item) => item.artifactId === artifact.id && item.status === "pending");
  const resolved = state.proposals.find((item) => item.artifactId === artifact.id && item.status !== "pending");
  const label = provenanceLabel(artifact.thesis.provenance);
  const [tagDraft, setTagDraft] = useState("");

  const onSelectAnnotation = useCallback(
    (id: string) => {
      dispatch({ type: "selectAnnotation", id });
    },
    [dispatch],
  );

  return (
    <article className="thesis" aria-labelledby="artifact-title">
      {label.isDemonstration ? (
        <div className="banner" role="status">
          {label.text}
        </div>
      ) : null}
      <header className="thesis-head">
        <div>
          <h2 id="artifact-title">{artifact.title}</h2>
          <p className="artifact-kicker">
            <span className="num">
              {artifact.thesis.symbol}
              {artifact.thesis.contract_code ? ` · ${artifact.thesis.contract_code}` : ""}
            </span>
            <span className={`stance stance-${shownStructured.stance}`}>{stanceLabel(shownStructured.stance)}</span>
          </p>
        </div>
        <div className="row-actions">
          <span className="draft-status" role="status" data-testid="draft-status">
            {viewing ? `Viewing revision ${String(viewing.revisionNumber)}` : draftStatusLabel(draft)}
          </span>
          <button
            type="button"
            onClick={() => {
              downloadMarkdown(`${artifact.thesis.symbol.toLowerCase()}-thesis.md`, thesisToMarkdown(artifact, {
                ...draft,
                structured: shownStructured,
                presentationMarkdown: shownMarkdown,
              }));
            }}
          >
            Export Markdown
          </button>
          {viewing ? (
            <button
              type="button"
              onClick={() => {
                dispatch({ type: "viewRevision", id: null });
              }}
            >
              Back to draft
            </button>
          ) : (
            <button
              type="button"
              disabled={pendingKind === null}
              onClick={() => {
                dispatch({ type: "saveRevision", artifactId: artifact.id });
              }}
            >
              {pendingKind === "structured_edit" ? "Save structured revision" : "Save narrative revision"}
            </button>
          )}
        </div>
      </header>

      <ResultMeta artifact={artifact} snapshot={snapshot} run={run} capabilities={capabilities.data} />

      <div className="tags" aria-label="Tags">
        {artifact.tags.map((tag) => (
          <button
            key={tag}
            type="button"
            className="tag"
            onClick={() => {
              dispatch({ type: "removeTag", artifactId: artifact.id, tag });
            }}
          >
            {tag} <span aria-hidden="true">×</span>
            <span className="sr-only">Remove tag {tag}</span>
          </button>
        ))}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            dispatch({ type: "addTag", artifactId: artifact.id, tag: tagDraft });
            setTagDraft("");
          }}
        >
          <input
            aria-label="Add tag"
            value={tagDraft}
            onChange={(event) => {
              setTagDraft(event.target.value);
            }}
            placeholder="Add tag"
          />
        </form>
      </div>

      {proposal ? (
        <ProposalCard
          proposal={proposal}
          current={draft.structured}
          onAccept={() => {
            dispatch({ type: "acceptProposal", id: proposal.id });
          }}
          onReject={() => {
            dispatch({ type: "rejectProposal", id: proposal.id });
          }}
        />
      ) : resolved ? (
        <p className="proposal-state" role="status">
          Proposal {resolved.status}.
        </p>
      ) : null}

      {pendingKind === "structured_edit" ? (
        <p className="hint">Structured changes will be saved as a new revision marked for recalculation.</p>
      ) : null}

      <StructuredBlock
        draft={shownStructured}
        features={artifact.features}
        instrument={instrument}
        readOnly={viewing !== null}
        onChange={(patch) => {
          dispatch({ type: "updateStructured", artifactId: artifact.id, patch });
        }}
      />

      <NarrativeEditor
        markdown={shownMarkdown}
        revisionKey={viewing?.id ?? draft.baseRevisionId}
        readOnly={viewing !== null}
        onChange={(markdown) => {
          dispatch({ type: "updateNarrative", artifactId: artifact.id, markdown });
        }}
      />

      <section className="revisions" aria-label="Revisions">
        <h3>Revisions</h3>
        <ol>
          {revisions.map((revision) => (
            <li key={revision.id}>
              <RevisionRow
                revision={revision}
                active={revision.id === (viewing?.id ?? draft.baseRevisionId) && viewing !== null}
                onOpen={() => {
                  dispatch({ type: "viewRevision", id: revision.id });
                }}
              />
            </li>
          ))}
        </ol>
      </section>

      {bars.isError ? <p role="alert">Bars are unavailable. Annotations still describe the saved calculations.</p> : null}
      <CandleChart
        bars={bars.data?.bars ?? []}
        features={artifact.features}
        provenance={bars.data?.provenance ?? snapshot?.provenance ?? null}
        selectedId={state.selectedAnnotationId}
        onSelect={onSelectAnnotation}
      />
    </article>
  );
}

function RevisionRow({
  revision,
  active,
  onOpen,
}: {
  revision: RevisionRecord;
  active: boolean;
  onOpen: () => void;
}) {
  const kind =
    revision.changeKind === "proposed_edit_accepted"
      ? "Accepted proposal"
      : revision.changeKind === "structured_edit"
        ? "Structured edit"
        : revision.changeKind === "narrative_edit"
          ? "Narrative edit"
          : "Generated";
  return (
    <button type="button" className={active ? "revision is-selected" : "revision"} onClick={onOpen} aria-label={`Revision ${String(revision.revisionNumber)} ${kind}`}>
      <span>
        Revision {revision.revisionNumber} · {kind}
      </span>
      <span className="hint">
        {revision.createdBy} · {formatInstant(revision.createdAt)}
        {revision.recalculation === "requested" ? " · recalculation requested" : ""}
      </span>
    </button>
  );
}
