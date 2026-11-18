# Mix Report — マンコ主義 / var_streaming_universal

## 1. 概要
- 総合結果: **pass**
- 経路: stem_mix (R-21) — ステムとミックス段の結果があるため、ステムミックス経路を選んだ
- 目的関数: low_fatigue×1.0 / intensity 0.5
- 出口: streaming_universal × hires_native → pass (`renders/var_streaming_universal/streaming_universal__hires_native.wav`)
- 目的関数の score（0 が理想、内訳は 5 章）: 0.353 → **0.345**
- トランスレーション・ゲート（OF-5）: incomplete
- ジャンル「ヒップホップ」の prior は、目的関数の重みと目標範囲の初期値にだけ使う（[慣行]）。リファレンスの実測とユーザーの指定が常に優先する
- リファレンスが登録されていないため、汎用の目安に対する評価であり、ジャンルに合わせた評価ではない。v1 は市販曲から得た統計を同梱しない（D-039）。手元の曲を reference add で登録すると、その測定ベクトルの分布が目標範囲になる
- 「low_fatigue」は暫定の目的関数で、聴覚疲労を定量した査読研究は弱い。Mix Report の評価は弱証拠に基づく

## 2. 入力と出所
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
- 取り込み検査: 27
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
- ステム合算の整合は解析段（analyze）の結果を参照。このレポートでは再評価しない

## 3. 測定（前後比較）
_比較はレベルマッチ後の信号で行う（R-01）。幅と定位の値はスピーカー（±30°）とモノ合算を前提にする_

| 指標 | 処理前 | 処理後 |
|---|---|---|
| LUFS-I | -17.63 | -14.00 |
| Short-term max | -15.91 | -12.28 |
| LRA | 2.77 | 2.70 |
| True peak dBTP | -3.64 | -1.01 |
| PLR | 13.99 | 12.99 |
| PSR | 12.28 | 11.27 |

- ラウドネスの変化: +3.6 dB（知覚上の大きさ 約 1.29 倍）
- レベルマッチ後の差（処理後 − 処理前）, match gain -3.632 dB:
  - P-03/lra_lu: -0.07 LU
  - P-03/true_peak_dbtp: -1.00 dBTP
  - P-03/plr_db: -1.00 dB
  - P-03/psr_db: -1.01 dB
  - P-07/partition_bands/sub/level_db: +0.1 dB（知覚上の大きさ 約 1.01 倍）
  - P-07/partition_bands/bass/level_db: +0.1 dB（知覚上の大きさ 約 1.01 倍）
  - P-07/partition_bands/lowmid/level_db: +0.1 dB（知覚上の大きさ 約 1.01 倍）
  - P-07/partition_bands/mid/level_db: -0.0 dB（知覚上の大きさ 約 1.00 倍）
  - P-07/partition_bands/highmid/level_db: -1.0 dB（知覚上の大きさ 約 0.93 倍）
  - P-07/partition_bands/air/level_db: -0.2 dB（知覚上の大きさ 約 0.99 倍）
  - P-04/bands/sub/crest_db: +0.00 dB
  - P-04/bands/bass/crest_db: +0.00 dB
  - P-04/bands/lowmid/crest_db: -0.01 dB
  - P-04/bands/mid/crest_db: +0.02 dB
  - P-04/bands/highmid/crest_db: +0.01 dB
  - P-04/bands/air/crest_db: -0.00 dB
  - P-06/bands/sub/mono_loss_db: -0.00 dB
  - P-06/bands/bass/mono_loss_db: -0.00 dB
  - P-06/bands/lowmid/mono_loss_db: +0.00 dB
  - P-06/bands/mid/mono_loss_db: +0.00 dB
  - P-06/bands/highmid/mono_loss_db: -0.00 dB
  - P-06/bands/air/mono_loss_db: +0.00 dB

_目的関数の代理指標の処理前後。レベルマッチ後に測定した値（R-01）_

