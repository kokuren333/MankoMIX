// Domain types shared by the GUI and both backends.
// Project types follow schemas/project.schema.json; report types follow
// schemas/report.schema.json. Analysis, plan, verification, audio and
// history payloads are defined by the GUI <-> server contract in gui/API.md.

export type Lang = "ja" | "en";

/** A label is either a plain string or a per-language map ({ ja, en }). */
export type Label = string | { [lang: string]: string | undefined };

export type Role =
  | "vocals"
  | "backing_vocals"
  | "drums"
  | "percussion"
  | "bass"
  | "guitar"
  | "keyboard"
  | "synth"
  | "strings"
  | "brass"
  | "woodwinds"
  | "fx"
  | "other"
  | "fullmix";

export const ROLES: Role[] = [
  "vocals",
  "backing_vocals",
  "drums",
  "percussion",
  "bass",
  "guitar",
  "keyboard",
  "synth",
  "strings",
  "brass",
  "woodwinds",
  "fx",
  "other",
  "fullmix",
];

/** Common pass/fail state used by verification and diagnostics. */
export type CheckStatus = "pass" | "fail" | "warning" | "not_run";

// ---------------------------------------------------------------------------
// Project (schemas/project.schema.json)
// ---------------------------------------------------------------------------

export interface Asset {
  id: string;
  path: string;
  original_name?: string | null;
  sha256: string;
  format?: string | null;
  channels?: number | null;
  sample_rate?: number | null;
  length_samples?: number | null;
  duration_s?: number | null;
  role: Role;
  role_source?: string;
  origin: "native_stem" | "separated" | "reference_fullmix" | "derived" | "added";
  linked?: boolean;
}

export interface IngestCheck {
  check: string;
  level: "info" | "warning" | "reject";
  asset?: string | null;
  message: string;
  values?: Record<string, unknown>;
}

export interface Processor {
  id: string;
  type: string;
  params: Record<string, unknown>;
  reason: string;
  backend?: string | null;
  enabled?: boolean;
}

export interface Clip {
  id: string;
  asset: string;
  source_start: number;
  length: number | null;
  timeline_start: number;
  gain_db?: number;
  fade_in?: number;
  fade_out?: number;
  muted?: boolean;
}

export interface Track {
  id: string;
  kind?: "audio";
  name?: string;
  role: Role;
  is_lead?: boolean;
  importance?: { value: number; source: string; by_section?: Record<string, number> };
  clips?: Clip[];
  cleanup?: { enabled?: boolean; plan?: unknown; overrides?: Record<string, unknown> };
  chain?: Processor[];
  gain_db?: number;
  pan?: { position?: number; width?: number };
  muted?: boolean;
  solo?: boolean;
  sends?: { bus: string; level_db?: number; pre_fader?: boolean }[];
  output?: string;
}

export interface Bus {
  id: string;
  kind: "mix" | "fx" | "group" | "aux";
  name?: string;
  chain: Processor[];
  gain_db?: number;
  output?: string;
}

export interface BlendItem {
  id: string;
  weight: number;
}

export interface ObjectiveSpec {
  blend: BlendItem[];
  intensity: number;
  overrides?: Record<string, Record<string, unknown>>;
  lead_stem?: string | null;
}

export interface OutputSpec {
  profile: string;
  delivery: string;
  target_lufs_i?: number | null;
  ceiling_dbtp?: number | null;
}

export interface ProjectVariant {
  id: string;
  label?: Label;
  objective?: ObjectiveSpec | null;
  master?: { route?: "stem_mix" | "fullmix" | "auto"; chain?: Processor[] };
  outputs: OutputSpec[];
  track_overrides?: Record<string, unknown>;
}

export interface Reference {
  id: string;
  label?: string;
  vector?: string;
  sha256?: string;
}

export interface Project {
  schema_version: 1;
  id: string;
  title: string;
  genre?: string | null;
  timebase: {
    sample_rate: number | null;
    bpm: number | null;
    key: string | null;
    length_samples: number | null;
    conform_policy: Record<string, unknown>;
  };
  provenance?: Record<string, string | boolean | null>;
  assets: Asset[];
  fullmix_asset?: string | null;
  ingest?: {
    adapter?: string | null;
    input_kind?: string | null;
    detected_by?: string | null;
    files?: unknown[];
    checks?: IngestCheck[];
    conform?: Record<string, unknown>;
  };
  tracks: Track[];
  buses: Bus[];
  mix: { pan_law_center_db: number; declared_depth_order?: string[] };
  objective: ObjectiveSpec;
  references?: Reference[];
  listening_assumption?: { system: string; level: string };
  variants?: ProjectVariant[];
  sections?: { id: string; label?: string; start: number; length: number }[];
  engine: { min_version: string };
  notes?: string;
  [extension: `x_${string}`]: unknown;
}

