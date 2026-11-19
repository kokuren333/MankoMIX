# MankoMIX

AI 生成楽曲や既存のステムを、**人の耳にとって聞き心地がよいもの**に、あるいは**目的に沿ったもの**（重低音強化、ボーカル前面など）に仕上げるための、AI エージェント向けミックス／マスタリングツール。

> **状態: 公開プレビュー（v0.1、pre-1.0）。** 取り込み、測定、整音、ミックス、マスタリング、検証、Mix Report、ステム分離、CLI、MCP、ローカル GUI に加え、楽曲ごとの指揮書で方向付けするディレクターレイヤー（後述）が動く。Apache-2.0 で公開しているが、まだ開発中であり、仕様・挙動は今後変わりうる。進み具合は [docs/SPEC.md](docs/SPEC.md) §17 のマイルストーンに沿う。

**▶ デモ（GitHub Pages）: https://kokuren333.github.io/MankoMIX/** — インストール不要、ブラウザ内モックで GUI をそのまま触れる。Pages デモでは主サンプルを処理前→床（#1 指揮なし）→指揮版の 3 段で切り替えて聴ける。#2〜#8 も測定値・レベルマッチ付きで試聴でき、#9〜#11 は未完成（音声なし、S-08）と表示される。

## 何をするツールか

入力はステム群（または 2mix）。指定するのは「目的関数」と「媒体プロファイル」。出力は、その媒体向けのマスター音声と、全ての判断を記録した Mix Report。

```
入力アダプタ → [任意] ステム分離 → 解析 → 整音 → ミックス → マスタリング → 検証 ＋ Mix Report
```

- **目的関数（意図）** — デフォルトは「聞き心地」。ほかに重低音強化、ボーカル前面、明瞭さ、クラブ・インパクトなどを名前で選び、強度を指定し、混合できる
- **媒体プロファイル（出口）** — Spotify、YouTube、Apple Music、SNS、クラブ、CD など。ラウドネスと True Peak の条件、納品形式を定める
- 目的関数と媒体プロファイルは独立した軸で、自由に組み合わせる（例: 重低音強化 × クラブ）

## 特徴

- **決定的な DSP と実測検証** — 生成モデルで音を作り直すのではなく、実ファイルを決定的に処理する。元の演奏はそのまま保たれ、同じプロジェクトから同じ出力が再現できる
- **測って、決めて、測り直す** — エージェントは測定値に基づいてパラメータを決め、処理後に再測定して検証する
- **判断の透明性** — 何を測り、なぜその処理を選んだかを Mix Report に全て残す。提案されたチェーンは後から編集できる
- **AI 生成音源の整音** — 高域のシマー（シュワシュワ音）や高域欠落に対処し、マスタリング後にノイズが戻っていないかまで監視する
- **ダウンロードしたままのステムがそのまま入力になる** — Suno Studio のマルチトラック書き出しを展開したフォルダを、変換もリネームもせずに取り込める。原本は変更しない
- **ステム単位のリミックス** — ステムの差し替え、追加、再配置をプロジェクト形式で扱う
- **エージェント主軸** — ヘッドレスのコア、JSON 正本のプロジェクト形式、CLI と MCP。人間向けの GUI も同じ正本を共有する
- **指揮書による方向付け（ディレクターレイヤー）** — 自然文の依頼に対して、その曲の解析（ドシエ）に基づく指揮書を作り、コアの外側から適用する。適用後は目標への到達を測り直し、指揮書で宣言された範囲内なら適用量の自動較正（`direction apply --calibrate`）もできる。使った指揮書・解析・知見は Markdown で蓄積し、再利用する（蓄積先はローカルの `_private/kb/` が既定で、公開リポジトリの `kb/` には既定のカードだけが入る）
- **VST プラグイン化（将来フェーズ）** — DAW の中で直接使える VST プラグイン版を将来実装予定。現行の提供形態は CLI／MCP／ローカル GUI のみで、プラグイン版はまだ無い

自動指標は知覚の代理に過ぎない。最終判定は人の耳であり、Mix Report は必ず「人の耳で確認すべき点」を含む。

## 使い方

### インストール

Python 3.11 以上。FFmpeg は同梱しないので、別にインストールして `PATH` に置く（コーデック往復の検証と、MP3 などの読み込みに使う。LGPL 構成のビルドを推奨。`mankomix doctor` がビルド構成を確認する）。

