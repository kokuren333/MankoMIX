# dsp — DSP エンジン

抽象プロセッサのグラフ（JSON のチェーン）を受け取り、バックエンドに割り当てて決定的に実行する（`docs/SPEC.md` §3.2、§6.5.2）。内部はすべて 64 bit 浮動小数点。

## 構成

| ファイル | 内容 |
|---|---|
| `processors.py` | 抽象プロセッサの定義（データ）。`PROCESSORS`、`describe(type)`、`validate_params(type, params)`、`graph_schema()` |
| `engine.py` | チェーンの検証と実行 `render_chain(...)`、書き出しモジュール `export_audio(...)` |
| `reference/` | `reference` バックエンド（numpy / scipy）。真のピーク検出器 `truepeak.py` を内蔵し、core に依存しない |
| `ffmpeg_backend.py` | `ffmpeg` バックエンド（外部プロセス）。ビルド構成の判定、符号化器の一覧、コーデック往復、`aresample` |
| `errors.py` | `DSPError`（`ValueError` の派生）。`rule` に違反した不変条件（`S-05` / `S-06` / `S-09` / `stage` / `params`）が入る |
| `native_backend.py`, `native/` | `native` バックエンド（C++ 核、M4。別担当） |

## バックエンド

- `reference` — 数値計算ライブラリ上の参照実装。BSD 系のみ。全プロセッサを実装
- `ffmpeg` — ユーザー環境の FFmpeg を外部プロセスとして呼ぶ。LGPL 構成のビルドに含まれる機能だけを使う（ネイティブ `aac`、`libmp3lame`、`libopus` / `libvorbis`、`aresample` の swr）。rubberband、libfdk、soxr は使わない。M2 では `resample` とコーデック往復を担う
- `native` — 自前のネイティブ DSP 核。MIT / Apache-2.0 のみ。将来のプラグイン核

`render_chain(..., backend_preference=("ffmpeg", "reference"))` のように優先順を渡すと、そのプロセッサを実装しているバックエンドのうち先頭が使われる。各ステップの記録に実行したバックエンドを残し、`RenderResult.backends` にバックエンドの版（FFmpeg は版とビルド構成）を残す（§9.6）。

## プロセッサ

| type | 主なパラメータ ID（単位） | 段 | マスター順の枠 | 実装 |
|---|---|---|---|---|
| `gain` | `gain_db` | track / bus / master | 中立（リミッターより前ならどこでも） | ○ |
| `pan` | `position`（−1..1）、`center_db`（既定 −3） | track / bus | — | ○ |
| `filter` | `kind`（hpf / lpf）、`freq_hz`、`slope_db_oct`（6/12/18/24/48） | track / bus / master | 1 修正 EQ | ○ Butterworth、最小位相。位相コストを記録 |
| `eq` | `shape`（peak / low_shelf / high_shelf / notch）、`freq_hz`、`gain_db`、`bw_oct`、`phase`（minimum / linear） | track / bus / master | 1 修正 EQ | ○ RBJ 双二次。帯域幅はオクターブ（R-12）。linear はプリリンギングを記録 |
| `dynamic_eq` | `shape`、`freq_hz`、`bw_oct`、`range_db`、`threshold_db`、`attack_ms`、`release_ms` | track / bus / master | 2 ダイナミクス | 宣言のみ |
| `compressor` | `threshold_db`、`ratio`、`knee_db`、`attack_ms`、`release_ms`、`detector`（peak / rms）、`rms_window_ms`、`makeup_db`、`stereo_link` | track / bus / master | 2 ダイナミクス | ○ フィードフォワード、GR 統計を記録 |
| `deesser` | `freq_hz`、`bw_oct`、`threshold_db`、`range_db` | track / bus / master | 2 ダイナミクス | 宣言のみ |
| `saturator` | `drive_db`、`mode`（tanh / asymmetric）、`asymmetry`、`mix`、`output_db`、`oversample` | track / bus / master | 3 エンハンス | ○ 倍音の偶奇を測定して記録 |
| `stereo` | `mono_below_hz`、`width`、`crossovers_hz[]`、`widths[]` | track / bus / master | 4 ステレオ | ○ M/S、Side を線形位相の相補 FIR で帯域分割 |
| `clipper` | `mode`（hard / soft）、`ceiling_db`、`drive_db`、`softness`、`oversample` | track / bus / master | 5 ラウドネス到達 | ○ オーバーサンプリング |
| `loudness_gain` | `gain_db` | master（枠 5、リミッターのドライブ）/ export | 5 | ○ |
| `limiter` | `ceiling_dbtp`、`lookahead_ms`、`release_ms`、`oversample` | master のみ | 6 最終段 | ○ True Peak リミッター |
| `reverb` / `delay` | `rt60_s`、`predelay_ms`、… / `time_ms`、`feedback`、`mix` | track / bus | — | 宣言のみ |
| `resample` | `target_sr` | export のみ | 書き出し 2 | ○ reference / ffmpeg |
| `dither` | `bit_depth`（16 / 24）、`type`（tpdf）、`noise_shaping`（none） | export のみ | 書き出し 3（最後） | ○ |

各定義は単位、範囲、既定値、`realtime`（`block_ok`、`latency_samples`、`allocates`、必要なら `latency_rule`）、`offline_only` を持つ（§14.2）。パラメータ ID は版をまたいで変えない。`allocates` は核の設計上の宣言であり、参照実装（numpy）は処理中にメモリを確保する。

## 規則（エンジンが強制する）

- パラメータは `validate_params` で検証する。未知の ID、範囲外、型違いは `ValueError`
- 段の規則: `limiter` はマスター段のみ、`resample` / `dither` は書き出し段のみ
- S-06: マスター段は「修正 EQ → ダイナミクス → エンハンス → ステレオ → ラウドネス到達（クリッパー、ドライブ）→ リミッター」の順。リミッターは最後で 1 つまで。違反は `S-06` を名乗る `ChainError`
- S-05: ディザの後には何も置けない。ディザ済みの音声（`DitheredAudio`）は `render_chain` と `export_audio` が受け付けない。書き出しの中でもディザは 1 回まで
- S-09: 各ステップの後で NaN / 無限大を検査して例外にする。`resample` 以外は長さを変えない。出力の DC が −60 dBFS を超えたら警告
- 警告: マスター EQ が ±2 dB 超（R-15）、マスター段の linear EQ がブーストまたは 1 dB 超のカット（§6.6.3）、リミッターの GR p95 が 4 dB 超（P-18）、コンプの GR p95 が 10 dB 超

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

## 守ること

- ネイティブ核は、UI、ファイル入出力、ネットワーク、エージェント層、プラグイン SDK のヘッダに依存しない（§14.2）
- GPL / AGPL のコードを持ち込まない（§13）。soxr / librosa のリサンプラーは使わない
