# Mix Report — マンコ主義 / var_streaming_universal

## 1. Summary
- Overall result: **pass**
- Route: stem_mix (R-21) — Stems with mix-stage results exist, so the stem-mix route was chosen
- Objective: comfort×1.0 / intensity 0.5
- Output: streaming_universal × hires_native → pass (`renders/var_streaming_universal/streaming_universal__hires_native.wav`)
- Output: streaming_universal × distributor_44k16 → pass (`renders/var_streaming_universal/streaming_universal__distributor_44k16.wav`)
- Objective score (0 is ideal; breakdown in section 5): 0.181 → **0.181**
- Translation gate (OF-5): incomplete
- The genre prior 'Hip-hop' only sets the initial weights and target ranges of the objective (practice level); measured references and user settings always take precedence
- No references are registered: this is an evaluation against a generic prior, not a genre-specific one. v1 ships no statistics taken from commercial tracks (D-039); registering your own tracks with reference add makes their measured distribution the target ranges

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
| LUFS-I | -17.66 | -14.01 |
| Short-term max | -15.95 | -12.34 |
| LRA | 2.79 | 2.77 |
| True peak dBTP | -3.65 | -1.01 |
| PLR | 14.01 | 13.00 |
| PSR | 12.30 | 11.33 |

- Loudness change: +3.6 dB (about 1.29x perceived loudness)
- Level-matched differences (after - before), match gain -3.649 dB:
  - P-03/lra_lu: -0.02 LU
  - P-03/true_peak_dbtp: -1.01 dBTP
  - P-03/plr_db: -1.01 dB
  - P-03/psr_db: -0.97 dB
  - P-07/partition_bands/sub/level_db: +0.0 dB (about 1.00x perceived loudness)
  - P-07/partition_bands/bass/level_db: +0.0 dB (about 1.00x perceived loudness)
  - P-07/partition_bands/lowmid/level_db: +0.0 dB (about 1.00x perceived loudness)
  - P-07/partition_bands/mid/level_db: -0.0 dB (about 1.00x perceived loudness)
  - P-07/partition_bands/highmid/level_db: -0.0 dB (about 1.00x perceived loudness)
  - P-07/partition_bands/air/level_db: +0.0 dB (about 1.00x perceived loudness)
  - P-04/bands/sub/crest_db: +0.00 dB
  - P-04/bands/bass/crest_db: +0.00 dB
  - P-04/bands/lowmid/crest_db: +0.01 dB
  - P-04/bands/mid/crest_db: +0.01 dB
  - P-04/bands/highmid/crest_db: -0.14 dB
  - P-04/bands/air/crest_db: +0.00 dB
  - P-06/bands/sub/mono_loss_db: -0.00 dB
  - P-06/bands/bass/mono_loss_db: -0.00 dB
  - P-06/bands/lowmid/mono_loss_db: +0.00 dB
  - P-06/bands/mid/mono_loss_db: +0.00 dB
  - P-06/bands/highmid/mono_loss_db: +0.00 dB
  - P-06/bands/air/mono_loss_db: +0.00 dB

_Objective proxy metrics before and after, measured on level-matched signals (R-01)_

| Objective | Metric | Before | After | Unit |
|---|---|---|---|---|
| comfort | P-01 | 7.56 | 7.56 | dB (ISO 226 weighted RMS deviation) |
| comfort | P-02 | - | - |  |
| comfort | P-11 | 1.05 | 1.04 | dB prominence |
| comfort | P-03 | {"lra_lu": 2.79189754866756, "plr_db": 14.005821367401968} | {"lra_lu": 2.771204713790002, "plr_db": 12.997092600011703} | dB / LU |
| comfort | P-09 | - | - |  |
| comfort | P-12 | 0.00 | 0.02 | dB crest loss |
| comfort | P-19 | 1.31 | 1.31 | dB |

