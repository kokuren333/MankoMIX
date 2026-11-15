---
id: dir_925f853a58bc
kind: direction
title: マンコ主義 × 低域の整理と小さな再生 全体指揮書
song: manko-shugi
request: "全体をもう少しすっきりさせたい。低いところでキックとベースが重なって聞こえるのと、スマホのような小さな再生で低音の輪郭が消えないかが気になる。リファレンスは無し"
pattern: p7
analysis: ana_cb0912af47b4
created: 2026-11-15
status: active
visibility: public
---

# 全体指揮書 p7 — マンコ主義 × 「すっきり、キックとベースの重なり、小さな再生の低音」

## 1. 狙い
キックの打点の間だけベースが浅く引き、ベースは基音を少し譲って倍音で輪郭を持つ。フレーズの間の無音同然の区間は消す。a1「キックとベースが重なって聞こえる」（時間で分ける、確信度 medium）、a2「小さな再生で低音の輪郭」（低音の重なりを減らし、ベースに倍音を足す、確信度 medium）、a3「全体をもう少しすっきり」（小さな量。曲でない部分の掃除、確信度 medium）。根拠: キックとベースは同じ 50–150 Hz にほぼ同じ量で居て、帯域で分ける隙間が無い〔測定・追加＋推定〕。40–150 Hz は全体のエネルギーの約半分で、モノ＋150–6000 Hz の見方では -2.78 LU 落ちる〔測定・追加〕。リファレンスは無し。

## 2. 全体方針
触るのは bass と、編集の 3 本（bass・backing_vocals・woodwinds）だけ。編集 → 静的バランス → 時間の処理 → 倍音の順に小さく重ねる（R-04）。**触らない所**: drums（キックを含む）、声、パン・幅、残響、マスター。素材はオーナー自身の曲（生成サービスの書き出し）で、この案件が示せるのは機構であって効き目ではない。

## 3. 手
6 手。ブロック参照。
- m01〜m03 `edit_gate`（bass、backing_vocals、woodwinds。既定値）: 走査では候補 3／8／9 区間、拒否 0、区間内の最大フレームは全て -81 dBFS 以下、除くエネルギーはトラック比 -75.5／-66.7／-69.6 dB。聞こえる差は出ない見込み。safeguard（EG-1〜5）は機械が掛ける。
- m04 `gain`（bass -0.5〜-1.0 dB）: 床の提案「譲る trk_bass」（arr1・arr2）を小さく採る〔理論: KT-0012〕。
- m05 `duck`（対象 bass、キー drums の 40–120 Hz、深さ 1.5〜3.0 dB、回復 1/8 音符）〔理論: KT-0026〕。回復は音価（R-11）。回復率は適用記録の `recovery` で確かめる。
- m06 `saturator`（bass、非対称、並列）: 倍音で輪郭を補う〔理論: KT-0005、KT-0024〕。マスターの観察量にはほぼ現れない見込みで、耳で確かめる手。

## 4. 変種別の差分
`streaming_universal`（既定）1 本。

## 5. 到達の主張
床とレベルマッチ後に比較。量は小さい。主たる主張: c1 sec9（ベースが最大の区間）の 40–150 Hz の比が -0.15 dB 以上下がる（床 -2.65）。副: c2 全曲の同じ比 -0.1 dB 以上（床 -2.96）、c3 `view: mono_band` の積分ラウドネスが +0.05 LU 以上（床 -16.79。見込み 0.1 LU 前後で、機構の確認に近い）、c4 sec9 の 150–400 Hz 対 40–150 Hz の比 +0.25 dB 以上（床 -6.16。主に分母が下がる分）。ガード: c5 `view: mono` のラウドネスが 0.1 LU より下がらない（床 -14.11）、c6 40–150 Hz のエネルギーが 0.8 dB より下がらない（土台の下限。床 -59.65）、c7 250–800 Hz の比が 0.5 dB より上がらない（こもりの天井）。`--calibrate` を勧める（必須ではない）。

