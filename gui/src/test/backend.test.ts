import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { BackendError, UnsupportedError } from "../backend/Backend";
import { LocalBackend } from "../backend/LocalBackend";
import { selectBackendKind } from "../backend/select";
import { DEMO_DIR, REPO_ROOT, demoBackend } from "./helpers";

describe("MockBackend", () => {
  it("loads the demo index, definitions and project", async () => {
    const b = demoBackend();
    const idx = await b.index();
    expect(idx.schema_version).toBe(1);
    expect(idx.variants.length).toBeGreaterThan(0);
    const variants = await b.listVariants();
    expect(variants.map((v) => v.id)).toEqual(idx.variants.map((v) => v.id));
    const project = await b.getProject();
    expect(project.schema_version).toBe(1);
    expect(project.tracks.length).toBeGreaterThan(0);
    const cat = await b.listObjectives();
    expect(cat.objectives.some((o) => o.id === cat.default)).toBe(true);
    expect((await b.listProfiles()).length).toBeGreaterThan(0);
    expect((await b.listDeliveries()).length).toBeGreaterThan(0);
    expect((await b.listModels()).models.length).toBeGreaterThan(0);
    expect((await b.history()).length).toBeGreaterThan(0);
  });

  it("carries the direction metadata of the committed example", async () => {
    const b = demoBackend();
    const v = (await b.listVariants()).find((x) => x.available)!;
    // The committed dataset is the main sample direction example (gui/DEMO_DATA.md):
    // its headline is the direction, not its comfort × streaming floor.
    expect(v.direction?.id).toBe("dir_cf3e85c484fa");
    expect(v.direction?.pattern).toBe("sample_main");
    expect(JSON.stringify(v.direction)).toContain("空間音響 × 複雑で心地の良いパンニング");
    expect(JSON.stringify(v.label)).toContain("空間音響 × 複雑で心地の良いパンニング");
    expect(JSON.stringify(v.label)).toContain("土台");
  });

  it("loads every per-variant file of an available variant", async () => {
    const b = demoBackend();
    const v = (await b.listVariants()).find((x) => x.available)!;
    const a = await b.getAnalysis(v.id);
    expect(a.loudness.before.length).toBeGreaterThan(0);
    expect(a.ltas.freqs_hz.length).toBe(a.ltas.before.length);
    expect((await b.listProposals(v.id)).length).toBeGreaterThan(0);
    const ver = await b.getVerification(v.id);
    expect(ver.constraints.map((c) => c.id)).toContain("S-01");
    const en = await b.getReport(v.id, "en");
    const ja = await b.getReport(v.id, "ja");
    expect(en.language).toBe("en");
    expect(ja.language).toBe("ja");
    const audio = await b.listAudio(v.id);
    expect(typeof audio.match_gain_db).toBe("number");
    expect(["before", "after"]).toContain(audio.match_target);
  });

  it("reports a missing variant as not generated", async () => {
    const b = demoBackend();
    const missing = (await b.listVariants()).find((x) => !x.available);
    if (!missing) return;
    await expect(b.getAnalysis(missing.id)).rejects.toMatchObject({ code: "not_generated" });
  });

  it("disables every IO / agent capability and rejects those calls", async () => {
    const b = demoBackend();
    const { mode, ...flags } = await b.capabilities();
    expect(mode).toBe("mock");
    expect(Object.values(flags).every((f) => f === false)).toBe(true);
    await expect(b.patchProject([])).rejects.toBeInstanceOf(UnsupportedError);
    await expect(b.importFiles([])).rejects.toBeInstanceOf(UnsupportedError);
    await expect(b.applyPlan("x")).rejects.toBeInstanceOf(UnsupportedError);
    await expect(b.rejectPlan("x", "r")).rejects.toBeInstanceOf(UnsupportedError);
    await expect(b.render("v01")).rejects.toBeInstanceOf(UnsupportedError);
    await expect(b.pullModel("x")).rejects.toBeInstanceOf(UnsupportedError);
    await expect(b.undo()).rejects.toBeInstanceOf(UnsupportedError);
  });

  it("only accepts relative demo paths (no cross-origin requests)", () => {
    const b = demoBackend();
    expect(b.resolve("variants/v01/audio.json")).toBe("demo/variants/v01/audio.json");
    expect(() => b.resolve("https://example.invalid/x.mp3")).toThrow(BackendError);
    expect(() => b.resolve("/abs/x.mp3")).toThrow(BackendError);
  });

  it("keeps demo definitions identical to the canonical data files", () => {
    const pairs = [
      ["objectives/catalog.json", "definitions/objectives.json"],
      ["profiles/media_profiles.json", "definitions/media_profiles.json"],
      ["profiles/delivery_formats.json", "definitions/delivery_formats.json"],
      ["registry/models.json", "definitions/models.json"],
    ];
    for (const [src, dst] of pairs) {
      const a = JSON.parse(readFileSync(join(REPO_ROOT, src), "utf8"));
      const b = JSON.parse(readFileSync(join(DEMO_DIR, dst), "utf8"));
      expect(b, `${dst} is out of date: run npm run demo:sync-defs`).toEqual(a);
    }
  });

  it("commits a generated (non-synthetic) dataset whose referenced audio files exist", async () => {
    // The committed demo is a real dataset built by tools/build_demo_data.py (gui/DEMO_DATA.md);
    // the sample-set placeholder it replaced is covered by regenerating it locally.
    const b = demoBackend();
    const idx = await b.index();
    expect(idx.synthetic).toBe(false);
    for (const v of idx.variants.filter((x) => x.available)) {
      const audio = await b.listAudio(v.id);
      for (const url of Object.values(audio.files)) {
        if (!url) continue;
        expect(url.startsWith("demo/")).toBe(true);
        expect(existsSync(join(DEMO_DIR, url.slice("demo/".length))), url).toBe(true);
      }
    }
  });
});

