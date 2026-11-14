---
id: dir_b465721f74fb
kind: direction
title: マンコ主義 × 空間音響と複雑なパンニング 全体指揮書
song: manko-shugi
request: "空間音響と複雑なパンニング"
pattern: p3
analysis: ana_b174fb3a26b3
created: 2026-11-14
status: active
visibility: public
---

# 全体指揮書 p3 — マンコ主義 × 「空間音響と複雑なパンニング」

## 1. 狙い
ほぼモノ（相関 0.945、S/M 0.028〔測定 §4.1〕）の床に、奥行きの段と左右の多様性を作る。「空間音響」→ a1（前: 乾いた声・drums・bass／中: 床のプレート／奥: 新しい遠い部屋）、確信度 medium。「複雑なパンニング」→ a2（LCR の固定配置の多様性と、音価同期 L/R エコーによる時間の動き）、確信度 low（動くパンは道具にない。10 節）。仮定: 主役と低域は中央固定（hiphop prior、R-09）。モノ互換は守る。

## 2. 全体方針
差はミックス段の配置・バス・幅で作る。(a) 配置: keyboard LC（-0.4）、synth RC（+0.4）、guitar R（+0.7、床 +0.35 から）、woodwinds L（-0.7、床 -0.35 から）、backing_vocals は中央で幅 1.45（LCR の対比〔知見: 07 §2-4〕、hiphop「backing は左右に」〔知見: 07b §34〕）。guitar（sec2/4/7/9）と woodwinds（sec5/9/10）と BV（sec3–4/7）は出入りが違うので、区間ごとに鳴る位置が変わる = 自動化なしの動き〔推定〕。(b) 新バス 3: bus_space_far（遠い部屋: RT60 1.8 s、短いプリディレイ＋強い ER＋HF 減衰 = 遠い〔知見: 07 §3-1, §3-2〕、幅 1.5）、bus_echo_L（1/8 付点、左）、bus_echo_R（1/4、右。音価は BPM 91.2 から。R-11）。(c) percussion に Haas 11 ms 右（R-10: 時間域とモノ損失を報告〔知見: 07a E1〕）。(d) 最後に bus_mix で帯域別幅（120 Hz 以下 1.0、120–500 1.1、500–3k 1.3、3k 以上 1.4。M/S は既存の側を増減するだけなので、パンで側を作った後〔知見: 07 §3-4〕）。**触らない所**: vocals・drums・bass のレベル・処理・配置、床のプレート、マスター。奥行きは相対なので声が乾いて前に居るほど奥が奥に見える〔知見: 07 §3-2〕。

## 3. 手
19 手（m01–m05、m07–m20。m06 は欠番）、すべて mix 段、静的（パンのオートメーションなし）。ブロック参照。

## 4. 変種別の差分
`streaming_universal`（既定）1 本。モノ折返し検査（S-04、mono_fold_check）が付く出口で、幅を機械で守れる。sns_hot のようなモノ寄り再生前提の出口は空間の依頼と合わないので選ばない。

## 5. 到達の主張
床とレベルマッチ後に比較。主たる主張: c1 マスターの側成分比（300–8000 Hz）が +4.0 dB 以上、c2 全帯域の L/R 相関が 0.08 以上下がる（0.945 → 0.865 以下。健全域 0.3–0.8〔知見: 07 §2-3〕へ向かう）、c3 低域（20–120 Hz）の側成分比が 1.0 dB 以上増えない。副: c4 P-02 対主役不変（±0.3）、c5 P-10 不変（±0.3）、c6 break（sec3）の側成分比 +5 dB 以上。

