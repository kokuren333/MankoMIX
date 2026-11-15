# kb — 経験の蓄積庫（最小版の規約）

MankoMIX の指揮レイヤー（director）が読み書きする Markdown のカード置き場。コアは読まない。

## 構成

| 場所 | 中身 |
|---|---|
| `INDEX.md` | 索引。`mankomix kb index` が機械生成する。手で編集しない |
| `songs/<slug>/song.md` | 曲カード（kind: song） |
| `songs/<slug>/dossier.md` | 曲資料（`mankomix direction dossier` の出力。front matter なし） |
| `songs/<slug>/<日付>_<pattern>-<名>/` | 案件フォルダ: `analysis.md`（分析メモ）、`direction.md`（指揮書）、`outcome.md`（結果） |
| `lessons/KL-nnnn.md` | 学びカード（kind: lesson） |
| `moves/KM-nnnn.md` | 手カード（kind: move） |

## front matter

必須: `id`、`kind`（song／lesson／move／research／outcome／direction／analysis／research-log）、`title`、`created`（YYYY-MM-DD）、`status`（draft／active／stale／disputed／superseded／retracted）、`visibility`（public／private）。

- lesson／move／research は `evidence`（replicated／measured／literature／practice／observed_media／tip／hunch）が必須
- `evidence` が replicated／measured のカードは `backing`（kb 内の相対リンク。結果カードなど）が 1 つ以上必須
- 任意: `applies_to`（`{ genre: [hiphop], profile: [club] }` の形）、`song`、`request`、`pattern`

## 禁止内容（`mankomix kb lint` が拒否する）

- 絶対パス（ドライブ文字、ユーザーのホーム、file URL）
- 音声ファイルの参照（拡張子つきの名前）。音源は git に入れない（D-061）
- 壊れた相対リンク、古い `INDEX.md`

## 道具

- `mankomix kb index [--root kb]` — 索引の再生成
- `mankomix kb lint [--root kb]` — 検査（違反があれば終了コード 1）

## 追補: 作品・技術者・理論のカード（2026-11-15）

指揮レイヤーの「原液」経路（利用者が持ち込んだリファレンスを測り、指揮者が読む資料にする）と理論ナレッジのために、kind を 3 つ足した。上の front matter の規則（必須 6 欄、禁止内容）はそのまま新 kind にも掛かる。kind の並びは song > work > engineer > lesson > move > research > theory > curriculum > outcome > direction > analysis > research-log。

### 置き場と ID

| kind | 置き場 | ID |
|---|---|---|
| work（作品） | `references/works/<slug>/work.md` | `work_<slug>` |
| engineer（クレジットされた技術者） | `references/engineers/<slug>.md` | `eng_<slug>` |
| theory（理論） | `theory/KT-nnnn.md` | `KT-nnnn`（4 桁） |

- slug は英小文字・数字で始まり、英小文字・数字・`_`・`-` だけ
- ID と置き場が合わないカードは `kb lint` が拒否する（`bad_id`／`bad_location`）
- 同じフォルダの `refstudy.md`（作品の測定資料）は機械生成で、カードではない（下の「機械生成文書」）

### 必須欄（共通 6 欄に加えて）

| kind | 必須欄 |
|---|---|
| work | `rights`（own／third_party。権利の所在の自己申告）、`credits_source`（クレジットの出所。例「利用者提供（盤のクレジット表記など）」）、`materials`（素材の記録。下記） |
| engineer | `works`（クレジットされた作品の ID のリスト。各要素 `work_<slug>`）、`credits_source`（公表クレジットの出所） |
| theory | `evidence`（literature／practice）、`domain`（rudiments／harmony／philosophy／practice）、`tradition`（common／berklee-style／genneki／field）、`paraphrase: true`（自分の言葉で書いたことの宣言）、`sources_note`（出典の扱いの注記） |

