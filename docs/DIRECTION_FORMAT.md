# 指揮書の形式（DIRECTION_FORMAT v1）

指揮レイヤー（`director/`、コアの外。コアは import しない）が扱う指揮書の契約。director（PM 層）が書き、`mankomix direction validate／apply／check` が機械で扱う。改築案 v2 の b.6／d.2／c.2 に準拠した最小版で、v2 の決裁（D-085〜／Q-29〜）を先取りしない。

**引き継ぎ書は指揮書と同一物である。** 「指揮書」は形式の名前（本書、`dir_` ID、`direction` ブロック）、「引き継ぎ書」は役割の名前（計画を終えた指揮者が、実行側と人へ判断を渡す文書）で、上位の文書は作らない。分析メモは根拠の記録（`ana_` ID）として引き継ぎ書に含めず、指揮書が `sources` で分析メモ・曲資料・カード・refstudy を指す。

### 計画フェーズの既定の型（既定であって手順ではない）

指揮者が 1 曲の指揮書を書くまでの進め方の既定。**型は手順でもゲートでもない。** 新しいコマンド・文書・欄は無く、既存の道具の並べ方の既定である。

| 段 | すること | 使う道具・資料 | 残る場所 |
|---|---|---|---|
| 1 分析 | 曲全体とステムを読む | 曲資料（`direction dossier`）、追加の `direction query` | 分析メモの曲の読み（〔測定〕〔推定〕） |
| 2a 調査・文献の脚 | この曲の問いに効く知見を引く | 曲資料 §10.1 経験・§10.2 理論の棚、`kb search`／`kb show`（lesson／move／research／theory）、案件ごとの調査ログ | 分析メモの知見の節、`sources.cards` |
| 2b 調査・リファレンスの脚 | 原液（持ち込まれたリファレンス）を測り、逆算する | `direction ref study` → refstudy、`direction ref compare` → refsheet、work／engineer カード | 分析メモ「リファレンスの読み」（§6.4）、`sources.references` |
| 3 引き継ぎ書の立案 | 1・2 を受けて手と主張に落とす | 指揮書（散文 10 節＋ `direction` ブロック） | `dir_<id>`、以降は validate 以下の流れ |

- **型からの逸脱は指揮者の裁量**で、許可も事前申告も要らない。省略（リファレンス無しの案件は 2b を丸ごと飛ばす。「ボーカルを 1 dB 前へ」のような小さな依頼は 2a も飛ばし、曲資料から直接立案する）、軽量化（同じ曲の再指揮は前回の分析メモと outcome を読み直すだけで 1 を済ませる。2a は棚の題を見て 1 枚引くだけでよい）、順序変更（「この作品風」が依頼の中心なら 2b から入り、原液の問いを持って 1 に戻る）、深掘り（1 つの問いに `direction query` を重ね、他の節は 1 行で済ます）、往復（根拠が足りなければ 1・2 に戻る。check の結果を受けた次の指揮で調査をやり直す）のいずれもよい
- リファレンス無しの案件では型は「1 → 2a → 3」に縮み、従来と同じに動く。2a の省略・軽量化も不利にならない
- 最低限の目安（指揮者の規律であり、検査項目ではない）:
  1. **この曲の実素材に当たる。** どれだけ省いても、手を書く前に曲資料（または同等の `direction query`）でこの曲の測定を見る。記憶や一般論だけで手を書かない
  2. **リファレンスを根拠にするなら原液に当たる。** 〔参照〕と書く、`origin: reference` を付ける、`request.like` を受ける、のいずれかをするなら refstudy を実際に読む。無ければ利用者に持ち込みを求める
  3. **指定されたリファレンスを採らない場合も、読んでから決める。** 「この曲には移せない」は読んだ上での判断で、読まずに捨てる理由にしない
  4. **省いたことを隠さない。** 分析メモに、何を読み何を省いたかを 1〜2 行で書くことを勧める（書式なし・任意）
- **機械は段の実施を要求しない。** `direction validate`／`apply`／`check`／`--calibrate`、`kb lint` は、どの段が行われたか、どの順だったかを検査も採点も警告もしない。見るのは従来どおり出来上がった指揮書の形式・範囲・不変領域・主張だけ。段の実施を表す欄（実施済みフラグ、チェックリスト、段ごとの成果物 ID の必須化）は無く、段を順に進める道具も無い。`sources.cards`／`sources.references` は「使ったものの記録」で、空でも不足ではない

## 0. 道具

