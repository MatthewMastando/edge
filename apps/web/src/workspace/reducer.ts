import { normalizeMarkdown } from "../lib/format";
import { changeKindFor, cloneStructured, structuredEqual } from "./draft";
import type {
  Conversation,
  DraftRecord,
  ProposalRecord,
  RevisionRecord,
  StructuredDraft,
  WorkspaceAction,
  WorkspaceState,
} from "./types";

function attachedArtifactId(state: WorkspaceState, conversation: Conversation): string | null {
  const attachment = conversation.attachment;
  if (attachment?.kind !== "artifact") return null;
  return state.artifacts.some((artifact) => artifact.id === attachment.id) ? attachment.id : null;
}

function createId(): string {
  return crypto.randomUUID();
}

function draftFor(state: WorkspaceState, artifactId: string): DraftRecord | null {
  return state.drafts[artifactId] ?? null;
}

function withDraft(state: WorkspaceState, draft: DraftRecord): WorkspaceState {
  return {
    ...state,
    drafts: { ...state.drafts, [draft.artifactId]: draft },
    viewingRevisionId: null,
  };
}

function nextRevision(state: WorkspaceState, artifactId: string, draft: DraftRecord, changeKind: RevisionRecord["changeKind"], createdBy: RevisionRecord["createdBy"], now: string): RevisionRecord {
  const siblings = state.revisions.filter((revision) => revision.artifactId === artifactId);
  const revisionNumber = siblings.reduce((max, revision) => Math.max(max, revision.revisionNumber), 0) + 1;
  const artifact = state.artifacts.find((item) => item.id === artifactId);
  return {
    id: createId(),
    artifactId,
    revisionNumber,
    changeKind,
    createdBy,
    createdAt: now,
    structured: cloneStructured(draft.structured),
    presentationMarkdown: draft.presentationMarkdown,
    provenance: artifact?.thesis.provenance ?? "recorded",
    isDemonstration: artifact?.thesis.is_demonstration ?? true,
    recalculation: changeKind === "narrative_edit" ? "not_required" : "requested",
  };
}

function applyStructuredPatch(current: StructuredDraft, patch: Partial<StructuredDraft>): StructuredDraft {
  const next: StructuredDraft = { ...current, ...patch };
  const levelsSet = next.entry !== "" && next.invalidation !== "" && next.target !== "";
  if (levelsSet) next.unsetReason = "";
  else if (next.unsetReason === "" && (patch.entry === "" || patch.invalidation === "" || patch.target === "")) {
    next.unsetReason = "Entry, invalidation, or target is unset.";
  }
  return next;
}

