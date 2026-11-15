---
id: dir_b86a8a0667a2
kind: direction
title: マンコ主義 × 配布ステムと p3 の結果を比べて問う 全体指揮書
song: manko-shugi
request: "配布ステム（work_manko-shugi-suno-stems）のバランスと、p3（空間・パン）案件の結果を比べて、気になる差を 1 つ以上取り上げて指揮してほしい"
pattern: p5
analysis: ana_07d5fb9f2022
created: 2026-11-15
status: active
visibility: public
---

# 全体指揮書 p5 — マンコ主義 × 「配布ステムと p3 の結果を比べて問う」

## 1. 狙い
取り上げる差は 1 つ: p3 が左右に振った和声の 4 本（guitar・keyboard・synth・woodwinds）は、配布ステムの釣り合いより 3.7〜5.2 LU 小さい〔参照: work_manko-shugi-suno-stems refsheet §2〕。問い: 「p3 の幅が量で届かなかったのは、振った楽器自体が小さいからではないか」。答えを確かめるために、4 本を配置したうえで聞こえる大きさへ持ち上げる（a1）。p3 が落とした低域の側成分は初めから守る（a2）。素材の限界: 参照は生成サービスの配布ステムでプロのステムではない。この指揮書が示すのは原液経路の機構で、原液の効き目ではない。

## 2. 全体方針
床の写しから指揮する（p3 の上には重ねない）。(a) p3 の配置の核 4 手を事例として再使用: keyboard LC、synth RC（幅 1.2〜1.4）、guitar R、woodwinds L。(b) その 4 本にゲイン +1.0〜+2.5 dB。参照の「中央で大きい」は写さない: 4 本は lowmid に集まり P-02 全体は範囲の外〔測定 §4.1, §4.2〕なので、**側へ逃がしてから上げる**のがこの曲での翻訳。上限 2.5 dB は参照との差を埋める量ではなく、lowmid 比のガードから決めた。(c) bus_mix に 120 Hz 以下のモノ分割（R-09。p3 は低域の側成分比 +1.84 dB で c3 不成立）。**触らない所**: 声・drums・bass・backing_vocals、床のプレート、マスター。p3 の遠い部屋・L/R エコー・Haas・帯域別ワイドナーは入れない（問いを 1 つに絞る）。

## 3. 手
9 手、すべて mix 段、静的。m01–m04 配置（`origin: case`）、m05–m08 ゲイン（`origin: reference`）、m09 低域モノ分割（`origin: case`）。ブロック参照。

## 4. 変種別の差分
`streaming_universal`（既定）1 本。モノ折返し検査（S-04）が付く出口。

## 5. 到達の主張
床とレベルマッチ後に比較。主たる主張: c1 側成分比（300–8000 Hz）が +1.5 dB 以上（床 -14.92。p3 は 19 手で +3.54）、c2 低域（20–120 Hz）の側成分比が 1.0 dB を超えて増えない（床 -23.67。p3 が落とした主張）。副: c3 outro（sec9）の側成分比 +3.0 dB 以上（床 -19.37。4 本が全部鳴る区間）、c4 lowmid 比（200–800 Hz）の増加が 0.8 dB 以内、c5 P-02 対主役不変（±0.3。check では未測定になる見込み）。全帯域の S/M（o5、参照 -17.28）と相関（o6、参照 0.963）には `ref_value` を付けた。この指揮は参照のマスターより**広い側へ離れる**ので `reference_distance` は開く見込みだが、距離は参考値で判定に入らない。

## 6. 委任範囲と事前承認の分岐
許す: 範囲内の量の選択（`--calibrate` 可）、全体を鏡像（L↔R）にする、4 本のゲインを個別に範囲内で変える。禁止: 声・drums・bass のレベル・パン・処理、120 Hz 以下の幅を増やす、ゲインの上限 2.5 dB 超え（参照との差を埋めに行かない）、p3 の空間の手（バス・エコー・Haas・ワイドナー）の追加、主張の引き下げ。分岐: c1 未達 → m05–m08 を上限、m03／m04 の位置を外側の端へ → それでも届かなければ未達で出し再召喚（「小ささが原因」という読みが弱い）。c4 悪化 → m05・m06（keyboard・synth）を下限 1.0 へ。c2 悪化 → m01 の位置を -0.35、幅を 1.2 へ。S-03／S-04 → m01・m02 の幅を 1.0 へ。

