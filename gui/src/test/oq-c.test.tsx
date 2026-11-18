import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { LocalBackend } from "../backend/LocalBackend";
import type { MeterObservation, NoteObservation, SpectralPreview } from "../backend/observations";
import { MetersScreen, NotesScreen, SpectralScreen } from "../screens/ObservationScreens";
import { FullCapsBackend, renderWithApp } from "./helpers";

const notes: NoteObservation = {
  target: "trk_vocals", sample_rate: 24000, count: 1, confidence: .9876,
  section_samples: [3000, 21000], measurements: { a4_hz: 440 }, caveats: ["Monophonic estimate"],
  notes: [{ id: "n_3000", t0: .125, t1: .875, pitch_midi: 69.123456789, confidence: .9876,
    cents_off: 12.3456789, drift_cents: 2.34, level_db: -18.765, vibrato: { hz: 5.12, width_cents: 8.765 } }],
};
const meters: MeterObservation = {
  target: "trk_vocals", times_s: [.125, .5], end_times_s: [.5, .875], range_s: [.125, .875], effective_step_ms: 375,
  summary: { integrated_lufs: -18.123456789, lra_lu: 1.234 },
  peak: { sample_peak_dbfs: [-3.12345, -4.56789], true_peak_dbtp: [-2.9876, -4.4321] },
  loudness: { momentary: { mean_lufs: [-18.123, -19.234] }, short_term: { mean_lufs: [null, null] } },
  spectrum: { bands_hz: [[100, 400], [400, 4000]], levels_dbfs: [[-30.123, -40.456], [-31, -41]], ltas_dbfs: [-30, -40], max_hold_dbfs: [-30.123, -40.456] },
  spectrogram: { edges_hz: [100, 400, 4000], levels_dbfs: [[-30.123, -40.456], [-31, -41]] },
  correlation: { full: .87654321 },
  vectorscope: { windows: [{ tilt_degrees: 12.345, spread: .12345, mid_dbfs: -18, side_dbfs: -22 }, { tilt_degrees: -9.876, spread: .54321, mid_dbfs: -19, side_dbfs: -23 }], points_lr: [[.1, .2], [-.2, -.1]] },
};

class ObservationsBackend extends FullCapsBackend {
  getPitchNotes = vi.fn(async () => notes);
  getMeters = vi.fn(async () => meters);
  previewSpectralRepair = vi.fn(async (options: Parameters<LocalBackend["previewSpectralRepair"]>[0]): Promise<SpectralPreview> => ({
    type: "spectral_repair", params: options.params, observation: meters, read_only: true, apply_via: "CLI direction op",
  }));
}

afterEach(() => vi.unstubAllGlobals());

async function load(name: string) {
  const button = await screen.findByRole("button", { name }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
}

describe("OQ-3 observation panels", () => {
  it("shows exact API note numbers and keeps a comparison after a CLI edit", async () => {
    const backend = new ObservationsBackend();
    renderWithApp(<NotesScreen />, { backend });
    await load("Load notes");
    expect(await screen.findByText("69.123456789")).toBeTruthy();
    expect(screen.getByText("12.3456789")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep for comparison" }));
    backend.getPitchNotes.mockResolvedValue({ ...notes, notes: [{ ...notes.notes[0], pitch_midi: 70.23456789 }] });
    await load("Load notes");
    expect(await screen.findByText("70.23456789")).toBeTruthy();
    expect(screen.getByText("69.123456789")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Note bands" })).toBeTruthy();
  });

  it("turns a dragged region into spec arrays and sends them unchanged for preview", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const backend = new ObservationsBackend();
    renderWithApp(<SpectralScreen />, { backend });
    await load("Load spectrogram");
    const plot = await screen.findByRole("img", { name: "Spectrogram" });
    vi.spyOn(plot, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 640, height: 240 } as DOMRect);
    fireEvent.pointerDown(plot, { clientX: 10, clientY: 230, pointerId: 1 });
    fireEvent.pointerUp(plot, { clientX: 630, clientY: 10, pointerId: 1 });
    const input = screen.getByLabelText("spectral_repair params") as HTMLTextAreaElement;
    const params = JSON.parse(input.value);
    expect(params.t0_s).toEqual([.125]); expect(params.t1_s).toEqual([.875]);
    expect(params.lo_hz).toEqual([100]); expect(params.hi_hz).toEqual([4000]);
    await load("Validate / preview");
    await screen.findByText("Validated (not applied)");
    expect(backend.previewSpectralRepair.mock.calls[0][0].params).toEqual(params);
    expect(screen.getByText(/Apply these params/)).toBeTruthy();
  });

  it("reads selected meter bins without recomputing measurements", async () => {
    renderWithApp(<MetersScreen />, { backend: new ObservationsBackend() });
    await load("Load meters");
    expect(await screen.findByText("-18.123456789")).toBeTruthy();
    expect(screen.getByText("correlation.full: 0.87654321")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Observation position"), { target: { value: "1" } });
    expect(screen.getByText(/sample_peak_dbfs: -4.56789/)).toBeTruthy();
    expect(screen.getByText(/tilt_degrees: -9.876 \/ spread: 0.54321/)).toBeTruthy();
    expect(screen.getByRole("img", { name: "Vectorscope" })).toBeTruthy();
  });

  it("disables observation requests in the demo", async () => {
    renderWithApp(<NotesScreen />);
    const button = await screen.findByRole("button", { name: "Load notes" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/demo has no observation data/)).toBeTruthy();
  });

  it("uses the additive LocalBackend endpoints and preserves returned JSON", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    const backend = new LocalBackend({ fetchFn: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response(JSON.stringify(String(url).includes("pitch/notes") ? notes : meters), { status: 200 });
    } });
    expect(await backend.getPitchNotes({ target: "trk_vocals", a4: 442 })).toEqual(notes);
    expect(await backend.getMeters({ target: "trk_vocals", what: "peak,spectrogram", max_points: 7 })).toEqual(meters);
    const params = { t0_s: [.1], t1_s: [.2], lo_hz: [100], hi_hz: [200] };
    await backend.previewSpectralRepair({ target: "trk_vocals", params });
    expect(requests[0].url).toBe("/api/direction/pitch/notes?target=trk_vocals&a4=442");
    expect(requests[1].url).toContain("/direction/query/meters?");
    expect(requests[2].url).toBe("/api/direction/spectral-repair/preview");
    expect(requests[2].init?.method).toBe("POST");
    expect(JSON.parse(requests[2].init?.body as string)).toEqual({ target: "trk_vocals", params });
  });
});
