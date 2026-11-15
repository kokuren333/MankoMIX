---
id: out_9a31fadac3cc
kind: outcome
title: マンコ主義 × 参照フルミックスを読んで移す 結果
song: manko-shugi
request: "参照フルミックス（work_manko-shugi-suno-master）の感じを参考にしたい。写すのではなく、読んで、この曲のミックスに移せるところを取り入れてほしい"
pattern: p4
direction: dir_9a31fadac3cc
created: 2026-11-15
status: active
visibility: public
---

# 結果: 参照フルミックスを読んで移す（p4、経路 1）

## 主張

ゲートは成立（verify pass、OF-5 は床と同じ incomplete）。主たる主張は 0/1 達成、主張全体 3/5。床とは非収束（差分 RMS -31.31 dB）。主たる主張 c1 は向きは合っているが量が足りない（+0.366／必要 +0.5 LU）。

## 実行

- 指揮書 [dir_9a31fadac3cc](direction.md)、分析メモ [analysis.md](analysis.md)、決定論の結果 [dir_9a31fadac3cc.outcome.json](dir_9a31fadac3cc.outcome.json)
- リファレンス: [work_manko-shugi-suno-master](../../../references/works/manko-shugi-suno-master/work.md)（測定資料 [refstudy](../../../references/works/manko-shugi-suno-master/refstudy.md)、対照表 [refsheet](refsheet.md)）。素材は生成サービスのフルミックスで、プロのマスターではない。この結果が示すのは原液経路の機構で、原液の効き目ではない
- 床のミックス `mxp_e1d4794712c2` に重ねた提案 `mxp_b65eb9dc0275`（`direction apply`、較正なし。3 手とも範囲の中央: drums +1.0、bass +1.0、percussion +1.5 dB、sec9 = 84.3–95.7 s の区間ゲイン）→ マスター計画 `mpl_ce687a94b85e`（streaming_universal、目標 -14.0 LUFS、loudness_gain +3.572 dB → limiter、差し戻しなし、計画段 S-08 最悪の超過 -1.28 dB、GR p95 0.00 dB）
- ゲート定義ハッシュ apply 時 ba2f2976c595710e = check 時 ba2f2976c595710e（不変）。move_ref の網羅 ok（記録 3 件: automation:trk_drums／trk_bass／trk_percussion）
- 事前承認の分岐（c1 未達 → m01・m02 を上限へ）は今回実行していない

## 実測（描画後）

| 納品形式 | LUFS-I | True Peak | verify |
|---|---|---|---|
| hires_native | -14.005 | -1.01 dBTP | pass |
| distributor_44k16 | -14.001 | -1.007 dBTP | pass |

OF-5（gate）: incomplete（band_limited_lead_preserved not_evaluated、mono_fold_loss_within_limit pass、low_level_balance_preserved not_evaluated、pitch_preserved_without_fundamental pass）。床も同じ incomplete（マスター段にステムを渡さない既知の制約）

## 主張の判定（床とレベルマッチ後に比較）

| id | 主 | 量 | 向き | 必要 | 床 | 結果 | 差 | 判定 |
|---|---|---|---|---|---|---|---|---|
| c1 | ◯ | `obs:o1` 窓 90.8–93.8 s ラウドネス | up | 0.5 | -12.833 | -12.467 | +0.366 | not_met |
| c2 |  | `obs:o7` sec9 ラウドネス | up | 0.4 | -13.686 | -13.329 | +0.357 | not_met |
| c3 |  | `obs:o2` 窓の mid 比（500–2000 Hz） | down | 0.3 | -7.942 | -8.569 | -0.627 | met |
| c4 |  | `obs:o5` sec2 ラウドネス | not_worse | ±0.3 | -14.322 | -14.382 | -0.060 | met |
| c5 |  | `obs:o6` 窓のクレスト | not_worse | ±1.0 | 11.526 | 11.555 | +0.029 | met |

- ガード不成立: なし
- 手ごとの期待・ガードは手を分離せず全体の結果で判定（v0）。m01 の期待「o1 +0.4」は not_met、m02 の期待「o1 +0.2」・m03 の期待「o4 +0.2」は met

## 参照との距離（参考値・判定外）

`reference_distance` は `ref_value` を付けた 6 観察について |値 − ref_value| を床と結果で並べたもので、**主張の判定には入らない**（判定は上の表のとおり床に対して行う）。change < 0 は結果のほうが参照に近い。

| 観察 | ref_value | 床 | 結果 | change |
|---|---|---|---|---|
| o2 窓の mid 比 | -9.5 | 1.558 | 0.931 | -0.627 |
| o3 窓の sub 比 | -8.5 | 0.638 | 0.433 | -0.205 |
| o4 窓の highmid 比 | -18.3 | 1.113 | 0.828 | -0.285 |
| o6 窓のクレスト | 11.6 | 0.074 | 0.045 | -0.029 |
| o8 全曲の sub 比 | -10.7 | 1.605 | 1.473 | -0.132 |
| o9 全曲の mid 比 | -9.1 | 1.522 | 1.442 | -0.080 |

## 人の耳

未試聴。指揮書の `listen_for` を参照: 59.7 s（hook2 と outro のどちらが山に聞こえるか）、84.3 s（outro 入りの段差）、90.8 s（押し切る感じか、ただ大きいだけか。kick が潰れていないか）、95.7 s（tail 入りでゲインが戻る段差）