## 6. 委任範囲と事前承認の分岐
許す: 範囲内の量の選択（`--calibrate` 可）、m05 の回復を 1/16 に替える、m06 を外す。禁止: drums・声に触る、m05 を 3 dB より深くする、編集の閾値を緩めて区間を増やす、主張の引き下げ。分岐: c1 未達 → m05 を 3.0 dB、m04 を -1.0 dB → それでも届かなければ未達で出す。m05 の回復率が 0.8 未満 → 回復を 1/16 に。c6 不成立 → m04 を外す。c7 不成立または S-08 → m06 を下限 → 外す。編集の適用結果が走査（3／8／9 区間、拒否 0）と違う → そのまま進めて報告（閾値は動かさない）。

## 7. 再召喚してほしい条件
- ベースが波打って聞こえる（ポンピング）。深さでなく回復の音価かキーの帯域の読みが違う。
- 編集した区間の頭・尻で音が欠ける、残響が切れて聞こえる（`direction edit revert` で戻してから）。
- c1 は達成したのに耳では重なったまま（問題は量でなく音色・音程の側）。
- 床との同一収束。

## 8. 採らなかった案と理由
- `edit_trim`: 末尾の候補は全トラック 0。先頭は `edit_gate` の最初の区間と同じ範囲。
- 他のトラックの `edit_gate`: 声は主役（E3）で候補 1.07 s だけ。brass・strings は素材全体がほぼ無音で、残る側が曲かを測定から言えない。ほかは候補が短く除く量が -73 dB 以下。
- 帯域別の側成分倍率（`stereo`）: 低域は既に中央（`mono` で -0.10 LU、S-04 低域モノ損失 0.020 dB）。
- キックとベースを EQ で住み分ける: 両方が 50–150 Hz に広く居て隙間が無い。キックはドラムのステムの中で、EQ はスネアにも掛かる。
- 伴奏へのハイパスの追加: 床が R-07 で決めた値で、トラック別のスペクトルが見えない。
- 深いダッキング（4〜6 dB）: 「もう少し」に合わない。
- 輪郭つきの一時 refstudy を目標にする: 参照作品の測定で、依頼はリファレンス無し。

## 9. 人の耳で確かめる点
5.5 s（verse1: キックの打点が見えるか、ベースが波打たないか）、33.1 s（break: bass・backing_vocals・woodwinds の無音化の切り口）、61.75 s（最大区間: 低音が痩せていないか）、86.0 s（ベースが最大の区間: 小さなスピーカーでベースの音程が追えるか、歪みが粗くないか）、95.7 s（終わり: 残響の尾が切れていないか）。

## 10. 道具の要望
キー入力つきの帯域限定ダッキング（ベースの 50–150 Hz だけを下げる）、キック単独のキー（ドラムの分離）、トラック寄与の観察量（`view` つき）、適用後の P-02:temporal・P-22 の測り直し、`duck` の区間限定。

