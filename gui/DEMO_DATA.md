# Pages デモのデータ配置（`public/demo/`）

GitHub Pages デモ（SPEC §11.4）の `MockBackend`（`src/backend/MockBackend.ts`）が読む、事前計算データの配置。

**本番のデータは、本体のコアで生成するビルド手順（Python）が書き出す。手書きしない。** 今リポジトリにある `public/demo/` は、GUI の開発とテストのための**合成のプレースホルダー**（`scripts/make-placeholder-demo.mjs` が生成。全ファイルに `"synthetic": true`、音声なし）であり、実際の処理結果ではない。GUI は `synthetic` のデータに注意書きを表示する。

The real dataset is written by a Python build step from the core, using exactly this layout, and replaces the placeholder. All paths inside the files are **relative to the demo root**; absolute paths and URLs to other hosts are rejected by the mock (the demo only fetches same-origin static files).

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
│  ├─ before_level_matched.mp3     main pair only
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
      └─ after.mp3                 processed listening copy
```

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

- `match_gain_db` comes from the sample manifest (SPEC 15.3: only the main pair has a level-matched file; the others carry the gain as a number). The player applies it with a Web Audio `GainNode` to `match_target` (the louder side) while level match is on, which is the default.
- Any file may be `null` or missing; the player then shows a message instead of failing.

## Regenerating the placeholder

```
npm run demo:placeholder   # rewrites public/demo/ (synthetic, no audio)
npm run demo:sync-defs     # only re-copies definitions/ from the canonical files
```

`npm test` fails if `definitions/` drifts from the canonical files.
