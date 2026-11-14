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
