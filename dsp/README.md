# dsp — DSP エンジン

抽象プロセッサのグラフ（JSON のチェーン）を受け取り、バックエンドに割り当てて決定的に実行する（`docs/SPEC.md` §3.2、§6.5.2）。内部はすべて 64 bit 浮動小数点。

## 構成

| ファイル | 内容 |
|---|---|
| `processors.py` | 抽象プロセッサの定義（データ）。`PROCESSORS`、`describe(type)`、`validate_params(type, params)`、`graph_schema()` |
| `engine.py` | チェーンの検証と実行 `render_chain(...)`、書き出しモジュール `export_audio(...)` |
| `reference/` | `reference` バックエンド（numpy / scipy）。真のピーク検出器 `truepeak.py` を内蔵し、core に依存しない。`ballistics.py`（アタック／リリースの平滑化）、`dyneq.py`（dynamic_eq / deesser）、`space.py`（reverb / delay） |
| `native_wiring.py` | `native` バックエンドの実装表（`aw.*` と、平滑化をネイティブ核で回すダイナミクス系）と、`aw.*` の代替（fallback）へのパラメータ写像 |
| `ffmpeg_backend.py` | `ffmpeg` バックエンド（外部プロセス）。ビルド構成の判定、符号化器の一覧、コーデック往復、`aresample` |
| `errors.py` | `DSPError`（`ValueError` の派生）。`rule` に違反した不変条件（`S-05` / `S-06` / `S-09` / `stage` / `params` / `backend`）が入る |
| `native_backend.py`, `native/` | `native` バックエンド（C++ 核。ctypes で呼ぶ。`native/README.md`） |

## バックエンド

- `reference` — 数値計算ライブラリ上の参照実装。BSD 系のみ。全プロセッサを実装
- `ffmpeg` — ユーザー環境の FFmpeg を外部プロセスとして呼ぶ。LGPL 構成のビルドに含まれる機能だけを使う（ネイティブ `aac`、`libmp3lame`、`libopus` / `libvorbis`、`aresample` の swr）。rubberband、libfdk、soxr は使わない。M2 では `resample` とコーデック往復を担う
- `native` — 自前のネイティブ DSP 核。MIT / Apache-2.0 のみ。将来のプラグイン核。ライブラリ（`python -I tools/build_native.py`）があるときだけ登録される。Airwindows の移植（`aw.*`）と、`compressor` / `dynamic_eq` / `deesser`（ゲイン計算の平滑化をネイティブ核で実行。出力は reference とビット一致）を持つ

### バックエンドの選び方（`render_chain`）

1. ステップの `backend` が指定されていればそれ（使えなければ警告を残して次へ）
2. `backend_preference` の順で、その型を実装している最初のバックエンド（例: `("native", "reference")`）
3. それもなければ、プロセッサ定義の `backends` の順で使えるもの（`aw.*` は既定の `("reference",)` でも `native` で動く）
4. どれも使えない（`aw.*` でネイティブライブラリがない）とき、ステップに `fallback` があれば reference の代替プロセッサで実行し、記録と警告を残す。なければ `DSPError`（`rule="backend"`）

各ステップの記録に実際に実行したバックエンドを残し、`RenderResult.backends` にバックエンドの版（FFmpeg は版とビルド構成、native は版、ABI、ビルド情報、ライブラリの SHA-256。パスは残さない）を残す（§3.2、§9.6）。

### 代替（fallback）

`aw.*` のステップは `fallback` を持てる。

```json
{"type": "aw.purest_drive", "params": {"drive": 0.4}, "fallback": "saturator"}
{"type": "aw.console7_buss", "fallback": {"type": "gain", "params": {"gain_db": -0.5}}}
```

- 型名だけのときは、定義の `fallback.type` と一致しなければならず、パラメータは `native_wiring.py` の写像で決まる（近似。写像の説明は定義の `fallback.mapping`）
- `{"type", "params"}` のときは、そのパラメータをそのまま検証して使う
- 代替で動いたステップの記録: `type` / `params` は元のまま、`backend: "reference"`、`fallback: {type, params, mapping, reason, notes}`。警告に「近似」と理由が入る
- `limiter` / `resample` / `dither` は代替にできない。代替の型も同じ段で許されていなければならない

## プロセッサ

