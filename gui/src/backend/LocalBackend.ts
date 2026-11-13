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
import {
  BackendError,
  type Backend,
  type Capabilities,
  type PatchResult,
  type UndoResult,
  type Unsubscribe,
} from "./Backend";
import { normalizeCatalog, normalizeDeliveries, normalizeProfiles, variantsFromProject } from "./normalize";

type FetchFn = typeof fetch;

export interface LocalBackendOptions {
  /** API root; same-origin by default. */
  baseUrl?: string;
  fetchFn?: FetchFn;
  /** EventSource constructor (injectable for tests). */
  eventSource?: typeof EventSource;
  /** Polling interval used when EventSource is unavailable. */
  pollMs?: number;
}

/**
 * HTTP client for `mankomix serve`. Endpoints are listed in gui/API.md.
 * All requests are same-origin JSON; the server identifies GUI writes as actor "human".
 */
export class LocalBackend implements Backend {
  readonly kind = "local" as const;
  private readonly base: string;
  private readonly fetchFn: FetchFn;
  private readonly es?: typeof EventSource;
  private readonly pollMs: number;

  constructor(opts: LocalBackendOptions = {}) {
    this.base = (opts.baseUrl ?? "/api").replace(/\/$/, "");
    this.fetchFn = opts.fetchFn ?? ((...a) => fetch(...a));
    this.es = opts.eventSource ?? (typeof EventSource !== "undefined" ? EventSource : undefined);
    this.pollMs = opts.pollMs ?? 3000;
  }