describe("backend selection", () => {
  it("prefers the query parameter, then the build default", () => {
    expect(selectBackendKind("?backend=mock", "local")).toBe("mock");
    expect(selectBackendKind("?backend=local", "mock")).toBe("local");
    expect(selectBackendKind("", "mock")).toBe("mock");
    expect(selectBackendKind("", undefined)).toBe("local");
  });
});

describe("LocalBackend", () => {
  it("calls the documented endpoints and surfaces server errors", async () => {
    const calls: { url: string; method: string; body?: string }[] = [];
    const fetchFn = (async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
      if (url.startsWith("/api/report")) return new Response(JSON.stringify({ error: { code: "not_found", message: "no report" } }), { status: 404 });
      return new Response(JSON.stringify({ applied: 1, entries: [] }), { status: 200 });
    }) as typeof fetch;
    const b = new LocalBackend({ fetchFn });
    await b.patchProject([{ op: "replace", path: "/title", value: "x" }], "why");
    await b.history(5);
    await b.applyPlan("p1", { prc_1: { gain_db: -1 } });
    await expect(b.getReport("v01", "ja")).rejects.toMatchObject({ status: 404, code: "not_found", message: "no report" });
    expect(calls[0]).toMatchObject({ url: "/api/project", method: "PATCH" });
    expect(JSON.parse(calls[0].body!)).toEqual({ ops: [{ op: "replace", path: "/title", value: "x" }], reason: "why" });
    expect(calls[1].url).toBe("/api/history?limit=5");
    expect(calls[2]).toMatchObject({ url: "/api/plan/apply", method: "POST" });
    expect(JSON.parse(calls[2].body!)).toEqual({ proposal_id: "p1", edits: { prc_1: { gain_db: -1 } } });
    expect(calls[3].url).toBe("/api/report?variant=v01&lang=ja");
  });
});