```
pip install -e .                 # コア（numpy / scipy / soundfile / jsonschema）
pip install -e ".[separation]"   # 任意: ステム分離（推論は別プロセスで動く）
python -I tools/build_native.py  # 任意: ネイティブ DSP 核（C++）。なければ Python 実装で同じ結果を出す
mankomix doctor
```

コマンドは `mankomix`（短縮名 `mmx`）。全コマンドが JSON を出力し、終了コードで成否を返す（0 成功 / 1 検証不合格 / 2 入力エラー / 3 環境エラー）。

音声ファイルだけのコーデック下見は、プロジェクト外でも
`mmx direction preview codec --audio input.wav --codec aac` で実行できる。
入力は変更せず、`--out listen` を指定した場合だけ試聴ファイルを保存する。
拡張コマンドの任意プロジェクト宣言は [commands の README](director/commands/README.md)、
派生音声を作らない group 編集計画 `ClipBundle` は [xops の README](director/xops/README.md) を参照。

### 一括実行

```
mankomix run ./stems --objective comfort --profile spotify --delivery distributor_44k16 --out ./out
mankomix run ./stems --objective bass_heavy:0.7 --profile club --out ./out
mankomix run ./song.wav --objective comfort:0.6+vocal_forward:0.4 --profile apple_music --out ./out
```

`./stems` は、Suno Studio のマルチトラック書き出しを展開したフォルダをそのまま指定できる。2mix を 1 本だけ渡すと、フルミックス経路でマスタリングする（`--separate` でステム分離から始めることもできる）。`./out` にマスター、マニフェスト、検証結果、Mix Report（JSON と Markdown）が出る。検証に通らなかった出口のマスターは納品物に入れず、理由（差し戻し）をレポートに書く。

### 段ごとの操作

```
mankomix init my_song.mmx --genre hiphop
mankomix -p my_song.mmx import ./stems
mankomix -p my_song.mmx analyze
mankomix -p my_song.mmx objective set comfort
mankomix -p my_song.mmx clean plan                 # 提案だけ（適用はしない）。提案 ID が返る
mankomix -p my_song.mmx clean apply <提案 ID>       # 確認してから適用
mankomix -p my_song.mmx mix plan --apply            # 提案してそのまま適用
mankomix -p my_song.mmx master plan --profile streaming_universal --apply
mankomix -p my_song.mmx render && mankomix -p my_song.mmx verify && mankomix -p my_song.mmx report
```

提案は全て、適用前に確認・編集・却下できる。正本（`project.json`）の変更は全て履歴に残り、`undo` / `checkout` で戻せる。コマンドの一覧は [cli/README.md](cli/README.md)。

### 指揮書で方向付ける（任意）

目的関数の指定とは別に、自然文の依頼から作る指揮書で、その曲に合わせた方向付けができる。指揮書の形式は [docs/DIRECTION_FORMAT.md](docs/DIRECTION_FORMAT.md)。

```
mankomix direction dossier --project my_song.mmx --song <slug> --out dossier.md   # 曲の解析ドシエを作る
mankomix direction validate direction.md                                          # 指揮書の検証
mankomix direction apply --project my_song.mmx direction.md                       # 適用（--calibrate で宣言範囲内の量を自動較正）
mankomix direction check --project my_song.mmx --floor <床のプロジェクト> direction.md  # 目標への到達と床からの乖離を測定
mankomix kb index                                                                 # kb/ の知見蓄積を再構築
mankomix kb lint                                                                  # kb/ の検査
```

任意で、利用者が持ち込んだリファレンス（マスターやステム）を測って指揮書の材料にできる（`direction ref study|compare|credit|list`）。これは目標への自動一致ではなく、差を問いとして読むための資料で、使わなくても指揮書は従来どおり動く。kb のカードは `kb search`／`kb show` で引ける。詳しくは [docs/DIRECTION_FORMAT.md](docs/DIRECTION_FORMAT.md) §6。この経路の効き目は、プロの市販音源ではまだ確かめていない。

指揮書で選べる手には、ステムの内容の無い区間を無音化する編集 op（`edit_trim`／`edit_gate`）と、あるトラックが鳴る瞬間だけ別のトラックを下げる `duck` もある。観察量の `view`（モノ・帯域制限の見方）、`direction check --translation`、`direction ref study|compare --add` も選べる。どれも任意で、使わなくても指揮書は従来どおり動き、不利にもならない。

