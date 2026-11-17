# 指揮書の形式（DIRECTION_FORMAT v1）

指揮レイヤー（`director/`、コアの外。コアは import しない）が扱う指揮書の契約。director（PM 層）が書き、`mankomix direction validate／apply／check` が機械で扱う。改築案 v2 の b.6／d.2／c.2 に準拠した最小版で、v2 の決裁（D-085〜／Q-29〜）を先取りしない。

**引き継ぎ書は指揮書と同一物である。** 「指揮書」は形式の名前（本書、`dir_` ID、`direction` ブロック）、「引き継ぎ書」は役割の名前（計画を終えた指揮者が、実行側と人へ判断を渡す文書）で、上位の文書は作らない。分析メモは根拠の記録（`ana_` ID）として引き継ぎ書に含めず、指揮書が `sources` で分析メモ・曲資料・カード・refstudy を指す。

### 計画フェーズの既定の型（既定であって手順ではない）

指揮者が 1 曲の指揮書を書くまでの進め方の既定。**型は手順でもゲートでもない。** 新しいコマンド・文書・欄は無く、既存の道具の並べ方の既定である。調査の脚（2a／2b）の詳細は調査プロトコル（`docs/RESEARCH_PROTOCOL.md`、2026-11-15、D-068）が正で、本節はその要約である。

| 段 | すること | 使う道具・資料 | 残る場所 |
|---|---|---|---|
| 1 分析 | 曲全体とステムを読む | 曲資料（`direction dossier`）、追加の `direction query`、トラック横断の下見 `direction stems observe／relate／purity`（§8.5）、追補 4 の下見 `direction stems stages／placement／phrases`、`direction stems relate --axes`、配線の図 `direction wiring`（§9.7〜§9.10、§9.13） | 分析メモの曲の読み（〔測定〕〔推定〕） |
| 2a 調査・知見の脚 | Fable 5.2 が、依頼内容と段 1 の分析を入力に、5 層（論文／プロユース／アマチュア tips／解説動画／リファレンス作品。国内外問わず）で調査し、この曲の問いに効く知見を引く（調査プロトコル §2・§3） | 曲資料 §10.1 経験・§10.2 理論の棚、`kb search`／`kb show`（lesson／move／research／theory。公開 kb と蓄積 kb の両方）、案件ごとの調査ログ、カリキュラム（`kb show cur_<slug>`、`kb search --curriculum`。§7.5）、棚に無い問いの外部調査 | 分析メモの知見の節（調査→手・主張の対応つき）、調査ログ（蓄積 kb）、`sources.cards` |
| 2b 調査・リファレンスの脚 | 原液（持ち込まれたリファレンス）を測り、逆算する。ステムが存在しそうな作品は、非公式の配布経路も含めて所在を探す（調査プロトコル §3 層 5） | `direction ref study` → refstudy、`direction ref compare` → refsheet、work／engineer カード、輪郭とガイドの追加節（`ref study --add`／`ref compare --add`。§6.1）、work カードの `sources`・`observed_media`（§7.5） | 分析メモ「リファレンスの読み」（§6.4）、`sources.references` |
| 3 引き継ぎ書の立案 | 1・2 を受けて手と主張に落とす | 指揮書（散文 10 節＋ `direction` ブロック）。選べる手・観察の中に `edit_trim`／`edit_gate`（下見は `direction edit scan`）、`duck`、観察量の `view`、`check --translation`（§7）、`place`、`scene`、観察量 `image_position`／`masking`／`wet_ratio` とトラック対象（`trk_<stem>`、§8）、追補 4 の欄 `frame`・`scene.room`・`triage`、手 `gain_curve`、観察量の `view: side` と対象 `mix`、`check --edit-list`／`--contour`、聴き比べ `direction listen pack／record`（§9） | `dir_<id>`、以降は validate 以下の流れ |

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
- 追補 4 の手・観察・下見・欄（§9）は段を増やさず、使わなくても不利にならない

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
| `mankomix direction stems stages`／`stems placement`／`stems phrases`、`stems relate --axes` | 追補 4 の下見（段階の測定、居場所の表、フレーズと余裕、重なりの軸）。何も書かない（§9.7〜§9.10） |
| `mankomix direction check ... [--edit-list] [--contour]` | 判定外のブロック `edit_list`／`contour` を outcome に足す（§9.11・§9.12） |
| `mankomix direction wiring --project <p> [--variant <v>] [--direction <md>] [--format json\|mermaid]` | 配線の図（読み取りのみ。§9.13） |
| `mankomix direction listen pack`／`listen record` | 聴き比べの書き出しと聴取記録（CLI だけ。§9.2） |

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
  - 注記（追補 4）: `gain_curve` を持つトラックでは、区間ゲインが既存のオートメーションに当たっても拒否せず、合成する（§9.10）
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
| 聴いて採用 | 聴取記録で採用の等級が付いたこと（§9.2） | 測定上の到達 |

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

### 9.2 聴き比べ（`direction listen pack`／`direction listen record`）

§9.1.3 の「聴いた結果」と §9.1.4 の「聴いて採用」（「後の節」）は、本節の聴取記録と等級を指す。

結果・床・無処理の 3 つを、音量をそろえ名前を隠して書き出し（`pack`）、聴いた回答を 1 回ずつ記録に足す（`record`）。道具は再生も判定もしない。聴くこと・記録することは任意で、validate／apply／check／`--calibrate`／`kb lint` は聴取記録の有無を見ない。

**`direction listen pack --project <p> --floor <floor> [--variant <v>] (--section <id|json> | --excerpt <t0,t1>)... --out <dir> [--match integrated|section|lead] [--kb <root>]...`**

- 構成員（1 つの抜粋につき 3 本）:

| 構成員 | 中身 |
|---|---|
| `result` | `--project` の変種（省略時は先頭の変種）の描画済みマスター（`hires_native`） |
| `floor` | `--floor` の同じ ID の変種の描画済みマスター。同じ ID が無ければ床の先頭の変種 |
| `raw_gain_only` | 取り込んだステムの素材をそのまま足した和（整音・クリップの編集・ミュート・フェード・ゲイン・チェーンを通さない）。ステムが無い案件は原曲。音量合わせのゲインだけを掛ける |

- 抜粋: `--section`（床の提案の区間 ID か `{"t0_s", "t1_s"}` の JSON）と `--excerpt t0,t1`（秒）を、どちらも繰り返して併用できる。1 つ以上が必須。サンプル位置に直して重複を除き、時刻順に並べる。3 本の共通の長さを超える抜粋・空の抜粋・負の時刻は入力エラーで、切り詰めない
- 音量合わせ（R-01）: 3 本の大きさを測り、**最も小さい構成員に合わせて他を下げる**（ゲインは常に 0 dB 以下。上げない）。リミッター・ディザー・正規化は掛けない

| `--match` | 測る範囲 |
|---|---|
| `integrated`（既定） | 各構成員の全長の積分ラウドネス（どの抜粋にも同じゲイン） |
| `section` | 抜粋ごとの積分ラウドネス |
| `lead` | 抜粋のうち、主役のステムの素材が鳴っているフレーム（編集段と同じ 50 ms 窓・10 ms ホップ、−70 dBFS より上）だけをつないだ積分ラウドネス。主役は目的関数の主役。主役のステムが無い・抜粋に鳴っている所が無いときは入力エラー |

- 名前を隠す: 音声のファイル名は `x01_k1abcdef.wav` の形（抜粋の連番＋中身と無関係な記号）。3 本の並びは、結果に適用済みの指揮書の ID（無ければプロジェクトの ID）・抜粋のサンプル位置・サンプルレートから作った固定の種で決まる。時刻・乱数は使わず、同じ入力からは同じバイト列になる
- 書き出す物（`--out` の下だけ）:

| ファイル | 中身 |
|---|---|
| `x<nn>_k<n><記号>.wav` | 抜粋ごとに 3 本。元のサンプルレート、24 bit PCM |
| `key/key.json` | 対応表（`kind: direction_listen_key`）。ファイル名ごとの構成員・抜粋（秒とサンプル位置）・掛けたゲイン（`gain_db`）・測った大きさ（`loudness_lufs`）・合わせ方・素材の種類（`stem_sum`／`fullmix`）・PCM の範囲外のサンプル数（`pcm_clipped_samples`）と、入力のハッシュ（両プロジェクトの `project.json`、両マスター、無処理の和に使った素材、床の提案）。`lead` なら主役の活動の定義も。絶対パスは書かない |
| `sheet.md` | 回答用紙。聴いた日・再生環境、抜粋ごとに「違いが分かるか」「どちらが好きか」「依頼に合うか」「メモ」の欄。構成員名・区間名・音量は出さない |
| `answers.template.json` | 記録用の回答 1 回分の雛形。`conditions` は実際の条件で埋まり、`date`・`playback`・`judgments` の中身は空 |

- 標準出力は `{"kind": "direction_listen_pack", "files": [...], "key_path": "key/key.json"}` だけで、構成員とファイルの対応を出さない
- 書き出し先の拒否（G-5）: `--out` が結果のプロジェクト・床のプロジェクト・`kb/`・`_private/kb/`・`--kb` で足したフォルダのどれかの中（リンクを解決した後で判定）なら入力エラー（終了コード 2）。既にあるファイル、または空でないフォルダも拒否する（上書きしない）。拒否のときは何も書かない。プロジェクトと kb には何も書かない
- その他の入力エラー: 描画済みマスターが無い、変種が無い、3 本のサンプルレートが違う、床の区間 ID が無い、`--match` が未知

**`direction listen record --project <p> --direction <dir_id> --from <answers.json>`**

`--from` は `answers.template.json` を埋めた回答 **1 回分**（`sessions` で包まない）。`directions/dir_<id>.listening.json` に 1 回分を足す（無ければ作る）。outcome・適用記録は書き換えない。

```json
{ "kind": "direction_listening", "schema_version": 1, "direction": "dir_xxxxxxxxxxxx",
  "conformance": { "source": "dir_xxxxxxxxxxxx.outcome.json", "verify": "pass", "gate": null,
                   "outcome_status": "checked", "outcome_summary": { "…": "outcome の写し" } },
  "sessions": [ { "date": "2026-11-20", "playback": "（文）",
      "conditions": { "level_match": "integrated", "blind": true, "members": ["result", "floor", "raw_gain_only"] },
      "judgments": [ { "axis": "preference", "pair": ["result", "floor"], "answer": "floor", "note": "（文）" } ] } ],
  "grade": "trial" }
```

- 回答の検査（形だけ）: 各階層のキーはちょうど上の形（足りない・余るのは拒否。`grade` を書いた回答も拒否）。`date` は実在する日付 `YYYY-MM-DD`（自動では入れない）。`playback`・`note` は 400 字までの文字列。`level_match` は `integrated`／`section`／`lead`／`none`、`blind` は真偽値、`members` と `pair`（2 件）は構成員名。`axis` は `audible`（違いが分かるか）／`preference`（どちらが好きか）／`fits_request`（依頼に合うか）、`answer` は `pair` のどちらか・`none`・`unsure`。`judgments` は配列。誤りは入力エラー（終了コード 2）で、何も書かない
- `--direction` は `dir_` と小文字 16 進 12 桁。その指揮書の outcome（`dir_<id>.outcome.json`）が無ければ入力エラー（先に `direction check`）。既にある記録も読み直して検査する
- 回答は記号で書いた後、鍵（`key/key.json`）を見て構成員名に直して書く。鍵を開けるのは回答を書き終えてから（目安。機械は確かめない）
- 同じ回答を 2 回足すと 2 回分として残る（重複を除かない）
- **等級 `grade` は機械が付ける（G-4。自己申告させない）**: 記録された全聴取が、音量をそろえ（`level_match` が `none` でない）、名前を隠し（`blind: true`）、`raw_gain_only` を含み、かつ異なる日付の聴取が 2 回以上あるとき `adoption`。それ以外は `trial`。足すたびに全聴取から付け直す。どちらが好きかの答え・outcome の合否は等級に入らない
- `conformance` は聴いた結果とは別の軸で、機械の判定の写し: `verify` は同じ変種の `reports/verify_<variant>.json` の `overall`、`gate` は同じ変種の Mix Report（`reports/report_<variant>.json`）の `translation_gate.status`、それが無ければ `project.json` の変種の評価の `gate.status`（現在のマスター段のチェーンのハッシュと一致するときだけ）。記録が無ければ `null` で、`pass` を推定しない。`outcome_status`／`outcome_summary` は outcome の `status`／`summary` があるときだけ写す（数値は小数 3 桁）。検査や判定を新たに実行しない
- kb に収蔵するときは、聴取記録を outcome と同じフォルダへ写す（JSON は `kb lint` の対象外。`edits.json` と同じ扱い）

使わない場合: 2 つのコマンドを呼ばなければ何も変わらない。validate・check・`kb lint` の出力は、聴取記録の有無で変わらない（記録が無い案件は従来とバイト同一）。新しいゲートは G-4（記録の中の等級）と G-5（書き出し先）だけで、既存の指揮書の合否・警告・出力を変えない。聴いたか・いつ聴いたか・何回聴いたかを機械は検査しない。

当てになり度と固定の注記:

- 等級は記録された**条件**から付く。条件の欄（名前を隠したか等）が実際どうだったかを機械は確かめられない。`adoption` は「条件をそろえて、日を変えて 2 回以上聴いた記録がある」ことを言うだけで、音が良くなったことの証明ではない
- 3 本の音量合わせは比較のためだけのもので、納品の検査ではない（§9.1.7）。`integrated` は全長でそろえるので、抜粋ごとの大きさはそろわないことがある。`pcm_clipped_samples` が 0 でない抜粋は、書き出しで範囲外のサンプルが丸められている
- `raw_gain_only` は「何もしなかったら」の目安で、取り込み時の素材の単純な和である（時間のずれは推定しない。§9.1.6）
- 聴いていない処理は候補として残してよいが、「改善を確認済み」とは扱わない（§9.1.4）

範囲外: 再生、ABX の実施、聴取結果の集計と重みの較正、MCP への公開（今回は CLI だけ）。

### 9.3 枠の宣言（`frame`）

ブロックの任意欄（トップレベル）。狙い（`aims`）の外側に、何を一番聴かせ、何を譲り、何を守り、どこまでの粗さを許すかを書いておく置き場。機械は宣言から手を導かず、宣言と手・実測との整合も見ない（`scene` と同じ線。§8.3）。

