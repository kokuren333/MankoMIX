# Mix Report — マンコ主義 / var_club

## 1. Summary
- Overall result: **fail**
- Route: stem_mix (R-21) — Stems with mix-stage results exist, so the stem-mix route was chosen
- Objective: bass_heavy×1.0 / intensity 0.5
- Output: club × dj_wav → fail (`renders/var_club/club__dj_wav.wav`)
- Objective score (0 is ideal; breakdown in section 5): 0.000 → **0.000**
- Translation gate (OF-5): pass
- **Send back (S-08)**: The noise-return guard (S-08) does not pass even with the target lowered within the profile window. The least-failing candidate (-8.7 LUFS) still has shimmer index +1.5 dB (tolerance 1.5 dB). The tolerance is not relaxed; sent back to the mix (or cleanup) stage
- The genre prior 'Hip-hop' only sets the initial weights and target ranges of the objective (practice level); measured references and user settings always take precedence
- No references are registered: this is an evaluation against a generic prior, not a genre-specific one. v1 ships no statistics taken from commercial tracks (D-039); registering your own tracks with reference add makes their measured distribution the target ranges
- Raising the sub band makes playback loudness normalization turn the whole track down, so the midrange drops relatively. Bass emphasis comes at this trade-off

## 2. Inputs and provenance
- `assets/backing_vocals.wav` (backing_vocals, native_stem, 48000 Hz) sha256 `c444fec15fc0d899…`
- `assets/bass.wav` (bass, native_stem, 48000 Hz) sha256 `f8c78c658af294c9…`
- `assets/brass.wav` (brass, native_stem, 48000 Hz) sha256 `cd50cecd6bd0b8bc…`
- `assets/drums.wav` (drums, native_stem, 48000 Hz) sha256 `fca494f025b0fca6…`
- `assets/fullmix_conformed.wav` (fullmix, reference_fullmix, 48000 Hz) sha256 `ba9a2aafb6920767…`
- `assets/fx.wav` (fx, native_stem, 48000 Hz) sha256 `b0d12e1435cfc60e…`
- `assets/guitar.wav` (guitar, native_stem, 48000 Hz) sha256 `80b1df8b2ae6eecc…`
- `assets/keyboard.wav` (keyboard, native_stem, 48000 Hz) sha256 `647cb4b65678c9be…`
- `assets/percussion.wav` (percussion, native_stem, 48000 Hz) sha256 `88740e65fa8a1647…`
- `assets/strings.wav` (strings, native_stem, 48000 Hz) sha256 `d7114de4b2b55f4e…`
- `assets/synth.wav` (synth, native_stem, 48000 Hz) sha256 `e3ed491638689a47…`
- `assets/vocals.wav` (vocals, native_stem, 48000 Hz) sha256 `6ea15e88a1b7b3a4…`
- `assets/woodwinds.wav` (woodwinds, native_stem, 48000 Hz) sha256 `ff66f9531e966cf5…`
- Ingest checks: 27
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] format: wav_f32 48000 Hz 2 ch 4746240 samples
  - [info] headroom: peak and headroom recorded [true peak / PLR]
  - [info] headroom: peak and headroom recorded [true peak / PLR]
  - [info] headroom: peak and headroom recorded [true peak / PLR]
  - [info] headroom: peak and headroom recorded [true peak / PLR]
  - [info] headroom: peak and headroom recorded [true peak / PLR]
  - [info] headroom: peak and headroom recorded [true peak / PLR]
  - [info] headroom: peak and headroom recorded [true peak / PLR]
- Stem-sum consistency comes from the analysis stage; not re-evaluated in this report

## 3. Measurements (before / after)
_Comparisons use level-matched signals (R-01). Width/localisation values assume speakers (+/-30 deg) and a mono fold_

| Metric | Before | After |
|---|---|---|
| LUFS-I | -17.63 | - |
| Short-term max | -15.91 | - |
| LRA | 2.77 | - |
| True peak dBTP | -3.64 | - |
| PLR | 13.99 | - |
| PSR | 12.28 | - |

_Objective proxy metrics before and after, measured on level-matched signals (R-01)_

| Objective | Metric | Before | After | Unit |
|---|---|---|---|---|
| bass_heavy | P-07:sub+bass | 2.77 | 2.24 | dB band/rest |
| bass_heavy | P-13 | - | - |  |
| bass_heavy | P-02:low_to_mid | - | - |  |
| bass_heavy | P-08 | -0.89 | -0.87 | dB harmonic index |
| bass_heavy | P-03:plr | 13.99 | 8.15 | plr_db |