- work の `materials` は 1 素材 1 要素のマップで、`sha256`（ステム一式は `sha256_set`）が必須。ほかに `type`（master／stems）、`lossy`、`format`（例 `"44.1k/16"`）、`count`、`obtained`（入手経路の利用者申告）を書ける。**パスもファイル名も書かない**（`path`／`file`／`filename`／`name`／`url` のキー、ファイル名やパスに見える値を lint が拒否する）
- work の任意欄: `artist`、`release`（`{ title: "…", year: 2019 }`）、`credits`（`role` は mix／master／produce／arrange／record、`person` は `eng_<slug>`、`name`）、`genre`、`study`（`{ sha256: "…", engine: { … } }`）、`evidence: measured`、`backing: [refstudy.md]`。いずれも利用者提供の事実情報で、道具が自動で集めることはない
- **draft の扱い**: `status: draft` の work は `credits_source`／`materials`、engineer は `works`／`credits_source` を、キーがあれば空にしておける（`direction ref study`／`ref credit` が作る雛形はメタ情報が空欄の draft）。`rights` は draft でも必須。active にするときは空欄を埋める
- theory の本文は「要点／指揮での使いどころ／効かない条件・誤用／関連」の定型で書く。work の本文は「何の作品か／測定の要点（refstudy からの書き写し）／読み（指揮者の〔推定〕と確度）／使った案件」。engineer の本文は、クレジットされた作品へのリンクと、`direction ref credit` が `<!-- ref credit: begin … -->`〜`end` の間に書く集計（各量の中央値・四分位範囲・n。n < 3 は「傾向とは言えない（事例）」と機械表示）。人物評・私的情報は書かない

### flow 形式の front matter

front matter のパーサは 1 行 1 キーの flow 形式だけを読む。入れ子の値も 1 行に書く（ブロック形式の YAML は読まない）。

```yaml
credits: [{ role: mix, person: eng_xxx, name: "…" }]
materials: [{ type: master, lossy: false, format: "44.1k/16", sha256: "…", obtained: "利用者申告（購入盤）" }]
```

### 機械生成文書（refstudy／refsheet）

- `refstudy.md`（`direction ref study` の測定資料）と `refsheet*.md`（`direction ref compare` の対照表）は、`dossier.md` と同じく front matter を持たない。ファイル名で判定し、置き場所は問わない
- **粒度の上限**（音や細かい測定列を再構成できる粒度のデータを残さないため。lint が `too_fine` で拒否する）: 時間は区間単位まで、周波数は帯域集計まで。具体的には、表 1 つは 64 行・24 列まで、第 1 列や時間・周波数の軸を示す列が 16 行以上の等間隔の数値列になる表は拒否（フレーム列・線形周波数ビンとみなす）、表の外の数値は 1 行 64 個・数値主体の行の連続 32 行まで。`ref study --sections` の区間は 23 個まで
- 手で編集しない。測定し直すときは同じコマンドを再実行する（同じ入力からはバイト同一）

### 著作権と出典

| 対象 | してよい | しない |
|---|---|---|
| 理論・概念 | 自分の言葉で書いた要約 | 書籍・教材の文面、譜例、図表、章立ての引き写し |
| 対話由来の思想 | 原則への蒸留（KT-0018〜0022） | 発言の逐語、発言者の個人名・特定できる情報 |
| リファレンス音源 | 利用者が持ち込んだファイルをその場で測る | 音源・その変換物・再構成できる粒度のデータの保存、取得機能（ダウンロード等） |
| 測定値 | 事実として記録 | 第三者作品の測定を公開リポジトリへ既定で入れること |
| 作品名・クレジット | 利用者提供の事実情報として記録 | 道具による自動収集、人物評、歌詞・解説文 |
| 所在メモ（work の `sources`。追補 2） | 素材の所在と利用条件の要点を自分の言葉で記録（確認日つき） | ファイル名・パスの記録、道具による所在の確認・取得、第三者作品の所在を公開 kb へ出すこと |

- 音色の呼び名（低音の音色カードなど）は、音の作り（波形、変調、包絡、共鳴）で書く。製品名・人名・機種の型番に由来する通称は使わない（追補 2）

