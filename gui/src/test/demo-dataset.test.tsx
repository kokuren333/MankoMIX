// Loads a demo dataset written by tools/build_demo_data.py through the MockBackend, exactly as
// the Pages demo does. The folder is given by MANKOMIX_DEMO_DIR; without it the suite is skipped
// (the committed placeholder in public/demo/ is covered by backend.test.ts).
//
//   python -I tools/build_demo_data.py --project <song.mmx> --out tmp/demo_data [--mp3]
//   MANKOMIX_DEMO_DIR=../tmp/demo_data npm test
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { App } from "../App";
import { MockBackend } from "../backend/MockBackend";
import { FakeEngine, renderWithApp, setWidth } from "./helpers";

const DIR = process.env.MANKOMIX_DEMO_DIR ? resolve(process.env.MANKOMIX_DEMO_DIR) : "";

function backend(): MockBackend {
  const fetchFn = async (url: string): Promise<Response> => {
    const p = join(DIR, url.replace(/^\.?\/?demo\//, ""));
    if (!existsSync(p)) return new Response("not found", { status: 404 });
    return new Response(readFileSync(p, "utf8"), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return new MockBackend({ baseUrl: "demo/", fetchFn });
}

const ABS = /(^|[\s"'(=])(?:[A-Za-z]:[\\/]|\\\\|\/(?:Users|home|mnt|tmp|var|private|Volumes)\/)/;

describe.skipIf(!DIR)("generated demo dataset (MANKOMIX_DEMO_DIR)", () => {
  it("is a real (non-synthetic) dataset with definitions, project and history", async () => {
    const b = backend();
    const idx = await b.index();
    expect(idx.schema_version).toBe(1);
    expect(idx.synthetic).toBe(false);
    expect(idx.variants.length).toBeGreaterThan(0);
    const variants = await b.listVariants();
    expect(variants.map((v) => v.id)).toEqual(idx.variants.map((v) => v.id));
    const project = await b.getProject();
    expect(project.schema_version).toBe(1);
    expect(Array.isArray(project.tracks)).toBe(true);
    const cat = await b.listObjectives();
    expect(cat.objectives.some((o) => o.id === cat.default)).toBe(true);
    expect((await b.listProfiles()).length).toBeGreaterThan(0);
    expect((await b.listDeliveries()).length).toBeGreaterThan(0);
    expect((await b.listModels()).models.length).toBeGreaterThan(0);
    expect((await b.history()).length).toBeGreaterThan(0);
  });

  it("loads every per-variant file of every available variant", async () => {
    const b = backend();
    const vs = await b.listVariants();
    expect(vs.some((v) => v.available)).toBe(true);
    for (const v of vs.filter((x) => x.available)) {
      const a = await b.getAnalysis(v.id);
      expect(a.loudness.before.length).toBeGreaterThan(0);
      expect(a.ltas.freqs_hz.length).toBe(a.ltas.before.length);
      expect(Array.isArray(a.stems) && Array.isArray(a.masking) && Array.isArray(a.diagnostics)).toBe(true);
      expect((await b.listProposals(v.id)).length).toBeGreaterThan(0);
      const ver = await b.getVerification(v.id);
      expect(ver.constraints.map((c) => c.id)).toContain("S-01");
      expect((await b.getReport(v.id, "en")).language).toBe("en");
      expect((await b.getReport(v.id, "ja")).language).toBe("ja");
      const audio = await b.listAudio(v.id);
      expect(typeof audio.match_gain_db).toBe("number");
      expect(audio.match_gain_db).toBeLessThanOrEqual(0);
      expect(["before", "after"]).toContain(audio.match_target);
      // Every audio URL is a same-origin demo file that exists on disk.
      for (const url of Object.values(audio.files)) {
        if (!url) continue;
        expect(url.startsWith("demo/")).toBe(true);
        expect(existsSync(join(DIR, url.slice("demo/".length)))).toBe(true);
      }
    }
  });

  it("reports the variants that were not generated", async () => {
    const b = backend();
    for (const v of (await b.listVariants()).filter((x) => !x.available)) {
      await expect(b.getAnalysis(v.id)).rejects.toMatchObject({ code: "not_generated" });
    }
  });

  it("contains no absolute paths", async () => {
    const idx = await backend().index();
    const files = ["index.json", idx.project, idx.history ?? "history.json"];
    for (const v of idx.variants.filter((x) => x.available)) {
      for (const f of ["analysis.json", "plan.json", "verify.json", "report.ja.json", "report.en.json", "audio.json"]) {
        files.push(v.dir + f);
      }
    }
    for (const f of files) {
      const text = readFileSync(join(DIR, f), "utf8");
      expect(ABS.test(text), `${f} contains an absolute path`).toBe(false);
    }
  });
});

describe.skipIf(!DIR)("generated demo dataset in the app (MANKOMIX_DEMO_DIR)", () => {
  const ROUTES = ["project", "stems", "mixmap", "analysis", "intent", "plan", "listen", "verify", "report", "models", "history"];
  for (const route of ROUTES) {
    it(`renders the ${route} screen without a load error`, async () => {
      setWidth(1280);
      window.location.hash = `#/${route}`;
      renderWithApp(<App />, { backend: backend(), engineFactory: () => new FakeEngine() });
      await screen.findByTestId("app-root");
      await new Promise((r) => setTimeout(r, 100));
      const alerts = screen.queryAllByRole("alert").map((a) => a.textContent ?? "");
      expect(alerts, alerts.join(" | ")).toEqual([]);
    });
  }
});
