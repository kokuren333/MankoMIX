# tests — テスト

テストの方針は `docs/SPEC.md` §16 にある。

## 層（§16.1）

| 層 | 内容 |
|---|---|
| 測定の適合 | ラウドネス（EBU Tech 3341 / 3342 の考え方の合成信号）、True Peak（サンプル間ピークを持つ合成信号） |
| DSP の単体 | 正弦波、スイープ、インパルス、ピンクノイズでの周波数応答、ゲイン、時定数、レイテンシ |
| 不変条件 | S-01〜S-11 を合成素材とランダムなパラメータで検査（性質ベース）。整音の低域無傷はヌルテスト |
| 決定性 | 同じ正本と素材から2回レンダリングしてビット一致 |
| パイプライン | 合成のステム一式で取り込みから検証とレポートまで |
| スキーマとデータ | 正本、目的関数、媒体プロファイル、レジストリの JSON |
| 顔の等価性 | CLI と MCP が同じ操作で同じ正本の変更を生むこと |
| 衛生とライセンス | `test_hygiene.py`（`tools/check_hygiene.py` を実行） |

## テスト素材（§16.2）

テスト素材は合成信号に限り、コードで生成する。**音声ファイルをリポジトリに置かない。**

- `fixtures/synth.py` — 決定的な信号生成器。すべて `float64`、形は `(frames, channels)`。
  - 基本: `sine`、`sweep`（対数）、`impulse`、`white_noise`、`pink_noise`、`silence`、レベル換算（`db_to_amp`、`rms_dbfs`、`peak_dbfs` など）
  - 測定の適合: `ebu_tone_sequence`、`intersample_peak_signal`（fs/4、45°、True Peak がサンプルピークより +3.01 dB）
  - 合成ソング: `song_stems()`（8 秒、48 kHz、120 BPM、A マイナー、12 ステム、ステレオ。前半が静かなセクション、後半が盛り上がるセクション。`song_sections()` で境界を得る）。部品として `kick`、`snare`、`hihat`、`bass_line`、`vocal_line`、`pad_chords`
  - AI 生成音源らしい欠陥（§6.4）: `add_hf_ceiling`（高域の頭打ち）、`add_shimmer`（10〜14 kHz の信号相関・変調ノイズ）、`add_head_click`、`add_noise_floor`、`add_lowmid_buildup`、`make_overlimited`、`add_dc`、`inject_nan`、`antiphase_low`（S-03 用）
  - `stem_sum`（ゲイン 0、先頭そろえ、短いものは末尾を無音で埋める）、`write_wav`、`read_wav`
- `fixtures/plugin.py` — 共有 fixture（`conftest.py` が登録）

| fixture | スコープ | 内容 |
|---|---|---|
| `sr` | session | 48000 |
| `rng` | function | 固定シードの `numpy.random.Generator` |
| `song_stems` | session | 役割名をキーにした 12 ステムの dict（読み取り専用） |
| `song_sections` | session | 静かなセクションと盛り上がるセクションの範囲（秒） |
| `song_mix` | session | ステムの単純合算をピーク −6 dBFS に正規化したもの（読み取り専用） |
| `defective_mix` | session | `song_mix` に高域の頭打ち（16 kHz）、シマー、冒頭クリックを加えたもの（読み取り専用） |
| `stems_dir` | function | 一時フォルダに `<role>.wav`（32 bit float）を書いたもの |
| `mix_wav` | function | 2mix の WAV |
| `defective_mix_wav` | function | 欠陥入り 2mix の WAV |

session スコープの配列は書き込み禁止にしてある。変更するときは `.copy()` してから使う。

## 実行

リポジトリのルートで:

```
python -m pytest -q
```

一部だけ:

```
python -m pytest -q tests/test_synth.py
```

## マーカー

| マーカー | 意味 |
|---|---|
| `sample` | 公式サンプルを使う回帰テスト。`MANKOMIX_SAMPLE_DIR` が未設定なら自動でスキップ |
| `ffmpeg` | ffmpeg が必要。PATH にないと自動でスキップ |
| `slow` | 時間のかかるテスト。`-m "not slow"` で除外できる |

## 環境変数

| 変数 | 意味 |
|---|---|
| `MANKOMIX_SAMPLE_DIR` | 公式サンプルの conform 済みセットのフォルダ（§15.1）。設定したときだけ `sample` のテストが動く |
| `MANKOMIX_SAMPLE_EXPORT_DIR` | 任意。Suno Studio からダウンロードしたままの書き出しセットのフォルダ |
| `MANKOMIX_SKIP_HYGIENE` | `1` にすると衛生検査のテストをスキップする。git がない環境や、git の checkout でない書き出し済みのツリーでは自動でスキップされる |

サンプルの場所は外から指定する。ローカルの所在をリポジトリ内のファイルに書かない（所在の記録は `_private/` だけ）。