```json direction
{
  "schema_version": 1,
  "kind": "direction",
  "song": "manko-shugi",
  "request": { "pattern": "p7", "utterance": "全体をもう少しすっきりさせたい。低いところでキックとベースが重なって聞こえるのと、スマホのような小さな再生で低音の輪郭が消えないかが気になる。リファレンスは無し" },
  "sources": {
    "analysis": "ana_cb0912af47b4",
    "dossier_sha256": "326a6bf18aed578447f9c049025d2b3ac61dd31aedfb840da324a4ff4a5af9d5",
    "cards": ["KT-0005", "KT-0012", "KT-0024", "KT-0026", "cur_low-end-basics"]
  },
  "aims": [
    { "id": "a1", "phrase": "低いところでキックとベースが重なって聞こえる", "text": "キックの打点の間だけベースが浅く引き、静的にも少し譲る。キックには触らない", "confidence": "medium", "assumption": "両者は同じ 50–150 Hz にほぼ同じ量で居て、帯域では分けられない（区間別の追加観察からの推定）" },
    { "id": "a2", "phrase": "スマホのような小さな再生で低音の輪郭が消えないか", "text": "重なった低音の量を減らして小さな再生での落差を縮め、ベースに倍音を足して 150 Hz より上に輪郭を置く", "confidence": "medium", "assumption": "ベースは基音型（P-07 比 0.98）。倍音の効きはマスターの観察量では測れず、耳で確かめる" },
    { "id": "a3", "phrase": "全体をもう少しすっきり", "text": "小さな量で。フレーズの間の無音同然の区間を消す。伴奏の音色・残響・声は床のまま", "confidence": "medium", "assumption": "「すっきり」は低域の整理と無音区間の掃除まで。編集で聞こえる差は出ない見込み" }
  ],
  "variants": [
    { "id": "var_p7", "profile": "streaming_universal", "delivery": ["hires_native", "distributor_44k16"], "target_lufs": null, "reason": "既定" }
  ],
  "template_use": { "floor": "comfort:0.5", "keep_floor_mix": true, "notes": "床を出発点に、編集 3 手と bass への 3 手を重ねる。型は 1 → 2a → 3（リファレンス無し）" },
  "moves": [
    { "id": "m01", "aim": "a3", "stage": "edit", "target": "trk_bass", "section": null, "op": "edit_gate", "processor": null, "params": { "threshold_db": -60, "hold_ms": 400, "min_gap_ms": 1000 }, "replaces": null,
      "expect": [],
      "safeguard": [ { "quantity": "obs:o8", "direction": "not_worse", "tolerance": 0.5, "unit": "LU" } ],
      "basis": "edit scan（候補 3 区間 4.80 s、拒否 0、区間内最大 -81.0 dBFS 以下、除くエネルギー -75.47 dB）/ 曲資料 §3（sec1・sec3・sec6 で bass は不在）、§9（無音の区間がコンプのメイクアップ +2 dB を通る）", "origin": "new" },
    { "id": "m02", "aim": "a3", "stage": "edit", "target": "trk_backing_vocals", "section": null, "op": "edit_gate", "processor": null, "params": { "threshold_db": -60, "hold_ms": 400, "min_gap_ms": 1000 }, "replaces": null,
      "expect": [],
      "safeguard": [ { "quantity": "obs:o8", "direction": "not_worse", "tolerance": 0.5, "unit": "LU" } ],
      "basis": "edit scan（候補 8 区間 51.57 s、拒否 0、区間内最大 -82.0 dBFS 以下、除くエネルギー -66.71 dB）/ 曲資料 §2（在・不在）、§9（リバーブへ -15 dB で送られている）", "origin": "new" },
    { "id": "m03", "aim": "a3", "stage": "edit", "target": "trk_woodwinds", "section": null, "op": "edit_gate", "processor": null, "params": { "threshold_db": -60, "hold_ms": 400, "min_gap_ms": 1000 }, "replaces": null,
      "expect": [],
      "safeguard": [ { "quantity": "obs:o8", "direction": "not_worse", "tolerance": 0.5, "unit": "LU" } ],
      "basis": "edit scan（候補 9 区間 71.39 s、拒否 0、区間内最大 -88.1 dBFS 以下、除くエネルギー -69.59 dB）/ 曲資料 §2（在・不在）、§9（リバーブへ -15 dB で送られている）", "origin": "new" },
    { "id": "m04", "aim": "a1", "stage": "mix", "target": "trk_bass", "section": null, "op": "gain", "processor": null, "params": { "delta_db": [-1.0, -0.5] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "down", "min_delta": 0.15, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o5", "direction": "not_worse", "tolerance": 0.8, "worse": "down", "unit": "dB" } ],
      "basis": "R-04（静的バランスが先）R-28（重要度の低い側が譲る。bass 0.70 < drums 0.80）/ 曲資料 §5.3 arr1・arr2（譲る trk_bass）、§11.1 未解決 band_density / KT-0012 / 逆側の弁 R-29（vocabulary sukasuka）", "origin": "new" },
    { "id": "m05", "aim": "a1", "stage": "mix", "target": "trk_bass", "section": null, "op": "duck", "processor": null, "params": { "key": "trk_drums", "depth_db": [1.5, 3.0], "key_lo_hz": 40, "key_hi_hz": 120, "release_note": "1/8" }, "select": { "depth_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "down", "min_delta": 0.15, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o5", "direction": "not_worse", "tolerance": 0.8, "worse": "down", "unit": "dB" } ],
      "basis": "追加観察（sec10 のキックは 50–150 Hz に広く、sec9 の残りと同じ帯・同程度の量。帯域で分ける隙間が無い）/ KT-0026（片方を相手に合わせて下げる）/ R-11（回復は音価。mix_rules ducking.release_note_default 1/8、91.2 BPM で約 329 ms）/ genre_priors hiphop（低域の主役 kick、P-02:temporal 重視）/ 深さは mix_rules ducking.depth_db 3.0 を上限に浅く", "origin": "new" },
    { "id": "m06", "aim": "a2", "stage": "mix", "target": "trk_bass", "section": null, "op": "chain_add", "processor": "saturator", "params": { "mode": "asymmetric", "drive_db": [9.0, 15.0], "asymmetry": 0.3, "mix": [0.3, 0.5], "oversample": 2 }, "select": { "drive_db": "mid", "mix": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o6", "direction": "up", "min_delta": 0.25, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o7", "direction": "not_worse", "tolerance": 0.5, "worse": "up", "unit": "dB" }, { "quantity": "obs:o4", "direction": "not_worse", "tolerance": 0.1, "worse": "down", "unit": "LU" } ],
      "basis": "曲資料 §4.1（bass の P-07 比 0.98／lowmid 0.03）/ 追加観察（sec9 の 150–400 Hz 対 40–150 Hz は -6.16 dB）/ KT-0024・KT-0005、vocabulary futoi（倍音で聞こえを補う）/ mix_rules saturation.bass_enhance（非対称 9 dB・0.35。その発動条件は満たさないので catalog としない）/ R-29（倍音が増える帯の天井を対に置く）/ マスターの観察量では効きをほぼ測れない手（listen_for 86.0 s）", "origin": "new" }
  ],
  "claims": [
    { "id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "down", "min_delta": 0.15, "unit": "dB", "primary": true },
    { "id": "c2", "quantity": "obs:o2", "vs": "floor", "direction": "down", "min_delta": 0.1, "unit": "dB", "primary": false },
    { "id": "c3", "quantity": "obs:o3", "vs": "floor", "direction": "up", "min_delta": 0.05, "unit": "LU", "primary": false },
    { "id": "c4", "quantity": "obs:o6", "vs": "floor", "direction": "up", "min_delta": 0.25, "unit": "dB", "primary": false },
    { "id": "c5", "quantity": "obs:o4", "vs": "floor", "direction": "not_worse", "tolerance": 0.1, "worse": "down", "unit": "LU", "primary": false },
    { "id": "c6", "quantity": "obs:o5", "vs": "floor", "direction": "not_worse", "tolerance": 0.8, "worse": "down", "unit": "dB", "primary": false },
    { "id": "c7", "quantity": "obs:o7", "vs": "floor", "direction": "not_worse", "tolerance": 0.5, "worse": "up", "unit": "dB", "primary": false }
  ],
  "observations": [
    { "id": "o1", "primitive": "band_ratio", "target": "master", "band_hz": [40, 150], "ref_band_hz": [20, 20000], "section": "sec9", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o2", "primitive": "band_ratio", "target": "master", "band_hz": [40, 150], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o3", "primitive": "loudness", "target": "master", "section": "all", "stat": "integrated", "view": "mono_band", "level_match": true, "unit": "LUFS" },
    { "id": "o4", "primitive": "loudness", "target": "master", "section": "all", "stat": "integrated", "view": "mono", "level_match": true, "unit": "LUFS" },
    { "id": "o5", "primitive": "band_energy", "target": "master", "band_hz": [40, 150], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o6", "primitive": "band_ratio", "target": "master", "band_hz": [150, 400], "ref_band_hz": [40, 150], "section": "sec9", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o7", "primitive": "band_ratio", "target": "master", "band_hz": [250, 800], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o8", "primitive": "loudness", "target": "master", "section": "sec3", "stat": "integrated", "level_match": true, "unit": "LUFS" }
  ],
  "delegation": {
    "allowed": ["範囲内の量の選択（--calibrate 可）", "m05 の release_note を 1/16 に替える", "m06 を外す"],
    "forbidden": ["狙いの変更・追加", "trk_drums・trk_vocals に手を足す", "m05 の depth_db を 3 dB より深くする", "編集 op の threshold_db を上げて区間を増やす", "編集 op を他のトラックへ広げる", "主張の削除・最小量の引き下げ"]
  },
  "branches": [
    { "on": "claim:c1", "do": "m05 の depth_db を 3.0、m04 の delta_db を -1.0 へ。それでも届かなければ未達で出す" },
    { "on": "safeguard:m05", "do": "適用記録の recovery.recovered_ratio が 0.8 未満なら release_note を 1/16 に替える。c6 不成立なら m04 を外す" },
    { "on": "claim:c7", "do": "m06 を下限（drive_db 9、mix 0.3）へ。まだ不成立なら m06 を外す" },
    { "on": "S-08", "do": "m06 を外す → それでも不通なら RB-3" },
    { "on": "safeguard:m01", "do": "編集の適用結果が走査（3／8／9 区間、拒否 0）と違っても、そのまま進めて台帳の件数を報告する。閾値は動かさない。o8 が不成立なら direction edit revert で編集を戻して再召喚" }
  ],
  "recall_on": [
    "ベースが波打って聞こえる（ポンピング）。回復の音価かキーの帯域の読みが違う",
    "編集した区間の頭・尻で音が欠ける、残響が切れて聞こえる",
    "c1 は達成したのに耳では重なったまま（問題は量でなく音色・音程の側）",
    "床との同一収束"
  ],
  "rejected": [
    { "candidate": "edit_trim（末尾・先頭）", "reason": "末尾の候補は全トラック 0（曲末まで音が残る）。先頭は edit_gate の最初の区間と同じ範囲（bass 0–1.21 s）で重複する", "card": null },
    { "candidate": "edit_gate を他のトラックへ（vocals、brass、strings、guitar、keyboard、percussion、synth）", "reason": "声は主役（E3）で候補 1.07 s だけ。brass・strings は素材全体がほぼ無音で、残る側が曲かを測定から言えない。ほかは候補が短く除く量が -73 dB 以下。drums・fx は候補なし", "card": null },
    { "candidate": "帯域別の側成分倍率（stereo の mono_below_hz・widths）", "reason": "低域は既に中央（view: mono で -0.10 LU、S-04 低域モノ損失 0.020 dB、bass 相関 0.984、drums 0.999）", "card": null },
    { "candidate": "キックとベースを EQ で住み分ける", "reason": "両方が 50–150 Hz に広く居て隙間が無い。キックはドラムのステムの中で、EQ はスネアにも掛かる", "card": "KT-0012" },
    { "candidate": "伴奏（keyboard、guitar、synth）へのハイパスの追加・引き上げ", "reason": "床が R-07 で決めた値。トラック別のスペクトルが見えず、根拠が一般論だけになる", "card": null },
    { "candidate": "深いダッキング（4〜6 dB）", "reason": "「もう少し」に合わない。ポンピングが効果として聞こえる量", "card": null },
    { "candidate": "輪郭つきの一時 refstudy の値を目標にする", "reason": "参照作品の測定で床の測定ではない。依頼はリファレンス無し", "card": null }
  ],
  "listen_for": [
    { "t_s": 5.5, "what": "verse1: キックの打点が見えるか。ベースが波打たないか" },
    { "t_s": 33.1, "what": "break: bass・backing_vocals・woodwinds の無音化の切り口で音が欠けないか" },
    { "t_s": 61.75, "what": "最大区間: 低音が痩せていないか" },
    { "t_s": 86.0, "what": "ベースが最大の区間: 小さなスピーカーでベースの音程が追えるか。歪みが粗くないか" },
    { "t_s": 95.7, "what": "終わり: 残響の尾が切れていないか" }
  ],
  "tool_requests": ["キー入力つきの帯域限定ダッキング（対象の 50–150 Hz だけを下げる）", "キック単独のキー（ドラムのステムの分離）", "トラック寄与の観察量（target: trk_bass、view つき）", "適用後の P-02:temporal・P-22 の測り直し", "duck の区間限定"],
  "human_questions": [
    { "q": "「すっきり」は低域の整理の意味か、楽器の数・残響まで含むか", "assumed": "低域の整理と無音区間の掃除まで" },
    { "q": "brass・strings はほぼ無音の素材。曲の一部として残すか", "assumed": "残す（触らない）" }
  ]
}
```
