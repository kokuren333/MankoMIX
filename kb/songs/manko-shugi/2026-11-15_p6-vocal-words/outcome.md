---
id: out_89dc56c90b97
kind: outcome
title: マンコ主義 × ボーカルの言葉を前に 結果
song: manko-shugi
request: "ボーカルの言葉をもう少し前に出したい。リファレンスは無し"
pattern: p6
direction: dir_89dc56c90b97
created: 2026-11-15
status: active
visibility: public
---

# 結果: ボーカルの言葉を前に（p6、リファレンス無し）

## 主張

ゲートは成立（verify pass、OF-5 は床と同じ incomplete）。主たる主張は 1/1 達成、主張全体 4/6（測定できたものは 4/5）。床とは非収束（差分 RMS -25.68 dB）。副の主張 c3（verse1 の 2–6 kHz クレスト、アタックの効き）は逆向き（-0.476 dB）で未達。

## 実行

- 指揮書 [dir_89dc56c90b97](direction.md)、分析メモ [analysis.md](analysis.md)、決定論の結果 [dir_89dc56c90b97.outcome.json](dir_89dc56c90b97.outcome.json)
- リファレンス無し。計画の型は 2a・2b を省いた形（分析メモに省いた旨の記載あり）。validate・apply・check はリファレンスありの案件と同じコマンド・同じ扱いで通り、警告は出ていない（validate の warnings は空）。outcome に `reference_distance` の欄は無い（`ref_value` を持つ観察が無いため）
- 床のミックス `mxp_e1d4794712c2` に重ねた提案 `mxp_cfce76eff3b0`（`direction apply`、較正なし。範囲の中央: 声のピークコンプのアタック 2 → 6 ms、2.8 kHz ピーク +1.75 dB（1.4 oct）、プレートへのセンド -18 → -21 dB）→ マスター計画 `mpl_da6e19ae50df`（streaming_universal、目標 -14.0 LUFS、loudness_gain +3.382 dB → limiter、差し戻しなし、計画段 S-08 最悪の超過 -1.28 dB、GR p95 0.00 dB）
- ゲート定義ハッシュ apply 時 ba2f2976c595710e = check 時 ba2f2976c595710e（不変）。move_ref の網羅 ok（記録 3 件: mx.trk_vocals.comp_peak、dr.trk_vocals.m02、send:trk_vocals->bus_reverb）

## 実測（描画後）

| 納品形式 | LUFS-I | True Peak | verify |
|---|---|---|---|
| hires_native | -14.009 | -1.01 dBTP | pass |
| distributor_44k16 | -14.005 | -1.006 dBTP | pass |

S-08 も両形式 pass。OF-5（gate）: incomplete（band_limited_lead_preserved not_evaluated、mono_fold_loss_within_limit pass、low_level_balance_preserved not_evaluated、pitch_preserved_without_fundamental pass）。床も同じ incomplete（マスター段にステムを渡さない既知の制約）

## 主張の判定（床とレベルマッチ後に比較）

| id | 主 | 量 | 向き | 必要 | 床 | 結果 | 差 | 判定 |
|---|---|---|---|---|---|---|---|---|
| c1 | ◯ | `obs:o1` sec2 の 2–6 kHz 比 | up | 0.5 | -17.150 | -16.084 | +1.066 | met |
| c2 |  | `obs:o2` 全曲の 2–6 kHz 比 | up | 0.3 | -14.471 | -13.550 | +0.921 | met |
| c3 |  | `obs:o3` sec2 の 2–6 kHz クレスト | up | 0.3 | 24.130 | 23.654 | -0.476 | not_met |
| c4 |  | `obs:o4` sec2 の 500–2000 Hz 比 | not_worse | ±0.5 | -11.299 | -11.070 | +0.229 | met |
| c5 |  | `obs:o5` 全曲の 6–10 kHz 比 | not_worse（悪化 = up） | ±0.6 | -22.829 | -22.831 | -0.002 | met |
| c6 |  | `P-10` | not_worse | ±0.3 | — | — | — | not_measured |

- `not_measured`: P-10 はミックス段の量で、指揮書の提案は再測定されない（v0 の道具の空白）
- ガード不成立: なし
- 手ごとの期待・ガードは手を分離せず全体の結果で判定（v0）。m01（アタック）の期待「o3 up」は not_met

## 人の耳

未試聴。指揮書の `listen_for` を参照: 5.5 s（verse1: 子音が立って言葉が近く聞こえるか、きつくないか）、32.5 s（break: サ行が刺さらないか、声が乾きすぎないか）、61.75 s（最大区間: 伴奏の中で言葉が読めるか）、71.5 s（verse2: 5.5 s と同じ確認）
