# 曲資料（dossier）— manko-shugi

<!-- 機械生成（mankomix direction dossier v2）。決定論・読み取りのみ。並べるだけで重みづけしない。 -->

- 入力（sha256 先頭 16 桁）: `cache/proposals/mpl_0fc2f2fc9ff7.json` 70e1f2f0cf7808d5、`cache/proposals/mxp_e1d4794712c2.json` d6cbb55bb57f82ec、`project.json` 048677849a6de42b、`reports/verify_var_streaming_universal.json` 5ddfea19d6eedff3、analysis 14 件

## 1. 依頼・媒体・床の指定

- 曲: `manko-shugi`（スラグで指す）
- ジャンル宣言: `hiphop`
- 依頼の原文: 曲資料には載せない（依頼ごとに指揮書の `request.utterance` に記す。この曲資料は依頼をまたいで共通）
- 変種: `var_streaming_universal` / プロファイル `streaming_universal` / 経路 `stem_mix`
- 納品形式: `hires_native`（目標 -14.0 LUFS）, `distributor_44k16`（目標 -14.0 LUFS）
- プロファイルの値（変更不可）: 目標 -14.0 LUFS、窓 [-15, -13.5]、天井 -1.0 dBTP、方針 `gate`、コーデック検査 aac, opus, mp3
- テンプレ（床）の目的関数: `comfort:1.00`、強度 0.50（床 = この目的関数で適用済みのミックスとマスター）
- 長さ 98.88 s、48000 Hz、テンポ 91.2 BPM（estimated）
- 取り込み: `stem_folder`、生成サービス 未申告（生成時のスタイル指定・構成タグはプロジェクトに無い）

## 2. ステム目録

| トラック | 役割 | 主役 | origin | 重要度 | LUFS-I（素材） | TP dBTP | ヘッドルーム dB | 在・不在（区間順） |
|---|---|---|---|---|---|---|---|---|
| trk_backing_vocals | backing_vocals | — | native_stem | 0.50 | -23.7 | -8.43 | 8.43 | ··●●··●●·· |
| trk_bass | bass | — | native_stem | 0.70 | -23.0 | -8.72 | 8.72 | ●●●●●·●●●● |
| trk_brass | brass | — | native_stem | 0.50 | -54.6 | -9.87 | 9.87 | ········●● |
| trk_drums | drums | — | native_stem | 0.80 | -18.7 | -3.73 | 3.73 | ●●●●●●●●●● |
| trk_fx | fx | — | native_stem | 0.30 | -44.6 | -10.73 | 10.73 | ●●●●●●●●●● |
| trk_guitar | guitar | — | native_stem | 0.50 | -28.5 | -8.87 | 8.87 | ·●●●●●●●●· |
| trk_keyboard | keyboard | — | native_stem | 0.50 | -28.6 | -12.20 | 12.20 | ●●●●●●●●●● |
| trk_percussion | percussion | — | native_stem | 0.80 | -37.9 | -10.99 | 10.99 | ···●●●●●●● |
| trk_strings | strings | — | native_stem | 0.50 | -64.1 | -12.97 | 12.97 | ·········· |
| trk_synth | synth | — | native_stem | 0.50 | -30.2 | -15.29 | 15.29 | ●●●●●●●●●● |
| trk_vocals | vocals | 主役 | native_stem | 1.00 | -19.9 | -6.23 | 6.23 | ●●●●●●●●●· |
| trk_woodwinds | woodwinds | — | native_stem | 0.50 | -29.7 | -14.40 | 14.40 | ·●··●···●● |

- origin: `native_stem` = 生成元のステム、`separated` = 分離由来（R-22）、`reference_fullmix` = 参照用の 2 ミックス
- 在・不在: 区間 sec1, sec2, sec3, sec4, sec5, sec6, sec7, sec8, sec9, sec10 の順。● = 区間の積分ラウドネス ≥ -60 LUFS、· = 未満（整音後の素材、フェーダー前）
- 参照 2 ミックス: `ast_fullmix`（ミックスには入らない）

## 3. セクション表

区間はミックス提案（`sections`）の推定。ラベル quiet/mid/loud はその推定の分類。

| 区間 | 秒 | 長さ s | ラベル | 和 LUFS-I | 和 短期最大 | 在ステム数 | 大きい順 2 本（フェーダー込み LUFS） |
|---|---|---|---|---|---|---|---|
| sec1 | 0.0–3.1 | 3.1 | mid | -19.2 | -19.2 | 6 | trk_vocals（-20.7）, trk_drums（-22.3） |
| sec2 | 3.1–32.5 | 29.4 | mid | -17.0 | -15.5 | 8 | trk_vocals（-19.4）, trk_drums（-21.5） |
| sec3 | 32.5–36.3 | 3.8 | quiet | -21.0 | -20.7 | 8 | trk_vocals（-22.8）, trk_drums（-25.6） |
| sec4 | 36.3–50.9 | 14.6 | loud | -15.7 | -15.1 | 9 | trk_vocals（-19.2）, trk_drums（-20.9） |
| sec5 | 50.9–56.3 | 5.4 | mid | -16.9 | -16.3 | 9 | trk_vocals（-18.8）, trk_drums（-23.1） |
| sec6 | 56.3–59.7 | 3.4 | quiet | -20.2 | -20.1 | 7 | trk_vocals（-20.8）, trk_drums（-30.2） |
| sec7 | 59.7–71.5 | 11.8 | loud | -15.0 | -14.4 | 9 | trk_drums（-20.0）, trk_vocals（-20.3） |
| sec8 | 71.5–84.3 | 12.8 | mid | -17.4 | -16.6 | 9 | trk_vocals（-19.1）, trk_drums（-21.8） |
| sec9 | 84.3–95.7 | 11.4 | loud | -17.0 | -15.9 | 10 | trk_drums（-19.5）, trk_bass（-23.8） |
| sec10 | 95.7–98.9 | 3.2 | quiet | -22.8 | -24.2 | 8 | trk_drums（-24.2）, trk_keyboard（-33.3） |

