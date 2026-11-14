---
id: dir_68e88f393670
kind: direction
title: マンコ主義 × 聞きごこちを最大追求 全体指揮書
song: manko-shugi
request: "聞きごこちを最大追求"
pattern: p1
analysis: ana_8a8a77341fcd
created: 2026-11-14
status: active
visibility: public
---

# 全体指揮書 p1 — マンコ主義 × 「聞きごこちを最大追求」

## 1. 狙い
長く聴いても疲れないミックスにする。「聞きごこち」→ a1（声が伴奏から浮かず、低中域の重なりが薄く、声なしの終盤の密度が整う）、「最大追求」→ a2（疲労の方向にある高域ブースト・圧縮・マスター処理には触らない）。確信度 medium。仮定: 利用者は派手さでなく耳当たりを求める〔推定〕。

## 2. 全体方針
差はミックス段の 3 か所だけで作る。(a) 浮いた主役を 1 dB 下げる（P-10 5.77 → 目標 [2, 5] の内側。床の計画器は主役を上げる側しか動かなかった〔測定 §4.3〕）、(b) lowmid 比 0.90／0.76 の synth と keyboard を 300–350 Hz で -2 dB（上方拡散マスキング〔知見: 07a B1〕、200–800 Hz が最も濁る〔知見: 07 §5-3〕、「こもり」の対処〔知見: vocabulary komori〕）、(c) outro（84.3 s〜）で synth を -1.5 dB（arr4/arr5、R-28）。**触らない所**: drums、bass、床の vocal チェーン 7 段、リバーブ（hiphop 既定の短いプレート）、マスター（計画器に任せる）。暗い音色（highmid+air 4%）は作品の個性として残す（R-17、〔知見: 07 §6-1〕）。KL-0001 の警告どおり、床との同一収束を direction check で確かめる。

## 3. 手
4 手、すべて mix 段、静的。m04 だけ区間ゲイン（オートメーション）。量は範囲で書き、既定は中央値。詳細はブロック。

## 4. 変種別の差分
`streaming_universal`（既定）1 本。正規化媒体で疲労を避ける目的と合い、別の出口を選ぶ理由がない。目標 LUFS はプロファイル既定のまま。

## 5. 到達の主張
床とレベルマッチ後に比較。主たる主張: c1 P-10 が 0.5 dB 以上下がる（5.77 → 5.27 以下。目標帯内 5.0 以下が望ましいが主張は 0.5）、c2 マスターの lowmid 比（200–800 Hz／全帯域）が 0.4 dB 以上下がる。副: c3 P-02 全体が 0.2 dB 以上下がる、c4 outro 区間の lowmid 比が 0.5 dB 以上下がる、c5 P-02 対主役が 0.3 dB 以上悪化しない、c6 P-22 が悪化しない。

## 6. 委任範囲と事前承認の分岐
既定（b.4）に加えて: m02/m03 の中心周波数を 250–450 Hz で掃引してよい。m04 は効かなければ外してよい。m01 は外せない（主たる主張）。禁止: 声を上げる方向の手、高域ブースト、圧縮の追加、リバーブ量の変更。分岐: c1 未達 → m01 を下限 -1.5 dB へ。それでも 5.0 超なら伴奏を上げずに「P-10 は 5.x に留まる」と報告（床保証の範囲内で出す）。m01 の安全弁（P-02 対主役 +0.3 超）→ m01 を -0.5 に縮め、m02/m03 を -3.0（競合側を下げる R-05）。c2 未達 → 掃引、bw 1.5 まで。S-03/S-04/S-08 不通 → 想定外。床へ戻し RB-3。

## 7. 再召喚してほしい条件
- m01 を -1.5 dB にしても P-10 が 5.0 を超える（浮きはレベル由来という読みが覆る）。
- m02/m03 で P-02 全体が 0.1 dB も動かない（低中域の重なりは P-02 では測れない。別の量が要る）。
- 床との同一収束（ミックス changes のハッシュ一致）。

## 8. 採らなかった案と理由
- 254 Hz の対主役競合カット: 床で 4 回棄却〔測定 §5.1〕。
- 高域シェルフで暗さを直す: Harman を目標にしない（R-17）、シャープネス増は疲労方向〔知見: 07 §6-1、07a C1〕。
- バス圧縮の追加／glue の強化: 圧縮選好は条件依存で過圧縮は嫌われる〔知見: 07a G6、G7〕、R-27、LRA 下端まで 0.77。
- comfort 強度 1.0 のテンプレ切替: 同一収束〔知見: KL-0001〕。
- kick ダッキング: 床で 0.0017 dB〔知見: KL-0001〕。
- vocals のサチュレーター mix 低減（粗さ〔知見: 07a C2〕）: 小口径での存在感（OF-5）と引き換えで、量を測る指標がない → 聴取点へ。
- woodwinds の終盤ゲイン: outro の旋律を担っている可能性 → 聴取点へ。

