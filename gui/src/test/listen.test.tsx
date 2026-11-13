import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Player, ListenScreen } from "../screens/ListenScreen";
import { dbToGain, sourceGains } from "../audio/gains";
import type { AudioSet } from "../types";
import { FakeEngine, renderWithApp } from "./helpers";

const SET: AudioSet = {
  variant: "v01",
  files: { before: "demo/audio/before.mp3", after: "demo/variants/v01/after.mp3", delta: "demo/audio/delta.mp3" },
  match_gain_db: -2.5,
  match_target: "before",
};

describe("sourceGains", () => {
  it("applies the match gain only to the louder side and only when enabled", () => {
    expect(sourceGains({ active: "before", levelMatch: true, matchGainDb: -6, matchTarget: "before" })).toEqual({ before: dbToGain(-6), after: 0, delta: 0 });
    expect(sourceGains({ active: "after", levelMatch: true, matchGainDb: -6, matchTarget: "before" })).toEqual({ before: 0, after: 1, delta: 0 });
    expect(sourceGains({ active: "before", levelMatch: false, matchGainDb: -6, matchTarget: "before" })).toEqual({ before: 1, after: 0, delta: 0 });
  });
});

describe("Listen", () => {
  it("applies the match gain from the data by default, and toggling level match changes the gain", async () => {
    const engine = new FakeEngine();
    renderWithApp(<Player set={SET} />, { engineFactory: () => engine });

    const toggle = await screen.findByTestId("level-match");
    // Level match is ON by default.
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect(engine.lastGains()).toBeDefined());
    expect(engine.lastGains().before).toBeCloseTo(dbToGain(-2.5), 6);
    expect(engine.lastGains().after).toBe(0);
    expect(screen.getByTestId("match-readout").textContent).toContain("−2.5 dB");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(engine.lastGains().before).toBe(1);

    fireEvent.click(toggle);
    expect(engine.lastGains().before).toBeCloseTo(dbToGain(-2.5), 6);
  });

  it("switches A/B instantly via gains (no reload) and supports delta", async () => {
    const engine = new FakeEngine();
    renderWithApp(<Player set={SET} />, { engineFactory: () => engine });
    await waitFor(() => expect(engine.loaded.length).toBe(1));
    fireEvent.click(screen.getByTestId("ab-after"));
    expect(engine.lastGains()).toEqual({ before: 0, after: 1, delta: 0 });
    fireEvent.click(screen.getByTestId("ab-delta"));
    expect(engine.lastGains()).toEqual({ before: 0, after: 0, delta: 1 });
    fireEvent.click(screen.getByTestId("ab-before"));
    expect(engine.lastGains().before).toBeCloseTo(dbToGain(-2.5), 6);
    // Sources were loaded once; switching never reloads (position is kept).
    expect(engine.loaded.length).toBe(1);
  });

  it("forwards mono / small speaker / low level toggles to the engine", async () => {
    const engine = new FakeEngine();
    renderWithApp(<Player set={SET} />, { engineFactory: () => engine });
    fireEvent.click(await screen.findByTestId("mono"));
    fireEvent.click(screen.getByTestId("band-limit"));
    fireEvent.click(screen.getByTestId("low-level"));
    expect(engine.monitors[engine.monitors.length - 1]).toEqual({ mono: true, bandLimit: true, lowLevel: true });
  });

  it("handles a dataset without audio gracefully", async () => {
    const engine = new FakeEngine();
    renderWithApp(<ListenScreen />, { engineFactory: () => engine });
    expect(await screen.findByTestId("no-audio")).toBeTruthy();
    expect(engine.loaded.length).toBe(0);
    // Level match is still on and reflects the precomputed match gain.
    expect(screen.getByTestId("level-match").getAttribute("aria-checked")).toBe("true");
  });
});