- 「和」= 整音後のステムに床のフェーダーだけを掛けた静的和（パン・処理・バスなし）。描画済みミックスではない
- 密度は在ステム数で示す。帯域ごとの主役数（P-22）は代表区間だけ測られている（§5）

トラック別の区間ラウドネス（LUFS-I、整音後、フェーダー前。— は無音または 0.4 s 未満）

| トラック | sec1 | sec2 | sec3 | sec4 | sec5 | sec6 | sec7 | sec8 | sec9 | sec10 |
|---|---|---|---|---|---|---|---|---|---|---|
| trk_backing_vocals | — | -67.9 | -35.6 | -27.1 | — | — | -21.8 | -56.8 | -61.8 | -63.2 |
| trk_bass | -33.0 | -22.9 | -50.1 | -23.9 | -32.2 | -60.1 | -22.5 | -26.8 | -20.7 | -58.6 |
| trk_brass | — | — | — | — | — | — | — | — | -56.7 | -51.0 |
| trk_drums | -19.9 | -19.1 | -23.2 | -18.5 | -20.7 | -27.8 | -17.6 | -19.4 | -17.1 | -21.8 |
| trk_fx | -43.4 | -42.8 | -54.3 | -58.8 | -59.2 | -50.5 | -39.3 | -46.3 | -48.5 | -43.7 |
| trk_guitar | -68.8 | -27.0 | -30.8 | -28.7 | -51.4 | -43.0 | -31.1 | -47.6 | -28.2 | -65.9 |
| trk_keyboard | -39.3 | -28.3 | -26.9 | -30.8 | -30.7 | -35.3 | -30.5 | -33.0 | -25.5 | -28.8 |
| trk_percussion | -62.0 | -68.7 | -67.6 | -52.3 | -57.1 | -56.0 | -56.2 | -47.0 | -38.3 | -32.1 |
| trk_strings | — | -67.5 | — | -62.4 | — | -64.7 | -67.9 | -67.5 | -67.9 | -60.5 |
| trk_synth | -43.0 | -33.6 | -30.8 | -41.6 | -39.6 | -38.5 | -33.0 | -47.6 | -26.0 | -31.4 |
| trk_vocals | -20.7 | -19.4 | -22.8 | -19.2 | -18.8 | -20.8 | -20.3 | -19.1 | -24.0 | -60.0 |
| trk_woodwinds | — | -48.4 | — | -66.2 | -48.9 | -61.0 | — | — | -28.3 | -32.6 |

- 音声の出どころ: cleaned（cleaned = cache/clean の整音済み、asset = 素材そのまま）
- 代表区間（ミックス評価に使った抜粋）: lead_present 5.50–9.50 s, loudest 61.75–65.75 s, quietest 94.75–98.75 s

## 4. 測定ベクトル

### 4.1 全体とステム別（analysis の要約値。LTAS の全ビンなど生の配列は載せない）

