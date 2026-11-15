---
id: dir_89dc56c90b97
kind: direction
title: マンコ主義 × ボーカルの言葉を前に 全体指揮書
song: manko-shugi
request: "ボーカルの言葉をもう少し前に出したい。リファレンスは無し"
pattern: p6
analysis: ana_32695533131c
created: 2026-11-15
status: active
visibility: public
---

# 全体指揮書 p6 — マンコ主義 × 「ボーカルの言葉を前に」

## 1. 狙い
声の音量は上げずに、言葉（子音）の明瞭さと近さを少し足す。「言葉を前に」→ a1（2–6 kHz の子音の帯と立ち上がり、乾き）、確信度 medium。「もう少し」→ a2（小さな量。声のフェーダーと伴奏は動かさない）。根拠: 声は既に P-10 5.77 で目標 [2, 5] の外に浮いていて、対主役マスキングも 0.684 dB と良好〔測定 §4.3〕。前に出ない理由は音量ではなく、暗い素材（highmid 比 0.07〔測定 §4.1〕）と、子音を先に抑えるアタック 2 ms のピークコンプ〔推定〕。リファレンスは無し。型は曲資料から直接立案に縮めた。

## 2. 全体方針
手は声だけに 3 つ。(a) ピークコンプのアタックを 2 → 4〜8 ms（子音の立ち上がりを通す）、(b) 2.8 kHz 中心・幅 1.4 oct の +1.0〜+2.5 dB（R-06 の ±3 dB 内。床の 3.5 kHz の狭い共鳴カットは残す）、(c) プレートへのセンドを -18 → -22〜-20 dB（乾いたものは手前。`mae_oku`）。**触らない所**: 声のフェーダー、ディエッサー、サチュレーター、伴奏の全部、パン、マスター。

## 3. 手
3 手、すべて mix 段、静的（主役への時間で変わる処理は無い）。ブロック参照。

## 4. 変種別の差分
`streaming_universal`（既定）1 本。

## 5. 到達の主張
床とレベルマッチ後に比較。主たる主張: c1 verse1（sec2）の highmid 比（2–6 kHz／全帯域）が +0.5 dB 以上（床 -17.15）。副: c2 全曲の highmid 比 +0.3 dB 以上（床 -14.47）、c3 verse1 の 2–6 kHz のクレスト +0.3 dB 以上（アタックの効き。見込みは不確か）、c4 verse1 の mid 比（500–2000 Hz）が ±0.5 dB 内（音量で前に出したのではないことの機械表現。床 -11.30）、c5 サ行の帯（6–10 kHz）の比の増加が 0.6 dB 以内（床 -22.83）、c6 P-10 不変（±0.3。check では未測定になる見込み）。

## 6. 委任範囲と事前承認の分岐
許す: 範囲内の量の選択（`--calibrate` 可）、m02 の中心を 2.4〜3.2 kHz で動かす、m03 を外す。禁止: 声のフェーダーを上げる、伴奏を下げて相対的に出す、ディエッサーを緩める、高域シェルフ、主張の引き下げ。分岐: c1 未達 → m02 を上限 +2.5 dB、m01 を 8 ms → それでも届かなければ未達で出す（R-06 を超えない）。c5 悪化 → `mx.trk_vocals.deess` の range_db を 6 → 8、まだなら m01 を下限 4 ms。S-08 → m02 を下限 +1.0 dB → まだなら m01 を外す → RB-3。

## 7. 再召喚してほしい条件
- 言葉は立ったが声が刺さる・きつい（2.5–5 kHz の `kinkin`）。量ではなく帯域の読みが違う。
- c1 は達成したのに耳では前に出ない（言葉の問題は帯域ではなく、発音・残響・伴奏の側にある）。
- 床との同一収束。

## 8. 採らなかった案と理由
- 声のフェーダーを上げる: P-10 5.77 は既に目標の外（床保証のガード項）。依頼は「言葉」。
- drums・percussion の 2–5 kHz を下げる（R-05 の順序）: この帯の競合は snare・hat だけで、対主役マスキングは 0.684 dB と良好。リズムの打点を鈍らせる引き換えに見合わない。
- 床の 3517 Hz 共鳴カット（-3 dB）を外す: 共鳴は狭く、言葉の帯全体の薄さとは別の問題。
- 高域シェルフ（エア）: サ行とシマー（S-08）に寄り、言葉の芯（2–4 kHz）に効かない。
- 声の区間ゲイン（語尾や小さい語を上げる）: 主役への時間変化処理（E3）。小さな依頼に対して重い。
- サチュレーターの増量: 倍音は足せるが粗さと引き換えで、測る指標が無い。

