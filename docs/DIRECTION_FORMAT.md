# 指揮書の形式（DIRECTION_FORMAT v1）

指揮レイヤー（`director/`、コアの外。コアは import しない）が扱う指揮書の契約。director（PM 層）が書き、`mankomix direction validate／apply／check` が機械で扱う。改築案 v2 の b.6／d.2／c.2 に準拠した最小版で、v2 の決裁（D-085〜／Q-29〜）を先取りしない。

## 0. 道具

| コマンド | 役割 |
|---|---|
| `mankomix direction dossier --project <p> --song <slug> --out <md>` | 曲資料（決定論・読み取りのみ） |
| `mankomix direction validate [--project <p>] <direction.md>` | 形式・op・プロセッサ宣言範囲（範囲の両端）・不変領域・量の参照・評価段 E1〜E3。誤りがあれば終了コード 1 |
| `mankomix direction apply --project <p> <direction.md>` | 床（適用済みミックス）に手を重ねる。`cleanup_override` → `clean plan --apply`、ミックスの手 → 1 本の `mxp_` 提案 → `plan apply`。`directions/` に凍結コピーと適用記録 `dir_<id>.apply.json`。マスター目標を返す |
| `mankomix direction check --project <p> --floor <floor> <direction.md>` | 描画結果を床とレベルマッチして比べる（主張・期待・ガード、`move_ref` の網羅、ゲート定義ハッシュの前後一致、床との同一収束）→ `directions/dir_<id>.outcome.json` |
| `mankomix direction query [--project <p>] <audio> <spec>` | 観察量（v2 の `analyze query` の最小版。既存の `analyze` の挙動を変えないため `direction` の下に置く） |
| `mankomix kb index／kb lint` | 蓄積庫 `kb/` の索引と検査 |

実行の流れ: 床の写し → `direction validate` → `direction apply` → `master plan --profile <p> [--target-lufs <t>] --apply` → `render` → `verify` → `gate` → `direction check` → kb に結果を収蔵（`kb index`、`kb lint`）。

## 1. 文書