| 対象 | LUFS-I | 短期 p95 | LRA | PLR | PSR | クレスト | 相関 | S/M 比 | モノ損失 最悪帯域 dB | P-07 帯域比 sub/bass/lowmid/mid/highmid/air |
|---|---|---|---|---|---|---|---|---|---|---|
| 静的ステム和 | -15.0 | -12.6 | 4.8 | 14.4 | 11.6 | 16.4 | 0.945 | 0.028 | lowmid 0.33 | 0.06/0.67/0.23/0.05/0.03/0.01 |
| 参照 2 ミックス | -15.5 | -14.1 | 3.3 | 13.0 | 10.9 | 15.0 | 0.963 | 0.018 | lowmid 0.21 | 0.07/0.66/0.22/0.06/0.03/0.01 |
| trk_backing_vocals | -23.7 | -21.1 | 12.3 | 15.3 | 12.4 | 24.3 | 0.541 | 0.230 | lowmid 1.46 | 0.00/0.52/0.39/0.11/0.07/0.02 |
| trk_bass | -23.0 | -21.2 | 12.5 | 14.3 | 10.2 | 17.6 | 0.984 | 0.008 | air 0.24 | 0.01/0.98/0.03/0.00/0.00/0.00 |
| trk_brass | -54.6 | -59.5 | 5.4 | 44.7 | 45.9 | 55.1 | 0.862 | 0.069 | sub 0.59 | 0.00/0.00/0.10/0.47/0.28/0.15 |
| trk_drums | -18.7 | -17.3 | 5.5 | 15.0 | 12.1 | 17.4 | 0.999 | 0.001 | air 0.01 | 0.15/0.74/0.09/0.03/0.03/0.00 |
| trk_fx | -44.6 | -39.3 | 21.4 | 33.9 | 26.1 | 39.3 | 0.998 | 0.001 | air 0.02 | 0.07/0.15/0.41/0.16/0.20/0.02 |
| trk_guitar | -28.5 | -26.8 | 21.8 | 19.7 | 14.9 | 25.7 | 0.936 | 0.032 | sub 0.22 | 0.00/0.37/0.59/0.05/0.08/0.00 |
| trk_keyboard | -28.6 | -25.9 | 11.2 | 16.4 | 10.7 | 20.2 | 0.790 | 0.105 | lowmid 0.62 | 0.00/0.30/0.76/0.02/0.00/0.00 |
| trk_percussion | -37.9 | -34.4 | 29.2 | 26.9 | 19.9 | 38.4 | 0.972 | 0.015 | air 0.40 | 0.00/0.01/0.11/0.32/0.41/0.15 |
| trk_strings | -64.1 | -63.8 | 4.2 | 51.1 | 50.1 | 55.4 | 0.925 | 0.039 | bass 0.58 | 0.00/0.04/0.14/0.39/0.33/0.12 |
| trk_synth | -30.2 | -25.3 | 22.5 | 14.9 | 7.7 | 21.4 | 0.851 | 0.075 | bass 0.84 | 0.00/0.11/0.90/0.02/0.00/0.00 |
| trk_vocals | -19.9 | -18.4 | 5.3 | 13.7 | 11.6 | 16.9 | 0.960 | 0.020 | sub 0.18 | 0.00/0.45/0.40/0.14/0.07/0.01 |
| trk_woodwinds | -29.7 | -27.7 | 27.7 | 15.3 | 13.1 | 30.1 | 0.997 | 0.002 | sub 0.05 | 0.00/0.02/0.99/0.00/0.00/0.00 |

- 素材（整音前・フェーダー前）の測定。P-07 の帯域: sub 20–60、bass 60–250、lowmid 200–800、mid 800–2k、highmid 2k–6k、air 6k–20k Hz

### 4.2 目的関数の項と範囲端までの距離

| 段 | 指標 | 状態 | 値 | 範囲 | 範囲端まで | 範囲の出どころ | 罰 |
|---|---|---|---|---|---|---|---|
| mix | P-01 | measured | 7.558 | — | — | generic_prior | 0.211 |
| mix | P-02 | measured | 7.085 | [0, 3] | 外 4.08 | masking_model | 0.186 |
| mix | P-11 | measured | 1.047 | [−∞, 2.5] | 内 1.45 | thresholds_m3 | 0.495 |
| mix | P-03 | measured | lra_lu 2.77; plr_db 13.99 | lra_lu [2, 15]; plr_db [7, 18] | lra_lu 内 0.77; plr_db 内 4.01 | generic | 0.000 |
| mix | P-09 | measured | — | — | — | module | 0.273 |
| mix | P-12 | measured | 0.640 | — | — | module | 0.000 |
| mix | P-19 | measured | 1.305 | — | — | module | 0.000 |
| master | P-01 | measured | 7.554 | — | — | generic_prior | 0.211 |
| master | P-02 | not_measured | — | [0, 3] | — | masking_model | — |
| master | P-11 | measured | 1.035 | [−∞, 2.5] | 内 1.46 | thresholds_m3 | 0.495 |
| master | P-03 | measured | lra_lu 2.77; plr_db 13.00 | lra_lu [2, 15]; plr_db [7, 18] | lra_lu 内 0.77; plr_db 内 5.00 | generic | 0.000 |
| master | P-09 | not_measured | — | — | — | module | — |
| master | P-12 | measured | 0.019 | — | — | module | 0.000 |
| master | P-19 | measured | 1.307 | — | — | module | 0.000 |

- 範囲端まで: 内 x = 範囲の内側に x の余裕、外 x = x はみ出し。罰は目的関数の値（重みは掛けていない）

### 4.3 ミックス段の測定（ミックス提案 `measurements`、開始 → 最終）

| 量 | 開始 | 最終（床） |
|---|---|---|
| P-10 | -0.650 | 5.770 |
| P-10_verdict | buried | floating |
| P-02_vs_lead_db | 1.257 | 0.684 |
| P-02_overall_db | 6.673 | 7.085 |
| P-22_max_owners | 5.000 | 3.000 |
| P-09_penalty | 0.455 | 0.273 |
| low_ratio_db | 4.550 | 2.770 |
| gate | fail | pass |

- P-10 の目標 [2, 5] dB（ジャンル prior。§7）に対し最終 5.77 dB: 範囲端まで 外 0.77

## 5. ステム間の関係

### 5.1 主役に対するマスキング（P-02。ミックス提案が候補に挙げた対）

