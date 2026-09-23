import type { Job, MarketSnapshot, Provenance, Run, Stance, TAFeature, Thesis } from "../api/types";

export type LayoutMode = "output" | "agent";

export type ChangeKind = "generated" | "narrative_edit" | "structured_edit" | "proposed_edit_accepted";

export interface Attachment {
  kind: "instrument" | "watchlist" | "artifact";
  id: string;
  label: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  provenance: Provenance | null;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  attachment: Attachment | null;
  messages: ChatMessage[];
}

/** Form state for the structured block. Empty strings mean the value is unset. */
export interface StructuredDraft {
  stance: Stance;
  entry: string;
  invalidation: string;
  target: string;
  contracts: string;
  estimatedCosts: string;
  unsetReason: string;
}

export interface ArtifactRecord {
  id: string;
  title: string;
  tags: string[];
  conversationId: string | null;
  thesis: Thesis;
  features: TAFeature[];
  runId: string;
  snapshotId: string;
  createdAt: string;
  updatedAt: string;
}

export interface RevisionRecord {
  id: string;
  artifactId: string;
  revisionNumber: number;
  changeKind: ChangeKind;
  createdBy: "user" | "agent";
  createdAt: string;
  structured: StructuredDraft;
  presentationMarkdown: string;
  provenance: Provenance;
  isDemonstration: boolean;
  recalculation: "requested" | "not_required";
}

export interface DraftRecord {
  artifactId: string;
  baseRevisionId: string;
  structured: StructuredDraft;
  presentationMarkdown: string;
  updatedAt: string;
  saveState: "clean" | "pending" | "saved";
}

export interface ProposalRecord {
  id: string;
  artifactId: string;
  baseRevisionId: string;
  status: "pending" | "accepted" | "rejected";
  summary: string;
  structured: StructuredDraft;
  presentationMarkdown: string;
  createdAt: string;
}

export interface RoutineRecord {
  id: string;
  name: string;
  kind: "scheduled_briefing" | "ta_trigger" | "manual";
  enabled: boolean;
  schedule: string | null;
  timezone: string;
  cooldownSeconds: number;
  dailyCap: number;
  lastRunAt: string | null;
  nextRunAt: string | null;
  instrumentLabel: string;
}

export interface WatchlistRecord {
  id: string;
  name: string;
  symbols: string[];
}

export interface WorkspaceState {
  mode: LayoutMode;
  newChatOpen: boolean;
  conversations: Conversation[];
  activeConversationId: string;
  artifacts: ArtifactRecord[];
  selectedArtifactId: string;
  revisions: RevisionRecord[];
  drafts: Record<string, DraftRecord>;
  proposals: ProposalRecord[];
  routines: RoutineRecord[];
  runs: Run[];
  jobs: Job[];
  snapshots: MarketSnapshot[];
  watchlists: WatchlistRecord[];
  scroll: { chat: number; report: number };
  selectedAnnotationId: string | null;
  viewingRevisionId: string | null;
}

export type WorkspaceAction =
  | { type: "setMode"; mode: LayoutMode }
  | { type: "scroll"; slot: "chat" | "report"; top: number }
  | { type: "selectArtifact"; id: string }
  | { type: "selectAnnotation"; id: string | null }
  | { type: "openNewChat" }
  | { type: "closeNewChat" }
  | { type: "startConversation"; title: string; attachment: Attachment | null }
  | { type: "selectConversation"; id: string }
  | { type: "sendMessage"; text: string; now?: string }
  | { type: "updateStructured"; artifactId: string; patch: Partial<StructuredDraft> }
  | { type: "updateNarrative"; artifactId: string; markdown: string }
  | { type: "draftsSaved"; now?: string }
  | { type: "saveRevision"; artifactId: string; now?: string }
  | { type: "addTag"; artifactId: string; tag: string }
  | { type: "removeTag"; artifactId: string; tag: string }
  | { type: "acceptProposal"; id: string; now?: string }
  | { type: "rejectProposal"; id: string; now?: string }
  | { type: "viewRevision"; id: string | null }
  | { type: "appendChat"; conversationId: string; message: ChatMessage }
  | { type: "renameConversation"; from: string; to: string; title?: string }
  | {
      type: "restoreSaved";
      artifacts: ArtifactRecord[];
      revisions: RevisionRecord[];
      drafts: Record<string, DraftRecord>;
      runs: Run[];
      selectedArtifactId: string;
      conversationId: string | null;
      messages: ChatMessage[];
    }
  | {
      type: "openSavedArtifact";
      artifact: ArtifactRecord;
      revisions: RevisionRecord[];
      draft: DraftRecord;
      run: Run | null;
      conversationId: string;
    }
  | { type: "applyRemoteRevision"; revision: RevisionRecord };