## 4. Decision log
### Balance
- Action: Not handled by full-mix mastering (the mix stage arrives in M4) (not_evaluated)
### Panning
- Action: Low-band mono loss and anti-phase are within limits; no stereo processing [R-09]
  - Measured: `{"low_band_hz": 120.0, "low_band_mono_loss_db": 0.02, "low_band_negative_corr": {"longest_run_s": 0.0, "min_corr": 0.47909907152108233, "negative_fraction": 0.0, "windows": 231}}`
  - Alternatives: mono below 120 Hz
### Frequency
- Action: No clear band issue was measured, so no EQ is applied (0 dB) [R-06]
  - Measured: `{"band_ratios_vs_generic_prior": {"air": {"deviation_db": 0.0, "prior_range": [0.0005, 0.12], "ratio": 0.00599}, "bass": {"deviation_db": 0.0, "prior_range": [0.05, 0.7], "ratio": 0.60608}, "high_mid": {"deviation_db": 0.0, "prior_range": [0.01, 0.25], "ratio": 0.03592}, "low_mid": {"deviation_db": 0.0, "prior_range": [0.03, 0.3], "ratio": 0.11773}, "mid": {"deviation_db": 0.0, "prior_range": [0.04, 0.4], "ratio": 0.1751}, "sub": {"deviation_db": 0.0, "prior_range": [0.01, 0.6], "ratio": 0.05918}}}`
  - Alternatives: small moves toward the generic prior
  - Result (expected): `{"eq_moves": 0}`
- Action: No enhancement by default [R-06]
  - Alternatives: harmonic enhancement (only with a stated purpose)
### Depth
- Action: Not handled by full-mix mastering (the mix stage arrives in M4) (not_evaluated)
### Dynamics
- Action: No dynamics processing by default (no multiband) [R-30]
  - Measured: `{"lra_lu": 2.79189754866756, "plr_db": 14.005821367401968}`
  - Alternatives: light single-band compression (1-2 dB); multiband (only as an alternative to a send-back)
- Action: Normalized medium: match -14.0 LUFS (a delivery gate, not a goal) [R-18]
  - Measured: `{"input_lufs_i": -17.66, "pre_limiter_lufs_i": -17.66, "profile_target_lufs_i": -14.0, "tried": [{"gr_p95_db": 0.0, "lufs_i": -14.01, "target": -14.0}], "window_lufs_i": [-15.0, -13.5]}`
  - Alternatives: a louder target (more limiter dependency and noise return)
  - Result (expected): `{"gain_db": 3.656, "lufs_i": -14.01}`
- Action: True-peak limiter last (ceiling -1.0 dBTP, release 100 ms) [R-14]
  - Measured: `{"limiter_gr": {"gr_fraction_gt_1db": 0.0, "gr_max_db": 1.02, "gr_median_db": 0.0, "gr_p95_db": 0.0}}`
  - Alternatives: add a clipper (not default); a different release time (changes pumping and noise lift)
  - Result (expected): `{"true_peak": -1.01}`
- Action: The simulated master passes the noise-return guard (no correction needed) [S-08]
  - Measured: `{"baseline": {"cleaned": true, "source": "measured on the master input built from cleaned assets"}, "frame_selection": "baseline frames, time aligned", "s08": {"deltas": {"noise_floor_dbfs": {"delta_db": -0.02, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": 0.01, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 0.01, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.01, "tolerance_db": 1.5}}, "failing": [], "frame_selection": "baseline_frames", "gain_db": 3.649, "margin_db": 0.2, "status": "pass", "verify_tolerance_status": "pass", "worst_excess_db": -1.29}, "scope": "full input, simulated chain"}`
  - Alternatives: relax the tolerance (never: hard constraint, SPEC 4.3); suppress the noise with multiband processing (not default, R-30)
  - Result (expected): `{"s08": {"deltas": {"noise_floor_dbfs": {"delta_db": -0.02, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": 0.01, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 0.01, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.01, "tolerance_db": 1.5}}, "failing": [], "frame_selection": "baseline_frames", "gain_db": 3.649, "margin_db": 0.2, "status": "pass", "verify_tolerance_status": "pass", "worst_excess_db": -1.29}}`
