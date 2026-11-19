import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Player } from "../screens/ListenScreen";
import { dbToGain, sourceGains, type SourceId } from "../audio/gains";
import { WebAudioEngine } from "../audio/engine";
import type { AudioSet } from "../types";
import { FakeEngine, renderWithApp } from "./helpers";

const SET: AudioSet = {
  variant: "directed",
  files: { before: "before.mp3", floor: "floor.mp3", after: "after.mp3", delta: "delta.mp3" },
  // Deliberately different from the three-way table to check precedence.
  match_gain_db: -9,
  match_target: "before",
  level_match_gains_db: { before: 0, floor: -1.02, after: -2.34 },
  floor: {
    project_variant: "floor", project_id: "synthetic", content_hash: "synthetic",
    objective: "comfort", profile: "streaming_universal",
    measurements: { lufs_i: -14.01, true_peak_dbtp: -1.01 },
    match_gain_db: -1.02, match_target: "floor", source_files: {},
  },
  measurements: {
    before: { lufs_i: -15, true_peak_dbtp: -2 },
    floor: { lufs_i: -14.01, true_peak_dbtp: -1.01 },
    after: { lufs_i: -13, true_peak_dbtp: -0.5 },
  },
};

describe("Listen floor", () => {
  it("switches all four synchronized sources using the supplied gains without reload or seek", async () => {
    const engine = new FakeEngine();
    const seek = vi.spyOn(engine, "seek");
    const play = vi.spyOn(engine, "play");
    renderWithApp(<Player set={SET} />, { engineFactory: () => engine });
    await waitFor(() => expect(engine.loaded).toHaveLength(1));
    expect(engine.loaded[0]).toEqual(SET.files);
    expect(screen.getByRole("radio", { name: "Before" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Floor (no direction)" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Directed" })).toBeTruthy();
    expect(screen.getByTestId("level-match").getAttribute("aria-checked")).toBe("true");
    for (const [source, db] of [["floor", -1.02], ["after", -2.34], ["before", 0], ["delta", 0]] as const) {
      fireEvent.click(screen.getByTestId(`ab-${source}`));
      expect(screen.getByTestId(`ab-${source}`).getAttribute("aria-checked")).toBe("true");
      for (const id of ["before", "floor", "after", "delta"] as SourceId[]) {
        expect(engine.lastGains()[id]).toBeCloseTo(id === source ? dbToGain(db) : 0, 8);
      }
    }
    expect(engine.loaded).toHaveLength(1);
    expect(seek).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it("turns level matching off to apply 0 dB to each selected source", async () => {
    const engine = new FakeEngine();
    renderWithApp(<Player set={SET} />, { engineFactory: () => engine });
    fireEvent.click(await screen.findByTestId("level-match"));
    for (const id of ["before", "floor", "after", "delta"] as SourceId[]) {
      fireEvent.click(screen.getByTestId(`ab-${id}`));
      expect(engine.lastGains()[id]).toBe(1);
    }
    fireEvent.click(screen.getByTestId("ab-floor"));
    fireEvent.click(screen.getByTestId("level-match"));
    expect(engine.lastGains().floor).toBeCloseTo(dbToGain(-1.02), 8);
  });

  it("shows three measurement rows and per-source gains in Japanese", async () => {
    renderWithApp(<Player set={{ ...SET, level_match_gains_db: { before: 0, floor: -1.02, after: -1.02 } }} />, { lang: "ja" });
    expect(await screen.findByRole("radio", { name: "処理前" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "床（指揮なし）" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "指揮版" })).toBeTruthy();
    expect(screen.getByTestId("match-readout").textContent).toBe("床 −1.0 dB／指揮版 −1.0 dB を適用");
    expect(screen.getAllByTestId(/^measurement-/)).toHaveLength(3);
    expect(screen.getByTestId("measurement-floor").textContent).toContain("−14.0 LUFS / −1.0 dBTP");
  });

  it("shows floor metadata and measurements in a JSON-only dataset", async () => {
    renderWithApp(<Player set={{ ...SET, files: { before: null, floor: null, after: null }, measurements: undefined }} />);
    expect(await screen.findByRole("radio", { name: "Floor (no direction)" })).toBeTruthy();
    expect(screen.getByTestId("measurement-floor").textContent).toContain("−14.0 LUFS");
    expect(screen.getByTestId("no-audio")).toBeTruthy();
  });

  it("keeps two-way labels and legacy gains when no floor or table exists", async () => {
    const engine = new FakeEngine();
    renderWithApp(<Player set={{ ...SET, files: { before: "before.mp3", after: "after.mp3" },
      floor: undefined, level_match_gains_db: undefined }} />, { engineFactory: () => engine });
    await waitFor(() => expect(engine.loaded).toHaveLength(1));
    expect(screen.getByRole("radio", { name: "A: Before" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "B: After" })).toBeTruthy();
    expect(screen.queryByTestId("ab-floor")).toBeNull();
    expect(engine.lastGains()).toEqual({ before: dbToGain(-9), after: 0, delta: 0 });
    expect(screen.getAllByTestId(/^measurement-/)).toHaveLength(2);
  });

  it("requires a gain table before offering the floor source", async () => {
    renderWithApp(<Player set={{ ...SET, level_match_gains_db: undefined }} />);
    expect(await screen.findByRole("radio", { name: "B: After" })).toBeTruthy();
    expect(screen.queryByTestId("ab-floor")).toBeNull();
  });

  it("uses nonzero Before table gain too, without deriving it from measurements", () => {
    expect(sourceGains({ active: "before", levelMatch: true, matchGainDb: -9, matchTarget: "after",
      levelMatchGainsDb: { before: -3, floor: -1, after: 0 } }))
      .toEqual({ before: dbToGain(-3), floor: 0, after: 0, delta: 0 });
  });

  it("starts four Web Audio sources at one instant and keeps position when gains switch", async () => {
    const starts: unknown[][] = [];
    const ramps: number[] = [];
    const node = () => ({ connect: vi.fn(), disconnect: vi.fn(),
      gain: { value: 0, setTargetAtTime: (v: number) => ramps.push(v) }, frequency: { value: 0 } });
    const ctx = {
      currentTime: 10, state: "running", destination: {},
      createGain: node, createBiquadFilter: node,
      decodeAudioData: async () => ({ duration: 100 }),
      createBufferSource: () => ({ ...node(), start: (...args: unknown[]) => starts.push(args), stop: vi.fn() }),
      close: vi.fn(),
    };
    vi.stubGlobal("AudioContext", class { constructor() { return ctx; } });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(0) })));
    const engine = new WebAudioEngine();
    try {
      expect(await engine.load(SET.files)).toEqual({ before: "ok", floor: "ok", after: "ok", delta: "ok" });
      engine.seek(12);
      await engine.play();
      expect(starts).toEqual(Array.from({ length: 4 }, () => [10.03, 12]));
      ctx.currentTime = 11;
      const pos = engine.currentTime();
      engine.setSourceGains(sourceGains({ active: "floor", levelMatch: true, matchGainDb: -9,
        matchTarget: "before", levelMatchGainsDb: SET.level_match_gains_db }));
      expect(ramps.slice(-4)).toEqual([0, dbToGain(-1.02), 0, 0]);
      expect(engine.currentTime()).toBe(pos);
      expect(engine.isPlaying()).toBe(true);
      expect(starts).toHaveLength(4);
    } finally {
      engine.dispose();
      vi.unstubAllGlobals();
    }
  });
});
