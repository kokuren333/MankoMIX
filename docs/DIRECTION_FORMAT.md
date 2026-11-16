# 指揮書の形式（DIRECTION_FORMAT v1）

指揮レイヤー（`director/`、コアの外。コアは import しない）が扱う指揮書の契約。director（PM 層）が書き、`mankomix direction validate／apply／check` が機械で扱う。改築案 v2 の b.6／d.2／c.2 に準拠した最小版で、v2 の決裁（D-085〜／Q-29〜）を先取りしない。

**引き継ぎ書は指揮書と同一物である。** 「指揮書」は形式の名前（本書、`dir_` ID、`direction` ブロック）、「引き継ぎ書」は役割の名前（計画を終えた指揮者が、実行側と人へ判断を渡す文書）で、上位の文書は作らない。分析メモは根拠の記録（`ana_` ID）として引き継ぎ書に含めず、指揮書が `sources` で分析メモ・曲資料・カード・refstudy を指す。

### 計画フェーズの既定の型（既定であって手順ではない）

指揮者が 1 曲の指揮書を書くまでの進め方の既定。**型は手順でもゲートでもない。** 新しいコマンド・文書・欄は無く、既存の道具の並べ方の既定である。調査の脚（2a／2b）の詳細は調査プロトコル（`docs/RESEARCH_PROTOCOL.md`、2026-11-15、D-068）が正で、本節はその要約である。

| 段 | すること | 使う道具・資料 | 残る場所 |
|---|---|---|---|
| 1 分析 | 曲全体とステムを読む | 曲資料（`direction dossier`）、追加の `direction query`、トラック横断の下見 `direction stems observe／relate／purity`（§8.5） | 分析メモの曲の読み（〔測定〕〔推定〕） |
| 2a 調査・知見の脚 | Fable 5.2 が、依頼内容と段 1 の分析を入力に、5 層（論文／プロユース／アマチュア tips／解説動画／リファレンス作品。国内外問わず）で調査し、この曲の問いに効く知見を引く（調査プロトコル §2・§3） | 曲資料 §10.1 経験・§10.2 理論の棚、`kb search`／`kb show`（lesson／move／research／theory。公開 kb と蓄積 kb の両方）、案件ごとの調査ログ、カリキュラム（`kb show cur_<slug>`、`kb search --curriculum`。§7.5）、棚に無い問いの外部調査 | 分析メモの知見の節（調査→手・主張の対応つき）、調査ログ（蓄積 kb）、`sources.cards` |
| 2b 調査・リファレンスの脚 | 原液（持ち込まれたリファレンス）を測り、逆算する。ステムが存在しそうな作品は、非公式の配布経路も含めて所在を探す（調査プロトコル §3 層 5） | `direction ref study` → refstudy、`direction ref compare` → refsheet、work／engineer カード、輪郭とガイドの追加節（`ref study --add`／`ref compare --add`。§6.1）、work カードの `sources`・`observed_media`（§7.5） | 分析メモ「リファレンスの読み」（§6.4）、`sources.references` |
| 3 引き継ぎ書の立案 | 1・2 を受けて手と主張に落とす | 指揮書（散文 10 節＋ `direction` ブロック）。選べる手・観察の中に `edit_trim`／`edit_gate`（下見は `direction edit scan`）、`duck`、観察量の `view`、`check --translation`（§7）、`place`、`scene`、観察量 `image_position`／`masking`／`wet_ratio` とトラック対象（`trk_<stem>`、§8） | `dir_<id>`、以降は validate 以下の流れ |

- **型からの逸脱は指揮者の裁量**で、許可も事前申告も要らない。省略（リファレンス無しの案件は 2b を丸ごと飛ばす。「ボーカルを 1 dB 前へ」のような小さな依頼は 2a も飛ばし、曲資料から直接立案する）、軽量化（同じ曲の再指揮は前回の分析メモと outcome を読み直すだけで 1 を済ませる。2a は棚の題を見て 1 枚引くだけでよい）、順序変更（「この作品風」が依頼の中心なら 2b から入り、原液の問いを持って 1 に戻る）、深掘り（1 つの問いに `direction query` を重ね、他の節は 1 行で済ます）、往復（根拠が足りなければ 1・2 に戻る。check の結果を受けた次の指揮で調査をやり直す）のいずれもよい
- リファレンス無しの案件では型は「1 → 2a → 3」に縮み、従来と同じに動く。2a の省略・軽量化も不利にならない
- 最低限の目安（指揮者の規律であり、検査項目ではない）:
  1. **この曲の実素材に当たる。** どれだけ省いても、手を書く前に曲資料（または同等の `direction query`）でこの曲の測定を見る。記憶や一般論だけで手を書かない
  2. **リファレンスを根拠にするなら原液に当たる。** 〔参照〕と書く、`origin: reference` を付ける、`request.like` を受ける、のいずれかをするなら refstudy を実際に読む。無ければ利用者に持ち込みを求める
  3. **指定されたリファレンスを採らない場合も、読んでから決める。** 「この曲には移せない」は読んだ上での判断で、読まずに捨てる理由にしない
  4. **省いたことを隠さない。** 分析メモに、何を読み何を省いたかを 1〜2 行で書くことを勧める（書式なし・任意）
- **機械は段の実施を要求しない。** `direction validate`／`apply`／`check`／`--calibrate`、`kb lint` は、どの段が行われたか、どの順だったかを検査も採点も警告もしない。見るのは従来どおり出来上がった指揮書の形式・範囲・不変領域・主張だけ。段の実施を表す欄（実施済みフラグ、チェックリスト、段ごとの成果物 ID の必須化）は無く、段を順に進める道具も無い。`sources.cards`／`sources.references` は「使ったものの記録」で、空でも不足ではない
- **カリキュラムの位置（2026-11-15 追補 2）**: カリキュラム（束カード `cur_<slug>`）は 2a の入力の 1 つで、語彙と判断材料を供給する。読むか、どこまで読むか、どの順で読むかは指揮者の裁量。束の `order`／`level` は学ぶ順と難度で、ミックスの作業順・手の順・確認項目ではなく、指揮書の手の並びに写すものでもない。validate／apply／check／`--calibrate`／`kb lint` は、カリキュラムを読んだか、`sources.cards` に束のカードがあるかを見ない。束から引いたカードは他のカードと同じ重み（§6.6 の「理論カード」または「調査カード」）で、束に入っていることで重みは上がらない
- **調査と蓄積の置き場（2026-11-15、D-068）**: 調査の既定は調査プロトコル（`docs/RESEARCH_PROTOCOL.md`）。案件の記録（分析メモ・指揮書・outcome・調査ログ・蒸留カード）はローカルの蓄積 kb（`_private/kb/`、非コミット）に貯めるのが既定で、公開 kb（`kb/`）に入るのは既定のカードだけ。蓄積分を公開側へ移すのは、オーナーの判断による昇格（匿名化・一般化された原則のみ）に限る
- 追補 2 の手・観察・材料（§7）は、上の表の段を増やさず、既存の段の「使う道具・資料」に並ぶだけである。使わなくても不利にならない
- 追補 3 の手・観察・下見（§8）は段を増やさず、使わなくても不利にならない
- 追補 4 の文脈（§9.1）: 段 3 で手を選ぶときの「譲らせる順の目安」と、レビュー側の目安（指揮書を読む前に音を聴く）。どちらも既定の考え方で、手順でも検査項目でもない

## 0. 道具

| コマンド | 役割 |
|---|---|
| `mankomix direction dossier --project <p> --song <slug> --out <md>` | 曲資料（決定論・読み取りのみ） |
| `mankomix direction validate [--project <p>] <direction.md>` | 形式・op・プロセッサ宣言範囲（範囲の両端）・不変領域・量の参照・評価段 E1〜E3。誤りがあれば終了コード 1 |
| `mankomix direction apply --project <p> [--calibrate] <direction.md>` | 床（適用済みミックス）に手を重ねる（`--calibrate`: 範囲内の量を主張の予測で選ぶ。§5）。`cleanup_override` → `clean plan --apply`、ミックスの手 → 1 本の `mxp_` 提案 → `plan apply`。`directions/` に凍結コピーと適用記録 `dir_<id>.apply.json`。マスター目標を返す |
| `mankomix direction check --project <p> --floor <floor> [--translation] <direction.md>` | 描画結果を床とレベルマッチして比べる（主張・期待・ガード、`move_ref` の網羅、ゲート定義ハッシュの前後一致、床との同一収束）→ `directions/dir_<id>.outcome.json`（`--translation`: 判定外の `translation` ブロックを足す。§7.4） |
| `mankomix direction query [--project <p>] <audio> <spec>` | 観察量（v2 の `analyze query` の最小版。既存の `analyze` の挙動を変えないため `direction` の下に置く） |
| `mankomix kb index／kb lint` | 蓄積庫 `kb/` の索引と検査 |
| `mankomix direction ref study --work <slug> [--master <audio>] [--stems <dir>] [--sections <json>] [--roles <json>] [--separate] [--add transient] [--kb <root>]` | リファレンス（原液）を測り、測定資料 refstudy を書く。work カードの雛形が無ければ作る（§6.1。`--add` は §6.1 の追加節） |
| `mankomix direction ref compare --project <p> --work <slug> [--variant <v>] --out <md> [--add transient\|guide] [--kb <root>]` | 対照表 refsheet（参照とこちらを同じ定義で並べる。読み取りのみ。§6.1。`--add` は §6.1 の追加節） |
| `mankomix direction ref credit --person <slug> [--kb <root>]` | 技術者カードの集計部を再生成（§6.1） |
| `mankomix direction ref list [--kb <root>]` | 作品・技術者の一覧と refstudy の鮮度 |
| `mankomix kb search [--kind K]... [--genre G]... [--text T] [--source-type T]... [--curriculum cur_<slug>] [--root <kb>]`／`kb show <id> [--root <kb>]` | カードの検索と表示（理論・作品・既存カード共通。読み取りのみ） |
| `mankomix direction edit scan --project <p> --track <trk> --op edit_trim\|edit_gate [--params <json\|@file>] [--section <id\|json>]` | 編集 op が切る区間・拒否する区間（EG-1〜EG-5 の判定と測定値）・除くエネルギーを、適用と同じ関数で JSON に返す。何も書かない（§7.1） |
| `mankomix direction edit revert --project <p> --direction <dir_id> [--move <mid>]` | 編集段で無音化した区間とフェードを台帳 `dir_<id>.edits.json` から戻す（ジャーナル 1 エントリ。§7.1） |
| `mankomix direction stems observe --project <p> [--variant <v>] <spec>` | トラック対象・文脈の観察量（§8.1・§8.2）をプロジェクトの現状で測り、JSON（`kind: direction_stem_observations`）で返す。`<spec>` は観察量 1 つか配列（JSON か `@file`）。何も書かない（§8.5） |
| `mankomix direction stems relate --project <p> [--variant <v>] [--section <id\|json>] [--top <n>]` | 全トラック横断の被りの表（P-02 の埋もれ量、帯域別、上位の相手、P-22 の帯域の担当）を JSON（`kind: direction_stem_relate`）で返す。`--top` は既定 3、1〜8。何も書かない（§8.5） |
| `mankomix direction stems purity --project <p> [--track <trk>]...` | ステムの非純粋性（共有成分・焼き付いた残響・幅・動き・和の整合）を JSON（`kind: direction_stem_purity`）で返す。何も書かない（§8.5） |

`direction dossier` は `--ref <work_id>`（繰り返し可）と `--ref-kb <root>`（既定 `_private/kb`）を受け、曲資料 §10.3 に指定された作品カードの ID・題・refstudy のハッシュだけを載せる（§6.1）。

実行の流れ: 床の写し → `direction validate` → `direction apply` → `master plan --profile <p> [--target-lufs <t>] --apply` → `render` → `verify` → `gate` → `direction check` → kb に結果を収蔵（`kb index`、`kb lint`）。

