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

各ディレクトリには `LICENSE`（原文のまま）と `ORIGIN.md`（リポジトリ URL、コミット、元のファイル名、変更点）を置く。移植した各ソースの先頭にも、作者、出所、ライセンス、変更点を書く。
