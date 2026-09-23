import { API_BASE_URL, api } from "../api/client";
import type { Run, RunEvent, TAFeature, Thesis } from "../api/types";
import type { ArtifactRecord, ChatMessage, DraftRecord, RevisionRecord, StructuredDraft } from "../workspace/types";

const FIXTURE_SYMBOL = "6EZ6";

export interface ResearchProgress {
  event: "progress" | "message" | "done" | "error";
  message: string;
  stage: string | null;
  run_id: string | null;
  job_id: string | null;
  job_state: string | null;
  is_demonstration: boolean | null;
  artifact_id: string | null;
  conversation_id: string | null;
}

export async function streamFixtureResearch(
  input: { message: string; conversationId: string | null; clientMessageId: string },
  onEvent: (event: ResearchProgress) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      message: input.message,
      symbol: FIXTURE_SYMBOL,
      timeframe: "5m",
      horizon: "2-5 sessions",
      dispatch: "worker",
      conversation_id: input.conversationId,
      client_message_id: input.clientMessageId,
    }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`Research failed (${String(response.status)})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const event = parseEvent(part);
      if (event) onEvent(event);
    }
  }
}

export async function saveDraftRemote(draft: DraftRecord): Promise<void> {
  const saved = await api.PUT("/v1/artifacts/{artifact_id}/draft", {
    params: { path: { artifact_id: draft.artifactId } },
    body: {
      base_revision_id: draft.baseRevisionId,
      presentation_markdown: draft.presentationMarkdown,
      structured: formPayload(draft.structured, draft.updatedAt),
    },
  });
  if (!saved.response.ok) {
    throw new Error(`Draft save failed (${String(saved.response.status)})`);
  }
}

export async function saveUserRevision(artifactId: string, draft: DraftRecord): Promise<RevisionRecord | null> {
  const response = await fetch(`${API_BASE_URL}/v1/artifacts/${artifactId}/revisions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_revision_id: draft.baseRevisionId,
      presentation_markdown: draft.presentationMarkdown,
      stance: draft.structured.stance,
      entry: decimalOrNull(draft.structured.entry),
      invalidation: decimalOrNull(draft.structured.invalidation),
      target: decimalOrNull(draft.structured.target),
      contracts: draft.structured.contracts === "" ? null : Number(draft.structured.contracts),
      estimated_costs: decimalOrNull(draft.structured.estimatedCosts),
      unset_reason: draft.structured.unsetReason === "" ? null : draft.structured.unsetReason,
    }),
  });
  if (!response.ok) return null;
  const body: unknown = await response.json();
  return revisionFromDetail(body, artifactId);
}

export interface RestoredWorkspace {
  artifacts: ArtifactRecord[];
  revisions: RevisionRecord[];
  drafts: Record<string, DraftRecord>;
  runs: Run[];
  selectedArtifactId: string;
  conversationId: string | null;
  messages: ChatMessage[];
}

export async function loadSavedWorkspace(preferredId: string): Promise<RestoredWorkspace | null> {
  const listed = await api.GET("/v1/artifacts", { params: { query: { limit: 20 } } });
  if (!listed.response.ok || !listed.data || listed.data.length === 0) return null;
  const artifacts: ArtifactRecord[] = [];
  const revisions: RevisionRecord[] = [];
  const drafts: Record<string, DraftRecord> = {};
  const runs: Run[] = [];
  for (const summary of listed.data) {
    const loaded = await loadArtifactBundle(summary.id);
    if (!loaded) continue;
    artifacts.push(loaded.artifact);
    revisions.push(...loaded.revisions);
    drafts[loaded.artifact.id] = loaded.draft;
    if (loaded.run) runs.push(loaded.run);
  }
  if (artifacts.length === 0) return null;
  const selected = artifacts.find((artifact) => artifact.id === preferredId) ?? artifacts[0];
  if (!selected) return null;
  const messages = await progressMessages(selected);
  return {
    artifacts,
    revisions,
    drafts,
    runs,
    selectedArtifactId: selected.id,
    conversationId: selected.conversationId,
    messages,
  };
}