## 4. Decision log
### Balance
- Action: balance is handled at the mix stage [R-28]
### Panning
- Action: Low-band mono loss and anti-phase are within limits; no stereo processing [R-09]
  - Measured: `{"low_band_hz": 120.0, "low_band_mono_loss_db": 0.02, "low_band_negative_corr": {"longest_run_s": 0.0, "min_corr": 0.486137904123278, "negative_fraction": 0.0, "windows": 234}}`
  - Alternatives: mono below 120 Hz
- Action: no panning / width change [R-09]
  - Measured: `{"S-03": "pass", "S-04": "pass"}`
### Frequency
- Action: No clear band issue was measured, so no EQ is applied (0 dB) [R-06]
  - Measured: `{"band_ratios_vs_generic_prior": {"air": {"deviation_db": 0.0, "prior_range": [0.0005, 0.12], "ratio": 0.006}, "bass": {"deviation_db": 0.0, "prior_range": [0.05, 0.7], "ratio": 0.60554}, "high_mid": {"deviation_db": 0.0, "prior_range": [0.01, 0.25], "ratio": 0.03586}, "low_mid": {"deviation_db": 0.0, "prior_range": [0.03, 0.3], "ratio": 0.11896}, "mid": {"deviation_db": 0.0, "prior_range": [0.04, 0.4], "ratio": 0.17489}, "sub": {"deviation_db": 0.0, "prior_range": [0.01, 0.6], "ratio": 0.05874}}}`
  - Alternatives: small moves toward the generic prior
  - Result (expected): `{"eq_moves": 0}`
- Action: No enhancement by default [R-06]
  - Alternatives: harmonic enhancement (only with a stated purpose)
- Action: small moves were tried along the objective breakdown; the best level-matched candidate was kept [R-01,R-06,R-15,R-29]
  - Measured: `{"iterations": 0, "score_best": 0.0, "score_start": 0.0}`
  - Alternatives: use the plan_master proposal unchanged
  - Result (expected): `{"converged": true, "reason": "no applicable move left (all proposals blocked or nothing to improve)", "s08": {"deltas": {"noise_floor_dbfs": {"delta_db": 0.86, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": 1.66, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 1.51, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.99, "tolerance_db": 1.5}}, "status": "fail", "worst_excess_db": 0.21}, "score": 0.0}`
- Action: no further frequency correction [R-06]
### Depth
- Action: depth is handled at the mix stage
### Dynamics
- Action: No dynamics processing by default (no multiband) [R-30]
  - Measured: `{"lra_lu": 2.768912987861441, "plr_db": 13.99379702165553}`
  - Alternatives: light single-band compression (1-2 dB); multiband (only as an alternative to a send-back)
- Action: Non-normalized medium: -8.7 LUFS, reachable within the window under the P-18 limit and the S-08 guard [R-18]
  - Measured: `{"input_lufs_i": -17.63, "pre_limiter_lufs_i": -17.63, "profile_target_lufs_i": -7.0, "tried": [{"gr_p95_db": 8.97, "lufs_i": -7.01, "target": -7.0}, {"gr_p95_db": 5.22, "lufs_i": -7.98, "target": -8.0}, {"gr_p95_db": 3.73, "lufs_i": -8.66, "target": -8.7}], "window_lufs_i": [-9.0, -6.0]}`
  - Alternatives: a louder target (more limiter dependency and noise return)
  - Result (expected): `{"gain_db": 10.779, "lufs_i": -8.66}`
- Action: True-peak limiter last (ceiling -0.5 dBTP, release 100 ms) [R-14]
  - Measured: `{"limiter_gr": {"gr_fraction_gt_1db": 0.46, "gr_max_db": 7.65, "gr_median_db": 0.87, "gr_p95_db": 3.73}}`
  - Alternatives: add a clipper (not default); a different release time (changes pumping and noise lift)
  - Result (expected): `{"true_peak": -0.51}`
