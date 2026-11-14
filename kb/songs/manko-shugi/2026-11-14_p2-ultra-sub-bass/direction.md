---
id: dir_2a6c9969107a
kind: direction
title: マンコ主義 × 超重低音強化しつつも聞ける 全体指揮書
song: manko-shugi
request: "超重低音強化しつつも聞ける"
pattern: p2
analysis: ana_0e97838efceb
created: 2026-11-14
status: active
visibility: public
---

# 全体指揮書 p2 — マンコ主義 × 「超重低音強化しつつも聞ける」

## 1. 狙い
20–80 Hz を床より明確に増やしつつ、声の明瞭さと小口径・モノ再生での低音の存在を守る。「超重低音強化」→ a1（kick の sub と bass の最低オクターブを持ち上げる。808 はない〔測定 §5.2〕）、確信度 high。「聞ける」→ a2（対主役マスキングを悪化させない、bass に倍音を付ける、周辺の 60–120 Hz を整理する）、確信度 medium。仮定: 聴くのは配信（スマホ・イヤホン）。

## 2. 全体方針
差はミックス段の低域だけで作る。(a) drums に 55 Hz の低シェルフ +2.5〜+4.5 dB（sub は drums 単独所有〔測定 §5.2〕。R-06 の ±3 dB を依頼が sub を主語にする理由で超える。f.1）、(b) bass に 65 Hz の低シェルフ +3〜+5 dB（最低 f0 ≈ 39 Hz〔推定〕）、(c) bass に非対称サチュレーター（倍音。「808 needs harmonics」〔知見: genre_priors hiphop〕、小口径で聴こえる低音〔知見: 07b §20〕）、(d) 競合側を先に下げる（R-05）: vocals の HPF 84 → 115 Hz、guitar の HPF 41 → 105 Hz、keyboard に HPF 90 Hz（R-08 非所有者が譲る）。**触らない所**: マスター（計画器に任せる。目標の引き下げは委任）、リバーブ、パン、vocals のレベルと他の 6 段、synth・woodwinds・percussion。壁: -14 LUFS／-1 dBTP では sub は LUFS にほとんど寄与せずピークに寄与する〔推定〕→ kick のピークがリミッターに当たる。対策は分岐（KM-0001、目標引き下げ）。届かなければ「-14 LUFS の出口で sub +2.5 dB は出せない」と未達で出す。

## 3. 手
6 手、すべて mix 段、静的。ブロック参照。m01 だけ `select: max`（「超」の主張。安全弁と分岐で削る）。

## 4. 変種別の差分
`streaming_universal`（既定）1 本。「聞ける」は日常の配信再生を指すと読む。club は再生系も作品も別物になるので選ばない（求められたら別依頼）。目標 LUFS は窓 [-15, -13.5] の内側で Opus 層が下げてよい（S-08／R-14 対応。既定の委任）。

## 5. 到達の主張
床とレベルマッチ後に比較。主たる主張: c1 マスターの 20–60 Hz エネルギーが +2.5 dB 以上、c2 20–80 Hz／全帯域の比が +2.0 dB 以上、c4 P-02 対主役が 0.3 dB 以上悪化しない（「聞ける」の機械表現）。副: c3 bass の 120–1500 Hz（倍音帯）が +1.5 dB 以上、c5 P-10 不変（±0.3）、c6 P-22 不変、c7 低域クレスト（20–120 Hz）が 1.5 dB 以上落ちない（リミッターが kick を潰していない）。

## 6. 委任範囲と事前承認の分岐
既定に加えて許す: m01 の量を S-08／R-14 のために下限 2.5 まで下げる、目標 LUFS を -15.0 まで下げる、KM-0001 の追加（分岐）、m05/m06 を外す。禁止: m01 と m02 を両方外す、sub を bass 帯（60–250 Hz）のブーストに読み替える、声を下げて相対的に低域を出す、マスター EQ。分岐: S-08／R-14 → ① trk_drums に KM-0001（peak、閾値 -18〜-12 dB を S-08 余裕で掃引、4:1、knee 3、attack 1 ms、release 60 ms）→ ② 目標 LUFS -14.5 → -15.0 → ③ m01 を 2.5 へ → ④ RB-3（未達宣言の候補）。S-03／S-04 → bus_mix に stereo mono_below_hz 120（R-09）。c4 悪化 → m01/m02 を下限へ、m04 を 125 Hz へ。それでも → RB-3（声 vs sub の優先順位、b.4 条件 2）。c1 未達（m01 が max でも +2.5 届かない）→ RB-3（素材に sub があるという読みが覆る）。c7 悪化（kick が潰れる）→ KM-0001 より先に目標引き下げ。

