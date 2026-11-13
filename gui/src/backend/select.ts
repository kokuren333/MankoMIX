import type { Backend } from "./Backend";
import { LocalBackend } from "./LocalBackend";
import { MockBackend } from "./MockBackend";

export type BackendKind = "local" | "mock";

/**
 * Backend selection: `?backend=mock|local` in the page URL wins, then the
 * build-time VITE_BACKEND (set to "mock" by `npm run build:demo`), then local.
 */
export function selectBackendKind(search: string, buildDefault: string | undefined): BackendKind {
  const q = new URLSearchParams(search).get("backend");
  if (q === "mock" || q === "local") return q;
  return buildDefault === "mock" ? "mock" : "local";
}

export function createBackend(kind: BackendKind): Backend {
  return kind === "mock" ? new MockBackend() : new LocalBackend();
}