| type | 主なパラメータ ID（単位） | 段 | マスター順の枠 | 実装 |
|---|---|---|---|---|
| `gain` | `gain_db` | track / bus / master | 中立（リミッターより前ならどこでも） | ○ |
| `pan` | `position`（−1..1）、`center_db`（既定 −3） | track / bus | — | ○ |
| `filter` | `kind`（hpf / lpf）、`freq_hz`、`slope_db_oct`（6/12/18/24/48） | track / bus / master | 1 修正 EQ | ○ Butterworth、最小位相。位相コストを記録 |
| `eq` | `shape`（peak / low_shelf / high_shelf / notch）、`freq_hz`、`gain_db`、`bw_oct`、`phase`（minimum / linear） | track / bus / master | 1 修正 EQ | ○ RBJ 双二次。帯域幅はオクターブ（R-12）。linear はプリリンギングを記録 |
| `dynamic_eq` | `shape`（peak / low_shelf / high_shelf）、`freq_hz`、`bw_oct`、`range_db`（負 = カット）、`threshold_db`、`attack_ms`、`release_ms` | track / bus / master | 2 ダイナミクス | ○ 最小位相。閾値以下ではビット一致で素通し（R-13） |
| `compressor` | `threshold_db`、`ratio`、`knee_db`、`attack_ms`、`release_ms`、`detector`（peak / rms）、`rms_window_ms`、`makeup_db`、`stereo_link` | track / bus / master | 2 ダイナミクス | ○ フィードフォワード、GR 統計を記録。reference / native |
| `deesser` | `freq_hz`（既定 6.5 kHz）、`bw_oct`（既定 1）、`threshold_db`、`range_db`、`attack_ms`（既定 1）、`release_ms`（既定 60） | track / bus / master | 2 ダイナミクス | ○ スプリットバンド（検出帯域だけを下げる） |
| `saturator` | `drive_db`、`mode`（tanh / asymmetric）、`asymmetry`、`mix`、`output_db`、`oversample` | track / bus / master | 3 エンハンス | ○ 倍音の偶奇を測定して記録 |
| `stereo` | `mono_below_hz`、`width`、`crossovers_hz[]`、`widths[]` | track / bus / master | 4 ステレオ | ○ M/S、Side を線形位相の相補 FIR で帯域分割 |
| `clipper` | `mode`（hard / soft）、`ceiling_db`、`drive_db`、`softness`、`oversample` | track / bus / master | 5 ラウドネス到達 | ○ オーバーサンプリング |
| `loudness_gain` | `gain_db` | master（枠 5、リミッターのドライブ）/ export | 5 | ○ |
| `limiter` | `ceiling_dbtp`、`lookahead_ms`、`release_ms`、`oversample` | master のみ | 6 最終段 | ○ True Peak リミッター |
| `reverb` | `rt60_s`、`predelay_ms`、`er_late_db`、`mix`（1 = センド用の 100 % ウェット）、`lowcut_hz`（既定 600）、`highcut_hz`（既定 6000）、`rt60_low_mult`、`rt60_high_mult`、`bpm` | track / bus | — | ○ 決定的。自分のインパルス応答を測って記録 |
| `delay` | `time_ms`、`feedback`、`mix`、`note`（`1/8`、`1/8d`、`1/8t` など）、`bpm`、`lowcut_hz` / `highcut_hz`（0 = なし）、`route`（both / left / right） | track / bus | — | ○ 整数サンプルの正確な遅延。Haas 区分とモノ損失を記録（R-10） |
| `resample` | `target_sr` | export のみ | 書き出し 2 | ○ reference / ffmpeg |
| `dither` | `bit_depth`（16 / 24）、`type`（tpdf）、`noise_shaping`（none） | export のみ | 書き出し 3（最後） | ○ |

| `aw.purest_drive` | `drive`（0..1） | track / bus / master | 3 エンハンス | native のみ。代替 `saturator` |
| `aw.console7_channel` / `aw.console7_buss` | `fader` / `master`（0..1） | track / bus / master | 3 エンハンス（バスのまとまり） | native のみ。代替 `gain`（小信号の利得） |
| `aw.pressure4` | `pressure`、`speed`、`mewiness`、`output_gain` | track / bus / master | 2 ダイナミクス | native のみ。代替 `compressor`。既定の mewiness = +1 では波高率が**上がる**（測定値を記録） |
| `aw.clip_only2` | `input_gain_db`、`ceiling_db` | track / bus / master | 5 ラウドネス到達 | native のみ。代替 `clipper`。1 サンプルのレイテンシはオフラインで補償 |

各定義は単位、範囲、既定値、`realtime`（`block_ok`、`latency_samples`、`allocates`、必要なら `latency_rule`）、`offline_only` を持つ（§14.2）。`aw.*` のパラメータ ID、単位、範囲、既定値、レイテンシはネイティブ核の JSON と同じ（テストで照合）。パラメータ ID は版をまたいで変えない。`allocates` は核の設計上の宣言であり、参照実装（numpy）は処理中にメモリを確保する。

## 規則（エンジンが強制する）

