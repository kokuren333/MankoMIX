/** OQ-3 payloads are CLI observations; no browser-side signal measurements. */
export interface NoteObservation {
  target: string;
  sample_rate: number;
  count: number;
  confidence: number;
  section_samples: number[];
  measurements: Record<string, number>;
  caveats: string[];
  notes: { id: string; t0: number; t1: number; pitch_midi: number; confidence: number;
    cents_off: number; drift_cents: number; level_db: number; vibrato: { hz: number; width_cents: number } }[];
}

export interface MeterObservation {
  target: string;
  times_s: number[];
  end_times_s: number[];
  range_s: number[];
  summary: Record<string, number | null>;
  effective_step_ms: number;
  peak?: { sample_peak_dbfs: (number | null)[]; true_peak_dbtp: (number | null)[] };
  loudness?: { momentary: { mean_lufs: (number | null)[] }; short_term: { mean_lufs: (number | null)[] } };
  spectrum?: { bands_hz: number[][]; levels_dbfs: number[][]; ltas_dbfs: number[]; max_hold_dbfs: number[] };
  spectrogram?: { edges_hz: number[]; levels_dbfs: number[][] };
  correlation?: { full: number | null };
  vectorscope?: { windows: { tilt_degrees: number | null; spread: number | null; mid_dbfs: number; side_dbfs: number }[];
    points_lr?: number[][] };
}

export interface SpectralParams {
  t0_s: number[];
  t1_s: number[];
  lo_hz: number[];
  hi_hz: number[];
  [key: string]: unknown;
}

export interface SpectralPreview {
  type: "spectral_repair";
  params: SpectralParams;
  observation: MeterObservation;
  read_only: true;
  apply_via: string;
}

export interface ObservationOptions {
  target: string;
  section?: string;
  step_ms?: number;
  max_points?: number;
}