- 音源は測るときにメモリ上で読むだけで、複製・変換物をどこにも残さない。記録するのは内容の SHA-256、形式（サンプルレート、ビット深度、非可逆か）、長さ
- 例外は `ref study --separate`（既定は無効）で、分離ワーカーの入出力をシステムの一時フォルダに書き、終了時に消す。kb・プロジェクトには残らない
- 「バークリー」は理論の系統を指す通称として `tradition` と本文で使う。教材名・講座名・ページ参照は書かず、提携や公認を示す表現をしない

### 第三者作品の置き場と公開止め

- **第三者（市販）作品の作品カード・測定資料の既定の置き場は、非コミットの `_private/kb/`**。`direction ref study`／`ref compare`／`ref credit`／`ref list` の `--kb` の既定はこのフォルダ（リポジトリ直下からの相対）で、雛形は `rights: third_party`、`visibility: private`、`status: draft` で作られる
- **公開 kb（このフォルダ）に置けるのは `rights: own` の作品だけ**。自前の作品を公開 kb に入れるときは `--kb kb` を付け、雛形の `rights` を own に直す。市販曲の統計を同梱しない決定（D-039）は変わらない
- lint の公開止め:
  - どの kb でも、`rights: third_party` かつ `visibility: public` のカードを拒否する（`public_third_party`）
  - 公開 kb では、work の `rights` が own 以外なら拒否し、engineer が参照する作品（`works` 欄、本文中の `work_<slug>`、作品カードへのリンク）が own でない、または kb 内に無い（own と確認できない）なら拒否する（`public_kb_rights`）
- **公開か非公開かの判定**: lint の root を絶対パスに解決し、その途中に `_private` という名のフォルダがあれば非公開、それ以外はすべて公開 kb とみなす（保守側）。結果は lint の JSON の `scope`（public／private）に出る

### 理論カードの転載の歯止め

`kind: theory` のカードだけに掛かる機械検査:

- 本文 1,200 字まで（空白・改行は数えない。`theory_too_long`）
- 画像の埋め込みなし（`theory_image`）、引用ブロック（行頭 `>`）なし（`theory_blockquote`）
- かぎ括弧・引用符の 1 対の中身が 80 字を超えない（改行をまたいでも数える。`theory_long_quote`）

機械で見られないこと（特定の書籍の言い回し・例・構成をなぞっていないか、蒸留カードから発言者が特定できないか）は関門で人が見る。語彙は `knowledge/vocabulary.json` が正で、理論カードは写さず見出しで引用する。同じ主張が research と theory の両方に立つときは、出典つきの research を正とし、theory は要点 1 行とリンクにする。

理論カードは指揮者が使える材料で、使うことは求められない。validate／check／calibrate は理論カードの有無・使用を見ず、未使用を警告しない。曲資料 §10.2「理論の棚」には `status: active` の理論カードの ID と題だけが全件載る（本文は `kb show` で引く）。

### 検索と表示（追加の道具）

- `mankomix kb search [--kind K]... [--genre G]... [--text T] [--root kb]` — カードの検索（INDEX と同じ順、読み取りのみ）。`--kind`・`--genre` は繰り返せる。`--genre` は `genre` 欄と `applies_to.genre` を大小無視で照合、`--text` は ID・題・本文の大小無視の部分一致
- `mankomix kb show <id> [--root kb]` — 1 枚の front matter と本文（読み取りのみ）。ID が無ければ入力エラー（終了コード 2）
- `kb lint` の JSON に `scope`（public／private）が増えた

### INDEX の並び

INDEX は種類 → ID の順。種類の順は上の kind の並び（作品を上、理論を経験カードの後ろ）。見出し行には旧来の 8 種と、カードが実在する新 kind だけが並ぶ。

## 追補 2: 任意欄・等級・カリキュラム（2026-11-15）

work カードの発見経路と観察記録、等級 `observed_media`、束カード kind `curriculum`、`source_type` を足した。**どれも任意で、使わなくても不利にならない。** 欄の無いカードに `kb lint` は何も言わず（新しい誤り・警告は出ない）、lint・validate・check はこれらの使用の有無や順序を検査しない。lint が見るのは、書かれた欄の形式と転載・固有名の歯止めだけ。上の front matter の規則と禁止内容は新しい欄・kind にもそのまま掛かる。