/** RFC 6902 JSON Patch operation (core `patch`). */
export interface PatchOp {
  op: "add" | "remove" | "replace" | "move" | "copy" | "test";
  path: string;
  value?: unknown;
  from?: string;
}

// ---------------------------------------------------------------------------
// Definitions (objectives/catalog.json, profiles/*.json, registry/models.json)
// ---------------------------------------------------------------------------

export interface ObjectiveTerm {
  metric: string;
  variant?: string;
  weight: number;
  sense?: string;
}

export interface ObjectiveDef {
  id: string;
  spec_id?: string;
  kind: "score" | "gate" | string;
  label: Label;
  summary?: Label;
  terms?: ObjectiveTerm[];
  constraints_emphasis?: string[];
  status?: string;
  [key: string]: unknown;
}

export interface ObjectiveCatalog {
  default: string;
  objectives: ObjectiveDef[];
  note?: string;
}

export interface MediaProfile {
  id: string;
  aliases?: string[];
  label: Label;
  kind: string;
  loudness: {
    target_lufs_i: number | null;
    window_lufs_i?: [number, number] | null;
    normalization?: string;
    policy?: string;
  };
  true_peak: { ceiling_dbtp: number; conditional?: { when: string; ceiling_dbtp: number }[] };
  codec_checks?: string[];
  playback_assumptions?: Record<string, unknown>;
  default_delivery?: string;
  source?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DeliveryFormat {
  id: string;
  container: string | string[];
  sample_rate: number | string | number[];
  bit_depth: number | string;
  channels?: number;
  dither: string;
  use?: string;
  [key: string]: unknown;
}

export interface ModelEntry {
  id: string;
  task: string;
  stems?: string[];
  architecture?: string;
  weights?: { source_url?: string | null; sha256?: string | null; size_bytes?: number | null };
  license: {
    code?: string;
    weights?: string;
    usage_restrictions?: string;
    evidence?: { url: string; checked_on?: string; note?: string }[];
    caveats?: string[];
  };
  attribution?: string;
  tier: string;
  status: string;
  installed?: boolean;
  [key: string]: unknown;
}

export interface ModelRegistry {
  status?: string;
  note?: string;
  models: ModelEntry[];
  excluded_from_standard_route?: { name: string; reason: string; allowed_via: string }[];
}

// ---------------------------------------------------------------------------
// Variants (objective x profile combinations offered to the GUI)
// ---------------------------------------------------------------------------

/** A director-layer direction applied on top of a variant's objective × profile
 * (its floor). Present only when the variant's mix carries director moves. */
export interface DirectionRef {
  id: string;
  pattern?: string;
  /** The natural-language request the direction answers (source text). */
  request?: Label;
  title?: Label;
}

export interface VariantSummary {
  id: string;
  n?: number;
  label?: Label;
  /** Objective ids in blend order (first = dominant). */
  objectives: string[];
  direction?: DirectionRef;
  objective?: ObjectiveSpec | null;
  profile: string;
  deliveries: string[];
  role?: string;
  intensity?: number;
  /** False when the data for this variant has not been generated yet. */
  available: boolean;
}

// ---------------------------------------------------------------------------
// Analysis (GET /api/analysis)
// ---------------------------------------------------------------------------

export interface StemPlacement {
  track: string;
  centroid_hz: number;
  /** 0 = far, 1 = near (P-09 depth score, normalized). */
  depth: number;
  level_db?: number;
  pan?: number;
}

export interface MaskingPair {
  a: string;
  b: string;
  band_hz: [number, number];
  amount_db: number;
  severity: "info" | "warning" | "critical";
}

export interface Diagnostic {
  id: string;
  metric?: string;
  label: Label;
  value: number | string | null;
  unit?: string;
  threshold?: number | string | null;
  status: "ok" | "warning" | "fail" | "not_run";
  note?: Label;
}

export interface MetricRow {
  id: string;
  label?: Label;
  before: number | null;
  after: number | null;
  unit?: string;
  better?: "higher" | "lower" | "in_range" | string;
}

export interface Analysis {
  schema_version: 1;
  synthetic?: boolean;
  variant?: string;
  loudness: {
    hop_s: number;
    before: number[];
    after?: number[] | null;
    integrated_lufs?: { before: number | null; after: number | null };
    true_peak_dbtp?: { before: number | null; after: number | null };
    lra_lu?: { before: number | null; after: number | null };
  };
  ltas: {
    freqs_hz: number[];
    before: number[];
    after?: number[] | null;
    reference?: { label?: Label; low: number[]; high: number[] } | null;
  };
  band_correlation: {
    bands: { id: string; lo_hz: number; hi_hz: number; before: number | null; after: number | null }[];
  };
  stems: StemPlacement[];
  masking: MaskingPair[];
  diagnostics: Diagnostic[];
  metrics?: MetricRow[];
}

// ---------------------------------------------------------------------------
// Plan proposals (GET /api/proposals, POST /api/plan/*)
// ---------------------------------------------------------------------------

export type Stage = "cleanup" | "mix" | "master";
export type Actor = "human" | "agent" | "planner";

export interface PlanStep {
  /** Track id, bus id, or "master". */
  target: string;
  processor: Processor;
  /** Parameter names that may be edited before applying (default: all params). */
  editable?: string[];
  alternatives?: Label[];
  note?: Label;
}

export interface Proposal {
  id: string;
  stage: Stage;
  variant?: string | null;
  author: Actor;
  status: "pending" | "applied" | "rejected";
  created_at?: string;
  summary?: Label;
  steps: PlanStep[];
  reject_reason?: string;
}

export type ParamEdits = Record<string, Record<string, unknown>>; // processor id -> params

// ---------------------------------------------------------------------------
// Verification (GET/POST /api/verify)
// ---------------------------------------------------------------------------

export interface Verification {
  schema_version: 1;
  synthetic?: boolean;
  variant: string;
  overall: CheckStatus;
  constraints: { id: string; status: CheckStatus; value?: number | string | null; limit?: number | string | null; note?: Label }[];
  gate: { status: CheckStatus; checks: { id: string; label?: Label; status: CheckStatus; note?: Label }[] };
  profiles: {
    profile: string;
    delivery?: string | null;
    status: CheckStatus;
    lufs_i?: number | null;
    true_peak_dbtp?: number | null;
    note?: Label;
  }[];
  noise_return: { status: CheckStatus; delta_db?: number | null; tolerance_db?: number | null; note?: Label };
  codec: { codec: string; status: CheckStatus; true_peak_dbtp?: number | null; ceiling_dbtp?: number | null; note?: Label }[];
}

// ---------------------------------------------------------------------------
// Audio set for A/B listening (GET /api/audio)
// ---------------------------------------------------------------------------

export interface AudioSet {
  variant: string;
  /** URLs (relative to the page or same-origin absolute paths). null = not available. */
  files: {
    before: string | null;
    after: string | null;
    delta?: string | null;
    before_level_matched?: string | null;
    fullmix_reference?: string | null;
  };
  /** Gain in dB applied to `match_target` so that Before and After have equal integrated loudness. */
  match_gain_db: number;
  /** The louder side, which is turned down (SPEC 15.2: match by lowering the louder one). */
  match_target: "before" | "after";
  measurements?: {
    before?: { lufs_i?: number | null; true_peak_dbtp?: number | null };
    after?: { lufs_i?: number | null; true_peak_dbtp?: number | null };
  };
  note?: Label;
}

// ---------------------------------------------------------------------------
// Mix Report (schemas/report.schema.json)
// ---------------------------------------------------------------------------

export interface Decision {
  measured?: unknown;
  rule?: string | null;
  action?: unknown;
  alternatives?: unknown[];
  result?: unknown;
  [key: string]: unknown;
}

export interface Report {
  schema_version?: 1;
  language?: string;
  synthetic?: boolean;
  summary: {
    project?: string;
    objective?: Record<string, unknown>;
    profiles?: unknown[];
    outputs?: unknown[];
    result?: "pass" | "fail" | "warning" | "incomplete";
    [key: string]: unknown;
  };
  inputs?: Record<string, unknown>;
  measurements?: { before?: Record<string, unknown>; after?: Record<string, unknown>; level_matched?: boolean; [k: string]: unknown };
  decisions?: Record<string, Decision[]>;
  objective_breakdown?: unknown;
  constraints?: unknown;
  cleanup?: unknown;
  tradeoffs?: unknown[];
  listening_checks?: { time_s?: number | null; point?: unknown; conditions?: unknown; [k: string]: unknown }[];
  reproducibility?: Record<string, unknown>;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// History (GET /api/history)
// ---------------------------------------------------------------------------

export interface HistoryEntry {
  seq: number;
  ts: string;
  actor: Actor;
  op: string;
  reason?: string | null;
  summary?: Label;
  undone?: boolean;
}

// ---------------------------------------------------------------------------
// Jobs and change events
// ---------------------------------------------------------------------------

export interface Job {
  job_id: string;
  kind: "render" | "export" | "analyze" | "verify";
  state: "queued" | "running" | "done" | "failed";
  progress?: number;
  result?: unknown;
  error?: string;
}

export type ChangeEvent =
  | { type: "project_changed"; seq?: number; actor?: Actor; content_hash?: string; summary?: Label }
  | { type: "proposal"; proposal_id: string; author: Actor; stage?: Stage }
  | { type: "job"; job: Job }
  | { type: "connection"; state: "open" | "lost" };
