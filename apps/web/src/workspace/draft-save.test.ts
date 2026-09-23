import { describe, expect, it } from "vitest";

import { workspaceReducer } from "./reducer";
import type { DraftRecord, WorkspaceState } from "./types";

function draft(updatedAt: string, markdown: string): DraftRecord {
  return {
    artifactId: "artifact-1",
    baseRevisionId: "revision-1",
    structured: {
      stance: "insufficient_evidence",
      entry: "",
      invalidation: "",
      target: "",
      contracts: "",
      estimatedCosts: "",
      unsetReason: "unset",
    },
    presentationMarkdown: markdown,
    updatedAt,
    saveState: "pending",
  };
}

function state(record: DraftRecord): WorkspaceState {
  return {
    mode: "output",
    newChatOpen: false,
    conversations: [],
    activeConversationId: "",
    artifacts: [],
    selectedArtifactId: "",
    revisions: [],
    drafts: { [record.artifactId]: record },
    proposals: [],
    routines: [],
    runs: [],
    jobs: [],
    snapshots: [],
    watchlists: [],
    scroll: { chat: 0, report: 0 },
    selectedAnnotationId: null,
    viewingRevisionId: null,
  };
}

describe("draft save acknowledgement", () => {
  it("keeps a newer edit pending when an older save finishes", () => {
    const current = state(draft("2026-09-23T17:00:02.000Z", "newer sentence"));
    const next = workspaceReducer(current, {
      type: "draftsSaved",
      now: "2026-09-23T17:00:03.000Z",
      stamps: { "artifact-1": "2026-09-23T17:00:01.000Z" },
    });
    expect(next.drafts["artifact-1"]?.saveState).toBe("pending");
    expect(next.drafts["artifact-1"]?.presentationMarkdown).toBe("newer sentence");
  });

  it("marks the draft that was actually saved", () => {
    const current = state(draft("2026-09-23T17:00:01.000Z", "saved sentence"));
    const next = workspaceReducer(current, {
      type: "draftsSaved",
      now: "2026-09-23T17:00:03.000Z",
      stamps: { "artifact-1": "2026-09-23T17:00:01.000Z" },
    });
    expect(next.drafts["artifact-1"]?.saveState).toBe("saved");
  });
});
