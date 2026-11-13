# third_party — 取り込んだ第三者コード

本体に取り込む第三者コードを、ライセンス文と出所の記録とともに置く。

- 取り込めるのは MIT / BSD / ISC / Apache-2.0 のコードだけ
- GPL / AGPL のコードは置かない
- LGPL のもの（FFmpeg など）はここに置かず、外部プロセスとして呼ぶ
- 取り込むたびに、出所の URL、版（コミット）、ライセンス文、変更点を記録する

方針の詳細は `docs/SPEC.md` §13。

## 取り込み済み

| ディレクトリ | 内容 | ライセンス | 版 | 使う場所 |
|---|---|---|---|---|
| `airwindows/` | Airwindows（Chris Johnson）の PurestDrive、ClipOnly2、Console7Channel、Console7Buss、Pressure4 を移植したもの | MIT（`airwindows/LICENSE`） | コミット `94cb679`（詳細は `airwindows/ORIGIN.md`） | ネイティブ DSP 核（`dsp/native/`）。ビルド時に `dsp/native/CMakeLists.txt` から直接コンパイルする |
| `scnet/` | SCNet（starrytong）のモデル定義 `SCNet.py`、`separation.py`（無改変） | MIT（`scnet/LICENSE`） | コミット `5d95bf9`（詳細は `scnet/ORIGIN.md`） | 分離ワーカー（`core/separation/archs.py`）。別プロセスで読み込む |
| `bs_roformer/` | Mel-Band RoFormer（Phil Wang）の推論部分の移植 | MIT（`bs_roformer/LICENSE`） | 詳細は `bs_roformer/ORIGIN.md` | 分離ワーカー（`core/separation/archs.py`）。別プロセスで読み込む |

各ディレクトリには `LICENSE`（原文のまま）と `ORIGIN.md`（リポジトリ URL、コミット、元のファイル名、変更点）を置く。移植した各ソースの先頭にも、作者、出所、ライセンス、変更点を書く。

`tools/license_audit.py`（CI で `--check` 付きで実行）が、各フォルダに `LICENSE`（MIT / BSD / ISC / Apache-2.0 の文面）と、出所 URL を含む `ORIGIN.md` があり、上の表に `` `<フォルダ名>/` `` の形で載っていることを検査する。依存パッケージを含む全体のライセンス一覧は `licenses/THIRD_PARTY_LICENSES.md`（生成物）。
