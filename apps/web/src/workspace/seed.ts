import type { Job, Run, TAFeature, Thesis } from "../api/types";
import { snapshotsFixture } from "../mocks/catalog";
import { BAR_COUNT, barCloseIso, DATA_REVISION, IDS } from "../mocks/ids";
import type { ArtifactRecord, Conversation, DraftRecord, ProposalRecord, RevisionRecord, RoutineRecord, StructuredDraft, WatchlistRecord, WorkspaceState } from "./types";

const NARRATIVE = [
  "The fixture snapshot contains synthetic 5-minute bars for the December 2026 Euro FX contract. No sourced macro context was retrieved, so this note does not set a conditional entry, invalidation, or target.",
  "",
  "The chart annotations are saved calculations on fixture data. They describe the synthetic path. They are not a live research view and they are not a trade.",
].join("\n");

const PROPOSED_NARRATIVE = [
  NARRATIVE,
  "",
  "Agent note: treat the gap and the sweep as descriptions of the fixture path, not as a setup to trade.",
].join("\n");

const STRUCTURED: StructuredDraft = {
  stance: "insufficient_evidence",
  entry: "",
  invalidation: "",
  target: "",
  contracts: "",
  estimatedCosts: "",
  unsetReason: "Fixture snapshot; no sourced evidence available in this recording.",
};

const PROPOSED_STRUCTURED: StructuredDraft = {
  ...STRUCTURED,
  estimatedCosts: "2.50",
};

function featureBase(partial: Pick<TAFeature, "id" | "detector" | "direction" | "levels" | "origin_time" | "confirmation_time"> & {
  details: TAFeature["details"];
  parameters: TAFeature["parameters"];
}): TAFeature {
  return {
    id: partial.id,
    detector: partial.detector,
    calc_version: "1.0.0",
    instrument_id: IDS.instrument6E,
    contract_code: "6EZ6",
    timeframe: "5m",
    session: "current_session",
    session_calendar_id: "cme_globex_fx",
    session_calendar_version: "1.0.0",
    direction: partial.direction,
    levels: partial.levels,
    state: "confirmed",
    origin_time: partial.origin_time,
    origin_tz: "America/Chicago",
    confirmation_time: partial.confirmation_time,
    confirmation_tz: "America/Chicago",
    as_of: barCloseIso(BAR_COUNT - 1),
    as_of_tz: "America/Chicago",
    parameters: partial.parameters,
    details: partial.details,
    snapshot_id: IDS.snapshot6E,
    data_revision: DATA_REVISION,
    provenance: "fixture",
    warnings: ["Synthetic demonstration calculation on fixture bars. Not a live signal."],
  };
}

const features: TAFeature[] = [
  featureBase({
    id: IDS.featureFvg,
    detector: "fvg",
    direction: "bullish",
    origin_time: "2026-09-22T14:00:00.000Z",
    confirmation_time: "2026-09-22T14:15:00.000Z",
    levels: [
      { name: "zone_upper", price: "1.17350", role: "zone_upper" },
      { name: "zone_lower", price: "1.17300", role: "zone_lower" },
      { name: "midpoint", price: "1.17325", role: "midpoint" },
    ],
    parameters: { min_ticks: 1, displacement_body_ratio: 0.6 },
    details: {
      kind: "zone",
      label: "Bullish FVG",
      start_bar: 24,
      end_bar: 26,
      calculation:
        "Bullish FVG on completed bars A/B/C. low(C) 1.17350 is above high(A) 1.17300, so the zone is [1.17300, 1.17350]. Confirmed at the close of bar C. Minimum gap is one tick (0.00005). Displacement tag stored separately and is not a probability.",
    },
  }),
  featureBase({
    id: IDS.featureLevel,
    detector: "session_levels",
    direction: "neutral",
    origin_time: "2026-09-21T21:00:00.000Z",
    confirmation_time: "2026-09-21T21:00:00.000Z",
    levels: [{ name: "level", price: "1.17650", role: "level" }],
    parameters: { session: "prior_session", name: "PDH" },
    details: {
      kind: "level",
      label: "PDH 1.17650",
      start_bar: 0,
      end_bar: BAR_COUNT - 1,
      calculation:
        "Prior-session high taken from the fixture session calendar (CME Globex FX, America/Chicago). The level was known before this session opened. Confirmation time is the prior session settle used by the fixture, not a pivot confirmation.",
    },
  }),
  featureBase({
    id: IDS.featureSweep,
    detector: "liquidity_sweep",
    direction: "bearish",
    origin_time: "2026-09-22T16:00:00.000Z",
    confirmation_time: "2026-09-22T16:05:00.000Z",
    levels: [{ name: "level", price: "1.17420", role: "level" }],
    parameters: { min_excursion_ticks: 1, reclaim: "same_candle" },
    details: {
      kind: "marker",
      label: "Buy-side sweep",
      start_bar: 48,
      end_bar: 48,
      calculation:
        "Buy-side sweep of a previously known high. Price traded at least one tick through 1.17420 and the same candle closed back below. Wick extension alone would not confirm. Confirmation time is the close of that candle.",
    },
  }),
  featureBase({
    id: IDS.featureRsi,
    detector: "rsi_divergence",
    direction: "bearish",
    origin_time: "2026-09-22T16:55:00.000Z",
    confirmation_time: "2026-09-22T17:10:00.000Z",
    levels: [{ name: "pivot", price: "1.17440", role: "level" }],
    parameters: { period: 14, min_separation_bars: 5, max_separation_bars: 60, min_rsi_difference: 2 },
    details: {
      kind: "rsi",
      label: "RSI divergence",
      start_bar: 40,
      end_bar: 60,
      calculation:
        "RSI(14) Wilder on closes. Bearish divergence: a higher price high at the second confirmed pivot with RSI at least 2 points lower. Emitted at the second pivot's confirmation (pivot bar + 3). The subpane line is the same smoothing, drawn so the marker can be inspected. Hidden divergence is not included.",
    },
  }),
];