| 手 | 覆う側 | 領域 | 帯域 Hz | 主役のピーク Hz | 埋もれ dB | 覆う側の重要度 | 採否 | 結果 |
|---|---|---|---|---|---|---|---|---|
| m3.11 | trk_keyboard | low_mid | [200, 800] | 254 | 0.667 | 0.50 | rejected | no improvement (total change +0.0001) |
| m3.12 | trk_drums | low_mid | [200, 800] | 254 | 0.570 | 0.80 | rejected | no improvement (total change +0.0001) |
| m3.13 | trk_keyboard | low_mid | [200, 800] | 254 | 0.667 | 0.50 | rejected | no improvement (total change +0.0000) |
| m3.14 | trk_drums | low_mid | [200, 800] | 254 | 0.570 | 0.80 | rejected | no improvement (total change +0.0000) |

- 床の P-02: 対主役 0.684 dB、全体 7.085 dB。区間別・対ごとの全表はプロジェクトに保存されていない（§付記）

### 5.2 最低オクターブの占有（素材の P-07 帯域レベル dB、フェーダー込みは床の gain_db を加算）

| トラック | sub 20–60 | bass 60–250 | フェーダー | sub（込み） | bass（込み） |
|---|---|---|---|---|---|
| trk_drums | -29.4 | -22.5 | -2.4 | -31.8 | -24.9 |
| trk_bass | -45.9 | -26.4 | -3.1 | -49.0 | -29.5 |
| trk_vocals | -61.2 | -26.6 | +0.0 | -61.2 | -26.6 |
| trk_fx | -62.1 | -58.8 | -5.9 | -68.0 | -64.7 |
| trk_backing_vocals | -65.9 | -35.6 | -4.5 | -70.4 | -40.1 |
| trk_synth | -66.6 | -46.3 | -4.5 | -71.1 | -50.8 |

- sub（込み）の大きい順に上位 6 本。キックはドラムのステムに含まれる（キック単独のステムはない）

### 5.3 帯域担当（P-22、R-28。ミックス提案 `arrangement`、代表区間ごと）

| ID | 代表区間 | 秒 | 帯域 | 主役数 | 残す | 譲る | 状態 |
|---|---|---|---|---|---|---|---|
| arr1 | lead_present | 5.50–9.50 | bass | 3 | trk_vocals, trk_drums | trk_bass | recommended |
| arr2 | loudest | 61.75–65.75 | bass | 3 | trk_vocals, trk_drums | trk_bass | recommended |
| arr3 | loudest | 61.75–65.75 | mid | 3 | trk_vocals, trk_drums | trk_backing_vocals | recommended |
| arr4 | quietest | 94.75–98.75 | lowmid | 4 | trk_drums, trk_keyboard | trk_synth, trk_woodwinds | recommended |
| arr5 | quietest | 94.75–98.75 | mid | 4 | trk_drums, trk_keyboard | trk_synth, trk_woodwinds | recommended |

- 提案のみ（自動適用されない）。区間ミュート・オクターブ変更はリミックス操作

### 5.4 相関・幅（素材の P-05 全帯域）

- 相関/S/M 比: trk_backing_vocals 0.541/0.230、trk_bass 0.984/0.008、trk_brass 0.862/0.069、trk_drums 0.999/0.001、trk_fx 0.998/0.001、trk_guitar 0.936/0.032、trk_keyboard 0.790/0.105、trk_percussion 0.972/0.015、trk_strings 0.925/0.039、trk_synth 0.851/0.075、trk_vocals 0.960/0.020、trk_woodwinds 0.997/0.002

## 6. 制約までの余裕

### 6.1 verify（`reports/verify_var_streaming_universal.json`。overall: pass）

**streaming_universal / hires_native**: overall pass、LUFS-I -14.007、TP -1.01 dBTP、48000 Hz PCM_24

| 検査 | 状態 | 値と許容 |
|---|---|---|
| OF-5 | not_evaluated | translation gate is implemented in M3 |
| P-03 | pass | lufs_i -14.010; target_lufs_i -14.000; window_lufs_i [-15.00, -13.50] |
| S-01 | pass | ceiling_dbtp -1.000; true_peak_dbtp -1.010; oversample 4.000 |
| S-02 | pass | コーデック後 TP aac -0.95, mp3 -0.99, opus -0.74 dBTP / 天井 -0.1 |
| S-03 | pass | 上限 max_negative_fraction 0.100; 上限 max_persistence_s 1.000; boundary_hz 120.000; longest_negative_run_s 0.100; min_correlation -0.455; negative_fraction 0.002 |
| S-04 | pass | 上限 lead_clarity_band_hz [300.00, 5000.00]; 上限 lead_clarity_max_db 3.000; 上限 low_band_max_db 1.500; lead_clarity_mono_loss_db 0.131; low_band_mono_loss_db 0.020 |
| S-05 | pass | dither tpdf_dither ×1 |
| S-06 | pass | — |
| S-07 | pass | 最大残差 ast_drums -159.8 dBFS / 上限 -80.0 |
| S-08 | pass | noise_floor_dbfs Δ-0.015 / 許容 2.0; noise_floor_hf_dbfs Δ0.005 / 許容 2.0; shimmer_index_db Δ0.018 / 許容 1.5; side_shimmer_index_db Δ0.017 / 許容 1.5 |
| S-09 | pass | nan 0, inf 0, clipped 0, frames 4746240/4746240 |