- パラメータは `validate_params` で検証する。未知の ID、範囲外、型違いは `ValueError`
- 段の規則: `limiter` はマスター段のみ、`resample` / `dither` は書き出し段のみ
- S-06: マスター段は「修正 EQ → ダイナミクス → エンハンス → ステレオ → ラウドネス到達（クリッパー、ドライブ）→ リミッター」の順。リミッターは最後で 1 つまで。違反は `S-06` を名乗る `ChainError`
- S-05: ディザの後には何も置けない。ディザ済みの音声（`DitheredAudio`）は `render_chain` と `export_audio` が受け付けない。書き出しの中でもディザは 1 回まで
- S-09: 各ステップの後で NaN / 無限大を検査して例外にする。`resample` 以外は長さを変えない。出力の DC が −60 dBFS を超えたら警告
- 警告: マスター EQ が ±2 dB 超（R-15）、マスター段の linear EQ がブーストまたは 1 dB 超のカット（§6.6.3）、リミッターの GR p95 が 4 dB 超（P-18）、コンプの GR p95 が 10 dB 超

## ダイナミクスの平滑化（`reference/ballistics.py`）

アタック／リリースを分けた一次平滑化は、直前の出力で分岐する再帰なので `lfilter` にできない。ネイティブ核に `mmx_smooth_attack_release`（ライブラリ 0.2.0 以降、ABI 1 のまま追加）があればそれを使い、なければ同じ演算順の Python ループで計算する。ネイティブ核は FMA への縮約も fast-math も使わないので、両者の出力はビット一致する（テストで確認）。記録の `stats.ballistics` に `native` / `python` が入る。

- 3 分のステレオ 48 kHz（RMS 検出）: 約 4.1 s → 約 1.4 s（基準機）。平滑化だけなら 2.2 s → 0.06 s
- 検出器と GR の統計も見直した（チャンネル連動の最大値、パーセンタイルを 1 回で計算、`exp` でのゲイン変換）

## dynamic_eq / deesser（`reference/dyneq.py`）

- 構造: `y = x + (G(t) - 1) * B(x)`。`B` は帯域通過（peak、0 dB 頂点の RBJ BPF）または 2 次 Butterworth の LPF / HPF（シェルフ）。G を固定すれば `1 + (G - 1) B(z)` は最小位相のピーキング／シェルビングフィルタで、G は線形に入るので時変ゲインでも係数の更新が要らない
- `bw_oct` は帯域通過の −3 dB 点の間の幅（オクターブ）。中心での変化量はちょうど G。カット時は −6 dB 幅が少し狭まる
- 検出: 帯域信号の因果 RMS（窓は `freq_hz` の 2 周期、1〜50 ms）、チャンネル連動。閾値を超えた分だけ帯域を閾値に引き下げ（比は無限大）、`|range_db|` で頭打ち。閾値以下では出力が入力とビット一致
- 統計: `gain_change` / `gain_reduction`（GR 統計）、`activity`（作動時間の割合と回数）。dynamic_eq が 8 割超の時間作動したら「常時の問題には静的 EQ」（R-13）の注記
- deesser は同じ構造のスプリットバンド。既定の帯域は約 4.6〜9.2 kHz

## reverb / delay（`reference/space.py`）

reverb（決定的、LTI）:

- 初期反射: 固定の 12 タップ（4〜61 ms）。右出力は時間格子をずらし（+8.3 % + 0.7 ms）、中央の音源でも左右が無相関になる
- 後期: 4 段のシュレーダー全域通過（`z^-D` を行方向の単位遅延に読み替えて厳密かつベクトル化）→ 8 本の FDN（アダマール行列、各線路に吸収フィルタ）。吸収は 1 周あたり `-60 dB × m_i / (sr × RT60(帯域))` で、帯域は 250 Hz / 4 kHz の RBJ シェルフで分ける（`rt60_low_mult` / `rt60_high_mult`）
- ER と後期はエネルギーを正規化して `er_late_db` で混ぜ、`predelay_ms` だけずらす。ウェット側に 12 dB/oct の `lowcut_hz` / `highcut_hz`（§6.5.4 のプレート系: 600 Hz / 6 kHz が既定）
- インパルス応答（最も長い帯域で −90 dB まで、最長 30 s）を作り、重畳加算の FFT 畳み込みで適用する（真のステレオ: 入力 2 × 出力 2。入力ブロックの FFT を出力間で共有）。3 分のステレオで約 3 s
- `y = (1 - mix) × dry + mix × wet`。`mix = 1` がセンドバス用の 100 % ウェット
- 統計（自分のインパルス応答の測定）: 帯域別 RT60（250 / 1k / 4k Hz のオクターブ帯域、シュレーダー積分の T20）、ER/late の比、白色入力での D/R、左右の相関とモノ損失（`mono_compatible`）。`bpm` を与えるとプリディレイと RT60 を音価でも記録（R-11）
- 入力の終端より後の残響は描かない（長さを変えない規則。`tail_truncated_at_end`）

