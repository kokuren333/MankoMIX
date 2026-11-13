import type {
  Analysis,
  AudioSet,
  ChangeEvent,
  DeliveryFormat,
  HistoryEntry,
  Job,
  Label,
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
import {
  BackendError,
  MOCK_CAPABILITIES,
  UnsupportedError,
  type Backend,
  type Capabilities,
  type PatchResult,
  type UndoResult,
  type Unsubscribe,
} from "./Backend";
import { normalizeCatalog, normalizeDeliveries, normalizeProfiles } from "./normalize";

/** One entry of demo/index.json (layout documented in gui/DEMO_DATA.md). */
export interface DemoVariant {
  id: string;
  n?: number;
  label?: Label;
  objective: string;
  profile: string;
  role?: string;
  deliveries?: string[];
  intensity?: number;
  available: boolean;
  /** Folder of the per-variant files, relative to the demo root (e.g. "variants/v01/"). */
  dir: string;
}

export interface DemoIndex {
  schema_version: 1;
  synthetic?: boolean;
  generator?: { name?: string; version?: string; note?: string };
  title?: Label;
  notice?: Label;
  project: string;
  history?: string;
  definitions: { objectives: string; profiles: string; deliveries: string; models?: string };
  intensity?: number;
  variants: DemoVariant[];
  verification_only_profiles?: string[];
}

type FetchFn = (url: string) => Promise<Response>;

export interface MockBackendOptions {
  /** Demo data root (default: "<BASE_URL>demo/", i.e. relative to the page). */
  baseUrl?: string;
  fetchFn?: FetchFn;
}

/**
 * In-browser mock for the GitHub Pages demo (SPEC 11.4). Reads precomputed
 * static JSON (and audio URLs) from the demo folder. Only same-origin static
 * files are requested; nothing is ever sent anywhere. Every operation that
 * would need real DSP, file upload, the agent link or model download throws
 * UnsupportedError, and capabilities() reports them as unavailable.
 */
export class MockBackend implements Backend {
  readonly kind = "mock" as const;
  private readonly base: string;
  private readonly fetchFn: FetchFn;
  private cache = new Map<string, Promise<unknown>>();

  constructor(opts: MockBackendOptions = {}) {
    const b = opts.baseUrl ?? `${import.meta.env.BASE_URL ?? "./"}demo/`;
    this.base = b.endsWith("/") ? b : b + "/";
    this.fetchFn = opts.fetchFn ?? ((url: string) => fetch(url, { credentials: "same-origin" }));
  }

  /** Resolve a demo-relative path to a URL usable by fetch/audio. */
  resolve(path: string): string {
    if (/^[a-z]+:/i.test(path) || path.startsWith("/")) {
      // Only same-origin, relative data is allowed in the demo.
      throw new BackendError(`Demo data must use relative paths: ${path}`, undefined, "bad_path");
    }
    return this.base + path.replace(/^\.\//, "");
  }

  private json<T>(path: string): Promise<T> {
    let p = this.cache.get(path);
    if (!p) {
      p = this.fetchFn(this.resolve(path)).then(async (res) => {
        if (!res.ok) throw new BackendError(`Demo file not found: ${path}`, res.status, "not_found");
        return res.json();
      });
      p.catch(() => this.cache.delete(path));
      this.cache.set(path, p);
    }
    return p as Promise<T>;
  }

  index(): Promise<DemoIndex> {
    return this.json<DemoIndex>("index.json");
  }

  private async variant(id: string): Promise<DemoVariant> {
    const idx = await this.index();
    const v = idx.variants.find((x) => x.id === id);
    if (!v) throw new BackendError(`Unknown demo variant: ${id}`, 404, "not_found");
    if (!v.available) throw new BackendError(`Demo data for ${id} has not been generated`, 404, "not_generated");
    return v;
  }

  private async variantFile<T>(id: string, file: string): Promise<T> {
    const v = await this.variant(id);
    const dir = v.dir.endsWith("/") ? v.dir : v.dir + "/";
    return this.json<T>(dir + file);
  }

  async capabilities(): Promise<Capabilities> {
    return { ...MOCK_CAPABILITIES };
  }

  async getProject(): Promise<Project> {
    const idx = await this.index();
    return this.json<Project>(idx.project);
  }

  patchProject(_ops: PatchOp[], _reason?: string): Promise<PatchResult> {
    return Promise.reject(new UnsupportedError("patchProject"));
  }

  importFiles(_files: File[]): Promise<Job | PatchResult> {
    return Promise.reject(new UnsupportedError("importFiles"));
  }

  async history(limit = 50): Promise<HistoryEntry[]> {
    const idx = await this.index();
    if (!idx.history) return [];
    const data = await this.json<{ entries: HistoryEntry[] } | HistoryEntry[]>(idx.history);
    const entries = Array.isArray(data) ? data : data.entries ?? [];
    return [...entries].sort((a, b) => b.seq - a.seq).slice(0, limit);
  }

  undo(): Promise<UndoResult> {
    return Promise.reject(new UnsupportedError("undo"));
  }

  async listObjectives(): Promise<ObjectiveCatalog> {
    const idx = await this.index();
    return normalizeCatalog(await this.json(idx.definitions.objectives));
  }

  async listProfiles(): Promise<MediaProfile[]> {
    const idx = await this.index();
    return normalizeProfiles(await this.json(idx.definitions.profiles));
  }

  async listDeliveries(): Promise<DeliveryFormat[]> {
    const idx = await this.index();
    return normalizeDeliveries(await this.json(idx.definitions.deliveries));
  }

  async listModels(): Promise<ModelRegistry> {
    const idx = await this.index();
    if (!idx.definitions.models) return { models: [] };
    return this.json<ModelRegistry>(idx.definitions.models);
  }

  pullModel(_id: string): Promise<Job> {
    return Promise.reject(new UnsupportedError("pullModel"));
  }

  async listVariants(): Promise<VariantSummary[]> {
    const idx = await this.index();
    return idx.variants.map((v) => ({
      id: v.id,
      n: v.n,
      label: v.label,
      objectives: [v.objective],
      objective: { blend: [{ id: v.objective, weight: 1 }], intensity: v.intensity ?? idx.intensity ?? 0.5 },
      profile: v.profile,
      deliveries: v.deliveries ?? [],
      role: v.role,
      intensity: v.intensity ?? idx.intensity,
      available: v.available,
    }));
  }

  getAnalysis(variant: string): Promise<Analysis> {
    return this.variantFile<Analysis>(variant, "analysis.json");
  }

  analyze(): Promise<Job> {
    return Promise.reject(new UnsupportedError("analyze"));
  }

  async listProposals(variant: string): Promise<Proposal[]> {
    const data = await this.variantFile<{ proposals: Proposal[] } | Proposal[]>(variant, "plan.json");
    return Array.isArray(data) ? data : data.proposals ?? [];
  }

  proposePlan(_stage: Stage, _variant: string): Promise<Proposal> {
    return Promise.reject(new UnsupportedError("proposePlan"));
  }

  applyPlan(_proposalId: string, _edits?: ParamEdits): Promise<PatchResult> {
    return Promise.reject(new UnsupportedError("applyPlan"));
  }

  rejectPlan(_proposalId: string, _reason: string): Promise<void> {
    return Promise.reject(new UnsupportedError("rejectPlan"));
  }

  render(_variant: string): Promise<Job> {
    return Promise.reject(new UnsupportedError("render"));
  }

  exportOutputs(_variant: string): Promise<Job> {
    return Promise.reject(new UnsupportedError("exportOutputs"));
  }

  getJob(_jobId: string): Promise<Job> {
    return Promise.reject(new UnsupportedError("getJob"));
  }

  getVerification(variant: string): Promise<Verification> {
    return this.variantFile<Verification>(variant, "verify.json");
  }

  /** The demo cannot run verification; it returns the precomputed result. */
  verify(variant: string): Promise<Verification> {
    return this.getVerification(variant);
  }

  async getReport(variant: string, lang: Lang): Promise<Report> {
    try {
      return await this.variantFile<Report>(variant, `report.${lang}.json`);
    } catch (e) {
      if (e instanceof BackendError && e.code === "not_found") return this.variantFile<Report>(variant, "report.json");
      throw e;
    }
  }

  async listAudio(variant: string): Promise<AudioSet> {
    const set = await this.variantFile<AudioSet>(variant, "audio.json");
    const files = { ...set.files } as Record<string, string | null | undefined>;
    for (const [k, v] of Object.entries(files)) files[k] = v ? this.resolve(v) : null;
    return { ...set, files: files as AudioSet["files"] };
  }

  subscribe(_onChange: (event: ChangeEvent) => void): Unsubscribe {
    // No agent link and no server in the demo: nothing ever changes.
    return () => {};
  }
}
