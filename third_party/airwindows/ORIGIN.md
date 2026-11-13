# Airwindows — 出所の記録

| 項目 | 内容 |
|---|---|
| 作者 | Chris Johnson（airwindows） |
| リポジトリ | https://github.com/airwindows/airwindows |
| コミット | `94cb6793893027fb418ffac7cdbfcb9b4c82aadb`（2026-11-07） |
| ライセンス | MIT（`LICENSE` は同コミットの `LICENSE` をそのまま複写。blob `e8feef9bdb417d8662f50cc43e6329c0bd071460`） |
| 取得方法 | リポジトリ外の一時ディレクトリへ sparse clone し、ソースを読んだだけ。上流のスクリプトやビルドは実行していない |

## 移植したファイル

各ファイルの `processDoubleReplacing`（64 bit 経路）を移植元とした。プラグインの外殻（`*.cpp` のコンストラクタ、パラメータ表示、チャンク）は、既定値とパラメータ名を読むためだけに参照した。

| 移植先（このディレクトリ） | 移植元（`plugins/LinuxVST/src/` 以下） | blob |
|---|---|---|
| `src/purest_drive.cpp` | `PurestDrive/PurestDriveProc.cpp` | `e49485280ffe86b226491308a56ebeb0b8736f95` |
| | `PurestDrive/PurestDrive.cpp` | `3010708e7265fcc0af0a389676572034e2eebcc1` |
| | `PurestDrive/PurestDrive.h` | `c3ee97bb1e4daee6d332e791f61ff759c4286730` |
| `src/clip_only2.cpp` | `ClipOnly2/ClipOnly2Proc.cpp` | `f5d765a0dd25a4875ca2b70201d2d39374df1329` |
| | `ClipOnly2/ClipOnly2.cpp` | `b32273c5b3f081017e4c96f1ee63f5900a39fc5e` |
| | `ClipOnly2/ClipOnly2.h` | `7a006f235c09bc73332bddbff9d40fe660cf1add` |
| `src/console7_channel.cpp` | `Console7Channel/Console7ChannelProc.cpp` | `a0b82774f8ec9401845a125d5208936f72135bc4` |
| | `Console7Channel/Console7Channel.cpp` | `27ba85cb368cd988ed9135d49a501c2c63960f80` |
| | `Console7Channel/Console7Channel.h` | `486bb3622d69812763b9bc2e6f86f6b246a8a8bc` |
| `src/console7_buss.cpp` | `Console7Buss/Console7BussProc.cpp` | `f0b65819e47c91b6fd63a58801a679a0b7a39935` |
| | `Console7Buss/Console7Buss.cpp` | `16769aa583e4045cb06695464ff1874c79a8af0e` |
| | `Console7Buss/Console7Buss.h` | `ffd952f6cf939f31b34e587f5d0eff33424368a1` |
| `src/pressure4.cpp` | `Pressure4/Pressure4Proc.cpp` | `1111cce8ea88fb6a6341c3c77ce15216a1b0244e` |
| | `Pressure4/Pressure4.cpp` | `2fac64f07bd16c907ddf75fe80eb4b7be96d763f` |
| | `Pressure4/Pressure4.h` | `b84c5bcff168e716334ce4ddc55ebca347a75b64` |

## 変更点（全ファイル共通）

サンプル単位のアルゴリズム（式、定数、処理順）は変えていない。変えたのは次の点だけである。各ファイルの先頭コメントにも、そのファイル固有の変更を記した。

- VST の外殻（`AudioEffectX`、プログラム、チャンク、表示文字列）を除き、`mmx::Processor`（`dsp/native/src/mmx_processor.h`）の実装にした
- ステレオ L/R の重複コードを、N チャンネル（最大 8）のループにした。Pressure4 の検出は、元の「L と R の大きい方」を「全チャンネルの最大」に一般化した
- **乱数の除去（決定性）**: 元はコンストラクタで `rand()` から `fpd` を初期化する。これを、チャンネルごとの固定値（`mmx::fpd_seed`）に置き換えた。`fpd` は元のデノーマル対策（`|x| < 1.18e-23` のサンプルを `fpd * 1.18e-17` に置き換える）にだけ使われる。64 bit 経路のディザの加算行は元から無効（コメントアウト）なので、信号にディザは足さない。`fpd` の状態更新（xorshift）は元どおりサンプルごとに行う。ディザは書き出しモジュールが別に担う（SPEC §6.5.2）
- **ブロック長への非依存（実時間適性）**: Console7Channel / Console7Buss は、フェーダー追従の初期化（`chasespeed` の倍増とホストのブロック長での上限、フェーダー値の取り込み）をホストのブロックごとに行う。これを、内部で数える固定の仮想ブロック（512 フレーム）ごとに行うようにした。出力は「ホストのブロック長が 512 のときの元の実装」と一致し、呼び出し側のブロックの切り方に左右されない
- Pressure4 のブロックごとの定数（閾値、リリース等）は、パラメータの変更時に計算する（パラメータとサンプルレートだけで決まるので結果は同じ）
- パラメータ ID と単位を付けた（`drive`、`input_gain_db`、`ceiling_db`、`fader`、`master`、`pressure`、`speed`、`mewiness`、`output_gain`）。ClipOnly2 には元にない入力ゲインと天井を前後のゲインとして足した（既定値では両方とも厳密に 1.0 で、元と同じ）
- 安全のための修正: ClipOnly2 の `intermediate[16]` は `spacing = 16`（705.6 kHz 以上）で範囲外に書くため 17 要素にした。Console7 の 20 kHz ローパスは、周波数比を 0.49 で頭打ちにした（約 40.8 kHz 未満のサンプルレートでだけ効く）
