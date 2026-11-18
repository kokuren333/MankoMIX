import type {
  Analysis,
  AudioSet,
  ChangeEvent,
  DeliveryFormat,
  HistoryEntry,
  Job,
  Lang,
  MediaProfile,
  ModelRegistry,
  ObjectiveCatalog,
  ParamEdits,
  PatchOp,
  Project,
  Proposal,
  Report,
  Stage,
  Verification,
  VariantSummary,
} from "../types";

/**
 * What the connected backend allows. The UI must disable (and explain) every
 * action whose capability is false instead of failing at click time.
 */
export interface Capabilities {
  mode: "local" | "mock";
  /** Edit the canonical project (stems, intent, outputs) via patch. */
  editProject: boolean;
  /** Import arbitrary audio into the project. */
  importAudio: boolean;
  /** Run analysis on the server. */
  runAnalysis: boolean;
  /** Ask the deterministic planner for a new proposal. */
  runPlanner: boolean;
  /** Apply or reject planner proposals. */
  applyPlan: boolean;
  /** Real DSP renders and final exports. */
  render: boolean;
  /** Run verification on the server. */
  runVerify: boolean;
  /** Undo / checkout in the history. */
  undo: boolean;
  /** External agent link: follow agent changes, approve/reject agent proposals (D-035). */
  agentLink: boolean;
  /** Server push of project changes. */
  liveUpdates: boolean;
  /** Download model weights from the registry. */
  modelDownload: boolean;
}

export const MOCK_CAPABILITIES: Capabilities = {
  mode: "mock",
  editProject: false,
  importAudio: false,
  runAnalysis: false,
  runPlanner: false,
  applyPlan: false,
  render: false,
  runVerify: false,
  undo: false,
  agentLink: false,
  liveUpdates: false,
  modelDownload: false,
};

export interface PatchResult {
  applied: number;
  content_hash?: string | null;
}

export interface UndoResult {
  undone: unknown;
  content_hash?: string | null;
}

export type Unsubscribe = () => void;

export interface Backend {
  getPitchNotes?(options: import("./observations").ObservationOptions & { lo_hz?: number; hi_hz?: number; a4?: number }): Promise<import("./observations").NoteObservation>;
  getMeters?(options: import("./observations").ObservationOptions & { what?: string; points?: number }): Promise<import("./observations").MeterObservation>;
  previewSpectralRepair?(options: import("./observations").ObservationOptions & { params: import("./observations").SpectralParams }): Promise<import("./observations").SpectralPreview>;
}

/** Raised when an operation is not available on the connected backend. */
export class UnsupportedError extends Error {
  constructor(public readonly operation: string) {
    super(`Operation not available on this backend: ${operation}`);
    this.name = "UnsupportedError";
  }
}

/** Raised for HTTP / data errors; `code` mirrors the core error codes when present. */
export class BackendError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code?: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "BackendError";
  }
}

/**
 * Backend connection. Mirrors the core API (core/api.py) one to one; the GUI
 * holds no processing logic of its own (SPEC 11.1). Every method is async.
 * Variant ids refer to project variants (local) or demo variants (mock).
 */
export interface Backend {
  readonly kind: "local" | "mock";

  capabilities(): Promise<Capabilities>;

  // Project (core: status / project_get / patch)
  getProject(): Promise<Project>;
  patchProject(ops: PatchOp[], reason?: string): Promise<PatchResult>;
  importFiles(files: File[]): Promise<Job | PatchResult>;

  // History (core: history / undo)
  history(limit?: number): Promise<HistoryEntry[]>;
  undo(): Promise<UndoResult>;

  // Definitions (core: objective_list / profile_list / delivery list / model_list)
  listObjectives(): Promise<ObjectiveCatalog>;
  listProfiles(): Promise<MediaProfile[]>;
  listDeliveries(): Promise<DeliveryFormat[]>;
  listModels(): Promise<ModelRegistry>;
  pullModel(id: string): Promise<Job>;

  // Variants (objective x profile combinations)
  listVariants(): Promise<VariantSummary[]>;

  // Analysis (core: analyze)
  getAnalysis(variant: string): Promise<Analysis>;
  analyze(): Promise<Job>;

  // Plans (core: plan_propose / plan_apply)
  listProposals(variant: string): Promise<Proposal[]>;
  proposePlan(stage: Stage, variant: string): Promise<Proposal>;
  applyPlan(proposalId: string, edits?: ParamEdits): Promise<PatchResult>;
  rejectPlan(proposalId: string, reason: string): Promise<void>;

  // Render / export (local only)
  render(variant: string, range?: { start_s: number; end_s: number }): Promise<Job>;
  exportOutputs(variant: string): Promise<Job>;
  getJob(jobId: string): Promise<Job>;

  // Verification and report (core: verify_run / report_get)
  getVerification(variant: string): Promise<Verification>;
  verify(variant: string): Promise<Verification | Job>;
  getReport(variant: string, lang: Lang): Promise<Report>;

  // Listening
  listAudio(variant: string): Promise<AudioSet>;

  /** Push notifications of project changes (SSE in local mode; no-op in mock). */
  subscribe(onChange: (event: ChangeEvent) => void): Unsubscribe;
}