編集 op（§7.1）を含む指揮書では、`direction apply` の内部で編集段が他の手（較正・整音の上書き・ミックス提案）より先に適用される。コマンドの並びは上と同じで、編集 op の無い指揮書では編集段は呼ばれない。

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
| `edit_trim` | edit | ステムの末尾（`side` により先頭・両端）の、内容が終わった後／始まる前を無音化する（追補 2。§7.1） | target, params |
| `edit_gate` | edit | ステム全体（または `section` の範囲）で、内容の無い区間を無音化する（オフラインのゲート。§7.1） | target, params |
| `duck` | mix | `params.key` のトラックが鳴る瞬間だけ、`target` のトラックをゲイン・オートメーションで下げる（§7.2） | target, params |
| `place` | mix | 方位と距離から、パン・フェーダー・高域・センドを同じ規則で導く（追補 3。既存の `pan`／`gain`／`chain_add`／`send` に展開される。§8.4） | target, params |

- `target` はトラック ID（`trk_<stem>`）、既存バス（`bus_reverb`、`bus_mix`）、新バス ID、または `master`
- `processor` と `params` は製品の抽象プロセッサ（`dsp/processors.py` の登録）とその宣言範囲に従う。範囲外は validate が拒否する
  - 帯域別の側成分倍率は実装済み（`stereo`。`chain_add` でトラック・バスに置ける）: `mono_below_hz`（これより下の側成分を除く）、`crossovers_hz`（側成分の帯域の境目。昇順、最大 8 個）、`widths`（帯域ごとの側成分倍率 0〜2。個数は境目の数 + 1）。中央成分 M は触らない
  - 例: `"processor": "stereo", "params": { "mono_below_hz": 120, "crossovers_hz": [4000], "widths": [1.0, 1.1] }`
  - 配列のパラメータ（`crossovers_hz`、`widths`）は範囲 `[下限, 上限]` で書けない。2 要素でも配列のまま渡り、較正の対象にもならない。中央成分だけ・側成分だけへの動的処理は無い（欲しい場合は `tool_requests`）
- **量は範囲で書ける**: 数値の代わりに `[下限, 上限]`。`select` で選び方を指定する: `mid`（既定）／`min`／`max`／`sweep:<量>`（Opus 層が乾式で掃引し、`<量>` が最良のものを採る。例 `sweep:S-08_margin`）
- `section`: `null`（全体）か、曲資料のセクション ID／`{"t0_s":…, "t1_s":…}`。**区間限定にできるのは `gain`（オートメーション化）だけ。**（追補 2 の `edit_trim`／`edit_gate` も `section` を書ける。検出範囲の限定で、§7.1） それ以外を区間限定したい場合は `tool_requests` に書く（レンダラーに区間ごとの処理切替がない）
- **時間で変わるパン（オートパン、パンのオートメーション）は現行のレンダラーにない。** 欲しい場合は `tool_requests` に書き、静的な配置・幅・ディレイ（`route: left|right`）・複数のリバーブバスで代替する
- `expect`／`safeguard`／`claims` の `quantity`: 台帳指標 `P-nn`（曲資料に値があるもの。限定子つき `P-nn:<qualifier>`、例 `P-02:vs_lead` も可。check は限定子つきの項が無ければ `P-nn` の項を読む）か、`obs:<observations の id>`
- `direction`: `up`／`down`／`not_worse`。`not_worse` は `tolerance` を持つ
- 全手に `aim`、`basis`、`origin` が必須

### 編集 op と `duck` のパラメータ（追補 2）

`params` に下表以外のキーがあれば `bad_value`。数値は範囲 `[下限, 上限]`＋`select` でも書ける（`duck` は表で「範囲可」のものだけ）。省略したキーは「省略時」の値になる。編集 op の `params` が空（`{}`）だと `missing_field` なので、全部を省略時の値で使うときも 1 キーは書く。

| op | ID | 単位 | 範囲 | 省略時 | 意味 |
|---|---|---|---|---|---|
| 編集 2 種 | `threshold_db` | dB（トラックの活動レベル比） | −72〜−36 | −60 | これを下回るフレームを「内容なし」の候補にする |
| 編集 2 種 | `hold_ms` | ms | 50〜2000 | 400 | 内容が閾値を下回ってから、この時間は切らない（減衰の保護） |
| 編集 2 種 | `fade_ms` | ms | 2〜200 | 20 | 切り口のフェード長（残す側のクリップ内に置く） |
| `edit_trim` | `side` | 列挙 | `tail`／`head`／`both` | `tail` | どちらの端を切るか |
| `edit_gate` | `lead_ms` | ms | 0〜100 | 10 | 内容が始まる前に開けておく時間 |
| `edit_gate` | `min_gap_ms` | ms | 200〜10000 | 1000 | これより短い無内容区間は切らない |
| `duck` | `key` | トラック ID | `target` と別の `trk_<stem>` | （必須） | 引き金にするトラック。バス・`master` は `bad_target`、無いトラックは `unknown_target` |
| `duck` | `depth_db` | dB | 0.5〜6.0（範囲可） | 2.0 | 打点での下げ幅（正の値で書く） |
| `duck` | `key_lo_hz` | Hz | 20〜2000 | 40 | キーの検出帯域の下端 |
| `duck` | `key_hi_hz` | Hz | 60〜12000、かつ `key_lo_hz` の 1.5 倍以上 | 120 | 同・上端。上下端は 2 つの別キーで書く（配列にしない） |
| `duck` | `trigger_below_p95_db` | dB | 3〜24（範囲可） | 床の `ducking.trigger_db_below_p95` | キー帯域包絡の 95 パーセンタイルからこの分だけ下を引き金の閾値にする |
| `duck` | `attack_ms` | ms | 1〜30（範囲可） | 床の `ducking.attack_ms` | 打点の手前から下げ始める時間 |
| `duck` | `release_note` | 列挙 | 音価（`none` 以外） | BPM があれば床の `ducking.release_note_default` | 回復に掛ける音価（R-11） |
| `duck` | `release_ms` | ms | 30〜600（範囲可） | BPM が無いとき床の `ducking.release_ms_without_bpm` | 回復時間を ms で書く場合 |
| `duck` | `min_interval_ms` | ms | 30〜500 | 床の `ducking.min_interval_ms` | 打点の最小間隔 |

- 「床の `ducking.…`」は `knowledge/mix_rules.json` の値を読み取りだけで使う（書き込まない）
- 編集 op の `target` はトラック ID だけ（バス・`master` は `bad_target`）。`duck` の `target` もトラック ID だけで、`section` は書けない（`section_scope`）
- `release_note` と `release_ms` は同時に書けない（`bad_value`）。`release_note` を書いたのに床の提案に `tempo.bpm` が無いときは、`--project` つきの validate と apply が `needs_bpm` で拒否する（`--project` 無しの validate はテンポを知らないので出さない）
- 範囲外は `param_range`、未知キー・形の誤り（`key_lo_hz` を配列で書く、未知の音価など）は `bad_value`

### `place` のパラメータ（追補 3）

`params` に下表以外のキーがあれば `bad_value`。「範囲可」のものは `[下限, 上限]`＋`select` で書ける（それ以外に範囲を書くと `bad_value`）。導出と注記は §8.4。

| ID | 単位 | 範囲 | 省略時 | 意味 |
|---|---|---|---|---|
| `azimuth` | −1..1 | −1〜1（範囲可） | （触らない） | パン位置（`pan.position` と同じ座標。＋が右） |
| `width` | 倍 | 0〜2（範囲可） | （触らない） | ステレオ素材の側成分倍率 |
| `distance` | 倍 | 1.0〜8.0（範囲可） | （距離の手がかりを付けない） | 基準（最前）からの相対距離。1.0 は変化なし |
| `room` | バス ID | 既存のバス、または同じ指揮書の `bus_add` の ID | （センドを作らない） | 残響を返すバス。`distance` が無ければ書けない |
| `level_db_per_doubling` | dB | 0〜6 | 2.0 | 距離 2 倍ごとに下げるレベル |
| `air_db_per_doubling` | dB | 0〜3 | 1.0 | 距離 2 倍ごとに下げる高域（ハイシェルフ） |
| `air_freq_hz` | Hz | 2000〜10000 | 5000 | ハイシェルフの角周波数 |
| `near_send_db` | dB | −40〜−12 | −24 | 距離 1.0 のときのセンド量 |
| `send_db_per_doubling` | dB | 0〜6 | 4.0 | 距離 2 倍ごとに上げるセンド量 |

- `target` はトラック ID だけ（`master`・バス・同じ指揮書の `bus_add` の ID は `bad_target`。`--project` つきで無いトラックは `unknown_target`）。`section` は書けない（`section_scope`）
- `azimuth`／`width`／`distance` が 1 つも無ければ `missing_field`。`room` を `distance` 無しで書くと `missing_field`（`moves.<id>.room`）、`bus_` で始まる文字列でなければ `bad_value`、`--project` つきで既存バスにも同じ指揮書の `bus_add` にも無ければ `unknown_target`
- 範囲外は `param_range`、数でない値（bool を含む）は `bad_value`（where は `moves.<id>.<キー>`）。同じトラックへの手の衝突は `conflict`（§8.4）

### observations（観察量。ゲートには入らない）

| primitive | 意味 | 欄 |
|---|---|---|
| `band_energy` | 帯域のエネルギー（dB） | band_hz |
| `band_ratio` | 帯域 A の B に対する比（dB） | band_hz, ref_band_hz |
| `crest` | クレストファクター（dB）。帯域指定可 | band_hz（任意） |
| `loudness` | 短期／積分ラウドネス（LUFS） | stat: `integrated`／`short_p95` 等 |
| `side_ratio` | 側成分 S の中央成分 M に対する比（dB）。帯域指定可 | band_hz（任意） |
| `correlation` | L/R 相関係数 | band_hz（任意） |
| `image_position` | 左右のエネルギーの比 `(E_R − E_L) / (E_R + E_L)`（−1〜+1、＋が右。追補 3。§8.2） | band_hz（任意） |
| `masking` | P-02 のモデルによる埋もれ量（dB、0 以上）。対象は `trk_*` か `"all"` だけ（追補 3。§8.2） | against（任意）、band_hz（任意） |
| `wet_ratio` | センド経由の音とセンド無しの音のエネルギー比（dB、下限 −120.0）。対象は `trk_*` だけ（追補 3。§8.2） | band_hz（任意） |

- `target`: `master`（描画済みマスター）か `trk_<stem>`（ミックス段の当該トラックの信号。追補 3 で対応済み。経路 `path` で測る段を選び、**レベルマッチはしない**。§8.1）。`masking` は `"all"` も受ける。それ以外の値（バス ID など）は validate が従来どおり `unsupported` と警告する（`image_position` はその警告に加えてエラー `bad_target`、`masking`／`wet_ratio` は警告の代わりにエラー `bad_target`）
- `path`（任意。追補 3）: トラック対象だけに書ける。`dry`（省略時。バスに入る直前の音）／`solo`（そのトラックだけを鳴らしたミックスバス出力）。`master` 対象に書く、未知の値、`masking`／`wet_ratio` に書く、のいずれも `bad_value`（§8.1）
- `section`: `all` か セクション ID か `{"t0_s","t1_s"}`
- `level_match`: true なら床と比べる前に積分ラウドネスを揃える（R-01）
- `view`（任意。追補 2）: 測る前の見方。無し／`stereo` は従来どおり（値も同じ）。`mono` は `(L+R)/2` を両チャンネルに置いてから測る。`mono_band` は `mono` の後に帯域通過（4 次・ゼロ位相）してから測る。帯域は省略時 150〜6000 Hz で、`view_band_hz: [lo, hi]`（lo 80〜400、hi 3000〜10000）で変えられる。小さなモノ再生での残り方を見るための見方で、ゲートには入らない
- `view` が `mono`／`mono_band` のときの `side_ratio`／`correlation`／`image_position`（追補 3。モノに側成分・左右差は無い）、`masking`／`wet_ratio` に書いた `view`・`view_band_hz`（追補 3）、未知の `view`、`mono_band` 以外と一緒に書いた `view_band_hz`、範囲外・形の悪い `view_band_hz` は、validate（`observations.<id>.view`／`.view_band_hz`）も `direction query` も同じ規則で `bad_value`。`view` を書かない観察量は従来どおりに検査・測定される

