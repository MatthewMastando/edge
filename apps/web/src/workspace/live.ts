import type { LayoutMode, WorkspaceState } from "./types";

export const VIEW_STORAGE_KEY = "trw.view.v1";

interface ViewPrefs {
  mode: LayoutMode;
  scroll: { chat: number; report: number };
  selectedArtifactId: string;
}

function emptyConversation(now: string): WorkspaceState["conversations"][number] {
  return {
    id: "local-fixture",
    title: "6EZ6 research",
    createdAt: now,
    attachment: { kind: "instrument", id: "6EZ6", label: "6EZ6" },
    messages: [],
  };
}

export function readView(): ViewPrefs {
  const fallback: ViewPrefs = { mode: "output", scroll: { chat: 0, report: 0 }, selectedArtifactId: "" };
  if (typeof localStorage === "undefined") return fallback;
  try {
    const raw = localStorage.getItem(VIEW_STORAGE_KEY);
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return fallback;
    const record = parsed as Partial<ViewPrefs>;
    const mode = record.mode === "agent" ? "agent" : "output";
    const scroll = record.scroll;
    return {
      mode,
      scroll: {
        chat: typeof scroll?.chat === "number" ? scroll.chat : 0,
        report: typeof scroll?.report === "number" ? scroll.report : 0,
      },
      selectedArtifactId: typeof record.selectedArtifactId === "string" ? record.selectedArtifactId : "",
    };
  } catch {
    return fallback;
  }
}

export function saveView(state: WorkspaceState): void {
  if (typeof localStorage === "undefined") return;
  const prefs: ViewPrefs = {
    mode: state.mode,
    scroll: state.scroll,
    selectedArtifactId: state.selectedArtifactId,
  };
  localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(prefs));
}

/** Live fixture path starts empty. Saved artifacts are loaded from the API. */
export function createLiveState(): WorkspaceState {
  const view = readView();
  const now = new Date().toISOString();
  const conversation = emptyConversation(now);
  return {
    mode: view.mode,
    newChatOpen: false,
    conversations: [conversation],
    activeConversationId: conversation.id,
    artifacts: [],
    selectedArtifactId: "",
    revisions: [],
    drafts: {},
    proposals: [],
    routines: [],
    runs: [],
    jobs: [],
    snapshots: [],
    watchlists: [],
    scroll: view.scroll,
    selectedAnnotationId: null,
    viewingRevisionId: null,
  };
}