### 等級の並び

`evidence` の並びは `replicated > measured > literature > practice > observed_media > tip > hunch`（強い順）。

- `observed_media`（プロセスメディアの観察）は practice の下・tip の上。測っていないので measured より下、1 作品・1 回の見え方で照合を経ていないので practice より下、制作者自身の過程という一次の材料で作品の測定と突き合わせられるので tip より上
- lesson／move／research が名乗れる。`backing` は要求しない。theory の `evidence`（literature／practice）は変わらない
- 既存の 6 等級の相対順は変わらない。曲資料 §10.1 の見出し文は従来の並びの表記のままで（曲資料のバイト列を保つため）、並びの正は本節

### work の任意欄 `sources`（発見経路）

```yaml
sources: [{ kind: official_stems, where: "（所在メモ。自分の言葉で）", rights_note: "（利用条件の要点。自分の言葉で）", noted: 2026-11-15 }]
```

| キー | 必須 | 形 |
|---|---|---|
| `kind` | ○ | `contest_stems`（公募・コンテストで配られる素材）／`description_materials`（公開物の説明欄などで案内される素材）／`official_stems`（権利者が公式に配るステム・パラデータ）／`breakdown_media`（制作過程を見せる解説・解剖のメディア） |
| `where` | ○ | 所在メモ（空でない文字列、200 字以内）。ファイル名・パスに見える値は拒否 |
| `rights_note` | ○ | 権利注記（利用条件の要点を自分の言葉で。空でない文字列、200 字以内） |
| `url` | — | `http://`／`https://` で始まる文字列 1 つ |
| `noted` | — | 確認日 `YYYY-MM-DD` |

- lint（kind が work のときだけ）: リストでない・要素がマップでない・未知キー・`kind` の列挙外・必須の欠落や空・字数超過・`url` や `noted` の形の誤り → `bad_sources`。`where` がファイル名・パスに見える → `source_file_name`（`materials` と同じ判定）。音声拡張子・絶対パスは従来の全体検査が効く
- **所在と権利の記録だけ**。`ref study` を含むどの道具もこの欄を読んで動かず、URL を開かない。素材を探して集めるのは人（KT-0023）
- 公開／非公開は従来の公開止めに従う（公開 kb の work は `rights: own` だけなので、第三者作品の `sources` は非公開側に置かれる）

### work／engineer の任意欄 `observed_media`（観察記録）

```yaml
observed_media: [{ part: "（対象パート）", order: 1, note: "（観察した事実を自分の言葉で）", source: 1 }]
```

| キー | 必須 | 形 |
|---|---|---|
| `part` | ○ | 対象パート（空でない文字列、60 字以内） |
| `note` | ○ | 観察した事実を自分の言葉で（空でない文字列、200 字以内） |
| `order` | — | そのメディアの中で何番目の判断として見えたか（1 以上の整数）。分からなければ書かない |
| `source` | — | 同じカードの `sources` の何番目か（1 始まり。work カードだけ。`kind: breakdown_media` の要素を指す） |

- 本文の任意の節「## 観察」に番号つきで補足を書ける（front matter の並び順が「観察 n」の n）
- lint（kind が work／engineer のときだけ）: 形の誤り・未知キー・必須の欠落、`source` が範囲外・`breakdown_media` 以外を指す・engineer カードに書かれた → `bad_observed`。逐語引用の歯止め: `note` の中の引用符 1 対の中身が 20 字を超える、または `observed_media` を持つカードの「## 観察」節に引用ブロック（行頭 `>`）がある → `observed_quote`
- **役割の限定**: 観察は意図推定の材料に限る。分析メモでは `〔観察: work_<slug> 観察 n〕` で引き、〔参照〕〔測定〕とは書かない。観察は確度を上げず（観察だけの〔推定〕は low）、測定の代わりにしない。カードの等級を動かすのは従来どおり outcome だけ（docs/DIRECTION_FORMAT.md §6.4・§6.6）
- 公開側に置けるのは自作品の過程の観察だけ（従来の公開止め）

