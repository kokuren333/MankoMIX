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

- lesson／move／research は `evidence`（replicated／measured／literature／practice／tip／hunch）が必須
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

指揮レイヤーの「原液」経路（利用者が持ち込んだリファレンスを測り、指揮者が読む資料にする）と理論ナレッジのために、kind を 3 つ足した。上の front matter の規則（必須 6 欄、禁止内容）はそのまま新 kind にも掛かる。kind の並びは song > work > engineer > lesson > move > research > theory > outcome > direction > analysis > research-log。

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