### 不変領域（validate が機械的に拒否する。v2 f.2）

ブロックのどこにも次を書けない: S-01〜S-11 の閾値・許容、`plan_margin_db`、プロファイルの天井・レンジ・納品形式の変更、R-14 の GR 上限、P-18 の閾値、OF-5、マスター段の順序・ディザ・リミッター（`limiter`、`clipper`、`dither`、`resample` を `stage: master` で使う手、`master` を target にした `chain_add`）、受理のデッドバンドとガード項、`knowledge/`・`profiles/` への書き込み。`target_lufs` はプロファイルのレンジ外を拒否する。

## 4. 評価段（validate が付ける。自己申告させない）

- E1: `origin: catalog` で、量が `knowledge/mix_rules.json` 等の既存の範囲内と確認できる手
- E2: それ以外（`new`、範囲外、`case`）。全長の評価とガード項の前後比較を `direction check` で行う
- E3: マスター段でプロファイルの既定（R-06、R-15）を超える手、主役（`trk_vocals`）への時間変化する処理。E2 に加え `listen_for` への登録が必須（無ければ validate が警告）
- `place`（追補 3）は常に E2 以上（`origin: catalog`＋R-nn でも E1 にならない）。静的な手なので、主役への `place` も E2 のまま

## 5. v1 実装の注記（validate／apply／check が実際にすること）

- **範囲と select**: 範囲 `[下限, 上限]` は両端とも宣言範囲内であることを validate が確かめる。apply は `mid`／`min`／`max` で値を選ぶ。`sweep:<量>` は v1 では未実装で、範囲の中央を使い、適用記録の `notes` に残す
- **範囲内の較正（`direction apply --calibrate`）**: `select` の値を出発点に、範囲の内側だけで値を選び直す（範囲の無い数値は変えない）。床の写しに手を載せたミックスバスをメモリ上で描画し、床のミックスと LUFS-I を合わせて観察量（`target: master`）の差を予測する。候補は「未達の主張を expect に挙げる手を強い端へ」「全手を強い端へ」「自分の safeguard が不成立の手を無作用側へ」（強い端＝ゲイン 0 dB・幅 1・位置 0 から遠い側、大きいセンド・drive・mix・feedback、高い HPF／低い LPF。中心周波数・遅延時間など順序の無い量は動かさない）。測れる主張と safeguard のうち met のものは met のまま（余裕 0.02）、未達のものは目標から遠ざからない候補だけを受理し、主たる主張の met 数 → 主張の met 数 → safeguard の met 数 → 主たる主張の不足の小ささで選んで、得点が下がらない範囲で `select` からの段を縮める。主たる主張どうしを引き換えにはしない。全予測と選択は適用記録の `calibration` に、予測とマスター実測の対照は outcome の `calibration.prediction_vs_master` に残る。`cleanup_override` を含む指揮書は較正しない。ゲート・プロファイル・マスター連鎖には触れない
- **床への重ね方**: 床のミックス提案（`mix.applied.proposal_id`）の `changes` を出発点に、手が触れたトラックのチェーン・センドを丸ごと書いた `mxp_` 提案を作り、既存の `plan apply` で適用する。足した処理・センド・バスには `owner: director` と `move_ref: dir_<id>/<move>` が付く。量を変えた床の処理（`chain_param`）にも `move_ref` が付く。外した処理（`chain_remove`）とトラックのゲイン・パンは適用記録に残る。既に指揮書の手が入っているプロジェクトには適用しない（床の新しい写しに適用する）
- **区間ゲイン**: `gain` に `section` を付けると、区間の前後 20 ms のランプを持つゲインのオートメーションになる。同じトラックの区間が重なる・接する場合と、既にオートメーションがある場合は拒否する
- **バスのパン**: 新バス・既存バスへの `pan` は、バスのチェーン末尾に `pan`（position）と `stereo`（width）の処理を足す
- **観察量**: `target: master` は、`level_match: true`（既定）なら結果の積分ラウドネスを床に揃えてから測る。`target: trk_<stem>` と `masking`／`wet_ratio`（追補 3）は、床と結果のプロジェクトからトラックの信号をメモリ上で描画して測り、`level_match` の値に関わらずゲイン 0 で測る（§8.1）。`direction query`（音声ファイル 1 本）は従来どおり `master` だけで、`trk_*` は `unsupported`
- **主張の判定**: `up` は差 ≥ `min_delta`、`down` は差 ≤ −`min_delta`。`not_worse` は、台帳指標 `P-nn` では変種の評価の罰（目標範囲からの距離）の増分 ≤ `tolerance`、観察量では |差| ≤ `tolerance`（`worse: up|down` を付けると片側）。`P-nn` の値は変種の評価（マスター計画の目的関数の項）から読む。値がない項は `not_measured`
- **手ごとの期待・ガード**: v1 では手を分離せず、全体の結果で判定する（outcome にその旨を記す）
- **同一収束**: ミックス状態（トラックのゲイン・パン・チェーン・センド・オートメーションとバス）のハッシュ一致、または床とのレベルマッチ後の差分 RMS が −60 dB 未満なら `converged: true`
- **ゲート定義ハッシュ**: `knowledge/thresholds.json`、`knowledge/rules.json`、`knowledge/objective_metrics.json`、`knowledge/mix_rules.json`、`profiles/media_profiles.json` の SHA-256 を apply 時と check 時に取り、一致を確かめる
- **追補 2 の注記**（新しい手を含まない指揮書では、以下はどれも働かず、validate・適用記録・ミックス提案・outcome は従来とバイト同一。どの手を使ったか・どの順かは検査しない）:
  - 適用の内部の順: validate → 既存の拒否条件（指揮書の手が入り済み、適用済み）→ 編集段（区間の計画 → safeguard → ミュートとフェード → 台帳。§7.1）→ プロジェクトの読み直し → 較正（`--calibrate`）→ 凍結コピー → 整音の上書き → ミックス提案。編集 op が無ければ編集段は丸ごと飛ばされる
  - 較正: 編集 op のパラメータと配列のパラメータ（`crossovers_hz`、`widths`）は較正の対象にしない。編集 op があっても較正は止まらない（止まるのは従来どおり `cleanup_override` のとき）。強い端に「`duck` の `depth_db` は上限側」が加わる（`duck` の他のパラメータは順序の無い量として動かさない）
  - 区間ゲインとオートメーション: `duck` のある対象トラックでは、床のオートメーション・同じ指揮書の区間ゲイン・`duck` を合成して 1 本にする（§7.2）。`duck` の無いトラックで区間ゲインが既存のオートメーションに当たったときは、従来どおり拒否する
  - 同一収束: ミックス状態のハッシュにクリップ（`clips`）を含める（編集だけの指揮書が床と同一と判定されないため）。床と写しのクリップが同じ案件の判定は変わらない
  - `move_ref` の網羅: `duck` は合成したオートメーションの `move_ref`（関わった手の ID の配列）で追う。打点 0 件の `duck` は適用記録で追う。編集 op は適用記録と台帳で追う
- **追補 3 の注記**（§8。新しい手・欄・観察量を含まない指揮書では、以下はどれも働かず、validate・適用記録・ミックス提案・outcome は従来とバイト同一。例外は §8.6 の警告 1 種だけ。どれを使ったか・どの順かは検査しない）:
  - 較正（`--calibrate`）が読まないもの: トラック対象の観察量、`masking`／`wet_ratio`（主張・safeguard から参照されていても予測しない）、`place` のパラメータ（`select` の値のまま使う）、outcome の `scene` ブロック。`target: master` の `image_position` は他の `master` の観察量と同じに読む
  - `place` の展開: validate は展開後の各手にも既存の範囲検査を掛ける（範囲で書いた場合は両端）。apply は `place` を `pan` → `gain` → `chain_add`（`eq` のハイシェルフ）→ `send` に展開して既存の経路へ流し、足した処理とセンドの `move_ref` は元の `place` の手の ID になる。適用記録には展開前の `place` が 1 件として残る（§8.4）
  - check のトラック信号: トラック対象か `masking`／`wet_ratio` の観察量、または `scene` があるときだけ床と結果の両方を描画する（プロジェクトには書かない）。どれも無い指揮書では描画しない
  - `scene` ブロックは判定外: 主張・期待・ガード・`summary`・`move_ref`・`--calibrate` のどれも読まない（§8.3）
  - 警告 `unmeasured_quantity`（§8.6）: 主張・期待・安全弁に台帳指標（`P-nn`）の量を書いた指揮書では、`--project` の有無に依らず量ごとに 1 件出る（文は 2 種）。警告であり `ok` と終了コードは変わらない。既存の指揮書でも `P-nn` の量を書いていれば出る
  - 記録: SPEC §8.2 の表にある「GUI のミックスマップの座標系（§11.3）」の参照は §11.2（画面）を指すのが正しい。SPEC は今回変えない

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
- **`--add`（追補 2。付けたときだけ働く）**: `ref study --add transient`、`ref compare --add transient`／`--add guide`（繰り返し可）。付けないときの refstudy・refsheet は従来とバイト同一（`REFSTUDY_VERSION` は 1 のまま）。既存の work カードの `study.sha256` は書き換えず、違えば従来どおり `work_card_stale` で知らせる。追加節も粒度の上限（kb/README）の内側で、フレーム列は出さない。使わなくても不利にならず、validate／check／`--calibrate` は追加節の有無を見ない
  - `ref study --add transient`: 冒頭の測定条件に `- 追加: transient`、既存の節の後ろに「## 8. トランジェント輪郭」を足す（マスターだけを測る）。8.1 区間別・帯域別クレスト（`whole`＋各区間。区間は `--sections`、無ければ自動の最大・最小の 2 区間。帯域は sub 20–60／bass 60–250／lowmid 250–500／mid 500–2000／highmid 2000–6000／air 6000–20000 Hz、dB 小数 2 桁）。8.2 アタック密度（モノ和を low 20–250／mid 250–2000／high 2000–20000 Hz の 3 群に帯域通過し、各群のオンセット強度から局所平均 0.4 秒を引いて曲全体の標準偏差で割った値が 1.5 以上の極大を、間隔 50 ms 以上でアタックと数える。区間内の数 ÷ 秒、1/s）と、BPM の確度が 0.5 以上のときの拍あたりの低域アタック（全体のみ）。8.3 輪郭の兆候
  - アタック密度の読み方（節に固定文で出る）: 曲全体の平均二乗が最大の群より `ATTACK_GROUP_FLOOR_DB`（40 dB）以上低い群は数えず「—」にする。密度は群ごとに正規化した相対の指標で、打点の実数ではない。打点の乏しい群では定常音・残響・雑音の揺らぎも数に入り、low 群では持続する低音のうねりも数に入る。群どうしの大小は比べず、同じ群の区間どうし・版どうしで読む。節の頭にはもう 1 つの固定文「クレストは最終段の抑え込みを含んだ結果で、ミックス段の立ち上がりそのものではない。読みは指揮者の〔推定〕」が出る
  - 輪郭の兆候（既存の兆候と同じ行の形）: RS-TR-BAND（全体の帯域別クレストのうち sub を除く 5 帯域の最大−最小が 6 dB 以上。どの帯域の立ち上がりが残り（14 dB 以上）、どの帯域がならされているか（8 dB 以下）。確度 high）、RS-TR-SECTION（LUFS-I の最大区間と最小区間で、bass 帯域のクレスト差 3 dB 以上、または low 群のアタック密度の比 1.5 倍以上。両方で medium、片方で low。low 群が「—」なら密度の比なしで判定）、RS-TR-DENSITY（BPM の確度 0.5 以上で、低域のアタックは 1 拍あたり何個か。medium。low 群が「—」のときは立たず、所見は「low 群は測定対象外（最大の群より 40 dB 以上低い）」）。所見は意図を言わない
  - `ref compare --add transient`: 節「トランジェント輪郭の対照」。全体の帯域別クレスト 6 行とアタック密度 3 行を、参照（refstudy の §8 の書き写し）とこちら（マスターを同じ関数で測る）で並べる。参照の refstudy に §8 が無ければ「参照側は未測定（`ref study --add transient`）」と書いてこちらの値だけを出す。どちらかが「—」なら差も「—」
  - `ref compare --add guide`: 節「汎用ガイドからの形の偏差」。出どころは `knowledge/thresholds_m3.json` の `p01_generic_prior`（読み取りのみ）で、節の頭に固定文「ジャンル固有の目標カーブは同梱していない。汎用ガイドは目標ではない。偏差は性格の記述で、0 に近いほど良いわけではない」が出る。定義は両者同じで、レベルマッチ済み LTAS の 6 帯域平均からガイドの同じ 6 帯域平均を引き、lowmid・mid・highmid の中央値を引いて形だけにする（6 行、dB）。プロジェクトに物差し（`reference add` の参照群）が登録されていれば、その分布の中央値からの偏差をこちら側だけ 6 行足し、無ければ「物差しは未登録」と 1 行
  - 追加節の列は従来の「量／参照／こちら／差／比較条件」のままで、追加節の番号は付けた種類の数で詰まる（transient → guide の順）。冒頭に `- 追加: …` の行が出る。CLI の JSON には、付けたときだけ `add`（refstudy は加えて `transient_signs`）が出る

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
- **`translation` は判定外（追補 2）**: `direction check --translation` が outcome に足す `translation` ブロック（§7.4）は、主張・期待・ガード・summary・ゲートのどの判定にも入らない。フラグ無しの outcome は従来とバイト同一
- **輪郭・ガイドの追加節と `translation` を `--calibrate` は読まない**。`ref_value` と同じく、較正は主張と safeguard だけを見る。追加節・`translation` を使わなくても不利にならない

