---
id: dir_9a31fadac3cc
kind: direction
title: マンコ主義 × 参照フルミックスを読んで移す 全体指揮書
song: manko-shugi
request: "参照フルミックス（work_manko-shugi-suno-master）の感じを参考にしたい。写すのではなく、読んで、この曲のミックスに移せるところを取り入れてほしい"
pattern: p4
analysis: ana_71399c8d372a
created: 2026-11-15
status: active
visibility: public
---

# 全体指揮書 p4 — マンコ主義 × 「参照フルミックスを読んで移す」

## 1. 狙い
参照の「感じ」を「終盤（outro）をリズム隊が押し切る山」と読み〔推定・確度 medium〕、床で 1 段低くなったその山を戻す（a1）。参照の最大の 3 秒は声の抜けた 90.8–93.8 s にあり全体比 +2.1 LU〔参照: work_manko-shugi-suno-master §4〕、床の同じ窓は +1.17 LU で、床の最大は hook2〔測定・追加〕。声と verse・hook の言葉には触らない（a2）。素材の限界: 参照は生成サービスのフルミックスでプロのマスターではない。この指揮書が示すのは原液経路の機構で、原液の効き目ではない。

## 2. 全体方針
差は sec9（84.3–95.7 s）の区間ゲイン 3 手だけで作る: drums +0.5〜+1.5 dB、bass +0.5〜+1.5 dB、percussion +1.0〜+2.0 dB。outro は drums・bass が全曲で最大、声が -24.0 に退く区間〔測定 §3〕で、ここでリズム隊を上げても主役と引き換えにならない。量は参照の +2.1 LU に合わせず、この曲の壁（ピークがリミッターの GR になる、区間境界の段差、R-26）から決めた。**触らない所**: 声、verse・hook・break のレベル、パンと空間、床のチェーン、マスター（計画器に任せる）。全曲の重心（sub -1.6／mid +1.5 dB の差）は採らず、声の無い outro でだけ結果として出る。

## 3. 手
3 手、すべて mix 段、区間ゲイン（オートメーション、前後 20 ms のランプ）。3 手とも `origin: reference`（E2）。量は範囲で、既定は中央値。ブロック参照。

## 4. 変種別の差分
`streaming_universal`（既定）1 本。参照の -15.5 LUFS／-2.48 dBTP には従わない（プロファイルの窓と天井が上位）。目標 LUFS は既定のまま。

## 5. 到達の主張
床とレベルマッチ後に比較。主たる主張: c1 窓 90.8–93.8 s のラウドネスが +0.5 LU 以上（床 -12.83）。副: c2 sec9 全体のラウドネス +0.4 LU 以上（床 -13.69）、c3 同じ窓の mid 比（500–2000 Hz）が 0.3 dB 以上下がる（床 -7.94）、c4 verse1（sec2）のラウドネスが ±0.3 LU 内（声の区間を動かしていない）、c5 同じ窓のクレストが 1.0 dB 以上落ちない（リミッターが山を潰していない）。参照側に同じ量がある観察（o2 mid 比 -9.5、o3 sub 比 -8.5、o4 highmid 比 -18.3、o6 クレスト 11.6、全曲の o8 sub 比 -10.7・o9 mid 比 -9.1）には `ref_value` を付けた。`reference_distance` は参考値で、主張の判定には入らない。

## 6. 委任範囲と事前承認の分岐
許す: 範囲内の量の選択（`--calibrate` 可）、m03 を S-08 のために外す、区間の端を ±0.3 s 動かす（段差が聞こえる場合）。禁止: 声への手、sec9 以外の区間への拡張、範囲の上限を超える量、参照の値を目標にした量の選択、マスターへの手。分岐: S-08／R-14 → ① trk_drums に KM-0001（ピーク検出コンプ、4:1、アタック 1 ms、リリース 60 ms、閾値 -15 dB 前後）→ ② m01 を下限 0.5 へ → ③ RB-3。c1 未達 → m01・m02 を上限へ。それでも届かなければ未達で出す（上限は超えない）。c5 悪化 → m01 を下限へ（KM-0001 より先）。c4 悪化 → 想定外。床へ戻し RB-3。

## 7. 再召喚してほしい条件
- outro が hook2 より大きくなって、曲の終わり方として不自然に聞こえる（山場の読みが覆る）。
- 84.3 s と 95.7 s の境界でレベルの段差が聞こえる。
- 床との同一収束。