トラックごとの観察量（`trk_<stem>` を対象にした測定と、定位 `image_position`・埋もれ `masking`・残響の付き方 `wet_ratio`）、配置の宣言 `scene`、方位と距離からパン・レベル・高域・センドを導く手 `place`、全トラック横断の下見 `direction stems observe|relate|purity`（何も書かない）も選べる。`direction validate` は、台帳指標（`P-nn`）に立てた主張・期待・安全弁を警告 `unmeasured_quantity` で知らせる（`direction check` は結果を測り直さず、標準の流れでは判定されないため）。これらで音が良くなることは実証していない（[docs/DIRECTION_FORMAT.md](docs/DIRECTION_FORMAT.md) §8）。

```
mankomix direction stems relate --project my_song.mmx                               # 全トラック横断の被りの表（何も書かない）
mankomix direction stems purity --project my_song.mmx                               # ステムの共有成分・焼き付いた残響などを測る（何も書かない）
mankomix direction edit scan --project my_song.mmx --track <trk> --op edit_gate     # 編集 op が切る区間・拒否する区間を下見する（何も書かない）
mankomix direction edit revert --project my_song.mmx --direction <dir_id>           # 編集で無音化した区間を戻す
```

追補 4 では、枠の宣言 `frame`、部屋の宣言 `scene.room`、直さない出口 `triage`、名前を隠した聴き比べの書き出しと聴取記録（`direction listen pack|record`）、居場所の表（`direction stems placement`）、重なりの軸（`direction stems relate --axes`）、段階の測定（`direction stems stages`、観察量の対象 `mix`）、側成分の見方（観察量の `view: side`）、時間つきのゲイン列 `gain_curve`（下見は `direction stems phrases`）、編集の一覧と曲線と空白（`direction check --edit-list`／`--contour`）、配線の図（`direction wiring`）、kb のカードの立場の欄 `stance` が加わった。どれも任意で、使わなくても指揮書は従来どおり動き、不利にもならない。これらで音が良くなることは実証していない（[docs/DIRECTION_FORMAT.md](docs/DIRECTION_FORMAT.md) §9）。

**持ち込む音源の入手と利用条件は、利用者の責任で確かめること。** 本ツールは持ち込まれた音源をその場で測るだけで、音源やその変換物を保存しない。第三者の作品の測定は、既定で非公開の `_private/kb/` に置かれる。
素材の入手は利用者が公式の経路で行う。本ツールは素材を探しにも取りにも行かない（kb のカードに残せるのは所在メモと権利注記だけ）。

### エージェントから（MCP）

```
mankomix mcp --root <作業フォルダ>
```

標準入出力の MCP サーバー。ツールは CLI と 1 対 1 で対応し、応答は要約が既定（詳細度は引数で指定）。時間のかかる処理はジョブとして実行する。設定例とツールの一覧は [mcp/README.md](mcp/README.md)。

### GUI

```
mankomix serve -p my_song.mmx
```

ループバックでローカルサーバーを起動し、ブラウザの GUI から同じプロジェクトを操作する。CLI や MCP からの変更は GUI に即座に反映される。詳しくは [gui/README.md](gui/README.md)。

## サンプル聴き比べ

公式サンプル「マンコ主義」（Suno で生成、hiphop、98.9 秒、12 ステム）を本ツールで処理した試聴用の MP3（320 kbps）。**マスターではない**。2026-11-18 に現在のハーネスで作り直した。利用条件は [samples/README.md](samples/README.md)（Suno の規約に従う。AI の学習への利用は許諾しない。本体の Apache-2.0 の対象外）。目録（測定値・検証結果・ハッシュ・再生成コマンド）は [samples/public/manifest.json](samples/public/manifest.json)、Mix Report は [samples/public/reports/](samples/public/reports/)。