  private async request<T>(method: string, path: string, body?: unknown, query?: Record<string, string | number | undefined>): Promise<T> {
    let url = this.base + path;
    if (query) {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) if (v !== undefined) q.set(k, String(v));
      const s = q.toString();
      if (s) url += "?" + s;
    }
    const init: RequestInit = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (body instanceof FormData) {
      init.body = body;
    } else if (body !== undefined) {
      init.body = JSON.stringify(body);
      (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    }
    let res: Response;
    try {
      res = await this.fetchFn(url, init);
    } catch (e) {
      throw new BackendError(`Cannot reach the local server (${(e as Error).message})`, 0, "network");
    }
    const text = await res.text();
    let data: unknown = undefined;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        throw new BackendError(`Invalid JSON from ${method} ${path}`, res.status, "bad_json");
      }
    }
    if (!res.ok) {
      const err = (data as { error?: { code?: string; message?: string; details?: unknown } } | undefined)?.error;
      throw new BackendError(err?.message ?? `${method} ${path} failed (${res.status})`, res.status, err?.code, err?.details);
    }
    return data as T;
  }

  capabilities(): Promise<Capabilities> {
    return this.request<Partial<Capabilities>>("GET", "/capabilities").then((c) => ({
      mode: "local",
      editProject: c.editProject ?? true,
      importAudio: c.importAudio ?? true,
      runAnalysis: c.runAnalysis ?? true,
      runPlanner: c.runPlanner ?? true,
      applyPlan: c.applyPlan ?? true,
      render: c.render ?? true,
      runVerify: c.runVerify ?? true,
      undo: c.undo ?? true,
      agentLink: c.agentLink ?? true,
      liveUpdates: c.liveUpdates ?? true,
      modelDownload: c.modelDownload ?? true,
    }));
  }

  getProject(): Promise<Project> {
    return this.request("GET", "/project");
  }

  patchProject(ops: PatchOp[], reason?: string): Promise<PatchResult> {
    return this.request("PATCH", "/project", { ops, reason });
  }

  importFiles(files: File[]): Promise<Job | PatchResult> {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    return this.request("POST", "/import", form);
  }

  async history(limit = 50): Promise<HistoryEntry[]> {
    const r = await this.request<{ entries: HistoryEntry[] } | HistoryEntry[]>("GET", "/history", undefined, { limit });
    return Array.isArray(r) ? r : r.entries ?? [];
  }

  undo(): Promise<UndoResult> {
    return this.request("POST", "/history/undo", {});
  }

  async listObjectives(): Promise<ObjectiveCatalog> {
    return normalizeCatalog(await this.request("GET", "/objectives"));
  }

  async listProfiles(): Promise<MediaProfile[]> {
    return normalizeProfiles(await this.request("GET", "/profiles"));
  }

  async listDeliveries(): Promise<DeliveryFormat[]> {
    return normalizeDeliveries(await this.request("GET", "/deliveries"));
  }

  listModels(): Promise<ModelRegistry> {
    return this.request("GET", "/models");
  }

  pullModel(id: string): Promise<Job> {
    return this.request("POST", `/models/${encodeURIComponent(id)}/pull`, {});
  }

  async listVariants(): Promise<VariantSummary[]> {
    try {
      return await this.request<VariantSummary[]>("GET", "/variants");
    } catch (e) {
      // Older servers: derive the list from the project document.
      if (e instanceof BackendError && e.status === 404) return variantsFromProject(await this.getProject());
      throw e;
    }
  }

  getAnalysis(variant: string): Promise<Analysis> {
    return this.request("GET", "/analysis", undefined, { variant });
  }

  analyze(): Promise<Job> {
    return this.request("POST", "/analyze", {});
  }

  listProposals(variant: string): Promise<Proposal[]> {
    return this.request<{ proposals: Proposal[] } | Proposal[]>("GET", "/proposals", undefined, { variant }).then((r) =>
      Array.isArray(r) ? r : r.proposals ?? [],
    );
  }

  proposePlan(stage: Stage, variant: string): Promise<Proposal> {
    return this.request("POST", "/plan/propose", { stage, variant });
  }

  applyPlan(proposalId: string, edits?: ParamEdits): Promise<PatchResult> {
    return this.request("POST", "/plan/apply", { proposal_id: proposalId, edits: edits ?? {} });
  }

  async rejectPlan(proposalId: string, reason: string): Promise<void> {
    await this.request("POST", "/plan/reject", { proposal_id: proposalId, reason });
  }

  render(variant: string, range?: { start_s: number; end_s: number }): Promise<Job> {
    return this.request("POST", "/render", { variant, range: range ?? null });
  }

  exportOutputs(variant: string): Promise<Job> {
    return this.request("POST", "/export", { variant });
  }

  getJob(jobId: string): Promise<Job> {
    return this.request("GET", `/jobs/${encodeURIComponent(jobId)}`);
  }

  getVerification(variant: string): Promise<Verification> {
    return this.request("GET", "/verify", undefined, { variant });
  }

  verify(variant: string): Promise<Verification | Job> {
    return this.request("POST", "/verify", { variant });
  }

  getReport(variant: string, lang: Lang): Promise<Report> {
    return this.request("GET", "/report", undefined, { variant, lang });
  }

  listAudio(variant: string): Promise<AudioSet> {
    return this.request("GET", "/audio", undefined, { variant });
  }

  subscribe(onChange: (event: ChangeEvent) => void): Unsubscribe {
    if (this.es) {
      const source = new this.es(this.base + "/events");
      const forward = (type: string) => (msg: MessageEvent) => {
        try {
          const payload = msg.data ? JSON.parse(msg.data) : {};
          onChange({ ...payload, type } as ChangeEvent);
        } catch {
          // Ignore malformed events; the next event or a reload resyncs.
        }
      };
      const types = ["project_changed", "proposal", "job"];
      const handlers = types.map((t) => [t, forward(t)] as const);
      for (const [t, h] of handlers) source.addEventListener(t, h as EventListener);
      source.onopen = () => onChange({ type: "connection", state: "open" });
      source.onerror = () => onChange({ type: "connection", state: "lost" });
      return () => {
        for (const [t, h] of handlers) source.removeEventListener(t, h as EventListener);
        source.close();
      };
    }
    // Fallback: poll the history head and report a change when it moves.
    let last: number | undefined;
    let stopped = false;
    const tick = async () => {
      try {
        const [head] = await this.history(1);
        if (head && last !== undefined && head.seq !== last) {
          onChange({ type: "project_changed", seq: head.seq, actor: head.actor, summary: head.summary });
        }
        last = head?.seq ?? last;
      } catch {
        onChange({ type: "connection", state: "lost" });
      }
    };
    void tick();
    const timer = setInterval(() => {
      if (!stopped) void tick();
    }, this.pollMs);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }
}