**streaming_universal / distributor_44k16**: overall pass、LUFS-I -14.004、TP -1.01 dBTP、44100 Hz PCM_16

- 状態: OF-5 not_evaluated, P-03 pass, S-01 pass, S-02 pass, S-03 pass, S-04 pass, S-05 pass, S-06 pass, S-07 pass, S-08 pass, S-09 pass
- S-01: ceiling_dbtp -1.000; true_peak_dbtp -1.007; oversample 5.000
- S-02: コーデック後 TP aac -0.99, mp3 -0.98, opus -0.74 dBTP / 天井 -0.1
- S-08: noise_floor_dbfs Δ-0.016 / 許容 2.0; noise_floor_hf_dbfs Δ0.009 / 許容 2.0; shimmer_index_db Δ0.021 / 許容 1.5; side_shimmer_index_db Δ0.016 / 許容 1.5

### 6.2 マスター計画段（`mpl_0fc2f2fc9ff7`）

- R-14 リミッター GR: p95 0.00 dB（警告 4.0、差し戻し 5.0）、中央値 0.00、最大 1.00、1 dB 超の割合 0.000
- 計画段 S-08: pass（verify 許容での判定 pass）、最悪の超過 -1.28 dB（負 = 許容の内側）、計画余裕 0.20 dB

| S-08 指標 | 模擬の差 dB | verify 許容 | 計画上限（許容 − 余裕） | 計画上限までの余裕 |
|---|---|---|---|---|
| noise_floor_dbfs | -0.01 | 2.00 | 1.80 | 1.81 |
| noise_floor_hf_dbfs | 0.01 | 2.00 | 1.80 | 1.79 |
| shimmer_index_db | 0.02 | 1.50 | 1.30 | 1.28 |
| side_shimmer_index_db | 0.02 | 1.50 | 1.30 | 1.28 |

- 期待値: LUFS-I -14.01、TP -1.01 dBTP（天井 -1.0、コーデック後の天井 -0.1）
- マスター入力: -17.63 LUFS、TP -3.64 dBTP

### 6.3 OF-5（トランスレーション・ゲート、計画時）: incomplete

- band_limited_lead_preserved: not_evaluated（not_evaluable_without_stems）
- mono_fold_loss_within_limit: pass
- low_level_balance_preserved: not_evaluated（not_evaluable_without_stems）
- pitch_preserved_without_fundamental: pass
- 注: 2mix only: lead checks are not evaluable without stems and are not counted as passes

- S-08 の許容（knowledge/cleanup_policy.json、変更不可）: above_ceiling_tol_db 3.0、noise_floor_hf_tol_db 2.0、noise_floor_tol_db 2.0、shimmer_index_tol_db 1.5

## 7. ジャンル prior

- `hiphop`（knowledge/genre_priors.json、状態 draft、等級 practice）: P-10 目標 [2, 5] dB（暫定）、低域の主役 `kick`、重視 P-13, P-02:temporal, P-08、重要度の順 rhythm_core > low_end_foundation > lead_vocal > harmony > pads_fx_ornaments
  - 注記: kick vs 808 separation is central
  - 注記: 808 needs harmonics, not sub only
  - 注記: short, dry-leaning reverb
  - 注記: lead vocal mono-center

**この曲資料で prior 由来の数値**（実測ではない。範囲・重み・目標だけ）

- P-01 の範囲: `generic_prior`
- P-02 の範囲: `masking_model`
- P-11 の範囲: `thresholds_m3`
- P-10 の目標（§4.3）: `genre_prior`
- §2 の重要度: `default`（ジャンルの重要度の順から）
- マスター段の帯域比の範囲（`generic_prior`）: sub [0.01, 0.6]（実測 0.059）、bass [0.05, 0.7]（実測 0.606）、low_mid [0.03, 0.3]（実測 0.119）、mid [0.04, 0.4]（実測 0.175）、high_mid [0.01, 0.25]（実測 0.036）、air [0.001, 0.12]（実測 0.006）

## 8. 抽象プロセッサと宣言範囲

`dsp/processors.py` の登録から機械的に列挙。範囲外の値は validate が拒否する。