### Interest
- Action: Interest is the hardest axis to automate and depends on human direction and references; the planner only watches that section contrast is not flattened [R-26] (depends_on_humans_and_references)
  - References: No references are registered

## 5. Objective achievement
- Objective: comfort×1.00 / intensity 0.5 / targets from: generic prior (not genre-specific)
- Lead: trk_vocals
- Evaluated from: evaluated on the rendered master (full_length)
- score: before 0.181 → after **0.181** (comfort 0.181)

| Objective | Metric | Status | Value (before → after) | Target | Penalty (before → after) | Eff. weight | Contribution |
|---|---|---|---|---|---|---|---|
| comfort | P-01 | measured | 7.56 → 7.56 dB (ISO 226 weighted RMS deviation) | {"source": "generic_prior"} | 0.211 → 0.211 | 0.357 | 0.075 |
| comfort | P-02 | not_measured: needs stems (masking is an inter-stem metric) | - → -  | [0.00, 3.00] | - → - | 0.000 | 0.000 |
| comfort | P-11 | measured | 1.05 → 1.04 dB prominence | [-, 2.50] | 0.495 → 0.495 | 0.214 | 0.106 |
| comfort | P-03 | measured | {"lra_lu": 2.79189754866756, "plr_db": 14.005821367401968} → {"lra_lu": 2.771204713790002, "plr_db": 12.997092600011703} dB / LU | {"lra_lu": [2.0, 15.0], "plr_db": [7.0, 18.0]} | 0.000 → 0.000 | 0.214 | 0.000 |
| comfort | P-09 | not_measured: needs stems (depth order is per stem) | - → -  | - | - → - | 0.000 | 0.000 |
| comfort | P-12 | measured | 0.00 → 0.02 dB crest loss | - | 0.000 → 0.000 | 0.143 | 0.000 |
| comfort | P-19 | measured | 1.31 → 1.31 dB | - | 0.000 → 0.000 | 0.071 | 0.000 |
- Weight redistribution (comfort): P-02, P-09 → 0.300
- Each penalty is 0 inside the target range and approaches 1 the further it is outside. The score is the sum of effective weight x penalty; 0 is ideal. Weights of terms that cannot be measured are redistributed proportionally to the measured terms of the same objective and recorded