## 9. 人の耳で確かめる点
5.5 s（verse1: 声が -1 dB で引っ込みすぎないか）、36.3 s（hook1 入り: 対比が残るか）、61.75 s（最大区間: 声と drums の前後）、84.3 s（outro: synth -1.5 dB の後に woodwinds が旋律として立つか、暗さ）、95.7 s（tail: 密度）。

## 10. 道具の要望
区間限定の EQ（outro だけ lowmid を削りたい。今回は区間ゲインで代替）。

```json direction
{
  "schema_version": 1,
  "kind": "direction",
  "song": "manko-shugi",
  "request": { "pattern": "p1", "utterance": "聞きごこちを最大追求" },
  "sources": { "analysis": "ana_8a8a77341fcd", "dossier_sha256": "7eaa75d8829f34ce", "cards": ["KL-0001"] },
  "aims": [
    { "id": "a1", "phrase": "聞きごこち", "text": "長く聴いても疲れない: 声が伴奏から浮かず、低中域の重なりが薄く、声なしの終盤の密度が整う", "confidence": "medium", "assumption": "派手さではなく耳当たりを求めている。comfort の意図を床より一歩進める" },
    { "id": "a2", "phrase": "最大追求", "text": "疲労の方向にある高域ブースト・圧縮・マスター処理には触らない。暗い音色は個性として残す", "confidence": "medium", "assumption": "highmid+air 4% は生成由来の音色で、直す依頼ではない" }
  ],
  "variants": [
    { "id": "var_p1", "profile": "streaming_universal", "delivery": ["hires_native", "distributor_44k16"], "target_lufs": null, "reason": "既定。正規化媒体で疲労を避ける目的と合い、別の出口を選ぶ理由がない" }
  ],
  "template_use": { "floor": "comfort:0.5", "keep_floor_mix": true, "notes": "床（comfort × streaming_universal の適用済みミックス）を出発点に、下の手を重ねる。床の vocal チェーン 7 段・リバーブ・glue はそのまま" },
  "moves": [
    { "id": "m01", "aim": "a1", "stage": "mix", "target": "trk_vocals", "section": null, "op": "gain", "processor": null, "params": { "delta_db": [-1.5, -0.5] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "P-10", "direction": "down", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02:vs_lead", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "R-05 / mix_rules static_balance lead_cut_max_db 3.0 / genre_priors hiphop P-10 [2,5] / 07b §32 / 曲資料 §4.3 P-10 5.77 floating", "origin": "catalog" },
    { "id": "m02", "aim": "a1", "stage": "mix", "target": "trk_synth", "section": null, "op": "chain_add", "processor": "eq", "params": { "shape": "peak", "freq_hz": 350, "gain_db": [-3.0, -1.5], "bw_oct": 1.2, "phase": "minimum" }, "select": { "gain_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "down", "min_delta": 0.3, "unit": "dB" }, { "quantity": "P-02", "direction": "down", "min_delta": 0.1, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o3", "direction": "not_worse", "tolerance": 1.0, "unit": "dB" } ],
      "basis": "vocabulary komori / R-05 R-06 R-12 R-29 / 07 §5-3 / 07a B1 / 曲資料 §4.1 synth lowmid 0.90", "origin": "new" },
    { "id": "m03", "aim": "a1", "stage": "mix", "target": "trk_keyboard", "section": null, "op": "chain_add", "processor": "eq", "params": { "shape": "peak", "freq_hz": 320, "gain_db": [-3.0, -1.5], "bw_oct": 1.2, "phase": "minimum" }, "select": { "gain_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "down", "min_delta": 0.2, "unit": "dB" } ],
      "safeguard": [ { "quantity": "obs:o3", "direction": "not_worse", "tolerance": 1.0, "unit": "dB" } ],
      "basis": "vocabulary komori / R-05 R-06 R-29 / 07 §5-3 / 曲資料 §4.1 keyboard lowmid 0.76、§5.1 の 254 Hz 狭帯域カットは棄却済みなので広帯域で", "origin": "new" },
    { "id": "m04", "aim": "a1", "stage": "mix", "target": "trk_synth", "section": { "t0_s": 84.3, "t1_s": 98.88 }, "op": "gain", "processor": null, "params": { "delta_db": [-2.0, -1.0] }, "select": { "delta_db": "mid" }, "replaces": null,
      "expect": [ { "quantity": "obs:o2", "direction": "down", "min_delta": 0.5, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-22", "direction": "not_worse", "tolerance": 0, "unit": "penalty" } ],
      "basis": "曲資料 §5.3 arr4/arr5（synth が lowmid/mid を譲る）/ R-28 / 曲資料 §3 outro は声 -24.0 で synth が最大", "origin": "catalog" }
  ],
  "claims": [
    { "id": "c1", "quantity": "P-10", "vs": "floor", "direction": "down", "min_delta": 0.5, "unit": "dB", "primary": true },
    { "id": "c2", "quantity": "obs:o1", "vs": "floor", "direction": "down", "min_delta": 0.4, "unit": "dB", "primary": true },
    { "id": "c3", "quantity": "P-02", "vs": "floor", "direction": "down", "min_delta": 0.2, "unit": "dB", "primary": false },
    { "id": "c4", "quantity": "obs:o2", "vs": "floor", "direction": "down", "min_delta": 0.5, "unit": "dB", "primary": false },
    { "id": "c5", "quantity": "P-02:vs_lead", "vs": "floor", "direction": "not_worse", "tolerance": 0.3, "unit": "dB", "primary": false },
    { "id": "c6", "quantity": "P-22", "vs": "floor", "direction": "not_worse", "tolerance": 0, "unit": "penalty", "primary": false }
  ],
  "observations": [
    { "id": "o1", "primitive": "band_ratio", "target": "master", "band_hz": [200, 800], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o2", "primitive": "band_ratio", "target": "master", "band_hz": [200, 800], "ref_band_hz": [20, 20000], "section": { "t0_s": 84.3, "t1_s": 98.88 }, "stat": "mean", "level_match": true, "unit": "dB" },
    { "id": "o3", "primitive": "band_ratio", "target": "master", "band_hz": [20, 250], "ref_band_hz": [20, 20000], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" }
  ],
  "delegation": {
    "allowed": ["範囲内の量の選択", "m02/m03 の中心周波数を 250–450 Hz で掃引（sweep:obs:o1）、bw_oct 1.5 まで", "m04 が効かなければ外す", "目標 LUFS はプロファイル既定のまま（下げる理由は想定しない）"],
    "forbidden": ["狙いの変更・追加", "声を上げる方向の手", "高域ブースト", "圧縮の追加・glue の強化", "リバーブ量の変更", "m01 の削除（主たる主張）", "主張の削除・最小量の引き下げ"]
  },
  "branches": [
    { "on": "claim:c1", "do": "m01 を下限 -1.5 dB へ。それでも P-10 > 5.0 なら伴奏を上げずに『P-10 は 5.x に留まる』と報告して出す（床保証の範囲内）" },
    { "on": "safeguard:m01", "do": "m01 を -0.5 dB に縮め、m02/m03 を -3.0 dB（競合側を下げる R-05）" },
    { "on": "claim:c2", "do": "m02/m03 の中心を 250–450 Hz で掃引、bw_oct 1.5 まで。それでも届かなければ再召喚（P-02 で測れない）" },
    { "on": "S-03|S-04|S-08", "do": "想定外。床へ戻し RB-3" }
  ],
  "recall_on": [
    "m01 を -1.5 dB にしても P-10 が 5.0 を超える（浮きはレベル由来という読みが覆る）",
    "m02/m03 で P-02 全体が 0.1 dB も動かない（低中域の重なりは P-02 で測れない。別の量が要る）",
    "床との同一収束（ミックス changes のハッシュ一致、レベルマッチ後の差分 RMS が -100 dBFS 以下）"
  ],
  "rejected": [
    { "candidate": "254 Hz の対主役競合カット（keyboard/drums）", "reason": "床で 4 回棄却、改善なし（曲資料 §5.1）", "card": null },
    { "candidate": "高域シェルフで暗さ（air 0.6%）を直す", "reason": "R-17（Harman を目標にしない）、07 §6-1、07a C1 シャープネス増は疲労方向", "card": null },
    { "candidate": "バス圧縮の追加／glue の強化", "reason": "07a G6/G7（圧縮選好は条件依存、過圧縮は嫌われる）、R-27、LRA 2.77 は下端まで 0.77", "card": null },
    { "candidate": "comfort 強度 1.0 のテンプレ切替", "reason": "同一収束の恐れ", "card": "KL-0001" },
    { "candidate": "kick ダッキング", "reason": "床で 0.0017 dB、解く対象がない", "card": "KL-0001" },
    { "candidate": "vocals サチュレーター mix 0.25 → 0.15（粗さ 07a C2）", "reason": "OF-5 小口径の存在感と引き換え。量を測る指標がない → listen_for", "card": null },
    { "candidate": "woodwinds の outro ゲイン（arr4/arr5）", "reason": "outro の旋律を担う可能性（声 -24.0、woodwinds -28.3）→ listen_for", "card": null }
  ],
  "listen_for": [
    { "t_s": 5.5, "what": "verse1: 声 -1 dB で引っ込みすぎないか（P-10 5.0 前後の聴感）" },
    { "t_s": 36.3, "what": "hook1 入り: break からの対比が残るか" },
    { "t_s": 61.75, "what": "最大区間: 声と drums の前後関係、350 Hz カット後の synth の薄さ" },
    { "t_s": 84.3, "what": "outro: synth -1.5 dB の後に woodwinds が旋律として立つか。暗さが気になるか" },
    { "t_s": 95.7, "what": "tail: 密度と余韻" }
  ],
  "tool_requests": ["区間限定の EQ（outro だけ lowmid を削る。今回は区間ゲインで代替）"],
  "human_questions": [
    { "q": "「聞きごこち」は疲れないことか、温かい音色のことか", "assumed": "疲れないこと" },
    { "q": "暗い音色（highmid+air 4%）を作品の個性として残してよいか", "assumed": "残す" }
  ]
}
```
