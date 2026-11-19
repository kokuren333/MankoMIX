import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { App } from "../App";
import { MockBackend, type DemoIndex } from "../backend/MockBackend";
import { STRINGS } from "../i18n/strings";
import { FakeEngine, renderWithApp } from "./helpers";
import type { Lang } from "../types";

// Entirely in-memory synthetic dataset: no source project or audio files needed.
function fixture(rule = "S-08") {
  const variants: DemoIndex["variants"] = [
    { id: "v01", n: 1, objective: "comfort", profile: "stream", available: true, dir: "variants/v01/" },
    { id: "v02", n: 2, objective: "clarity", profile: "stream", available: true, dir: "variants/v02/", project: "variants/v02/project.json", history: "variants/v02/history.json", source: { project_id: "p2", content_hash: "hash2" } },
    ...[9, 10, 11].map((n) => ({ id: `v${n}`, n, objective: `stopped${n}`, profile: "stream", available: false, dir: "", unavailable_reason: "not_rendered", stopped: { at: "master", rule } })),
    { id: "missing", objective: "missing", profile: "stream", available: false, dir: "", unavailable_reason: "not_in_project" },
  ];
  const index: DemoIndex = { schema_version: 1, project: "project.json", history: "history.json", definitions: { objectives: "objectives.json", profiles: "profiles.json", deliveries: "deliveries.json" }, variants };
  const project = (name: string, pan: number) => ({
    schema_version: 1, id: name, title: name, timebase: { sample_rate: 48000, bpm: null, key: null, length_samples: 48000, conform_policy: {} },
    tracks: [{ id: "lead", name, role: "vocals", pan: { position: pan }, processors: [], sends: [] }], assets: [], buses: [],
    mix: { pan_law_center_db: -3 }, objective: { blend: [{ id: "comfort", weight: 1 }], intensity: 0.5 }, engine: { min_version: "0.1" },
  });
  const history = (summary: string, seq: number) => [{ seq, summary, actor: "human", op: "patch", ts: "2026-01-01T00:00:00Z" }];
  const analysis = { schema_version: 1, stems: [{ track: "lead", centroid_hz: 1000, depth: 0.5 }], masking: [], loudness: { hop_s: 1, before: [] }, ltas: { freqs_hz: [], before: [] }, band_correlation: { bands: [] }, diagnostics: [] };
  const files: Record<string, unknown> = {
    "index.json": index, "project.json": project("Main direction hand", -0.8), "history.json": { entries: history("Main direction history", 1) },
    "variants/v02/project.json": project("Second project hand", 0.6), "variants/v02/history.json": history("Second project history", 2),
    "objectives.json": { default: "comfort", objectives: variants.map((v) => ({ id: v.objective, label: v.objective })) },
    "profiles.json": [{ id: "stream", label: "stream", loudness: { target_lufs_i: -14 }, true_peak: { ceiling_dbtp: -1 } }], "deliveries.json": [],
    "variants/v01/analysis.json": analysis, "variants/v02/analysis.json": analysis,
    "variants/v01/audio.json": { files: { before: "audio/before.mp3", after: "variants/v01/after.mp3" }, measurements: { before: { lufs_i: -19.5, true_peak_dbtp: -2 }, after: { lufs_i: -14, true_peak_dbtp: -1 } } },
  };
  const fetchFn = vi.fn(async (url: string) => {
    const path = url.replace(/^demo\//, "");
    return path in files ? new Response(JSON.stringify(files[path])) : new Response("missing", { status: 404 });
  });
  return { backend: new MockBackend({ baseUrl: "demo/", fetchFn }), fetchFn };
}

async function select(id: string, lang: Lang = "en") {
  const picker = await screen.findByRole("combobox", { name: STRINGS[lang]["app.variant"] });
  await waitFor(() => expect(within(picker).getAllByRole("option").length).toBe(6));
  fireEvent.change(picker, { target: { value: id } });
  return picker;
}

describe("stopped variants", () => {
  it("keeps the approved Japanese and English reason text verbatim", () => {
    expect(STRINGS.ja["stopped.reason"]).toBe("未完成（音声なし）。マスター段で停止しました。ノイズ戻り監視（S-08）が合格せず、ミックス段へ差し戻されています。許容幅は緩めていません。");
    expect(STRINGS.en["stopped.reason"]).toBe("Not finished (no audio). Stopped at the master stage: the noise-return guard (S-08) did not pass and the variant was sent back to the mix stage. The tolerance was not relaxed.");
  });
  it("disposes the previous player immediately when selecting a stopped variant", async () => {
    window.location.hash = "#/listen";
    const engine = new FakeEngine();
    const dispose = vi.spyOn(engine, "dispose");
    renderWithApp(<App />, { backend: fixture().backend, engineFactory: () => engine });
    await screen.findByTestId("measurement-before");
    await waitFor(() => expect(screen.getByRole("button", { name: STRINGS.en["listen.play"] }).hasAttribute("disabled")).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: STRINGS.en["listen.play"] }));
    const loads = engine.loaded.length;
    await select("v9");
    expect(dispose).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("measurement-before")).toBeNull();
    expect(screen.queryByRole("button", { name: STRINGS.en["listen.play"] })).toBeNull();
    expect(engine.loaded.length).toBe(loads);
  });
  for (const lang of ["ja", "en"] as const) {
    for (const route of ["analysis", "plan", "listen", "verify", "report"]) {
      it(`${lang}: ${route} shows the exact reason and hides audio and measurements`, async () => {
        window.location.hash = `#/${route}`;
        const { backend, fetchFn } = fixture();
        const engine = new FakeEngine();
        renderWithApp(<App />, { backend, lang, engineFactory: () => engine });
        const picker = await select("v9", lang);
        const suffix = lang === "ja" ? "未完成・音声なし（S-08）" : "not finished · no audio (S-08)";
        for (const n of [9, 10, 11]) expect(within(picker).getByRole("option", { name: new RegExp(`#${n} .*${suffix.replace(/[()]/g, "\\$&")}`) })).toBeTruthy();
        expect(screen.getByTestId("stopped-banner").textContent).toBe(STRINGS[lang]["stopped.reason"]);
        const main = screen.getByRole("main");
        expect(within(main).getByText(STRINGS[lang]["stopped.reason"])).toBeTruthy();
        expect(within(main).queryByText(STRINGS[lang]["app.notGenerated"])).toBeNull();
        expect(within(main).queryByRole("button")).toBeNull();
        expect(within(main).queryByRole("table")).toBeNull();
        expect(within(main).queryByRole("img")).toBeNull();
        for (const id of ["v10", "v11"]) {
          await select(id, lang);
          expect(within(main).getByText(STRINGS[lang]["stopped.reason"])).toBeTruthy();
          expect(within(main).queryByRole("button")).toBeNull();
          expect(within(main).queryByRole("table")).toBeNull();
        }
        expect(fetchFn.mock.calls.some(([url]) => /variants\/v(?:9|10|11)\//.test(url))).toBe(false);
      });
    }
    it(`${lang}: Intent chips include the index rule and selecting one shows the banner`, async () => {
      window.location.hash = "#/intent";
      renderWithApp(<App />, { backend: fixture("S-99").backend, lang });
      const suffix = STRINGS[lang]["stopped.short"].replace("{rule}", "S-99");
      const chip = await screen.findByRole("button", { name: `#10 ${suffix}` });
      fireEvent.click(chip);
      expect(screen.getByTestId("stopped-banner").textContent).toBe(STRINGS[lang]["stopped.reason"]);
      expect((await screen.findByRole("button", { name: `#10 ${suffix}` })).getAttribute("aria-pressed")).toBe("true");
    });
  }
  for (const route of ["analysis", "plan", "listen", "verify", "report"]) {
    it(`${route}: unavailable without stopped keeps the existing message`, async () => {
      window.location.hash = `#/${route}`;
      renderWithApp(<App />, { backend: fixture().backend, engineFactory: () => new FakeEngine() });
      const picker = await select("missing");
      expect(await screen.findByText(STRINGS.en["app.notGenerated"])).toBeTruthy();
      expect(within(picker).getByRole("option", { name: "missing × stream (—)" })).toBeTruthy();
      expect(screen.queryByTestId("stopped-banner")).toBeNull();
    });
  }
});

