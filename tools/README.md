# tools — 開発用スクリプト

| スクリプト | 内容 |
|---|---|
| `build_demo_data.py` | Pages デモ用データの生成（SPEC §11.4）。プロジェクトから `core/api.py` 経由だけで解析・計画・検証・Mix Report・聴き比べのゲインを書き出す（手書きしない）。`--mp3` で ffmpeg（libmp3lame）による MP3 320 kbps の試聴用複製（マスターではない）を作る。既定の出力先は `tmp/demo_data/`（git 管理外）。`gui/public/demo/` の音声は、M9 の公開監査の承認まで（D-061）コミットしない（以後もリリースの節目だけ、SPEC §15.3）。配置は `gui/DEMO_DATA.md`。`python -I tools/build_demo_data.py --project <song.mmx> [--out DIR] [--mp3]` |
| `build_samples.py` | 公式サンプル一式の生成（SPEC §15）。`sample_set.json` の種別ごとに本体の `init` と `run`（CLI）を実行し、`listen`、`measure`、`gate` で処理前（ステムの単純合算）、参考フルミックス、除去分、測定値、レベルマッチのゲイン、トランスレーション・ゲートを得る。`samples/public/` に目録 `manifest.json`、Mix Report、MP3 320 kbps の試聴用複製（マスターではない。D-061 の承認によりコミットする）を、`tmp/release_assets/` に検証に通ったロスレスのマスターを置く。サンプルの場所は `MANKOMIX_SAMPLE_DIR`（`--source-kind export` では `MANKOMIX_SAMPLE_EXPORT_DIR`）で外から渡す。`python -I tools/build_samples.py [--variants 1,8] [--jobs N]`。詳細は `samples/README.md` |
| `check_hygiene.py` | 衛生検査。追跡対象のファイルに、絶対パス、個人のメールアドレス、トークンらしい文字列、禁止ディレクトリが含まれていないかを調べる。全コミットが noreply の identity で、トレーラーがないことも調べる（`docs/SPEC.md` §16.4） |
| `license_audit.py` | 依存とライセンスの監査（SPEC §13、§13.4、D-057、D-060）。Python のコア依存の閉包と各 extra（`test`、`test-crosscheck`、`separation`）、コアが読み込むネイティブ部品（libsndfile など）、コアの import 境界（librosa、soxr、torch などを worker の外で import しない）、`gui/package-lock.json` の npm 依存（runtime / dev）、`third_party/` の LICENSE と ORIGIN.md、モデルレジストリ（`core/registry.py` の検証）、FFmpeg を同梱していないこと、を調べる。許可リスト外・未確認のライセンスがあれば終了コード 1。生成物は `licenses/THIRD_PARTY_LICENSES.md`、`licenses/python.json`、`licenses/npm.json`（手で編集しない）。審査済みの例外は `licenses/exceptions.json`（理由と根拠 URL が必須）。`python -I tools/license_audit.py`（生成して書き出す）、`python -I tools/license_audit.py --check`（CI。コミット済みの生成物との差分でも失敗する） |
| `make_icons.py` | GUI のアイコン一式（D-067、SPEC §11.5）。`gui/public/icons/` に CyberSprite から意味の合うアイコンをそのままコピーし、MankoMIX 固有のアイコンを同じ 16×16・ui-icons 11 色パレットで CyberSprite の CLI により描いて書き出す（設計データはこのスクリプト内、由来は `gui/public/icons/manifest.json` と `NOTICE`）。`build` は隣に CyberSprite が必要。`check` は標準ライブラリだけで寸法・パレット・設計との一致・ハッシュ・由来を検査する（CI も実行）。`python -I tools/make_icons.py build`、`python -I tools/make_icons.py check` |
| `build_native.py` | ネイティブ DSP 核（`dsp/native/`）を Release でビルドし、`dsp/build/lib/` に置く。Windows は Visual Studio（vswhere、vcvars64）、Linux / macOS は PATH 上の CMake と C++17 コンパイラを使う。`python -I tools/build_native.py [--clean] [--verbose]` |
| `tool_status_table.py` | 「無いツール 143 件」の実装状況の表（`docs/tool_impl/README.md` の自動生成部分）。各型の `implemented` は実行時の `describe()`、op・コマンドは登録表から取る（手で書かない）。`python -X utf8 tools/tool_status_table.py`（再生成）、`--check`（差分の検査） |
| `generate_synthetic_irs.py` | 同梱の自作合成 IR（`registry/irs.json` の `official` の項目）を決定的に生成し、記録済みの sha256 と照合する。音声本体はコミットしない |
| `generate_synthetic_samples.py` | `drum_replace` 用の自作合成ワンショット（`registry/samples.json`）を決定的に生成し、sha256 を照合する。音声本体はコミットしない |
| `register_hrtf.py` | 持ち込みの HRTF（SOFA から変換した配列）を `registry/hrtfs.json` の規則でローカル登録する（同梱は自作の球頭モデルだけ） |

コミットの前に実行する（CI も同じものを実行する。`.github/workflows/ci.yml`）:

```
python -I tools/check_hygiene.py
python -I tools/license_audit.py --check
python -I tools/make_icons.py check
```

依存を足したり `gui/package-lock.json` を更新したりしたら、`python -I tools/license_audit.py` で `licenses/` を再生成してコミットする。CI は pip が解決した最新版で監査するので、上流の依存が変わると `--check` が差分で落ちることがある。そのときも再生成して差分（新しい依存とライセンス）を確かめてからコミットする。

## git の identity

このリポジトリのコミットは、author / committer とも GitHub の noreply アドレスで統一する。設定はリポジトリ単位で行い、PC の全体設定には触れない。clone し直したときは、最初に次を実行する（`<ID>` と `<name>` は自分の GitHub の数値 ID とユーザー名）。

```
git config user.name "<name>"
git config user.email "<ID>+<name>@users.noreply.github.com"
```

コミットメッセージに `Co-Authored-By:` トレーラーは付けない。`check_hygiene.py` は、全コミットの identity とトレーラーの有無も検査する。
