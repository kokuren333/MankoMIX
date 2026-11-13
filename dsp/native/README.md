# dsp/native — ネイティブ DSP 核

`native` バックエンド（`docs/SPEC.md` §3.2）の C++17 実装。C ABI を公開する共有ライブラリで、Python からは `dsp/native_backend.py`（ctypes）で呼ぶ。将来のプラグインシェル（§14、D-049）からも同じ核を呼ぶ。

## 守っていること（§14.2）

- UI、ファイル入出力、ネットワーク、エージェント層、プラグイン SDK に依存しない。依存は C++ 標準ライブラリだけ。入出力はサンプルバッファとパラメータだけ
- プロセッサ ID とパラメータ ID は安定。版をまたいで名前を変えたり消したりしない（追加はよい）
- `mmx_process()` はメモリ確保、ロック、入出力をしない。状態は `mmx_create()` で確保した固定長の領域にある
- 決定的。乱数を使わない（Airwindows の `fpd` は固定の種。`third_party/airwindows/ORIGIN.md`）。同じ入力・パラメータ・呼び出し順なら、ブロックの切り方によらずビット単位で同じ出力になる（テストで確認）
- 浮動小数点の再現性のため、fast-math と FMA への縮約を使わない（MSVC `/fp:precise`、GCC/Clang `-ffp-contract=off`）

## ビルド

```
python -I tools/build_native.py            # Release ビルド → dsp/build/lib/
python -I tools/build_native.py --clean    # dsp/build/ を消してから
python -m pytest -q tests/test_native_backend.py
```

- Windows: PATH に CMake がなければ、vswhere で Visual Studio を探し、同梱の CMake と Ninja を使う。コンパイラ環境が有効でなければ、同じインストールの `vcvars64.bat` の環境を読み込んで実行する。MSVC ランタイムは静的リンク（DLL 単体で動く）
- Linux / macOS: システムの CMake と C++ コンパイラを使う
- 中間生成物は `dsp/build/`（gitignore 済み）。成果物は `dsp/build/lib/mankomix_dsp.{dll,so,dylib}`
- 別の場所のライブラリを使うときは、環境変数 `MANKOMIX_NATIVE_LIB` にファイルを指定する
- ライブラリがなくても `native_backend` の import は失敗しない（`available()` が False を返す）

CMake を直接使う場合:

```
cmake -S dsp/native -B dsp/build/cmake -DCMAKE_BUILD_TYPE=Release
cmake --build dsp/build/cmake --config Release
```

## C ABI（`include/mankomix_dsp.h`、ABI 版 1）

| 関数 | 内容 |
|---|---|
| `mmx_version()` / `mmx_abi_version()` | ライブラリの版（`"0.1.0"`）と ABI 版（`1`） |
| `mmx_build_info()` | 版、ABI、コンパイラ、精度、レイアウト、Airwindows のコミットを JSON で返す |
| `mmx_processor_count()` / `mmx_processor_info(i, buf, buflen)` | プロセッサの記述を JSON で返す（snprintf と同じ規約。`buf = NULL` で長さを問い合わせる） |
| `mmx_create(id, sample_rate, channels)` | インスタンスを作る（8 k〜768 kHz、1〜8 チャンネル）。パラメータは既定値 |
| `mmx_set_param(h, param_id, value)` / `mmx_get_param` | 安定 ID でパラメータを設定・取得。範囲外は丸めて `MMX_OK_CLAMPED`（1）を返す。NaN は拒否 |
| `mmx_latency(h)` | レイテンシ（サンプル） |
| `mmx_process(h, double* const* channels, frames)` | **planar の double、その場で処理**。`channels[c]` がチャンネル c の連続した `frames` 個のサンプル。公称フルスケール ±1.0 |
| `mmx_reset(h)` | 信号の状態を作成直後に戻す（パラメータは保つ） |
| `mmx_destroy(h)` | 破棄 |

戻り値は 0 以上が成功、負がエラー（`MMX_ERR_*`）。例外は ABI を越えない。

プロセッサの JSON の形:

```json
{"id": "aw.clip_only2", "type": "clipper", "role": "safety_clipper", "name": "...", "summary": "...",
 "origin": {"source": "airwindows", "plugin": "ClipOnly2", "license": "MIT", "files": "...",
            "repository": "https://github.com/airwindows/airwindows", "commit": "94cb679..."},
 "channels": {"min": 1, "max": 8}, "sample_format": "planar_f64_inplace",
 "params": [{"id": "ceiling_db", "unit": "dBFS", "min": -24, "max": 0, "default": -0.4, "description": "..."}],
 "realtime": {"block_ok": true, "latency_samples": 1, "allocates_in_process": false, "deterministic": true}}
```

`type` は §6.5.2 の抽象プロセッサ（`saturator` / `clipper` / `compressor`）。`role` はその中の役割。

## プロセッサ

| ID | type | 由来 | パラメータ（ID: 範囲, 既定） | 性質 |
|---|---|---|---|---|
| `aw.purest_drive` | saturator | Airwindows PurestDrive | `drive`: 0〜1, 0 | 直前のサンプルに応じて掛かり方が変わるサイン飽和。0 で透明（奇数次優位） |
| `aw.clip_only2` | clipper | Airwindows ClipOnly2 | `input_gain_db`: −24〜24, 0 / `ceiling_db`: −24〜0, −0.4 | 天井の手前で角を丸めるセーフティクリッパー。天井以下では 1 サンプル遅れるだけ。レイテンシ 1 |
| `aw.console7_channel` | saturator（console_channel） | Airwindows Console7Channel | `fader`: 0〜1, 0.772 | Console7 の対の前半（各チャンネル、または 2mix に） |
| `aw.console7_buss` | saturator（console_buss） | Airwindows Console7Buss | `master`: 0〜1, 1.0 | Console7 の対の後半（合算の後）。channel → buss の既定値でほぼ単位利得（±0.25 dB 以内をテスト） |
| `aw.pressure4` | compressor（vari_mu_bus） | Airwindows Pressure4 | `pressure`: 0〜1, 0 / `speed`: 0〜1, 0.2 / `mewiness`: −1〜1, 1 / `output_gain`: 0〜1, 1 | 全チャンネル連動の vari-mu 風コンプ。最終段のサイン飽和で出力は ±1.0 以内 |

`norm` 単位のパラメータは、元のプラグインのつまみ（0〜1）と同じ尺度である。

## ライセンス

- 核（`include/`、`src/`、`CMakeLists.txt`）: Apache-2.0（本体と同じ）
- 移植した Airwindows のコード: MIT。ソースは `third_party/airwindows/src/` にあり、ライセンス原文は `third_party/airwindows/LICENSE`、出所（コミット、元のファイル名、変更点）は `third_party/airwindows/ORIGIN.md`
- GPL / AGPL のコードは含まない（§13）

## プロセッサを足すとき

1. `mmx::Processor` を実装し、`mmx::ProcessorSpec` を公開する（`src/mmx_processor.h` の規則を守る）
2. `src/registry.cpp` に登録し、`CMakeLists.txt` にソースを足す
3. 第三者コードなら `third_party/<name>/` に置き、`LICENSE` と `ORIGIN.md` を書く
4. `tests/test_native_backend.py` の `EXPECTED_IDS` に足す（決定性とブロック長非依存のテストが自動で掛かる）
