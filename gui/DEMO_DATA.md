# Pages デモのデータ配置（`public/demo/`）

GitHub Pages デモ（SPEC §11.4）の `MockBackend`（`src/backend/MockBackend.ts`）が読む、事前計算データの配置。

**本番のデータは、本体のコアで生成するビルド手順（`tools/build_demo_data.py`）が書き出す。手書きしない。** 現在リポジトリにコミットされている `public/demo/` は、指揮書実例 p3「空間音響と複雑なパンニング」（楽曲「マンコ主義」）を `tools/build_demo_data.py --project-variants --mp3` でビルドした実データである（単一バリアント v01 = プロジェクトの `var_streaming_universal`、試聴用 MP3 付き。2026-11-14 にオーナーが D-061 を承認して差し替えた）。GUI 開発用の**合成のプレースホルダー**（`scripts/make-placeholder-demo.mjs` が生成。全ファイルに `"synthetic": true`、音声なし）は `npm run demo:placeholder` で再生成できる。GUI は `synthetic` のデータに注意書きを表示する。

The real dataset is written by `tools/build_demo_data.py` from a project, only through `core/api.py` (the same calls the local server makes), using exactly this layout; it replaces the placeholder. All paths inside the files are **relative to the demo root**; absolute paths and URLs to other hosts are rejected by the mock (the demo only fetches same-origin static files).

## Layout

```
public/demo/
├─ index.json                      entry point (below)
├─ project.json                    project.json of the sample (schemas/project.schema.json)
├─ history.json                    { "entries": HistoryEntry[] } — optional
├─ definitions/                    copied verbatim from the canonical data files
│  ├─ objectives.json              ← objectives/catalog.json
│  ├─ media_profiles.json          ← profiles/media_profiles.json
│  ├─ delivery_formats.json        ← profiles/delivery_formats.json
│  └─ models.json                  ← registry/models.json
├─ audio/                          shared listening copies (MP3 320 kbps, not masters)
│  ├─ before.mp3                   unity-gain stem sum (SPEC 15.2)
│  ├─ before_level_matched.mp3     main pair only, when Before is the louder side
│  ├─ fullmix_reference.mp3        reference only, never the "before" baseline
│  └─ delta.mp3                    removed by cleanup (main sample)
└─ variants/
   └─ v01/ … v11/                  one folder per sample variant (samples/sample_set.json)
      ├─ analysis.json             Analysis
      ├─ plan.json                 { "proposals": Proposal[] }
      ├─ verify.json               Verification
      ├─ report.ja.json            Report (schemas/report.schema.json), language "ja"
      ├─ report.en.json            Report, language "en" (fallback: report.json)
      ├─ audio.json                AudioSet (URLs relative to the demo root)
      ├─ after.mp3                 processed listening copy (of the rendered master)
      └─ after_level_matched.mp3   main pair only, when After is the louder side
```

Audio files exist only when the dataset was built with `--mp3`. A second, different Before (a variant on another route) is written as `audio/before_vNN.mp3`.

Payload types are defined in `gui/API.md` (same as the local server responses) and `src/types.ts`.

## `index.json`

```json
{
  "schema_version": 1,
  "synthetic": false,
  "generator": { "name": "<build step>", "version": "<engine version>" },
  "title": { "ja": "…", "en": "…" },
  "project": "project.json",
  "history": "history.json",
  "definitions": {
    "objectives": "definitions/objectives.json",
    "profiles": "definitions/media_profiles.json",
    "deliveries": "definitions/delivery_formats.json",
    "models": "definitions/models.json"
  },
  "intensity": 0.5,
  "variants": [
    { "id": "v01", "n": 1, "objective": "comfort", "profile": "streaming_universal", "role": "main",
      "deliveries": ["hires_native", "distributor_44k16"], "intensity": 0.5, "available": true, "dir": "variants/v01/" }
  ],
  "verification_only_profiles": ["spotify", "youtube", "amazon_music", "tidal", "sns_safe"]
}
```