| 処理 | 段 |  | パラメーターと宣言範囲 |
|---|---|---|---|
| gain | track/bus/master | — | gain_db -60.00..24.00 dB |
| pan | track/bus | — | position -1.00..1.00; center_db -6.00..0.00 dB |
| filter | track/bus/master | — | kind {hpf/lpf}; freq_hz 10.00..24000.00 Hz; slope_db_oct {6/12/18/24/48} |
| eq | track/bus/master | — | shape {peak/low_shelf/high_shelf/notch}; freq_hz 10.00..24000.00 Hz; gain_db -24.00..24.00 dB; bw_oct 0.02..6.00 oct; phase {minimum/linear} |
| dynamic_eq | track/bus/master | — | shape {peak/low_shelf/high_shelf}; freq_hz 10.00..24000.00 Hz; bw_oct 0.02..6.00 oct; range_db -24.00..24.00 dB; threshold_db -80.00..0.00 dBFS; attack_ms 0.10..200.00 ms; release_ms 5.00..2000.00 ms |
| compressor | track/bus/master | — | threshold_db -60.00..0.00 dBFS; ratio 1.00..30.00 :1; knee_db 0.00..24.00 dB; attack_ms 0.05..300.00 ms; release_ms 5.00..3000.00 ms; detector {peak/rms}; rms_window_ms 1.00..300.00 ms; makeup_db -12.00..24.00 dB; stereo_link bool |
| deesser | track/bus/master | — | freq_hz 2000.00..16000.00 Hz; bw_oct 0.10..4.00 oct; threshold_db -80.00..0.00 dBFS; range_db 0.00..24.00 dB; attack_ms 0.10..50.00 ms; release_ms 5.00..500.00 ms |
| saturator | track/bus/master | — | drive_db 0.00..36.00 dB; mode {tanh/asymmetric}; asymmetry 0.00..1.00 0..1; mix 0.00..1.00 0..1; output_db -24.00..12.00 dB; oversample {1/2/4/8} |
| clipper | track/bus/master | — | mode {hard/soft}; ceiling_db -24.00..0.00 dBFS; drive_db 0.00..24.00 dB; softness 0.00..1.00 0..1; oversample {1/2/4/8} |
| stereo | track/bus/master | — | mono_below_hz 0.00..500.00 Hz; width 0.00..2.00 x; crossovers_hz [20.0..20000.0]×≤8; widths [0.0..2.0]×≤9 |
| reverb | track/bus | — | rt60_s 0.10..10.00 s; predelay_ms 0.00..250.00 ms; er_late_db -24.00..24.00 dB; mix 0.00..1.00 0..1; lowcut_hz 20.00..2000.00 Hz; highcut_hz 1000.00..20000.00 Hz; rt60_low_mult 0.10..4.00 x; rt60_high_mult 0.10..4.00 x; bpm 0.00..400.00 BPM |
| delay | track/bus | — | time_ms 0.10..4000.00 ms; feedback 0.00..0.95 0..1; mix 0.00..1.00 0..1; note {none/1/1/1/1d/1/1t/1/2/1/2d/1/2t/1/4/1/4d/1/4t/1/8/1/8d/1/8t/1/16/1/16d/1/16t/1/32/1/32d/1/32t/1/64/1/64d/1/64t}; bpm 0.00..400.00 BPM; lowcut_hz 0.00..2000.00 Hz; highcut_hz 0.00..24000.00 Hz; route {both/left/right} |
| limiter | master | — | ceiling_dbtp -12.00..0.00 dBTP; lookahead_ms 1.00..10.00 ms; release_ms 5.00..2000.00 ms; oversample {4/8/16} |
| loudness_gain | master/export | — | gain_db -60.00..40.00 dB |
| resample | export | — | target_sr 8000..768000 Hz |
| dither | export | — | bit_depth {16/24}; type {tpdf}; noise_shaping {none} |
| aw.purest_drive | track/bus/master | — | drive 0.00..1.00 norm |
| aw.clip_only2 | track/bus/master | — | input_gain_db -24.00..24.00 dB; ceiling_db -24.00..0.00 dBFS |
| aw.console7_channel | track/bus/master | — | fader 0.00..1.00 norm |
| aw.console7_buss | track/bus/master | — | master 0.00..1.00 norm |
| aw.pressure4 | track/bus/master | — | pressure 0.00..1.00 norm; speed 0.00..1.00 norm; mewiness -1.00..1.00 bipolar; output_gain 0.00..1.00 linear |

- `limiter`・`loudness_gain` はマスター段の固定順（S-06）、`resample`・`dither` は書き出し段。指揮書の不変領域
- `aw.*` はネイティブ実装（Airwindows 移植）。ネイティブが無い環境では参照実装の代替が走る
- 区間ごとの処理切替・パンのオートメーションはない（オートメーションはゲインだけ）

## 9. 床ミックスの構成

床（現在の project.json）のトラック。処理 ID は `chain_param`／`chain_remove` の `replaces` に使う。owner が mixplan 以外の処理には [owner] を付けた。