## 7. 再召喚してほしい条件
- 4 本を上限まで上げても c1 が +1.5 dB に届かない（Q1 の読みが覆る。幅を作るのはレベルではなく空間の手だった）。
- 和声が上がって verse の声の言葉が聞き取りにくくなった（声 > 配置の優先順位）。
- 床との同一収束。

## 8. 採らなかった案と理由
- 声を下げて主役対伴奏を参照（-3.12 LU）へ: 写さない。声のレベルは p1 が試し、P-10 は check で測れない。4 本を上げる結果として少し縮むだけ。
- 全役割を中央に戻す: 中央定位が意図か書き出しの既定かは不明。
- 幅を参照のマスター（S/M -17.28 dB）へ狭める: 参照の値は目標ではない。
- backing_vocals・bass も上げる: BV は lowmid のモノ損失 1.46 dB、bass は帯域担当で譲る側。
- 和とマスターの差分（幅 -1.81 dB、クレスト -1.47 dB）からバス処理を足す: 差分は信頼できない（確度上限 low）。
- 4 本を中央のまま上げる: P-02 全体 7.085 が範囲の外。この曲の測定を優先。
- fx・brass・strings: 実質無音か間欠で、幅にも釣り合いにも効かない。

## 9. 人の耳で確かめる点
3.1 s（verse1: keyboard 左・synth 右が上がって声の言葉を邪魔しないか）、36.3 s（hook1: guitar 右が聞こえる大きさか）、84.3 s（outro: woodwinds 左・guitar 右が配置として読めるか。lowmid が濁らないか）、モノ再生で 84.3 s（woodwinds と guitar が消えないか）。

## 10. 道具の要望
トラック寄与の観察量（`trk_*`）、適用後のミックス段の台帳指標（P-10、P-02 系）の測り直し、既存の指揮結果（p3）の上に差分だけを重ねる適用。