### 6.4 分析メモ: 凡例の追加と「リファレンスの読み」節

凡例に次を加える: `〔参照: work_<slug> §n〕` = refstudy／refsheet の値（数値は書き写し）、`〔理論: KT-nnnn〕` = 理論カード。追補 2 で `〔観察: work_<slug> 観察 n〕` = work カードの `observed_media` の n 番目（プロセスメディアの観察。下の規則）を加える。

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
- **輪郭の上限（追補 2）**: 輪郭の兆候にも同じ上限規則が掛かる。非可逆音源では air 帯域が所見に関わる RS-TR-BAND を low に、分離由来は輪郭の兆候を全て medium 以下に抑える
- **観察は確度を上げない（追補 2）**: 〔観察〕は意図推定の材料（何を見るか、どの順で判断されたと読むか）に限り、〔参照〕〔測定〕とは書かない。確度は測定だけが決める。観察だけに立つ〔推定〕は low で、観察＋兆候 1 つも low のまま（「独立な測定 2 つ以上で medium」の 2 つに観察を数えない）。観察を根拠に `origin: reference` の手を書くなら refstudy を読んでいること（目安 2）。観察だけなら `origin: new`／`case`。機械は検査しない（関門で人が見る）。観察を書かない分析メモも不利にならない
- 道具が出すのは〔測定〕と〔兆候〕まで。作品の意図の読みは指揮者の〔推定〕
- 配布ステムは通常「処理済みの書き出し」で、見えるのは要素ごとの結果であり処理そのものではない

### 6.5 指揮者の規則（リファレンス）

| 規則 | 内容 |
|---|---|
| 持ち込みを求める | `request.like` の ID が kb に無い、または refstudy が無いときは、指揮者は利用者に音源の持ち込みを求める。道具は音源もクレジットも取得しに行かない。何を探せばよいかを伝えるときの経路は KT-0023 の 4 種（公募・コンテストの配布素材、公開物の説明欄で案内される素材、権利者が公式に配るステム、制作過程を見せるメディア）で、集まった素材の所在と権利注記は work カードの `sources` に残せる（追補 2） |
| 記憶は原液ではない | モデルが覚えている「あの作品の音」は〔推定・記憶〕として仮説に使ってよいが、等級は hunch で、〔参照〕とは書けず、`origin: reference` にもできない |
| 原液が一次 | 両方の脚を踏むときは、理論カード・調査カードより refstudy／refsheet の読みを重く扱い、分析メモで前に置く。重みと配置の規則で、段の順序の強制ではない |
| 差は問い | 対照表の差を 1 つずつ問いにする（低域の量、主役のレベル、幅、ダイナミクス、帯域バランス）。「差があるから埋める」は根拠にならない。輪郭・ガイドの追加節の差・偏差も同じ扱い（追補 2） |
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
| 良し悪しの問い（どちらが良いか・採るか）（追補 4） | 聴いた結果（聴取記録。§9 の後の節）→ 依頼の文言 → 測定は状態の説明として（§9.1） |

- 衝突は自動では解決しない。指揮者がどちらを採ったかを分析メモに両方の ID つきで書き、採らなかった側を `rejected` に残す
- 事実どうしが食い違うときの重みは「この曲の測定 > リファレンスの測定 > 他曲の実績カード > 文献・実務の調査カード > プロセスメディアの観察（追補 2） > 理論カード > 記憶」。同じ作品について測定と観察が食い違えば測定を採る。理論は説明の語彙で、実測に勝たない
- リファレンスの観察はカードの等級を動かさない。等級を動かすのは従来どおり outcome だけ

## 7. 追補 2: 編集段・ダッキング・輪郭と翻訳の観察・kb の任意欄（2026-11-15）

本節の手・観察・欄は、どれも指揮者が選べるもので、**使わなくても不利にならない**。validate／apply／check／`--calibrate`／`kb lint` は、これらの使用の有無・順序・回数を検査も採点も警告もしない。見るのは書かれたものの形式・範囲・安全（下の EG-1〜EG-5、§3 のパラメータ範囲、不変領域）だけ。使わない指揮書・カード・コマンドの出力は従来とバイト同一で、`schema_version` は 1 のまま、既存の指揮書の `dir_` ID も変わらない。新しい op・欄・フラグは誰が書いても同じに動き、担い手（指揮者・実行層・レビュワー・統括）による分岐は無い。

効き目についての注記: 機構は自前の素材（公式サンプル、合成フィクスチャ）で確かめているだけで、編集・ダッキング・翻訳観察が音を良くすることは実証していない。

### 7.1 編集段（`edit_trim`／`edit_gate`）

ステムに残る「曲でない部分」（演奏が終わった後の雑音、フレーズ間の漏れ）を、チェーンやセンドが増幅する前に無音化する手。床には入らない。パラメータは §3。

- **段の位置（U-19）**: stage 名は `edit`。決定・適用・記録の順は `edit → clean → mix → master`。検出と safeguard は**整音前の原素材**（トラックの `cleanup` を外したメモリ上の写しで、クリップ配置後・チェーン前・フェーダー前の信号）で行い、同じ指揮書の `cleanup_override` の有無で検出結果は変わらない。無音化はクリップの区間ミュート（整音済み素材の上）で、整音器は素材の全長を見続ける（整音キャッシュ・計画ハッシュ・S-07／S-08 の基準は編集で動かない）。原素材と整音キャッシュは書き換えず、音声ファイルも書かない
- **検出（固定。指揮書から変えられない）**: フレーム窓 50 ms、ホップ 10 ms、フレームレベルは L/R の二乗平均の平均の dBFS。活動レベル `active_db` は −70 dBFS を超えるフレームの 95 パーセンタイル（該当なしは無音のトラックとして区間 0 件）。内容フレーム = `active_db + threshold_db` 以上
  - `edit_gate`: 内容フレームの連なりを前へ `lead_ms`、後ろへ `hold_ms` 広げて結合し、その補集合（先頭・末尾を含む）のうち `min_gap_ms` 以上を候補にする
  - `edit_trim`: `tail` は最後の内容フレームの終わり＋`hold_ms` から末尾まで、`head` は先頭から最初の内容フレームの始まり −20 ms まで。100 ms 未満の候補は捨てる
  - 候補は `section`（あれば）と、ミュートされていないクリップの範囲との交差に限る。交差の後も最小長をもう一度当てる。端はサンプルに丸める
- **safeguard（U-20。固定値。緩める・外すキーは無い）**: 候補区間ごとに、区間と前後の `fade_ms` の範囲に窓が収まるフレーム（1 枚も収まらない短い範囲だけ、重なるフレーム）で判定し、当たった区間は「音楽的内容を含む」として切らない

| ID | 測るもの | 拒否の条件 |
|---|---|---|
| EG-1 相対レベル | 区間内の最大フレームレベル − `active_db` | −36 dB を超える |
| EG-2 絶対レベル | 区間内の最大フレームレベル | −40 dBFS を超える |
| EG-3 音程成分 | 最大フレームレベルが −60 dBFS を超える区間の、モノ和の平均化パワースペクトル（200 Hz〜8 kHz）の平坦度 | 0.10 未満（音程のある持続音・残響の尾とみなす）。判定範囲が 4096 サンプルに満たず −60 dBFS を超える区間も拒否 |
| EG-4 総量 | 受理した全区間のエネルギーの和 ÷ トラック全体のエネルギー | −40 dB を超える間、エネルギーの大きい区間から受理を取り消す |
| EG-5 断片化 | 1 手あたりの受理区間数 | 48 を超えると手全体を適用しない（`too_many_regions`。`min_gap_ms` を上げて書き直せる） |

- 拒否は区間単位で、手はエラーにならない。複数の規則に当たる区間は EG-1 → EG-2 → EG-3 の順で最初の 1 つを記録する。受理 0 件の手も記録する。手の `status` は `applied`／`no_regions`／`too_many_regions`／`reverted`
- 性質: EG-3 の帯域は 200 Hz〜8 kHz なので、200 Hz 未満の減衰音は EG-3 からは見えず、EG-1・EG-2 と `threshold_db` の範囲でだけ守られる。雑音に埋もれかけた音程成分（信号対雑音比 0 dB 前後）は通る
- 指揮書の `moves[].safeguard`（量の前後比較）は別物で、従来どおり `check` が判定する
- **実現**: 受理区間ごとに既存の区間ミュート（`stem mute` と同じ操作。ジャーナル 1 エントリずつ）。切り口のフェードは、区間の直前で終わるクリップの `fade_out` と直後に始まるクリップの `fade_in` を `fade_ms` 相当（クリップ長まで）にし、1 手ぶんをまとめてパッチ 1 回にする。既存のフェードがそれより長ければ短くしない。タイムラインの先頭・末尾の切り口には付けない。タイムラインの長さは変わらない
- **台帳（U-21）**: プロジェクトの `directions/dir_<id>.edits.json`（適用記録の隣。kb に収蔵するときは outcome と同じフォルダへ写す。JSON は `kb lint` の対象外）。受理・拒否の全区間が載る

```json
{
  "kind": "direction_edits", "schema_version": 1, "direction": "dir_xxxxxxxxxxxx", "journal_seq_before": 41,
  "measure": { "source": "raw_asset_pre_clean", "frame_ms": 50, "hop_ms": 10, "guards": { "EG-1": -36.0, "EG-2": -40.0, "EG-3": 0.10, "EG-4": -40.0, "EG-5": 48 } },
  "moves": { "m01": {
    "op": "edit_gate", "track": "trk_xxx", "section": null, "params": { "…": "省略時の値を埋めた全キー" },
    "active_db": -21.4, "track_energy_db": -24.9,
    "regions": [ { "n": 1, "start": 0, "end": 148800, "t0_s": 0.0, "t1_s": 3.1, "max_frame_dbfs": -71.2, "rel_active_db": -49.8, "energy_rel_track_db": -58.3, "flatness": null, "muted_clips": ["clp_xxx"], "journal_seq": 42 } ],
    "refused": [ { "start": 2304000, "end": 2400000, "t0_s": 48.0, "t1_s": 50.0, "guard": "EG-3", "value": 0.04, "limit": 0.10, "max_frame_dbfs": -52.0 } ],
    "fades": [ { "clip": "clp_xxx_b", "field": "fade_in", "before": 0, "after": 960 } ], "fades_journal_seq": 43,
    "removed_energy_rel_db": -58.3, "status": "applied" } },
  "reverted": false
}
```

