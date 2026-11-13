# tools — 開発用スクリプト

| スクリプト | 内容 |
|---|---|
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

予定: 依存ライセンスの監査、レジストリの検証、デモ用データの生成。