```json direction
{
  "schema_version": 1,
  "kind": "direction",
  "song": "manko-shugi",
  "request": { "pattern": "p5", "utterance": "配布ステム（work_manko-shugi-suno-stems）のバランスと、p3（空間・パン）案件の結果を比べて、気になる差を 1 つ以上取り上げて指揮してほしい", "like": ["work_manko-shugi-suno-stems"] },
  "sources": {
    "analysis": "ana_07d5fb9f2022",
    "dossier_sha256": "93218a14d406402c7005aed6a02a54853819dac4d6e616a049c9c9764edbd439",
    "cards": ["KL-0001", "dir_b465721f74fb", "out_b465721f74fb"],
    "references": [ { "work": "work_manko-shugi-suno-stems", "study_sha256": "90f9b14ee7ed95edf6dbc5361d7db3ea7a63c0183e8ffa7d88970559ce9ea9eb", "refsheet_sha256": "1ed3c11d417d0fd5031d5ebd3bcfdbfe520b2a6e2c0f40401f451a1ed5ff81bb" } ]
  },
  "aims": [
    { "id": "a1", "phrase": "気になる差を 1 つ以上取り上げて", "text": "p3 が左右に振った和声の 4 本（guitar・keyboard・synth・woodwinds）を、配置したうえで聞こえる大きさへ持ち上げる。問い: p3 の幅の量不足は、振った楽器が小さいからか", "confidence": "medium", "assumption": "配布ステムの相対レベルが意図した釣り合いかは不明（ステム和はフルミックスを再現しない）。差を埋めるのでなく、問いを確かめる量だけ動かす" },
    { "id": "a2", "phrase": "p3（空間・パン）案件の結果を比べて", "text": "p3 が落とした低域の側成分の主張を初めから守る。声・drums・bass は床のまま", "confidence": "high", "assumption": "p3 の outcome（低域の側成分比 +1.84 dB）は配置と幅が原因" }
  ],
  "variants": [
    { "id": "var_p5", "profile": "streaming_universal", "delivery": ["hires_native", "distributor_44k16"], "target_lufs": null, "reason": "既定。モノ折返し検査（S-04）が付く出口" }
  ],
  "template_use": { "floor": "comfort:0.5", "keep_floor_mix": true, "notes": "床の写しを出発点にする（p3 の結果には重ねない）。配置 4 手は p3 の事例の再使用、ゲイン 4 手がリファレンス由来" },
  "moves": [
    { "id": "m01", "aim": "a1", "stage": "mix", "target": "trk_keyboard", "section": null, "op": "pan", "processor": null, "params": { "position": [-0.5, -0.35], "width": [1.2, 1.4] }, "select": { "position": "mid", "width": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.3, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o2", "direction": "not_worse", "tolerance": 1.0, "worse": "up", "unit": "dB" } ],
      "basis": "dir_b465721f74fb m01 の再使用（p3 の実測: 床と非収束）/ 曲資料 §5.4 keyboard 相関 0.79", "origin": "case" },
    { "id": "m02", "aim": "a1", "stage": "mix", "target": "trk_synth", "section": null, "op": "pan", "processor": null, "params": { "position": [0.35, 0.5], "width": [1.2, 1.4] }, "select": { "position": "mid", "width": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.3, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o2", "direction": "not_worse", "tolerance": 1.0, "worse": "up", "unit": "dB" } ],
      "basis": "dir_b465721f74fb m02 の再使用 / 曲資料 §5.4 synth 相関 0.85。keyboard と対称", "origin": "case" },
    { "id": "m03", "aim": "a1", "stage": "mix", "target": "trk_guitar", "section": null, "op": "pan", "processor": null, "params": { "position": [0.6, 0.8] }, "select": { "position": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.2, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "dir_b465721f74fb m03 の再使用（床 +0.35 を R へ）", "origin": "case" },
    { "id": "m04", "aim": "a1", "stage": "mix", "target": "trk_woodwinds", "section": null, "op": "pan", "processor": null, "params": { "position": [-0.8, -0.6] }, "select": { "position": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o3", "direction": "up", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "dir_b465721f74fb m04 の再使用（床 -0.35 を L へ）/ 曲資料 §3 woodwinds は sec9–10 が本番", "origin": "case" },
    { "id": "m05", "aim": "a1", "stage": "mix", "target": "trk_keyboard", "section": null, "op": "gain", "processor": null, "params": { "delta_db": [1.0, 2.5] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.3, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o4", "direction": "not_worse", "tolerance": 0.8, "worse": "up", "unit": "dB" } ],
      "basis": "ref:work_manko-shugi-suno-stems §6.2（keyboard の和との差 -13.6 LU。refsheet §2.7 で p3 は -17.3 LU）/ 曲資料 §9（床のフェーダー -4.5 dB）、§4.3（P-10 5.77 は目標の外）/ 側へ置いてから上げる（曲資料 §4.2 P-02 全体 7.085）", "origin": "reference" },
    { "id": "m06", "aim": "a1", "stage": "mix", "target": "trk_synth", "section": null, "op": "gain", "processor": null, "params": { "delta_db": [1.0, 2.5] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.3, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o4", "direction": "not_worse", "tolerance": 0.8, "worse": "up", "unit": "dB" } ],
      "basis": "ref:work_manko-shugi-suno-stems §6.2（synth の和との差 -15.2 LU。refsheet §2.10 で p3 は -19.2 LU）/ 曲資料 §9、§4.1（lowmid 比 0.90 → ガード o4）", "origin": "reference" },
    { "id": "m07", "aim": "a1", "stage": "mix", "target": "trk_guitar", "section": null, "op": "gain", "processor": null, "params": { "delta_db": [1.0, 2.5] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.2, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "ref:work_manko-shugi-suno-stems §6.2（guitar の和との差 -13.5 LU。refsheet §2.6 で p3 は -18.7 LU、L/R 差 -9.4 dB）/ 曲資料 §9", "origin": "reference" },
    { "id": "m08", "aim": "a1", "stage": "mix", "target": "trk_woodwinds", "section": null, "op": "gain", "processor": null, "params": { "delta_db": [1.0, 2.5] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o3", "direction": "up", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o4", "direction": "not_worse", "tolerance": 0.8, "worse": "up", "unit": "dB" } ],
      "basis": "ref:work_manko-shugi-suno-stems §6.2（woodwinds の和との差 -14.6 LU。refsheet §2.12 で p3 は -19.6 LU、L/R 差 9.3 dB）/ 曲資料 §3（sec9 -28.3）", "origin": "reference" },
    { "id": "m09", "aim": "a2", "stage": "mix", "target": "bus_mix", "section": null, "op": "chain_add", "processor": "stereo", "params": { "mono_below_hz": 120.0 }, "select": {}, "replaces": null,
      "expect": [ { "quantity": "obs:o2", "direction": "not_worse", "tolerance": 1.0, "worse": "up", "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o1", "direction": "not_worse", "tolerance": 0.3, "worse": "down", "unit": "dB" } ],
      "basis": "R-09 / mix_rules mix_bus.mono_below_hz 120 / out_b465721f74fb（p3 は低域の側成分比 +1.84 dB で c3 不成立。p3 の分岐にあった手を初めから入れる）/ 曲資料 §4.1 keyboard は bass 帯 30%", "origin": "case" }
  ],
  "claims": [
    { "id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 1.5, "unit": "dB", "primary": true },
    { "id": "c2", "quantity": "obs:o2", "vs": "floor", "direction": "not_worse", "tolerance": 1.0, "worse": "up", "unit": "dB", "primary": true },
    { "id": "c3", "quantity": "obs:o3", "vs": "floor", "direction": "up", "min_delta": 3.0, "unit": "dB", "primary": false },
    { "id": "c4", "quantity": "obs:o4", "vs": "floor", "direction": "not_worse", "tolerance": 0.8, "worse": "up", "unit": "dB", "primary": false },
    { "id": "c5", "quantity": "P-02:vs_lead", "vs": "floor", "direction": "not_worse", "tolerance": 0.3, "unit": "dB", "primary": false }
  ],
  "observations": [
    { "id": "o1", "primitive": "side_ratio", "target": "master", "band_hz": [300, 8000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o2", "primitive": "side_ratio", "target": "master", "band_hz": [20, 120], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o3", "primitive": "side_ratio", "target": "master", "band_hz": [300, 8000], "section": "sec9", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o4", "primitive": "band_ratio", "target": "master", "band_hz": [200, 800], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o5", "primitive": "side_ratio", "target": "master", "section": "all", "stat": "mean", "level_match": true, "unit": "dB", "ref_value": -17.28 },
    { "id": "o6", "primitive": "correlation", "target": "master", "section": "all", "stat": "mean", "level_match": true, "unit": "coefficient", "ref_value": 0.963 }
  ],
  "delegation": {
    "allowed": ["範囲内の量の選択（--calibrate 可）", "全体を鏡像（L↔R）にする", "m05–m08 のゲインを個別に範囲内で変える"],
    "forbidden": ["狙いの変更・追加", "vocals・drums・bass のレベル・パン・幅・処理", "120 Hz 以下の幅を増やす", "ゲインの上限 2.5 dB を超える（参照との差を埋めに行かない）", "p3 の空間の手（新バス・エコー・Haas・帯域別ワイドナー）の追加", "参照の値（ref_value、reference_distance）を目標にした量の選択", "主張の削除・最小量の引き下げ"]
  },
  "branches": [
    { "on": "claim:c1", "do": "m05–m08 を上限 2.5 dB、m03／m04 の位置を外側の端（0.8／-0.8）へ。それでも +1.5 dB に届かなければ未達で出して再召喚（『小ささが原因』という読みが弱い）" },
    { "on": "claim:c4", "do": "m05・m06（keyboard・synth）を下限 1.0 dB へ。m07・m08 は保つ" },
    { "on": "claim:c2", "do": "m01 の position を -0.35、width を 1.2 へ" },
    { "on": "S-03|S-04", "do": "m01・m02 の width を 1.0 へ。まだ不通なら m03／m04 を内側の端（0.6／-0.6）へ" }
  ],
  "recall_on": [
    "4 本を上限まで上げても obs:o1 が +1.5 dB に届かない（幅を作るのはレベルではなく空間の手だった、に読みが変わる）",
    "和声が上がって verse の声の言葉が聞き取りにくくなった（声 > 配置）",
    "床との同一収束"
  ],
  "rejected": [
    { "candidate": "声を下げて主役対伴奏を参照（-3.12 LU。p3 は -0.21 LU）へ寄せる", "reason": "値を写さない。声のレベルは p1 が試した問いで、P-10 は check で測り直されない。4 本を上げる結果として少し縮むだけに留める", "card": null },
    { "candidate": "全役割を中央に戻す（参照は L/R 差 ±0.6 dB 以内）", "reason": "中央定位が意図か書き出しの既定かは不明。依頼元の p3 は配置の多様性", "card": null },
    { "candidate": "幅を参照のマスター（全帯域 S/M -17.28 dB。p3 は -13.33 dB）へ狭める", "reason": "参照の値は目標ではない。距離は参考値として出すだけ", "card": null },
    { "candidate": "backing_vocals（p3 は 2.1 LU 小さい）・bass（1.1 LU 小さい）も上げる", "reason": "BV は lowmid のモノ損失 1.46 dB（曲資料 §4.1）、bass は帯域担当で譲る側（曲資料 §5.3 arr1／arr2）。問いを 1 つに絞る", "card": null },
    { "candidate": "和とマスターの差分（幅 -1.81 dB、クレスト -1.47 dB）からバスの絞りを足す", "reason": "差分は信頼できない（残差 -3.99 dB、相関 0.7587）。確度上限 low で手の根拠にしない", "card": null },
    { "candidate": "4 本を中央のまま上げる（参照の釣り合いをそのまま）", "reason": "P-02 全体 7.085 が範囲 [0, 3] の外。この曲の測定 > リファレンスの測定。側へ逃がしてから上げる", "card": null },
    { "candidate": "p3 の遠い部屋・L/R エコー・Haas・帯域別ワイドナーも入れる", "reason": "問い（振った楽器の大きさ）と混ざる。p3 でガード不成立（低域の側成分）が出た手を含む", "card": null }
  ],
  "listen_for": [
    { "t_s": 3.1, "what": "verse1: keyboard 左・synth 右が上がって声の言葉を邪魔しないか" },
    { "t_s": 36.3, "what": "hook1: guitar 右が聞こえる大きさか、重量バランスが右へ傾かないか" },
    { "t_s": 84.3, "what": "outro: woodwinds 左・guitar 右が配置として読めるか。lowmid が濁らないか。モノでも聴いて 2 本が消えないか" }
  ],
  "tool_requests": ["トラック寄与の観察量（target: trk_*）", "適用後のミックス段の台帳指標（P-10、P-02 系）の測り直し", "既存の指揮結果（p3）の上に差分の指揮だけを重ねる適用"],
  "human_questions": [
    { "q": "和声の 4 本が今より聞こえてよいか", "assumed": "よい（声の言葉を邪魔しない範囲で）" },
    { "q": "p3 の空間（エコー・遠い部屋）も込みで比べたいか", "assumed": "今回は配置とレベルだけ。込みなら p3 の結果に重ねる指揮を別に立てる" }
  ]
}
```