- 適用記録の `moves[<mid>]` には `{op, track, regions: 件数, refused: 件数, removed_energy_rel_db, status, ledger}`、適用結果には `edits: {moves, regions, refused, ledger}` が出る。outcome には台帳があるときだけ `edits`（手の数、区間数、拒否数、手ごとの除いたエネルギーと `status`、台帳のパス、`reverted`）が出る。台帳の無い案件の outcome は従来とバイト同一
- **可逆性（3 通り）**: (1) 床の写しに適用する運用は変わらず、床そのものは編集されない。(2) `direction edit revert --project <p> --direction <dir_id> [--move <mid>]` が台帳の `muted_clips` を戻し、`fades` を `before` に戻す（パッチ 1 回）。台帳に `reverted: true`（手単位なら手の `status: "reverted"`）と `reverted_journal_seq` を書く。分割されたクリップは残るが、フェード無しの分割点はサンプル精度の突き合わせなので、描画は編集前とビット同一になる（元のクリップのフェードの途中で分割された場合は、既存の分割がフェード長を詰めるため、ビット同一にならないことがある）。同じトラックに編集の手が複数あるとき、切り口のフェードはそのトラックの最後の手の区間ミュートの後にまとめて置く（手の順に、手ごとにパッチ 1 回）。その場合、手単位の `revert --move` は拒否される（指揮書全体の `revert` か `checkout` を使う）。ビット同一は 1 本の指揮書の編集についての性質である。別の指揮書の編集が同じトラックに残っている間（その台帳の手が `applied` で、そのミュートかフェードがプロジェクトに現にある間）、そのトラックへの編集の手を持つ指揮書の `apply` は編集段の前で止まる（先の指揮書を `direction edit revert` で戻すか、床の新しい写しに適用する）。(3) `mankomix checkout <journal_seq_before>` で編集前へ（以後の適用も戻る）
- **途中で失敗したとき**: 台帳は編集段の全手（区間ミュートとフェード）を終えた後に 1 回だけ書かれるので、区間ミュートの途中で `apply` が失敗するとそこまでのミュートだけが残って台帳も適用記録も無く（再適用は止まらず、残ったミュートの上で編集段が最初から走る）、編集段の後の段（較正・整音の上書き・ミックス提案）で失敗すると編集と台帳が残って適用記録は無い（再適用は「台帳が既にある」で止まる）。どちらも `mankomix history` で編集段の前のジャーナル番号（台帳があればその `journal_seq_before`）を確かめて `mankomix checkout <番号>` で戻せるが、`checkout` は `project.json` の状態だけを戻し `directions/` の台帳などは消さないので、適用し直す先は床の新しい写しである
- **較正との関係**: 較正は編集後のプロジェクトを床側・候補側の両方に使う。編集 op のパラメータは較正の対象にならず、編集 op があっても較正は止まらない
- **評価段**: 編集 op は常に E2 以上（`origin: catalog`＋R-nn でも E1 にならない）。`target` が主役（`trk_vocals`）なら E3（`listen_for` が無ければ既存の警告）
- **下見**: `direction edit scan --project <p> --track <trk> --op edit_trim|edit_gate [--params <json|@file>] [--section <id|json>]` は、適用と同じ関数で候補・拒否・除かれるエネルギーを JSON（`kind: direction_edit_scan`、`status` は `ok`／`no_regions`／`too_many_regions`）で返し、何も書かない。手を書く前に見られる材料の 1 つで、見るかどうかは指揮者の裁量
- 範囲外: 床への組み込み、整音入力の書き換え、区間の手書き指定、時間伸縮、クロスフェードでの差し替え、MCP 露出

### 7.2 ダッキング（`duck`）

あるトラック（キー）が鳴る瞬間だけ別のトラック（対象）を少し下げる手。常時の EQ・ゲインでなく時間で譲る（R-13）。パラメータは §3。

- **包絡の作り方（床の計画器のダッキングと同じ手順を指揮レイヤーに定義）**: キー信号は `key` のトラックの整音後・チェーン前・フェーダー前の音（同じ指揮書の `cleanup_override` より前の整音で検出される）。`key_lo_hz`〜`key_hi_hz` に 4 次・ゼロ位相で帯域通過し、5 ms ホップのフレームパワー（dB）の活動フレーム（> −150 dB）の 95 パーセンタイル − `trigger_below_p95_db` を閾値に、立ち上がりの交差を打点にする（`min_interval_ms` 未満の連打は先のものだけ）。打点ごとに折れ点 3 つ `[打点 − attack, 0]`、`[打点, −depth_db]`、`[終点, 0]`（終点 = min(打点＋回復時間, 次の打点 − attack − 1 サンプル)）。床の計画器は因果のフィルタなので、打点の位置が床と 1 ホップほど違うことがある
- **打点 0 件**: 手は何も書かず、適用記録に `hits: 0` と注記、`notes` に 1 行（エラーではない）。`move_ref` の網羅は適用記録で足りる扱い
- **R-11 への従わせ方（U-22）**: 回復は音価（`release_note`）で書ける。記録は床と同じキー `{note, bpm, ms, rule: "R-11"}`。ms で書いた場合も BPM があれば最も近い音価と偏差を残す（`{note, bpm, ms, note_ms, deviation_ms, written: "ms", rule}`）。BPM が無ければ `note: null` と理由
- **回復の検証**: 指定した回復時間のまま次の打点の下げ始めより前に 0 dB へ戻れる打点（打点＋回復 < 次の打点 − attack。最後の打点は戻れるものとして数える）を数え、適用記録に `recovery: {hits, recovered, recovered_ratio, median_interval_ms, release_ms}` を残す。`recovered_ratio` が 0.8 未満なら `notes` に「回復が打点間隔に収まらない打点が n/m。より短い音価を検討」と 1 行出る。拒否はしない（読む材料）
- **既存のオートメーションとの合成（U-23）**: 折れ点列は dB で区分線形なので、2 本の和は両方の点の位置の和集合で値を足したものとして厳密に表せる。対象トラックに床のオートメーション、同じ指揮書の区間ゲイン、別の `duck` があれば合成して 1 本にし、`owner: director`、`move_ref` は関わった手の ID の配列（区間ゲイン → `duck` の順）。床の折れ点数と所有者は適用記録の `floor_automation: {points, owner}` に残る。`duck` の無いトラックの扱いは従来どおり（§5）
- **適用記録**: `moves[<mid>]` = `{op, track, key, hits, depth_db, attack_ms, release, recovery, key_band_hz, trigger_below_p95_db, min_interval_ms, points, floor_automation}`
- **評価段**: 常に E2 以上。`target` が主役なら E3
- **限界**: 対象は**全帯域で**下がる（帯域を指定できるのはキーの検出帯域だけ）。対象側の帯域だけを下げるには DSP に外部キーの入力が要り、現行には無い。欲しい場合は `tool_requests` に書く。バスを対象・キーにすること、先読みつきの滑らかな包絡も無い

### 7.3 帯域別の側成分（`stereo`）

帯域別の側成分倍率は既存の `stereo` プロセッサで書ける（§3 の `processor` の下の 3 行）。今回の追加は、2 要素・3 要素の配列が範囲と誤解されて validate に拒否されていた点の修正だけで、DSP の追加は無い。中央成分だけへの処理、側成分だけへの動的処理・歪み、任意の処理を M/S の片側に掛ける見方は無い（欲しい場合は `tool_requests`）。

### 7.4 翻訳の観察（`view`、`check --translation`）

観察量の `view`（§3）は、小さなモノ再生での残り方を見るための見方で、指揮書の `observations` に書けば主張・ガードにも使える（使うかは裁量）。音声は書かない（描画済みマスターをメモリ上で変換して測る）。

`direction check --translation` は、付けたときだけ outcome の `translation` キーに次の 5 量を足す。各量は `{floor, result, change}`（結果は観察量と同じくレベルマッチ後、`change` = result − floor）。

| キー | 定義 |
|---|---|
| `mono_fold_lu` | LUFS-I（`mono`）− LUFS-I（stereo） |
| `small_speaker_lu` | LUFS-I（`mono_band`）− LUFS-I（stereo） |
| `low_harmonic_db` | 帯域エネルギー 150–400 Hz（`mono_band`）− 帯域エネルギー 40–150 Hz（stereo）。低音が小さな再生系に倍音で残る度合い |
| `presence_db` | `mono_band` での帯域比 1000–4000 Hz 対 150–1000 Hz |
| `crest_db` | `mono_band` でのクレスト |

- ブロックの頭に `note`「参考値。どの判定にも入らない（主張・期待・ガード・summary・ゲート）」と `view: {mono_band_hz: [150, 6000]}` が付く。主張の判定・`summary`・`--calibrate` はこのブロックを読まない
- 範囲外: コーデック往復の観察（既存の検証段の仕事）、ステム単位の輪郭

### 7.5 kb の任意欄と等級（発見経路・観察記録・カリキュラム）

カードの形は kb/README の「追補 2」。指揮書の扱いに関わる点だけ書く。どの欄も無いことを `kb lint` は咎めず、validate／check はこれらの欄を読まない。

- **発見経路（work の `sources`）**: 素材の所在メモと権利注記の記録だけ。道具はこの欄を読んで動かず、URL を開かない。素材を探して集めるのは人（KT-0023、§6.5「持ち込みを求める」）
- **観察記録（work／engineer の `observed_media`、等級 `observed_media`）**: 等級の並びは `replicated > measured > literature > practice > observed_media > tip > hunch`（U-25）。観察は意図推定の材料に限り、確度を上げず、測定の代わりにしない（U-26。§6.4）。カードの等級を動かすのは従来どおり outcome だけ
- **カリキュラム（kind `curriculum`、`source_type: curriculum`）**: 計画フェーズの表の 2a の入力の 1 つ（冒頭の「カリキュラムの位置」）。`order`／`level` を読むのは `kb search --curriculum` の並びだけで、validate／apply／check／`--calibrate` は読まない
- **低音の音色カード（KT-0024〜KT-0030）**: 理論カードとして他の理論カードと同じ扱い（§6.3。`basis` に書いても E1 にならず、書かなくても警告なし）

## 8. 追補 3: トラック文脈の観察・配置・純度（2026-11-16）

本節の手・欄・観察量・下見は、どれも指揮者が選べるもので、**使わなくても不利にならない**。validate／apply／check／`--calibrate`／`kb lint` は、これらの使用の有無・順序・回数を検査も採点も警告もしない。見るのは書かれたものの形式・範囲・衝突だけで、使わない指揮書の validate・適用記録・ミックス提案・outcome は従来とバイト同一（例外は §8.6 の警告 1 種）。`schema_version` は 1 のまま、既存の指揮書の `dir_` ID も変わらない。

効き目についての注記: 機構は合成フィクスチャと自前の素材で確かめているだけで、これらの道具で音が良くなること、配置や距離の印象が実際に出ることは実証していない。

### 8.1 トラック対象と経路（`target: trk_<stem>`、`path`）

観察量の `target` に `trk_<stem>` を書くと、そのトラックのミックス段の信号を測る。経路は任意欄 `path` で選ぶ。

| `path` | 測る信号 |
|---|---|
| `dry`（省略時） | そのトラックがバスに入る直前の音（整音 → チェーン → フェーダー・オートメーション → パン・幅の後）。ミックス全体を 1 回描画して全トラックを得る |
| `solo` | そのトラックだけを鳴らしたミックスバス出力（マスター段の前）。センド戻りとバスの処理を通った音 |