| コマンド | 役割 |
|---|---|
| `mankomix direction dossier --project <p> --song <slug> --out <md>` | 曲資料（決定論・読み取りのみ） |
| `mankomix direction validate [--project <p>] <direction.md>` | 形式・op・プロセッサ宣言範囲（範囲の両端）・不変領域・量の参照・評価段 E1〜E3。誤りがあれば終了コード 1 |
| `mankomix direction apply --project <p> [--calibrate] <direction.md>` | 床（適用済みミックス）に手を重ねる（`--calibrate`: 範囲内の量を主張の予測で選ぶ。§5）。`cleanup_override` → `clean plan --apply`、ミックスの手 → 1 本の `mxp_` 提案 → `plan apply`。`directions/` に凍結コピーと適用記録 `dir_<id>.apply.json`。マスター目標を返す |
| `mankomix direction check --project <p> --floor <floor> <direction.md>` | 描画結果を床とレベルマッチして比べる（主張・期待・ガード、`move_ref` の網羅、ゲート定義ハッシュの前後一致、床との同一収束）→ `directions/dir_<id>.outcome.json` |
| `mankomix direction query [--project <p>] <audio> <spec>` | 観察量（v2 の `analyze query` の最小版。既存の `analyze` の挙動を変えないため `direction` の下に置く） |
| `mankomix kb index／kb lint` | 蓄積庫 `kb/` の索引と検査 |
| `mankomix direction ref study --work <slug> [--master <audio>] [--stems <dir>] [--sections <json>] [--roles <json>] [--separate] [--kb <root>]` | リファレンス（原液）を測り、測定資料 refstudy を書く。work カードの雛形が無ければ作る（§6.1） |
| `mankomix direction ref compare --project <p> --work <slug> [--variant <v>] --out <md> [--kb <root>]` | 対照表 refsheet（参照とこちらを同じ定義で並べる。読み取りのみ。§6.1） |
| `mankomix direction ref credit --person <slug> [--kb <root>]` | 技術者カードの集計部を再生成（§6.1） |
| `mankomix direction ref list [--kb <root>]` | 作品・技術者の一覧と refstudy の鮮度 |
| `mankomix kb search [--kind K]... [--genre G]... [--text T] [--root <kb>]`／`kb show <id> [--root <kb>]` | カードの検索と表示（理論・作品・既存カード共通。読み取りのみ） |

`direction dossier` は `--ref <work_id>`（繰り返し可）と `--ref-kb <root>`（既定 `_private/kb`）を受け、曲資料 §10.3 に指定された作品カードの ID・題・refstudy のハッシュだけを載せる（§6.1）。

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
- **範囲内の較正（`direction apply --calibrate`）**: `select` の値を出発点に、範囲の内側だけで値を選び直す（範囲の無い数値は変えない）。床の写しに手を載せたミックスバスをメモリ上で描画し、床のミックスと LUFS-I を合わせて観察量（`target: master`）の差を予測する。候補は「未達の主張を expect に挙げる手を強い端へ」「全手を強い端へ」「自分の safeguard が不成立の手を無作用側へ」（強い端＝ゲイン 0 dB・幅 1・位置 0 から遠い側、大きいセンド・drive・mix・feedback、高い HPF／低い LPF。中心周波数・遅延時間など順序の無い量は動かさない）。測れる主張と safeguard のうち met のものは met のまま（余裕 0.02）、未達のものは目標から遠ざからない候補だけを受理し、主たる主張の met 数 → 主張の met 数 → safeguard の met 数 → 主たる主張の不足の小ささで選んで、得点が下がらない範囲で `select` からの段を縮める。主たる主張どうしを引き換えにはしない。全予測と選択は適用記録の `calibration` に、予測とマスター実測の対照は outcome の `calibration.prediction_vs_master` に残る。`cleanup_override` を含む指揮書は較正しない。ゲート・プロファイル・マスター連鎖には触れない
- **床への重ね方**: 床のミックス提案（`mix.applied.proposal_id`）の `changes` を出発点に、手が触れたトラックのチェーン・センドを丸ごと書いた `mxp_` 提案を作り、既存の `plan apply` で適用する。足した処理・センド・バスには `owner: director` と `move_ref: dir_<id>/<move>` が付く。量を変えた床の処理（`chain_param`）にも `move_ref` が付く。外した処理（`chain_remove`）とトラックのゲイン・パンは適用記録に残る。既に指揮書の手が入っているプロジェクトには適用しない（床の新しい写しに適用する）
- **区間ゲイン**: `gain` に `section` を付けると、区間の前後 20 ms のランプを持つゲインのオートメーションになる。同じトラックの区間が重なる・接する場合と、既にオートメーションがある場合は拒否する
- **バスのパン**: 新バス・既存バスへの `pan` は、バスのチェーン末尾に `pan`（position）と `stereo`（width）の処理を足す
- **観察量**: `target: master` だけ（`trk_*` は `unsupported`）。`level_match: true`（既定）なら結果の積分ラウドネスを床に揃えてから測る
- **主張の判定**: `up` は差 ≥ `min_delta`、`down` は差 ≤ −`min_delta`。`not_worse` は、台帳指標 `P-nn` では変種の評価の罰（目標範囲からの距離）の増分 ≤ `tolerance`、観察量では |差| ≤ `tolerance`（`worse: up|down` を付けると片側）。`P-nn` の値は変種の評価（マスター計画の目的関数の項）から読む。値がない項は `not_measured`
- **手ごとの期待・ガード**: v1 では手を分離せず、全体の結果で判定する（outcome にその旨を記す）
- **同一収束**: ミックス状態（トラックのゲイン・パン・チェーン・センド・オートメーションとバス）のハッシュ一致、または床とのレベルマッチ後の差分 RMS が −60 dB 未満なら `converged: true`
- **ゲート定義ハッシュ**: `knowledge/thresholds.json`、`knowledge/rules.json`、`knowledge/objective_metrics.json`、`knowledge/mix_rules.json`、`profiles/media_profiles.json` の SHA-256 を apply 時と check 時に取り、一致を確かめる