| トラック | フェーダー dB | パン位置 / 幅 | センド | 出力 | チェーン |
|---|---|---|---|---|---|
| trk_backing_vocals | -4.5 | 0.00 / 1.00 | bus_reverb -15.0 dB | bus_mix | `mx.trk_backing_vocals.hpf` filter(freq_hz=89.1, kind=hpf, slope_db_oct=12)<br>`mx.trk_backing_vocals.yield` eq(bw_oct=1.58, freq_hz=1732, gain_db=-1.5, phase=minimum, shape=peak) |
| trk_bass | -3.1 | 0.00 / 1.00 | — | bus_mix | `mx.trk_bass.hpf` filter(freq_hz=27.5, kind=hpf, slope_db_oct=12)<br>`mx.trk_bass.comp` compressor(attack_ms=30, detector=rms, knee_db=6, makeup_db=2, ratio=2.5, release_ms=328.92, rms_window_ms=30, threshold_db=-24.15) |
| trk_brass | -4.5 | 0.00 / 1.00 | bus_reverb -15.0 dB | bus_mix | `mx.trk_brass.hpf` filter(freq_hz=88.8, kind=hpf, slope_db_oct=12) |
| trk_drums | -2.4 | 0.00 / 1.00 | — | bus_mix | — |
| trk_fx | -5.9 | 0.00 / 1.00 | bus_reverb -13.0 dB | bus_mix | — |
| trk_guitar | -4.5 | 0.35 / 1.00 | bus_reverb -15.0 dB | bus_mix | `mx.trk_guitar.hpf` filter(freq_hz=41.3, kind=hpf, slope_db_oct=12) |
| trk_keyboard | -4.5 | 0.00 / 1.00 | bus_reverb -15.0 dB | bus_mix | — |
| trk_percussion | -2.4 | 0.00 / 1.00 | — | bus_mix | `mx.trk_percussion.hpf` filter(freq_hz=56.2, kind=hpf, slope_db_oct=12) |
| trk_strings | -4.5 | 0.50 / 1.00 | bus_reverb -15.0 dB | bus_mix | `mx.trk_strings.hpf` filter(freq_hz=80, kind=hpf, slope_db_oct=12) |
| trk_synth | -4.5 | 0.00 / 1.00 | bus_reverb -15.0 dB | bus_mix | — |
| trk_vocals | +0.0 | 0.00 / 1.00 | bus_reverb -18.0 dB | bus_mix | `mx.trk_vocals.hpf` filter(freq_hz=84.4, kind=hpf, slope_db_oct=18)<br>`mx.trk_vocals.mud` eq(bw_oct=0.7, freq_hz=254, gain_db=-3, phase=minimum, shape=peak)<br>`mx.trk_vocals.res` eq(bw_oct=0.33, freq_hz=3517.3, gain_db=-3, phase=minimum, shape=peak)<br>`mx.trk_vocals.comp_peak` compressor(attack_ms=2, detector=peak, knee_db=3, makeup_db=0, ratio=4, release_ms=82.23, threshold_db=-17.76)<br>`mx.trk_vocals.comp_level` compressor(attack_ms=25, detector=rms, knee_db=6, makeup_db=4.6, ratio=2, release_ms=657.84, rms_window_ms=30, threshold_db=-27.19)<br>`mx.trk_vocals.deess` deesser(attack_ms=1, bw_oct=1, freq_hz=6500, range_db=6, release_ms=60, threshold_db=-37)<br>`mx.trk_vocals.sat` saturator(drive_db=6, mix=0.25, mode=tanh, output_db=0.05, oversample=2) |
| trk_woodwinds | -4.5 | -0.35 / 1.00 | bus_reverb -15.0 dB | bus_mix | — |

**バス**

| バス | 種別 | 出力 | チェーン |
|---|---|---|---|
| bus_reverb | fx | bus_mix | `mx.bus_reverb.plate` reverb(bpm=91.21, er_late_db=-6, highcut_hz=6000, lowcut_hz=600, mix=1, predelay_ms=41.11, rt60_high_mult=0.6, rt60_low_mult=0.8, rt60_s=0.8) |
| bus_mix | mix | — | `mx.bus_mix.glue` compressor(attack_ms=30, detector=rms, knee_db=6, makeup_db=0, ratio=1.5, release_ms=657.84, rms_window_ms=50, threshold_db=-17.34) |

- パン則: 中央 -3.0 dB。奥行きの宣言順: なし

## 10. 過去知見（kb 抜粋）

### 10.1 経験

並び順は kb 規約（同じ曲の実測 > replicated > measured > literature > practice > tip > hunch、stale は末尾）。最大 8 枚。

- **song_manko-shugi**（song、等級 —、状態 active、同じ曲）マンコ主義
  - 適用条件（front matter）: genre=hiphop
  - 主張: Suno 公式ステム 12 本の hiphop、約 99 秒、91.2 BPM（推定）。公式サンプルセット（v01〜v11）の素材。
- **KL-0001**（lesson、等級 measured、状態 active、同じ曲）目的関数を変えても床のミックスが同一に収束することがある
  - 適用条件（front matter）: genre=hiphop; profile=streaming_universal,club
  - 主張: 目的関数（comfort／bass_heavy／club_impact）を変えても、ミックス計画の固定順の操作が同じ手を選び、音が同一になることがある。変種の差を約束する前に、床との同一収束を機械で確かめる。
- **KM-0001**（move、等級 measured、状態 active、同じ曲）S-08 シマーで差し戻されたらミックス段でドラムのピークを制御する
  - 適用条件（front matter）: genre=hiphop; profile=club
  - 主張: マスター計画が S-08（シマー）で差し戻されたとき、整音の強化ではなく、ミックス段の `trk_drums` にピーク検出のコンプレッサー（閾値 −15 dB、4:1、ニー 3 dB、アタック 1 ms、リリース 60 ms）を足すとリミッターの駆動が減り、S-08 が +1.51 → +1.12 dB に下がって合格した。

### 10.2 理論の棚

active な理論カード（kind: theory）の ID と題だけを全件、ID 順に載せる（22 枚。本文は載せない。10.1 の上限とは別枠）。引くときは `mankomix kb show <ID>`。使うかどうかは指揮者の裁量で、使わなくてよい。