### 束カード kind `curriculum` と `source_type`

| 項目 | 形 |
|---|---|
| 置き場・ID | `curricula/<slug>.md`、`cur_<slug>`（合わなければ `bad_id`／`bad_location`） |
| 必須欄（共通 6 欄に加えて） | `specified_by`（誰が束を指定したか）、`paraphrase: true`、`sources_note`、`items` |
| `items` | flow リスト。要素 `{ order: 1, level: intro, topic: "（主題を自分の言葉で）", cards: [KT-nnnn] }`。`order` は 1 以上の整数で束の中で重複なし、`level` は `intro`／`core`／`advanced`、`topic` は 80 字以内、`cards` は `KT-`／`KR-`／`KL-`／`KM-`＋4 桁のリスト（省略・空でもよい） |
| draft | `status: draft` なら `items` は空でよい |
| 本文の定型 | 目的／範囲と水準／読み方の注意（順序は学ぶ順で、作業の手順ではないこと） |

- lint: `items` の形の誤り → `bad_curriculum`。`items` の要素に `title`／`name`／`author`／`publisher`／`url`／`uri`／`isbn`／`source`／`file`／`path` のキーがあれば `curriculum_material_name`。本文には理論カードと同じ転載の歯止め（1,200 字、画像、引用ブロック、80 字超の引用）。`cards` は形だけ見て、実在は見ない
- **教材そのものの名前・所在はリポジトリに書かない。** 束カードに載るのは主題（自分の言葉）と蒸留カードの ID だけ。どの教材に当たるかの対応は、利用者が非コミットの場所で持つ（非公開 kb の束カード本文には書ける。公開側は不可）
- `source_type`（任意。どの kind でも）: `paper`／`pro`／`amateur`／`internal`／`curriculum`。列挙外は `bad_value`
- `curriculum`（任意の参照欄。どの kind でも）: `{ id: cur_<slug>, order: 3, level: core }`。`id` は必須、形の誤り・未知キーは `bad_curriculum_ref`
- `source_type: curriculum`（人が指定した教材から蒸留したカード。kind は theory か research）には kind を問わず `paraphrase: true` を要求し、本文に画像・引用ブロック・80 字超の引用の歯止めを掛ける（字数上限は theory だけ）
- 束の `order`／`level` は学ぶ順と難度で、作業の順ではない。読む機械は `kb search --curriculum` の並びだけで、validate／apply／check／calibrate は束を読まない。束に入っていてもカードの重みは上がらない
- 曲資料 §10.2 の末尾に、active な束カードがあるときだけ `- カリキュラム: cur_<slug> <題>（n 項）` が 1 行ずつ載る（束の無い kb の曲資料は従来とバイト同一）

### 検索フラグ（追補 2）

- `mankomix kb search --source-type <t>`（繰り返し可）: `source_type` で絞る
- `mankomix kb search --curriculum <cur_id>`: 束の `items[].cards` に載るカードと、`curriculum.id` が一致するカードを、学ぶ順（`order`）→ ID の順で返す。各要素に `curriculum_order`／`curriculum_level`、結果に `not_in_this_kb`（束に載っているがこの kb に無い ID）が付く
- 新しいフラグを使わない検索の結果は従来と同じ

### 機械生成文書（追補 2）

`ref study --add transient` の節「トランジェント輪郭」と、`ref compare --add transient|guide` の追加節も、上の粒度の上限の内側に収まる（行は区間単位、列は帯域・群の集計。フレーム列を出さない）。測定対象外の値は「—」で出る。

### 公開 kb の work ID（追補 2）

公開 kb（非公開 root でないもの）では、`README.md`・`INDEX.md` 以外の全 Markdown（カード、分析メモ、指揮書、outcome、refsheet、refstudy、曲資料）に現れる `work_<slug>` が、同じ kb の `rights: own` の work カードでなければ `public_kb_rights` で拒否する（同じファイルの同じ ID は 1 回だけ報告）。書式の例を書くときは `work_<slug>` の形を使う。