## 6. Constraints and gates
### streaming_universal × hires_native — pass
| Check | Status | Values |
|---|---|---|
| P-03 | pass | `{"measured": {"lufs_i": -14.01}, "target_lufs_i": -14.0, "window_lufs_i": [-15.0, -13.5]}`  |
| S-01 | pass | `{"ceiling_dbtp": -1.0, "conditional_applied": false, "measured": {"true_peak_dbtp": -1.01}, "oversample": 4}`  |
| S-02 | pass | `{"codec_after_ceiling_dbtp": -0.1, "codecs": {"aac": {"status": "pass", "tp": -0.951}, "mp3": {"status": "pass", "tp": -1.0}, "opus": {"status": "pass", "tp": -0.834}}, "final_limiter_ceiling_dbtp": -1.0, "render_iterations": 1}`  |
| S-05 | pass | `{"expected": "TPDF dither exactly once at the final export (word length reduced)"}`  |
| S-06 | pass | `{}`  |
| S-09 | pass | `{"measured": {"channels": 2, "clipped_samples": 0, "dc_offset": [0.00018, 0.000132], "expected_frames": 4746240, "frames": 4746240, "inf": 0, "input_dc_scaled": [0.00018, 0.000132], "nan": 0, "tolerance": 1}, "problems": []}`  |
| S-03 | pass | `{"limits": {"max_negative_fraction": 0.1, "max_persistence_s": 1.0}, "measured": {"boundary_hz": 120.0, "longest_negative_run_s": 0.1, "min_correlation": -0.47144604666252743, "negative_fraction": 0.001}}`  |
| S-04 | pass | `{"limits": {"lead_clarity_band_hz": [300, 5000], "lead_clarity_max_db": 3.0, "low_band_max_db": 1.5}, "measured": {"lead_clarity_mono_loss_db": 0.132, "low_band_mono_loss_db": 0.019}}`  |
| OF-5 | incomplete | `{}` see 'translation_gate' (objective evaluation of this master) |
| S-07 | pass | `{"assets": {"ast_backing_vocals": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "ede9e6ba0f18f8b4048f6cd9478fb80a6db13a9f5570842d67f1d42375f6449d", "residual_dbfs": -300.0, "residual_stored_dbfs": -168.723}, "ast_bass": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "b5f3d10865b6284e287b85d7ea8163921943ae1c9be1159e72a2287e10878045", "residual_dbfs": -300.0, "residual_stored_dbfs": -166.229}, "ast_brass": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "81cf4b91ab35a282412351081280da8683bba467b82b943cade2c71a02c9c55a", "residual_dbfs": -300.0, "residual_stored_dbfs": -190.795}, "ast_drums": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "c2551282580f47ad49d1c1345f534334bd4c04ac1038fe97a6b678ebb3a2fadd", "residual_dbfs": -300.0, "residual_stored_dbfs": -159.846}, "ast_fx": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "301ed26dd460be35c250299d504a76432955e7485da5ac4a051e4285ab898b89", "residual_dbfs": -300.0, "residual_stored_dbfs": -180.463}, "ast_guitar": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "df2ff4d636ed930975352964ac5516cd4e36b7172df95e88cc80006a0a7dfb44", "residual_dbfs": -300.0, "residual_stored_dbfs": -172.528}, "ast_keyboard": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "e4efe3197ca63de07605d0114c2a6563fddf584a9edd619798adde713253513a", "residual_dbfs": -300.0, "residual_stored_dbfs": -192.019}, "ast_percussion": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "d736dd6719f6cf0b260445eb481590af3d8e7e4843dcde60453dd0ea51f6e00d", "residual_dbfs": -300.0, "residual_stored_dbfs": -182.443}, "ast_strings": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "ba50c7c719b44fdc7b537576596af7daab5ad35294f4e3bb5a32f6325b23932a", "residual_dbfs": -300.0, "residual_stored_dbfs": -190.514}, "ast_synth": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "fc784e8770712b1ab2b1670d4487036fad52c8c7ecaec42519d50edf3c495722", "residual_dbfs": -300.0, "residual_stored_dbfs": -172.524}, "ast_vocals": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "cd71dd420835085e7df5b4a22809ff9030ac8a137142d3c01a71717f64570b17", "residual_dbfs": -300.0, "residual_stored_dbfs": -166.374}, "ast_woodwinds": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "fc94bac9d226437a6012da4c121f10f93a5ae5cea7719d2bf3db0e07ca626e48", "residual_dbfs": -300.0, "residual_stored_dbfs": -176.222}}, "method": "null test: peak of (cleaned - input) after a brick-wall low-pass at the crossover"}`  |
| S-08 | pass | `{"baseline": {"cleaned": true, "cleaned_assets": ["ast_backing_vocals", "ast_bass", "ast_brass", "ast_drums", "ast_fx", "ast_guitar", "ast_keyboard", "ast_percussion", "ast_strings", "ast_synth", "ast_vocals", "ast_woodwinds"], "source": "measured on the master input built from cleaned assets"}, "deltas": {"above_ceiling_level_db": {"after": null, "before": null, "delta_db": null, "note": "not measurable", "pass": null, "tolerance_db": null}, "noise_floor_dbfs": {"after": -25.241, "before": -28.87, "delta_db": -0.02, "gain_compensated": true, "pass": true, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"after": -43.198, "before": -46.852, "delta_db": 0.005, "gain_compensated": true, "pass": true, "tolerance_db": 2.0}, "shimmer_index_db": {"after": -41.736, "before": -41.751, "delta_db": 0.015, "gain_compensated": false, "pass": true, "tolerance_db": 1.5}, "side_shimmer_index_db": {"after": -55.802, "before": -55.816, "delta_db": 0.014, "gain_compensated": false, "pass": true, "tolerance_db": 1.5}}, "frame_selection": "baseline_frames", "gain_db": 3.649, "gain_source": "output integrated loudness - baseline integrated loudness", "suggestions": []}`  |
### streaming_universal × distributor_44k16 — pass
| Check | Status | Values |
|---|---|---|
| P-03 | pass | `{"measured": {"lufs_i": -14.0}, "target_lufs_i": -14.0, "window_lufs_i": [-15.0, -13.5]}`  |
| S-01 | pass | `{"ceiling_dbtp": -1.0, "conditional_applied": false, "measured": {"true_peak_dbtp": -1.007}, "oversample": 5}`  |
| S-02 | pass | `{"codec_after_ceiling_dbtp": -0.1, "codecs": {"aac": {"status": "pass", "tp": -0.837}, "mp3": {"status": "pass", "tp": -0.978}, "opus": {"status": "pass", "tp": -0.821}}, "final_limiter_ceiling_dbtp": -1.0, "render_iterations": 1}`  |
| S-05 | pass | `{"expected": "TPDF dither exactly once at the final export (word length reduced)"}`  |
| S-06 | pass | `{}`  |
| S-09 | pass | `{"measured": {"channels": 2, "clipped_samples": 0, "dc_offset": [0.00018, 0.000132], "expected_frames": 4360608, "frames": 4360608, "inf": 0, "input_dc_scaled": [0.00018, 0.000132], "nan": 0, "tolerance": 1}, "problems": []}`  |
| S-03 | pass | `{"limits": {"max_negative_fraction": 0.1, "max_persistence_s": 1.0}, "measured": {"boundary_hz": 120.0, "longest_negative_run_s": 0.1, "min_correlation": -0.471459654358842, "negative_fraction": 0.001}}`  |
| S-04 | pass | `{"limits": {"lead_clarity_band_hz": [300, 5000], "lead_clarity_max_db": 3.0, "low_band_max_db": 1.5}, "measured": {"lead_clarity_mono_loss_db": 0.132, "low_band_mono_loss_db": 0.019}}`  |
| OF-5 | incomplete | `{}` see 'translation_gate' (objective evaluation of this master) |
| S-07 | pass | `{"assets": {"ast_backing_vocals": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "ede9e6ba0f18f8b4048f6cd9478fb80a6db13a9f5570842d67f1d42375f6449d", "residual_dbfs": -300.0, "residual_stored_dbfs": -168.723}, "ast_bass": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "b5f3d10865b6284e287b85d7ea8163921943ae1c9be1159e72a2287e10878045", "residual_dbfs": -300.0, "residual_stored_dbfs": -166.229}, "ast_brass": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "81cf4b91ab35a282412351081280da8683bba467b82b943cade2c71a02c9c55a", "residual_dbfs": -300.0, "residual_stored_dbfs": -190.795}, "ast_drums": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "c2551282580f47ad49d1c1345f534334bd4c04ac1038fe97a6b678ebb3a2fadd", "residual_dbfs": -300.0, "residual_stored_dbfs": -159.846}, "ast_fx": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "301ed26dd460be35c250299d504a76432955e7485da5ac4a051e4285ab898b89", "residual_dbfs": -300.0, "residual_stored_dbfs": -180.463}, "ast_guitar": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "df2ff4d636ed930975352964ac5516cd4e36b7172df95e88cc80006a0a7dfb44", "residual_dbfs": -300.0, "residual_stored_dbfs": -172.528}, "ast_keyboard": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "e4efe3197ca63de07605d0114c2a6563fddf584a9edd619798adde713253513a", "residual_dbfs": -300.0, "residual_stored_dbfs": -192.019}, "ast_percussion": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "d736dd6719f6cf0b260445eb481590af3d8e7e4843dcde60453dd0ea51f6e00d", "residual_dbfs": -300.0, "residual_stored_dbfs": -182.443}, "ast_strings": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "ba50c7c719b44fdc7b537576596af7daab5ad35294f4e3bb5a32f6325b23932a", "residual_dbfs": -300.0, "residual_stored_dbfs": -190.514}, "ast_synth": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "fc784e8770712b1ab2b1670d4487036fad52c8c7ecaec42519d50edf3c495722", "residual_dbfs": -300.0, "residual_stored_dbfs": -172.524}, "ast_vocals": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "cd71dd420835085e7df5b4a22809ff9030ac8a137142d3c01a71717f64570b17", "residual_dbfs": -300.0, "residual_stored_dbfs": -166.374}, "ast_woodwinds": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "fc94bac9d226437a6012da4c121f10f93a5ae5cea7719d2bf3db0e07ca626e48", "residual_dbfs": -300.0, "residual_stored_dbfs": -176.222}}, "method": "null test: peak of (cleaned - input) after a brick-wall low-pass at the crossover"}`  |
| S-08 | pass | `{"baseline": {"cleaned": true, "cleaned_assets": ["ast_backing_vocals", "ast_bass", "ast_brass", "ast_drums", "ast_fx", "ast_guitar", "ast_keyboard", "ast_percussion", "ast_strings", "ast_synth", "ast_vocals", "ast_woodwinds"], "source": "measured on the master input built from cleaned assets"}, "conformed": {"resampled_from_hz": 44100, "resampled_to_hz": 48000}, "deltas": {"above_ceiling_level_db": {"after": null, "before": null, "delta_db": null, "note": "not measurable", "pass": null, "tolerance_db": null}, "noise_floor_dbfs": {"after": -25.239, "before": -28.87, "delta_db": -0.022, "gain_compensated": true, "pass": true, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"after": -43.192, "before": -46.852, "delta_db": 0.007, "gain_compensated": true, "pass": true, "tolerance_db": 2.0}, "shimmer_index_db": {"after": -41.733, "before": -41.751, "delta_db": 0.018, "gain_compensated": false, "pass": true, "tolerance_db": 1.5}, "side_shimmer_index_db": {"after": -55.802, "before": -55.816, "delta_db": 0.014, "gain_compensated": false, "pass": true, "tolerance_db": 1.5}}, "frame_selection": "baseline_frames", "gain_db": 3.653, "gain_source": "output integrated loudness - baseline integrated loudness", "suggestions": []}`  |
### archive × archive_f32 — pass
| Check | Status | Values |
|---|---|---|
| S-05 | pass | `{"expected": "no dither (word length not reduced)"}`  |
| S-06 | pass | `{}`  |
| S-09 | pass | `{"measured": {"channels": 2, "clipped_samples": 0, "dc_offset": [0.00018, 0.000132], "expected_frames": 4746240, "frames": 4746240, "inf": 0, "input_dc_scaled": [0.00018, 0.000132], "nan": 0, "tolerance": 1}, "problems": []}`  |
### Safety invariants (at objective evaluation)
_Safety invariants at objective evaluation; never relaxed by blend or intensity (SPEC 4.3). The per-output verdicts above are final_