- KT-0001 音程と協和
- KT-0002 音階と調
- KT-0003 和音の構成と転回
- KT-0004 音名と周波数
- KT-0005 倍音と音色
- KT-0006 拍子とリズムの骨格
- KT-0007 ダイアトニックコードと機能
- KT-0008 コードスケールの考え方
- KT-0009 テンションとアヴォイド
- KT-0010 ドミナントの連鎖
- KT-0011 代理と借用
- KT-0012 低音域の間隔の限界
- KT-0013 ベースと分数コード
- KT-0014 和声リズムとセクション
- KT-0015 原液理論
- KT-0016 原液の読み方
- KT-0017 記憶は原液ではない
- KT-0018 参照は作品とクレジットで集める
- KT-0019 リファレンスは正攻法
- KT-0020 マスタリングは古典的な連鎖の量決め
- KT-0021 生成物の劣化は前段で扱う
- KT-0022 判断は要所に置く

### 10.3 リファレンス

案件で指定された作品（work カード）の ID・題・測定資料 refstudy の sha256（先頭 16 桁）だけを載せる。数値の対照は曲資料に入れない（`direction ref compare` の対照表 refsheet）。

- work_manko-shugi-suno-master マンコ主義（生成サービスの整合済みフルミックス）（kb）: refstudy `971fbcdb6bf9e755`

## 11. 床の結果（参考）

### 11.1 ミックス（`mxp_e1d4794712c2`）

- 目的関数の値（罰の合計。小さいほど範囲に近い）: 0.1916、ガード込み 0.2002（ガード項 P-02:vs_lead 0.0000, P-10 0.0164, P-22 0.0369）
- 制約: S-01 pass, S-02 not_evaluated, S-03 pass, S-04 pass, S-05 not_evaluated, S-06 not_evaluated, S-07 not_evaluated, S-08 not_evaluated, S-09 pass, S-10 not_evaluated, S-11 not_evaluated
- 適用された手 40: static_balance 14; subtractive_eq 10; dynamics 4; additive_eq 1; space 10; mix_bus 1
- 棄却された手 4:
  - m3.11 trk_keyboard: trk_keyboard の 254 Hz を -1.3 dB（知覚倍率 約0.91倍）（主役のlow_mid帯域の競合を下げる） → no improvement (total change +0.0001)
  - m3.12 trk_drums: trk_drums の 254 Hz を -1.1 dB（知覚倍率 約0.92倍）（主役のlow_mid帯域の競合を下げる） → no improvement (total change +0.0001)
  - m3.13 trk_keyboard: trk_keyboard の 254 Hz を -1.3 dB（知覚倍率 約0.91倍）（主役のlow_mid帯域の競合を下げる）（半分の量で再試行） → no improvement (total change +0.0000)
  - m3.14 trk_drums: trk_drums の 254 Hz を -1.1 dB（知覚倍率 約0.92倍）（主役のlow_mid帯域の競合を下げる）（半分の量で再試行） → no improvement (total change +0.0000)
- 未解決: `p10_off_target` {"target": [2.0, 5.0], "value": 5.77}
- 未解決: `band_density` {"max_owners": 3, "rule": "R-28", "see": ["arr1", "arr2", "arr3", "arr4", "arr5"]}
- ミックス段の OF-5: pass（band_limited_lead_preserved pass, low_level_balance_preserved pass, mono_fold_loss_within_limit pass, pitch_preserved_without_fundamental pass）

### 11.2 マスター（`mpl_0fc2f2fc9ff7`、streaming_universal / hires_native）

- チェーン: loudness_gain(gain_db=3.63) → limiter(ceiling_dbtp=-1, lookahead_ms=3, oversample=4, release_ms=100)
- 目的関数の値 0.1816（ステムを渡さないため未測定の項: P-02, P-09）
- ラウドネスの試行: 目標 -14.0 → -14.01 LUFS、GR p95 0.00（正規化される媒体のため目標 -14.0 LUFS に合わせる（配送条件として扱う））
- 支配した制約（値の並び。どれが効いたかの判定はしない）: 目標ラウドネス -14.0 LUFS（プロファイル）、R-14 GR p95 0.00 dB、計画段 S-08 最悪の超過 -1.28 dB

### 11.3 実測（verify）

- hires_native: LUFS-I -14.007、TP -1.01 dBTP、overall pass
- distributor_44k16: LUFS-I -14.004、TP -1.01 dBTP、overall pass

## 付記: 載せていない項目

- マスキングの区間別・対ごとの全表、相関の対ごとの表（プロジェクトに保存されていない。追加観察で取る）
- 帯域担当（P-22）の全区間の表（代表区間 3 つだけ測られている）
- セクション別の P-01〜P-22（解析はステム単位の全長値だけ）
- 描画済みミックス・マスターの区間別ラウドネス（写しに描画結果がない。§3 は静的和）
- 生成時の情報（スタイル指定・歌詞の構成タグ）と利用者の感想（プロジェクトに無い）
- LTAS の全ビン、ラウドネスの時系列など生の配列（方針として載せない）