- Action: Corrections did not pass; the least-failing candidate is kept and the master is sent back [S-08]
  - Measured: `{"baseline": {"cleaned": true, "source": "measured on the master input built from cleaned assets"}, "frame_selection": "baseline frames, time aligned", "s08": {"deltas": {"noise_floor_dbfs": {"delta_db": 0.86, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": 1.66, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 1.51, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.99, "tolerance_db": 1.5}}, "failing": ["shimmer_index_db"], "frame_selection": "baseline_frames", "gain_db": 8.971, "margin_db": 0.2, "status": "fail", "verify_tolerance_status": "fail", "worst_excess_db": 0.21}, "scope": "full input, simulated chain"}`
  - Alternatives: relax the tolerance (never: hard constraint, SPEC 4.3); suppress the noise with multiband processing (not default, R-30)
  - Result (expected): `{"s08": {"deltas": {"noise_floor_dbfs": {"delta_db": 0.86, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": 1.66, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 1.51, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.99, "tolerance_db": 1.5}}, "failing": ["shimmer_index_db"], "frame_selection": "baseline_frames", "gain_db": 8.971, "margin_db": 0.2, "status": "fail", "verify_tolerance_status": "fail", "worst_excess_db": 0.21}}`
  - Step 1 [S-08]: The chain has no HF boost, so reducing it does not apply
    - Measured: S-08 fail `{"noise_floor_dbfs": {"delta_db": 0.86, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": 1.66, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 1.51, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.99, "tolerance_db": 1.5}}`
- Action: the limiter is a ceiling; its drive was kept constant by loudness compensation [R-14]
  - Result (expected): `{"gr_fraction_gt_1db": 0.458103, "gr_max_db": 7.6523, "gr_median_db": 0.8724, "gr_p95_db": 3.727}`
### Interest
- Action: Interest is the hardest axis to automate and depends on human direction and references; the planner only watches that section contrast is not flattened [R-26] (depends_on_humans_and_references)
  - References: No references are registered

## 5. Objective achievement
- Objective: bass_heavy×1.00 / intensity 0.5 / targets from: generic prior (not genre-specific)
- Lead: trk_vocals
- Evaluated from: evaluation stored with the applied proposal (planner, full length) (full_length), proposal `mpl_87235d5d809b`
- score: before 0.000 → after **0.000** (bass_heavy 0.000)

| Objective | Metric | Status | Value (before → after) | Target | Penalty (before → after) | Eff. weight | Contribution |
|---|---|---|---|---|---|---|---|
| bass_heavy | P-07:sub+bass | measured | 2.77 → 2.24 dB band/rest | [-1.00, 7.50] | 0.000 → 0.000 | 0.519 | 0.000 |
| bass_heavy | P-13 | not_measured: needs stems (kick and bass separately) | - → -  | - | - → - | 0.000 | 0.000 |
| bass_heavy | P-02:low_to_mid | not_measured: needs stems (masking is an inter-stem metric) | - → -  | [0.00, 1.50] | - → - | 0.000 | 0.000 |
| bass_heavy | P-08 | measured | -0.89 → -0.87 dB harmonic index | [-11.50, -] | 0.000 → 0.000 | 0.333 | 0.000 |
| bass_heavy | P-03:plr | measured | 13.99 → 8.15 plr_db | [7.00, 18.00] | 0.000 → 0.000 | 0.148 | 0.000 |
- Weight redistribution (bass_heavy): P-13, P-02:low_to_mid → 0.426
- Each penalty is 0 inside the target range and approaches 1 the further it is outside. The score is the sum of effective weight x penalty; 0 is ideal. Weights of terms that cannot be measured are redistributed proportionally to the measured terms of the same objective and recorded

## 6. Constraints and gates
### club × dj_wav — fail
| Check | Status | Values |
|---|---|---|
| render | missing | `{}` output not rendered; run render first |
### Safety invariants (at objective evaluation)
_Safety invariants at objective evaluation; never relaxed by blend or intensity (SPEC 4.3). The per-output verdicts above are final_

S-01: pass / S-02: not_evaluated / S-03: pass / S-04: pass / S-05: not_evaluated / S-06: pass / S-07: not_evaluated / S-08: not_evaluated / S-09: pass / S-10: not_evaluated / S-11: not_evaluated
### Translation gate (OF-5) — pass
_Every required check passed_

| Check | Required | Status | Reason |
|---|---|---|---|
| band_limited_lead_preserved | False | not_evaluated | not_required_by_profile |
| mono_fold_loss_within_limit | True | pass |  |
| low_level_balance_preserved | False | not_evaluated | not_required_by_profile |
| pitch_preserved_without_fundamental | False | not_evaluated | not_required_by_profile |
- 2mix only: lead checks are not evaluable without stems and are not counted as passes