## 6. 追補: リファレンス（原液）と理論カード（2026-11-15）

本節は任意の材料の扱いを定める。**リファレンスも理論カードも必須ではなく、推奨経路でもない。** 使わない指揮書は従来どおりに動き、検査・警告・採点のどこでも不利に扱われない。目標カーブ・目標ベクトルへ自動で一致させる処理（マッチ EQ、参照値を目的関数にする較正、`match` 系の op）は作らない。

効き目についての注記: この経路の機構は自前の素材（公式サンプル、合成フィクスチャ）で確かめているだけで、プロの市販マスター・配布ステム（原液）での本番確認は**まだ行っていない**。「原液を読むと良くなる」ことは実証されていない。

### 6.1 二つのリファレンスと道具

| | 物差し（既存・不変） | 原液（指揮レイヤー） |
|---|---|---|
| 入口 | `mankomix reference add/list/remove` | `mankomix direction ref …` |
| 置き場 | プロジェクト内 `analysis/ref_<id>.json` | kb の `references/`（既定は非公開 `_private/kb/`） |
| 読み手 | コア（目的関数の目標分布。SPEC §4.6） | 指揮者だけ。コアは読まない |
| 床への影響 | あり（既存挙動） | なし。プロジェクトの `references` に書かない |
| 単位 | プロジェクトごとの曲 | 作品・技術者（案件をまたいで再利用） |

原液を取り込んでも物差しは自動登録されない。両方使うなら両方のコマンドを打つ。

- **`direction ref study`**: 持ち込まれたマスター（`--master`）とステムのフォルダ（`--stems`）をメモリ上で測り、`<kb>/references/works/<slug>/refstudy.md` を書く。音声の複製・変換物はどこにも残さない（`--separate` を有効にしたときだけ、分離ワーカーの入出力をシステムの一時フォルダに書き、終了時に消す）。測るのは既存の測定の再利用だけ（全体ベクトル、ラウドネスと動き、帯域の配分、空間、高域、区間、ステム単位の量とステム間の関係、ステムとマスターが両方あるときは和とマスターの差分）。
  - `--sections` は `[{"id": …, "start_s": …, "end_s": …}]` の JSON（インラインかファイル）。区間は 23 個まで、1 区間 1 秒以上。無ければ最大・最小の 3 秒区間（`loudest`／`quietest`）を自動区間にする（曲全体の区分は作らない）
  - ステムの役割はファイル名から既存の取り込み規則の語彙で割り当て、割り当てられないものは `other`。`--roles '{"<ファイル名>": "<役割>"}'` で直せる
  - `--separate`: 既存の分離経路が使える環境だけで、マスターを擬似ステムにする（`origin: separated`、確度の上限 medium）。使えなければ環境エラー（終了コード 3）。`--stems` とは併用できない
  - `--kb` の既定は `_private/kb`（第三者作品は非公開。kb/README の「第三者作品の置き場と公開止め」）。work カードが無いときだけ雛形（`rights: third_party`、`visibility: private`、`status: draft`、メタ情報は空欄）を作る。既存カードは書き換えず、カードの `study.sha256` と新しい refstudy が違えば JSON の `work_card_stale: true` で知らせる