```json
"frame": {
  "lead": "一番聴かせる物（文）",
  "yield": ["譲る物（文）"],
  "keep": ["変えてはいけない特徴（文）"],
  "roughness_ok": ["許す粗さ（文）"],
  "scale": "この曲が狙う音場の規模（1 行）",
  "era": { "year": 2024, "genre": "（文）", "stance": "（文）" },
  "key_words": [ { "t_s": 32.0, "text": "聴かせたい言葉" } ],
  "mono_keep": ["trk_vocals", "trk_kick"],
  "section_roles": [ { "section": "s3", "lead": "trk_guitar",
      "roles": { "trk_keys": ["harmony_bed"], "trk_fx": ["unknown"] } } ],
  "tolerances": [ { "quantity": "obs:o_vox_mono", "range": [-24.0, -18.0], "note": "（文）" } ]
}
```

- すべてのキーが任意で、`frame: {}` も書ける。書いたキーに `null` は書けない（型の誤り）。文は空文字でもよい
- 役割の語彙（`section_roles[].roles` の値）: `lead_melody`（主旋律）／`counter`（合いの手・対旋律）／`rhythm`／`harmony_bed`（和声の土台）／`ornament`（飾り）／`double`（同じ旋律の重ね）／`harmony_vocal`（ハモリ）／`call_response`（掛け合い）／`unknown`（決めていない）。1 トラックに複数書け、重複も拒否しない。役割は宣言で、機械は決めない
- `section` は区間 ID（`all` も可）か `{"t0_s", "t1_s"}`。時刻の区間は音源の長さで切らず、最短の長さも求めない
- validate の検査（G-1。形と範囲だけ）:

| 条件 | where | コード |
|---|---|---|
| `frame` が object でない／未知のキー | `frame` | `bad_value` |
| 文（`lead`・`scale`・配列の各要素・`era.genre`／`stance`・`key_words[].text`・`tolerances[].note`）が文字列でない／401 字以上 | 各欄 | `bad_value`／`param_range` |
| `yield`・`keep`・`roughness_ok`・`mono_keep`・`tolerances` が配列でない／17 件以上 | 各欄 | `bad_value`／`param_range` |
| `key_words`・`section_roles` が配列でない／65 件以上 | 各欄 | `bad_value`／`param_range` |
| `era` が object でない／`year`・`genre`・`stance` 以外のキー | `frame.era` | `bad_value` |
| `era.year` が整数でない（bool・小数を含む）／1900〜2100 の外 | `frame.era.year` | `bad_value`／`param_range` |
| `key_words[i]` が object でない／未知のキー、`text` が無い | `frame.key_words[i]`／`.text` | `bad_value`／`missing_field` |
| `t_s` が有限の数でない／負 | `frame.key_words[i].t_s` | `bad_value`／`param_range` |
| `mono_keep[i]`・`section_roles[i].lead`・`roles` のキーが `trk_<stem>` でない／`--project` つきで無いトラック | 各欄 | `bad_value`／`unknown_target` |
| `section_roles[i]` が object でない／未知のキー、`section`・`roles` が無い | `frame.section_roles[i]`／`.section`・`.roles` | `bad_value`／`missing_field` |
| `section` が空でない文字列でも `{t0_s, t1_s}` でもない／時刻が有限でない・負／`t0_s ≥ t1_s` | `frame.section_roles[i].section`（時刻は `.t0_s`／`.t1_s`） | `bad_value`／`param_range` |
| `--project` つきで無い区間 ID | `frame.section_roles[i].section` | `unknown_section` |
| `roles` が object でない／役割の配列が配列でない・17 件以上／語彙の外 | `frame.section_roles[i].roles…` | `bad_value`／`param_range`／`bad_value` |
| `tolerances[i]` が object でない／未知のキー、`quantity`・`range` が無い | `frame.tolerances[i]`／`.quantity`・`.range` | `bad_value`／`missing_field` |
| `quantity` が `obs:<このブロックの observations の id>` でない（`P-nn` も拒否） | `frame.tolerances[i].quantity` | `bad_quantity` |
| `range` が有限の 2 数でない／下限 ≥ 上限 | `frame.tolerances[i].range` | `bad_value`／`param_range` |

- **検査しないこと**: どのキーを書いたか（未記入の警告は無い）、宣言が全トラック・全区間を覆うか、手が宣言どおりか（譲ると書いた物を下げたか等）、宣言と実測が合うか。評価段・手の件数も変えない
- `direction check` は `frame.tolerances` があるときだけ（空配列でも）outcome に判定外のブロック `frame` を足す。値は観察量の測定済みの値を使い、測り直さない

```json
"frame": { "tolerances": [ { "quantity": "obs:o_vox_mono", "range": [-24.0, -18.0],
      "floor": 0.0, "result": 0.0, "within": true } ],
  "note": "参考値。どの判定にも入らない" }
```

- `floor`・`result` は観察量の値（小数 3 桁）。`within` は結果の値が `range` の閉区間（両端を含む）に入るか。どちらかの側が測れない（値が無い・`status: error`）とその側は `null` で、`within` も `null`。`range` は書かれたまま。`tolerances` 以外のキーと各項の `note` は outcome に写さない
- ブロック全体を、主張・期待・ガード・`summary`・`move_ref`・`--calibrate` のどれも読まない（`translation`・`scene` と同じ扱い）。合否にしたいときは既存の主張（`not_worse`／`up`／`down`）で立てられる。許容の幅は床の目標範囲の代わりではない

`mono_keep` を確かめる観察量の書き方（例）: `mono_keep` 自体は何も測らない。モノで残したいトラックの残り方を見たいときは、同じトラックを同じ経路で、見方だけ変えた 2 つの観察量を書く。

```json
"observations": [
  { "id": "o_vox_st",   "primitive": "loudness", "stat": "integrated", "target": "trk_vocals", "path": "solo", "section": "all" },
  { "id": "o_vox_mono", "primitive": "loudness", "stat": "integrated", "target": "trk_vocals", "path": "solo", "view": "mono", "section": "all" } ]
```

- 読み方: 2 つの差（`o_vox_mono` − `o_vox_st`）がモノにしたときの減り方である。`view: mono` は `(L+R)/2` を両チャンネルに置く見方なので、**位相の問題が無くても、中央から外したトラックは値が下がる**（等電力則で片側に振り切ったモノ素材なら約 −3 dB、中央なら 0 dB）。このパンによる通常の差を損失と数えず、損失として読むのは、パンから見込める差を超えて下がった分（逆相、幅の処理、左右の違う素材の打ち消し）である。床と結果でパンを変えていなければ、差の床から結果への変化を読むのが分かりやすい
- トラック対象の観察量はレベルマッチしない（§8.1）。主張・ガードに使うか、`tolerances` に並べるか、読むだけにするかは指揮者の裁量で、`mono_keep` を書いても観察量は求められない
- 既存の S-04・OF-5（低域のモノの検査）は変わらない。`mono_keep` はそれらに何も足さない

使わない場合: `frame` の無い指揮書の validate・適用記録・ミックス提案・outcome は従来とバイト同一で、`dir_` ID も変わらない（ID が変わるのは `frame` を書いた新しい指揮書だけ）。`tolerances` の無い `frame` は outcome を変えない。新しいゲートは形の検査（G-1）だけで、使ったかどうか・どのキーを書いたかを機械は検査しない。

当てになり度と固定の注記: 宣言は狙いの記述で、実測とずれても誤りではなく、減点もしない。役割は機械が決めない。宣言を書いたことで音が良くなることは実証していない。

範囲外: 宣言から手を導くこと、宣言の未記入の警告、`mono_keep` の自動測定、`section_roles` を床の重要度・役割に反映すること。

### 9.4 部屋の宣言（`scene.room`）

`scene`（§8.3）の任意のキー。どんな部屋で鳴っている音楽かを書き、部屋に当たるバスを指せる。

```json
"scene": { "sources": [ { "track": "trk_vocals", "azimuth": 0.0, "depth": 1 } ],
  "room": { "note": "どんな部屋で鳴っている音楽か（文）", "bus": "bus_room" } }
```

- `note` は必須、`bus` は任意。`scene` の他の規則（`sources` が必須で 1〜32 件など）は変わらない
- validate の検査（G-1。§8.3 の表に加わる行）:

| 条件 | where | コード |
|---|---|---|
| `room` が object でない（文字列を含む） | `scene` | `bad_value` |
| `note`・`bus` 以外のキー | `scene.room` | `bad_value` |
| `note` が無い／文字列でない／401 字以上 | `scene.room.note` | `missing_field`／`bad_value`／`param_range` |
| `bus` が `bus_` で始まる文字列でない | `scene.room.bus` | `bad_value` |
| `--project` つきで、既存のバスでも同じ指揮書の `bus_add` の対象でもない | `scene.room.bus` | `unknown_target` |

- **検査しないこと**: 指したバスに音源が送られているか、`place` の `room` と同じバスか、手の順序、宣言と響きの実測が合うか
- `direction check` は `room` があるときだけ、outcome の `scene` ブロックの末尾に `room` を書かれたまま写す。判定外で、主張・期待・ガード・`summary`・`--calibrate` は読まない

使わない場合: `room` の無い `scene` の validate・outcome は従来とバイト同一。新しいゲートは形の検査だけで、書いたかどうかを機械は検査しない。

当てになり度と固定の注記: 宣言は狙いの記述で、部屋の響きを測ったり作ったりはしない。部屋の印象が実際に出ることは実証していない。

範囲外: 部屋の響きのデータの読み込み、音源ごとの初期反射（§8.7）。

### 9.5 直さない出口（`triage`）

ブロックの任意欄（トップレベル）。見つけた問題を「直す」だけでなく、「差し替える」「生成し直す」「そのままにする」も正当な結論として書く置き場。

```json
"triage": { "decision": "leave",
  "options": [ { "choice": "regenerate", "gains": "（文）", "loses": ["気に入っている歌い回し"] } ],
  "findings": [ { "what": "（文）", "track": "trk_vocals", "t_s": 41.2, "status": "intentional", "basis": "（文）", "move": "m03" } ] }
```

- 語彙: `decision`・`options[].choice` は `fix`（直す）／`replace`（差し替える）／`regenerate`（生成し直す）／`leave`（そのまま）。`findings[].status` は `fix`（直す）／`unknown`（分からない）／`intentional`（意図した物）／`no_change`（変えない）
- 必須: `decision`。`options` の各項は `choice`・`gains`・`loses`、`findings` の各項は `what`・`status`・`basis`。`track`・`t_s`・`move` は任意。`options`・`findings` は省略・空配列でもよい
- validate の検査（G-1。形と範囲だけ）:

| 条件 | where | コード |
|---|---|---|
| `triage` が object でない／未知のキー | `triage` | `bad_value` |
| `decision` が無い／語彙の外 | `triage.decision` | `missing_field`／`bad_value` |
| `options` が配列でない／9 件以上 | `triage.options` | `bad_value`／`param_range` |
| 項が object でない・未知のキー／必須欄が無い | `triage.options[i]`（欠落は `.choice` 等） | `bad_value`／`missing_field` |
| `choice` が語彙の外、`gains` が文字列でない・401 字以上、`loses` が配列でない・17 件以上・要素が文でない | 各欄 | `bad_value`／`param_range` |
| `findings` が配列でない／65 件以上 | `triage.findings` | `bad_value`／`param_range` |
| 項が object でない・未知のキー／必須欄が無い | `triage.findings[i]`（欠落は `.what` 等） | `bad_value`／`missing_field` |
| `what`・`basis` が文字列でない・401 字以上、`status` が語彙の外 | 各欄 | `bad_value`／`param_range` |
| `track` が `trk_<stem>` でない／`--project` つきで無いトラック | `triage.findings[i].track` | `bad_value`／`unknown_target` |
| `t_s` が有限の数でない／負 | `triage.findings[i].t_s` | `bad_value`／`param_range` |
| `move` が同じブロックの手の ID でない | `triage.findings[i].move` | `bad_id` |

- **機械は判定しない。** `status: fix` に手が無いこと、`decision: leave` なのに手があること、`decision` と手の件数の整合、所見の網羅は検査しない。check・`--calibrate` は `triage` を読まず、outcome に何も足さない。パイプラインを止めない
- **手が 0 件の指揮書**: `"moves": []` と明記すれば、現状でも validate・apply・check を通る（apply は適用記録だけを書き、ミックス提案は作らない）。`moves` キーの省略は従来どおり `moves`／`missing_field` で拒否する（緩めない）。主張（`claims`）など他の必須欄の規則も変わらない。「そのまま」の結論は、`triage` と散文（分析メモ、`human_questions`）に残せる

使わない場合: `triage` の無い指揮書の validate・適用記録・ミックス提案・outcome は従来とバイト同一で、`dir_` ID も変わらない。新しいゲートは形の検査（G-1）だけで、書いたかどうかを機械は検査しない。

当てになり度と固定の注記: 直すか・差し替えるか・残すかの判断は指揮者とオーナーの物で、機械が「直すな」と言う根拠は無い。道具は差し替え・生成し直しを行わない。

範囲外: 判定の自動化、`triage` から手を導くこと、差し替え・生成し直しの実行。

### 9.6 側成分の見方（観察量の `view: side`）

観察量の任意欄 `view`（§3 の observations、追補 2）に `side` を足した。`(L−R)/2` を両チャンネルに置いてから測る。中央の成分（M）を見るのは既存の `view: mono`（`(L+R)/2`）で、`side` はその対になる見方である。

```json
"observations": [
  { "id": "o_side_hi", "primitive": "band_energy", "band_hz": [4000, 12000], "target": "master", "view": "side", "section": "all" },
  { "id": "o_pad_side", "primitive": "loudness", "stat": "integrated", "target": "trk_pad", "path": "solo", "view": "side" } ]
```

- 使える primitive は `band_energy`／`crest`／`loudness` の 3 つだけ。`band_hz`・`stat` 等は各 primitive の既存の規則のまま書ける
- 対象: `master` と `trk_*`（`path` の `dry`／`solo` のどちらも。§8.1）。§9.7 の対象 `mix` にも同じ規則で掛かる
- `direction query`（音声ファイル 1 本、`master`）、指揮書の `observations`（validate と check）、`direction stems observe` で同じ規則を使う（`query.view_spec` を共有）
- 結果: `side` の観察量の `value` と `gain_db` は小数 3 桁（既存の見方は従来どおり 4 桁）。`master` 対象の check では従来どおりレベルマッチのゲインを先に掛けてから側成分を取り出す。トラック対象はゲイン 0（§8.1）

検査（G-1。validate と query で同じ規則・同じ文）:

| 条件 | where | コード |
|---|---|---|
| `side` と、`band_energy`／`crest`／`loudness` 以外の primitive（`band_ratio`・`side_ratio`・`correlation`・`image_position`・`masking`・`wet_ratio`）の併用 | `observations.<id>.view` | `bad_value` |
| `side` と `view_band_hz` の併用（値が `null`・配列・数のどれでも、キーを書いた時点で拒否） | `observations.<id>.view_band_hz` | `bad_value` |

- `direction query` では同じ組み合わせが入力エラー（理由の文は validate の `bad_value` の文と同じ）。`stems observe`・check では、その観察量が音声を読む前に `status: error` になる
- **側成分が無音なら欠測**: 選んだ区間（`section` で切った後）で、側成分を両チャンネルに置いた信号の二乗和が 1e-20 以下なら `{"status": "error", "reason": "view 'side': the signal is silent in the range"}`。0 dB や下限の値で埋めない。曲全体に側成分があっても、選んだ区間だけ無音なら欠測になる。左右が同じ素材（モノ）は常に欠測
- **検査しないこと**: `side` を使ったか、M（`view: mono`）と組で書いたか。幅についての主張に `side` を求めない

使わない場合: `view` を書かない観察量、既存の値（`stereo`／`mono`／`mono_band`）の観察量の検査・結果・丸め桁・キー順は従来とバイト同一。新しい検査・変換・欠測は `view: side` を書いたときだけ働く。新しいゲートは形の検査（G-1）だけで、使ったかどうかを機械は検査しない。

当てになり度と固定の注記: 値の計算は既存の 3 つの primitive と同じで、測定の当てになり度もそれらと同じ。`band_energy` は既存どおり 2 チャンネルの平均に対して測るので、両チャンネルに同じ側成分を置いたこの見方では側成分そのものの帯域エネルギーになる。側成分の量が増えたことを、広がりが良くなった・音源を空間に置けたことと読まない（§8.2 の読み方の注記）。音が良くなることは実証していない。

範囲外: 側成分の帯域通過の見方（`view_band_hz`）、側成分に対する `side_ratio`／`correlation` 等の比の量、M/S の処理の手（op）。

### 9.7 段階の測定（`direction stems stages`）と観察量の対象 `mix`

帯域を 1 つ決めて、その帯域のエネルギーをトラックの段・足し合わせ・ミックスバス・描画済みマスターの順に並べる読み取り専用の下見と、ミックスバス出力を観察量の対象にする `target: "mix"`。どこで帯域の量が変わったか（チェーン、打ち消し合い、バスの処理、マスター段）を分けて読むための材料である。

**`direction stems stages --project <p> [--variant <v>] --band <lo,hi> [--section <id|json>] [--direction <md>]`**

```json
{ "kind": "direction_stem_stages", "variant": "v1", "band_hz": [300.0, 1000.0], "range_s": [0.0, 180.0],
  "tracks": { "trk_a": { "pre_chain_db": -60.535, "dry_db": -58.535, "chain_delta_db": 2.0 } },
  "sum_of_dry_db": -62.945, "cancellation_db": -5.049,
  "mix_db": -59.916, "master_db": -53.916, "master_minus_mix_matched_db": 0.0,
  "note": "値は各段の帯域エネルギーの記述で、良し悪しを言わない。読みは指揮者の〔推定〕",
  "reliability": { "band_energy": "high", "interpretation": "not_provided" },
  "large_boosts": [ { "move": "m03", "target": "trk_a", "freq_hz": 3000.0, "gain_db": 5.0, "rule": "R-06" } ],
  "large_boosts_note": "読む材料。拒否も警告もしない" }
```

| キー | 意味 |
|---|---|
| `variant` | 測った変種の ID（`--variant` 省略時はプロジェクトの最初の変種。変種が無ければ `null`） |
| `band_hz`・`range_s` | 測った帯域と時間範囲（秒） |
| `tracks.<trk>.pre_chain_db` | 整音後（クリップのゲイン・フェードの後）、トラックのチェーン・フェーダー・パンの前 |
| `tracks.<trk>.dry_db` | チェーン・フェーダー・オートメーション・パンの後（§8.1 の `dry` と同じ段） |
| `tracks.<trk>.chain_delta_db` | `dry_db − pre_chain_db`。チェーンだけでなく、その区間のフェーダー・パンの影響も含む |
| `sum_of_dry_db` | 各トラックの `dry` の信号を足した信号の帯域エネルギー |
| `cancellation_db` | `sum_of_dry_db − 10·log10(Σ 10^(dry_db/10))`（足した信号と、各トラックのパワーの和の差）。負なら打ち消し合い。相関して足し合わさる素材では正にもなる |
| `mix_db` | ミックスバス出力（センド・バスの処理・ミックスバスの処理の後、マスター段の前） |
| `master_db` | その変種の描画済みマスターの同じ帯域。`renders/<variant>/master__archive_f32.wav`（納品用の変換前の float の保存版）を優先し、無ければ既存の描画済みマスター（`hires_native`）。どちらも無ければ `null` で、`master_reason` に理由 |
| `master_minus_mix_matched_db` | マスターとミックスの**全曲の**積分ラウドネスをそろえた後の、指定区間・帯域の差（マスター − ミックス）。マスター段がこの帯域の釣り合いを変えた分。マスターが無ければ `null`、積分ラウドネスが測れなければ `null` と `master_match_reason` |

- 各段の値は既存の観察量 `band_energy`（`stat: mean`）と同じ計算（新しい測定器は無い）。数値は小数 3 桁、トラックは ID の辞書順
- `--band` は `lo,hi`（Hz、0 ≤ lo < hi、有限）。`--section` は床の提案の区間 ID か `{"t0_s", "t1_s"}` の JSON（省略・`all` は全長。既存の観察量の区間の規則）
- 対象は聞こえるトラックだけ（ミュート・ソロと変種の上書きは既存のレンダラーに任せる）
- **`--direction` を渡したときだけ** `large_boosts` と `large_boosts_note` を足す。その指揮書の手のうち、ブースト量が R-06 の一手の基準（`knowledge/mix_rules.json` の `eq.max_move_db`。読み取りだけで、毎回そこから読む）を**超える**物の一覧（等しい物は含めない）
  - 読む手: `chain_add` の `eq`（`gain_db`）と `dynamic_eq`（`range_db`）、`bus_add` の `params.chain` の中の同じ処理、`chain_param` で既存の `eq`／`dynamic_eq` に書いた変更（既存のパラメータに重ねて読む）。`notch`・カット・通常の `gain` は数えない
  - 範囲で書いた量は既存の `select` で 1 つの値に決めてから比べる（較正はしない）。`freq_hz` が書かれていなければ EQ の既定の 1000 Hz
  - 各行は `move`・`target`・`freq_hz`・`gain_db`・`rule`（`R-06`）。手の順、その手のチェーンの順
  - **読む材料で、拒否も警告もしない。** validate は呼ばれず、同じ指揮書の validate の出力は変わらない。§9.1.1 の「大きなブーストは居場所の合図」を読む手がかりで、新しい警告ではない

検査（G-3）: プロジェクト・kb・指揮書に何も書かない。整音キャッシュが無い・古いときは描画せずに入力エラー。マスターは作らない（描画済みの物を読むだけ）。入力エラー（終了コード 1）: `--band` が 2 数でない・範囲の外・有限でない、未知の区間、未知の変種、聞こえるトラックが 0 本、読めない指揮書。`--band` が数として読めないときは終了コード 2。

**観察量の対象 `mix`**: `direction stems observe` と指揮書の `observations` で `target: "mix"` を書くと、ミックスバス出力（上の `mix_db` と同じ信号）を測る。

```json
{ "id": "o_mix_low", "primitive": "band_energy", "band_hz": [40, 120], "target": "mix", "section": "all" }
```

- 使える primitive は単一の信号の 7 種（`band_energy`・`band_ratio`・`crest`・`loudness`・`side_ratio`・`correlation`・`image_position`）。`view`（`side` を含む）・`section`・`band_hz` の規則は `master` と同じ
- **レベルマッチはしない**: `level_match` の値に関わらずゲイン 0 で測る。結果は `gain_db: 0.0`、`signal: "mix_stage"` で、`path` は載らない。数値は小数 3 桁
- validate（G-1）: `masking`／`wet_ratio` との併用は `observations.<id>.target` に `bad_value`、`path` を書く（`null` を含む）と `observations.<id>.path` に `bad_value`。`stems observe`・check では同じ組み合わせが `status: error`
- **validate の扱いの変化**: 従来 `target: "mix"` は `unsupported` の警告（「only master」）が出て、check でも `unsupported` が返っていた。今は警告が出ず、check が床と結果の両方のミックスバス出力を測る（それぞれのプロジェクトの整音キャッシュから、メモリ上で描画する。描画済みの納品マスターを `mix` の代わりには使わない）。整音キャッシュが無い・古いときはその観察量が `status: error`（§8.1 と同じ）。`master`・`trk_*`・`mix` 以外の対象への従来の `unsupported` 警告は変わらない
- `direction query`（音声ファイル 1 本）は従来どおり `master` だけを測り、`mix` は `unsupported` を返す
- `--calibrate` は従来どおり `master` 対象の観察量だけを予測に使い、`mix` 対象の観察量（トラック対象と同じく）は読まない
- 読み方: check の `mix` 観察量は床と結果をそろえないので、差には全体の音量の変化がそのまま入る。マスター段の後の比較は `master` 対象（レベルマッチあり）で、マスター段の前の比較は `mix` 対象で見る、と分けて読める

使わない場合: `stems stages` を呼ばなければ何も変わらない。`target: "mix"` を書かない指揮書の validate・適用記録・ミックス提案・outcome は従来とバイト同一（`mix` を書いた既存の指揮書・テストが無いことは事前に確かめてある）。新しいゲートは形の検査（G-1）と読み取り専用の保証（G-3）だけで、下見を見たか、どの順で見たか、`mix` を使ったかを機械は検査しない。大きなブーストは validate の警告にしない（§9.1.1）。

当てになり度と固定の注記: `reliability` は固定で `{"band_energy": "high", "interpretation": "not_provided"}`（測定の値は既存の帯域エネルギーで、その解釈は道具が出さない）。`band_energy` は 2 チャンネルの平均に対して測るので、逆相の成分は各段で打ち消された後の量になる。`cancellation_db` は打ち消しの量の目安で、どのトラックの組が打ち消したかは言わない（組は `stems relate` や観察量で見る）。`master_minus_mix_matched_db` は全曲の積分ラウドネスでそろえた差なので、K 特性の影響（§9.1.7）を受ける。値は状態の記述で、どの段で直すべきかを言わない。音が良くなることは実証していない。

範囲外: 確認用のリミッターを別に通す経路（描画済みマスターとの比較で足りる）、マスターの描画、どのトラックが打ち消したかの特定、ブーストの量の提案・拒否、MCP への公開（今回は CLI だけ）。

### 9.8 居場所の表（`direction stems placement`）

床の提案の区間ごと・トラックごとに、帯域・活動・鳴り始め・持続・左右を 1 つの表にする読み取り専用の下見。「どのトラックがどの区間のどこにいるか」を並べるだけで、主役や役割は出さない。

**`direction stems placement --project <p> [--variant <v>] [--direction <md>]`**

```json
{ "kind": "direction_stem_placement", "signal": "mix_stage_dry",
  "sections": [ { "id": "s1", "t0_s": 0.0, "t1_s": 32.0 } ], "tracks": ["trk_a", "trk_b"],
  "cells": { "trk_a": { "s1": {
      "active_ratio": 0.0, "level_active_db": 0.0, "activity_share": 0.0,
      "bands": { "sub": 0.0, "bass": 0.0, "lowmid": 0.0, "mid": 0.0, "highmid": 0.0, "air": 0.0 },
      "occupied_hz": [0.0, 0.0],
      "onset": { "count": 0, "per_s": 0.0, "grid_offset_ms_median": null },
      "sustain": { "run_ms_median": 0.0 },
      "image_position": 0.0, "side_ratio_db": 0.0,
      "declared_roles": null } },
    "trk_b": { "s1": null } },
  "reliability": { "bands": "high", "active_ratio": "high", "onset": "medium", "sustain": "medium", "roles": "not_decided" },
  "note": "値は関係と配置の記述で、良し悪しを言わない。役割は機械が決めない。鳴り始めは密な素材で当てにならない。読みは指揮者の〔推定〕" }
```

- 信号は聞こえる全トラックの `dry`（§8.1）。区間は床の提案の区間を提案の順に使い（`start_s`／`end_s` を `t0_s`／`t1_s` に写す。音源の長さで切る）、床に区間が無いときだけ全長を `id: "all"` の 1 区間にする。トラックは ID の昇順、数値は小数 3 桁（`count` は整数）
- 各量はその区間で切り出した信号で測る:

| キー | 定義 |
|---|---|
| 活動フレーム（以下の基準） | 編集段と同じ 50 ms 窓・10 ms ホップのフレームの大きさ。その区間の、−70 dBFS より上のフレームの 95 パーセンタイルを活動レベルとし、それより 60 dB 下（編集段の `threshold_db` の既定値）以上のフレームを活動とする。区間をまたいで窓を取らない |
| `active_ratio` | 活動フレームの数 ÷ その区間の全フレームの数 |
| `level_active_db` | 活動フレームだけの平均二乗の平均（線形で平均してから dB。dB の平均ではない） |
| `activity_share` | その区間の全トラックの活動エネルギー（活動フレームの平均二乗の**和**）に占める、そのトラックの割合。活動率の差も入る。主役の**候補**を考える材料で、役割は出さない |
| `bands` | P-22 の 6 帯域（20／60／250／500／2000／6000／20000 Hz）へのエネルギーの割合（6 帯域の合計で割る。区間全体の信号で、活動でゲートしない） |
| `occupied_hz` | 累積エネルギーが 5% と 95% に達する周波数 `[下, 上]`（補間しない。20 Hz 未満・20 kHz 超のエネルギーも累積に入る） |
| `onset.count`・`per_s` | `direction ref study --add transient` のアタック検出（`director.refstudy` の `ATTACK_PEAK_MIN`／`ATTACK_MIN_GAP_S`）を全帯域・モノ和で使った鳴り始めの数と、区間の秒数（活動している時間ではない）あたりの数 |
| `onset.grid_offset_ms_median` | 最寄りの 16 分の格子（プロジェクトの時刻 0 を原点、間隔 60/BPM/4 秒）からのずれの中央値（ms、符号つき。遅いと正）。BPM と確度は既存の音楽解析のキャッシュ（`cache/remix/music_<key>.json`）を読むだけで、確度が 0.5 以上・BPM が正のときだけ出す。キャッシュが無い・古い・確度が足りない・鳴り始めが 0 件のときは `null`（解析し直さず、書かない） |
| `sustain.run_ms_median` | 活動フレームの連なり（連続した活動の区間。末尾は区間の端で切る）の長さの中央値（ms）。隙間の結合・最短長の足切りはしない |
| `image_position`・`side_ratio_db` | 区間全体の信号で、観察量の `image_position` と `side_ratio`（全帯域）と同じ計算 |
| `declared_roles` | `--direction` の指揮書の `frame.section_roles`（§9.3）のうち、その区間に当たる行を**書かれたまま**写した配列。当たる行が無い・`--direction` が無い・`section_roles` が無いときは `null` |