- 指揮書は Markdown 1 本。v2 b.6 の 10 節（狙い／全体方針／手／変種別の差分／到達の主張／委任範囲と事前承認の分岐／再召喚条件／採らなかった案／人の耳で確かめる点／道具の要望）を散文で書き、**```` ```json direction ```` のフェンスを 1 つだけ**含める
- ID: `dir_` ＋ ブロックの JSON を正規化（キー順ソート、区切り `,` `:`、UTF-8、ensure_ascii=False）した SHA-256 の先頭 12 桁。分析メモは `ana_` ＋ **front matter を除いた本文**（2 つ目の `---` 行の次の行から末尾まで、UTF-8 のバイト列そのまま）の SHA-256 先頭 12 桁（front matter に自分の ID を書くため、front matter はハッシュに含めない）
- Fable の書いた文書には、後から書き足さない。決定論側の結果は `dir_<id>.outcome.json` に分ける

## 2. ブロックの形

```json
{
  "schema_version": 1,
  "kind": "direction",
  "song": "manko-shugi",
  "request": { "pattern": "p1", "utterance": "（依頼の原文）" },
  "sources": {
    "analysis": "ana_xxxxxxxxxxxx",
    "dossier_sha256": "（曲資料の SHA-256。先頭 16 桁で可）",
    "cards": []
  },
  "aims": [ { "id": "a1", "phrase": "（依頼の語句）", "text": "（狙い）", "confidence": "high|medium|low", "assumption": "…" } ],
  "variants": [
    { "id": "var_p1", "profile": "streaming_universal", "delivery": ["hires_native"], "target_lufs": null, "reason": "…" }
  ],
  "template_use": { "floor": "comfort:0.5", "keep_floor_mix": true, "notes": "床（comfort × streaming_universal の適用済みミックス）を出発点に、下の手を重ねる" },
  "moves": [
    {
      "id": "m01", "aim": "a1", "stage": "mix", "target": "trk_bass", "section": null,
      "op": "chain_add",
      "processor": "eq",
      "params": { "shape": "low_shelf", "freq_hz": 80, "gain_db": [1.5, 3.0], "bw_oct": 1.0, "phase": "minimum" },
      "select": { "gain_db": "mid" },
      "replaces": null,
      "expect": [ { "quantity": "obs:o1", "direction": "up", "min_delta": 1.0, "unit": "dB" } ],
      "safeguard": [ { "quantity": "P-02", "direction": "not_worse", "tolerance": 0.3, "unit": "dB" } ],
      "basis": "R-xx / knowledge/mix_rules.json の該当項 / この曲の測定からの推論（曲資料 §n）",
      "origin": "catalog|case|new"
    }
  ],
  "claims": [
    { "id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 1.0, "unit": "dB", "primary": true }
  ],
  "observations": [
    { "id": "o1", "primitive": "band_energy", "target": "master", "band_hz": [20, 60], "section": "all", "stat": "mean", "level_match": true, "unit": "dB" }
  ],
  "delegation": { "allowed": ["範囲内の量の選択", "…"], "forbidden": ["狙いの変更", "…"] },
  "branches": [ { "on": "S-08|S-xx|claim:c1|safeguard:m01", "do": "…（事前承認の分岐。Opus 層が RB-2 で閉じる手）" } ],
  "recall_on": [ "…（曲固有の再召喚条件）" ],
  "rejected": [ { "candidate": "…", "reason": "…", "card": null } ],
  "listen_for": [ { "t_s": 32.0, "what": "…" } ],
  "tool_requests": [ "…（抽象プロセッサにない処理）" ],
  "human_questions": [ { "q": "…", "assumed": "…" } ]
}
```

## 3. 欄の規則

### op（手の種類）と必須欄

| op | 段 | 意味 | 必須欄 |
|---|---|---|---|
| `chain_add` | mix | トラックまたはバスのチェーンに処理を足す | target, processor, params |
| `chain_param` | mix | 床に既にある処理（`replaces` に処理 ID。例 `mx.trk_vocals.deesser`）の量を変える | target, replaces, params |
| `chain_remove` | mix | 床にある処理を外す | target, replaces |
| `gain` | mix | トラックのフェーダー。`params.gain_db`（絶対値）か `params.delta_db`（床からの差）。`section` を付けたときはゲインのオートメーションになる | target, params |
| `pan` | mix | `params.position`（−1〜1）、`params.width`（0〜2、ステレオ素材の側成分倍率） | target, params |
| `send` | mix | `params.bus`、`params.level_db`、`params.pre_fader` | target, params |
| `bus_add` | mix | 新しいバス（`target` に `bus_` で始まる新 ID、`params.kind` = `fx`、`params.chain` = 処理の配列、`params.output` = `bus_mix`）。バスにも `pan` を付けられる | target, params |
| `cleanup_override` | clean | 整音の段の強度（`params.overrides`。既存 `clean plan --overrides` の形）。S-07 の保護帯の内側は書けない | target, params |
| `master_target` | master | `params.target_lufs`（プロファイルのレンジ内）。マスターのチェーンはマスター計画器に任せる | params |

- `target` はトラック ID（`trk_<stem>`）、既存バス（`bus_reverb`、`bus_mix`）、新バス ID、または `master`
- `processor` と `params` は製品の抽象プロセッサ（`dsp/processors.py` の登録）とその宣言範囲に従う。範囲外は validate が拒否する
- **量は範囲で書ける**: 数値の代わりに `[下限, 上限]`。`select` で選び方を指定する: `mid`（既定）／`min`／`max`／`sweep:<量>`（Opus 層が乾式で掃引し、`<量>` が最良のものを採る。例 `sweep:S-08_margin`）
- `section`: `null`（全体）か、曲資料のセクション ID／`{"t0_s":…, "t1_s":…}`。**区間限定にできるのは `gain`（オートメーション化）だけ。** それ以外を区間限定したい場合は `tool_requests` に書く（レンダラーに区間ごとの処理切替がない）
- **時間で変わるパン（オートパン、パンのオートメーション）は現行のレンダラーにない。** 欲しい場合は `tool_requests` に書き、静的な配置・幅・ディレイ（`route: left|right`）・複数のリバーブバスで代替する
- `expect`／`safeguard`／`claims` の `quantity`: 台帳指標 `P-nn`（曲資料に値があるもの。限定子つき `P-nn:<qualifier>`、例 `P-02:vs_lead` も可。check は限定子つきの項が無ければ `P-nn` の項を読む）か、`obs:<observations の id>`
- `direction`: `up`／`down`／`not_worse`。`not_worse` は `tolerance` を持つ
- 全手に `aim`、`basis`、`origin` が必須

### observations（観察量。ゲートには入らない）

| primitive | 意味 | 欄 |
|---|---|---|
| `band_energy` | 帯域のエネルギー（dB） | band_hz |
| `band_ratio` | 帯域 A の B に対する比（dB） | band_hz, ref_band_hz |
| `crest` | クレストファクター（dB）。帯域指定可 | band_hz（任意） |
| `loudness` | 短期／積分ラウドネス（LUFS） | stat: `integrated`／`short_p95` 等 |
| `side_ratio` | 側成分 S の中央成分 M に対する比（dB）。帯域指定可 | band_hz（任意） |
| `correlation` | L/R 相関係数 | band_hz（任意） |

- `target`: `master`（描画済みマスター）か `trk_<stem>`（ミックス内の当該トラックの寄与。実装が対応しない場合は validate が `unsupported` と返す）
- `section`: `all` か セクション ID か `{"t0_s","t1_s"}`
- `level_match`: true なら床と比べる前に積分ラウドネスを揃える（R-01）

### 不変領域（validate が機械的に拒否する。v2 f.2）

ブロックのどこにも次を書けない: S-01〜S-11 の閾値・許容、`plan_margin_db`、プロファイルの天井・レンジ・納品形式の変更、R-14 の GR 上限、P-18 の閾値、OF-5、マスター段の順序・ディザ・リミッター（`limiter`、`clipper`、`dither`、`resample` を `stage: master` で使う手、`master` を target にした `chain_add`）、受理のデッドバンドとガード項、`knowledge/`・`profiles/` への書き込み。`target_lufs` はプロファイルのレンジ外を拒否する。

## 4. 評価段（validate が付ける。自己申告させない）

- E1: `origin: catalog` で、量が `knowledge/mix_rules.json` 等の既存の範囲内と確認できる手
- E2: それ以外（`new`、範囲外、`case`）。全長の評価とガード項の前後比較を `direction check` で行う
- E3: マスター段でプロファイルの既定（R-06、R-15）を超える手、主役（`trk_vocals`）への時間変化する処理。E2 に加え `listen_for` への登録が必須（無ければ validate が警告）

## 5. v1 実装の注記（validate／apply／check が実際にすること）

- **範囲と select**: 範囲 `[下限, 上限]` は両端とも宣言範囲内であることを validate が確かめる。apply は `mid`／`min`／`max` で値を選ぶ。`sweep:<量>` は v1 では未実装で、範囲の中央を使い、適用記録の `notes` に残す
- **床への重ね方**: 床のミックス提案（`mix.applied.proposal_id`）の `changes` を出発点に、手が触れたトラックのチェーン・センドを丸ごと書いた `mxp_` 提案を作り、既存の `plan apply` で適用する。足した処理・センド・バスには `owner: director` と `move_ref: dir_<id>/<move>` が付く。量を変えた床の処理（`chain_param`）にも `move_ref` が付く。外した処理（`chain_remove`）とトラックのゲイン・パンは適用記録に残る。既に指揮書の手が入っているプロジェクトには適用しない（床の新しい写しに適用する）
- **区間ゲイン**: `gain` に `section` を付けると、区間の前後 20 ms のランプを持つゲインのオートメーションになる。同じトラックの区間が重なる・接する場合と、既にオートメーションがある場合は拒否する
- **バスのパン**: 新バス・既存バスへの `pan` は、バスのチェーン末尾に `pan`（position）と `stereo`（width）の処理を足す
- **観察量**: `target: master` だけ（`trk_*` は `unsupported`）。`level_match: true`（既定）なら結果の積分ラウドネスを床に揃えてから測る
- **主張の判定**: `up` は差 ≥ `min_delta`、`down` は差 ≤ −`min_delta`。`not_worse` は、台帳指標 `P-nn` では変種の評価の罰（目標範囲からの距離）の増分 ≤ `tolerance`、観察量では |差| ≤ `tolerance`（`worse: up|down` を付けると片側）。`P-nn` の値は変種の評価（マスター計画の目的関数の項）から読む。値がない項は `not_measured`
- **手ごとの期待・ガード**: v1 では手を分離せず、全体の結果で判定する（outcome にその旨を記す）
- **同一収束**: ミックス状態（トラックのゲイン・パン・チェーン・センド・オートメーションとバス）のハッシュ一致、または床とのレベルマッチ後の差分 RMS が −60 dB 未満なら `converged: true`
- **ゲート定義ハッシュ**: `knowledge/thresholds.json`、`knowledge/rules.json`、`knowledge/objective_metrics.json`、`knowledge/mix_rules.json`、`profiles/media_profiles.json` の SHA-256 を apply 時と check 時に取り、一致を確かめる