const thesis6E: Thesis = {
  id: IDS.thesis6E,
  run_id: IDS.run6E,
  instrument_id: IDS.instrument6E,
  symbol: "6E",
  asset_class: "futures",
  contract_code: "6EZ6",
  venue: "CME",
  horizon: "intraday",
  as_of: barCloseIso(BAR_COUNT - 1),
  expires_at: null,
  stance: "insufficient_evidence",
  plan: {
    entry: null,
    invalidation: null,
    target: null,
    monitoring_criteria: [],
    unset_reason: STRUCTURED.unsetReason,
  },
  risk: {
    account_currency: "USD",
    assumptions: ["No position is assumed. Costs stay blank until a plan exists."],
    contracts: null,
    estimated_costs: null,
    is_hypothetical: true,
    point_value: "125000",
    tick_value: "6.25",
    reward_to_risk: null,
    risk_per_contract: null,
    total_risk: null,
  },
  technical_findings: [
    {
      feature_id: IDS.featureFvg,
      annotation_id: IDS.featureFvg,
      summary: "Bullish fair-value gap 1.17300–1.17350, confirmed at the close of bar C.",
    },
    {
      feature_id: IDS.featureLevel,
      annotation_id: IDS.featureLevel,
      summary: "Prior-session high 1.17650 from the Globex FX calendar.",
    },
    {
      feature_id: IDS.featureSweep,
      annotation_id: IDS.featureSweep,
      summary: "Buy-side sweep of 1.17420 with a same-candle close back below.",
    },
    {
      feature_id: IDS.featureRsi,
      annotation_id: IDS.featureRsi,
      summary: "Bearish RSI(14) divergence at the second confirmed price pivot.",
    },
  ],
  market_narrative: NARRATIVE,
  macro_context: "No macro packet was retrieved for this recording.",
  catalysts: [],
  correlated_markets: [
    {
      symbol: "DX",
      relationship: "Dollar index is the usual offset to euro FX futures. Not computed on this fixture.",
      correlation: null,
      feature_id: null,
      window_bars: null,
    },
  ],
  supporting_evidence: [],
  opposing_evidence: [],
  missing_data: ["rate differentials", "official calendar", "positioning"],
  uncertainty: "The path is synthetic. None of the annotations are evidence of a tradable edge.",
  rationale: "Abstaining. The fixture has bars and calculations, and no sourced context.",
  versions: {
    model: null,
    provider: "recorded",
    prompt_version: "research-0.1.0",
    harness_version: "0.1.0",
    tool_versions: { fvg: "1.0.0", session_levels: "1.0.0", liquidity_sweep: "1.0.0", rsi_divergence: "1.0.0" },
  },
  validation: {
    passed: true,
    repair_attempted: false,
    checks: [
      { name: "schema", passed: true, detail: "Recorded thesis matches the contract." },
      { name: "numeric_crosscheck", passed: true, detail: "No numerical plan to cross-check." },
      { name: "evidence_ids_exist", passed: true, detail: "No evidence ids were claimed." },
    ],
  },
  presentation_markdown: NARRATIVE,
  provenance: "recorded",
  is_demonstration: true,
};

