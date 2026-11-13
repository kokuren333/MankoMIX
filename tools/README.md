# tools — 開発用スクリプト

| スクリプト | 内容 |
|---|---|
| `build_demo_data.py` | Pages デモ用データの生成（SPEC §11.4）。プロジェクトから `core/api.py` 経由だけで解析・計画・検証・Mix Report・聴き比べのゲインを書き出す（手書きしない）。`--mp3` で ffmpeg（libmp3lame）による MP3 320 kbps の試聴用複製（マスターではない）を作る。既定の出力先は `tmp/demo_data/`（git 管理外）。`gui/public/demo/` の音声は、M9 の公開監査の承認まで（D-061）コミットしない（以後もリリースの節目だけ、SPEC §15.3）。配置は `gui/DEMO_DATA.md`。`python -I tools/build_demo_data.py --project <song.mmx> [--out DIR] [--mp3]` |
| `check_hygiene.py` | 衛生検査。追跡対象のファイルに、絶対パス、個人のメールアドレス、トークンらしい文字列、禁止ディレクトリが含まれていないかを調べる。全コミットが noreply の identity で、トレーラーがないことも調べる（`docs/SPEC.md` §16.4） |

コミットの前に実行する:

```
python -I tools/check_hygiene.py
```

## git の identity

このリポジトリのコミットは、author / committer とも GitHub の noreply アドレスで統一する。設定はリポジトリ単位で行い、PC の全体設定には触れない。clone し直したときは、最初に次を実行する（`<ID>` と `<name>` は自分の GitHub の数値 ID とユーザー名）。

```
git config user.name "<name>"
git config user.email "<ID>+<name>@users.noreply.github.com"
```

コミットメッセージに `Co-Authored-By:` トレーラーは付けない。`check_hygiene.py` は、全コミットの identity とトレーラーの有無も検査する。

予定: 依存ライセンスの監査、レジストリの検証。