- **`direction ref compare`**: refstudy とこちら（床、または `--variant` のマスター）を同じ定義で並べた refsheet を `--out` に書く（プロジェクトの外。プロジェクトも kb も書かない）。節はマスターどうし／ステムどうし（役割が両方にあるものだけ）／ステム間の関係どうし／移せない特徴（役割が片方にしかないもの）／高域の雑音性。列は「量／参照／こちら／差／比較条件」だけで、**「目標」「推奨」の列は無い**。こちらのステムは各トラックがバスに入る直前の音（整音 → 処理チェーン → フェーダー・オートメーション → パン・幅の後）を役割ごとに足したもので、センド戻り・バス処理・マスター段は含まない（それらはマスターどうしの表にだけ現れる）。比較条件にその旨が載る。整音の cache が無いか古いときはステムを比べない（プロジェクトを書かないため、先に clean apply／render する）。段は揃える（リファレンスのマスターはこちらのマスターと比べる）
- **`direction ref credit --person <slug>`**: work カードの `credits[].person` がその技術者の作品の refstudy から、各量の中央値・四分位範囲・n を集計し、技術者カードの集計部だけを再生成する。n < 3 は「傾向とは言えない（事例）」と機械表示する
- **`direction ref list`**: 作品（カードと refstudy の有無、鮮度）と技術者の一覧
- **`direction dossier --ref <work_id>`**: 曲資料は v2（`DOSSIER_VERSION` 2。見出し 12 本は不変）で、§10 が 10.1 経験（従来の抜粋）／10.2 理論の棚（`status: active` の理論カードの ID と題を全件、本文なし）／10.3 リファレンス（指定された作品の ID・題・refstudy の SHA-256 先頭 16 桁だけ）に分かれる。数値の対照は曲資料に入れず refsheet に分ける

### 6.2 ブロックの追加欄（任意）

`schema_version` は 1 のまま。追加欄の無い文書の validate／apply／check の結果は従来と同じで、既存の指揮書の `dir_` ID は変わらない。validate は**形式だけ**を検査し、ID が kb にあるかは見ない。空・無しでも警告しない。

| 欄 | 形 | validate の検査 |
|---|---|---|
| `request.like` | `["work_<slug>" \| "eng_<slug>", …]` | リストであること（`bad_value`）、各要素の形（`bad_ref`） |
| `sources.references` | `[{ "work": "work_<slug>", "study_sha256": "…", "refsheet_sha256": "…" }]` | `work` は必須。2 つの sha は省略・null 可で、書くなら英小文字 16 進 16〜64 桁。ほかのキーは `bad_value` |
| `moves[].origin` | `catalog`／`case`／`new` に `reference` を追加 | 値の列挙 |
| `moves[].basis` | `ref:work_<slug> §n` を書ける（§n は refstudy／refsheet の節） | `ref:` の直後に slug の文字（英数字・`_`・`-`）が続くときだけ検査し（`ref: …` のように空白が続く形や `ref:` 単独は検査しない）、それが `work_<slug>` でなければ `bad_ref`。`origin: reference` に `ref:` を必須にはしない |
| `observations[].ref_value` | 参照側の同じ観察量の値（数値か null）。参考 | 有限の数値か null（bool・文字列は `bad_value`） |

slug は英小文字・数字で始まり、英小文字・数字・`_`・`-` だけ。追加欄も不変領域の検査（§3）をそのまま受ける。

### 6.3 評価段・判定・較正

- **`origin: reference` の手は常に E2 以上**（E1 にならない）。他曲の事実は、この曲で効く保証ではないため。E1 は従来どおり `origin: catalog` で既存の範囲内と確認できる手だけ
- **理論カード（KT-nnnn）を `basis` に書いても E1 にはならない**（E1 を外すこともない）
- **`reference_distance` は判定外**: `direction check` は、数値の `ref_value` を持つ観察量ごとに `{ref_value, floor, result, change}`（`floor`＝|床 − ref_value|、`result`＝|結果 − ref_value|、`change`＝result − floor。負なら結果のほうが近い）を outcome の `reference_distance` に参考として出す。主張・期待・ガード・summary のどの判定にも入らない。数値の `ref_value` が 1 つも無い文書では欄が出ない（outcome は従来と同じ）
- **`direction apply --calibrate` は `ref_value` と `reference_distance` を読まない**。較正は従来どおり主張と safeguard だけを見る
- 理論カード・`sources.cards`・`sources.references`・`request.like` の有無や使用を validate／check／calibrate は見ず、未使用を警告しない