export async function loadArtifactBundle(artifactId: string): Promise<{
  artifact: ArtifactRecord;
  revisions: RevisionRecord[];
  draft: DraftRecord;
  run: Run | null;
} | null> {
  const detail = await api.GET("/v1/artifacts/{artifact_id}", { params: { path: { artifact_id: artifactId } } });
  if (!detail.response.ok || !detail.data) return null;
  const revisionList = await api.GET("/v1/artifacts/{artifact_id}/revisions", {
    params: { path: { artifact_id: artifactId }, query: { limit: 20 } },
  });
  if (!revisionList.response.ok || !revisionList.data || revisionList.data.length === 0) return null;
  const currentId = detail.data.current_revision_id ?? revisionList.data[0]?.id;
  if (!currentId) return null;
  const current = await api.GET("/v1/artifacts/{artifact_id}/revisions/{revision_id}", {
    params: { path: { artifact_id: artifactId, revision_id: currentId } },
  });
  if (!current.response.ok || !current.data) return null;
  const thesis = asThesis(current.data.structured);
  if (!thesis) return null;
  const features = thesis.run_id ? await loadFeatures(thesis.run_id) : [];
  const run = thesis.run_id ? await loadRun(thesis.run_id) : null;
  const draftResponse = await api.GET("/v1/artifacts/{artifact_id}/draft", {
    params: { path: { artifact_id: artifactId } },
  });
  const revision = toRevision(current.data, thesis, artifactId);
  const older = revisionList.data
    .filter((item) => item.id !== revision.id)
    .map((item) => summaryRevision(item, artifactId, thesis));
  const draft = draftFromResponse(draftResponse.data, revision);
  const artifact: ArtifactRecord = {
    id: detail.data.id,
    title: detail.data.title,
    tags: detail.data.tags ?? [],
    conversationId: detail.data.conversation_id ?? null,
    thesis,
    features,
    runId: run?.id ?? thesis.run_id ?? "",
    snapshotId: features[0]?.snapshot_id ?? "",
    createdAt: detail.data.created_at,
    updatedAt: detail.data.updated_at,
  };
  return { artifact, revisions: [revision, ...older], draft, run };
}