delay:

- `w[n] = u[n - D] + feedback × w[n - D]`。`D` は `time_ms`、または `note` と `bpm` から決まる整数サンプル（4 分音符 = 1 拍、`d` = 付点、`t` = 3 連）。行方向の再帰で厳密にベクトル化
- フィルタはウェットの入力に掛ける（どの繰り返しも同じ帯域）。`route` = left / right で片側だけに遅延を足す（Haas）
- 統計: 遅延サンプル数、音価（`bpm` があれば最寄りの音価と偏差）、Haas 区分（< 5 ms 定位／コム・リスク、5〜30 ms 融合、> 30 ms エコー。R-10）と必ず対になるモノ損失（入力、出力、変化量）と最初の繰り返しによるコムの谷（周波数、深さ）、帰還の 60 dB 減衰時間

## True Peak リミッター

- 検出: 4 倍以上かつ実効 192 kHz 以上のオーバーサンプリング（Kaiser 窓 sinc のナイキストフィルタ）。倍率は BS.1770 型の基準倍率の整数倍に取り、基準倍率のメーターが評価する点をすべて含める。倍率が 4 の倍数でないとき（44.1 kHz で 10 倍）は 4 倍の格子も併せて検出する
- ゲイン: 先読み区間の前方最小 → 指数リリース（dB 域）→ 合計長が先読み＋1 の二段の移動平均。ピーク位置では必ず必要ゲイン以下になる
- 検証: 出力を同じ検出器で測り直し、天井を超えたら内部目標を下げて再計算する（最大 6 回、最後は静的トリム）
- オフライン処理では先読みのレイテンシを補償する（出力は入力と時間がそろい、長さも変わらない）。天井より小さい入力はビット一致で素通しする
- 統計: GR の中央値、p95、1 dB 超の時間割合、最大（P-18）

## 書き出し（`export_audio`、§5.3）

`profiles/delivery_formats.json` の形式（または ID）を受け取る。

- コンテナは出力の拡張子で決め、形式の `container` に含まれることを確かめる（wav / flac / aiff）
- サンプルレート: `native` は元のまま。候補が複数ならば元のレートが含まれればそれ、なければ先頭（引数 `sample_rate` で選べる）。変換は書き出しだけが行う（`resample_poly`、Kaiser 窓、阻止域約 120 dB、通過域は低い方のナイキストの 94 %）
- 深度: 16 / 24 bit は `WAVE_FORMAT_PCM`、32f は IEEE float。量子化は整数で書くのでビット正確
- ディザ: ワード長が減るときだけ、最後に 1 回、TPDF（±1 LSB）、ノイズシェーピングなし。乱数は numpy の PCG64 で、種は呼び出し側が正本のハッシュから決める（`seed_from_hash`、§9.6）。形式の `dither` が `"none"` のときは丸めで量子化し、記録と警告を残す（引数 `dither="tpdf"` で上書き可）
- 記録: `sample_rate`、`bit_depth`、`container`、`dithered`、`dither {type, seed, ...}`、`resampled_from`、`resample_backend`、`wav_format_tag`、`true_peak_dbtp`、`steps`、`warnings`。ファイル名だけを残し、絶対パスは残さない

## FFmpeg バックエンド

- `available()`、`version_info()`（`{version, configuration, build: lgpl|gpl|nonfree}`）、`encoders()`
- `encode_decode_roundtrip(x, sr, codec, bitrate)`: `aac` / `opus` / `mp3` / `ogg_vorbis`。一時ディレクトリで符号化と復号を行い、冒頭数秒の相互相関で符号化器の遅延を求めて元の長さにそろえる。符号化器がなければ `None`（「未実施」として記録する）
- `resample(x, sr_in, sr_out)`: `aresample`（swr）
- 一時ディレクトリを作業ディレクトリにしてファイル名だけで呼ぶので、エラー文に絶対パスが出ない。すべての呼び出しにタイムアウトを付ける

## ネイティブの Airwindows プロセッサ（`native_wiring.py`）

- 1 ブロックで処理し、レイテンシを補償する（出力は入力と時間がそろい、長さも変わらない）
- 統計: ネイティブ ID、出所（MIT、Airwindows）、レイテンシ、RMS と波高率の入出力（測定値。Pressure4 で波高率が上がれば注記）、飽和系は 1 kHz の正弦で測った倍音の偶奇
- 8 チャンネルを超える入力は `DSPError`（`rule="backend"`）

## 守ること

- ネイティブ核は、UI、ファイル入出力、ネットワーク、エージェント層、プラグイン SDK のヘッダに依存しない（§14.2）
- GPL / AGPL のコードを持ち込まない（§13）。soxr / librosa のリサンプラーは使わない