- 既存の 6 種と `image_position` は、どちらの経路でも `master` と同じ計算をする。`view`・`section`・`band_hz` の規則も同じ
- **レベルマッチはしない**: トラックの信号はマスター段の前なので、`level_match` の値に関わらずゲイン 0 で測る。結果に `gain_db: 0.0`、`signal: "mix_stage"`、`path` が載る
- validate: `path` を `master` 対象に書く・未知の値・`masking`／`wet_ratio` に書くと `bad_value`。`--project` つきで無いトラック（`target`・`against`）は `unknown_target`。トラック対象には従来の `unsupported` 警告を出さない
- **プロジェクトを書かない**: 描画の前に整音キャッシュの有効性を確かめ、無い・古いときは描画せず、その観察量を `{"status": "error", "reason": "整音の cache が無いか古い。先に clean apply／render する"}` にする。無いトラック（`unknown track '…'`）とミュート中のトラック（他のトラックの solo で聞こえない場合を含む）も `status: error`。描画はメモリ上だけで、結果はプロセスの中に持つ
- `direction query`（音声ファイル 1 本）は従来どおり `master` だけを測る
- 読み方: `dry` はフェーダーとパンの後の音なので、`gain` や `place` の距離で下げた分がそのまま値に出る。`solo` の差には、そのトラックの手に加えてバスの処理とセンドの変化が混ざる

### 8.2 観察量 3 種（`image_position`／`masking`／`wet_ratio`）

| primitive | 対象 | 定義 | 単位・範囲 | 欄 |
|---|---|---|---|---|
| `image_position` | `master`、`trk_*` | 区間内の `(E_R − E_L) / (E_R + E_L)`（E は二乗和）。`band_hz` があれば 4 次・ゼロ位相の帯域通過の後 | 係数 −1〜+1（＋が右。`pan` の向きと同じ） | band_hz（任意） |
| `masking` | `trk_*` または `"all"` | `core.analysis.stems.masking_matrix`（P-02）を、その状態の聞こえる全トラックの `dry` 信号に掛けた埋もれ量 | dB、0 以上（モデルの上限まで） | against（任意）、band_hz（任意） |
| `wet_ratio` | `trk_*` | A = `solo` の音、B = 同じ条件でそのトラックのセンドを空にした音。値 = `10·log10(E(A−B) / E(B))` | dB。下限 −120.0（センドの無いトラックはこの値） | band_hz（任意） |

- `image_position`: `direction query` と `--calibrate` からも使える（`master` 対象）。`view` が `mono`／`mono_band` なら `bad_value`。無音（E_L + E_R < 1e-20）は `status: error`。値は無次元
- `masking` の引き方:
  - `target: trk_x`（`against` 無し）→ x の、他の全トラックに対する埋もれ量
  - `against: "trk_y"` → x が y に埋もれる量（1 対 1）。`band_hz` との併用は `bad_value`。`against` が対象と同じ・トラック ID でないときも `bad_value`
  - `target: "all"` → 重要度で重みづけた全体の値。`against`・`band_hz` は `bad_value`
  - `band_hz: [lo, hi]` → 帯域の中心が `[lo, hi)` に入る ERB 帯の値の単純平均（欠測は除く。1 つも無ければ `status: error`）
  - `section` は全トラックの信号をその時間範囲に切ってから渡す。役割・主役・重要度とジャンルは床の評価と同じ材料から組み立てる。聞こえるトラックが 2 本未満、対象が区間内で無音、モデルが値を返さないときは `status: error`
  - `path`・`view` は書けない（`bad_value`）。常に `dry` で測る
- `wet_ratio`: `path`・`view` は書けない。**バスの非線形処理（ミックスバスのコンプ等）は、ソロ時の動作になる。** `band_hz` は A・B の両方に同じ帯域通過を掛ける
- `masking`／`wet_ratio` は単一の信号では計算できないので `direction query` には書けない（従来どおり未知の primitive のエラー）。指揮書の `observations` に書けば、主張・期待・安全弁から `obs:<id>` で引ける。判定の規則（`up`／`down`／`not_worse`、`worse`）は従来と同じ
- 新しい 3 種の `band_hz` は `[lo, hi]`（0 ≤ lo < hi、有限）でなければ validate が `bad_value`。対象の種類の誤り（`masking` にトラック・`all` 以外、`wet_ratio` にトラック以外、`image_position` に `master`・トラック以外）は `bad_target`。`against` を `masking` 以外に書くと `bad_value`
- 読み方の注記:
  - `image_position` はエネルギーの左右比であって、パン位置そのものではない。モノ素材を等電力則（センター −3 dB）で位置 p に置くと、値は `sin(p·π/2)` になる（p = 0.4 → 0.588、0.7 → 0.891）。ステレオとして取り込んだ素材は左右が同じでもパンが釣り合い則で働くので、0.4 に置くと約 0.415 になる
  - `masking` は粗い興奮パターンのモデル値で、知覚の真値ではない。被りは 2 つの音の関係で、埋もれ量が下がることは良いミックスと同義でない。意図した重なり・一体感もあるので、値を 0 に近づけること自体を目的にしない
  - `wet_ratio` はセンドで足した残響の量だけを見る。素材に既に焼き付いた残響は数に入らず（それは §8.5 の `stems purity` で見る）、距離の印象そのものでもない
  - 側成分比・相関のような幅の量が増えたことを、音源を空間に置けたことと読まない。配置を主張にしたいなら、配置の量（`image_position`、`wet_ratio`、トラックのレベル）で立てられる。どれを主張に選ぶかは指揮者の裁量で、空間の依頼にこれらを必須にはしない

### 8.3 配置の宣言（`scene`）

ブロックの任意欄（トップレベル）。手の前に、各音源をどこに置くつもりかを書く。

```json
"scene": { "note": "（任意）", "sources": [
  { "track": "trk_vocals", "azimuth": 0.0, "depth": 1, "note": "（任意）" },
  { "track": "trk_keyboard", "azimuth": -0.4, "depth": 3 } ] }
```

- `track` は必須で `trk_<stem>`、重複不可。`azimuth` は −1〜1（`pan.position` と同じ座標）。`depth` は整数 1〜5（1 が最前）。`azimuth` と `depth` のどちらかは必要。`sources` は 1〜32 件
- validate の検査（形と範囲だけ）:

| 条件 | where | コード |
|---|---|---|
| `scene` が object でない／`note`・`sources` 以外のキー | `scene` | `bad_value` |
| `note` が文字列でない | `scene.note` | `bad_value` |
| `sources` が無い／list でない | `scene.sources` | `missing_field`／`bad_value` |
| 件数が 1〜32 でない | `scene.sources` | `param_range` |
| 音源が object でない／`track`・`azimuth`・`depth`・`note` 以外のキー | `scene.sources[i]` | `bad_value` |
| `track` が無い／`trk_<stem>` でない | `scene.sources[i].track` | `missing_field`／`bad_value` |
| `track` の重複（2 本目に付く） | 同上 | `bad_id` |
| `--project` つきで無いトラック | 同上 | `unknown_target` |
| `azimuth` が数でない（bool・非有限を含む）／−1〜1 の外 | `scene.sources[i].azimuth` | `bad_value`／`param_range` |
| `depth` が整数でない（`2.0`・bool を含む）／1〜5 の外 | `scene.sources[i].depth` | `bad_value`／`param_range` |
| `azimuth` も `depth` も無い | `scene.sources[i]` | `missing_field` |
| 音源の `note` が文字列でない | `scene.sources[i].note` | `bad_value` |

- **検査しないこと**: 全トラックを載せたか、手が宣言どおりか、宣言と実測が合うか
- `direction check` は、`scene` があるときだけ outcome に判定外のブロック `scene` を足す（測った値と `expected_image` は小数 3 桁。`azimuth`・`depth` は書かれた値のまま）

```json
"scene": { "note": "参考値。どの判定にも入らない（主張・期待・ガード・summary・ゲート）。奥行きの知覚は 1 つの量で決まらない。expected_image は sin(azimuth·π/2) の目安（モノ素材の等電力則の値。ステレオで取り込んだ素材は釣り合い則で、これより中央寄りに出る）",
  "sources": { "trk_keyboard": { "azimuth": -0.4, "expected_image": -0.588,
      "image_position": { "floor": 0.0, "result": 0.0 }, "depth": 3,
      "wet_ratio_db": { "floor": 0.0, "result": 0.0 }, "level_lufs": { "floor": 0.0, "result": 0.0 } } },
  "depth_consistency": { "n": 0, "tau_wet": null, "tau_level": null } }
```

- 音源は宣言の順。`azimuth`・`expected_image` は `azimuth` を書いた音源だけ、`depth` は書いた音源だけに出る。`image_position` は `path: solo`・全区間・帯域なし、`wet_ratio_db` は §8.2 の定義、`level_lufs` は `dry` の積分ラウドネス。測れない値（無いトラック、ミュート、キャッシュ無し等）は `null` にして音源は残す
- `depth_consistency`: `depth` を宣言し、結果側の `wet_ratio_db` と `level_lufs` が両方測れた音源の数が `n`。その音源について、結果側の値でケンドールの τ（同順位ありの τ-b）を取る。`tau_wet` は depth と `wet_ratio_db`（深いほど大きいと +1）、`tau_level` は depth と `−level_lufs`（深いほど小さいと +1）。n < 3、または τ が定まらない（depth が全部同じ等）ときは `null`
- ブロック全体を、主張・期待・ガード・`summary`・`move_ref`・`--calibrate` のどれも読まない（`translation` と同じ扱い）。床のプロジェクトの `mix.declared_depth_order` には書かない。`scene` の無い指揮書の outcome は従来とバイト同一
- 読み方の注記: 宣言は狙いの記述で、実測とずれても誤りではなく、減点もしない。τ はレベルとセンド量という 2 つの手がかりの並びだけを見ており、奥行きが聞こえるかを言うものではない

### 8.4 配置の手（`place`）

方位と距離を 1 つの手で書き、距離の手がかり（レベル・高域・直接音と残響の比）を同じ規則で導く。パラメータの表と形式の検査は §3。

導出（L = log2(distance)。値は小数 2 桁に丸める）:

| 段 | 展開される手 | 値 | 足さない条件 |
|---|---|---|---|
| 1 パン | `pan` | `position = azimuth`、`width`（書かれたものだけ） | `azimuth`・`width` がどちらも無い |
| 2 フェーダー | `gain` | `delta_db = −level_db_per_doubling × L` | `distance` が無い、または値が 0 |
| 3 高域 | `chain_add`（チェーン末尾の `eq`） | `shape: high_shelf`、`freq_hz: air_freq_hz`、`gain_db: −air_db_per_doubling × L`、`bw_oct: 1.9`、`phase: minimum` | `distance` が無い、または値が 0 |
| 4 センド | `send` | `{bus: room, level_db: min(near_send_db + send_db_per_doubling × L, −3.0), pre_fader: false}` | `room` が無い |

- 例（既定の係数）: `distance: 2` → `delta_db` −2.0、シェルフ −1.0 dB @ 5000 Hz、センド −20.0 dB。`distance: 8`、`near_send_db: −12`、`send_db_per_doubling: 6` → センドは −3.0 に張り付き `send_clamped: true`。`distance: 1.0` はゲインも EQ も足さない（`room` があればセンドは `near_send_db`）
- `distance` は書いた値のまま使われ、2 のべきでなければ導出は端数になる（既定の係数で `1.41` → −0.99 dB／−0.5 dB／センド −22.02 dB、`1.4142` → −1.0／−0.5／−22.0）
- 実現: 上の既存 op に内部で展開し、既存の適用経路へ流す。足したシェルフとセンドには `owner: director` と元の `place` の手の `move_ref` が付く（シェルフの処理 ID は手書きの `chain_add` と同じ `dr.<trk>.<mid>`）。展開後の各手は既存の範囲検査をそのまま通る（範囲で書いた場合は両端）。範囲で書いたパラメータは `select` で 1 つの値に決まってから導出される
- 衝突（validate の `conflict`。エラーは `place` の手に付く）: 同じトラックに (a) `place` が 2 本（2 本目に付く）、(b) `azimuth`／`width` を持つ `place` と `pan`、(c) `distance` を持つ `place` と区間なし（`section` が無いか `all`）の `gain`、(d) `room` を持つ `place` と同じバスへの `send`。区間つきの `gain`、別のバスへの `send` は衝突しない
- 床に同じバスへのセンドが既にあるトラックでは、`place` の `room` のセンドがそれに置き換わる（既存の `send` op と同じで、床の計画器が持つセンドでも残らない）
- 適用記録: `moves[<mid>] = {op: "place", track, azimuth, width, distance, room, model: {5 つの係数}, derived: {position, width, delta_db, air_gain_db, send_level_db, send_clamped}}`。上の段の `azimuth`／`width`／`distance` は `select` で決まった値（丸めない）。`send_clamped` は導出値が −3.0 を超えたとき true（ちょうど −3.0 は false）。`distance` が無ければ `delta_db`・`air_gain_db` は `null`、`room` が無ければ `send_level_db`・`send_clamped` は `null`
- `move_ref` の網羅: `place` は適用記録で追う。シェルフかセンドを足した場合は、その `move_ref` が描画結果に現れることも数える
- 評価段: 常に E2 以上（§4）。`--calibrate` はパラメータを較正しない（`select` の値のまま）