## 7. 再召喚してほしい条件
- sub +2.5 dB が GR p95 を 4 dB 超に押し上げ、目標を -15.0 に下げても戻らない（不変領域が意図の中心を塞ぐ。b.4 条件 4）。
- m03 の倍音で P-11 または OF-5 small_speaker が落ちる。
- 床との同一収束。

## 8. 採らなかった案と理由
- bass_heavy テンプレ: 床と同一収束〔知見: KL-0001〕。
- kick ダッキング／サイドチェイン: 床で 0.0017 dB〔知見: KL-0001〕。kick キーの道具もない（10 節）。
- 低域モノ化を既定で: 既にモノ（drums 0.999、bass 0.984）。S-03/S-04 の分岐にだけ残す（R-09）。
- サブハーモニック合成（1 オクターブ下を生成）: 道具がない（10 節）。
- bass の 254 Hz 競合カット: 床で棄却。
- club プロファイル: 依頼は「聞ける」。別作品。
- マスター段の低シェルフ: R-15／R-30、master への chain_add は不変領域。

## 9. 人の耳で確かめる点
3.1 s（verse1 入り: kick の sub が体感かボワつきか）、36.3 s（hook1: bass+kick、glue のポンピング〔知見: 07a C3〕）、61.75 s（最大区間: kick がリミッターで潰れていないか）、71.5 s（verse2: HPF 115 Hz 後の声の薄さ）、84.3 s（outro: bass -20.7 で最大。倍音と woodwinds の重なり）、95.7 s（tail）。

## 10. 道具の要望
kick 打点をキーにしたサイドチェイン（bass のゲイン）、帯域限定サチュレーション（120 Hz–1.5 kHz だけに drive）、サブハーモニック合成、区間限定 EQ（hook だけ sub シェルフ）。