- その区間で活動フレームが 1 つも無いトラックのセルは、全体が `null`（`declared_roles` を含む）。`activity_share` の分母にも入らない
- `declared_roles` の写し方: 文字列の `section` は区間 ID と完全に一致する行（`all` は、床に区間が無く全長が `all` になるときだけ当たる）。時刻の `section` は、その区間と正の長さで重なる区間すべて（端が接するだけは当たらない）。行の `lead`・`roles`・`section`、順序・重複・他のトラックの宣言もそのまま写し、結合・上書きしない。宣言と実測の照合・判定はしない
- `--direction` の指揮書は読むだけ。`section_roles` の `lead` と `roles` のキーがプロジェクトに無いトラックなら入力エラー。それ以外の `frame` の検査はしない（validate の仕事）

検査（G-3）: プロジェクト・kb・指揮書・音楽解析のキャッシュに何も書かない。整音キャッシュが無い・古いときは描画せずに入力エラー（終了コード 1）。他の入力エラー（終了コード 1）: 未知の変種、指揮書の宣言の未知のトラック、読めない指揮書、聞こえるトラックが 0 本、長さの無い床の区間。曲資料（`direction dossier`）には載らない。

使わない場合: コマンドを呼ばなければ何も変わらない。既存のコマンドは居場所の表を読まない。新しいゲートは読み取り専用の保証（G-3）だけで、表を見たか、どの順で見たかを機械は検査しない。`frame.section_roles` を書いても、この表を作ることは求められない。

当てになり度と固定の注記: `reliability` と `note` は上の固定の値で、判定には使わない。帯域・活動は `high`、鳴り始めと持続は `medium`（密な素材・減衰の長い素材では鳴り始めの検出が外れ、連なりは編集段の活動の定義に引きずられる）、役割は `not_decided`（機械が決めない）。値は関係と配置の記述で、良し悪しを言わない。`activity_share` が大きいトラックが主役だとは限らない。格子のずれは BPM の推定と 1 つのテンポを前提にし、テンポが揺れる素材・ずらしの意図は区別しない。音が良くなることは実証していない。

範囲外: 曲資料への節の追加（`DOSSIER_VERSION` を動かさない）、役割・主役の自動決定、切り位置・譲らせ方の推奨、区間を指揮書の任意の時刻で切ること、MCP への公開（今回は CLI だけ）。

### 9.9 重なりの軸（`direction stems relate --axes`）

`direction stems relate`（§8.5）に `--axes` を付けたときだけ、既存の JSON の末尾にキー `axes` を足す。2 つのトラックが「帯域」「時間（鳴り始め）」「長さ（同時に鳴っている時間）」「左右」の 4 つの軸でどれだけ重なっているかを、組ごとに並べる。

**`direction stems relate --project <p> [--variant <v>] [--section <id|json>] [--top <n>] --axes`**

```json
"axes": { "pairs": [ { "a": "trk_a", "b": "trk_b",
      "band_overlap": 0.999, "co_onset_ratio": 1.0, "co_active_ratio": 1.0, "same_octave_time": 1.0, "image_distance": 0.0,
      "overlapping": ["band", "time", "length", "space"] } ],
  "all_axes": [ ["trk_a", "trk_b"] ],
  "thresholds": { "band": 0.5, "time": 0.5, "length": 0.5, "space": 0.25 },
  "reliability": { "band": "high", "time": "medium", "length": "high", "same_octave_time": "medium", "space": "high" },
  "note": "4 軸とも重なる組は、まず見る所の候補であって、問題の判定ではない。意図した重なり・一体感もある。前後（距離）の軸は測っていない" }
```

- 信号は既存の `relate` と同じ（聞こえる全トラックの `dry`、`--section` があれば切った物）。長さの違うトラックは末尾を無音で埋める。組はトラック ID の昇順の組み合わせを 1 回ずつ。数値は小数 3 桁
- 各量（活動フレームと鳴り始めの検出は §9.8 と同じ部品。ただし区間全体を 1 つとして測る）:

| キー（軸） | 定義 | 範囲 |
|---|---|---|
| `band_overlap`（帯域） | 2 つのトラックの 6 帯域の割合（§9.8 の `bands`）の、成分ごとの小さい方の和 | 0〜1 |
| `co_onset_ratio`（時間） | 鳴り始めが ±15 ms 以内（両端を含む）で一致する数（1 対 1 の対応）÷ 少ない側の鳴り始めの数。どちらかが 0 件なら 0 | 0〜1 |
| `co_active_ratio`（長さ） | 両方が活動しているフレームの数 ÷ 少ない側の活動フレームの数。分母が 0 なら 0 | 0〜1 |
| `same_octave_time`（補助） | 両方が活動しているフレームのうち、エネルギー最大のオクターブ帯（20 Hz から倍々の 10 帯、最上端は 20 kHz で打ち切り。50 ms 窓）が同じフレームの割合。共通の活動が無ければ 0 | 0〜1 |
| `image_distance`（左右） | 2 つのトラックの `image_position`（全帯域）の差の絶対値 ÷ 2。どちらかが無音で位置が無ければ `null` | 0〜1 |

- `overlapping` は情報用の基準を超えた軸の名前（`band`・`time`・`length`・`space` の順）。`band`／`time`／`length` は値が基準**より大きい**とき、`space` は `image_distance` が基準**より小さい**とき（近い）に入る。等しい値は入らない。比較は丸める前の値で行う。`image_distance` が `null` の組は `space` に入らない
- `same_octave_time` は補助の量で、5 番目の軸ではなく、`overlapping` にも入らない（同じ P-22 帯域の中でオクターブが違う組を見分ける読みの材料）。音高・基音の推定ではない
- `all_axes` は 4 軸とも入った組（`pairs` と同じ順）
- `thresholds` は基準値の写し。**基準値は情報用で、`director/relate.py` のコード内の定数**（`knowledge/` に置かない。ゲート定義のハッシュの対象でもない）。指揮書・フラグから変えるキーは無い。合成した純音のバーストで、完全に分かれた組・半分以上を共有する組・左右の端どうしを分ける線として置いた値で、知覚で確かめた値ではない

検査（G-3）: 既存の `relate` と同じ。プロジェクトに何も書かず、整音キャッシュが無い・古いときは描画せずに入力エラー（終了コード 1）。聞こえるトラックが 2 本未満・未知の区間・`--top` の範囲外は従来どおり入力エラー。

使わない場合: `--axes` を付けない `relate` の出力は従来とバイト同一（付けたときの出力から `axes` を除いた物も従来と同じ）。`axes` を計算する部品は、フラグがあるときだけ読み込まれる。新しいゲートは無く、軸を見たか・どの順で見たかを機械は検査しない。基準値はどの検査・目的関数・提案にもつながっていない。

当てになり度と固定の注記: `reliability` は固定で、判定には使わない（帯域・長さ・左右は `high`、鳴り始めに頼る時間の軸と `same_octave_time` は `medium`）。**4 軸とも重なる組は、まず見る所の候補であって、問題の判定ではない。** 意図した重なり・一体感もあり、重なりを減らすこと自体を目的にしない（§8.2 の `masking` の注記と同じ）。**前後（距離）の軸は測っていない。** 鳴り始めの検出は密な素材で当てにならず、モノ和で測るので逆相の成分は消える。音が良くなることは実証していない。

範囲外: 譲らせ方の提案、前後（距離）の軸の推定、区間ごとの軸（区間は `--section` で 1 つずつ見る）、基準値を指揮書・kb から変えること、MCP への公開（今回は CLI だけ）。

### 9.10 時間つきのゲイン列（`gain_curve`）と下見（`direction stems phrases`）

1 本のトラックに、時刻で区切った区間ごとのゲインを手で書く任意の op と、その手を書く前にフレーズの区切り・大きさ・伴奏との差を並べる読み取り専用の下見。§9.1.1 の段 2（手で形を整える）の手に `gain_curve` が加わる（§9.1.1 の表は変えない）。

**op `gain_curve`**（stage `mix`、対象はトラックだけ）:

```json
{ "id": "m05", "op": "gain_curve", "target": "trk_vocals",
  "params": { "ramp_ms": 20, "segments": [
      { "t0_s": 12.40, "t1_s": 14.10, "delta_db": 1.5, "why": "フレーズ頭が伴奏に埋もれる" },
      { "t0_s": 31.00, "t1_s": 31.60, "delta_db": -2.0, "why": "語尾だけ突出", "hold": true } ] },
  "basis": "（文）" }
```

| 欄 | 規則 |
|---|---|
| `params.segments` | 必須。1〜256 件。各項のキーは `t0_s`・`t1_s`・`delta_db`・`why`（必須）と `hold`（任意）だけ |
| `t0_s`／`t1_s` | 有限の数（秒）で `t0_s < t1_s`。区間どうしの重なりは拒否、接する（前の `t1_s` = 次の `t0_s`）のは可。並びの順は問わない |
| `delta_db` | 有限の数で −6〜+6 dB（両端を含む）。範囲 `[下限, 上限]` は書けない（較正の対象外） |
| `why` | 文字列、200 字まで（空文字も可） |
| `hold` | 真偽値。`true` の区間は書いたまま残し、音には掛けない |
| `params.ramp_ms` | 5〜200 ms（両端を含む）。省略時 20 |

- 手のキーは `id`・`op`・`stage`・`target`・`params`・`aim`・`basis`・`origin`・`expect`・`safeguard`・`section`・`select` だけ。`section` は値に依らず書けない（区間は `segments` で書く）
- validate の検査（G-2。固定の範囲で、指揮書から緩めるキーは無い）:

| 条件 | where | コード |
|---|---|---|
| 手の未知のキー | `moves.<mid>` | `bad_value` |
| `section` を書いた（`null`・`all`・区間 ID・時刻のどれでも） | `moves.<mid>` | `section_scope` |
| 対象が `trk_<stem>` でない（バス・`master`。`master` には既存の `invariant` も付く） | `moves.<mid>` | `bad_target` |
| `--project` つきで無いトラック | `moves.<mid>` | `unknown_target` |
| `params` が object でない／`ramp_ms`・`segments` 以外のキー | `moves.<mid>` | `bad_value` |
| `ramp_ms` が有限の数でない（bool・範囲の配列を含む）／5〜200 の外 | `moves.<mid>` | `bad_value`／`param_range` |
| `segments` が無い／配列でない | `moves.<mid>` | `missing_field`／`bad_value` |
| 件数が 1〜256 でない | `moves.<mid>` | `param_range` |
| 区間が object でない／未知のキー | `moves.<mid>.params.segments[i]` | `bad_value` |
| `t0_s`・`t1_s`・`delta_db`・`why` が無い | 同上 | `missing_field` |
| 時刻が有限の数でない／`t0_s ≥ t1_s` | 同上 | `bad_value` |
| `delta_db` が有限の数でない（bool・範囲の配列を含む）／−6〜+6 の外 | 同上 | `bad_value`／`param_range` |
| `why` が文字列でない／201 字以上 | 同上 | `bad_value`／`param_range` |
| `hold` が真偽値でない | 同上 | `bad_value` |
| 区間どうしの重なり | `moves.<mid>` | `bad_value` |

- **検査しないこと**: 区間の時刻が曲の長さに収まるか（曲の外の部分は折れ点列を作るときに切られる）、量の良し悪し、`why` の中身、`hold` の数、手を書く前に下見を見たか
- 評価段: 常に E2 以上（`origin: catalog`＋R-nn でも E1 にならない）。対象が主役（`trk_vocals`）なら E3 で、`listen_for` が無ければ既存の警告（`moves.<mid>`／`listen_for` と `listen_for`／`missing`）が出る。§4 の「主役への時間変化する処理」に当たる

実現（apply）:

- `hold` でない区間を、dB で区分線形の折れ点列にする。各区間は `[t0_s − ramp, 0]` → `[t0_s, delta_db]` → `[t1_s, delta_db]` → `[t1_s + ramp, 0]`（ramp = `ramp_ms`/1000 秒）。隣の区間との隙間が 2 × ramp より短いときは、0 dB へ戻らず、隙間の中点を中心にした 1 本の直線でつなぐ（つなぎの端は各区間の中点を越えないので、短い区間でも書いた値に届く）。折れ点はサンプル位置に丸め、曲の 0〜終端（`timebase.length_samples`）の外は切る。`hold: true` の区間は折れ点を作らない（全区間が `hold` なら折れ点は 0 件）
- 合成: 対象トラックの床のオートメーション、同じ指揮書の区間ゲイン（`gain`＋`section`）、`duck`、`gain_curve`（同じトラックに複数書いてもよい）を、この順に足して 1 本のオートメーションにする（§7.2 の U-23 と同じ厳密な和）。`owner: director`、`reason` は「floor + section gains + ducking + gain curves」、`move_ref` は床のオートメーションの `move_ref`（あれば）→ 区間ゲイン → `duck` → `gain_curve` の順の配列（重複は除く）。区間ゲインとは合成して拒否しない
- `gain_curve` のあるトラックでは、床のオートメーションに区間ゲインが当たっても拒否しない（合成する）。同じトラックの区間ゲインどうしが重なる・接するときの拒否（§5）は従来どおり。`gain_curve` の無いトラックの扱いは従来どおり（§5、§7.2）
- 適用記録: `moves[<mid>] = {op: "gain_curve", track, ramp_ms, segments, points}`。`segments` は書かれた区間の写しの末尾に `applied`（`hold: true` なら `false`、それ以外は `true`）を足した物（書かれていない `hold` は補わない）。`ramp_ms` は省略時 20。`points` はこの手の折れ点の数（折れ点列そのものはミックス提案のオートメーションにある）
- 適用記録の `notes` に手ごとに 1 行 `<mid>: 先に計算して書いても、見つけ間違いと直しすぎは起きる。効き目は実証していない` が出る（全区間 `hold` の手にも出る）
- `move_ref` の網羅（check）: `gain_curve` の手は、描画結果のオートメーションの `move_ref` に現れることを数える（適用記録があるだけでは足りない）。全区間 `hold` の手も、合成したオートメーションに `move_ref` が残る
- 較正（`--calibrate`）: 動かせる量を持たない（範囲が書けないので候補に入らない）。主張・期待は、手を分けず全体の結果で判定される（§5）

