---
id: out_68e88f393670
kind: outcome
title: マンコ主義 × 聞きごこちを最大追求 結果
song: manko-shugi
request: "聞きごこちを最大追求"
pattern: p1
direction: dir_68e88f393670
created: 2026-11-14
status: active
visibility: public
---

# 結果: 聞きごこちを最大追求（p1）

## 主張

ゲートは成立（verify pass、OF-5 は床と同じ incomplete）。主たる主張は 0/2 達成、主張全体 1/6。床とは非収束（差分 RMS -24.46 dB）。

## 実行

- 指揮書 [dir_68e88f393670](direction.md)、分析メモ [analysis.md](analysis.md)、決定論の結果 [dir_68e88f393670.outcome.json](dir_68e88f393670.outcome.json)
- 床のミックス `mxp_e1d4794712c2` に重ねた提案 `mxp_8eacb9918cd3`（`direction apply`）→ マスター計画 `mpl_e8ee1b89ba9e`（streaming_universal、目標 -14.0 LUFS、差し戻しなし、計画段 S-08 最悪の超過 -1.27 dB）
- ゲート定義ハッシュ apply 時 ba2f2976c595710e = check 時 ba2f2976c595710e（不変）。move_ref の網羅 ok（記録 3 件）

## 実測（描画後）

| 納品形式 | LUFS-I | True Peak | verify |
|---|---|---|---|
| hires_native | -14.010 | -1.01 dBTP | pass |
| distributor_44k16 | -14.006 | -1.01 dBTP | pass |

OF-5（gate）: incomplete（band_limited_lead_preserved not_evaluated、mono_fold_loss_within_limit pass、low_level_balance_preserved not_evaluated、pitch_preserved_without_fundamental pass）。床も同じ incomplete（マスター段にステムを渡さない既知の制約）

## 主張の判定（床とレベルマッチ後に比較）

| id | 主 | 量 | 向き | 必要 | 床 | 結果 | 差 | 判定 |
|---|---|---|---|---|---|---|---|---|
| c1 | ◯ | `P-10` | down | 0.5 | — | — | — | not_measured |
| c2 | ◯ | `obs:o1` | down | 0.4 | -6.025 | -6.365 | -0.341 | not_met |
| c3 |  | `P-02` | down | 0.2 | — | — | — | not_measured |
| c4 |  | `obs:o2` | down | 0.5 | -5.850 | -6.401 | -0.551 | met |
| c5 |  | `P-02:vs_lead` | not_worse | ±0.3 | — | — | — | not_measured |
| c6 |  | `P-22` | not_worse | ±0 | — | — | — | not_measured |

- `not_measured`: 台帳指標のうちミックス段の量（P-10、P-22、P-02 系）は、指揮書の提案を床の評価のまま適用するため再測定されない（v0 の道具の空白）。マスター段の P-02 はステムがないため未測定
- ガード不成立: なし
- 手ごとの期待・ガードは手を分離せず全体の結果で判定（v0）

## 人の耳

未試聴。指揮書の `listen_for` を参照
