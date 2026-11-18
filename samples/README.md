# samples — 公式サンプル

README の聴き比べに使う公式サンプル（「マンコ主義」）の置き場。方針は `docs/SPEC.md` §15 にある。

> **利用条件（D-062）**: Suno で生成。利用条件は Suno の規約に従う。AI の学習への利用は許諾しない。本体の Apache-2.0 の対象外。
> *Generated with Suno. Use is subject to Suno's terms. Not licensed for AI training. Not covered by the repository's Apache-2.0 license.*
> この条件は、サンプルの音声（試聴用コピー、マスター、処理前、除去分、参考フルミックス）と入力ステムのすべてに適用される。

## 中身

| パス | 内容 |
|---|---|
| `sample_set.json` | サンプルの種別の定義。目的関数 × 媒体プロファイルの 11 種、処理前の定義、強度 0.5、ジャンル `hiphop`、リファレンスなし、置き場 |
| `public/manifest.json` | サンプルの目録（機械可読）。下の「目録」を参照 |
| `public/reports/vNN/` | 種別ごとの Mix Report。`report.json`（ja + en）、`report.ja.md`、`report.en.md`、検証結果 `verify.json` |
| `public/audio/*.mp3` | 試聴用の MP3（320 kbps）。**マスターではない**。下の「音声の扱い」を参照 |

聴き比べに置く音声（SPEC §15.2）:

- **処理前（before）**: 12 ステムの単純合算（各ステムのゲイン 0 dB、ステレオのまま、処理なし。D-036）。本体の `listen` が作る
- **処理前のレベルマッチ版**: 主サンプル（#1）との対だけをファイルにする。統合ラウドネスを揃えるときは大きい方を下げる。どちらを下げたかは目録の `audio.level_matched_pair` にある。ほかの種別は、目録の `level_match.gain_db` を数値で持つ
- **参考: 既存フルミックス**: conform 済みのフルミックス。参考であり、処理前の基準ではない（ステムの合算と一致しない）
- **処理後**: 11 種（`sample_set.json`）。主サンプルは `distributor_44k16` でも書き出す
- **主サンプル（指揮つき）**: 2026-11-18 版では、#1 の既定処理（床）に指揮書 `dir_cf3e85c484fa`（空間音響 × 複雑で心地の良いパンニング）を `direction apply` で重ねたものを主サンプルとする。`audio/v01_main_direction.mp3` とレベルマッチ版 `audio/v01_main_direction_level_matched.mp3`。Mix Report と `direction check` の結果は `public/reports/main/`、目録では `main_sample`。指揮書の本文は案件記録としてローカルの蓄積 kb に置き、公開しない（D-068）。#1 そのもの（床）は `audio/v01_comfort__streaming_universal.mp3`
- **2026-11-18 版の状態**: 11 種のうち 8 種が検証に合格。クラブの 3 種（#9〜#11）はマスター段で S-08（ノイズ戻り監視）の差し戻しにより停止し、音声はない（許容幅は緩めていない）。詳細は目録の `summary`
- **除去分（delta）**: 主サンプルの整音で除去した成分

`spotify`、`youtube`、`amazon_music`、`tidal`、`sns_safe` は音声を作らない。主サンプルのマスターがそれぞれのプロファイルの検証に通るかどうかだけを、目録の `verification_only_profiles` に表で載せる。トランスレーション・ゲート（OF-5）の合否は、種別ごとに `translation_gate` にある。

## 入力

- 正本は **conform 済みセット**（48 kHz、12 ステムと `fullmix_conformed.wav`）。ステムはファイル名で選ぶ。同じフォルダにある `other` と `no_vocals`（ステムを合算した派生ファイル。D-037）と、`0_fullmix`（時間整合前のダウンロードしたままのフルミックス）は**明示的に除外**する。除外したファイル名と理由は、目録の `source.excluded` に記録する
- 書き出しセット（Suno Studio からダウンロードしたままのフォルダ）も、`--source-kind export` でそのまま入力にできる。「ダウンロードしたものをそのまま入れられる」という約束の実証である（SPEC §15.1）。聴き比べに使うのは conform 済みセットの結果である
- ジャンルは `hiphop` を宣言し（D-053）、リファレンスは登録しない（D-039）。各 Mix Report にその旨が書かれる
- 入力ファイルの内容ハッシュ（sha256）は目録の `source.inputs` にある。素材のローカルの所在はどこにも記録しない

## 再生成の手順

すべての音声は本体のコマンドで作る。手作業では作らない。サンプルの場所は環境変数で外から渡す。

```sh
# conform 済みセット（正本）: samples/public/ と tmp/release_assets/ を書き出す
MANKOMIX_SAMPLE_DIR=<conform 済みセットのフォルダ> python -I tools/build_samples.py --jobs 2

# 書き出しセットをそのまま入力にする（結果は tmp/sample_build/export/ に置く）
MANKOMIX_SAMPLE_EXPORT_DIR=<ダウンロードしたフォルダ> python -I tools/build_samples.py --source-kind export

# 一部の種別だけ作る（番号は sample_set.json の n）
MANKOMIX_SAMPLE_DIR=<...> python -I tools/build_samples.py --variants 1,8
```

ビルダー（`tools/build_samples.py`）の処理:

1. 種別ごとに独立したプロジェクトを作る。`python -m mankomix.cli init` と `python -m mankomix.cli run --variants ...` を実行する。種別ごとにプロジェクトを分けるのは、ある種別の差し戻しや検証不合格で、ほかの種別が止まらないようにするためである。各種別のミックスは、その種別の目的関数で計画する
2. `listen` で処理前（ステムの合算）と参考フルミックスを得る。`measure` で LUFS、True Peak、主要な代理指標を測る。`gate` でトランスレーション・ゲートを判定する
3. 外部プロセスの ffmpeg（libmp3lame）で試聴用の MP3 を作る
4. 検証に通ったマスター（納品形式どおりのロスレス）だけを `tmp/release_assets/` に置く。将来の Release 添付用で、git の対象外である

種別ごとの正確なコマンドは、目録の `regeneration` にある。サンプルのフォルダは `$MANKOMIX_SAMPLE_DIR`、作業フォルダは `$WORK` のプレースホルダーで書いてある。検証に落ちた種別や、マスタリング段からの差し戻しも結果として記録する。目録の `summary` に一覧がある。

conform 済みセットは、選んだ 13 ファイルを明示した一覧として `run` に渡す（ばらのファイルは 1 組として取り込まれる。変換もリネームもしない）。除去分は `clean delta stems`（処理前のステム合算から、整音後のステム合算を引いたもの）で作る。検証のみのプロファイルの表は `verify --against-profile <id>` で作る（描き直さず、プロジェクトも変えない）。

## 音声の扱い

- 試聴用の MP3 は、マスターから作った**試聴用の複製であり、マスターではない**（SPEC §5.3、§15.3）。ブラウザなどでそのまま再生できるように MP3 にしている
- ロスレスのマスターと入力ステムは、GitHub の Release 添付に置く（作業中は `tmp/release_assets/`）
- **試聴用の MP3（`public/audio/*.mp3`）はコミットする**（D-061、オーナー承認済み）。`.gitignore` は音声を既定で除外し、`samples/public/audio/*.mp3` だけを例外にする（SPEC §15.4）。ロスレスのマスターと入力ステムはコミットしない
- 公開の直前に、権利条件を一次資料で再確認する（SPEC §15.4、M9）
