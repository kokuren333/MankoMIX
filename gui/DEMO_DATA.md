# Pages デモのデータ配置（`public/demo/`）

GitHub Pages デモ（SPEC §11.4）の `MockBackend` が読む事前計算データ。**本番のデータは `tools/build_demo_data.py` が各プロジェクトから `core/api.py` 経由で生成する。手書きしない。**

現データは公式サンプル「マンコ主義」の 11 枠を、複数プロジェクトから `--slot`／`--floor`／`--official-manifest` を指定した厳格モードで生成したもの。確認元は W3 出力の `tmp/demo_data/index.json` と `variants/*/audio.json`。同じ内容をビルダーの `--out` で `gui/public/demo/` に出力する。

主サンプル v01 は、指揮書 `dir_cf3e85c484fa`（pattern: `sample_main`）「空間音響 × 複雑で心地の良いパンニング」を、#1 comfort × streaming_universal の既定処理〔床〕に重ねたもの。Listen では **処理前 → 床（#1 指揮なし） → 指揮版** の 3 段を再生位置を保って切り替えられ、除去分も聴ける。#2〜#8 も測定値・レベルマッチ付きで試聴できる。#9〜#11 はマスター段の S-08（ノイズ戻り監視）で未完成・音声なし。ミックス段へ差し戻されており、許容幅は緩めていない。