## 7. Cleanup record
- Cleanup: applied
- Cleanup runs before mixing and mastering (R-20). Listen to the removed component (delta) for breaths or consonants
### ast_backing_vocals
- Steps: click repair = run, spectral reduction = run, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -280.8 dB | 0.000 | -300.0 |
| presence | 1000–5000 | -23.4 dB | 0.198 | -64.2 |
| sibilance | 5000–8000 | -25.6 dB | 0.169 | -76.9 |
| upper_presence | 8000–10000 | -26.7 dB | 0.157 | -78.6 |
| shimmer | 10000–14000 | -24.8 dB | 0.179 | -83.1 |
| air | 14000–24000 | -22.2 dB | 0.215 | -89.5 |

- Side effects (P-21): True — 250–500 Hz +0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": -0.112, "bass": -0.0, "high_mid": -0.006, "low_mid": 0.0, "mid": 0.011, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Removed component (for listening): `renders/delta/ast_backing_vocals.wav`
### ast_bass
- Steps: click repair = skip, spectral reduction = light, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -300.0 dB | 0.000 | -300.0 |
| presence | 1000–5000 | -60.2 dB | 0.015 | -117.7 |
| sibilance | 5000–8000 | -58.4 dB | 0.018 | -137.7 |
| upper_presence | 8000–10000 | -45.8 dB | 0.042 | -134.0 |
| shimmer | 10000–14000 | -37.9 dB | 0.072 | -124.1 |
| air | 14000–24000 | -29.9 dB | 0.126 | -120.3 |

- Side effects (P-21): True — 250–500 Hz +0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": -0.077, "bass": 0.0, "high_mid": -0.003, "low_mid": 0.0, "mid": -0.001, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Removed component (for listening): `renders/delta/ast_bass.wav`
### ast_brass
- Steps: click repair = run, spectral reduction = light, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -99.9 dB | 0.001 | -174.4 |
| presence | 1000–5000 | -5.5 dB | 0.685 | -72.5 |
| sibilance | 5000–8000 | -1.4 dB | 0.909 | -78.0 |
| upper_presence | 8000–10000 | -1.3 dB | 0.916 | -79.8 |
| shimmer | 10000–14000 | -3.2 dB | 0.801 | -82.7 |
| air | 14000–24000 | -11.1 dB | 0.465 | -101.1 |

- Side effects (P-21): True — 250–500 Hz -0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": 3.04, "bass": 0.0, "high_mid": 0.992, "low_mid": 0.0, "mid": 1.368, "sub": null}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Over-suppression detected: re-run with less strength
- Removed component (for listening): `renders/delta/ast_brass.wav`
### ast_drums
- Steps: click repair = run, spectral reduction = light, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -155.1 dB | 0.000 | -176.4 |
| presence | 1000–5000 | -21.7 dB | 0.222 | -56.4 |
| sibilance | 5000–8000 | -17.1 dB | 0.305 | -63.2 |
| upper_presence | 8000–10000 | -18.6 dB | 0.276 | -69.7 |
| shimmer | 10000–14000 | -17.8 dB | 0.291 | -73.7 |
| air | 14000–24000 | -7.0 dB | 0.617 | -74.9 |

- Side effects (P-21): False — 250–500 Hz -0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": -0.399, "bass": 0.0, "high_mid": -1.147, "low_mid": 0.0, "mid": 0.071, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Removed component (for listening): `renders/delta/ast_drums.wav`
### ast_fx
- Steps: click repair = run, spectral reduction = run, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -125.2 dB | 0.000 | -177.5 |
| presence | 1000–5000 | -15.0 dB | 0.352 | -70.4 |
| sibilance | 5000–8000 | -8.9 dB | 0.541 | -77.3 |
| upper_presence | 8000–10000 | -8.1 dB | 0.572 | -79.5 |
| shimmer | 10000–14000 | -7.0 dB | 0.616 | -79.3 |
| air | 14000–24000 | -12.0 dB | 0.436 | -88.1 |

- Side effects (P-21): True — 250–500 Hz +0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": -0.218, "bass": 0.0, "high_mid": 0.047, "low_mid": -0.0, "mid": -0.128, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Over-suppression detected: re-run with less strength
- Removed component (for listening): `renders/delta/ast_fx.wav`
### ast_guitar
- Steps: click repair = run, spectral reduction = skip, protection = skip, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -156.2 dB | 0.000 | -191.3 |
| presence | 1000–5000 | -23.4 dB | 0.198 | -67.4 |
| sibilance | 5000–8000 | -16.9 dB | 0.309 | -86.1 |
| upper_presence | 8000–10000 | -2.3 dB | 0.852 | -86.5 |
| shimmer | 10000–14000 | -4.8 dB | 0.720 | -86.7 |
| air | 14000–24000 | -1.3 dB | 0.913 | -91.0 |