async function loadFeatures(runId: string): Promise<TAFeature[]> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}/features?limit=80`);
  if (!response.ok) return [];
  const body: unknown = await response.json();
  if (!Array.isArray(body)) return [];
  return body.filter(isFeature);
}

async function loadRun(runId: string): Promise<Run | null> {
  const response = await api.GET("/v1/runs/{run_id}", { params: { path: { run_id: runId } } });
  if (!response.response.ok || !response.data) return null;
  return response.data;
}

async function progressMessages(artifact: ArtifactRecord): Promise<ChatMessage[]> {
  if (!artifact.runId) return [];
  const response = await api.GET("/v1/runs/{run_id}/events", { params: { path: { run_id: artifact.runId } } });
  if (!response.response.ok || !response.data) return [];
  return response.data.map((event) => eventMessage(event));
}

function eventMessage(event: RunEvent): ChatMessage {
  return {
    id: `${event.run_id}-${String(event.sequence)}`,
    role: "assistant",
    content: event.stage ? `${event.stage}: ${event.message}` : event.message,
    createdAt: event.at,
    provenance: null,
  };
}

function draftFromResponse(
  body: { base_revision_id?: string | null; presentation_markdown?: string | null; structured?: { [key: string]: unknown } | null; updated_at?: string | null } | undefined,
  revision: RevisionRecord,
): DraftRecord {
  const form = body?.structured ? formFromUnknown(body.structured) : null;
  return {
    artifactId: revision.artifactId,
    baseRevisionId: body?.base_revision_id ?? revision.id,
    structured: form ?? revision.structured,
    presentationMarkdown: body?.presentation_markdown ?? revision.presentationMarkdown,
    updatedAt: body?.updated_at ?? revision.createdAt,
    saveState: "saved",
  };
}

function revisionFromDetail(body: unknown, artifactId: string): RevisionRecord | null {
  if (typeof body !== "object" || body === null) return null;
  const record = body as {
    id?: unknown;
    revision_number?: unknown;
    change_kind?: unknown;
    created_by?: unknown;
    created_at?: unknown;
    presentation_markdown?: unknown;
    is_demonstration?: unknown;
    provenance?: unknown;
    structured?: unknown;
  };
  const thesis = asThesis(record.structured);
  if (!thesis || typeof record.id !== "string" || typeof record.created_at !== "string") return null;
  if (typeof record.presentation_markdown !== "string" || typeof record.revision_number !== "number") return null;
  return {
    id: record.id,
    artifactId,
    revisionNumber: record.revision_number,
    changeKind: changeKind(record.change_kind),
    createdBy: record.created_by === "user" ? "user" : "agent",
    createdAt: record.created_at,
    structured: structuredFromThesis(thesis),
    presentationMarkdown: record.presentation_markdown,
    provenance: thesis.provenance,
    isDemonstration: record.is_demonstration === true,
    recalculation: record.change_kind === "structured_edit" ? "requested" : "not_required",
  };
}

function toRevision(
  detail: {
    id: string;
    revision_number: number;
    change_kind: string;
    created_by: string;
    created_at: string;
    presentation_markdown: string;
    is_demonstration: boolean;
    provenance: string;
    structured: { [key: string]: unknown };
  },
  thesis: Thesis,
  artifactId: string,
): RevisionRecord {
  return {
    id: detail.id,
    artifactId,
    revisionNumber: detail.revision_number,
    changeKind: changeKind(detail.change_kind),
    createdBy: detail.created_by === "user" ? "user" : "agent",
    createdAt: detail.created_at,
    structured: structuredFromThesis(thesis),
    presentationMarkdown: detail.presentation_markdown,
    provenance: provenanceOf(detail.provenance),
    isDemonstration: detail.is_demonstration,
    recalculation: detail.change_kind === "structured_edit" ? "requested" : "not_required",
  };
}

function summaryRevision(
  summary: {
    id: string;
    revision_number: number;
    change_kind: string;
    created_by: string;
    created_at: string;
    presentation_markdown: string;
    is_demonstration: boolean;
    provenance: string;
  },
  artifactId: string,
  thesis: Thesis,
): RevisionRecord {
  return {
    id: summary.id,
    artifactId,
    revisionNumber: summary.revision_number,
    changeKind: changeKind(summary.change_kind),
    createdBy: summary.created_by === "user" ? "user" : "agent",
    createdAt: summary.created_at,
    structured: structuredFromThesis(thesis),
    presentationMarkdown: summary.presentation_markdown,
    provenance: provenanceOf(summary.provenance),
    isDemonstration: summary.is_demonstration,
    recalculation: summary.change_kind === "structured_edit" ? "requested" : "not_required",
  };
}

function formPayload(form: StructuredDraft, updatedAt: string): { [key: string]: string } {
  return {
    stance: form.stance,
    entry: form.entry,
    invalidation: form.invalidation,
    target: form.target,
    contracts: form.contracts,
    estimatedCosts: form.estimatedCosts,
    unsetReason: form.unsetReason,
    clientUpdatedAt: updatedAt,
  };
}

function formFromUnknown(value: { [key: string]: unknown }): StructuredDraft | null {
  if (typeof value["stance"] !== "string" || typeof value["entry"] !== "string") return null;
  const stance = value["stance"];
  if (stance !== "bullish" && stance !== "bearish" && stance !== "neutral" && stance !== "insufficient_evidence") {
    return null;
  }
  return {
    stance,
    entry: stringField(value["entry"]),
    invalidation: stringField(value["invalidation"]),
    target: stringField(value["target"]),
    contracts: stringField(value["contracts"]),
    estimatedCosts: stringField(value["estimatedCosts"]),
    unsetReason: stringField(value["unsetReason"]),
  };
}

export function structuredFromThesis(thesis: Thesis): StructuredDraft {
  return {
    stance: thesis.stance,
    entry: thesis.plan.entry ?? "",
    invalidation: thesis.plan.invalidation ?? "",
    target: thesis.plan.target ?? "",
    contracts: thesis.risk?.contracts == null ? "" : String(thesis.risk.contracts),
    estimatedCosts: thesis.risk?.estimated_costs ?? "",
    unsetReason: thesis.plan.unset_reason ?? "",
  };
}

function asThesis(value: unknown): Thesis | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Partial<Thesis>;
  if (typeof record.symbol !== "string" || typeof record.stance !== "string") return null;
  if (typeof record.provenance !== "string" || !record.plan || typeof record.plan !== "object") return null;
  return record as Thesis;
}

function isFeature(value: unknown): value is TAFeature {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Partial<TAFeature>;
  return typeof record.id === "string" && typeof record.detector === "string" && Array.isArray(record.levels);
}

function changeKind(value: unknown): RevisionRecord["changeKind"] {
  if (value === "narrative_edit" || value === "structured_edit" || value === "proposed_edit_accepted" || value === "generated") {
    return value;
  }
  return "generated";
}

function provenanceOf(value: string): Thesis["provenance"] {
  if (value === "fixture" || value === "recorded" || value === "live") return value;
  return "recorded";
}

function stringField(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function decimalOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function parseEvent(chunk: string): ResearchProgress | null {
  const line = chunk.split("\n").find((item) => item.startsWith("data: "));
  if (!line) return null;
  try {
    const parsed: unknown = JSON.parse(line.slice("data: ".length));
    if (typeof parsed !== "object" || parsed === null) return null;
    const record = parsed as Partial<ResearchProgress>;
    if (record.event !== "progress" && record.event !== "message" && record.event !== "done" && record.event !== "error") {
      return null;
    }
    if (typeof record.message !== "string") return null;
    return {
      event: record.event,
      message: record.message,
      stage: typeof record.stage === "string" ? record.stage : null,
      run_id: typeof record.run_id === "string" ? record.run_id : null,
      job_id: typeof record.job_id === "string" ? record.job_id : null,
      job_state: typeof record.job_state === "string" ? record.job_state : null,
      is_demonstration: typeof record.is_demonstration === "boolean" ? record.is_demonstration : null,
      artifact_id: typeof record.artifact_id === "string" ? record.artifact_id : null,
      conversation_id: typeof record.conversation_id === "string" ? record.conversation_id : null,
    };
  } catch {
    return null;
  }
}