All paths in JSON are **relative to the demo root** (index.json's folder). MockBackend rejects absolute paths and other-host URLs and only fetches same-origin static files. Payload types are in `gui/API.md` and `src/types.ts`; the index type is `DemoVariant` in `src/backend/MockBackend.ts`.

## Layout

```text
public/demo/
├─ index.json
├─ project.json                    main sample Project (schemas/project.schema.json)
├─ history.json                    { "entries": HistoryEntry[] }
├─ definitions/                    copied verbatim from canonical data
│  ├─ objectives.json              ← objectives/catalog.json
│  ├─ media_profiles.json          ← profiles/media_profiles.json
│  ├─ delivery_formats.json        ← profiles/delivery_formats.json
│  └─ models.json                  ← registry/models.json
├─ audio/                          MP3 320 kbps listening copies, not masters
│  ├─ before.mp3                   unity-gain stem sum (SPEC §15.2)
│  ├─ fullmix_reference.mp3         reference only, never the before baseline
│  └─ delta.mp3                    removed by cleanup (main sample)
└─ variants/
   ├─ v01/
   │  ├─ analysis.json
   │  ├─ plan.json                 { "proposals": Proposal[] }
   │  ├─ verify.json
   │  ├─ report.ja.json            Report (schemas/report.schema.json)
   │  ├─ report.en.json            Report (fallback: report.json)
   │  ├─ audio.json                AudioSet
   │  ├─ after.mp3                 directed main sample
   │  ├─ after_level_matched.mp3   main pair only
   │  └─ floor.mp3                 #1 without direction
   └─ v02/ … v08/                  each contains the following
      ├─ project.json             this slot's project
      ├─ history.json             this slot's history
      ├─ analysis.json
      ├─ plan.json
      ├─ verify.json
      ├─ report.ja.json
      ├─ report.en.json
      ├─ audio.json
      └─ after.mp3
```

現データの MP3 は **13 本**（共通 3 本、v01 の 3 本、v02〜v08 の各 1 本）。`variants/v09`〜`v11` はフォルダ自体がなく、音声・測定値・分析・レポートも置かない。床および #2〜#8 のレベルマッチ版ファイルは置かない。`fullmix_reference` はプレイヤーには出さない。v01 の Verify／Report は指揮版のもので、床のレポートは `samples/public/reports/v01/` を参照する。

Audio exists only with `--mp3`; JSON-only builds use null file entries. In the legacy path a different Before may be written as `audio/before_vNN.mp3`, and a main pair lowering Before uses `audio/before_level_matched.mp3`. With `--slot`, rendered slots must have identical Before source contents (sha256), regardless of project-relative path strings; a mismatch fails.

## `index.json`

- `schema_version: 1`, `synthetic: false`, `generator: {name, version, note}`, `title` / `notice` (ja/en labels), and `definitions` pointing to the four files above.
- Top-level `project` / `history` point to the main sample's project.json / history.json. Top-level `source: {project_id, content_hash, sample_set}` identifies the default project; content_hash is the journal head. Current sample_set is `samples/sample_set.json`.
- `variants` lists the 11 kinds in sample_set order, with ids v01 through v11. Entries contain `n`, `objective`, `profile`, `role`, `deliveries`, `intensity`, `label: {ja,en}`, `project_variant`, `available`, and `dir`.
- v01 has `floor: {objective, profile, project_id}`: comfort / streaming_universal / prj_sample_v01.
- A `--slot N=<project>` entry has `source: {project_id, content_hash}` whether available or unavailable. Available assigned slots also have `project: "variants/vNN/project.json"` / `history: "variants/vNN/history.json"` and those files. For the selected variant the GUI uses these in Project / Stems / MixMap / Intent / History; otherwise it falls back to the top-level paths.
- Unavailable entries have `unavailable_reason`: `not_in_project` (no matching single-objective variant), `not_rendered`, or `incomplete` with `missing: ["analysis" | "verification" | "audio" | "report"]`. No folder is created for unavailable slots.
- Strict mode copies sample_set `published.stopped` into `stopped: {at, rule}`. Current v09–v11 have `available: false`, `unavailable_reason: "not_rendered"`, and `stopped: {"at": "master", "rule": "S-08"}`. The picker displays 「未完成・音声なし（S-08）」; a shared banner and Analysis / Plan / Listen / Verify / Report show the reason, with no playback controls or measurements. Entries without stopped retain the ordinary not-generated display.
- Directed entries have `direction: {id, pattern, request, title}` from direction frontmatter, without its body. Their label leads with the direction and presents objective × profile as the floor.
- `audio: {included, format, listening_copies, masters, encoder, files[]}` inventories listening copies. MP3 builds have format mp3, masters false, and encoder metadata: ffmpeg version / build / license / codec libmp3lame / bitrate_kbps 320 / mode CBR / options. JSON-only has included false, format and encoder null, and files empty.
- `verification_only_profiles` lists profiles used only for verification. Switching variants selects precomputed results.

## `audio.json`

- `variant` is the demo id; `project_variant` is the source project variant id. `files` contains before / after / delta / before_level_matched / after_level_matched / fullmix_reference / floor as relative paths or null; optional entries may be absent.
- `measurements.before` / `measurements.after` are `{lufs_i, true_peak_dbtp}`. A floor slot also has `files.floor` and `measurements.floor`.
- `floor` contains `{project_variant, project_id, content_hash, objective, profile, measurements, match_gain_db, match_target, source_files}`. Its measurements equal `measurements.floor`. Its match_target is `"before"` or `"floor"` (renaming the core pair's `"after"`).
- `match_gain_db` (≤ 0) / `match_target` describe the before/after pair: lower the louder side. Normally these come from core `audio_set`.
- **厳格モードでは測定値とゲインは試聴元マスター基準、core の値は `core_audio_set`**。v01 の床と v02〜v08 の after は manifest の `listening_copy.of_master` を `api.measure_audio()` で測り、`build_samples.py` の `level_match()` と同じ規則で算出する。`after_master`（床は `floor.after_master`）に納品マスター種別、`core_audio_set: {gain_db, target, measurements}`（床は `floor.core_audio_set`）に core の元の対を併記する。主サンプル v01 after は archive_f32 から作り、最上位の値は従来どおり core `audio_set` 由来で、この併記欄はない。
- v08 は `after_master: "cd_redbook"`、after の測定値 −10.20 LUFS-I／−0.48 dBTP、ゲイン −4.83 dB（after）。`core_audio_set` は archive_f32 基準の −10.00／−0.31、−5.03 dB。v01〜v07 の対ではゲインが同値であり、「全 8 種で core と一致」ではない。
- Floor slots have `level_match_gains_db: {before, floor, after}`. Let d_before = 0; for each pair, d_s = −gain if its target is that source, or +gain if its target is before. Each output gain is `round(min(0, d_floor, d_after) − d_i, 2)`, aligning to the quietest source. Inputs are the directed core pair and floor listening-master pair. Current values are `{before: 0.0, floor: -1.02, after: -1.02}`; floor measurements are −14.01 LUFS-I / −1.01 dBTP.
- The GUI does not calculate loudness or matching gains. Level match defaults on and applies the supplied table with GainNode; slots without a floor use match_gain_db / match_target (v06: −0.97 dB on before; v07: −5.06 dB on after). Off plays at actual output level. Sources run synchronously to preserve position when switching. The player never loads level-matched files.
- Slots without a floor omit floor / files.floor / measurements.floor / level_match_gains_db.
- The builder also records `before_kind` (stem_sum or fullmix), `note`, `listening_copies`, and `source_files` (project-relative master/source names).
- Other files are core payloads: analysis_view, proposal_list (variant proposals plus project-wide cleanup/mix, ordered cleanup → mix → master), verification_get, and report(lang, write=False).

## Build options and failures

```text
python -I tools/build_demo_data.py --project <song.mmx> [--out tmp/demo_data] [--variants-from samples/sample_set.json | --project-variants] [--slot N=<project> ...] [--floor N=<project> ...] [--official-manifest <manifest.json>] [--mp3] [--ffmpeg <ffmpeg>]
```

- Inputs must already have analysis, rendered and verified results. The builder reads results; it does not run or render again. Core may write derived view caches under cache/listen/. Delta requires a previously rendered cleanup delta.
- `--variants-from` supplies slot definitions (default: samples/sample_set.json). `--project-variants` lists a project's own variants for general use; it is not how the current dataset was built.
- Repeatable `--slot N=<project>` overrides only that slot; unspecified slots match against `--project`. The assigned project must have exactly one variant matching objective × profile × intensity, or the build fails.
- `--floor N=<project>` requires an available directed slot, and a uniquely matching, undirected, rendered and verified floor with a readable master. Its Before source sha256 must equal the directed slot's. Missing requirements fail the build.
- Both assignment options reject malformed N=<project>, duplicate numbers, nonexistent slots, and inputs without project.json.
- `--official-manifest` enables strict official-sample checks and requires sample_set published metadata. A verified slot being unavailable, or a stopped slot being available or missing, fails. Encoding-source master sha256 and measured LUFS-I / TP, listening-master gain/target and core gain/target must match the manifest exactly at its rounding precision. Remeasured Before differing from core also fails. A listening/core pair difference outside v08 fails and requires PM review.
- `--mp3` encodes with external ffmpeg (libmp3lame, 320 kbps CBR, no tags, bit-exact). Strict mode checks every generated MP3 sha256 against the manifest; any mismatch fails. JSON-only skips MP3 checks and reports that explicitly. Audio is never copied from samples/public to make it match.
- Without the new options the legacy path preserves its previous output. Default output is gitignored tmp/demo_data. An existing output must be empty or contain a previous dataset; only the builder's own entries are replaced.
- Sorted JSON keys and stable names make output deterministic for identical inputs and encoder. All input projects are included in leak checks; absolute paths, local folder names and email addresses cause refusal. External project asset paths become linked/<name>.
- Listening-copy publication was approved under D-061. MP3 under public/demo/ and samples/public/audio/ is committed; other audio stays gitignored. Audio is regenerated, never hand-edited. Official sample publication changes only at release milestones (SPEC §15.3).

## 現データの再生成

リポジトリルートで実行する Windows cmd 用コマンド。`<work>` は既存の読み取り用プロジェクト群、`<ffmpeg>` は manifest と同じ版（現データは 9.0.2-essentials_build-www.gyan.dev）の実行ファイルに置き換える。重い実データ生成は統括が行う。

```bat
python -X utf8 -I tools/build_demo_data.py --project "<work>\main.mmx" --variants-from samples/sample_set.json ^
  --slot "2=<work>\sample_build\v02\song.mmx" --slot "3=<work>\sample_build\v03\song.mmx" ^
  --slot "4=<work>\sample_build\v04\song.mmx" --slot "5=<work>\sample_build\v05\song.mmx" ^
  --slot "6=<work>\sample_build\v06\song.mmx" --slot "7=<work>\sample_build\v07\song.mmx" ^
  --slot "8=<work>\sample_build\v08\song.mmx" --slot "9=<work>\sample_build\v09\song.mmx" ^
  --slot "10=<work>\sample_build\v10\song.mmx" --slot "11=<work>\sample_build\v11\song.mmx" ^
  --floor "1=<work>\sample_build\v01\song.mmx" --official-manifest samples/public/manifest.json ^
  --mp3 --ffmpeg "<ffmpeg>" --out tmp/demo_data
```

公開用への差し替えも同じコマンドの出力先を `--out gui/public/demo` にしてビルダーで行う。生成物は手で混ぜない。GUI の実データ検査は gui ディレクトリで `MANKOMIX_DEMO_DIR=../tmp/demo_data npm test`（PowerShell では `$env:MANKOMIX_DEMO_DIR='../tmp/demo_data'; npm test`）。`src/test/demo-dataset.test.tsx` が全ファイルを MockBackend 経由で読み、各画面を描画する。環境変数なしではこのスイートはスキップされる。

## 開発用プレースホルダー

`scripts/make-placeholder-demo.mjs` の合成データは全ファイルに `synthetic: true` が付き、音声なし。GUI は注意書きを表示する。

```text
npm run demo:placeholder   # public/demo/ を合成データで上書きする開発用コマンド
npm run demo:sync-defs     # definitions/ だけを正本から複製
```

`npm test` は definitions/ が正本と食い違うと失敗する。