export function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case "setMode":
      return state.mode === action.mode ? state : { ...state, mode: action.mode };
    case "scroll":
      if (state.scroll[action.slot] === action.top) return state;
      return { ...state, scroll: { ...state.scroll, [action.slot]: action.top } };
    case "selectArtifact": {
      const artifact = state.artifacts.find((item) => item.id === action.id);
      if (!artifact) return state;
      const linkedConversation =
        artifact.conversationId !== null &&
        state.conversations.some((conversation) => conversation.id === artifact.conversationId)
          ? artifact.conversationId
          : state.activeConversationId;
      const artifactChanged = artifact.id !== state.selectedArtifactId;
      const conversationChanged = linkedConversation !== state.activeConversationId;
      return {
        ...state,
        selectedArtifactId: artifact.id,
        activeConversationId: linkedConversation,
        selectedAnnotationId: null,
        viewingRevisionId: null,
        scroll: {
          chat: conversationChanged ? 0 : state.scroll.chat,
          report: artifactChanged ? 0 : state.scroll.report,
        },
      };
    }
    case "selectAnnotation":
      return { ...state, selectedAnnotationId: action.id };
    case "openNewChat":
      return { ...state, newChatOpen: true };
    case "closeNewChat":
      return { ...state, newChatOpen: false };
    case "selectConversation": {
      const conversation = state.conversations.find((item) => item.id === action.id);
      if (!conversation) return state;
      const linkedArtifact = attachedArtifactId(state, conversation);
      const nextArtifactId = linkedArtifact ?? state.selectedArtifactId;
      const artifactChanged = nextArtifactId !== state.selectedArtifactId;
      const conversationChanged = conversation.id !== state.activeConversationId;
      if (!artifactChanged && !conversationChanged) return state;
      return {
        ...state,
        activeConversationId: conversation.id,
        selectedArtifactId: nextArtifactId,
        selectedAnnotationId: artifactChanged ? null : state.selectedAnnotationId,
        viewingRevisionId: artifactChanged ? null : state.viewingRevisionId,
        scroll: {
          chat: conversationChanged ? 0 : state.scroll.chat,
          report: artifactChanged ? 0 : state.scroll.report,
        },
      };
    }
    case "startConversation": {
      const id = createId();
      const now = new Date().toISOString();
      const title = action.title.trim() || action.attachment?.label || "New conversation";
      const conversation = {
        id,
        title,
        createdAt: now,
        attachment: action.attachment,
        messages: [],
      };
      const attachment = action.attachment;
      const selectedArtifactId =
        attachment && attachment.kind === "artifact" && state.artifacts.some((artifact) => artifact.id === attachment.id)
          ? attachment.id
          : state.selectedArtifactId;
      const artifactChanged = selectedArtifactId !== state.selectedArtifactId;
      return {
        ...state,
        newChatOpen: false,
        conversations: [conversation, ...state.conversations],
        activeConversationId: id,
        selectedArtifactId,
        selectedAnnotationId: artifactChanged ? null : state.selectedAnnotationId,
        viewingRevisionId: artifactChanged ? null : state.viewingRevisionId,
        scroll: { chat: 0, report: artifactChanged ? 0 : state.scroll.report },
      };
    }
    case "sendMessage": {
      const text = action.text.trim();
      if (!text) return state;
      const now = action.now ?? new Date().toISOString();
      const artifact = state.artifacts.find((item) => item.id === state.selectedArtifactId);
      const contract = artifact?.thesis.contract_code ?? artifact?.thesis.symbol ?? "the open artifact";
      const reply = `DEMONSTRATION — recorded reply, not a live model. I can discuss ${contract}. The saved stance is ${artifact?.thesis.stance.replaceAll("_", " ") ?? "unknown"}. This shell does not call a model and will not place, change, or cancel an order.`;
      return {
        ...state,
        conversations: state.conversations.map((conversation) =>
          conversation.id === state.activeConversationId
            ? {
                ...conversation,
                messages: [
                  ...conversation.messages,
                  { id: createId(), role: "user", content: text, createdAt: now, provenance: null },
                  {
                    id: createId(),
                    role: "assistant",
                    content: reply,
                    createdAt: now,
                    provenance: "recorded" as const,
                  },
                ],
              }
            : conversation,
        ),
      };
    }
    case "updateStructured": {
      const draft = draftFor(state, action.artifactId);
      if (!draft) return state;
      const structured = applyStructuredPatch(draft.structured, action.patch);
      if (structuredEqual(structured, draft.structured)) return state;
      return withDraft(state, { ...draft, structured, saveState: "pending", updatedAt: new Date().toISOString() });
    }
    case "updateNarrative": {
      const draft = draftFor(state, action.artifactId);
      if (!draft) return state;
      if (normalizeMarkdown(draft.presentationMarkdown) === normalizeMarkdown(action.markdown)) return state;
      return withDraft(state, {
        ...draft,
        presentationMarkdown: action.markdown,
        saveState: "pending",
        updatedAt: new Date().toISOString(),
      });
    }
    case "draftsSaved": {
      const now = action.now ?? new Date().toISOString();
      let changed = false;
      const drafts = { ...state.drafts };
      for (const [id, draft] of Object.entries(drafts)) {
        if (draft.saveState !== "pending") continue;
        drafts[id] = { ...draft, saveState: "saved", updatedAt: now };
        changed = true;
      }
      return changed ? { ...state, drafts } : state;
    }
    case "saveRevision": {
      const draft = draftFor(state, action.artifactId);
      if (!draft) return state;
      const base = state.revisions.find((revision) => revision.id === draft.baseRevisionId);
      if (!base) return state;
      const changeKind = changeKindFor(base, draft);
      if (!changeKind) return state;
      const now = action.now ?? new Date().toISOString();
      const revision = nextRevision(state, action.artifactId, draft, changeKind, "user", now);
      return {
        ...state,
        revisions: [...state.revisions, revision],
        drafts: {
          ...state.drafts,
          [draft.artifactId]: { ...draft, baseRevisionId: revision.id, saveState: "saved", updatedAt: now },
        },
        viewingRevisionId: null,
        artifacts: state.artifacts.map((artifact) =>
          artifact.id === action.artifactId ? { ...artifact, updatedAt: now } : artifact,
        ),
      };
    }
    case "addTag": {
      const tag = action.tag.trim();
      if (!tag) return state;
      return {
        ...state,
        artifacts: state.artifacts.map((artifact) => {
          if (artifact.id !== action.artifactId) return artifact;
          if (artifact.tags.some((existing) => existing.toLowerCase() === tag.toLowerCase())) return artifact;
          return { ...artifact, tags: [...artifact.tags, tag] };
        }),
      };
    }
    case "removeTag":
      return {
        ...state,
        artifacts: state.artifacts.map((artifact) =>
          artifact.id === action.artifactId
            ? { ...artifact, tags: artifact.tags.filter((tag) => tag !== action.tag) }
            : artifact,
        ),
      };
    case "acceptProposal":
      return resolveProposal(state, action.id, "accepted", action.now);
    case "rejectProposal":
      return resolveProposal(state, action.id, "rejected", action.now);
    case "viewRevision":
      return { ...state, viewingRevisionId: action.id };
    default:
      return state;
  }
}

function resolveProposal(state: WorkspaceState, id: string, status: ProposalRecord["status"], now: string | undefined): WorkspaceState {
  const proposal = state.proposals.find((item) => item.id === id);
  if (!proposal || proposal.status !== "pending") return state;
  const stamped = now ?? new Date().toISOString();
  const proposals = state.proposals.map((item) => (item.id === id ? { ...item, status } : item));
  if (status === "rejected") return { ...state, proposals };

  const draft = draftFor(state, proposal.artifactId);
  if (!draft) return { ...state, proposals };
  const acceptedDraft: DraftRecord = {
    ...draft,
    structured: cloneStructured(proposal.structured),
    presentationMarkdown: proposal.presentationMarkdown,
    saveState: "saved",
    updatedAt: stamped,
  };
  const revision = nextRevision(state, proposal.artifactId, acceptedDraft, "proposed_edit_accepted", "user", stamped);
  return {
    ...state,
    proposals,
    revisions: [...state.revisions, revision],
    drafts: {
      ...state.drafts,
      [proposal.artifactId]: { ...acceptedDraft, baseRevisionId: revision.id },
    },
    viewingRevisionId: null,
    artifacts: state.artifacts.map((artifact) =>
      artifact.id === proposal.artifactId ? { ...artifact, updatedAt: stamped } : artifact,
    ),
  };
}