## 6. 委任範囲と事前承認の分岐
許す: 位置を範囲内で選ぶ、左右を鏡像にする（重量バランスの傾き〔知見: 07 §2-4〕）、m19（Haas）を S-04 の lead 帯が 0.5 dB 超悪化したら外す、センド量とフィードバック（0.1–0.4）の選択。禁止: vocals・drums・bass のパン、120 Hz 以下の幅、主役を echo／far に送る、echo バスを両方外す（a2 の中心）、床のプレートの変更。分岐: S-03／S-04 → bus_mix に mono_below_hz 120（R-09）→ まだ S-04 なら m19 を外す → m05 の幅を 1.2。c1 未達 → m20 の幅を [1.0, 1.2, 1.5, 1.6]、センドを範囲の上限 → それでも → RB-3（素材がモノで届かない読み）。c3 悪化 → keyboard を -0.35、mono_below 120。c4 悪化 → far のセンド -3 dB、highcut 3500。S-08 → echo の feedback 0.1、highcut 4000 → それでも → RB-3。

## 7. 再召喚してほしい条件
- モノ折返しで BV か woodwinds が聴感上 3 dB 超消える（S-04 を通っても。幅とモノ互換の優先順位、b.4 条件 2）。
- 側成分比が +4 dB に届かない。
- ディレイの反復がテンポとずれて聞こえる（BPM 91.2 の推定が誤り。読みが覆る）。
- 床との同一収束。

## 8. 採らなかった案と理由
- 主役への Haas／ダブリング／1/8 付点のスロー: R-10、hiphop「lead vocal mono-center」、モノでコム〔知見: 07 §2-6〕、lead の時間変化処理は E3。→ 人への確認へ。
- 全帯域ワイドナー: 低域の側は定位不能で S-03 の余裕（最小相関 -0.455）を食う〔知見: 07 §2-5, §3-4〕。
- オートパン／パンのオートメーション: 道具がない（10 節）。
- 床のプレートの長尺化: hiphop は短い・乾いた既定（genre_priors）。遠さは別バスで。
- drums のハットのパン: kick+snare+hat が 1 ステム。
- strings の配置見直し: 全区間 -60 LUFS 未満。

## 9. 人の耳で確かめる点
3.1 s（verse1: keyboard L／synth R の重量バランスの傾き）、32.5 s（break: BV の幅、echo の L/R、遠い部屋の距離感）、36.3 s（hook1 入り: モノで聴いて BV と woodwinds が消えないか）、59.7 s（hook2: percussion の Haas でアタックが滲まないか）、84.3 s（outro: woodwinds 左＋echo 右 vs guitar 右の傾き）、95.7 s（tail: echo の尾の長さ）。

## 10. 道具の要望
パンのオートメーション／音価同期オートパン、区間ごとのパン切替、真のピンポンディレイ（L→R 交互、1 バス）、HRTF 系の定位（ヘッドホン前提）、リバーブの ER パターン指定。

