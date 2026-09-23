import { createSeedState } from "./seed";
import type { WorkspaceState } from "./types";

export const WORKSPACE_STORAGE_KEY = "trw.workspace.v1";

interface Envelope {
  version: 1;
  state: WorkspaceState;
}

function isEnvelope(value: unknown): value is Envelope {
  if (typeof value !== "object" || value === null) return false;
  const record = value as { version?: unknown; state?: unknown };
  if (record.version !== 1 || typeof record.state !== "object" || record.state === null) return false;
  const state = record.state as { artifacts?: unknown; drafts?: unknown };
  return Array.isArray(state.artifacts) && typeof state.drafts === "object";
}

export function loadWorkspace(): WorkspaceState {
  if (typeof localStorage === "undefined") return createSeedState();
  try {
    const raw = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (!raw) return createSeedState();
    const parsed: unknown = JSON.parse(raw);
    if (!isEnvelope(parsed)) return createSeedState();
    return parsed.state;
  } catch {
    return createSeedState();
  }
}

export function saveWorkspace(state: WorkspaceState): void {
  if (typeof localStorage === "undefined") return;
  const envelope: Envelope = { version: 1, state };
  localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(envelope));
}