**`direction stems phrases --project <p> --track <trk> [--min-gap-ms <n>]`**

1 本のトラックの鳴っている所をフレーズに分け、大きさと、1〜4 kHz での他の全トラックとの差を並べる。ゲインの推奨値は出さない。

```json
{ "kind": "direction_stem_phrases", "signal": "mix_stage_dry", "track": "trk_vocals",
  "phrases": [ { "n": 1, "t0_s": 0.285, "t1_s": 0.715, "level_db": -23.324, "level_rel_median_db": 0.0,
      "head_db": -23.010, "tail_db": -29.031, "margin_db": 2.499 } ],
  "low_margin": [ { "t_s": 1.95, "margin_db": -12.041 } ],
  "reliability": { "phrases": "medium", "syllables": "not_provided" },
  "note": "先に計算して書いても、見つけ間違いと直しすぎは起きる。効き目は実証していない" }
```

| キー | 定義 |
|---|---|
| 信号 | そのトラックの `dry`（§8.1。プロジェクトの既定の変種。`--variant` は無い）。比べる相手は、他の聞こえる全トラックの `dry` をトラック ID 順に波形のまま足した和 |
| フレーズの区切り | §9.8 と同じ部品の活動フレーム（50 ms 窓・10 ms ホップ。ただし区間で切らず、トラックの全長の −70 dBFS より上のフレームの 95 パーセンタイルから 60 dB 下以上）の連なり。境目は最初と最後の活動窓の中心（信号の先頭・末尾に接するときは 0／信号の長さ）。隙間が `--min-gap-ms` より**短い**とき前後をつなぐ（等しいときはつながない） |
| `--min-gap-ms` | 有限の 0 以上の数（ms）。既定 250。0 はつながない |
| `n` | 1 始まりの番号 |
| `level_db` | フレーズ全体（つないだ隙間を含む）の全帯域 RMS（チャンネル平均のパワー、dBFS） |
| `level_rel_median_db` | `level_db` − 全フレーズの `level_db` の中央値 |
| `head_db`／`tail_db` | 先頭／末尾 150 ms の全帯域 RMS（フレーズが短ければその長さまで） |
| `margin_db` | そのトラックと相手の和を、それぞれ既存の 4 次・ゼロ位相の帯域通過（1〜4 kHz。観察量の `band_hz` と同じ部品）に通し、フレーズ内の平均パワーの dB の差（トラック − 相手）。dB の下限は観察量と同じ（1e-20）なので、相手が無音でも有限の値になる |
| `low_margin` | プロジェクトの時刻 0 から重ならずに並べた完全な 100 ms 窓のうち、中心がつなぐ前の活動の中にある窓の `margin_db`。小さい順（同値は時刻順）に最大 32 件。`t_s` は窓の中心。末尾の 100 ms に満たない窓は採らない |

- 数値は小数 3 桁。無音のトラックは `phrases: []`・`low_margin: []`
- 検査（G-3）: プロジェクト・kb・指揮書に何も書かない。整音キャッシュが無い・古いときは描画せずに入力エラー（終了コード 1）。他の入力エラー（終了コード 1）: 無いトラック・ミュート中のトラック、`--min-gap-ms` が負・非有限、サンプルレートの半分が 1 kHz 以下。`--min-gap-ms` が数として読めないときは終了コード 2。曲資料（`direction dossier`）には載らない

使わない場合: `gain_curve` の無い指揮書の validate・適用記録・ミックス提案・outcome は従来とバイト同一で、`dir_` ID も変わらない（区間ゲインが既存のオートメーションに当たったときの拒否も従来どおり）。`stems phrases` を呼ばなければ何も変わらない。新しいゲートは `gain_curve` の固定の範囲（G-2）と下見の読み取り専用の保証（G-3）だけで、`gain_curve` を使ったか、下見を見たか、どの順で見たかを機械は検査しない。区間ゲインと `duck` で同じことを書く自由は残る。

当てになり度と固定の注記: **先に計算して書いても、見つけ間違いと直しすぎは起きる。効き目は実証していない**（適用記録の `notes` と `stems phrases` の `note` の固定文。§9.1.5 の注意と同じ）。`reliability` は固定で `{"phrases": "medium", "syllables": "not_provided"}`（フレーズの区切りは活動の定義に引きずられ、音節は扱わない）。`margin_db` は帯域のパワーの差で、聴こえ方の真値ではなく、差が小さい所を上げるべき所とは読まない。下見の値はどの検査・目的関数・提案にもつながっていない。書いた量の結果は `direction check --edit-list`（§9.11）で床と並べて読める。

範囲外: 音節単位の区切り、チェーン前へのゲイン（レンダラーの変更が要る。欲しい場合は `tool_requests`）、先端と胴を別々に動かす処理、ゲインの推奨値、フレーズの区切りを指揮書に写すこと、MCP への公開（今回は CLI だけ）。

### 9.11 編集の一覧（`direction check --edit-list`）

`direction check` に `--edit-list` を付けたときだけ、outcome に判定外のブロック `edit_list` を足す。時間で動く手が、床と結果でそのトラックのその時刻をどう変えたかを 1 行ずつ並べる。`--translation`（§7.4）と同じ扱いで、どの判定にも入らない。

**`direction check --project <p> --floor <floor> <md> [--variant <v>] [--delivery <d>] [--translation] --edit-list [--contour]`**

```json
"edit_list": { "note": "参考値。どの判定にも入らない", "mode": "rows", "row_count": 3,
  "rows": [
    { "move": "m02", "track": "trk_keys", "t0_s": 1.0, "t1_s": 2.0, "amount_db": -2.0, "why": "（文）",
      "before_db": -23.010, "after_db": -25.010 },
    { "move": "m05", "track": "trk_vocals", "t0_s": 31.0, "t1_s": 31.6, "amount_db": 0.0, "why": "語尾だけ突出",
      "before_db": -23.010, "after_db": -23.010 },
    { "move": "m03", "track": "trk_bass", "key": "trk_kick", "hits": 12,
      "planned": { "depth_db": 3.0, "lead_ms": 5.0, "release": { "…": "適用記録の写し" } },
      "measured": { "band_drop_db_median": 1.627, "bottom_minus_onset_ms_median": 1.208 } } ] }
```

- 対象の手と行（手の順、手の中は区間の順）:

| 手 | 行 |
|---|---|
| `gain`＋`section`（`all` 以外） | 1 行。時刻は適用記録の `range_s`（無ければ床の区間から）、`amount_db` は適用記録の `delta_db`（無ければ指揮書の値。`gain_db` で書いた手は床のトラックのゲインとの差）、`why` は時刻の区間に書いた `why`、無ければ手の `basis` |
| `gain_curve`（§9.10） | 区間ごとに 1 行。`amount_db` は `delta_db`、`hold: true` の区間は実際に足す量の `0.0`。`why` は区間の `why` |
| `duck`（§7.2） | 手ごとに 1 行（下の形） |
| `edit_trim`／`edit_gate`（§7.1） | 台帳 `dir_<id>.edits.json` の受理された区間ごとに 1 行。区間の行に `op` と `applied`（台帳の状態が `applied` か）が付く。`amount_db` は `null`（無音化は有限の dB で書けない）。拒否された候補は載らない。戻した手も `applied: false` で残る |

- 量は適用記録を優先し、無ければ指揮書の値（範囲は既存の `select`、較正の選択があればそれ）を使う
- 区間の行の `before_db`／`after_db`: 床と結果の、そのトラックの `dry`（§8.1）の、その窓の平均パワー（チャンネル平均、dBFS）。レベルマッチはしない（マスターの揃えのゲインを掛けない）。窓は実在するサンプルに切り詰め、無音は −200.0、空の窓は `null`。測れないときは `measurement_errors`（`before_db`／`after_db` ごとの理由）を足す。同じトラックの全部の手の合成の結果を測るので、1 つの手だけの効果は分けない
- `duck` の行: `key`、`hits`（床のキーの整音後・チェーン前・フェーダー前の信号で、適用と同じ検出器で数えた打点の数。測れないときは適用記録の値）、`planned`（`depth_db`、`lead_ms` = `attack_ms`、`release` = 適用記録の戻りの写し）、`measured`:

| キー | 定義 |
|---|---|
| `band_drop_db_median` | 対象トラックの床と結果の `dry` を、キーの検出帯域（適用記録の `key_band_hz`）で帯域通過し、打点ごとに ±10 ms の平均パワーの dB を取った **床 − 結果** の中央値。**下がると正**で、`planned.depth_db`（正の量）と同じ向きで比べられる |
| `bottom_minus_onset_ms_median` | 同じ ±10 ms の中で、2 ms の移動パワー窓の「結果 − 床」の dB が最も小さい位置と打点の時刻の差（ms、遅いと正）の中央値。同値は打点に近い方、さらに同じ距離なら早い方 |

  - 床の帯域が無音（−199 dB 以下）の打点は集計から外す。測れないときは値が `null` で、`measurement_error` に理由
- 行が 512 を超えると `mode: "summary"` になり、手ごとに 1 行へまとめる: `{move, track, op, rows, t0_s, t1_s, amount_db_range, why, before_db, after_db}`（編集 op は `applied` も）。`t0_s`／`t1_s` は全区間を囲む窓、`before_db`／`after_db` はその窓全体（区間の間も含む）のレベル、`amount_db_range` は量の最小と最大（量が全部 `null` なら `null`）、`why` は手の `basis`。`duck` の行は同じ形のまま。`row_count` はまとめる前の行の数。512 行ちょうどまでは `mode: "rows"`
- 数値は小数 3 桁（非有限は `null`）。対象の手が無ければ `rows: []`・`row_count: 0`
- ブロック全体を、主張・期待・ガード・`summary`・`move_ref`・`--calibrate` のどれも読まない（`translation`・`scene` と同じ扱い）。描画済みのファイルが無く outcome が `incomplete` のときは従来どおりで、ブロックは足さない
- 検査: 新しいゲートは無い。`--edit-list` を付けたか、付けて何を読んだかを機械は検査しない。測定のためにメモリ上で `dry` 信号を描画するが、プロジェクトに書くのは従来どおり outcome だけ

使わない場合: フラグを付けない `check` の outcome は従来とバイト同一（測定の部品も読み込まれない）。付けたときの outcome から `edit_list` を除いた物も従来と同じ（`--contour`・`--translation` と同時に付けても、足されるのはそれぞれのキーだけ）。

当てになり度と固定の注記: 固定の `note` は「参考値。どの判定にも入らない」。`before_db`／`after_db` は合成した全部の手と、床と結果の違い全体の結果で、その行の手の効き目ではない。`band_drop_db_median` は ±10 ms の窓の平均なので、包絡の底だけを見た値より小さく出る（予定の深さと同じ値になることは求めない）。量が予定どおりに動いたことは、音が良くなったことの確認ではない（§9.1.4 の「測定上の到達」と同じ区別）。

範囲外: 1 つの手だけの効果の分離、量の良し悪しの判定、行を主張・ガードに使うこと、`edit_list` を指揮書の欄にすること、MCP への公開（今回は CLI だけ）。

### 9.12 曲線と空白（`direction check --contour`）

`direction check` に `--contour` を付けたときだけ、outcome に判定外のブロック `contour` を足す。床と結果の描画済みマスター（レベルマッチ後）で、区間ごとの大きさ・明るさ・低域・傾き、区間の落差、床の空白に結果で何が残ったかを並べる。`--translation` と同じ扱いで、どの判定にも入らない。

```json
"contour": { "note": "落差・傾き・空白が残ったかを見る参考値。大きいほど良いわけではない",
  "sections": { "s1": {
      "lufs_s_mean": { "floor": -20.0, "result": -20.5, "change": -0.5 },
      "side_ratio_db": { "floor": -10.792, "result": -10.792, "change": 0.0 },
      "bright_db": { "floor": 0.0, "result": 0.0, "change": 0.0 },
      "low_db": { "floor": -4.771, "result": -4.771, "change": 0.0 },
      "slope_db_per_s": { "floor": 0.5, "result": -0.25, "change": -0.75 } } },
  "steps": [ { "from": "s1", "to": "s2", "floor": 6.0, "result": 3.0, "change": -3.0 } ],
  "gaps": [ { "t0_s": 5.0, "t1_s": 5.5, "residual_db": { "floor": -103.010, "result": -65.010, "change": 38.0 } } ] }
```

- 信号: `check` が比べる描画済みマスター（`--delivery`）。結果には outcome の `loudness.level_match_gain_db`（床の LUFS-I − 結果の LUFS-I）を掛けてから測る（観察量の `level_match` の値に依らない）
- 区間: 床の提案の区間を提案の順に使い、床と結果を同じ時刻の窓で測る。床に区間が無ければ `sections: {}`・`steps: []`
- 各量（`floor`・`result` と `change` = 結果 − 床）:

| キー | 定義 |
|---|---|
| `lufs_s_mean` | 区間を切り出して測った短時間ラウドネス（3 秒窓・100 ms ホップ、区間の中に収まる完全な窓だけ）の有限値の算術平均。区間が 3 秒未満・有限値が無ければ `null` |
| `slope_db_per_s` | 同じ短時間ラウドネスの有限値を時刻に対して一次回帰した傾き（dB/秒、切片あり）。2 点未満なら `null` |
| `side_ratio_db` | 観察量 `side_ratio`（全帯域）と同じ計算 |
| `bright_db` | 観察量 `band_ratio` で 4000〜12000 Hz 対 250〜4000 Hz |
| `low_db` | 観察量 `band_ratio` で 20〜120 Hz 対 全帯域（0 Hz〜サンプルレートの半分） |

  - 帯域の量と側成分比は既存の観察量の部品で、測れない（区間が観察量の最短の長さに足りない等）ときは `null`