- `variants` lists the 11 kinds of `samples/sample_set.json` in order (a test checks this). `available: false` marks a variant whose files have not been generated; the GUI shows "not generated" instead of failing.
- The builder adds per variant: `label` (`{ja, en}`, from the objective catalogue and the media profiles), `project_variant` (the project variant id, or `null`) and, when unavailable, `unavailable_reason`: `not_in_project` (no single-objective variant with that objective, profile and intensity), `not_rendered`, or `incomplete` with `missing: ["analysis" | "verification" | "audio" | "report"]`. Nothing is filled in for a missing variant.
- When a variant's proposals carry director-layer moves (`move_ref` on a step), the builder also adds `direction`: `{id, pattern, request, title}` read from the frontmatter of the direction document stored inside the project (`<project>/directions/<id>.md`). The variant's `label` then becomes direction-first (指揮書 … × profile（土台: objective）), and the GUI heads the variant picker and a banner with the direction — the objective × profile is the floor the direction was applied on top of, never the headline.
- It also adds `source` (`project_id`, `content_hash` = the journal head, `sample_set`) and `audio`: `{ included, format: "mp3", listening_copies: true, masters: false, encoder: { tool: "ffmpeg", version, build, license, codec: "libmp3lame", bitrate_kbps: 320, mode: "CBR", options }, files[] }` (`included: false`, `encoder: null` for a JSON-only build).
- The objective × profile switch in the demo is the selection of one of these precomputed variants.

## `audio.json`

```json
{
  "variant": "v01",
  "files": {
    "before": "audio/before.mp3",
    "after": "variants/v01/after.mp3",
    "delta": "audio/delta.mp3",
    "before_level_matched": "audio/before_level_matched.mp3",
    "fullmix_reference": "audio/fullmix_reference.mp3"
  },
  "match_gain_db": -2.5,
  "match_target": "before",
  "measurements": { "before": { "lufs_i": -11.5, "true_peak_dbtp": 0.8 }, "after": { "lufs_i": -14.0, "true_peak_dbtp": -1.2 } }
}
```

- `match_gain_db` and `match_target` come from the core's level-matched comparison (`audio_set`: equal integrated loudness by lowering the louder side, so `match_gain_db` ≤ 0). SPEC 15.3: only the main pair has a level-matched file (`before_level_matched`, or `after_level_matched` when After is louder); the others carry the gain as a number. The player applies it with a Web Audio `GainNode` to `match_target` while level match is on, which is the default.
- The builder also writes `project_variant`, `before_kind` (`stem_sum` or `fullmix`), `note`, `listening_copies` and `source_files` (project-relative names of the masters the copies were made from).
- The other per-variant files are the core payloads unchanged: `analysis_view`, `proposal_list` (the variant's proposals plus the project-wide cleanup / mix proposals, ordered cleanup → mix → master), `verification_get`, `report(lang, write=False)`.
- Any file may be `null` or missing; the player then shows a message instead of failing.

## Building the dataset from a project

```
python -I tools/build_demo_data.py --project <song.mmx> [--out tmp/demo_data] [--variants-from samples/sample_set.json | --project-variants] [--mp3] [--ffmpeg PATH]
```

- The project must be analysed, and each variant rendered and verified (e.g. by `mankomix run`); the builder only reads results (the core's view caches under `cache/listen/` are the only thing written in the project). The delta file needs a cleanup delta rendered beforehand.
- `--mp3` encodes the listening copies with an external ffmpeg (libmp3lame, 320 kbps CBR, no tags, bit-exact) and records the encoder in `index.json`. Without it the dataset is JSON only.
- The default `--out` is `tmp/demo_data/` (gitignored). An existing `--out` must be empty or hold a previous dataset; only the builder's own entries are replaced.
- Output is deterministic: JSON with sorted keys, stable file names; two builds of the same project are byte-identical. The build refuses to write if any file would contain an absolute path, a local folder or an e-mail address; project asset paths outside the project become `linked/<name>`.
- **Audio is not committed** (D-061): MP3 files under `public/demo/` stay uncommitted (`*.mp3` is gitignored) until the owner approves the M9 public audit; until then only the JSON may replace the placeholder. Audio is regenerated with the command above at any time. **Exception (owner approval, 2026-11-14):** the listening copies of the p3 direction example — the dataset committed at that date — are committed (force-added past the `*.mp3` gitignore rule). Any other audio still needs its own approval, and further replacements happen only at release milestones (SPEC 15.3).
- Check a generated dataset with the GUI tests: `MANKOMIX_DEMO_DIR=<dataset folder> npm test` runs `src/test/demo-dataset.test.tsx` (loads every file through `MockBackend` and renders every screen); without the variable that suite is skipped.

## Regenerating the placeholder

```
npm run demo:placeholder   # rewrites public/demo/ (synthetic, no audio)
npm run demo:sync-defs     # only re-copies definitions/ from the canonical files
```

`npm test` fails if `definitions/` drifts from the canonical files.