固定の注記:

- **係数は慣行に基づく初期値で、物理の再現ではない。** 直接音の遅延、音源ごとの初期反射、頭部伝達関数は扱わない。距離の印象が実際に出るかは実証していない
- 部屋のバスは 1 つを共有するほうが一貫しやすいが、強制しない
- `place` は糖衣で、唯一の経路ではない。同じことを `pan`／`gain`／`chain_add`／`send` で手書きする自由は残る（ミックス状態は同じになる）
- 読み方: 残響だけで奥行きを作る以外の選択肢として、レベルと高域を同じ規則で動かす手である。残響を使うこと自体は誤りではなく、全体に掛ける広がりは個々の音源の配置の代わりにならない
- `distance` でレベルを下げたトラックは、そのトラックの `masking`（埋もれる量）が上がりうる。同じトラックの被りを解く手とは打ち消し合いうる。主張・期待は手を分けず全体の結果で判定される

### 8.5 下見 3 種（`direction stems observe／relate／purity`）

手を書く前に、全トラックを横断して量を見るための読み取り専用のコマンド。どれもプロジェクトに何も書かず、整音キャッシュが無い・古いときは描画せずに入力エラー（終了コード 1。先に `clean apply`／`render` する旨）。曲資料（`direction dossier`）には載らない。見るかどうか、どの順で見るかは指揮者の裁量で、手順の固定ではない（`direction edit scan` と同じ扱い）。

**`direction stems observe --project <p> [--variant <v>] <spec>`**: `<spec>` は観察量 1 つか配列（JSON か `@file`）。§8.1・§8.2 の観察量をプロジェクトの現状で測る。区間は床の提案の区間を使う。

```json
{ "kind": "direction_stem_observations",
  "observations": [ { "spec": { "…": "書かれたまま" }, "result": { "status": "ok", "value": 0.0, "unit": "dB", "range_s": [0.0, 0.0], "gain_db": 0.0, "signal": "mix_stage", "path": "dry" } } ] }
```

- トラックから測らない spec（`master` を対象にした単一信号の観察量）は `status: error`（`direction query` を使う旨）。測れない spec も `status: error` で返り、他の spec は測られる

**`direction stems relate --project <p> [--variant <v>] [--section <id|json>] [--top <n>]`**: `--top` は既定 3、1〜8 の整数（範囲外は入力エラー）。`--section` は区間 ID か `{"t0_s", "t1_s"}` の JSON。

```json
{ "kind": "direction_stem_relate", "signal": "mix_stage_dry", "section": null, "tracks": ["trk_a", "…"],
  "masking": { "overall_db": 0.0, "lead": "trk_vocals",
    "per_target": { "trk_a": { "buried_db": 0.0,
      "by_band": { "sub": null, "bass": 0.0, "lowmid": 0.0, "mid": 0.0, "highmid": 0.0, "air": null },
      "top_maskers": [ { "track": "trk_b", "buried_db": 0.0 } ] } } },
  "band_owners": { "sub": [], "bass": ["trk_a"], "lowmid": ["trk_a", "trk_b"], "mid": [], "highmid": [], "air": [] },
  "note": "P-02 のモデル値（粗い興奮パターン）。0 に近いほど良いわけではない。band_owners は P-22 の担当の規則を満たしたトラックだけで、その帯域で鳴っているトラックの一覧ではない。読みは指揮者の〔推定〕" }
```

- 聞こえる全トラックの `dry` 信号（区間があれば切ったもの）に `masking_matrix` を掛ける。`by_band` の 6 帯域は P-22 の境目（20／60／250／500／2000／6000／20000 Hz）で、集約は §8.2 の `band_hz` と同じ規則（値の無い帯域は `null`）
- `top_maskers` は埋もれ量の降順（同値はトラック ID 順）で、値の無い相手を除いた上位 `--top` 件（0 の相手も含む）。`lead` はモデルが決めた主役（決まらなければ `null`）
- `band_owners` は `core.analysis.stems.band_density` の全体（区間別は出さない）の帯域ごとの担当トラックで、6 帯域すべてがキーに出る（担当の無い帯域は `[]`）。担当に挙がらないトラックもその帯域で鳴っていることがあり、区間別の帯域比から数えた『重なりの多い帯域』とは定義が違うので、両者は食い違って見えうる
- 数値は小数 3 桁。聞こえるトラックが 2 本未満、未知の区間は入力エラー

**`direction stems purity --project <p> [--track <trk>]...`**: 各トラックの整音後・チェーン前・フェーダー前の音（`duck` のキー信号と同じ段）を測る。`--track` を省くと聞こえる全トラック。指定すればミュート中のトラックも測れ、無いトラックは入力エラー。共有成分の相手は、聞こえる全トラックと指定したトラック。

```json
{ "kind": "direction_stem_purity", "signal": "post_clean_pre_chain",
  "tracks": { "trk_a": {
      "shared": [ { "track": "trk_b", "shared_power_db": -12.0, "louder_in": "trk_b" } ],
      "baked_reverb": { "dr_db": 0.0, "rt60_mid_s": 0.0 },
      "baked_width": { "correlation": 0.0, "side_ratio_db": 0.0 },
      "baked_dynamics": { "peak_dbfs": 0.0, "lufs_integrated": 0.0, "plr_db": 0.0, "crest_db": 0.0 },
      "flags": { "origin": "…", "r22_baked": false, "floor_restricted": false } } },
  "mixture": { "residual_db": 0.0, "correlation": 0.0, "residual_after_gain_fit_db": 0.0 },
  "note": "（下の固定文）" }
```

| キー | 定義 |
|---|---|
| `shared` | 他トラックとの共有成分。両者をモノ和・16 kHz に落とし、二乗コヒーレンス C(f)（ハン窓、2048 点、重なり 1024）を 100〜7000 Hz で取り、`shared_power_db = 10·log10(Σ C·P_self / Σ P_self)`（P_self は自分のパワースペクトル）。−20.0 dB 以上の相手だけを大きい順に最大 5 件。`louder_in` は `Σ C·P` が大きい側のトラック ID（出どころの手がかり。同値はトラック ID 順） |
| `baked_reverb` | `core.analysis.stems.reverb_metrics` の D/R（`dr_db`）と中域の RT60（`rt60_mid_s`）。推定できない値は `null`、両方とも推定できなければ全体が `null` |
| `baked_width` | 全帯域の相関と側成分比（`query` の観察量と同じ計算） |
| `baked_dynamics` | ピーク dBFS、積分ラウドネス、PLR（ピーク − ラウドネス）、クレスト |
| `flags` | `origin`（アセットの由来。混在なら一覧、不明なら `null`）、`r22_baked`（`knowledge/mix_rules.json` の R-22 の焼き付き検出の条件を読み取りだけで当てた真偽）、`floor_restricted`（床のミックス提案の制限にそのトラックがあるか。床の提案が無ければ false） |

- 対のどちらかが RMS −70 dBFS 未満なら、その対は測らない。共通の長さ（同じ時刻上のクリップの重なり）が 10 秒未満の相手しか無いトラックは `shared: null` と `reason: "too_short"`
- `mixture` はプロジェクトの取り込み検査 `stem_sum_consistency` の値の写し。無ければ `null`。数値は小数 3 桁
- `note`（固定文）: 「共有成分は、線形に共通な成分が自分のエネルギーに占める割合の推定で、漏れの量そのものではない。同じ音を重ねて弾く別の楽器はほぼ数に入らず、残響で広がった漏れは低く出る。残響の値は粗い盲推定。読みは指揮者の〔推定〕」
- 道具は判断しない。「触るな」「制限する」とは出さず、`flags` も情報の真偽値で、どの検査にも効かない（R-22 は判断の出発点で、指揮書には強制しない）

読み方の注記:

- `relate` の値は粗いモデルの値で、0 に近いほど良いわけではない。被りは 2 つの音の関係なので片方だけを見て決めず、譲らせるなら重要度の低い側から、軽い手（位置・レベル・時間で譲る `duck`・狭い EQ）を考える材料にする
- `purity` の共有成分は漏れの量そのものではない。共有成分の大きい 2 本を別々の場所へ動かすと、漏れも一緒に動いて像が割れうる。同じ帯域・同じレベルの 2 本では `louder_in` がどちらにも転びうるので、出どころの断定には使えない
- 由来の札（生成元のステム、分離由来など）は純粋さの保証ではない。既に濡れた素材に残響を重ねるか、近くに置くか、触らないかは指揮者の判断で、触らない判断も正当な手である
- 下見は作業順の固定ではない。土台（レベルの釣り合い・被り・粒立ち・不要部分の掃除）を先に見るのは 1 つの進め方で、測って問題が無いと確かめたなら飛ばしてよい

### 8.6 警告 `unmeasured_quantity`（新しいゲート。警告）

**新しく足したゲートで、警告である（エラーではない）。** 何も判定されない主張・期待・安全弁を、書いた時点で知らせる。

- 仕組み: `direction check` は台帳指標（`P-nn`）を測り直さず、床と結果それぞれの変種の評価項（`project.json` の `variants[].evaluation.terms`）を読む。標準の流れ（`master plan --apply`）では結果の変種に評価項が残らない。だから `P-nn` に立てた主張・期待・安全弁は、標準の流れでは何も判定されない（`not_measured`。安全弁なら何も守らない）
- 出す条件: 主張・期待・安全弁の `quantity` が台帳指標の形（`P-nn` または `P-nn:<限定子>`）なら、`--project` の有無とプロジェクトの評価の有無に依らず、量ごとに 1 件出す。同じ `quantity` は 1 件にまとめ（n は主張・期待・安全弁を通した出現回数）、最初に出た順に、既存の警告の後ろに並ぶ。文は次の 2 種で、`where`（`quantities.<quantity>`）と `code`（`unmeasured_quantity`）は同じ

| 種 | 当たる条件 | `message` |
|---|---|---|
| A | `--project` つきで、床の変種（プロジェクトの最初の変種）に評価項が 1 つ以上あり、その量の項（`check` と同じ読み方: 限定子つき → 無ければ `P-nn`）が無い、または `value` も `penalty` も数値でない | `床の変種の評価項に <quantity> の数値（value／penalty）が無い（該当 n 件）。direction check は not_measured を返す。obs:<id>（masking／wet_ratio／trk 対象の観察量）で測れる` |
| B | A に当たらない全部（`--project` 無し、未評価のプロジェクト、床に数値の項がある量） | `<quantity> は台帳指標（該当 n 件）。direction check は結果の変種の評価項だけを読み、指揮書の結果を測り直さない。標準の流れ（master plan --apply）では評価項が残らず not_measured になる。obs:<id> の観察量は check が床と結果の両方を測る` |

- 出さない場合: `obs:` の量、形の誤った量（従来どおり `bad_quantity` だけ）
- B が出ても判定されうる場合: 目的関数つきの計画器でマスターを決めた流れでは結果の変種に評価項が残り、`check` が判定しうる。validate は後段の流れを知りえないので、その場合も B は出る（誤警告ではなく、判定が成り立つ条件の通知）
- `ok`・エラー・終了コードは変わらない。`apply`・`check`・適用記録・outcome も変わらない（`apply` は validate が `ok` のとき警告を記録に写さない）。しきい値は無い
- 新しい機能を使わない指揮書で出力が変わる唯一の例外: 主張・期待・安全弁に `P-nn` の量を書いた指揮書では、既存の指揮書でもこの警告が出る。`P-nn` の量を 1 つも書かない指揮書の validate は従来とバイト同一
- 読み方: 何を主張し何を守るかは自由で、この警告は事実の通知である。そのまま残してもよく、`obs:<id>` の観察量に置き換えてもよい。置き換えは求めない