- `steps`: 隣り合う区間の `lufs_s_mean` の差（後の区間 − 前の区間）を床と結果で取り、`{from, to, floor, result, change}`。どちらかが `null` ならその値と `change` は `null`
- `gaps`（床で決める空白）: 床のマスターの 50 ms 窓・10 ms ホップの RMS（編集段のフレームと同じ）が、床の全フレームの 95 パーセンタイル − 30 dB を**下回る**（等しい物は入らない）フレームの連なりを、最初のフレームの始まりから最後のフレームの終わりまでの窓にする。長さが 80 ms〜2 s（両端を含む）の窓だけを、時刻順に最大 16 件。2 s を超える連なりは分けずに除く。床が全部無音なら空
- `residual_db`: その窓の全帯域 RMS（チャンネル平均、dBFS）。完全な無音は −200.0。結果はレベルマッチのゲインを掛けた後の値なので、`change` には揃えのゲインが入る
- 差は丸める前の値で取り、出す数値は小数 3 桁
- ブロック全体を、主張・期待・ガード・`summary`・`move_ref`・`--calibrate` のどれも読まない。床の評価の項 P-20 とは別の物で、床の評価・目的関数には入らない。描画済みのファイルが無く outcome が `incomplete` のときは従来どおりで、ブロックは足さない
- 検査: 新しいゲートは無い。`--contour` を付けたか、何を読んだかを機械は検査しない

使わない場合: フラグを付けない `check` の outcome は従来とバイト同一（測定の部品も読み込まれない）。付けたときの outcome から `contour` を除いた物も従来と同じ（`--edit-list`・`--translation` と同時でも同じ）。

当てになり度と固定の注記: 固定の `note` は「落差・傾き・空白が残ったかを見る参考値。大きいほど良いわけではない」。落差・傾きを大きくすること、空白の残りを小さくすることを目的にしない。比べるのは全曲の積分ラウドネスでそろえた後の値なので、K 特性の影響（§9.1.7）を受け、`low_db` の変化には揃えのゲインの違いも混ざりうる。空白は床のマスターから決めるので、結果で新しくできた空白は数えない。区間の短時間ラウドネスは 3 秒未満の区間で `null` になる。音が良くなることは実証していない。

範囲外: 合否・許容幅の判定（量を主張にしたいときは既存の主張で `master` 対象の観察量を立てられる）、結果で新しくできた空白の検出、区間を指揮書の任意の時刻で切ること、P-20 の定義の変更、MCP への公開（今回は CLI だけ）。

### 9.13 配線の図（`direction wiring`）

プロジェクトの現状から、トラック・バス・マスターの経路、センド、ダッキングの引き金と相手、各節の処理の並びを導き出す読み取り専用のコマンド。図は**導出であって宣言ではない**ので、指揮書に新しい欄は足さない。指揮者は出力を散文（分析メモ等）に貼ってよい。

**`direction wiring --project <p> [--variant <v>] [--direction <md>] [--format json|mermaid]`**

```json
{ "kind": "direction_wiring", "variant": "v1",
  "nodes": [
    { "id": "bus_room", "type": "bus", "planned": false,
      "chain": [ { "type": "reverb", "planned": false, "lowcut_hz": 600.0, "highcut_hz": 6000.0 } ], "planned_moves": [] },
    { "id": "master", "type": "master", "planned": false, "chain": [], "planned_moves": [] },
    { "id": "trk_vocals", "type": "track", "planned": false, "chain": [ { "type": "eq", "planned": false } ], "planned_moves": [] } ],
  "edges": [
    { "type": "route", "source": "trk_vocals", "target": "bus_mix", "planned": false },
    { "type": "send", "source": "trk_vocals", "target": "bus_room", "level_db": -18.0, "pre_fader": false, "planned": false },
    { "type": "duck", "source": "trk_kick", "target": "trk_bass", "depth_db": 3.0, "attack_ms": 5.0,
      "release_ms": 180.0, "release_note": "1/8", "band": "full_band", "key_band_hz": [40.0, 120.0],
      "planned": false, "move": "m03", "direction": "dir_xxxxxxxxxxxx" } ],
  "note": "プロジェクトから導出した配線であり、宣言ではない。帯域を限ったダッキングとバスを相手にしたダッキングは未対応。",
  "reliability": { "routing": "high", "duck": "project_provenance", "planned": "not_applied" } }
```

- 節（`nodes`）: プロジェクトのトラックとバス（変種の上書きを既存の規則で反映した後。ID の順）と `master`。各節は `{id, type: track|bus|master, planned, chain, planned_moves}`。`chain` は処理の種類を音の処理順に並べ、`reverb` には `lowcut_hz`／`highcut_hz`、`filter` には `kind`／`freq_hz` を、省略された値はプロセッサの既定値で埋めて載せる（他の処理のパラメータは載せない）。`master` の `chain` はその変種のマスター段の処理
- 辺（`edges`）:

| `type` | 中身 |
|---|---|
| `route` | 各トラック・バスの出力先（`output`、無ければミックスバス）。ミックスバスの出力先は `master` |
| `send` | トラックからバスへのセンド。`level_db`、`pre_fader` |
| `duck` | 引き金（`source` = キー）→ 下がる側（`target`）。`depth_db`、`attack_ms`（打点の手前）、`release_ms`／`release_note`（戻り）、`band: "full_band"`（対象は全帯域で下がる。§7.2 の限界）、`key_band_hz`（キーの検出帯域）、`move`、`direction` |

- ダッキングの辺を出す条件（合成したオートメーションからはキーも時間も戻せないので、出どころの記録を読む）:
  - 床のダッキング: 床のミックス提案で採られた R-11 のオートメーションが、今もそのまま対象トラックに残っているときだけ。キーは床の測定の時間軸のキック、`key_band_hz` は `[40.0, 120.0]`、`direction: null`
  - 指揮書のダッキング: `directions/dir_*.apply.json` の `duck` の記録のうち、対象トラックのオートメーションの `move_ref` に `dir_<id>/<mid>` が今も残っている物だけ。古い記録だけの手は辺にしない
- `--direction` を渡すと、その指揮書の手のうち、まだ適用されていない手（同じ ID の適用記録に無い手）を `planned: true` で重ねる:
  - `bus_add` → 節（`planned: true`）と出力先への `route` 辺を先に足す
  - `send` → `send` 辺（`level_db` の既定 −15.0）。`duck` → `duck` 辺（パラメータは既存の `duck` の検査を通し、既定値と戻りの音価は既存の規則で決める。打点は検出しない）。`chain_add` → 対象の節の `chain` の末尾に足す。`place` → `planned_moves` に導出値つきで載せ、展開される `send` と `chain_add` も重ねる（§8.4）
  - その他の手 → 対象の節の `planned_moves` に `{op, move, params, planned: true}`（`replaces`・`section` があれば写す）。`master_target` は `master` の節に載せる
  - 範囲で書いた量は既存の `select` で 1 つの値に決める（較正はしない）
- 並び: 節は ID の順、辺は出どころ・行き先・種類・`planned`・指揮書・手の順。数値は小数 3 桁。同じ入力からは同じバイト列
- `--format mermaid`: 同じ節と辺を mermaid の `flowchart LR` の文字列にして、そのまま標準出力に書く（JSON で包まない）。節の ID は並びの順の連番、ラベルは各節・辺の JSON（図の記法と衝突する文字は mermaid の実体参照に置き換える）。今ある経路とセンドは実線、`planned` の辺とダッキングは点線。`kind`・`variant`・`note`・`reliability` は 1 行目の後のコメントに入る。このコマンドの `--format` は `json`（既定）と `mermaid` だけ（`text` は入力エラー）
- 検査（G-3）: プロジェクト・kb・指揮書に何も書かない。メタ情報だけを読み、音声の描画・整音キャッシュの生成はしない（整音キャッシュが無いプロジェクトでも導出できる）。入力エラー（終了コード 2）: 未知の変種、`--format` の未知の値、読めない指揮書、重ねる手の対象が無い（`unknown_target`）、`duck` のパラメータの誤り（既存の検査の文）、キー・対象がトラックでない `duck`

使わない場合: コマンドを呼ばなければ何も変わらない。既存のコマンドは配線の図を読まず、指揮書・適用記録・outcome の形も変わらない。新しいゲートは読み取り専用の保証（G-3）だけで、図を作ったか、散文に貼ったかを機械は検査しない。

当てになり度と固定の注記: `note` と `reliability` は上の固定の値で、判定には使わない（経路は `high`、ダッキングは出どころの記録に頼る `project_provenance`、重ねた手は `not_applied`）。帯域を限ったダッキングとバスを相手にしたダッキングは現行に無く、図にも出ない。重ねた手は適用前の予定で、適用の結果（打点の数、合成したオートメーション、範囲の較正）は表さない。図を書いたことで音が良くなることは実証していない。

範囲外: 図を宣言として指揮書に書く欄、図からの手の導出、処理のパラメータの全部の表示、打点の検出、画像への描画、MCP への公開（今回は CLI だけ）。

### 9.14 §8.7 の更新

§8.7 の表の行は変えない。追補 4 で入った物と、引き続き範囲外の物をここに並べる。§8.7 の他の行（ステム内の成分の再分離、`masking` などを目的関数・較正に入れること、R-22 の制限の強制、曲資料への純度・被りの節の追加、`direction check` での台帳指標の測り直し）は §8.7 のまま範囲外である。

入った物（どれも任意で、使わなくても不利にならない。音が良くなることは実証していない）:

| 入った物 | 節 | §8.7 との関係 |
|---|---|---|
| 名前を隠した聴き比べの書き出しと聴取記録（`direction listen pack／record`。等級は機械が付ける） | §9.2 | 「耳の評価を集める仕組み（盲検比較など）」のうち、書き出しと 1 回ずつの記録だけが入った。再生・ABX・集計は入っていない |
| 枠の宣言 `frame`、直さない出口 `triage` | §9.3、§9.5 | — |
| 部屋の宣言 `scene.room` | §9.4 | 宣言だけ。「音源ごとの初期反射」と部屋の響きを作ることは入っていない |
| 観察量の `view: side`、観察量の対象 `mix`、段階の測定 `direction stems stages` | §9.6、§9.7 | — |
| 居場所の表 `direction stems placement`、重なりの軸 `direction stems relate --axes` | §9.8、§9.9 | 下見だけ。「曲資料への純度・被りの節の追加」は入っていない |
| 時間つきのゲイン列 `gain_curve` と下見 `direction stems phrases` | §9.10 | トラックの中の時刻ごとのゲインだけ。「区間ごとの処理・パンの切替」は入っていない |
| 編集の一覧 `direction check --edit-list`、曲線と空白 `direction check --contour` | §9.11、§9.12 | 判定外のブロック |
| 配線の図 `direction wiring` | §9.13 | 導出であって宣言ではない |
| kb のカードの任意欄（立場 `stance`、work の `aim_note`） | `kb/README.md` | `kb lint` は型だけを見る |

引き続き範囲外（DSP・レンダラーに及ぶ物と、読み取り専用でも次の段階に回した物。どれもオーナーの着手判断の後で、今回は作らない）:

| 項目 | 理由 | 現状で代わりに出来ること |
|---|---|---|
| 帯域を限ったダッキング（対象の側の帯域だけを下げる） | DSP とレンダラーの追加が要る。既定値で恒等になること・床が同一であることのテストが先 | `duck` は全帯域で下げる（指定できるのはキーの検出帯域だけ。§7.2）。帯域の動的な処理は `chain_add` の `dynamic_eq` |
| バスを相手・キーにしたダッキング | 同上 | トラックどうしの `duck`。現行に無い手は `tool_requests` に書く（§7.2） |
| 部屋の響きのデータの読み込み、音源ごとの初期反射 | DSP の追加と、データのライセンス・記録の条件を先に決める | `scene.room` で宣言する（§9.4）。トラックのチェーンに短い `reverb` を手で置く（§8.7） |
| 手を 1 つ外した版との比較 | 較正の予測経路を使う別の下見で、次の段階に回した | 手を外した指揮書を床の新しい写しに適用して `check` で比べる。`check --edit-list` は手ごとの行を並べるが、1 つの手の効果は分けない（§9.11） |
| 指揮書のばらつきの集計（同じ入力から書いた複数の指揮書の幅） | 実施の費用の判断が先 | 指揮書と outcome を並べて読む。再指揮と再レンダーは §9.1.4 の用語で区別する |
| 出来事尺度（短い窓の最大・上位パーセンタイルの `stat`） | 既存の `stat` の値を変えずに足す別件 | 既存の `stat` と `crest` |
| キックの間の低域の谷の測定、孤立した 1 発の形の測定 | 読み取り専用の下見だが、次の段階に回した | `direction stems relate --axes`、`direction stems placement` の鳴り始め |
| 前後 2 本を時間と音量で合わせた比較 | 依頼が決まってから作る | `direction ref compare`（§6.1） |
| 時間で動くパン、区間ごとの処理・パンの切替 | §8.7 のまま | 静的配置、区間ゲイン、`duck`、`edit_gate`、`gain_curve`（§9.10） |
| 聴き比べの再生・ABX・聴取結果の集計と重みの較正 | §8.7 の「道具でなく運用の話」のまま（§9.2 の範囲外） | 聴取記録に残す（§9.2） |
| 追補 4 のコマンドの MCP への公開 | 今回は CLI だけ | CLI で使う |

### 9.15 実装追補の読み方

この追補はツール実装で追加された表面を記す。§9.14までの記述は当時の範囲として残し、追加分は以下を優先する。型の現在の真偽は [実装状況](tool_impl/README.md) の生成表、パラメータの宣言は `describe()`、op・コマンドの在否は登録表を正とする。未登録の予定名を、実行可能な手として使ってはならない。

direction 層のコマンドは CLI 専用（統括の判断 D-24）。MCP の計画名はツールの公開を意味しない。提案・観察値の出力と適用は別操作で、数値の到達は音が良くなったことの確認ではない（DESIGN_PHILOSOPHY §5.2）。GUI の音符表示・領域選択・メータ画面は、API追加がcore差分0と両立しないため OQ-3（D-28）で保留。数値をCLI・プロセッサへ渡す経路を使う。

使わない場合：新しい型・op・コマンド・観察量を使わない入力の結果は従来とバイト同一。下見の実施・順序・回数や、出力を読んだかは検査しないこと。新しい音質ゲートや必須の手順を足さない。

### 9.16 曲線ダッキング（`duck_curve`）

`duck` を残したまま別opとして追加する。`stage: mix`、`target` はトラックまたはバス、`params.key` は別のトラック。masterは不可。`section` は指定しない。キーの検出条件・attack・release・release_noteは既存 `duck` と同じで、加えて次を指定する。