const thesisGC: Thesis = {
  ...thesis6E,
  id: IDS.thesisGC,
  run_id: IDS.runGC,
  instrument_id: IDS.instrumentGC,
  symbol: "GC",
  contract_code: "GCZ6",
  venue: "COMEX",
  technical_findings: [],
  market_narrative: "Gold fixture snapshot only. No calculations have been saved for GCZ6 in this shell.",
  presentation_markdown: "Gold fixture snapshot only. No calculations have been saved for GCZ6 in this shell.",
  rationale: "Placeholder artifact so search and filters have a second instrument.",
  correlated_markets: [],
  missing_data: ["inventories", "rates", "dollar"],
};

const run6E: Run = {
  id: IDS.run6E,
  job_id: IDS.job6E,
  conversation_id: IDS.conversation6E,
  artifact_revision_id: IDS.revision6E,
  status: "completed",
  current_stage: null,
  stages_completed: [
    "resolve_instrument",
    "capture_snapshot",
    "deterministic_ta",
    "gather_context",
    "synthesize",
    "critique",
    "validate",
    "persist",
    "notify",
  ],
  provider: "recorded",
  model: null,
  prompt_version: "research-0.1.0",
  provenance: "recorded",
  usage: {
    input_tokens: 0,
    output_tokens: 0,
    retrieval_calls: 0,
    reserved_cost_usd: "0",
    actual_cost_usd: "0",
  },
  started_at: "2026-09-22T17:55:00.000Z",
  finished_at: "2026-09-22T17:56:00.000Z",
  error: null,
};

const runGC: Run = {
  ...run6E,
  id: IDS.runGC,
  job_id: IDS.jobGC,
  artifact_revision_id: IDS.revisionGC,
  status: "completed",
  started_at: "2026-09-22T18:05:00.000Z",
  finished_at: "2026-09-22T18:06:00.000Z",
};

const job6E: Job = {
  id: IDS.job6E,
  kind: "research",
  state: "completed",
  priority: 0,
  payload: { symbol: "6EZ6" },
  idempotency_key: "fixture-6ez6-session",
  routine_id: IDS.routineSweep,
  conversation_id: IDS.conversation6E,
  scheduled_for: "2026-09-22T17:55:00.000Z",
  scheduled_tz: "America/New_York",
  lease_until: null,
  leased_by: null,
  checkpoint: {},
  attempts: 1,
  max_attempts: 3,
  last_error: null,
  created_at: "2026-09-22T17:55:00.000Z",
  updated_at: "2026-09-22T17:56:00.000Z",
  started_at: "2026-09-22T17:55:00.000Z",
  finished_at: "2026-09-22T17:56:00.000Z",
};

const jobGC: Job = {
  ...job6E,
  id: IDS.jobGC,
  payload: { symbol: "GCZ6" },
  idempotency_key: "fixture-gcz6-session",
  routine_id: IDS.routineMorning,
  conversation_id: null,
  finished_at: "2026-09-22T18:06:00.000Z",
  updated_at: "2026-09-22T18:06:00.000Z",
};

const revision6E: RevisionRecord = {
  id: IDS.revision6E,
  artifactId: IDS.artifact6E,
  revisionNumber: 1,
  changeKind: "generated",
  createdBy: "agent",
  createdAt: "2026-09-22T17:56:00.000Z",
  structured: STRUCTURED,
  presentationMarkdown: NARRATIVE,
  provenance: "recorded",
  isDemonstration: true,
  recalculation: "not_required",
};

const revisionGC: RevisionRecord = {
  id: IDS.revisionGC,
  artifactId: IDS.artifactGC,
  revisionNumber: 1,
  changeKind: "generated",
  createdBy: "agent",
  createdAt: "2026-09-22T18:06:00.000Z",
  structured: { ...STRUCTURED, unsetReason: "No saved calculations for this fixture." },
  presentationMarkdown: thesisGC.presentation_markdown,
  provenance: "recorded",
  isDemonstration: true,
  recalculation: "not_required",
};

const draft6E: DraftRecord = {
  artifactId: IDS.artifact6E,
  baseRevisionId: IDS.revision6E,
  structured: { ...STRUCTURED },
  presentationMarkdown: NARRATIVE,
  updatedAt: "2026-09-22T17:56:00.000Z",
  saveState: "saved",
};

const draftGC: DraftRecord = {
  artifactId: IDS.artifactGC,
  baseRevisionId: IDS.revisionGC,
  structured: { ...revisionGC.structured },
  presentationMarkdown: revisionGC.presentationMarkdown,
  updatedAt: revisionGC.createdAt,
  saveState: "saved",
};