- Side effects (P-21): True — 250–500 Hz -0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": 0.375, "bass": 0.0, "high_mid": 0.018, "low_mid": 0.0, "mid": 0.003, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Removed component (for listening): `renders/delta/ast_guitar.wav`
### ast_keyboard
- Steps: click repair = run, spectral reduction = skip, protection = skip, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -151.1 dB | 0.000 | -183.5 |
| presence | 1000–5000 | -22.9 dB | 0.204 | -77.7 |
| sibilance | 5000–8000 | -2.9 dB | 0.816 | -85.2 |
| upper_presence | 8000–10000 | -2.6 dB | 0.834 | -87.8 |
| shimmer | 10000–14000 | -4.1 dB | 0.752 | -89.5 |
| air | 14000–24000 | -15.1 dB | 0.351 | -103.9 |

- Side effects (P-21): True — 250–500 Hz -0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": 2.514, "bass": -0.0, "high_mid": 0.177, "low_mid": 0.0, "mid": 0.0, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Removed component (for listening): `renders/delta/ast_keyboard.wav`
### ast_percussion
- Steps: click repair = run, spectral reduction = light, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -119.2 dB | 0.000 | -176.9 |
| presence | 1000–5000 | -18.8 dB | 0.272 | -69.8 |
| sibilance | 5000–8000 | -7.2 dB | 0.607 | -71.8 |
| upper_presence | 8000–10000 | -7.2 dB | 0.607 | -67.2 |
| shimmer | 10000–14000 | -7.7 dB | 0.586 | -70.4 |
| air | 14000–24000 | -9.1 dB | 0.534 | -85.7 |

- Side effects (P-21): True — 250–500 Hz +0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": 0.278, "bass": 0.0, "high_mid": -0.645, "low_mid": -0.0, "mid": -0.318, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Removed component (for listening): `renders/delta/ast_percussion.wav`
### ast_strings
- Steps: click repair = run, spectral reduction = light, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -106.6 dB | 0.001 | -182.9 |
| presence | 1000–5000 | -8.4 dB | 0.560 | -78.7 |
| sibilance | 5000–8000 | -2.7 dB | 0.831 | -83.9 |
| upper_presence | 8000–10000 | -2.6 dB | 0.834 | -84.6 |
| shimmer | 10000–14000 | -3.9 dB | 0.763 | -86.6 |
| air | 14000–24000 | -9.2 dB | 0.528 | -99.9 |

- Side effects (P-21): True — 250–500 Hz -0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": 2.356, "bass": 0.0, "high_mid": 0.927, "low_mid": 0.0, "mid": 0.238, "sub": null}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Over-suppression detected: re-run with less strength
- Removed component (for listening): `renders/delta/ast_strings.wav`
### ast_synth
- Steps: click repair = skip, spectral reduction = run, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -244.2 dB | 0.000 | -280.9 |
| presence | 1000–5000 | -40.5 dB | 0.060 | -97.8 |
| sibilance | 5000–8000 | -34.4 dB | 0.092 | -114.3 |
| upper_presence | 8000–10000 | -26.7 dB | 0.157 | -109.8 |
| shimmer | 10000–14000 | -22.9 dB | 0.205 | -104.5 |
| air | 14000–24000 | -22.6 dB | 0.209 | -106.1 |

- Side effects (P-21): True — 250–500 Hz +0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": -0.088, "bass": 0.0, "high_mid": -0.031, "low_mid": 0.0, "mid": -0.003, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Removed component (for listening): `renders/delta/ast_synth.wav`
### ast_vocals
- Steps: click repair = run, spectral reduction = light, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -265.9 dB | 0.000 | -289.9 |
| presence | 1000–5000 | -23.2 dB | 0.200 | -54.5 |
| sibilance | 5000–8000 | -28.7 dB | 0.137 | -71.8 |
| upper_presence | 8000–10000 | -30.3 dB | 0.123 | -75.3 |
| shimmer | 10000–14000 | -24.8 dB | 0.180 | -77.9 |
| air | 14000–24000 | -18.3 dB | 0.282 | -82.3 |

- Side effects (P-21): True — 250–500 Hz +0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": -0.13, "bass": -0.0, "high_mid": 0.005, "low_mid": 0.0, "mid": 0.003, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Removed component (for listening): `renders/delta/ast_vocals.wav`
### ast_woodwinds
- Steps: click repair = run, spectral reduction = run, protection = run, HF completion = skip