| パラメータ | 範囲・既定・意味 |
|---|---|
| `depth_db` | 0.5〜12 dB、既定3。範囲とselectも使える |
| `hold_ms` | 0〜500 ms、既定0 |
| `shape` | 1〜32個の `[x,y]`、各0〜1、xは狭義増加、yは非減少。既定 `[[0,0],[1,1]]` |
| `band_lo_hz` / `band_hi_hz` | 両方0（既定）は全帯域。それ以外はlo 20〜8000 Hz・hi 60〜20000 Hz、hi≥1.5×lo、描画時の帯域条件も満たすこと |

全帯域トラックは既存のゲイン列へ合成し、床→区間gain→duck＋duck_curve→gain_curveの順に加算する。帯域限定は `band_automation`、全帯域バスは合成した1本の `gain_automation` をチェーン末尾へ置く。後者はカタログ外の補助型（D-18）。使わないバスのチェーンへは追加しない。

適用記録にはshape・hold・帯域・打点一覧・戻りの記録と、対象の処理前後の測定を残す。測定のscopeは `combined_direction_on_target` で、同時に当てた全手の結果である。手1つの因果的な効果とは解釈しない。

使わない場合：`duck_curve` を書かない入力の提案・適用結果は従来とバイト同一。既存 `duck` の意味は変わらない。検査しないこと：このopを採ったか、帯域限定を採ったか、数値を音質の改善と読んだか。検査するのは入力値と既存の適用契約である。

### 9.17 追加opの登録と適用

以下は追補のop名の一覧。`target` は手の直下、各処理の値は `params` に書く。「必須」は登録宣言上の必須欄であり、params内の条件は続く説明と各specによる。新opの範囲指定は各plannerが解決し、自動較正の新しいつまみにはしない。

#### W4d受入後の登録表（W6b追補）

以下を現在の登録表とする。W4dの6編集opは登録・受入済みで、詳細は§9.21〜§9.26。既存文を残すため、W6a時点の表と停止説明は下の折り畳みに保存する。その「未登録」「停止」は当時の状態を表し、現在の在否には使わない。

<!-- tool-ops:begin -->
| op | 段 | 必須欄 | 登録状態 | 中身 |
|---|---|---|---|---|
| `duck_curve` | mix | target, params | 登録済み | §9.16 |
| `breath` | mix | target | 登録済み | ブレス候補を検出しフェーダーの線を書く |
| `drum_replace` | mix | target, params | 登録済み | 打点ごとのサンプルを足したトラックを作る |
| `edit_debleed` | edit | target, params | 登録済み | 指定した被り元から除去用パワーを推定する |
| `edit_isolate` | edit | target | 登録済み | 既存の分離モデルによる声／背景の抽出 |
| `edit_pitch` | edit | target, params | 登録済み | 音符ごとの音高・揺れ・音色・時刻・ゲイン |
| `level_phrases` | mix | target | 登録済み | 句内は一定、休止中に切り替わるゲイン列 |
| `ride` | mix | target | 登録済み | レベルを追う有界・傾き制限つきゲイン列 |
| `vocode` | mix | target, params | 登録済み | 外部キーの包絡で搬送トラックを処理する |
| `edit_stretch` | edit | target, params | 登録済み | T08-10。§9.21 |
| `edit_stretch_extreme` | edit | target | 登録済み | T08-11。§9.22 |
| `edit_varispeed` | edit | target, params | 登録済み | T08-12。§9.23 |
| `edit_reverse` | edit | target, params | 登録済み | T09-06。§9.24 |
| `edit_fade` | edit | target, params | 登録済み | T12-04。§9.25 |
| `edit_normalize` | edit | target, params | 登録済み | T12-05。§9.26 |
| `edit_align_time` | edit | target, params | 登録済み | T11-01。ガイドに対する時間写像 |
| `edit_align_pitch` | edit | target, params | 登録済み | T11-02。ガイドに対する音高と時間の写像 |
| `edit_quantize` | edit | target, params | 登録済み | T11-07。一定テンポの打点の量子化 |
<!-- tool-ops:end -->

<details>
<summary>W6a時点の登録表・停止説明（履歴）</summary>

<!-- tool-ops:begin -->
| op | 段 | 必須欄 | 登録状態 | 中身 |
|---|---|---|---|---|
| `duck_curve` | mix | target, params | 登録済み | §9.16 |
| `breath` | mix | target | 登録済み | ブレス候補を検出しフェーダーの線を書く |
| `drum_replace` | mix | target, params | 登録済み | 打点ごとのサンプルを足したトラックを作る |
| `edit_debleed` | edit | target, params | 登録済み | 指定した被り元から除去用パワーを推定する |
| `edit_isolate` | edit | target | 登録済み | 既存の分離モデルによる声／背景の抽出 |
| `edit_pitch` | edit | target, params | 登録済み | 音符ごとの音高・揺れ・音色・時刻・ゲイン |
| `level_phrases` | mix | target | 登録済み | 句内は一定、休止中に切り替わるゲイン列 |
| `ride` | mix | target | 登録済み | レベルを追う有界・傾き制限つきゲイン列 |
| `vocode` | mix | target, params | 登録済み | 外部キーの包絡で搬送トラックを処理する |
| `edit_stretch` | edit | — | 未登録 | T08-10。W4dの受入待ち |
| `edit_stretch_extreme` | edit | — | 未登録 | T08-11。W4dの受入待ち |
| `edit_varispeed` | edit | — | 未登録 | T08-12。W4dの受入待ち |
| `edit_reverse` | edit | — | 未登録 | T09-06。W4dの受入待ち |
| `edit_fade` | edit | — | 未登録 | T12-04。形状・crossの共通口が未解決 |
| `edit_normalize` | edit | — | 未登録 | T12-05。groupを含む受入待ち |
| `edit_align_time` | edit | target, params | 登録済み | T11-01。ガイドに対する時間写像 |
| `edit_align_pitch` | edit | target, params | 登録済み | T11-02。ガイドに対する音高と時間の写像 |
| `edit_quantize` | edit | target, params | 登録済み | T11-07。一定テンポの打点の量子化 |
<!-- tool-ops:end -->

W4dの6 opは、フェード形状・crossの配置変更・groupの静的ゲインに必要な共通口の不足で製品opを追加せず停止した。未登録行は仕様上の予定名であり、上記の適用契約を満たした実装済み機能には数えない。

</details>

`ride`・`level_phrases`・`breath` はトラックを対象に `section` を使える。処理前後の分布・選択した句や候補・適用量・作用しなかった理由を適用記録に残す。

- `ride`：`mode: self|against`（既定self）。selfは活動中の中央値、againstは `params.against` の別トラック／バスに対するレベル差を使う。上げ／下げの範囲は各0〜6 dB・既定2、窓400 ms、平滑300 ms、最大傾き12 dB/秒が既定。無音の区間では線を保持し、section外は0。
- `level_phrases`：`measure: lufs_phrase|lufs_short_max|rms`（既定lufs_phrase）、`amount` は0〜1・既定0.7、上げ／下げは各0〜18 dB・既定6。`to_lufs` 省略時は活動レベルから決める。短い句で短時間ラウドネスが測れなければ句の積分値へ、それも無ければゲイン0と理由を記録する。ノイズ床や休止のないsection端では上げない場合がある。
- `breath`：`mode: reduce|target`、既定reduce、`reduce_db` は0〜24・既定6、`target_db` は−40〜−6・既定−24。`only`／`skip` は `query breaths` の安定ID配列。low候補は既定で作用せずonlyで選べる。固定特徴の重みは合成素材でのみ較正済みで、出力の `calibration: synthetic_only` を保つ。confidenceは実録音での検出確率ではない。

`drum_replace` は `params.samples` に許諾・ハッシュを確認できる登録サンプルを指定する。最大8層、同一min_velocityの宣言順をround robinに使える。velocity曲線、only/skip、極性・位相合わせ、元音との比を記録する。適用は新しいトラック・音声資産・クリップを追加し、元資産は保持する。該当層のない弱打は理由を記録して配置しない。取り消し後の未使用資産・cache・履歴は残る。

`vocode` はtargetが搬送、`params.key` が別のトラック。既定はbands16、lo100/hi8000 Hz、attack5/release40 ms、formant_shift0、depth1。キーのチャンネルごとの包絡を平均したmonoの制御資産を記録し、`band_envelope` へ渡す。mono和の位相打消しで包絡を消さない。両トラックの資産・パラメータ・版・ハッシュを再生成用に残す。

編集opは原素材を上書きせず、派生資産または既存クリップ欄の変更計画として適用する。台帳は `directions/dir_<id>.edits.json`、処方には出典資産・パラメータ・コード版・ハッシュが入り、`direction edit revert` は適用順の逆に戻す。元資産や配置が変わった古い記録は拒否する。groupを返す場合は共有の写像と全メンバーの整合を検査する。

- `edit_pitch`：`params.notes` の時刻t0/t1はクリップ内の秒。有効クリップ1個に限定し、音符は時刻順・非重複。中立はshift_cents0・flatten0・vibrato1・formant_cents0・move_ms0・gain_db0。結果が同一なら派生音声を作らない。GUIの音符表示は保留。
- `edit_debleed`：`params.sources` はtarget以外の重複しない1〜8トラック。reduction_dbは0〜30・既定9、max_delay_msは0〜50・既定20。対象が静かで被り元が活動中の区間で伝達を推定し、資料不足なら作用せずlowとする。共有成分の推定値を実際の漏れ量や完全分離と同一視しない。
- `edit_isolate`：`keep: voice|background`（既定voice）、strength0〜1（既定1）、residual_db −90〜0（既定−90）。vocals出力のある登録モデルを使う。モデルID・重みハッシュ・許諾・保持／除去／再構成誤差を記録し、取得は行わない。通常の重みなし試験は実モデルの品質検証ではない。
- `edit_align_time`／`edit_align_pitch`：`params.guide` に別トラックを指定し、単調な共有時間写像を計算する。anchorsは選択区間に対するtarget秒／guide秒の組。groupは同じ写像を各トラックへ適用する。恒等・作用量0は派生を作らない計画で表す。pitch側は音高と時刻の変更を一度の処理で行う。計算結果と推定の留保を台帳に残す。
- `edit_quantize`：一定テンポのbpm20〜400、grid_note（既定1/16）、strength0〜1（既定0.7）、mode:slice/stretch（既定slice）。検出元detect_fromとonly/skipを指定でき、同距離のグリッドは早い方。groupは共通の切り位置・写像を使う。テンポマップの追跡や打点が音楽的に正しいことは保証しない。

使わない場合：新opを書かない入力の提案・適用・outcomeは従来とバイト同一。新しい記録・資産は使用時だけ作る。検査しないこと：特定opの採用・回数・順序、推定値を見てどう判断したか。既存のE2/E3・listen_forの扱いと入力・台帳の整合検査は維持する。

### 9.18 追加した下見コマンド

共通の `--project`・`--format` などは既存どおり。下表のコマンドは提案や測定を返すだけで、採用や適用はしない。`writes=False` は読み取り専用、`out_only` は `--out` を省略するとJSONだけ、指定すると明示出力だけを書く契約。プロジェクト・journal・指揮書台帳への書き込みを検出し、失敗時も検査する。出力先を指定しただけで正本を更新しない。

<!-- tool-commands:begin -->
| コマンド | 主な引数 | 書き込み契約 | 登録状態 | 出力・留保 |
|---|---|---|---|---|
| `direction suggest eq` | --target TRK [--against ID] [--refsheet MD または --ref-kb ID...] | False | 登録済み | 候補・測定根拠・confidence。候補を適用しない |
| `direction ref matcheq` | --target ID --ref AUDIO_OR_WORK [--smooth-oct N] [--max-db N] | False | 登録済み | 平滑した差の曲線とfir_eq候補。波形の一致ではない |
| `direction suggest lowend` | [--target ID] (--refsheet MD または --ref-kb ID...) | False | 登録済み | 低域の分布と限った量の候補。参照を目標値にはしない |
| `direction ref balance` | [--audio FILE] (--refsheet MD または --ref-kb ID... または --ref FILE...) | False | 登録済み | 4帯域／細分帯域の分布、量をそろえた偏差・時系列 |
| `direction suggest align` | --tracks IDS [--reference ID] [--mode delay または delay_polarity または phase] [--preset drums] | False | 登録済み | 遅れ・極性・根拠とtime_align候補 |
| `direction extract midi` | --target TRK --kind drums または mono [--out FILE] | out_only | 登録済み | 音符・打点の数値。明示outだけSMFファイルも保存 |
| `direction pitch notes` | --target TRK [--section ID_OR_JSON] [--lo-hz N] [--hi-hz N] [--a4 N] | False | 登録済み | 音符ID・時刻・音高・confidence。GUI表示は保留 |
| `direction query onsets` | [--target ID] [--kind percussive または soft] [--against ID] [--grid-note NOTE --bpm N] | False | 登録済み | sample位置由来の安定ID・打点・強さ・グリッド偏差 |
| `direction query mono` | [--target ID] [--by-track] [--worst N] | False | 登録済み | 帯域・400 ms窓・トラックを外した比較のモノ合算差 |
| `direction query limiter_headroom` | 追加引数なし | False | 登録済み | 適応リミッターのdrive0〜12 dBの仮描画。最終limiterは維持 |
| `direction query meters` | [--target ID] [--what ITEMS...] [--step-ms N] [--max-points N] | False | 登録済み | ラウドネス・ピーク・RMS/crest・スペクトル・相関等の数値 |
| `direction query breaths` | --target TRK [--sensitivity N] [--min-ms N] [--max-ms N] | False | 登録済み | 候補ID・特徴・スコア・confidence。合成素材のみの較正 |
| `direction suggest ambience` | --target TRK [--find-quiet] [--region T0,T1] | False | 登録済み | 静かな候補区間、明示ノイズ区間の測定とnoise_bed候補 |
| `direction preview codec` | [--audio FILE] [--codec ITEMS...] [--bitrate-kbps N...] [--normalize-lufs N...] [--out DIR] | out_only | 登録済み | 符号化往復・レベル・ピーク・差。明示outだけ試聴ファイル保存 |
| `direction query align_time` | --target TRK --guide TRK [--section ID_OR_JSON] [--anchors JSON] | False | 登録済み | 適用前のガイド時間写像、前後の測定とedit_align_time候補 |
<!-- tool-commands:end -->

