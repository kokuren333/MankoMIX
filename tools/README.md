# tools — 開発用スクリプト

| スクリプト | 内容 |
|---|---|
| `build_demo_data.py` | Pages デモ用データの生成（SPEC §11.4）。プロジェクトから `core/api.py` 経由だけで解析・計画・検証・Mix Report・聴き比べのゲインを書き出す（手書きしない）。`--mp3` で ffmpeg（libmp3lame）による MP3 320 kbps の試聴用複製（マスターではない）を作る。既定の出力先は `tmp/demo_data/`（git 管理外）。`gui/public/demo/` の音声は、M9 の公開監査の承認まで（D-061）コミットしない（以後もリリースの節目だけ、SPEC §15.3）。配置は `gui/DEMO_DATA.md`。`python -I tools/build_demo_data.py --project <song.mmx> [--out DIR] [--mp3]` |
| `build_samples.py` | 公式サンプル一式の生成（SPEC §15）。`sample_set.json` の種別ごとに本体の `init` と `run`（CLI）を実行し、`listen`、`measure`、`gate` で処理前（ステムの単純合算）、参考フルミックス、除去分、測定値、レベルマッチのゲイン、トランスレーション・ゲートを得る。`samples/public/` に目録 `manifest.json`、Mix Report、MP3 320 kbps の試聴用複製（マスターではない。D-061 によりコミットしない）を、`tmp/release_assets/` に検証に通ったロスレスのマスターを置く。サンプルの場所は `MANKOMIX_SAMPLE_DIR`（`--source-kind export` では `MANKOMIX_SAMPLE_EXPORT_DIR`）で外から渡す。`python -I tools/build_samples.py [--variants 1,8] [--jobs N]`。詳細は `samples/README.md` |
| `check_hygiene.py` | 衛生検査。追跡対象のファイルに、絶対パス、個人のメールアドレス、トークンらしい文字列、禁止ディレクトリが含まれていないかを調べる。全コミットが noreply の identity で、トレーラーがないことも調べる（`docs/SPEC.md` §16.4） |
| `license_audit.py` | 依存とライセンスの監査（SPEC §13、§13.4、D-057、D-060）。Python のコア依存の閉包と各 extra（`test`、`test-crosscheck`、`separation`）、コアが読み込むネイティブ部品（libsndfile など）、コアの import 境界（librosa、soxr、torch などを worker の外で import しない）、`gui/package-lock.json` の npm 依存（runtime / dev）、`third_party/` の LICENSE と ORIGIN.md、モデルレジストリ（`core/registry.py` の検証）、FFmpeg を同梱していないこと、を調べる。許可リスト外・未確認のライセンスがあれば終了コード 1。生成物は `licenses/THIRD_PARTY_LICENSES.md`、`licenses/python.json`、`licenses/npm.json`（手で編集しない）。審査済みの例外は `licenses/exceptions.json`（理由と根拠 URL が必須）。`python -I tools/license_audit.py`（生成して書き出す）、`python -I tools/license_audit.py --check`（CI。コミット済みの生成物との差分でも失敗する） |
| `build_native.py` | ネイティブ DSP 核（`dsp/native/`）を Release でビルドし、`dsp/build/lib/` に置く。Windows は Visual Studio（vswhere、vcvars64）、Linux / macOS は PATH 上の CMake と C++17 コンパイラを使う。`python -I tools/build_native.py [--clean] [--verbose]` |

コミットの前に実行する（CI も同じものを実行する。`.github/workflows/ci.yml`）:

```
python -I tools/check_hygiene.py
python -I tools/license_audit.py --check
```

依存を足したり `gui/package-lock.json` を更新したりしたら、`python -I tools/license_audit.py` で `licenses/` を再生成してコミットする。CI は pip が解決した最新版で監査するので、上流の依存が変わると `--check` が差分で落ちることがある。そのときも再生成して差分（新しい依存とライセンス）を確かめてからコミットする。

## git の identity

このリポジトリのコミットは、author / committer とも GitHub の noreply アドレスで統一する。設定はリポジトリ単位で行い、PC の全体設定には触れない。clone し直したときは、最初に次を実行する（`<ID>` と `<name>` は自分の GitHub の数値 ID とユーザー名）。

```
git config user.name "<name>"
git config user.email "<ID>+<name>@users.noreply.github.com"
```

コミットメッセージに `Co-Authored-By:` トレーラーは付けない。`check_hygiene.py` は、全コミットの identity とトレーラーの有無も検査する。