| 音声 | 内容 | 試聴 |
|---|---|---|
| 処理前 | 12 ステムの単純合算（各ステムのゲイン 0 dB、無加工）。−15.03 LUFS、True Peak −0.59 dBTP | [before.mp3](samples/public/audio/before.mp3) |
| 処理後（主サンプル） | 床（下の #1 の既定処理）に指揮書 `dir_cf3e85c484fa`「空間音響 × 複雑で心地の良いパンニング」を重ねた版。−14.01 LUFS、True Peak −1.01 dBTP（streaming_universal の検証に合格） | [v01_main_direction.mp3](samples/public/audio/v01_main_direction.mp3)<br>レベルマッチ版: [v01_main_direction_level_matched.mp3](samples/public/audio/v01_main_direction_level_matched.mp3) |
| 処理後（各種別） | 目的関数を変えた版、媒体を変えた版、両方を組み合わせた版。全 11 種のうち 8 種を収録（下表） | 下表 |
| 除去分 | 整音で取り除いた成分だけ（処理前のステム合算 − 整音後のステム合算）。主サンプルの指揮は整音を変えていないため、床と同一 | [delta.mp3](samples/public/audio/delta.mp3) |
| 参考: フルミックス | Suno のフルミックス（時間整合済み）。参考であり、処理前の基準ではない（ステムの合算とは一致しない） | [fullmix_reference.mp3](samples/public/audio/fullmix_reference.mp3) |

聴き比べは、処理前と処理後の音量を揃えた版（レベルマッチ版）を主に置く。音量が大きい方を「良い音」と感じる錯覚を除くためである。主サンプルのレベルマッチ版は、処理後を純ゲイン −1.02 dB で下げて処理前と統合ラウドネスを揃えたもの（実測の差 0.006 LU）。処理前 [before.mp3](samples/public/audio/before.mp3) と対で聴く。

### 主サンプル: 指揮の分（床との差）

床は #1（聞き心地 × ストリーミング共通）の既定処理。主サンプルは床をそのまま出発点にし、次だけを変えた。vocals・drums・bass、整音、床のチェーンとフェーダー、マスター段は床のまま。

- 方位: guitar +0.35 → +0.5、keyboard −0.2、synth +0.2、woodwinds・brass・strings を中央へ寄せ直し（床は woodwinds −0.35、strings +0.5）
- 動き（`autopan`、レベル差のパン）: fx は 3 小節周期の周回、上物 5 本（keyboard・synth・woodwinds・brass・strings）は同じ設定で 4 小節周期の浅い流れ、percussion は 1 小節で左右に跳ぶ、BV はエコーの戻りだけが動く
- 部屋: 初期反射だけの部屋（`early_reflections` のバス）を追加し、`place` で距離 4 段（センド量と高域）を付けた。フェーダーは動かしていない。BV に付点 8 分のエコー

測定の結果（`direction check`、床と比較）: 指揮書の主張 23 本のうち、主たる主張 3 本（percussion の左右の跳び 2 本、fx の部屋への送り 1 本）を含む 22 本が自動チェックで成立した。残る 1 本（主役帯域 300–5000 Hz のモノ損失）は、チェック側が帯域指定を無視する不具合のため未評価（別計算では床 0.1390 dB → 0.1388 dB で悪化なし）。安全弁の不成立はない。ただし全体の被り（masking）は許容 0.5 dB の内側で 0.45 dB 増えている。翻訳ゲート（OF-5）はステムが必要な 2 項目が未評価で incomplete。これらは測定できる量（像の左右比、センド量、被り、モノ互換）についての事実で、動きの心地よさなど聴感の評価は含まない。人の耳による確認は未実施。

### 各種別

強度 0.5、ジャンル `hiphop`、リファレンスなし。各種別は独立したプロジェクトで `run` した結果（指揮書なし）。