`query` の既存 `direction query AUDIO SPEC` はそのまま使える。新しいquery下位名を第1引数に書くと下位コマンドとして解釈する。下見が音声を読む際は整音cacheの整合を確認し、無い・古い場合に正本やcacheを黙って書き換えない。masterの測定はコマンドによりメモリ上の仮描画を行うため、既存 `check` の描画済みoutcomeとは区別する。入力エラーは終了コード2。

`query mono --by-track` は `--target master` かつstem_mix経路で、各トラックを外したマスターとの差を並べる。原因の分離ではなく再合成した比較である。`query limiter_headroom` の `low_thd_estimate` は20〜250 Hzの線形ゲインを差し引いた残差比で、音楽の調波THDではない（confidence low）。既存の最初の有効adaptive_limiterを使い、無ければ最終limiterの直前へ仮に挿す。

`query meters` は既定100 ms刻み・最大2000点。点数を超えると実効刻み・間引き率・変更の有無を返し、ピークは最大値を保持する。`--what` は loudness/peak/rms_crest/spectrum/spectrogram/correlation/vectorscope/balance/dynamics。無音・短すぎる窓・未定義の値はnullや状態で表し、合否の代わりにしない。

`suggest ambience --find-quiet` は候補の列挙だけ。候補生成には0.2秒以上のノイズだけの `--region T0,T1` を明示する。測定値がnoise_bedの範囲を外れた場合は丸めた別物を勧めず、候補なしの理由を返す。`preview codec` は明示音声ならプロジェクトなしでも使える。`--out` 省略では音声を保存しない。利用できない符号化器も状態として返す。

使わない場合：新コマンドを呼ばない既存コマンドの出力は従来とバイト同一。呼んでも正本・kb・指揮書・outcomeへ観察結果を自動転記しない。検査しないこと：下見を実施したか、候補を採用したか、参照との差を縮めたか。confidenceは測定・推定の留保であり音質の等級ではない。

### 9.19 追加観察量（`mono_loss`・`correlation_bands`・`onsets`）

`observations` のprimitiveに次を追加する。既存のprimitive・viewの意味は変えない。master／mix／トラックなどの対象は既存の対象解決を使い、対応しない対象・viewは入力検査で拒否する。mono_lossとcorrelation_bandsはステレオの情報を要し、mono系viewでは使えない。side viewは既存のband_energy/crest/loudnessだけ。

<!-- tool-primitives:begin -->
| primitive | params | 出力 |
|---|---|---|
| `mono_loss` | band: full（既定）、20〜20000 Hzの中心、または[lo,hi] | P-06と同じ符号付きlevel_change_db（dB）。負は合算で小さくなった差。完全打消しはvalue:nullとcancelled、無音もフラグで区別 |
| `correlation_bands` | なし | 0〜120/120〜500/500〜2000/2000〜8000/8000〜20000 Hzの400 ms窓。Nyquist内だけ。median/p05/negative_fraction/active_windowsと列。valueはnullの構造化量 |
| `onsets` | kind:percussive/soft、band:full/low/mid/high、threshold、min_interval_ms、任意grid_note/bpm/origin_s | count・per_second・strength分布。grid指定時は偏差msの分布。valueはcount |
<!-- tool-primitives:end -->

onsetsの既定はpercussive/full/threshold0.3/min_interval_ms30。threshold0〜1、min_interval_ms5〜500、gridを使うときは音価とbpm20〜400を一緒に指定し、origin_sは0〜36000・既定0。同距離のグリッド点は早い方を取る。打点検出は全長の先行文脈を保持してからsectionを選び、安定IDを振り直さない。検出のconfidenceはヒューリスティックの留保である。

correlation_bandsは無音窓を分位点・負の割合から除く。構造化量へ架空の単一スカラー判定を付けない。既存の主張比較がvalueを要する場合、構造化の補助列を自動で合否へ変換しない。観察量を新しい目的関数・較正つまみ・ゲートには入れない。

使わない場合：新primitiveを書かない観察・validate・checkの結果は従来とバイト同一。検査しないこと：観察の実施や、相関・打点数・モノ損失を特定方向へ動かしたか。値は状態の記述であり、0や大きい値が常によいとは限らない。

### 9.20 ファイル間の空間変換（`spatial ambi`）

direction外の独立CLI。`encode`／`rotate`／`decode`／`convert`／`info` を提供する。入力は `--in FILE`、info以外は `--out FILE.wav` が必須でfloat64 WAVを書く。プロジェクトのミックスグラフには入れず、正本・指揮書・kbを更新しない。次数1〜3、ACN/SN3D、座標x前/y左/z上。回転はroll→pitch→yaw。encodeのstereo入力は `(L+R)/2`、decodeはstereoまたはbinaural、convertは1次のfuma/ambix間。

infoは次数・成分別RMS/peakを返すが、音声だけから正規化や並びを推定できないためunknown/undeterminedとする。出力音声のsr・フレーム数を保ち、復号の末尾は入力長で切る。処理の数学的な性質と聴感上の配置の良し悪しは区別する。

使わない場合：コマンドを呼ばない既存入力の結果は従来とバイト同一。検査しないこと：空間変換を使ったか、特定次数を選んだか。CLI専用であり、GUI・MCPの表面は追加しない。

### 9.21 タイムストレッチ（`edit_stretch`）

T08-10。`stage: edit`、登録上の必須欄は `target, params`。`target` は既存トラック（バス・masterは不可）。§9.21〜§9.26の処理値は `params` に書く。区間を使えるopの `section` は手の直下またはparams内のどちらか一方に書き、セクションID、`"t0,t1"` の秒、`{t0_s: ..., t1_s: ...}` を使える。stretch・extreme・varispeed・reverseでは省略時に対象の非ミュートクリップの先頭から末尾までを選ぶ。

| パラメータ | 範囲・既定・意味 |
|---|---|
| `ratio` | 出力長／入力長、0.25〜4。既定なし |
| `bpm_from` / `bpm_to` | 各20〜400 BPM。両方を指定し、比from/toも0.25〜4 |
| `map` | 既定 `[]`。非負の `[元秒, 出力秒]` を2〜1024点、両軸とも狭義増加。[0,0]から選択元区間の末尾までを覆う区分線形写像 |
| `quality` | `standard` / `high`、既定high。WSOLA／位相ロック付き位相ボコーダ |
| `transients` | 0〜1、既定0.7 |
| `fit` | `keep_start` / `keep_length`、宣言上の既定keep_start |

ratio・BPM対・空でないmapからちょうど1つを指定する。mapの時刻は選択区間の頭を0とした秒で、区間外への外挿はしない。ratio1・mapなしは空のClipPlanで同一と記録し、派生音声を作らない。

stretch・extreme・varispeedの実配置は統括の尺不変の読み替えに従い、要求したfitを `requested_fit` に残し、BB-18へは `fit: keep_length` を渡す。自然な計算後の長さを記録し、選択区間からはみ出す分を切り、不足は無音で埋める。プロジェクト尺は変えない。派生の出典・パラメータ・コード版・ハッシュ、前後のLUFS-I／サンプルピーク／TP、入力・計算後・配置後フレーム数を台帳に残す。再生成と逆順revertは§9.17の共通契約による。

使わない場合：`edit_stretch` を書かない入力の提案・適用・outcomeは従来とバイト同一。検査しないこと：伸縮の採用・回数・順序、テンポ変更の音楽的な妥当性や音質の改善。入力範囲・写像・台帳の整合は検査する。

### 9.22 極端タイムストレッチ（`edit_stretch_extreme`）

T08-11。`stage: edit`、登録上の必須欄は `target` のみ。対象・section・fit・派生台帳は§9.21と同じ。`params` はオブジェクトで、`{}` なら以下の既定値を使う。

| パラメータ | 範囲・既定・意味 |
|---|---|
| `ratio` | 2〜200、既定8 |
| `window_s` | 0.05〜2秒、既定0.25 |
| `onset` | 0〜1、既定0。過渡検出に応じて窓を短くする度合い |
| `seed` | 整数0〜65535、既定0 |
| `max_out_s` | 1〜3600秒、既定600。自然な出力長の上限 |
| `fit` | `keep_start` / `keep_length`、宣言上の既定keep_start。実配置はkeep_length |

長窓FFT・位相乱数化・重ね合わせと局所エネルギー補正を行う。プロジェクトseed・手のID・seedから導出し、フレームごとに独立したPCG64を使う。同じ入力・種・版で再現する。max_out_sを超える設定は、配置時に切る場合も拒否する。

使わない場合：`edit_stretch_extreme` を書かない入力の提案・適用・outcomeは従来とバイト同一。検査しないこと：極端な伸縮の採用、seedの選び方、音の好み。上限・決定論・台帳の整合は検査する。

### 9.23 バリスピード（`edit_varispeed`）

T08-12。`stage: edit`、登録上の必須欄は `target, params`。対象・section・fit・派生台帳は§9.21と同じ。速度と音程が連動する編集である。

| パラメータ | 範囲・既定・意味 |
|---|---|
| `speed` | 0.25〜4、既定なし。自然な出力長は入力長/speed |
| `semitones` | −24〜24、既定なし。speed＝2^(semitones/12) |
| `ramp` | 既定 `[]`。`[元秒, 速度]` を2〜1024点、元秒は非負・狭義増加、速度は各0.25〜4 |
| `fit` | `keep_start` / `keep_length`、宣言上の既定keep_start。実配置はkeep_length |

speed・semitones・空でないrampからちょうど1つを指定する。rampは選択区間の元0秒から末尾までを明示し、区分線形速度の時間積分で読み出し位置を決める。定速は既存の高品質polyphase核、可変速は帯域制限付きsinc読み出しを使う。speed1・rampなしは派生音声を作らず同一と記録する。

使わない場合：`edit_varispeed` を書かない入力の提案・適用・outcomeは従来とバイト同一。検査しないこと：半速・変速の採用や音程の選択、聴感上の改善。入力範囲・rampの端点・台帳の整合は検査する。

### 9.24 区間リバース（`edit_reverse`）

T09-06。`stage: edit`、登録上の必須欄は `target, params`。対象・section・派生台帳は§9.21と同じ。`params: {}` でも使える。

| パラメータ | 範囲・既定・意味 |
|---|---|
| `fade_ms` | 0〜200 ms、既定5。反転後の両端のequal_powerフェード |
| `tail_ms` | 0〜10000 ms、既定0。元区間の後ろから追加して読む余韻 |

選択区間と元素材のtailを読んで反転し、選択区間の長さに収める。tailはその区間の素材の余白であり、別の隣接クリップを混ぜない。素材の余白不足・プロジェクト末尾超過は拒否する。区間外とプロジェクト尺は変えず、派生資産・測定・再生成用の処方を記録する。

使わない場合：`edit_reverse` を書かない入力の提案・適用・outcomeは従来とバイト同一。検査しないこと：反転の採用、余韻や効果の好み。区間・素材の余白・台帳の整合は検査する。

### 9.25 フェード／クロスフェード（`edit_fade`）

T12-04。`stage: edit`、登録上の必須欄は `target, params`。targetは既存トラック。params内ではwhereが必須。

| パラメータ | 範囲・既定・意味 |
|---|---|
| `where` | `in` / `out` / `both` / `cross`、既定なし |
| `in_ms` / `out_ms` | 各0〜60000 ms、既定各10 |
| `cross_ms` | 1〜5000 ms、既定20 |
| `shape` | `linear` / `equal_power` / `s_curve` / `exp` / `log`。crossは既定equal_power、それ以外は既定s_curve |
| `cross_law` | `auto` / `equal_power` / `equal_gain`、既定auto |
| `clip` | 対象トラック内のクリップID。省略時は対象の非ミュートクリップから選ぶ |
| `section` | §9.21の区間。crossでは必須で、隣接する1組の編集点だけを選ぶ。点指定はparams.sectionに秒数を書く |

in/out/bothはsectionと交差するクリップの指定端を置換し、長さは各クリップ長までに収める。指定しない端のフェードを保持する。linear／equal_powerを既存の単一fade_curve欄で両端とも表せる場合はClipPlan、それ以外の形状やcrossはBB-18のDerivedPlanを使う。既存edit_trimの切り口を基に処理する。exp／logのfloorは−120 dB。

crossは境目を中心に両素材を重ね、余白が足りなければ拒否する。autoは実際に重なる素材の相関が0.5以上ならequal_gain、未満ならequal_powerを選ぶ。相関・選択law・形状・前後の測定を記録する。プロジェクト尺は変えず、再生成・revertは§9.17による。

使わない場合：`edit_fade` を書かない入力の提案・適用・outcomeは従来とバイト同一。検査しないこと：フェードの採用・形状の好み、crossが聴感上なめらかと判断したか。入力・余白・台帳の整合は検査する。

### 9.26 静的ノーマライズ（`edit_normalize`）

T12-05。`stage: edit`、登録上の必須欄は `target, params`。targetは既存トラック。params内ではmodeとto_dbが必須。sectionは使えず、クリップ／トラック全体を測る。

| パラメータ | 範囲・既定・意味 |
|---|---|
| `mode` | `peak` / `true_peak` / `lufs_i` / `lufs_active` / `rms`、既定なし |
| `to_db` | −60〜0 dBFS／LUFS、既定なし |
| `max_gain_db` | 0〜40 dB、既定20。上げ幅の上限 |
| `ceiling_db` | −12〜0 dBTP、既定−1。lufs_i／lufs_active／rmsのTP上限 |
| `scope` | `clip` / `track` / `group`、既定track |
| `group` | 既定 `[]`。targetを含まない重複なしの既存トラックID、最大32 peer＋target。空でない配列はscope:groupでだけ使える |

clipは各クリップ、trackは対象全体、groupは同時刻のrawトラック和を1素材として測る。groupには同じ静的ゲインを全員へ与え、相対バランスを保つ。lufs_i／lufs_activeは既存BS.1770の絶対／相対ゲート付き積分を呼ぶ。無音・測定不能はゲイン0と理由を記録する。上げ幅やTP上限に当たれば抑え、目標へ届かなかった理由を残す。

変更は既存クリップのgain_dbだけで、音声資産や派生cacheを作らず、リミッターを掛けない。同一レシピの再適用は既存台帳から基準を復元し、上限付きのゲインも積み上げない。基準の水準・実適用前後の水準・ゲイン・制限理由・group各メンバーの水準を記録し、group全員を整合検査・revertする。マスター目標・既存検証の定義は変えない。

使わない場合：`edit_normalize` を書かない入力の提案・適用・outcomeは従来とバイト同一。検査しないこと：正規化の採用、特定の水準やscopeを選んだか、目標到達を音質の改善と判断したか。入力・group・台帳の整合と既存の検証契約は維持する。