### 8.7 範囲外（今回やらないこと）

| 項目 | 理由 | 現状で代わりに出来ること |
|---|---|---|
| ステム内の成分の再分離、時間周波数マスクでの漏れの除去 | 新しい分離モデル・依存を入れない。人工物が出やすく、聴いて確かめる仕組みなしに採れない | `stems purity` で見て、近くに置く／触らない／`edit_gate` で無内容区間を切る |
| 区間ごとの処理・パンの切替（トラックを区間で分けて別の扱いにする） | レンダラーに区間切替が無く、トラックの複製はプロジェクト構造・台帳・取り消しに及ぶ | 区間ゲイン、`duck`、`edit_gate` |
| 時間で動くパン、交互に返るディレイ | DSP の追加が要る | 静的配置、左右別のディレイ |
| 音源ごとの初期反射、頭部伝達関数、直接音の遅延 | 同上 | トラックのチェーンに短い `reverb` を手で置くことは今も出来る（`place` はしない） |
| `masking` などを目的関数・較正に入れる | ゲート・目的関数の定義を動かさない | 主張と安全弁で使う |
| R-22 の制限を指揮書に強制する | R-22 は判断の出発点で不変条件ではなく、動かすかどうかは創作上の選択 | `stems purity` の `flags` を見て指揮者が決める |
| 曲資料への純度・被りの節の追加 | `DOSSIER_VERSION` と既存の出力を動かさない | 下見コマンド |
| 耳の評価を集める仕組み（盲検比較など） | 道具でなく運用の話 | 記録に残す |
| `direction check` で台帳指標（`P-nn`）を指揮書の結果について測り直す | check の所要時間・outcome の形・評価器の呼び方に及ぶ別件 | 警告 `unmeasured_quantity`（§8.6）で書いた時点で知る。`obs:<id>` の観察量は床と結果の両方を測る |

## 9. 追補 4: 枠・居場所・手で書く作業・聴くこと（2026-11-16）

本追補は、指揮者が読む**文脈**（§9.1）と、後続の機能の節（§9.2 以降）から成る。文脈は規則でもゲートでもない。validate／apply／check／`--calibrate`／`kb lint` は、文脈に書かれた考え方を使ったか、どの順で使ったかを検査も採点も警告もしない。文脈を読まずに書いた指揮書も、従来どおりに検査され、不利に扱われない。文脈の背後にある設計思想は `docs/DESIGN_PHILOSOPHY.md` に置く。

### 9.1 文脈

#### 9.1.1 譲らせる順の目安（計画の型への補足）

2 つの音がぶつかるとき、どちらかに譲らせる手は、軽い物から順に考えるのが既定である。番号は考える順の目安で、作業の手順ではない。曲によって入れ替わり、飛ばしてもよい。**順序は機械が検査しない。**

| 段 | 考え方 | 現行の手（例） |
|---|---|---|
| 0 フェーダー | レベルと位置だけで成り立つ範囲を先に確かめる | `gain`、`pan`、`place` |
| 1 編曲で譲る | 鳴らさない・減らす。その区間にその音が要るかを問う | `stem mute`（CLI のステム操作）、`edit_gate`／`edit_trim`、区間つきの `gain` |
| 2 手で形を整える | 区間やフレーズの単位で、量を手で書く | 区間つきの `gain`（区間の前後 20 ms のランプ。§5）、`chain_add` の `eq`／`filter` での帯域の切り |
| 3 時間で分け合う | 片方が鳴る瞬間だけ他方を下げる | `duck`（§7.2）、`chain_add` の `dynamic_eq` |
| 4 処理で押し込む | 常時の処理で音色・ダイナミクスを変えて収める | 大きな `eq`、強い `compressor` など |

- 編曲を変えられない素材では、下の段（2〜4）が主役になる。生成素材では「生成し直す」「差し替える」も 1 の段の現実の選択肢である（道具はそれを行わない。指揮書の散文と `human_questions` に書ける）
- **大きなブーストは居場所の合図。** 帯域を大きく持ち上げないと聞こえない音は、まず居場所（その帯域で他に何が鳴っているか、打ち消し合い、音量の関係、音の長さ、再生系）を疑い、`direction stems relate`（§8.5）や観察量で確かめてから、EQ・置き換え・譲らせ方を比べる。これは validate の警告ではない。R-06（EQ は小さく。超えるなら検証と理由）と評価段の既存の扱い（§4）はそのままで、新しい警告は足さない
- 床の計画器の固定順（SPEC §6.5.1）と R-04・R-05・R-28 は同じ向きで、本目安は指揮層で手を選ぶときの考え方の既定を書いたものである

#### 9.1.2 レビュー側の目安（先に聴く）

指揮書の結果をレビューする人・層の目安。**検査項目ではない。**

- **指揮書を読む前に音を聴く。** 指揮書の文章の出来は、音の出来の証拠にならない。狙い・根拠を先に読むと、聴く前に耳が説明に引っ張られる
- 聴いた印象を書いてから、指揮書・outcome・測定を読み、食い違いを問いにする

#### 9.1.3 良し悪しの問いと事実の問い（§6.6 への補足）

§6.6 の表に「良し悪しの問い」の行を足した。測定は音が**どうなっているか**を言い、**良いかどうか**は言わない。どちらの版が良いか・その手を採るかは、聴いた結果を先に読み、依頼の文言と照らし、測定は状態の説明として使う。

- §6.6 の「事実どうしが食い違うときの重み」（この曲の測定 > リファレンスの測定 > …）は、**事実の問い**の順として従来どおり残る。良し悪しの問いの順はそれを置き換えない
- 聴いた結果が無い案件でも、指揮書・check は従来どおりに動く。聴取の有無を機械は咎めない

#### 9.1.4 用語の固定

| 語 | 意味 | 区別するもの |
|---|---|---|
| 再レンダー | 同じ指揮書（同じ `dir_` ID）で作り直すこと。床と道具の版が同じなら、出力はビット同一が期待値（SPEC §9.6 の再現性の約束） | 再指揮 |
| 再指揮 | 指揮書から書き直すこと。ブロックが変われば新しい `dir_` ID になる。言語モデルの判断にはばらつきがあり、同じ依頼から同じ指揮書が出るとは限らない | 再レンダー |
| 測定上の到達 | 主張が check で `met` になったこと。測定がそう動いたことを言うだけで、音が良くなったことの確認ではない | 聴いて採用 |
| 聴いて採用 | 聴取記録で採用の等級が付いたこと（後の節） | 測定上の到達 |

- outcome の文面（`met` などの値と既存の欄）は変えない。用語は文書と記録を読むときの言葉の区別である
- 聴いていない処理は候補として残してよいが、「改善を確認済み」とは扱わない

#### 9.1.5 時間で分け合う手の 4 つの数字（§7.2 への補足）

時間で分け合う手（ダッキング）は、4 つの数字で考えると書きやすい。現行の `duck` との対応:

| 数字 | 意味 | `duck` の欄 | 確かめ方 |
|---|---|---|---|
| 手前 | 打点のどれだけ前から下げ始めるか | `attack_ms`（1〜30 ms） | — |
| 深さ | どれだけ下げるか | `depth_db`（0.5〜6.0 dB） | — |
| 戻り | どこで戻り切るか（秒でなく拍で） | `release_note`（音価）か `release_ms`（ms。BPM が無いときの既定もこちら） | 適用記録の `recovery`（`recovered_ratio`） |
| 帯域 | 対象のどの帯域を下げるか | 未対応。対象は全帯域で下がる（指定できるのはキーの検出帯域 `key_lo_hz`／`key_hi_hz` だけ。§7.2 の限界） | — |

読み方:

- 手前が早すぎると、前の音の終わりが吸い込まれる。効果としてそれを狙う音楽もあるので、良し悪しは聴いて決める
- 深すぎると揺れとして聴こえる。深さと戻りの形は聴いて決める
- 戻りは秒でなく拍で決めるのが既定（R-11）で、正解は曲による
- テンポが揺れる素材では、1 つの BPM から音価を ms にした戻りが場所によって合わない。適用記録の `recovery` の戻り切り率（`recovered_ratio`）を見るか、`release_ms` で書く
- 道具は曲全体を先に解析してから下げる量と位置を決める。**先に計算して書いても、打点の見つけ間違いと直しすぎは起きる。** 計算で書いたことは、聴かずに採る理由にならない

#### 9.1.6 下見の値の読み方（§8.5 への補足）

- **足し戻しの残差**（取り込み検査 `stem_sum_consistency`、`stems purity` の `mixture`）は「ステムを足して原曲に戻るか」だけを示す。本物のステムであることの証明ではない。残差が大きいときは、原曲を基準にした比較（和とマスターの差分、原曲を床の手がかりにする読み）の前提が崩れている。取り込み検査は先頭揃え（`alignment: head`）で、時間のずれは推定しない。ゲイン合わせ後の残差（`residual_after_gain_fit_db`）が小さく素の残差が大きいなら音量の違い、両方大きいなら時間のずれ・サンプルレート・中身の違いを先に疑う
- **焼き込みの残響の値**（`stems purity` の `baked_reverb`）は、完成した音からの粗い盲推定で、減衰と広がりの目安に留める。残響と音そのものの減衰・ディレイは完成した音から一意に分けられない。推定できない値は `null` で、それは「無い」ではなく「分からない」
- **分離由来のステム**は別カテゴリとして読む。ステムごとに違う処理をするほど漏れと分離の雑音が表に出る。分離で得たステムしか無い場合の既定はフルミックス経路（R-21）、分離・焼き付きのステムはバランスだけに使うのが床の出発点（R-22）。`stems purity` の `flags.origin` と `flags.r22_baked` はその手がかりで、指揮書には強制しない（§8.5）
- **ステムごとの LUFS**（`scene` の `level_lufs`、purity の `lufs_integrated`）は、休符の多いパートでは無音の割合が値を決める。規格のゲートは無音を一部しか除かないので、鳴っている区間の大きさとは別物として読む。既存の値の定義は変えない

#### 9.1.7 比較の音量揃え

- `direction check` の比較は、積分ラウドネス（LUFS-I）で結果を床に揃えてから測る（観察量の `level_match: true`、既定。R-01）。揃えたゲインは outcome の `loudness.level_match_gain_db` に、観察量の結果には `gain_db` として残る。トラック対象の観察量は揃えない（`gain_db: 0.0`。§8.1）
- 読み方: LUFS は K 特性で低域を小さく測る（SPEC §4.2 の補足）。揃えのゲインは主に中高域の変化で決まるので、`master` 対象の低域の帯域エネルギーの差は、低域への手そのものの効果と、他の手が動かした揃えのゲインの和として読む。低域の主張はこの揃え方の影響を受ける
- 揃えた信号は比較のためだけのものである。納品の検査（ラウドネス、True Peak、コーデック往復など）は、出口ごとの最終出力に対して行う（SPEC §6.7）

#### 9.1.8 再現に要る記録の所在

新しい記録は作らない。要素は既存の記録に分かれて揃っている。

| 要るもの | 所在 |
|---|---|
| 入力（正本・素材）のハッシュ、エンジン・バックエンドの版、モデルの ID とハッシュ、定義の版、ディザの種 | レンダリング記録（SPEC §9.6。描画した各ファイルの隣の `<ファイル名>.manifest.json`） |
| 採用した手と選ばれた量、較正の予測と選択、編集段の区間 | 適用記録 `directions/dir_<id>.apply.json`（編集 op があれば台帳 `directions/dir_<id>.edits.json`） |
| 判定（主張・期待・ガード、ゲート定義ハッシュの apply 時と check 時の一致） | outcome `directions/dir_<id>.outcome.json` |
| 指揮書そのもの | `dir_` ID（ブロックの正規化 JSON の SHA-256。§1）と、`directions/` の凍結コピー |