| Band | Hz | Removed (re input) | Perceived loudness (sone ratio) | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -147.1 dB | 0.000 | -191.8 |
| presence | 1000–5000 | -8.3 dB | 0.562 | -75.0 |
| sibilance | 5000–8000 | -4.0 dB | 0.759 | -85.2 |
| upper_presence | 8000–10000 | -3.1 dB | 0.807 | -85.7 |
| shimmer | 10000–14000 | -4.7 dB | 0.721 | -83.7 |
| air | 14000–24000 | -11.2 dB | 0.460 | -98.7 |

- Side effects (P-21): True — 250–500 Hz +0.0 dB (about 1.00x perceived loudness) (tolerance ±0.5 dB), width change `{"air": 1.454, "bass": 0.0, "high_mid": -0.346, "low_mid": 0.0, "mid": -0.053, "sub": 0.0}` (tolerance -1.0 dB)
- S-07 low-band residual: -300.0 dBFS (limit -80.0 dBFS, 1000.0 Hz) → True
- Over-suppression detected: re-run with less strength
- Removed component (for listening): `renders/delta/ast_woodwinds.wav`
- Noise-return baseline: `analysis/noise_baseline.json` — -
- S-08 at planning (simulated): fail → fail — Corrections did not pass; the least-failing candidate is kept and the master is sent back
  - step 1: The chain has no HF boost, so reducing it does not apply

## 8. Trade-offs and open issues
- [send_back S-08] The noise-return guard (S-08) does not pass even with the target lowered within the profile window. The least-failing candidate (-8.7 LUFS) still has shimmer index +1.5 dB (tolerance 1.5 dB). The tolerance is not relaxed; sent back to the mix (or cleanup) stage
- [warning R-14] Target lowered from -7.0 to -8.7 LUFS because of limiter dependency
- [weak_evidence] Thresholds (limiter dependency, mono loss, low-band anti-phase persistence) are practice-level initial values subject to calibration
- [not_measured] Terms that could not be measured (P-02:low_to_mid, P-13) had their weight redistributed to the measured terms of the same objective; some metrics need stems or the cleanup stage
- [note R-17] No references are registered: this is an evaluation against a generic prior, not a genre-specific one. v1 ships no statistics taken from commercial tracks (D-039); registering your own tracks with reference add makes their measured distribution the target ranges
- [note] Raising the sub band makes playback loudness normalization turn the whole track down, so the midrange drops relatively. Bass emphasis comes at this trade-off

## 9. Listening checks (human ears decide)
**Listening conditions**: Listen at a fixed volume / compare before and after only level-matched / use several playback systems (monitors, headphones, smartphone) / decide with rested ears (after long loud listening, high-frequency judgement gets lenient)

- [0:00.0] First 10 s: in a level-matched comparison with the input, is the tone (low-end amount, top-end brightness) as intended?
- [1:02.4] Loudest section: are attacks flattened or is there pumping from the limiter? (GR p95 3.7 dB, max 7.7 dB)
- [1:02.4] Loudest section in mono: does the bass thin out or vanish, does the lead step back?
- [1:35.8] Quietest section: is noise or hiss exposed, is the quiet/loud contrast preserved? (R-26)
- [0:00.0] Listen to the removed component (`renders/delta/ast_backing_vocals.wav`, ast_backing_vocals): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_bass.wav`, ast_bass): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_brass.wav`, ast_brass): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_drums.wav`, ast_drums): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_fx.wav`, ast_fx): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_guitar.wav`, ast_guitar): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_keyboard.wav`, ast_keyboard): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_percussion.wav`, ast_percussion): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_strings.wav`, ast_strings): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_synth.wav`, ast_synth): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_vocals.wav`, ast_vocals): does it contain breaths or consonants? (if so, the cleanup is too strong)
- [0:00.0] Listen to the removed component (`renders/delta/ast_woodwinds.wav`, ast_woodwinds): does it contain breaths or consonants? (if so, the cleanup is too strong)

## 10. Reproducibility
- project hash: `None`
- engine: mankomix 0.1.0 — mankomix.dsp (reference backend)
- ffmpeg: not used
- FFmpeg is not bundled; the user's build is called as an external process and its build configuration is recorded
- No models were used in this render
- Same project, assets, engine and backend versions give the same output (bit-identical in the same environment)
