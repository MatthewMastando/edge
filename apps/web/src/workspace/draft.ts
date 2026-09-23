import { normalizeMarkdown } from "../lib/format";
import type { ChangeKind, DraftRecord, RevisionRecord, StructuredDraft } from "./types";

export function structuredEqual(left: StructuredDraft, right: StructuredDraft): boolean {
  return (
    left.stance === right.stance &&
    left.entry === right.entry &&
    left.invalidation === right.invalidation &&
    left.target === right.target &&
    left.contracts === right.contracts &&
    left.estimatedCosts === right.estimatedCosts &&
    left.unsetReason === right.unsetReason
  );
}

export function draftsMatch(revision: RevisionRecord, draft: Pick<DraftRecord, "structured" | "presentationMarkdown">): boolean {
  return (
    structuredEqual(revision.structured, draft.structured) &&
    normalizeMarkdown(revision.presentationMarkdown) === normalizeMarkdown(draft.presentationMarkdown)
  );
}

export function changeKindFor(revision: RevisionRecord, draft: Pick<DraftRecord, "structured" | "presentationMarkdown">): ChangeKind | null {
  if (draftsMatch(revision, draft)) return null;
  if (!structuredEqual(revision.structured, draft.structured)) return "structured_edit";
  return "narrative_edit";
}

export function cloneStructured(structured: StructuredDraft): StructuredDraft {
  return { ...structured };
}