```json direction
{
  "schema_version": 1,
  "kind": "direction",
  "song": "manko-shugi",
  "request": { "pattern": "p3", "utterance": "空間音響と複雑なパンニング" },
  "sources": { "analysis": "ana_b174fb3a26b3", "dossier_sha256": "7eaa75d8829f34ce", "cards": ["KL-0001"] },
  "aims": [
    { "id": "a1", "phrase": "空間音響", "text": "奥行きの段を作る: 声・drums・bass は乾いて前、鍵盤・シンセ・木管・FX は 2 種の空間（短いプレート=床、遠い部屋=新）に置く", "confidence": "medium", "assumption": "主役は乾いた中央（hiphop prior）。奥行きは相対で決まる（07 §3-2）" },
    { "id": "a2", "phrase": "複雑なパンニング", "text": "配置の多様性（LCR）と時間の動き: woodwinds L／guitar R／keyboard LC／synth RC の固定配置、BV の幅、音価同期の L/R エコーで動きを出す", "confidence": "low", "assumption": "時間で動くパンは道具にない。静的配置＋ディレイで代替し、要望に記録" }
  ],
  "variants": [
    { "id": "var_p3", "profile": "streaming_universal", "delivery": ["hires_native", "distributor_44k16"], "target_lufs": null, "reason": "既定。モノ折返し検査（S-04）が付く出口で幅を機械で守れる。sns_hot のようなモノ寄り再生前提の出口は空間の依頼と合わない" }
  ],
  "template_use": { "floor": "comfort:0.5", "keep_floor_mix": true, "notes": "床を出発点に配置・バス・幅を重ねる。床のプレート（bus_reverb）とそのセンド、vocals/drums/bass はそのまま" },
  "moves": [
    { "id": "m01", "aim": "a2", "stage": "mix", "target": "trk_keyboard", "section": null, "op": "pan", "processor": null, "params": { "position": [-0.5, -0.35], "width": [1.2, 1.4] }, "select": { "position": "mid", "width": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 1.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o3", "direction": "not_worse", "tolerance": 1.0, "unit": "dB" } ],
      "basis": "mix_rules static_balance.pan positions / 07 §2-4 LCR / 曲資料 §5.4 keyboard 相関 0.79（側成分あり）", "origin": "catalog" },
    { "id": "m02", "aim": "a2", "stage": "mix", "target": "trk_synth", "section": null, "op": "pan", "processor": null, "params": { "position": [0.35, 0.5], "width": [1.2, 1.4] }, "select": { "position": "mid", "width": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 1.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o3", "direction": "not_worse", "tolerance": 1.0, "unit": "dB" } ],
      "basis": "mix_rules static_balance.pan positions / 07 §2-4 / 曲資料 §5.4 synth 相関 0.85。keyboard と対称に置き lowmid の 2 本を左右に分ける", "origin": "catalog" },
    { "id": "m03", "aim": "a2", "stage": "mix", "target": "trk_guitar", "section": null, "op": "pan", "processor": null, "params": { "position": [0.6, 0.8] }, "select": { "position": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "07 §2-4 LCR（床 +0.35 を R へ）/ 曲資料 §3 guitar は sec2/4/7/9 に出入り → 位置の変化がアレンジで生まれる", "origin": "new" },
    { "id": "m04", "aim": "a2", "stage": "mix", "target": "trk_woodwinds", "section": null, "op": "pan", "processor": null, "params": { "position": [-0.8, -0.6] }, "select": { "position": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.3, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "07 §2-4 LCR（床 -0.35 を L へ、guitar と対）/ 曲資料 §3 woodwinds は sec5/9/10", "origin": "new" },
    { "id": "m05", "aim": "a2", "stage": "mix", "target": "trk_backing_vocals", "section": null, "op": "pan", "processor": null, "params": { "position": 0.0, "width": [1.3, 1.6] }, "select": { "width": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o4", "direction": "up", "min_delta": 2.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o3", "direction": "not_worse", "tolerance": 1.0, "unit": "dB" } ],
      "basis": "07b §34 backing は左右に広げる / 曲資料 §5.4 BV 相関 0.54、S/M 0.23（唯一の広い素材）/ 床の lowmid モノ損失 1.46 dB を S-04 で監視", "origin": "new" },
    { "id": "m07", "aim": "a1", "stage": "mix", "target": "bus_space_far", "section": null, "op": "bus_add", "processor": null, "params": { "kind": "fx", "output": "bus_mix", "chain": [ { "processor": "reverb", "params": { "rt60_s": 1.8, "predelay_ms": 12.0, "er_late_db": 3.0, "mix": 1.0, "lowcut_hz": 350.0, "highcut_hz": 4500.0, "rt60_low_mult": 0.7, "rt60_high_mult": 0.5, "bpm": 91.2 } } ] }, "select": {}, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "07 §3-1（Room/Hall の測定ベクトル）/ 07 §3-2 短いプリディレイ＋強い ER＋HF 減衰 = 遠い / mix_rules reverb 既定からの派生（lowcut を 350 に下げ胴を残す）/ R-11", "origin": "new" },
    { "id": "m08", "aim": "a1", "stage": "mix", "target": "bus_space_far", "section": null, "op": "pan", "processor": null, "params": { "position": 0.0, "width": [1.4, 1.6] }, "select": { "width": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.3, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o3", "direction": "not_worse", "tolerance": 1.0, "unit": "dB" } ],
      "basis": "07 §2-3 幅は側成分の増大 / 返しは 350 Hz 以上なので低域の側は増えない", "origin": "new" },
    { "id": "m09", "aim": "a1", "stage": "mix", "target": "trk_keyboard", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_space_far", "level_db": [-18, -14], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.2, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "mix_rules reverb sends_db harmony -15 を基準に遠い段へ / 07 §3-2 D/R 比が最強の距離手がかり", "origin": "catalog" },
    { "id": "m10", "aim": "a1", "stage": "mix", "target": "trk_synth", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_space_far", "level_db": [-18, -14], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.2, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "mix_rules reverb sends_db harmony / 07 §3-2", "origin": "catalog" },
    { "id": "m11", "aim": "a1", "stage": "mix", "target": "trk_woodwinds", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_space_far", "level_db": [-16, -12], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.1, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "mix_rules reverb sends_db / 曲資料 §3 woodwinds は outro の旋律候補 → 遠い段に置く", "origin": "catalog" },
    { "id": "m12", "aim": "a1", "stage": "mix", "target": "trk_fx", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_space_far", "level_db": [-12, -9], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.1, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "mix_rules reverb sends_db pads_fx_ornaments -13 → 最奥 / 曲資料 §2 fx 重要度 0.3", "origin": "catalog" },
    { "id": "m13", "aim": "a2", "stage": "mix", "target": "bus_echo_L", "section": null, "op": "bus_add", "processor": null, "params": { "kind": "fx", "output": "bus_mix", "chain": [ { "processor": "delay", "params": { "note": "1/8d", "bpm": 91.2, "time_ms": 493.4, "feedback": 0.3, "mix": 1.0, "lowcut_hz": 400.0, "highcut_hz": 5000.0, "route": "left" } } ] }, "select": {}, "replaces": null,
      "expect": [ { "quantity": "obs:o4", "direction": "up", "min_delta": 1.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "07 §3-3 テンポシンク（60000/91.2 × 0.75 = 493 ms）/ R-11 音価で記録 / 左だけに返して右の 1/4 と交互に動く", "origin": "new" },
    { "id": "m14", "aim": "a2", "stage": "mix", "target": "bus_echo_R", "section": null, "op": "bus_add", "processor": null, "params": { "kind": "fx", "output": "bus_mix", "chain": [ { "processor": "delay", "params": { "note": "1/4", "bpm": 91.2, "time_ms": 657.9, "feedback": 0.2, "mix": 1.0, "lowcut_hz": 400.0, "highcut_hz": 5000.0, "route": "right" } } ] }, "select": {}, "replaces": null,
      "expect": [ { "quantity": "obs:o4", "direction": "up", "min_delta": 1.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "07 §3-3 テンポシンク（60000/91.2 = 658 ms）/ R-11 / 左の 1/8 付点と非対称にして動きを出す", "origin": "new" },
    { "id": "m15", "aim": "a2", "stage": "mix", "target": "trk_backing_vocals", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_echo_L", "level_db": [-16, -12], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o4", "direction": "up", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "07b §34 backing は左右に / 曲資料 §3 BV は sec3–4, sec7 → break で echo が露出する", "origin": "new" },
    { "id": "m16", "aim": "a2", "stage": "mix", "target": "trk_backing_vocals", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_echo_R", "level_db": [-18, -14], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o4", "direction": "up", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "m15 と対。右は 2 dB 弱くして左右非対称の反復に", "origin": "new" },
    { "id": "m17", "aim": "a2", "stage": "mix", "target": "trk_woodwinds", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_echo_R", "level_db": [-20, -16], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.1, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "woodwinds は L（m04）、echo は R → 左の音が右で返る動き / 07 §3-3", "origin": "new" },
    { "id": "m18", "aim": "a2", "stage": "mix", "target": "trk_fx", "section": null, "op": "send", "processor": null, "params": { "bus": "bus_echo_L", "level_db": [-16, -12], "pre_fader": false }, "select": { "level_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.1, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "fx は間欠（LRA 21）で echo が目立つ / 曲資料 §2 重要度 0.3", "origin": "new" },
    { "id": "m19", "aim": "a2", "stage": "mix", "target": "trk_percussion", "section": null, "op": "chain_add", "processor": "delay", "params": { "note": "none", "bpm": 91.2, "time_ms": [9.0, 14.0], "feedback": 0.0, "mix": 0.4, "lowcut_hz": 300.0, "highcut_hz": 12000.0, "route": "right" }, "select": { "time_ms": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 0.3, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o3", "direction": "not_worse", "tolerance": 0.5, "unit": "dB" } ],
      "basis": "07a E1 先行音効果 / 07 §3-3 5–20 ms はタイトな幅、モノでコム（最初のノッチ 1000/(2×11.5) ≈ 43 Hz、以降 87 Hz 間隔）/ R-10 時間域とモノ損失を報告 / 曲資料 §4.1 percussion は 2–20 kHz を持つ唯一の素材、-38 LUFS で S-04 への寄与は小", "origin": "new" },
    { "id": "m20", "aim": "a1", "stage": "mix", "target": "bus_mix", "section": null, "op": "chain_add", "processor": "stereo", "params": { "crossovers_hz": [120.0, 500.0, 3000.0], "widths": [1.0, 1.1, 1.3, 1.4] }, "select": {}, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 1.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o3", "direction": "not_worse", "tolerance": 0.5, "unit": "dB" }, { "quantity": "obs:o5", "direction": "not_worse", "tolerance": 0.05, "unit": "coefficient" } ],
      "basis": "07 §3-4 M/S は既存の側を増減するだけ → パンで側を作った後に掛ける / 07 §2-3 健全域 0.3–0.8 / 120 Hz 以下は 1.0 のまま（R-09、S-03 最小相関 -0.455）", "origin": "new" }
  ],
  "claims": [
    { "id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 4.0, "unit": "dB", "primary": true },
    { "id": "c2", "quantity": "obs:o2", "vs": "floor", "direction": "down", "min_delta": 0.08, "unit": "coefficient", "primary": true },
    { "id": "c3", "quantity": "obs:o3", "vs": "floor", "direction": "not_worse", "tolerance": 1.0, "unit": "dB", "primary": true },
    { "id": "c4", "quantity": "P-02:vs_lead", "vs": "floor", "direction": "not_worse", "tolerance": 0.3, "unit": "dB", "primary": false },
    { "id": "c5", "quantity": "P-10", "vs": "floor", "direction": "not_worse", "tolerance": 0.3, "unit": "dB", "primary": false },
    { "id": "c6", "quantity": "obs:o4", "vs": "floor", "direction": "up", "min_delta": 5.0, "unit": "dB", "primary": false }
  ],
  "observations": [
    { "id": "o1", "primitive": "side_ratio", "target": "master", "band_hz": [300, 8000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o2", "primitive": "correlation", "target": "master", "section": "all", "stat": "mean", "level_match": true, "unit": "coefficient" },
    { "id": "o3", "primitive": "side_ratio", "target": "master", "band_hz": [20, 120], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o4", "primitive": "side_ratio", "target": "master", "band_hz": [300, 8000], "section": "sec3", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o5", "primitive": "correlation", "target": "master", "band_hz": [20, 120], "section": "all", "stat": "mean", "level_match": true, "unit": "coefficient" }
  ],
  "delegation": {
    "allowed": ["範囲内の量の選択", "全体を鏡像（L↔R）にする（重量バランスの傾き、07 §2-4）", "m19 を S-04 の lead 帯が 0.5 dB 超悪化したら外す", "センド量とフィードバック（0.1–0.4）の選択", "m20 の widths を各帯 ±0.2 で調整（120 Hz 以下は 1.0 固定）"],
    "forbidden": ["狙いの変更・追加", "vocals・drums・bass のパン・幅・処理", "120 Hz 以下の幅を 1.0 より増やす", "主役を bus_echo_* / bus_space_far に送る", "echo バスを両方外す（a2 の中心）", "床のプレート（mx.bus_reverb.plate）の変更", "主張の削除・最小量の引き下げ"]
  },
  "branches": [
    { "on": "S-03|S-04", "do": "bus_mix に chain_add stereo（mono_below_hz 120）。R-09。まだ S-04 なら m19 を外す → m05 の width を 1.2 へ" },
    { "on": "claim:c1", "do": "m20 の widths を [1.0, 1.2, 1.5, 1.6]、センド（m09–m12, m15–m18）を範囲の上限へ。それでも +4 dB に届かなければ RB-3（素材がモノで届かないという読み）" },
    { "on": "claim:c3", "do": "m01 の position を -0.35、bus_mix に mono_below_hz 120" },
    { "on": "claim:c4", "do": "far のセンド（m09–m12）を -3 dB、m07 の highcut_hz を 3500" },
    { "on": "S-08", "do": "echo の feedback を 0.1、highcut_hz 4000 → それでも不通なら RB-3" }
  ],
  "recall_on": [
    "モノ折返しで BV か woodwinds が聴感上 3 dB 超消える（S-04 を通っても。幅とモノ互換の優先順位）",
    "側成分比（obs:o1）が +4 dB に届かない",
    "ディレイの反復がテンポとずれて聞こえる（BPM 91.2 の推定が誤り）",
    "床との同一収束（ミックス changes のハッシュ一致）"
  ],
  "rejected": [
    { "candidate": "主役への Haas／ダブリング／1/8 付点のスロー", "reason": "R-10、genre_priors hiphop lead vocal mono-center、07 §2-6 モノでコム、lead の時間変化処理は E3 → human_questions", "card": null },
    { "candidate": "全帯域ワイドナー（低域含む）", "reason": "07 §2-5/§3-4 低域の側は定位不能で S-03 の余裕（最小相関 -0.455）を食う", "card": null },
    { "candidate": "オートパン／パンのオートメーション", "reason": "道具がない（tool_requests）", "card": null },
    { "candidate": "床のプレートの長尺化", "reason": "genre_priors hiphop short, dry-leaning reverb。遠さは別バスで", "card": null },
    { "candidate": "drums のハットのパン", "reason": "kick+snare+hat が 1 ステムで分離不能", "card": null },
    { "candidate": "strings の配置見直し", "reason": "全区間 -60 LUFS 未満", "card": null },
    { "candidate": "幅の主張を目的関数（clarity の P-05 width_restraint）で", "reason": "P-05 は幅の抑制側の項で、幅を増やす主張には使えない → 観察量 side_ratio/correlation で", "card": "KL-0001" }
  ],
  "listen_for": [
    { "t_s": 3.1, "what": "verse1: keyboard L／synth R の重量バランスの傾き" },
    { "t_s": 32.5, "what": "break: BV の幅、echo の L/R の動き、遠い部屋の距離感" },
    { "t_s": 36.3, "what": "hook1 入り: モノで聴いて BV と woodwinds が消えないか" },
    { "t_s": 59.7, "what": "hook2: percussion の Haas でアタックが滲まないか" },
    { "t_s": 84.3, "what": "outro: woodwinds 左＋echo 右 vs guitar 右の傾き。声なしで空間が空きすぎないか" },
    { "t_s": 95.7, "what": "tail: echo の尾の長さ（feedback）、無音への落ち方" }
  ],
  "tool_requests": ["パンのオートメーション／音価同期オートパン", "区間ごとのパン切替", "真のピンポンディレイ（L→R 交互、1 バス）", "HRTF 系の定位（ヘッドホン前提の空間）", "リバーブの ER パターン指定（部屋形状）"],
  "human_questions": [
    { "q": "「複雑なパンニング」は時間で動くパンを求めているか", "assumed": "配置の多様性＋ディレイの動きで代替し、要望に記録" },
    { "q": "ヘッドホン前提か、スピーカーも含むか", "assumed": "両方（モノ互換を守る）" },
    { "q": "主役の声に 1/8 付点のスローを入れてよいか", "assumed": "入れない（声は乾いた中央）" }
  ]
}
```