S-01: pass / S-02: not_evaluated / S-03: pass / S-04: pass / S-05: not_evaluated / S-06: pass / S-07: not_evaluated / S-08: not_evaluated / S-09: pass / S-10: not_evaluated / S-11: not_evaluated
### Translation gate (OF-5) — incomplete
_Some required checks could not be evaluated (see each reason); incomplete is never a pass. With a 2mix only, the lead checks (band-limited, low level) cannot be evaluated without stems_

| Check | Required | Status | Reason |
|---|---|---|---|
| band_limited_lead_preserved | True | not_evaluated | not_evaluable_without_stems |
| mono_fold_loss_within_limit | True | pass |  |
| low_level_balance_preserved | True | not_evaluated | not_evaluable_without_stems |
| pitch_preserved_without_fundamental | True | pass |  |
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
- Noise-return baseline: `analysis/noise_baseline.json` — measured on the master input built from cleaned assets
- S-08 at planning (simulated): pass → pass — The simulated master passes the noise-return guard (no correction needed)

| Output | S-08 | Gain comp. | shimmer index | side shimmer index | noise floor | HF noise floor |
|---|---|---|---|---|---|---|
| streaming_universal × hires_native | pass | 3.65 dB | +0.01 / 1.5 | +0.01 / 1.5 | -0.02 / 2.0 | +0.01 / 2.0 |
| streaming_universal × distributor_44k16 | pass | 3.65 dB | +0.02 / 1.5 | +0.01 / 1.5 | -0.02 / 2.0 | +0.01 / 2.0 |