| # | 目的関数 × 媒体 | 結果 | LUFS-I／True Peak | 試聴 |
|---|---|---|---|---|
| 1 | 聞き心地 × ストリーミング共通（主サンプルの床） | 検証合格 | −14.01／−1.01 dBTP | [v01_comfort__streaming_universal.mp3](samples/public/audio/v01_comfort__streaming_universal.mp3)<br>レベルマッチ版: [v01_level_matched.mp3](samples/public/audio/v01_level_matched.mp3) |
| 2 | 重低音強化 × ストリーミング共通 | 検証合格 | −14.01／−1.01 dBTP | [v02_bass_heavy__streaming_universal.mp3](samples/public/audio/v02_bass_heavy__streaming_universal.mp3) |
| 3 | ボーカル前面 × ストリーミング共通 | 検証合格 | −14.01／−1.01 dBTP | [v03_vocal_forward__streaming_universal.mp3](samples/public/audio/v03_vocal_forward__streaming_universal.mp3) |
| 4 | 明瞭さ × ストリーミング共通 | 検証合格 | −13.97／−1.01 dBTP | [v04_clarity__streaming_universal.mp3](samples/public/audio/v04_clarity__streaming_universal.mp3) |
| 5 | 疲れにくさ × ストリーミング共通 | 検証合格 | −14.00／−1.01 dBTP | [v05_low_fatigue__streaming_universal.mp3](samples/public/audio/v05_low_fatigue__streaming_universal.mp3) |
| 6 | 聞き心地 × Apple Music | 検証合格 | −16.00／−2.01 dBTP | [v06_comfort__apple_music.mp3](samples/public/audio/v06_comfort__apple_music.mp3) |
| 7 | 聞き心地 × SNS（熱いバリアント） | 検証合格 | −9.97／−1.01 dBTP | [v07_comfort__sns_hot.mp3](samples/public/audio/v07_comfort__sns_hot.mp3) |
| 8 | 聞き心地 × CD（Red Book） | 検証合格 | −10.20／−0.48 dBTP | [v08_comfort__cd.mp3](samples/public/audio/v08_comfort__cd.mp3) |
| 9 | 聞き心地 × クラブ／DJ | 未完成: マスター段で停止（S-08 ノイズ戻り監視の差し戻し。許容幅は緩めていない） | — | なし |
| 10 | クラブ・インパクト × クラブ／DJ | 未完成: 同上 | — | なし |
| 11 | 重低音強化 × クラブ／DJ | 未完成: 同上 | — | なし |

LUFS-I／True Peak はマスター（ロスレス）の実測。翻訳ゲート（OF-5）は 8 種とも incomplete（マスター段にステムを渡さないため 2 項目が未評価）。#1 のマスターを他の配信先の基準で検証した結果は、Spotify・YouTube・TIDAL・SNS（安全既定）が合格、Amazon Music が不合格（S-01、True Peak）。種別の定義は [samples/sample_set.json](samples/sample_set.json)、方針は [docs/SPEC.md](docs/SPEC.md) の §15。Pages デモでは主サンプルを処理前→床（#1 指揮なし）→指揮版の 3 段で切り替えて聴ける。#2〜#8 も測定値・レベルマッチ付きで試聴でき、#9〜#11 は未完成（音声なし、S-08）と表示される。

## ドキュメント

- [docs/SPEC.md](docs/SPEC.md) — 全体仕様
- [docs/DESIGN_PHILOSOPHY.md](docs/DESIGN_PHILOSOPHY.md) — 設計思想（規則でもゲートでもない、指揮者が読む文脈）
- [docs/DIRECTION_FORMAT.md](docs/DIRECTION_FORMAT.md) — 指揮書の形式と `direction` コマンド
- [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md) — 調査プロトコル（調査ファーストの既定）
- [docs/REQUIREMENTS_NOTES.md](docs/REQUIREMENTS_NOTES.md) — 決定事項の記録
- [UPSTREAM_REPORT.md](UPSTREAM_REPORT.md) — 上流設計の作業報告
- [cli/README.md](cli/README.md) / [mcp/README.md](mcp/README.md) / [gui/README.md](gui/README.md) — 各インターフェース

## リポジトリ構成

| ディレクトリ | 内容 |
|---|---|
| `docs/` | 仕様と決定記録 |
| `core/` | ヘッドレスコア |
| `dsp/` | DSP エンジン |
| `director/` | 指揮レイヤー（コアの外側で指揮書を適用・検証する） |
| `cli/` / `mcp/` | CLI と MCP サーバー |
| `gui/` | Web GUI と GitHub Pages デモ |
| `schemas/` | JSON Schema |
| `objectives/` | 目的関数の定義 |
| `profiles/` | 媒体プロファイルと納品形式の定義 |
| `registry/` | モデルレジストリ（ウェイト本体は含まない） |
| `knowledge/` | 判断規則、ジャンル prior、知覚語彙 |
| `kb/` | 既定の知見カード（Markdown）。案件の蓄積は `_private/kb/`（非公開） |
| `samples/` | 公開サンプルの置き場 |
| `licenses/` | 依存ライセンスの本文 |
| `tests/` / `tools/` / `third_party/` | テスト、開発用スクリプト、第三者コード |

## ライセンス

[Apache License 2.0](LICENSE)

- GPL / AGPL のコードは含めない
- FFmpeg は同梱せず、外部プロセスとして利用する
- ステム分離などのモデルウェイトは同梱しない。利用時に公式配布元から取得する方式とし、公式カタログにはライセンスを確認できたものだけを載せる
