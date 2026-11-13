import { readFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { AppProvider } from "../AppContext";
import { MockBackend } from "../backend/MockBackend";
import type { Backend, Capabilities } from "../backend/Backend";
import type { AudioEngine, EngineFactory, LoadStatus } from "../audio/engine";
import type { MonitorSettings, SourceId } from "../audio/gains";
import type { Lang } from "../types";

const here = dirname(fileURLToPath(import.meta.url));
export const GUI_ROOT = resolve(here, "..", "..");
export const REPO_ROOT = resolve(GUI_ROOT, "..");
export const DEMO_DIR = join(GUI_ROOT, "public", "demo");

/** fetch replacement serving public/demo/ from disk (base URL "demo/"). */
export async function fsFetch(url: string): Promise<Response> {
  const rel = url.replace(/^\.?\/?demo\//, "");
  const p = join(DEMO_DIR, rel);
  if (!existsSync(p)) return new Response("not found", { status: 404 });
  return new Response(readFileSync(p, "utf8"), { status: 200, headers: { "Content-Type": "application/json" } });
}

export function demoBackend(): MockBackend {
  return new MockBackend({ baseUrl: "demo/", fetchFn: fsFetch });
}

/** Mock data, but reporting full local capabilities (to test enabled controls). */
export class FullCapsBackend extends MockBackend {
  constructor() {
    super({ baseUrl: "demo/", fetchFn: fsFetch });
  }
  async capabilities(): Promise<Capabilities> {
    return {
      mode: "local",
      editProject: true,
      importAudio: true,
      runAnalysis: true,
      runPlanner: true,
      applyPlan: true,
      render: true,
      runVerify: true,
      undo: true,
      agentLink: true,
      liveUpdates: false,
      modelDownload: true,
    };
  }
}

/** Recording fake for the audio engine. */
export class FakeEngine implements AudioEngine {
  supported = true;
  gains: Record<SourceId, number>[] = [];
  monitors: MonitorSettings[] = [];
  loaded: Partial<Record<SourceId, string | null>>[] = [];
  async load(urls: Partial<Record<SourceId, string | null>>): Promise<Record<SourceId, LoadStatus>> {
    this.loaded.push(urls);
    return { before: urls.before ? "ok" : "none", after: urls.after ? "ok" : "none", delta: urls.delta ? "ok" : "none" };
  }
  async play() {}
  pause() {}
  seek() {}
  isPlaying() {
    return false;
  }
  currentTime() {
    return 0;
  }
  duration() {
    return 99;
  }
  setSourceGains(g: Record<SourceId, number>) {
    this.gains.push({ ...g });
  }
  setMonitor(m: MonitorSettings) {
    this.monitors.push({ ...m });
  }
  dispose() {}
  lastGains() {
    return this.gains[this.gains.length - 1];
  }
}

export function renderWithApp(ui: ReactNode, opts: { backend?: Backend; lang?: Lang; engineFactory?: EngineFactory } = {}) {
  return render(
    <AppProvider backend={opts.backend ?? demoBackend()} lang={opts.lang ?? "en"} engineFactory={opts.engineFactory}>
      {ui}
    </AppProvider>,
  );
}

export function setWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: width });
  window.dispatchEvent(new Event("resize"));
}