describe("variant project and history", () => {
  it("falls back for project and history independently", async () => {
    const { backend } = fixture();
    const index = await backend.index();
    index.variants[0].history = index.variants[1].history;
    delete index.variants[1].history;
    expect((await backend.getProject("v01")).title).toBe("Main direction hand");
    expect((await backend.history(100, "v01"))[0].summary).toBe("Second project history");
    expect((await backend.getProject("v02")).title).toBe("Second project hand");
    expect((await backend.history(100, "v02"))[0].summary).toBe("Main direction history");
  });
  it("loads per-entry paths and independently falls back to index paths", async () => {
    const { backend } = fixture();
    expect((await backend.getProject("v02")).title).toBe("Second project hand");
    expect((await backend.history(100, "v02"))[0].summary).toBe("Second project history");
    for (const id of ["v01", "v9", undefined]) {
      expect((await backend.getProject(id)).title).toBe("Main direction hand");
      expect((await backend.history(100, id))[0].summary).toBe("Main direction history");
    }
  });
  for (const [route, first, second] of [
    ["project", "Main direction hand", "Second project hand"],
    ["stems", "Main direction hand", "Second project hand"],
    ["mixmap", "Main direction hand", "Second project hand"],
    ["history", "Main direction history", "Second project history"],
    ["intent", "Main direction hand", "Second project hand"],
  ]) {
    it(`${route}: switches to v02 and back without showing the main hand`, async () => {
      window.location.hash = `#/${route}`;
      renderWithApp(<App />, { backend: fixture().backend });
      const main = await screen.findByRole("main");
      await waitFor(() => expect(main.textContent).toContain(first));
      await select("v02");
      await waitFor(() => expect(main.textContent).toContain(second));
      expect(main.textContent).not.toContain(first);
      await select("v01");
      await waitFor(() => expect(main.textContent).toContain(first));
      expect(main.textContent).not.toContain(second);
    });
  }
  it("Intent reloads the selected project and returns to the index project", async () => {
    window.location.hash = "#/intent";
    const { backend } = fixture();
    const load = vi.spyOn(backend, "getProject");
    renderWithApp(<App />, { backend });
    await screen.findByRole("button", { name: "#2" });
    await select("v02");
    await waitFor(() => expect(load).toHaveBeenLastCalledWith("v02"));
    await select("v01");
    await waitFor(() => expect(load).toHaveBeenLastCalledWith("v01"));
  });
});