_Values are rise / tolerance (dB). Level metrics are compensated by the master gain change (integrated loudness difference); the master is measured on the baseline frames (time-aligned quiet passages and onset gate)_

## 8. Trade-offs and open issues
- [weak_evidence] Thresholds (limiter dependency, mono loss, low-band anti-phase persistence) are practice-level initial values subject to calibration
- [off_target P-11] comfort / P-11: 1.04 against the target [-, 2.50] (penalty 0.50); not achieved
- [not_measured] Terms that could not be measured (P-02, P-09) had their weight redistributed to the measured terms of the same objective; some metrics need stems or the cleanup stage
- [gate_incomplete OF-5] Some required checks could not be evaluated (see each reason); incomplete is never a pass. With a 2mix only, the lead checks (band-limited, low level) cannot be evaluated without stems
- [note R-17] No references are registered: this is an evaluation against a generic prior, not a genre-specific one. v1 ships no statistics taken from commercial tracks (D-039); registering your own tracks with reference add makes their measured distribution the target ranges

## 9. Listening checks (human ears decide)
**Listening conditions**: Listen at a fixed volume / compare before and after only level-matched / use several playback systems (monitors, headphones, smartphone) / decide with rested ears (after long loud listening, high-frequency judgement gets lenient)

- [0:00.0] First 10 s: in a level-matched comparison with the input, is the tone (low-end amount, top-end brightness) as intended?
- [1:02.4] Loudest section: are attacks flattened or is there pumping from the limiter? (GR p95 0.0 dB, max 1.0 dB)
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
- project hash: `2d768503f74c92703a7b82adf890c302ea8bf4f46cf5f7d7edd5782e1a7d358e`
- engine: mankomix 0.1.0 — mankomix.dsp (reference backend)
- ffmpeg: 9.0.2-essentials_build-www.gyan.dev (build: gpl)
  - configuration: `--enable-gpl --enable-version3 --enable-static --disable-w32threads --disable-autodetect --enable-cairo --enable-fontconfig --enable-iconv --enable-gnutls --enable-libxml2 --enable-gmp --enable-bzlib --enable-lzma --enable-zlib --enable-libsrt --enable-libssh --enable-libzmq --enable-avisynth --enable-sdl2 --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxvid --enable-libaom --enable-libopenjpeg --enable-libvpx --enable-mediafoundation --enable-libass --enable-libfreetype --enable-libfribidi --enable-libharfbuzz --enable-libvidstab --enable-libvmaf --enable-libzimg --enable-amf --enable-cuda-llvm --enable-cuvid --enable-dxva2 --enable-d3d11va --enable-d3d12va --enable-ffnvcodec --enable-libvpl --enable-nvdec --enable-nvenc --enable-vaapi --enable-openal --enable-libgme --enable-libopenmpt --enable-libopencore-amrwb --enable-libmp3lame --enable-libtheora --enable-libvo-amrwbenc --enable-libgsm --enable-libopencore-amrnb --enable-libopus --enable-libspeex --enable-libvorbis --enable-librubberband`
- FFmpeg is not bundled; the user's build is called as an external process and its build configuration is recorded
- No models were used in this render
- `renders/var_streaming_universal/master__archive_f32.wav`: seed 4150696403, ceiling None dBTP, iterations None, sha256 `5bfd5e46ea44535c…`
- `renders/var_streaming_universal/streaming_universal__hires_native.wav`: seed 2330183705, ceiling -1.0 dBTP, iterations 1, sha256 `290367910b4a998e…`
- `renders/var_streaming_universal/streaming_universal__distributor_44k16.wav`: seed 2175086977, ceiling -1.0 dBTP, iterations 1, sha256 `3a7672e74fa39098…`
- Same project, assets, engine and backend versions give the same output (bit-identical in the same environment)