## 9. 人の耳で確かめる点
5.5 s（verse1: 子音が立って言葉が近く聞こえるか。きつくないか）、32.5 s（break: 伴奏が薄い所でサ行が刺さらないか、乾きすぎないか）、61.75 s（最大区間: 伴奏の中で言葉が読めるか）、71.5 s（verse2: 5.5 s と同じ確認を別の歌詞で）。

## 10. 道具の要望
チェーン内の挿入位置の指定（EQ をコンプの前に置きたい）、声のトラック寄与の観察量（`trk_vocals` の 2–6 kHz）、適用後の P-10・P-02 対主役の測り直し。

```json direction
{
  "schema_version": 1,
  "kind": "direction",
  "song": "manko-shugi",
  "request": { "pattern": "p6", "utterance": "ボーカルの言葉をもう少し前に出したい。リファレンスは無し" },
  "sources": {
    "analysis": "ana_32695533131c",
    "dossier_sha256": "44cb34cff7d9073d87dfc5f7ec019f45580f525e3b4d89ac1268a27a04af3461",
    "cards": []
  },
  "aims": [
    { "id": "a1", "phrase": "ボーカルの言葉を前に", "text": "声の音量は上げず、子音の帯（2–6 kHz）と立ち上がり、乾きで言葉を近づける", "confidence": "medium", "assumption": "「前に」は聞き取りの意味。声は既に目標より大きい（P-10 5.77）ので音量の問題ではない" },
    { "id": "a2", "phrase": "もう少し", "text": "小さな量で、声のチェーンの 3 か所だけ。フェーダー・伴奏・マスターは床のまま", "confidence": "high", "assumption": "EQ は R-06 の ±3 dB 内" }
  ],
  "variants": [
    { "id": "var_p6", "profile": "streaming_universal", "delivery": ["hires_native", "distributor_44k16"], "target_lufs": null, "reason": "既定" }
  ],
  "template_use": { "floor": "comfort:0.5", "keep_floor_mix": true, "notes": "床を出発点に、声のチェーンの 3 手だけを重ねる。型は曲資料から直接立案に縮めた（リファレンス無し、kb カード不使用）" },
  "moves": [
    { "id": "m01", "aim": "a1", "stage": "mix", "target": "trk_vocals", "section": null, "op": "chain_param", "processor": null, "params": { "attack_ms": [4.0, 8.0] }, "select": { "attack_ms": "mid" }, "replaces": "mx.trk_vocals.comp_peak",
      "expect": [ { "quantity": "obs:o3", "direction": "up", "min_delta": 0.3, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o5", "direction": "not_worse", "tolerance": 0.6, "worse": "up", "unit": "dB" } ],
      "basis": "vocabulary mae_oku（前後感はトランジェントでも決まる）/ 曲資料 §9（comp_peak attack 2 ms、4:1）/ mix_rules compressor.lead_peak attack 2.0 からの変更（理由: 依頼が子音を主語にする）", "origin": "new" },
    { "id": "m02", "aim": "a1", "stage": "mix", "target": "trk_vocals", "section": null, "op": "chain_add", "processor": "eq", "params": { "shape": "peak", "freq_hz": 2800, "gain_db": [1.0, 2.5], "bw_oct": 1.4, "phase": "minimum" }, "select": { "gain_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.4, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o5", "direction": "not_worse", "tolerance": 0.6, "worse": "up", "unit": "dB" }, { "quantity": "obs:o4", "direction": "not_worse", "tolerance": 0.5, "unit": "dB" } ],
      "basis": "vocabulary nukenai（1–4 kHz）/ R-06（±3 dB 内）R-12 / 曲資料 §4.1（声の highmid 比 0.07）、§9（3517 Hz の共鳴カットは残す。累積は mix_rules eq.max_cumulative_db 4.5 内）/ 追加観察（sec2 の highmid 比 -17.15 dB）", "origin": "new" },
    { "id": "m03", "aim": "a1", "stage": "mix", "target": "trk_vocals", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_reverb", "level_db": [-22.0, -20.0], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "not_worse", "tolerance": 0.3, "worse": "down", "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o4", "direction": "not_worse", "tolerance": 0.5, "unit": "dB" } ],
      "basis": "vocabulary mae_oku（残響の多いものは奥。前に出したいものにリバーブを足すのは逆）/ 曲資料 §9（床のセンド -18 dB）/ genre_priors hiphop short, dry-leaning reverb / マスターの観察量では効きを測れない手（listen_for 32.5 s で確かめる）", "origin": "new" }
  ],
  "claims": [
    { "id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 0.5, "unit": "dB", "primary": true },
    { "id": "c2", "quantity": "obs:o2", "vs": "floor", "direction": "up", "min_delta": 0.3, "unit": "dB", "primary": false },
    { "id": "c3", "quantity": "obs:o3", "vs": "floor", "direction": "up", "min_delta": 0.3, "unit": "dB", "primary": false },
    { "id": "c4", "quantity": "obs:o4", "vs": "floor", "direction": "not_worse", "tolerance": 0.5, "unit": "dB", "primary": false },
    { "id": "c5", "quantity": "obs:o5", "vs": "floor", "direction": "not_worse", "tolerance": 0.6, "worse": "up", "unit": "dB", "primary": false },
    { "id": "c6", "quantity": "P-10", "vs": "floor", "direction": "not_worse", "tolerance": 0.3, "unit": "dB", "primary": false }
  ],
  "observations": [
    { "id": "o1", "primitive": "band_ratio", "target": "master", "band_hz": [2000, 6000], "ref_band_hz": [20, 20000], "section": "sec2", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o2", "primitive": "band_ratio", "target": "master", "band_hz": [2000, 6000], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o3", "primitive": "crest", "target": "master", "band_hz": [2000, 6000], "section": "sec2", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o4", "primitive": "band_ratio", "target": "master", "band_hz": [500, 2000], "ref_band_hz": [20, 20000], "section": "sec2", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o5", "primitive": "band_ratio", "target": "master", "band_hz": [6000, 10000], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" }
  ],
  "delegation": {
    "allowed": ["範囲内の量の選択（--calibrate 可）", "m02 の中心周波数を 2400–3200 Hz で動かす", "m03 を外す"],
    "forbidden": ["狙いの変更・追加", "声のフェーダーを上げる", "伴奏を下げて相対的に声を出す", "ディエッサーを緩める・外す", "高域シェルフの追加", "m02 を +3 dB より上げる", "主張の削除・最小量の引き下げ"]
  },
  "branches": [
    { "on": "claim:c1", "do": "m02 を上限 +2.5 dB、m01 を 8 ms へ。それでも届かなければ未達で出す（R-06 を超えない）" },
    { "on": "claim:c5", "do": "chain_param mx.trk_vocals.deess の range_db を 6 → 8。まだ悪化なら m01 を下限 4 ms" },
    { "on": "S-08", "do": "m02 を下限 +1.0 dB → まだ不通なら m01 を外す → それでも不通なら RB-3" }
  ],
  "recall_on": [
    "言葉は立ったが声が刺さる・きつい（2.5–5 kHz）。量ではなく帯域の読みが違う",
    "c1 は達成したのに耳では前に出ない（問題は帯域ではなく発音・残響・伴奏の側）",
    "床との同一収束"
  ],
  "rejected": [
    { "candidate": "声のフェーダーを上げる", "reason": "P-10 5.77 は既に目標 [2, 5] の外（床保証のガード項）。依頼は音量でなく言葉", "card": null },
    { "candidate": "drums・percussion の 2–5 kHz を下げる（R-05: 競合を先に下げる）", "reason": "この帯の競合は snare・hat だけで、対主役マスキングは 0.684 dB と良好。打点を鈍らせる引き換えに見合わない", "card": null },
    { "candidate": "床の 3517 Hz 共鳴カット（-3 dB、0.33 oct）を外す", "reason": "狭い共鳴の対処で、言葉の帯全体の薄さとは別の問題", "card": null },
    { "candidate": "高域シェルフ（6 kHz 以上）", "reason": "サ行とシマー（S-08）に寄り、言葉の芯（2–4 kHz）に効かない", "card": null },
    { "candidate": "声の区間ゲイン（小さい語・語尾を上げる）", "reason": "主役への時間変化処理（E3）。小さな依頼に対して重い", "card": null },
    { "candidate": "サチュレーターの増量", "reason": "粗さと引き換えで、量を測る指標が無い", "card": null }
  ],
  "listen_for": [
    { "t_s": 5.5, "what": "verse1: 子音が立って言葉が近く聞こえるか。きつくないか" },
    { "t_s": 32.5, "what": "break: 伴奏が薄い所でサ行が刺さらないか、声が乾きすぎないか" },
    { "t_s": 61.75, "what": "最大区間: 伴奏の中で言葉が読めるか" },
    { "t_s": 71.5, "what": "verse2: 5.5 s と同じ確認" }
  ],
  "tool_requests": ["チェーン内の挿入位置の指定（EQ をコンプの前に置く）", "声のトラック寄与の観察量（target: trk_vocals）", "適用後の P-10・P-02 対主役の測り直し"],
  "human_questions": [
    { "q": "「前に」は音量の意味か、言葉の聞き取りの意味か", "assumed": "聞き取り（声は既に目標より大きい）" }
  ]
}
```