const artifacts: ArtifactRecord[] = [
  {
    id: IDS.artifact6E,
    title: "6EZ6 session note",
    tags: ["fx", "6E", "fixture"],
    conversationId: IDS.conversation6E,
    thesis: thesis6E,
    features,
    runId: IDS.run6E,
    snapshotId: IDS.snapshot6E,
    createdAt: "2026-09-22T17:56:00.000Z",
    updatedAt: "2026-09-22T17:56:00.000Z",
  },
  {
    id: IDS.artifactGC,
    title: "GCZ6 fixture brief",
    tags: ["metals", "GC", "fixture"],
    conversationId: null,
    thesis: thesisGC,
    features: [],
    runId: IDS.runGC,
    snapshotId: IDS.snapshotGC,
    createdAt: "2026-09-22T18:06:00.000Z",
    updatedAt: "2026-09-22T18:06:00.000Z",
  },
];

const conversation: Conversation = {
  id: IDS.conversation6E,
  title: "6EZ6 intraday",
  createdAt: "2026-09-22T17:50:00.000Z",
  attachment: { kind: "artifact", id: IDS.artifact6E, label: "6EZ6 session note" },
  messages: [
    {
      id: "msg-1",
      role: "user",
      content: "Look at 6EZ6 on the 5-minute session. Is there a level to work with?",
      createdAt: "2026-09-22T17:50:00.000Z",
      provenance: null,
    },
    {
      id: "msg-2",
      role: "assistant",
      content:
        "DEMONSTRATION — recorded reply, not a live model. The saved stance on 6EZ6 is insufficient evidence. The chart has a bullish gap, the prior-session high, a buy-side sweep, and an RSI divergence. None of those set an entry. No order will be placed.",
      createdAt: "2026-09-22T17:50:30.000Z",
      provenance: "recorded",
    },
    {
      id: "msg-3",
      role: "user",
      content: "What would invalidate a long if we had one?",
      createdAt: "2026-09-22T17:52:00.000Z",
      provenance: null,
    },
    {
      id: "msg-4",
      role: "assistant",
      content:
        "DEMONSTRATION — recorded reply. Invalidation is unset. The note says so explicitly because the fixture has no sourced context. I will not invent a stop.",
      createdAt: "2026-09-22T17:52:20.000Z",
      provenance: "recorded",
    },
  ],
};

const proposal: ProposalRecord = {
  id: IDS.proposal6E,
  artifactId: IDS.artifact6E,
  baseRevisionId: IDS.revision6E,
  status: "pending",
  summary: "Add a caution that the fixture path is not a trade, and record hypothetical costs of 2.50 USD.",
  structured: PROPOSED_STRUCTURED,
  presentationMarkdown: PROPOSED_NARRATIVE,
  createdAt: "2026-09-22T17:58:00.000Z",
};

const routines: RoutineRecord[] = [
  {
    id: IDS.routineMorning,
    name: "Morning FX and metals brief",
    kind: "scheduled_briefing",
    enabled: true,
    schedule: "30 7 * * 1-5",
    timezone: "America/New_York",
    cooldownSeconds: 14_400,
    dailyCap: 1,
    lastRunAt: "2026-09-22T18:06:00.000Z",
    nextRunAt: "2026-09-23T11:30:00.000Z",
    instrumentLabel: "6E, GC",
  },
  {
    id: IDS.routineSweep,
    name: "6E liquidity-sweep research",
    kind: "ta_trigger",
    enabled: true,
    schedule: null,
    timezone: "America/New_York",
    cooldownSeconds: 14_400,
    dailyCap: 4,
    lastRunAt: "2026-09-22T17:56:00.000Z",
    nextRunAt: null,
    instrumentLabel: "6EZ6",
  },
];

const watchlists: WatchlistRecord[] = [
  { id: IDS.watchlistMetalsFx, name: "FX and metals", symbols: ["6E", "GC"] },
  { id: IDS.watchlistIndex, name: "Index and energy", symbols: ["ES", "CL", "SPY"] },
];

export function createSeedState(): WorkspaceState {
  return {
    mode: "output",
    newChatOpen: false,
    conversations: [conversation],
    activeConversationId: conversation.id,
    artifacts,
    selectedArtifactId: IDS.artifact6E,
    revisions: [revision6E, revisionGC],
    drafts: {
      [IDS.artifact6E]: draft6E,
      [IDS.artifactGC]: draftGC,
    },
    proposals: [proposal],
    routines,
    runs: [run6E, runGC],
    jobs: [job6E, jobGC],
    snapshots: snapshotsFixture,
    watchlists,
    scroll: { chat: 0, report: 0 },
    selectedAnnotationId: null,
    viewingRevisionId: null,
  };
}

export const SEED_NARRATIVE = NARRATIVE;
