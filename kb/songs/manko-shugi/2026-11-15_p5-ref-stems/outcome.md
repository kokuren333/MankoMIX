---
id: out_b86a8a0667a2
kind: outcome
title: マンコ主義 × 配布ステムと p3 の結果を比べて問う 結果
song: manko-shugi
request: "配布ステム（work_manko-shugi-suno-stems）のバランスと、p3（空間・パン）案件の結果を比べて、気になる差を 1 つ以上取り上げて指揮してほしい"
pattern: p5
direction: dir_b86a8a0667a2
created: 2026-11-15
status: active
visibility: public
---

# 結果: 配布ステムと p3 の結果を比べて問う（p5、経路 2 素材 B）

## 主張

ゲートは成立（verify pass、OF-5 は床と同じ incomplete）。主たる主張は 1/2 達成、主張全体 3/5（測定できたものは 3/4）。床とは非収束（差分 RMS -24.96 dB）。問い「p3 の幅が量で届かなかったのは振った楽器が小さいからか」に対して: 側成分比（300–8000 Hz）は +1.257 dB で必要量 +1.5 dB に届かず（向きは合っている）、低域の側成分比は -7.368 dB と大きく減った（p3 が落としたガードはこの手の集合では成立）。

## 実行

- 指揮書 [dir_b86a8a0667a2](direction.md)、分析メモ [analysis.md](analysis.md)、決定論の結果 [dir_b86a8a0667a2.outcome.json](dir_b86a8a0667a2.outcome.json)
- リファレンス: [work_manko-shugi-suno-stems](../../../references/works/manko-shugi-suno-stems/work.md)（測定資料 [refstudy](../../../references/works/manko-shugi-suno-stems/refstudy.md)、対照表 [refsheet](refsheet.md)。対照表の「こちら」は p3 の結果）。素材は生成サービスの配布ステムで、プロのステムではない。この結果が示すのは原液経路の機構で、原液の効き目ではない
- 作業プロジェクトは床の写し（p3 の上には重ねていない）。p3 との比較は「配置の核 4 手＋ゲイン 4 手＋低域モノ分割の 9 手でどこまで出るか」
- 床のミックス `mxp_e1d4794712c2` に重ねた提案 `mxp_4e50866fab8d`（`direction apply`、較正なし。範囲の中央: keyboard 位置 -0.425・幅 1.3、synth +0.425・1.3、guitar +0.7、woodwinds -0.7、4 本のゲイン各 +1.75 dB（フェーダー -4.5 → -2.75 dB）、bus_mix に 120 Hz 以下のモノ分割）→ マスター計画 `mpl_d864bb56d7c4`（streaming_universal、目標 -14.0 LUFS、loudness_gain +3.635 dB → limiter、差し戻しなし、計画段 S-08 最悪の超過 -1.28 dB、GR p95 0.00 dB）
- ゲート定義ハッシュ apply 時 ba2f2976c595710e = check 時 ba2f2976c595710e（不変）。move_ref の網羅 ok（記録 1 件: `dr.bus_mix.m09`。パンとフェーダーの静的な変更は記録の対象外で、`moves_without_trace` は空）
- 事前承認の分岐（c1 未達 → m05–m08 を上限、m03／m04 を外側の端へ）は今回実行していない

## 実測（描画後）

| 納品形式 | LUFS-I | True Peak | verify |
|---|---|---|---|
| hires_native | -14.012 | -1.01 dBTP | pass |
| distributor_44k16 | -14.008 | -1.007 dBTP | pass |

S-03・S-04 も両形式 pass。OF-5（gate）: incomplete（band_limited_lead_preserved not_evaluated、mono_fold_loss_within_limit pass、low_level_balance_preserved not_evaluated、pitch_preserved_without_fundamental pass）。床も同じ incomplete（マスター段にステムを渡さない既知の制約）

## 主張の判定（床とレベルマッチ後に比較）

| id | 主 | 量 | 向き | 必要 | 床 | 結果 | 差 | 判定 |
|---|---|---|---|---|---|---|---|---|
| c1 | ◯ | `obs:o1` 側成分比 300–8000 Hz（全曲） | up | 1.5 | -14.917 | -13.661 | +1.257 | not_met |
| c2 | ◯ | `obs:o2` 側成分比 20–120 Hz（全曲） | not_worse（悪化 = up） | ±1.0 | -23.668 | -31.036 | -7.368 | met |
| c3 |  | `obs:o3` 側成分比 300–8000 Hz（sec9） | up | 3.0 | -19.371 | -14.977 | +4.394 | met |
| c4 |  | `obs:o4` 200–800 Hz 比（全曲） | not_worse（悪化 = up） | ±0.8 | -6.025 | -6.032 | -0.007 | met |
| c5 |  | `P-02:vs_lead` | not_worse | ±0.3 | — | — | — | not_measured |

- `not_measured`: P-02 系はミックス段の量で、指揮書の提案は再測定されない（v0 の道具の空白）
- ガード不成立: なし（測定できたガードはすべて成立。m03・m04・m07 の P-02:vs_lead ガードは not_measured）
- 手ごとの期待・ガードは手を分離せず全体の結果で判定（v0）

## 参照との距離（参考値・判定外）

`reference_distance` は `ref_value` を付けた 2 観察について |値 − ref_value| を床と結果で並べたもので、**主張の判定には入らない**。change > 0 は結果のほうが参照から遠い（指揮書 rejected のとおり、参照の幅へ狭めることは採っていないので、開く向きは想定どおり）。

| 観察 | ref_value | 床 | 結果 | change |
|---|---|---|---|---|
| o5 全帯域の側成分比 | -17.28 | 0.940 | 1.218 | +0.277 |
| o6 相関 | 0.963 | 0.008 | 0.011 | +0.003 |

## 人の耳

未試聴。指揮書の `listen_for` を参照: 3.1 s（verse1: keyboard 左・synth 右が上がって声の言葉を邪魔しないか）、36.3 s（hook1: guitar 右が聞こえる大きさか、左右の重心が傾かないか）、84.3 s（outro: woodwinds 左・guitar 右が配置として読めるか、lowmid が濁らないか、モノでも 2 本が消えないか）