```json direction
{
  "schema_version": 1,
  "kind": "direction",
  "song": "manko-shugi",
  "request": { "pattern": "p2", "utterance": "超重低音強化しつつも聞ける" },
  "sources": { "analysis": "ana_0e97838efceb", "dossier_sha256": "7eaa75d8829f34ce", "cards": ["KL-0001", "KM-0001"] },
  "aims": [
    { "id": "a1", "phrase": "超重低音強化", "text": "20–80 Hz のエネルギーを床より明確に増やす。素材は kick の sub（drums ステム）と bass の最低オクターブ", "confidence": "high", "assumption": "808 はない（bass は sub 1%）。体感帯（<60 Hz）を優先し、太さ帯（60–120）は保つ" },
    { "id": "a2", "phrase": "聞ける", "text": "声の明瞭さとモノ・小口径再生を守る: 対主役マスキングを悪化させず、bass に倍音を付け、周辺の 60–120 Hz を整理する", "confidence": "medium", "assumption": "配信（スマホ・イヤホン）で聴く。クラブ再生は求めていない" }
  ],
  "variants": [
    { "id": "var_p2", "profile": "streaming_universal", "delivery": ["hires_native", "distributor_44k16"], "target_lufs": null, "reason": "「聞ける」= 日常の配信再生。club は再生系も作品も別になるので選ばない。-14 LUFS/-1 dBTP では sub がピーク予算を食うので、目標は窓内で Opus 層が下げてよい" }
  ],
  "template_use": { "floor": "comfort:0.5", "keep_floor_mix": true, "notes": "床を出発点に低域の手を重ねる。床の bass の HPF 27.5 と comp、vocals の mud/res/comp/deess/sat はそのまま" },
  "moves": [
    { "id": "m01", "aim": "a1", "stage": "mix", "target": "trk_drums", "section": null, "op": "chain_add", "processor": "eq", "params": { "shape": "low_shelf", "freq_hz": 55, "gain_db": [2.5, 4.5], "bw_oct": 1.5, "phase": "minimum" }, "select": { "gain_db": "max" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 2.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" }, { "quantity": "obs:o4", "direction": "not_worse", "tolerance": 1.5, "unit": "dB" } ],
      "basis": "曲資料 §5.2 sub は drums 単独所有（bass より 17 dB 強い）/ 07b §8（sub は感じる帯域）/ 07a B1 上方拡散 → 対主役を安全弁に / R-06 超過の理由: 依頼が sub を主語にする（f.1）", "origin": "new" },
    { "id": "m02", "aim": "a1", "stage": "mix", "target": "trk_bass", "section": null, "op": "chain_add", "processor": "eq", "params": { "shape": "low_shelf", "freq_hz": 65, "gain_db": [3.0, 5.0], "bw_oct": 1.2, "phase": "minimum" }, "select": { "gain_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "曲資料 §2 bass HPF 27.5 Hz = 0.7×f0 → 最低 f0 ≈ 39 Hz〔推定〕、sub 1% / R-07 / genre_priors hiphop low_end_foundation", "origin": "new" },
    { "id": "m03", "aim": "a2", "stage": "mix", "target": "trk_bass", "section": null, "op": "chain_add", "processor": "saturator", "params": { "mode": "asymmetric", "drive_db": [6.0, 9.0], "asymmetry": 0.3, "mix": [0.25, 0.35], "output_db": 0.0, "oversample": 2 }, "select": { "drive_db": "mid", "mix": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o3", "direction": "up", "min_delta": 1.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-11", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" }, { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "mix_rules saturation.bass_enhance / genre_priors hiphop「808 needs harmonics, not sub only」/ 07b §20 / OF-5 pitch_preserved_without_fundamental", "origin": "catalog" },
    { "id": "m04", "aim": "a2", "stage": "mix", "target": "trk_vocals", "section": null, "op": "chain_param", "processor": "filter", "params": { "kind": "hpf", "freq_hz": [105, 125], "slope_db_oct": 18 }, "select": { "freq_hz": "mid" }, "replaces": "mx.trk_vocals.hpf",
      "expect": [ { "quantity": "obs:o5", "direction": "down", "min_delta": 3.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-10", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" }, { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "曲資料 §5.2/§5.3: vocals は bass 帯 45%（込み -26.6 dB で bass より強い）、arr1/arr2 の 3 主役を依頼の優先で読み替え → 譲るのは vocals（R-08, R-28）/ vocabulary futoi の安全弁 body_floor → 125 Hz 上限 / hpf by_role vocals max 100 を理由つきで超える", "origin": "new" },
    { "id": "m05", "aim": "a2", "stage": "mix", "target": "trk_guitar", "section": null, "op": "chain_param", "processor": "filter", "params": { "kind": "hpf", "freq_hz": [90, 120], "slope_db_oct": 12 }, "select": { "freq_hz": "mid" }, "replaces": "mx.trk_guitar.hpf",
      "expect": [ { "quantity": "obs:o6", "direction": "down", "min_delta": 4.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o2", "direction": "up", "min_delta": 0, "unit": "dB" } ],
      "basis": "mix_rules hpf by_role guitar max_hz 120 / R-07 R-08 / 曲資料 §4.1 guitar bass 0.37", "origin": "catalog" },
    { "id": "m06", "aim": "a2", "stage": "mix", "target": "trk_keyboard", "section": null, "op": "chain_add", "processor": "filter", "params": { "kind": "hpf", "freq_hz": [80, 100], "slope_db_oct": 12 }, "select": { "freq_hz": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o7", "direction": "down", "min_delta": 3.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o2", "direction": "up", "min_delta": 0, "unit": "dB" } ],
      "basis": "mix_rules hpf by_role keyboard max_hz 100 / R-07 R-08 / 曲資料 §4.1 keyboard bass 0.30、床に HPF なし", "origin": "catalog" }
  ],
  "claims": [
    { "id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 2.5, "unit": "dB", "primary": true },
    { "id": "c2", "quantity": "obs:o2", "vs": "floor", "direction": "up", "min_delta": 2.0, "unit": "dB", "primary": true },
    { "id": "c3", "quantity": "obs:o3", "vs": "floor", "direction": "up", "min_delta": 1.5, "unit": "dB", "primary": false },
    { "id": "c4", "quantity": "P-02:vs_lead", "vs": "floor", "direction": "not_worse", "tolerance": 0.3, "unit": "dB", "primary": true },
    { "id": "c5", "quantity": "P-10", "vs": "floor", "direction": "not_worse", "tolerance": 0.3, "unit": "dB", "primary": false },
    { "id": "c6", "quantity": "P-22", "vs": "floor", "direction": "not_worse", "tolerance": 0, "unit": "penalty", "primary": false },
    { "id": "c7", "quantity": "obs:o4", "vs": "floor", "direction": "not_worse", "tolerance": 1.5, "unit": "dB", "primary": false }
  ],
  "observations": [
    { "id": "o1", "primitive": "band_energy", "target": "master", "band_hz": [20, 60], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o2", "primitive": "band_ratio", "target": "master", "band_hz": [20, 80], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o3", "primitive": "band_energy", "target": "trk_bass", "band_hz": [120, 1500], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o4", "primitive": "crest", "target": "master", "band_hz": [20, 120], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o5", "primitive": "band_energy", "target": "trk_vocals", "band_hz": [60, 110], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o6", "primitive": "band_energy", "target": "trk_guitar", "band_hz": [40, 120], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o7", "primitive": "band_energy", "target": "trk_keyboard", "band_hz": [40, 100], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" }
  ],
  "delegation": {
    "allowed": ["範囲内の量の選択", "m01 の gain_db を S-08/R-14 のために下限 2.5 まで下げる", "目標 LUFS を窓内で -15.0 まで下げる", "KM-0001 のドラムのピーク制御を分岐どおり追加する", "m05/m06 が効かなければ外す"],
    "forbidden": ["狙いの変更・追加", "m01 と m02 を両方外す", "sub（20–80 Hz）を bass 帯（60–250 Hz）のブーストに読み替える", "声を下げて相対的に低域を出す", "マスター EQ", "主張の削除・最小量の引き下げ"]
  },
  "branches": [
    { "on": "S-08|R-14", "do": "① trk_drums に chain_add compressor（detector peak、threshold_db [-18,-12] select sweep:S-08_margin、ratio 4、knee_db 3、attack_ms 1、release_ms 60）= KM-0001 → ② 目標 LUFS を -14.5、次に -15.0 → ③ m01 を 2.5 dB へ → ④ まだ不通なら RB-3（未達宣言の候補）" },
    { "on": "S-03|S-04", "do": "bus_mix に chain_add stereo（mono_below_hz 120）。R-09。m02 の bw_oct を 1.0 に" },
    { "on": "claim:c4", "do": "m01/m02 を下限へ、m04 を 125 Hz へ。それでも悪化なら RB-3（声 vs sub の優先順位、b.4 条件 2）" },
    { "on": "claim:c1", "do": "m01 が max でも +2.5 dB 届かない → RB-3（kick に sub があるという読みが覆る）" },
    { "on": "claim:c7", "do": "kick が潰れている。KM-0001 より先に目標 LUFS の引き下げ" },
    { "on": "safeguard:m03", "do": "m03 の mix を 0.25、drive 6.0 へ。それでも P-11 悪化なら m03 を外し c3 を未達として記録" }
  ],
  "recall_on": [
    "sub +2.5 dB が GR p95 を 4 dB 超に押し上げ、目標を -15.0 に下げても戻らない（不変領域が意図の中心を塞ぐ）",
    "m03 の倍音で P-11 または OF-5 small_speaker が落ちる",
    "床との同一収束（ミックス changes のハッシュ一致）"
  ],
  "rejected": [
    { "candidate": "bass_heavy テンプレへの切替", "reason": "床と同一収束（v02）", "card": "KL-0001" },
    { "candidate": "kick ダッキング／サイドチェイン", "reason": "床で 0.0017 dB。kick キーの道具もない（tool_requests）", "card": "KL-0001" },
    { "candidate": "低域モノ化を既定で", "reason": "低域は既にモノ（drums 0.999、bass 0.984、曲資料 §5.4）。R-09 により S-03/S-04 の分岐にだけ残す", "card": null },
    { "candidate": "サブハーモニック合成", "reason": "道具がない（tool_requests）", "card": null },
    { "candidate": "bass への 254 Hz 競合カット", "reason": "床で棄却（曲資料 §5.1）", "card": null },
    { "candidate": "club プロファイル", "reason": "依頼は「聞ける」。再生系も作品も別になる", "card": null },
    { "candidate": "マスター段の低シェルフ", "reason": "R-15/R-30。master への chain_add は不変領域", "card": null }
  ],
  "listen_for": [
    { "t_s": 3.1, "what": "verse1 入り: kick の sub が体感か、ボワつき（vocabulary bowabowa）か" },
    { "t_s": 36.3, "what": "hook1: bass+kick の重なり、glue のポンピング（07a C3 フラクチュエーション）" },
    { "t_s": 61.75, "what": "最大区間: kick がリミッターで潰れていないか（c7）" },
    { "t_s": 71.5, "what": "verse2: HPF 115 Hz 後の声の薄さ（futoi の安全弁）" },
    { "t_s": 84.3, "what": "outro: bass -20.7 で全曲最大。倍音と woodwinds の重なり" },
    { "t_s": 95.7, "what": "tail: 低域の余韻、ノイズ" }
  ],
  "tool_requests": ["kick 打点をキーにしたサイドチェイン（trk_bass のゲイン）", "帯域限定サチュレーション（120 Hz–1.5 kHz だけに drive）", "サブハーモニック合成（1 オクターブ下）", "区間限定 EQ（hook だけ sub シェルフ）"],
  "human_questions": [
    { "q": "「超重低音」は体感（60 Hz 以下）か太さ（60–120 Hz）か", "assumed": "両方。体感を優先" },
    { "q": "声が少し薄くなる（HPF 115 Hz 前後）ことを許容するか", "assumed": "許容" }
  ]
}
```