| 目的関数 | 指標 | 処理前 | 処理後 | 単位 |
|---|---|---|---|---|
| low_fatigue | P-11 | 1.05 | 0.24 | dB prominence |
| low_fatigue | P-03:lra_density | {"lra_lu": 2.768912987861441, "short_term_p95_p10_lu": 2.76… | {"lra_lu": 2.703989522315265, "short_term_p95_p10_lu": 2.70… | LU |
| low_fatigue | P-17 | 27.30 | 27.29 | dB p99 prominence |
| low_fatigue | P-16 | - | - |  |
| low_fatigue | P-19 | 1.31 | 1.31 | dB |

## 4. 判断の記録
### バランス
- 行動: バランスはミックス段で扱う [R-28]
### 定位
- 行動: 低域のモノ損失と逆相は許容内。ステレオ処理は入れない [R-09]
  - 測定: `{"low_band_hz": 120.0, "low_band_mono_loss_db": 0.02, "low_band_negative_corr": {"longest_run_s": 0.0, "min_corr": 0.486137904123278, "negative_fraction": 0.0, "windows": 234}}`
  - 代替案: 120 Hz 以下のモノ化
- 行動: 定位・幅は変更なし [R-09]
  - 測定: `{"S-03": "pass", "S-04": "pass"}`
### 周波数
- 行動: 明確な帯域の問題が測定されなかったため、EQ は入れない（0 dB） [R-06]
  - 測定: `{"band_ratios_vs_generic_prior": {"air": {"deviation_db": 0.0, "prior_range": [0.0005, 0.12], "ratio": 0.006}, "bass": {"deviation_db": 0.0, "prior_range": [0.05, 0.7], "ratio": 0.60554}, "high_mid": {"deviation_db": 0.0, "prior_range": [0.01, 0.25], "ratio": 0.03586}, "low_mid": {"deviation_db": 0.0, "prior_range": [0.03, 0.3], "ratio": 0.11896}, "mid": {"deviation_db": 0.0, "prior_range": [0.04, 0.4], "ratio": 0.17489}, "sub": {"deviation_db": 0.0, "prior_range": [0.01, 0.6], "ratio": 0.05874}}}`
  - 代替案: 汎用 prior に寄せる小さな補正
  - 結果（予測）: `{"eq_moves": 0}`
- 行動: エンハンスは既定で使わない [R-06]
  - 代替案: 倍音付加（目的が説明できる場合のみ）
- 行動: 目的関数の内訳に沿って小さな手を試し、レベルマッチ後の測定で最良の候補を残した [R-01,R-06,R-15,R-29]
  - 測定: `{"iterations": 3, "score_best": 0.3599445704745145, "score_start": 0.3869574007261305}`
  - high_mid: -0.5 dB（知覚上の大きさ 約 0.97 倍） — キンキン、刺さる
  - high_mid: -0.5 dB（知覚上の大きさ 約 0.97 倍） — キンキン、刺さる
  - high_mid: -0.5 dB（知覚上の大きさ 約 0.97 倍） — キンキン、刺さる
  - 代替案: plan_master の提案をそのまま使う
  - 結果（予測）: `{"converged": true, "reason": "converged: best improvement 0.0047 < 0.005", "s08": {"deltas": {"noise_floor_dbfs": {"delta_db": 0.0, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": -0.33, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 0.48, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.49, "tolerance_db": 1.5}}, "status": "pass", "worst_excess_db": -0.81}, "score": 0.3599445704745145}`
- 行動: レベルマッチ後の測定で判断した [R-01]
  - 測定: `{"P-11": {"after": 0.2410614269678888, "before": 3.138250158898458, "penalty_after": 0.4694017897980169, "penalty_before": 0.596379373149522}, "P-17": {"after": 27.286888000993546, "before": 22.02963597416838, "penalty_after": 0.9999999999990596, "penalty_before": 0.9999998578156953}, "P-19": {"after": 1.305740480494265, "before": 1.3235468273584932, "penalty_after": 0.0, "penalty_before": 0.0}}`
- 行動: high_mid 帯域を -0.5 dB [R-05,R-06]
  - 測定: `"P-11: 2-5 kHz prominence (harshness)"`
  - 代替案: この手を入れない; ミックス段で原因を直す（R-15）
  - 結果（予測）: `{"improvement": 0.01083581510495396, "score_after": 0.37612158562117654}`
- 行動: high_mid 帯域を -0.5 dB [R-05,R-06]
  - 測定: `"P-11: 2-5 kHz prominence (harshness)"`
  - 代替案: この手を入れない; ミックス段で原因を直す（R-15）
  - 結果（予測）: `{"improvement": 0.0091445392906358, "score_after": 0.36697704633054073}`
- 行動: high_mid 帯域を -0.5 dB [R-05,R-06]
  - 測定: `"P-11: 2-5 kHz prominence (harshness)"`
  - 代替案: この手を入れない; ミックス段で原因を直す（R-15）
  - 結果（予測）: `{"improvement": 0.007032475856026232, "score_after": 0.3599445704745145}`
### 奥行き
- 行動: 奥行きはミックス段で扱う
### ダイナミクス
- 行動: 既定でダイナミクス処理なし（マルチバンドは使わない） [R-30]
  - 測定: `{"lra_lu": 2.768912987861441, "plr_db": 13.99379702165553}`
  - 代替案: 軽いシングルバンド・コンプ（1〜2 dB）; マルチバンド（ミックスへ差し戻す代替としてのみ）
- 行動: 正規化される媒体のため目標 -14.0 LUFS に合わせる（配送条件として扱う） [R-18]
  - 測定: `{"input_lufs_i": -17.63, "pre_limiter_lufs_i": -17.63, "profile_target_lufs_i": -14.0, "tried": [{"gr_p95_db": 0.0, "lufs_i": -14.01, "target": -14.0}], "window_lufs_i": [-15.0, -13.5]}`
  - 代替案: より大きい目標（リミッター依存度とノイズ戻りが増える）
  - 結果（予測）: `{"gain_db": 3.63, "lufs_i": -14.01}`
- 行動: 最終段に True Peak リミッター（天井 -1.0 dBTP、リリース 100 ms） [R-14]
  - 測定: `{"limiter_gr": {"gr_fraction_gt_1db": 0.0, "gr_max_db": 1.0, "gr_median_db": 0.0, "gr_p95_db": 0.0}}`
  - 代替案: クリッパーの併用（既定では使わない）; リリース時間の変更（ポンピングとノイズの持ち上がりが変わる）
  - 結果（予測）: `{"true_peak": -1.01}`
- 行動: シミュレーションしたマスターはノイズ戻り監視に合格（是正は不要） [S-08]
  - 測定: `{"baseline": {"cleaned": true, "source": "measured on the master input built from cleaned assets"}, "frame_selection": "baseline frames, time aligned", "s08": {"deltas": {"noise_floor_dbfs": {"delta_db": -0.01, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": 0.01, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 0.02, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.02, "tolerance_db": 1.5}}, "failing": [], "frame_selection": "baseline_frames", "gain_db": 3.623, "margin_db": 0.2, "status": "pass", "verify_tolerance_status": "pass", "worst_excess_db": -1.28}, "scope": "full input, simulated chain"}`
  - 代替案: 許容幅を緩める（ハード制約なので行わない。SPEC 4.3）; マルチバンド処理でノイズを抑える（R-30 により既定では使わない）
  - 結果（予測）: `{"s08": {"deltas": {"noise_floor_dbfs": {"delta_db": -0.01, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"delta_db": 0.01, "tolerance_db": 2.0}, "shimmer_index_db": {"delta_db": 0.02, "tolerance_db": 1.5}, "side_shimmer_index_db": {"delta_db": 0.02, "tolerance_db": 1.5}}, "failing": [], "frame_selection": "baseline_frames", "gain_db": 3.623, "margin_db": 0.2, "status": "pass", "verify_tolerance_status": "pass", "worst_excess_db": -1.28}}`
- 行動: リミッターは天井として扱い、駆動量はレベル補償で一定に保った [R-14]
  - 結果（予測）: `{"gr_fraction_gt_1db": 5.8e-05, "gr_max_db": 1.039, "gr_median_db": 0.0, "gr_p95_db": 0.0001}`
### 仕掛け
- 行動: 「仕掛け」は自動化が最も難しい軸で、人間の指示とリファレンスに依存する。プランナーは展開のコントラストを平坦にしないことだけを監視する [R-26] (depends_on_humans_and_references)
  - リファレンス: リファレンスは登録されていない

## 5. 目的関数の達成度
- 目的関数: low_fatigue×1.00 / intensity 0.5 / 目標の出どころ: 汎用 prior（ジャンルに合わせた評価ではない）
- 主役: trk_vocals
- 評価の出どころ: 適用した提案の評価（プランナーの全尺評価） (full_length), proposal `mpl_b931a5d08147`
- score: 処理前 0.353 → 処理後 **0.345** (low_fatigue 0.345)

| 目的関数 | 指標 | 状態 | 値（前 → 後） | 目標 | penalty（前 → 後） | 実効重み | 寄与 |
|---|---|---|---|---|---|---|---|
| low_fatigue | P-11 | measured | 1.05 → 0.24 dB prominence | [-, 1.75] | 0.495 → 0.469 | 0.353 | 0.166 |
| low_fatigue | P-03:lra_density | measured | {"lra_lu": 2.768912987861441, "short_term_p95_p10_lu": 2.76… → {"lra_lu": 2.703989522315265, "short_term_p95_p10_lu": 2.70… LU | [3.00, 12.00] | 0.006 → 0.010 | 0.294 | 0.003 |
| low_fatigue | P-17 | measured | 27.30 → 27.29 dB p99 prominence | [-, 6.50] | 1.000 → 1.000 | 0.176 | 0.176 |
| low_fatigue | P-16 | not_measured: cleanup stage measurements not available yet (M5) | - → -  | - | - → - | 0.000 | 0.000 |
| low_fatigue | P-19 | measured | 1.31 → 1.31 dB | - | 0.000 → 0.000 | 0.176 | 0.000 |
- 重みの再配分 (low_fatigue): P-16 → 0.150
- **弱証拠**: 「low_fatigue」は暫定の目的関数。聴覚疲労を定量した査読研究は弱く、この評価は弱証拠に基づく（SPEC 4.4）
- 各項の penalty は目標範囲内なら 0、外れるほど 1 に近づく。score は実効重み × penalty の合計で、0 が理想。測定できない項の重みは同じ目的関数の測定できた項へ比例配分し、記録する

## 6. 制約とゲート
### streaming_universal × hires_native — pass
| 検査 | 結果 | 値 |
|---|---|---|
| P-03 | pass | `{"measured": {"lufs_i": -14.0}, "target_lufs_i": -14.0, "window_lufs_i": [-15.0, -13.5]}`  |
| S-01 | pass | `{"ceiling_dbtp": -1.0, "conditional_applied": false, "measured": {"true_peak_dbtp": -1.01}, "oversample": 4}`  |
| S-02 | pass | `{"codec_after_ceiling_dbtp": -0.1, "codecs": {"aac": {"status": "pass", "tp": -0.948}, "mp3": {"status": "pass", "tp": -0.983}, "opus": {"status": "pass", "tp": -0.915}}, "final_limiter_ceiling_dbtp": -1.0, "render_iterations": 1}`  |
| S-05 | pass | `{"expected": "TPDF dither exactly once at the final export (word length reduced)"}`  |
| S-06 | pass | `{}`  |
| S-09 | pass | `{"measured": {"channels": 2, "clipped_samples": 0, "dc_offset": [0.00018, 0.000144], "expected_frames": 4746240, "frames": 4746240, "inf": 0, "input_dc_scaled": [0.000177, 0.000142], "nan": 0, "tolerance": 1}, "problems": []}`  |
| S-03 | pass | `{"limits": {"max_negative_fraction": 0.1, "max_persistence_s": 1.0}, "measured": {"boundary_hz": 120.0, "longest_negative_run_s": 0.1, "min_correlation": -0.4541929709248084, "negative_fraction": 0.0021}}`  |
| S-04 | pass | `{"limits": {"lead_clarity_band_hz": [300, 5000], "lead_clarity_max_db": 3.0, "low_band_max_db": 1.5}, "measured": {"lead_clarity_mono_loss_db": 0.133, "low_band_mono_loss_db": 0.02}}`  |
| OF-5 | incomplete | `{}` see 'translation_gate' (objective evaluation of this master) |
| S-07 | pass | `{"assets": {"ast_backing_vocals": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "ede9e6ba0f18f8b4048f6cd9478fb80a6db13a9f5570842d67f1d42375f6449d", "residual_dbfs": -300.0, "residual_stored_dbfs": -168.723}, "ast_bass": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "b5f3d10865b6284e287b85d7ea8163921943ae1c9be1159e72a2287e10878045", "residual_dbfs": -300.0, "residual_stored_dbfs": -166.229}, "ast_brass": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "81cf4b91ab35a282412351081280da8683bba467b82b943cade2c71a02c9c55a", "residual_dbfs": -300.0, "residual_stored_dbfs": -190.795}, "ast_drums": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "c2551282580f47ad49d1c1345f534334bd4c04ac1038fe97a6b678ebb3a2fadd", "residual_dbfs": -300.0, "residual_stored_dbfs": -159.846}, "ast_fx": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "301ed26dd460be35c250299d504a76432955e7485da5ac4a051e4285ab898b89", "residual_dbfs": -300.0, "residual_stored_dbfs": -180.463}, "ast_guitar": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "df2ff4d636ed930975352964ac5516cd4e36b7172df95e88cc80006a0a7dfb44", "residual_dbfs": -300.0, "residual_stored_dbfs": -172.528}, "ast_keyboard": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "e4efe3197ca63de07605d0114c2a6563fddf584a9edd619798adde713253513a", "residual_dbfs": -300.0, "residual_stored_dbfs": -192.019}, "ast_percussion": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "d736dd6719f6cf0b260445eb481590af3d8e7e4843dcde60453dd0ea51f6e00d", "residual_dbfs": -300.0, "residual_stored_dbfs": -182.443}, "ast_strings": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "ba50c7c719b44fdc7b537576596af7daab5ad35294f4e3bb5a32f6325b23932a", "residual_dbfs": -300.0, "residual_stored_dbfs": -190.514}, "ast_synth": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "fc784e8770712b1ab2b1670d4487036fad52c8c7ecaec42519d50edf3c495722", "residual_dbfs": -300.0, "residual_stored_dbfs": -172.524}, "ast_vocals": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "cd71dd420835085e7df5b4a22809ff9030ac8a137142d3c01a71717f64570b17", "residual_dbfs": -300.0, "residual_stored_dbfs": -166.374}, "ast_woodwinds": {"crossover_hz": 1000.0, "limit_dbfs": -80.0, "pass": true, "plan_hash": "fc94bac9d226437a6012da4c121f10f93a5ae5cea7719d2bf3db0e07ca626e48", "residual_dbfs": -300.0, "residual_stored_dbfs": -176.222}}, "method": "null test: peak of (cleaned - input) after a brick-wall low-pass at the crossover"}`  |
| S-08 | pass | `{"baseline": {"cleaned": true, "cleaned_assets": ["ast_backing_vocals", "ast_bass", "ast_brass", "ast_drums", "ast_fx", "ast_guitar", "ast_keyboard", "ast_percussion", "ast_strings", "ast_synth", "ast_vocals", "ast_woodwinds"], "source": "measured on the master input built from cleaned assets"}, "deltas": {"above_ceiling_level_db": {"after": null, "before": null, "delta_db": null, "note": "not measurable", "pass": null, "tolerance_db": null}, "noise_floor_dbfs": {"after": -25.156, "before": -28.788, "delta_db": 0.001, "gain_compensated": true, "pass": true, "tolerance_db": 2.0}, "noise_floor_hf_dbfs": {"after": -43.498, "before": -46.801, "delta_db": -0.328, "gain_compensated": true, "pass": true, "tolerance_db": 2.0}, "shimmer_index_db": {"after": -41.31, "before": -41.793, "delta_db": 0.483, "gain_compensated": false, "pass": true, "tolerance_db": 1.5}, "side_shimmer_index_db": {"after": -55.363, "before": -55.858, "delta_db": 0.495, "gain_compensated": false, "pass": true, "tolerance_db": 1.5}}, "frame_selection": "baseline_frames", "gain_db": 3.631, "gain_source": "output integrated loudness - baseline integrated loudness", "suggestions": []}`  |
### archive × archive_f32 — pass
| 検査 | 結果 | 値 |
|---|---|---|
| S-05 | pass | `{"expected": "no dither (word length not reduced)"}`  |
| S-06 | pass | `{}`  |
| S-09 | pass | `{"measured": {"channels": 2, "clipped_samples": 0, "dc_offset": [0.00018, 0.000144], "expected_frames": 4746240, "frames": 4746240, "inf": 0, "input_dc_scaled": [0.000177, 0.000142], "nan": 0, "tolerance": 1}, "problems": []}`  |
### 安全不変条件（目的関数の評価時）
_目的関数の評価時の安全不変条件。混合や強度で緩和されない（SPEC 4.3）。出口ごとの最終判定は上の検証結果_

S-01: pass / S-02: not_evaluated / S-03: pass / S-04: pass / S-05: not_evaluated / S-06: pass / S-07: not_evaluated / S-08: not_evaluated / S-09: pass / S-10: not_evaluated / S-11: not_evaluated
### トランスレーション・ゲート（OF-5） — incomplete
_評価できなかった必須の検査がある（各検査の理由を参照）。incomplete は合格扱いにしない。2mix だけの場合、主役に関する検査（帯域制限、小音量）はステムがないと評価できない_

| 検査 | 必須 | 結果 | 理由 |
|---|---|---|---|
| band_limited_lead_preserved | True | not_evaluated | not_evaluable_without_stems |
| mono_fold_loss_within_limit | True | pass |  |
| low_level_balance_preserved | True | not_evaluated | not_evaluable_without_stems |
| pitch_preserved_without_fundamental | True | pass |  |
- 2mix only: lead checks are not evaluable without stems and are not counted as passes

## 7. 整音の記録
- 整音: 適用済み
- 整音は M5 の工程（ミックスとマスタリングの前。R-20）。除去分の音声（delta）を聴いて、息や子音が含まれていないかを確認する
### ast_backing_vocals
- 工程: クリック修復 = run, スペクトル低減 = run, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -280.8 dB | 0.000 | -300.0 |
| presence | 1000–5000 | -23.4 dB | 0.198 | -64.2 |
| sibilance | 5000–8000 | -25.6 dB | 0.169 | -76.9 |
| upper_presence | 8000–10000 | -26.7 dB | 0.157 | -78.6 |
| shimmer | 10000–14000 | -24.8 dB | 0.179 | -83.1 |
| air | 14000–24000 | -22.2 dB | 0.215 | -89.5 |

- 副作用（P-21）: True — 250–500 Hz +0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": -0.112, "bass": -0.0, "high_mid": -0.006, "low_mid": 0.0, "mid": 0.011, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 除去分の音声（試聴用）: `renders/delta/ast_backing_vocals.wav`
### ast_bass
- 工程: クリック修復 = skip, スペクトル低減 = light, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -300.0 dB | 0.000 | -300.0 |
| presence | 1000–5000 | -60.2 dB | 0.015 | -117.7 |
| sibilance | 5000–8000 | -58.4 dB | 0.018 | -137.7 |
| upper_presence | 8000–10000 | -45.8 dB | 0.042 | -134.0 |
| shimmer | 10000–14000 | -37.9 dB | 0.072 | -124.1 |
| air | 14000–24000 | -29.9 dB | 0.126 | -120.3 |

- 副作用（P-21）: True — 250–500 Hz +0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": -0.077, "bass": 0.0, "high_mid": -0.003, "low_mid": 0.0, "mid": -0.001, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 除去分の音声（試聴用）: `renders/delta/ast_bass.wav`
### ast_brass
- 工程: クリック修復 = run, スペクトル低減 = light, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -99.9 dB | 0.001 | -174.4 |
| presence | 1000–5000 | -5.5 dB | 0.685 | -72.5 |
| sibilance | 5000–8000 | -1.4 dB | 0.909 | -78.0 |
| upper_presence | 8000–10000 | -1.3 dB | 0.916 | -79.8 |
| shimmer | 10000–14000 | -3.2 dB | 0.801 | -82.7 |
| air | 14000–24000 | -11.1 dB | 0.465 | -101.1 |

- 副作用（P-21）: True — 250–500 Hz -0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": 3.04, "bass": 0.0, "high_mid": 0.992, "low_mid": 0.0, "mid": 1.368, "sub": null}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 過剰除去の検出により弱めて再実行した
- 除去分の音声（試聴用）: `renders/delta/ast_brass.wav`
### ast_drums
- 工程: クリック修復 = run, スペクトル低減 = light, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -155.1 dB | 0.000 | -176.4 |
| presence | 1000–5000 | -21.7 dB | 0.222 | -56.4 |
| sibilance | 5000–8000 | -17.1 dB | 0.305 | -63.2 |
| upper_presence | 8000–10000 | -18.6 dB | 0.276 | -69.7 |
| shimmer | 10000–14000 | -17.8 dB | 0.291 | -73.7 |
| air | 14000–24000 | -7.0 dB | 0.617 | -74.9 |

- 副作用（P-21）: False — 250–500 Hz -0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": -0.399, "bass": 0.0, "high_mid": -1.147, "low_mid": 0.0, "mid": 0.071, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 除去分の音声（試聴用）: `renders/delta/ast_drums.wav`
### ast_fx
- 工程: クリック修復 = run, スペクトル低減 = run, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -125.2 dB | 0.000 | -177.5 |
| presence | 1000–5000 | -15.0 dB | 0.352 | -70.4 |
| sibilance | 5000–8000 | -8.9 dB | 0.541 | -77.3 |
| upper_presence | 8000–10000 | -8.1 dB | 0.572 | -79.5 |
| shimmer | 10000–14000 | -7.0 dB | 0.616 | -79.3 |
| air | 14000–24000 | -12.0 dB | 0.436 | -88.1 |

- 副作用（P-21）: True — 250–500 Hz +0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": -0.218, "bass": 0.0, "high_mid": 0.047, "low_mid": -0.0, "mid": -0.128, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 過剰除去の検出により弱めて再実行した
- 除去分の音声（試聴用）: `renders/delta/ast_fx.wav`
### ast_guitar
- 工程: クリック修復 = run, スペクトル低減 = skip, 保護 = skip, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -156.2 dB | 0.000 | -191.3 |
| presence | 1000–5000 | -23.4 dB | 0.198 | -67.4 |
| sibilance | 5000–8000 | -16.9 dB | 0.309 | -86.1 |
| upper_presence | 8000–10000 | -2.3 dB | 0.852 | -86.5 |
| shimmer | 10000–14000 | -4.8 dB | 0.720 | -86.7 |
| air | 14000–24000 | -1.3 dB | 0.913 | -91.0 |

- 副作用（P-21）: True — 250–500 Hz -0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": 0.375, "bass": 0.0, "high_mid": 0.018, "low_mid": 0.0, "mid": 0.003, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 除去分の音声（試聴用）: `renders/delta/ast_guitar.wav`
### ast_keyboard
- 工程: クリック修復 = run, スペクトル低減 = skip, 保護 = skip, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -151.1 dB | 0.000 | -183.5 |
| presence | 1000–5000 | -22.9 dB | 0.204 | -77.7 |
| sibilance | 5000–8000 | -2.9 dB | 0.816 | -85.2 |
| upper_presence | 8000–10000 | -2.6 dB | 0.834 | -87.8 |
| shimmer | 10000–14000 | -4.1 dB | 0.752 | -89.5 |
| air | 14000–24000 | -15.1 dB | 0.351 | -103.9 |

- 副作用（P-21）: True — 250–500 Hz -0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": 2.514, "bass": -0.0, "high_mid": 0.177, "low_mid": 0.0, "mid": 0.0, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 除去分の音声（試聴用）: `renders/delta/ast_keyboard.wav`
### ast_percussion
- 工程: クリック修復 = run, スペクトル低減 = light, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -119.2 dB | 0.000 | -176.9 |
| presence | 1000–5000 | -18.8 dB | 0.272 | -69.8 |
| sibilance | 5000–8000 | -7.2 dB | 0.607 | -71.8 |
| upper_presence | 8000–10000 | -7.2 dB | 0.607 | -67.2 |
| shimmer | 10000–14000 | -7.7 dB | 0.586 | -70.4 |
| air | 14000–24000 | -9.1 dB | 0.534 | -85.7 |

- 副作用（P-21）: True — 250–500 Hz +0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": 0.278, "bass": 0.0, "high_mid": -0.645, "low_mid": -0.0, "mid": -0.318, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 除去分の音声（試聴用）: `renders/delta/ast_percussion.wav`
### ast_strings
- 工程: クリック修復 = run, スペクトル低減 = light, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -106.6 dB | 0.001 | -182.9 |
| presence | 1000–5000 | -8.4 dB | 0.560 | -78.7 |
| sibilance | 5000–8000 | -2.7 dB | 0.831 | -83.9 |
| upper_presence | 8000–10000 | -2.6 dB | 0.834 | -84.6 |
| shimmer | 10000–14000 | -3.9 dB | 0.763 | -86.6 |
| air | 14000–24000 | -9.2 dB | 0.528 | -99.9 |

- 副作用（P-21）: True — 250–500 Hz -0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": 2.356, "bass": 0.0, "high_mid": 0.927, "low_mid": 0.0, "mid": 0.238, "sub": null}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 過剰除去の検出により弱めて再実行した
- 除去分の音声（試聴用）: `renders/delta/ast_strings.wav`
### ast_synth
- 工程: クリック修復 = skip, スペクトル低減 = run, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -244.2 dB | 0.000 | -280.9 |
| presence | 1000–5000 | -40.5 dB | 0.060 | -97.8 |
| sibilance | 5000–8000 | -34.4 dB | 0.092 | -114.3 |
| upper_presence | 8000–10000 | -26.7 dB | 0.157 | -109.8 |
| shimmer | 10000–14000 | -22.9 dB | 0.205 | -104.5 |
| air | 14000–24000 | -22.6 dB | 0.209 | -106.1 |

- 副作用（P-21）: True — 250–500 Hz +0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": -0.088, "bass": 0.0, "high_mid": -0.031, "low_mid": 0.0, "mid": -0.003, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 除去分の音声（試聴用）: `renders/delta/ast_synth.wav`
### ast_vocals
- 工程: クリック修復 = run, スペクトル低減 = light, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -265.9 dB | 0.000 | -289.9 |
| presence | 1000–5000 | -23.2 dB | 0.200 | -54.5 |
| sibilance | 5000–8000 | -28.7 dB | 0.137 | -71.8 |
| upper_presence | 8000–10000 | -30.3 dB | 0.123 | -75.3 |
| shimmer | 10000–14000 | -24.8 dB | 0.180 | -77.9 |
| air | 14000–24000 | -18.3 dB | 0.282 | -82.3 |

- 副作用（P-21）: True — 250–500 Hz +0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": -0.13, "bass": -0.0, "high_mid": 0.005, "low_mid": 0.0, "mid": 0.003, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 除去分の音声（試聴用）: `renders/delta/ast_vocals.wav`
### ast_woodwinds
- 工程: クリック修復 = run, スペクトル低減 = run, 保護 = run, 高域補完 = skip

| 帯域 | Hz | 除去量（入力比） | 知覚上の大きさ（sone 比） | dBFS |
|---|---|---|---|---|
| low | 0–1000 | -147.1 dB | 0.000 | -191.8 |
| presence | 1000–5000 | -8.3 dB | 0.562 | -75.0 |
| sibilance | 5000–8000 | -4.0 dB | 0.759 | -85.2 |
| upper_presence | 8000–10000 | -3.1 dB | 0.807 | -85.7 |
| shimmer | 10000–14000 | -4.7 dB | 0.721 | -83.7 |
| air | 14000–24000 | -11.2 dB | 0.460 | -98.7 |

- 副作用（P-21）: True — 250–500 Hz +0.0 dB（知覚上の大きさ 約 1.00 倍） (許容 ±0.5 dB), 幅の変化 `{"air": 1.454, "bass": 0.0, "high_mid": -0.346, "low_mid": 0.0, "mid": -0.053, "sub": 0.0}` (許容 -1.0 dB)
- S-07 低域保護帯の残差: -300.0 dBFS (上限 -80.0 dBFS, 1000.0 Hz) → True
- 過剰除去の検出により弱めて再実行した
- 除去分の音声（試聴用）: `renders/delta/ast_woodwinds.wav`
- ノイズ戻り監視の基準: `analysis/noise_baseline.json` — measured on the master input built from cleaned assets
- 計画時の S-08（シミュレーション）: pass → pass — シミュレーションしたマスターはノイズ戻り監視に合格（是正は不要）

| 出口 | S-08 | ゲイン補正 | シマー指数 | サイドのシマー指数 | ノイズ床 | 高域のノイズ床 |
|---|---|---|---|---|---|---|
| streaming_universal × hires_native | pass | 3.63 dB | +0.48 / 1.5 | +0.49 / 1.5 | +0.00 / 2.0 | -0.33 / 2.0 |

_値は 増加量 / 許容幅（dB）。レベル系はマスターのゲイン変化（統合ラウドネスの差）を補正済み。マスターは基準と同じフレーム（時刻を揃えた静かな区間とオンセットのゲート）で測る_

## 8. トレードオフと未解決事項
- [weak_evidence] 閾値（リミッター依存度、モノ損失、低域の逆相の持続）は [慣行] の初期値で、較正の対象である
- [off_target P-11] low_fatigue / P-11: 目標 [-, 1.75] に対して 0.24（penalty 0.47）。達成できていない
- [off_target P-17] low_fatigue / P-17: 目標 [-, 6.50] に対して 27.29（penalty 1.00）。達成できていない
- [not_measured] 測定できなかった項（P-16）の重みは、同じ目的関数の測定できた項へ比例配分した。ステムや整音段がないと測れない指標がある
- [gate_incomplete OF-5] 評価できなかった必須の検査がある（各検査の理由を参照）。incomplete は合格扱いにしない。2mix だけの場合、主役に関する検査（帯域制限、小音量）はステムがないと評価できない
- [weak_evidence SPEC 4.4] 「low_fatigue」は暫定の目的関数。聴覚疲労を定量した査読研究は弱く、この評価は弱証拠に基づく（SPEC 4.4）
- [note R-17] リファレンスが登録されていないため、汎用の目安に対する評価であり、ジャンルに合わせた評価ではない。v1 は市販曲から得た統計を同梱しない（D-039）。手元の曲を reference add で登録すると、その測定ベクトルの分布が目標範囲になる

## 9. 人の耳で確認すべき点
**試聴の条件**: 音量を固定して聴く／処理前後はレベルマッチ版で比べる／複数の再生環境（モニター、ヘッドホン、スマートフォン）で聴く／耳を休めてから最終判断する（長時間の大音量の後は高域の判断が甘くなる）

- [0:00.0] 最初の 10 秒: 処理前とのレベルマッチ比較で、音色（低域の量、高域の明るさ）が意図どおりか
- [1:02.4] 最も大きい区間: リミッターでアタックが潰れていないか、ポンピングがないか（ゲインリダクション 95 パーセンタイル 0.0 dB、最大 1.0 dB）
- [1:02.4] 最も大きい区間をモノで: 低音が痩せたり消えたりしないか、主役が引っ込まないか
- [1:35.8] 最も静かな区間: ノイズやヒスが目立っていないか、静と動のコントラストが残っているか（R-26）
- [0:00.0] 除去分の音声（`renders/delta/ast_backing_vocals.wav`、ast_backing_vocals）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_bass.wav`、ast_bass）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_brass.wav`、ast_brass）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_drums.wav`、ast_drums）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_fx.wav`、ast_fx）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_guitar.wav`、ast_guitar）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_keyboard.wav`、ast_keyboard）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_percussion.wav`、ast_percussion）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_strings.wav`、ast_strings）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_synth.wav`、ast_synth）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_vocals.wav`、ast_vocals）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）
- [0:00.0] 除去分の音声（`renders/delta/ast_woodwinds.wav`、ast_woodwinds）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）

## 10. 再現情報
- project hash: `74f2ae46fbf494ffebe1f7aec382e9b15bc52ff6e61bae31fc16b984e367ee26`
- engine: mankomix 0.1.0 — mankomix.dsp (reference backend)
- ffmpeg: 9.0.2-essentials_build-www.gyan.dev (build: gpl)
  - configuration: `--enable-gpl --enable-version3 --enable-static --disable-w32threads --disable-autodetect --enable-cairo --enable-fontconfig --enable-iconv --enable-gnutls --enable-libxml2 --enable-gmp --enable-bzlib --enable-lzma --enable-zlib --enable-libsrt --enable-libssh --enable-libzmq --enable-avisynth --enable-sdl2 --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxvid --enable-libaom --enable-libopenjpeg --enable-libvpx --enable-mediafoundation --enable-libass --enable-libfreetype --enable-libfribidi --enable-libharfbuzz --enable-libvidstab --enable-libvmaf --enable-libzimg --enable-amf --enable-cuda-llvm --enable-cuvid --enable-dxva2 --enable-d3d11va --enable-d3d12va --enable-ffnvcodec --enable-libvpl --enable-nvdec --enable-nvenc --enable-vaapi --enable-openal --enable-libgme --enable-libopenmpt --enable-libopencore-amrwb --enable-libmp3lame --enable-libtheora --enable-libvo-amrwbenc --enable-libgsm --enable-libopencore-amrnb --enable-libopus --enable-libspeex --enable-libvorbis --enable-librubberband`
- FFmpeg は同梱せず、ユーザー環境のものを外部プロセスとして呼ぶ。ビルド構成を記録する
- このレンダリングはモデルを使っていない
- `renders/var_streaming_universal/master__archive_f32.wav`: seed 1071705993, ceiling None dBTP, iterations None, sha256 `882db13556bfa69f…`
- `renders/var_streaming_universal/streaming_universal__hires_native.wav`: seed 4108565238, ceiling -1.0 dBTP, iterations 1, sha256 `d4385d1e9491f43c…`
- 同じ正本・素材・エンジンの版・バックエンドの版なら同じ出力になる（同一環境ではビット一致）
