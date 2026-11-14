---
id: out_b465721f74fb
kind: outcome
title: マンコ主義 × 空間音響と複雑なパンニング 結果
song: manko-shugi
request: "空間音響と複雑なパンニング"
pattern: p3
direction: dir_b465721f74fb
created: 2026-11-14
status: active
visibility: public
---

# 結果: 空間音響と複雑なパンニング（p3）

## 主張

ゲートは成立（verify pass、OF-5 は床と同じ incomplete）。主たる主張は 0/3 達成、主張全体 1/6。床とは非収束（差分 RMS -20.81 dB）。

## 実行

- 指揮書 [dir_b465721f74fb](direction.md)、分析メモ [analysis.md](analysis.md)、決定論の結果 [dir_b465721f74fb.outcome.json](dir_b465721f74fb.outcome.json)
- 床のミックス `mxp_e1d4794712c2` に重ねた提案 `mxp_25c0755feb9d`（`direction apply`）→ マスター計画 `mpl_b411cfaaf2a0`（streaming_universal、目標 -14.0 LUFS、差し戻しなし、計画段 S-08 最悪の超過 -1.28 dB）
- ゲート定義ハッシュ apply 時 ba2f2976c595710e = check 時 ba2f2976c595710e（不変）。move_ref の網羅 ok（記録 18 件）

## 実測（描画後）

| 納品形式 | LUFS-I | True Peak | verify |
|---|---|---|---|
| hires_native | -14.011 | -1.01 dBTP | pass |
| distributor_44k16 | -14.007 | -1.01 dBTP | pass |

OF-5（gate）: incomplete（band_limited_lead_preserved not_evaluated、mono_fold_loss_within_limit pass、low_level_balance_preserved not_evaluated、pitch_preserved_without_fundamental pass）。床も同じ incomplete（マスター段にステムを渡さない既知の制約）

## 主張の判定（床とレベルマッチ後に比較）

| id | 主 | 量 | 向き | 必要 | 床 | 結果 | 差 | 判定 |
|---|---|---|---|---|---|---|---|---|
| c1 | ◯ | `obs:o1` | up | 4.0 | -14.917 | -11.374 | +3.544 | not_met |
| c2 | ◯ | `obs:o2` | down | 0.08 | +0.955 | +0.911 | -0.043 | not_met |
| c3 | ◯ | `obs:o3` | not_worse | ±1.0 | -23.668 | -21.828 | +1.839 | not_met |
| c4 |  | `P-02:vs_lead` | not_worse | ±0.3 | — | — | — | not_measured |
| c5 |  | `P-10` | not_worse | ±0.3 | — | — | — | not_measured |
| c6 |  | `obs:o4` | up | 5.0 | -17.079 | -11.500 | +5.578 | met |

- `not_measured`: 台帳指標のうちミックス段の量（P-10、P-22、P-02 系）は、指揮書の提案を床の評価のまま適用するため再測定されない（v0 の道具の空白）。マスター段の P-02 はステムがないため未測定
- ガード不成立: m01:obs:o3, m02:obs:o3, m05:obs:o3, m08:obs:o3, m19:obs:o3, m20:obs:o3
- 手ごとの期待・ガードは手を分離せず全体の結果で判定（v0）

## 人の耳

未試聴。指揮書の `listen_for` を参照