### 6.4 分析メモ: 凡例の追加と「リファレンスの読み」節

凡例に次を加える: `〔参照: work_<slug> §n〕` = refstudy／refsheet の値（数値は書き写し）、`〔理論: KT-nnnn〕` = 理論カード。

リファレンスを使う案件では、分析メモに「リファレンスの読み」節を置く（知見の節より前）。3 層で書く:

1. 〔参照〕測定と兆候の引用（数値は refstudy からの書き写し）
2. 〔推定〕その作品の意図・傾向の読み。**確度必須**
3. 〔不明〕2mix・配布ステムからは分からないこと（個別トラックの処理、使用機材、編集の経緯）。書かないのでなく「不明」と書く

確度の付け方:

| 確度 | 条件 |
|---|---|
| high | 直接の測定で、比較条件が揃っている（可逆音源、レベルマッチ済み、同じ段どうし） |
| medium | 独立な測定 2 つ以上が同じ向きの兆候 |
| low | 兆候 1 つだけ／分離で得た擬似ステム由来／非可逆音源の高域（おおむね 16 kHz 以上）／編成が大きく違う |

- **上限規則**: 非可逆音源は高域の結論を low に、分離由来は全て medium 以下に抑える。和とマスターの差分が「信頼できない」とされたときは差分の結論を low にする。refstudy の「§2 確度の上限（機械的付記）」と兆候の各行に上限が付き、指揮者はそれを超える確度を書けない（validate は検査しない。関門で人が見る）
- 道具が出すのは〔測定〕と〔兆候〕まで。作品の意図の読みは指揮者の〔推定〕
- 配布ステムは通常「処理済みの書き出し」で、見えるのは要素ごとの結果であり処理そのものではない

### 6.5 指揮者の規則（リファレンス）

| 規則 | 内容 |
|---|---|
| 持ち込みを求める | `request.like` の ID が kb に無い、または refstudy が無いときは、指揮者は利用者に音源の持ち込みを求める。道具は音源もクレジットも取得しに行かない |
| 記憶は原液ではない | モデルが覚えている「あの作品の音」は〔推定・記憶〕として仮説に使ってよいが、等級は hunch で、〔参照〕とは書けず、`origin: reference` にもできない |
| 原液が一次 | 両方の脚を踏むときは、理論カード・調査カードより refstudy／refsheet の読みを重く扱い、分析メモで前に置く。重みと配置の規則で、段の順序の強制ではない |
| 差は問い | 対照表の差を 1 つずつ問いにする（低域の量、主役のレベル、幅、ダイナミクス、帯域バランス）。「差があるから埋める」は根拠にならない |
| 翻訳して採る | 採る特徴は、この曲の素材でどう実現するかを手に翻訳し、主張は従来どおり**床に対して**立てる。採らなかった特徴は `rejected` に理由つきで残す |
| 距離は参考 | `reference_distance` は近づいたかを見る参考値。未達でも失敗でなく、近づいても成功でない。成否は主張と人の耳 |
| 不変領域が上 | リファレンスがプロファイルの天井・レンジ・ゲートを超えていても従わない。不変領域の検査は従来のまま |
| 無くても同じ | リファレンスが無い案件は従来と同じに動く。リファレンスは任意の材料で、必須経路にしない |
| 使わない自由 | リファレンスが指定されていても、「この曲には移せない」と判断して採らなくてよい（読んだ上で、理由を書く） |

SPEC §4.6 の「EQ マッチで写さない」「一度に比べる問いは 1 つ」は原液にもそのまま当てはまる。

### 6.6 資料が食い違うとき

読む順の基本形（問いの種類で決める）:

| 問い | 先に読むもの |
|---|---|
| 何を目指すか | 依頼の文言 → リファレンス原液（refstudy／refsheet）→ 過去の同種案件 |
| この曲で何が効くか | 曲資料の測定 → 同じ曲の outcome → lesson／move（replicated > measured）→ research（literature > practice > tip） |
| なぜそうなるか・どう呼ぶか | 理論カード、`knowledge/vocabulary.json` |
| してよいか | 不変領域・ゲート（知識ではない。何にも上書きされない） |

- 衝突は自動では解決しない。指揮者がどちらを採ったかを分析メモに両方の ID つきで書き、採らなかった側を `rejected` に残す
- 事実どうしが食い違うときの重みは「この曲の測定 > リファレンスの測定 > 他曲の実績カード > 文献・実務の調査カード > 理論カード > 記憶」。理論は説明の語彙で、実測に勝たない
- リファレンスの観察はカードの等級を動かさない。等級を動かすのは従来どおり outcome だけ