## 8. 採らなかった案と理由
- 全曲の重心を参照側へ（声を下げる／drums を全曲で上げる／sub の EQ）: 声のレベルは p1、sub は p2 が試した問い。P-10 は check で測り直されず主張にできない。EQ で帯域比を写さない（SPEC §4.6）。
- 静かな側の谷を深くする（LRA 差 0.55 LU）: どの区間の差か参照側で不明。break は声主導で主役の区間ゲイン（E3）になる。
- 超低域・高域の側成分: 兆候 1 つずつで生成由来の残りの可能性〔理論: KT-0021〕。S-03／S-08 の余裕を食う。
- -15.5 LUFS／-2.48 dBTP: 不変領域。
- 傾き・エア（差 0.24 dB/oct、0.6 dB）: 暗さは素材の音色（R-17）。
- hook（sec4・sec7）のリズム隊も上げる: 参照が示すのは outro の山で、hook の値は参照側に無い。

## 9. 人の耳で確かめる点
59.7 s（hook2: ここと outro のどちらが山に聞こえるか）、84.3 s（outro 入り: リズム隊 +1 dB の段差）、90.8 s（参照の最大区間: 押し切る感じか、ただ大きいだけか。kick が潰れていないか）、95.7 s（tail 入り: ゲインが戻る段差）。

## 10. 道具の要望
観察量の LRA／区間間のラウドネス差（1 つの量で対比を主張したい）。refstudy の区間をこちらの区分で測る既定（参照側が自動 2 区間だと break・hook を問えない）。

```json direction
{
  "schema_version": 1,
  "kind": "direction",
  "song": "manko-shugi",
  "request": { "pattern": "p4", "utterance": "参照フルミックス（work_manko-shugi-suno-master）の感じを参考にしたい。写すのではなく、読んで、この曲のミックスに移せるところを取り入れてほしい", "like": ["work_manko-shugi-suno-master"] },
  "sources": {
    "analysis": "ana_71399c8d372a",
    "dossier_sha256": "5fdc1f70eaaf51acade06e9c60ea0aec41ea43cd0c23c2c2b5681fda87b84c3d",
    "cards": ["KT-0016", "KT-0021", "KL-0001", "KM-0001"],
    "references": [ { "work": "work_manko-shugi-suno-master", "study_sha256": "971fbcdb6bf9e7558c11b27cf2111a8b1eecd7ecbce1953214a40413cd88cbef", "refsheet_sha256": "0c689ca018b8444a910d33e39054a4ab413aa0e4aa751d592b9b87672b13eb0a" } ]
  },
  "aims": [
    { "id": "a1", "phrase": "参照フルミックスの感じ", "text": "終盤（outro、sec9）をリズム隊が押し切る山として戻す。床では声主導の hook2 が最大で、outro は 1 段低い", "confidence": "medium", "assumption": "参照の最大区間が outro にあることと、この曲のステムが outro で drums・bass 最大であることから読んだ推定。参照は生成サービスのフルミックスで、意図の裏づけは無い" },
    { "id": "a2", "phrase": "写すのではなく、移せるところを", "text": "声の無い区間でだけ動かす。量はこの曲の壁から決め、参照の値を目標にしない。声・verse・hook・空間は床のまま", "confidence": "high", "assumption": "全曲の帯域比・ラウドネス・幅の差は採らない（rejected）" }
  ],
  "variants": [
    { "id": "var_p4", "profile": "streaming_universal", "delivery": ["hires_native", "distributor_44k16"], "target_lufs": null, "reason": "既定。参照の -15.5 LUFS／-2.48 dBTP には従わない（プロファイルが上位）" }
  ],
  "template_use": { "floor": "comfort:0.5", "keep_floor_mix": true, "notes": "床を出発点に sec9 の区間ゲイン 3 手だけを重ねる。床のチェーン・パン・センド・バスはそのまま" },
  "moves": [
    { "id": "m01", "aim": "a1", "stage": "mix", "target": "trk_drums", "section": "sec9", "op": "gain", "processor": null, "params": { "delta_db": [0.5, 1.5] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.4, "unit": "LU" }, { "quantity": "obs:o3", "direction": "up", "min_delta": 0.1, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o6", "direction": "not_worse", "tolerance": 1.0, "worse": "down", "unit": "dB" } ],
      "basis": "ref:work_manko-shugi-suno-master §4（最大区間は 90.8–93.8 s、全体比 +2.1 LU、sub -8.5 dB、S/M -22.9 dB）/ 追加観察（床の同じ窓は全体比 +1.17 LU、sub -9.14 dB）/ 曲資料 §3（sec9 は drums -17.1 で全曲最大、声 -24.0）/ R-26", "origin": "reference" },
    { "id": "m02", "aim": "a1", "stage": "mix", "target": "trk_bass", "section": "sec9", "op": "gain", "processor": null, "params": { "delta_db": [0.5, 1.5] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.2, "unit": "LU" }, { "quantity": "obs:o2", "direction": "down", "min_delta": 0.2, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o5", "direction": "not_worse", "tolerance": 0.3, "unit": "LU" } ],
      "basis": "ref:work_manko-shugi-suno-master §4（最大区間の mid 比 -9.5 dB。床の同じ窓は -7.94 dB）/ 曲資料 §3（sec9 は bass -20.7 で全曲最大）/ drums と同じ量で上げ、低域の分け合い（曲資料 §5.2）を崩さない", "origin": "reference" },
    { "id": "m03", "aim": "a1", "stage": "mix", "target": "trk_percussion", "section": "sec9", "op": "gain", "processor": null, "params": { "delta_db": [1.0, 2.0] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o4", "direction": "up", "min_delta": 0.2, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o6", "direction": "not_worse", "tolerance": 1.0, "worse": "down", "unit": "dB" } ],
      "basis": "ref:work_manko-shugi-suno-master §4（最大区間の highmid 比 -18.3 dB。床の同じ窓は -19.41 dB。兆候 1 つで確度 low）/ 曲資料 §4.1（2–20 kHz を持つ素材は percussion だけ）、§3（sec9 で -38.3）", "origin": "reference" }
  ],
  "claims": [
    { "id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 0.5, "unit": "LU", "primary": true },
    { "id": "c2", "quantity": "obs:o7", "vs": "floor", "direction": "up", "min_delta": 0.4, "unit": "LU", "primary": false },
    { "id": "c3", "quantity": "obs:o2", "vs": "floor", "direction": "down", "min_delta": 0.3, "unit": "dB", "primary": false },
    { "id": "c4", "quantity": "obs:o5", "vs": "floor", "direction": "not_worse", "tolerance": 0.3, "unit": "LU", "primary": false },
    { "id": "c5", "quantity": "obs:o6", "vs": "floor", "direction": "not_worse", "tolerance": 1.0, "worse": "down", "unit": "dB", "primary": false }
  ],
  "observations": [
    { "id": "o1", "primitive": "loudness", "target": "master", "section": { "t0_s": 90.8, "t1_s": 93.8 }, "stat": "integrated", "level_match": true, "unit": "LUFS" },
    { "id": "o2", "primitive": "band_ratio", "target": "master", "band_hz": [500, 2000], "ref_band_hz": [20, 20000], "section": { "t0_s": 90.8, "t1_s": 93.8 }, "stat": "mean", "level_match": true, "unit": "dB", "ref_value": -9.5 },
    { "id": "o3", "primitive": "band_ratio", "target": "master", "band_hz": [20, 60], "ref_band_hz": [20, 20000], "section": { "t0_s": 90.8, "t1_s": 93.8 }, "stat": "mean", "level_match": true, "unit": "dB", "ref_value": -8.5 },
    { "id": "o4", "primitive": "band_ratio", "target": "master", "band_hz": [2000, 6000], "ref_band_hz": [20, 20000], "section": { "t0_s": 90.8, "t1_s": 93.8 }, "stat": "mean", "level_match": true, "unit": "dB", "ref_value": -18.3 },
    { "id": "o5", "primitive": "loudness", "target": "master", "section": "sec2", "stat": "integrated", "level_match": true, "unit": "LUFS" },
    { "id": "o6", "primitive": "crest", "target": "master", "section": { "t0_s": 90.8, "t1_s": 93.8 }, "stat": "mean", "level_match": true, "unit": "dB", "ref_value": 11.6 },
    { "id": "o7", "primitive": "loudness", "target": "master", "section": "sec9", "stat": "integrated", "level_match": true, "unit": "LUFS" },
    { "id": "o8", "primitive": "band_ratio", "target": "master", "band_hz": [20, 60], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB", "ref_value": -10.7 },
    { "id": "o9", "primitive": "band_ratio", "target": "master", "band_hz": [500, 2000], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB", "ref_value": -9.1 }
  ],
  "delegation": {
    "allowed": ["範囲内の量の選択（--calibrate 可）", "m03 を S-08 のために外す", "sec9 の区間の端を ±0.3 s 動かす（段差が聞こえる場合）", "分岐にある KM-0001 の追加"],
    "forbidden": ["狙いの変更・追加", "声（trk_vocals）への手", "sec9 以外の区間への拡張", "範囲の上限を超える量", "参照の値（ref_value、reference_distance）を目標にした量の選択", "マスターへの手", "主張の削除・最小量の引き下げ"]
  },
  "branches": [
    { "on": "S-08|R-14", "do": "trk_drums に chain_add compressor（KM-0001: detector peak、ratio 4、knee 3 dB、attack 1 ms、release 60 ms、threshold -15 dB 前後）。まだ不通なら m01 を下限 0.5 dB、それでも不通なら RB-3" },
    { "on": "claim:c1", "do": "m01・m02 を範囲の上限 1.5 dB へ。それでも +0.5 LU に届かなければ未達で出す（上限は超えない）" },
    { "on": "claim:c5", "do": "m01 を下限 0.5 dB へ（KM-0001 より先。山を潰して大きくしない）" },
    { "on": "claim:c4", "do": "想定外（verse は触っていない）。床へ戻し RB-3" }
  ],
  "recall_on": [
    "outro が hook2 より大きくなり、曲の終わり方として不自然に聞こえる（山場の読みが覆る）",
    "84.3 s／95.7 s の境界でレベルの段差が聞こえる",
    "床との同一収束"
  ],
  "rejected": [
    { "candidate": "全曲の重心を参照側へ（参照は sub 比が 1.6 dB 高く mid 比が 1.5 dB 低い）: 声を下げる／drums を全曲で上げる／sub の EQ", "reason": "声のレベルは p1、sub は p2 が試した問い。P-10 は check で測り直されず主張にできない。EQ で帯域比を写さない（SPEC §4.6）。声の無い outro でだけ結果として出る", "card": "KT-0016" },
    { "candidate": "静かな側の谷を深くする（LRA 参照 3.32／床 2.77）", "reason": "どの区間の差か参照側で不明（自動 2 区間のみ。末尾の窓は差なし）。break は声主導で主役の区間ゲイン（E3）になる。参照の区間別観察が先", "card": null },
    { "candidate": "超低域の側成分（20–40 Hz の S/M -9.2 dB）・高域の側成分（air の S/M が床より 2.0 dB 広い）", "reason": "兆候 1 つずつで、生成由来の残りの可能性。R-09、S-03（最小相関 -0.455）と S-08 side_shimmer の余裕を食う", "card": "KT-0021" },
    { "candidate": "参照のラウドネス -15.5 LUFS／TP -2.48 dBTP に合わせる", "reason": "プロファイルの窓 [-15, -13.5] と天井 -1.0 dBTP が上位（不変領域）", "card": null },
    { "candidate": "傾き（-3.27 対 -3.51 dB/oct）・エア比を高域シェルフで寄せる", "reason": "差が小さく、暗さは素材の音色（R-17）。マッチ EQ はしない", "card": null },
    { "candidate": "hook（sec4・sec7）でもリズム隊を上げる", "reason": "参照が示すのは outro の山で、hook の値は参照側に無い（不明）。床の hook2 は既に最大", "card": null }
  ],
  "listen_for": [
    { "t_s": 59.7, "what": "hook2: ここと outro のどちらが山に聞こえるか" },
    { "t_s": 84.3, "what": "outro 入り: リズム隊 +1 dB 前後の段差が不自然でないか" },
    { "t_s": 90.8, "what": "参照の最大区間: 押し切る感じか、ただ大きいだけか。kick が潰れていないか" },
    { "t_s": 95.7, "what": "tail 入り: ゲインが戻る段差、余韻" }
  ],
  "tool_requests": ["観察量の LRA／2 区間のラウドネス差（対比を 1 つの量で主張する）", "refstudy の区間をこちらのプロジェクトの区分で測る既定（自動 2 区間では break・hook を問えない）"],
  "human_questions": [
    { "q": "山場を outro に戻してよいか（床は hook2 が最大）", "assumed": "控えめに戻す（範囲の中央で outro の窓が hook2 と同程度になる見込み）" },
    { "q": "参照の「感じ」は終盤の押し出しのことか、全体の落ち着いた音量感のことか", "assumed": "終盤の押し出し。音量感（-15.5 LUFS）はプロファイルが決める" }
  ]
}
```
