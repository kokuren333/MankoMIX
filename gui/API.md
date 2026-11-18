# GUI ⇄ local server API (`mankomix serve`)

GUI とローカルサーバーの間の契約。サーバー（Python）はこの一覧を実装する。GUI 側の実装は `src/backend/LocalBackend.ts`、型は `src/types.ts`。

Contract between the GUI (`src/backend/LocalBackend.ts`) and the local server started by `mankomix serve`. Each endpoint wraps one core API function (`core/api.py`); the GUI holds no processing logic (SPEC 11.1).

## Conventions

- All endpoints live under `/api`, same origin as the GUI static files. The server serves `gui/dist/` at `/` and the API at `/api`. In development, `npm run dev` proxies `/api` to `MANKOMIX_API` (default `http://127.0.0.1:8765`).
- Bind to `127.0.0.1` by default. The GUI never talks to any other host (CSP `connect-src 'self'`).
- JSON in, JSON out (`Content-Type: application/json`), except `POST /api/import` (multipart) and `GET /api/events` (SSE) and audio files.
- Writes coming from the GUI are journaled with `actor: "human"`. Agents use CLI/MCP and are journaled as `"agent"`; the deterministic planner as `"planner"`.
- No absolute paths in any response (core `_face_safe` scrubbing). Paths are project-relative; audio URLs are server paths under `/api/files/...`.
- `variant` is a project variant id (`project.variants[].id`).
- Errors: non-2xx status with the same error object as the CLI and MCP (`MankoError.to_dict()`): `{"error": "<core error code>", "message": "...", "details": {...}}` (`LocalBackend` also accepts the nested form `{"error": {"code", "message", "details"}}`). Status mapping: input / validation error → 400, workspace escape or foreign Host/Origin → 403 (`path_outside_workspace` / `forbidden`), not found / not generated / unknown job → 404 (`not_found` / `not_generated` / `unknown_job`), a job already running on the project → 409 (`project_busy`), environment error → 503, unexpected → 500.
- The server (`core/server/`, `mankomix serve`) binds to 127.0.0.1 by default and refuses a non-loopback address without `--allow-remote`; requests with a non-loopback `Host` header and cross-origin writes are refused. Every path stays inside the `--root` workspace; `/api/files/...` serves files inside the open project only.
- Long operations (render, export, analysis, separation, model pull) return a `Job` immediately and report progress via `GET /api/jobs/{id}` and `job` events.

## Endpoints

| Method | Path | Body / query | Response | Core API |
|---|---|---|---|---|
| GET | `/api/capabilities` | — | `Capabilities` (all booleans; missing keys default to `true`) | — |
| GET | `/api/project` | — | `Project` (project.json, schema `schemas/project.schema.json`) | `project_get` / `status` |
| PATCH | `/api/project` | `{ "ops": PatchOp[], "reason"?: string }` (RFC 6902) | `{ "applied": n, "content_hash": "..." }` | `patch` |
| POST | `/api/import` | multipart, field `files` (one or more audio files) | `Job` or `{ "applied": n, "content_hash" }` | `import_files` |
| GET | `/api/history` | `?limit=50` | `{ "entries": HistoryEntry[] }` newest first (`summary` = the journal reason) | `history` |
| POST | `/api/history/undo` | `{}` | `{ "undone": ..., "content_hash" }` | `undo` |
| GET | `/api/objectives` | — | `objectives/catalog.json` shape (`{ default, objectives[] }`) or an array | `objective_list` |
| GET | `/api/profiles` | — | `{ profiles: MediaProfile[] }` or an array | `profile_list` |
| GET | `/api/deliveries` | — | `{ formats: DeliveryFormat[] }` or an array | delivery list |
| GET | `/api/models` | — | `{ models[], defaults, ... }`, entries with `installed`, `license`, `state` | `model_list` |
| GET | `/api/models/{id}` | — | model detail (license evidence, files) | `model_show` |
| POST | `/api/models/{id}/pull` | `{ "allow_candidate"?, "force"? }` | `Job` | `model_pull` |
| GET | `/api/variants` | — | `VariantSummary[]` (+ `rendered`, `has_master_chain`) | `variant_list` |
| GET | `/api/analysis` | `?variant=` | `Analysis` (404 `not_generated` before `analyze`) | `analysis_view` |
| POST | `/api/analyze` | `{}` | `Job` | `analyze` |
| GET | `/api/proposals` | `?variant=&stage=&status=` | `{ proposals: Proposal[] }` (planner and agent proposals, any status, newest first) | `proposal_list` |
| GET | `/api/proposals/{id}` | — | `{ view: Proposal, proposal }` | `proposal_get` |
| POST | `/api/plan/propose` | `{ "stage": "cleanup"\|"mix"\|"master", "variant", "profile"?, "max_iter"?, "async"? }` | `Proposal` (runs as a job and waits; `async: true` returns the `Job`) | `plan_propose` + `proposal_get` |
| POST | `/api/plan/apply` | `{ "proposal_id", "edits": { "<processor id>": { "<param>": value } } }` | `{ "applied", "content_hash", ... }` | `plan_apply` (`edits`) |
| POST | `/api/plan/reject` | `{ "proposal_id", "reason" }` | rejection record (journaled) | `plan_reject` |
| POST | `/api/render` | `{ "variant", "range": { "start_s", "end_s" } \| null }` | `Job` (`range` is not supported by the core yet: the whole variant is rendered) | `render` |
| POST | `/api/export` | `{ "variant" }` | `Job` | `export` |
| GET | `/api/jobs` / `/api/jobs/{id}` | — | `{ jobs: Job[] }` / `Job` | — |
| GET | `/api/verify` | `?variant=` | `Verification` (last result; 404 `not_generated` before the first run; `stale` when the project changed) | `verification_get` |
| POST | `/api/verify` | `{ "variant", "recheck_codecs"? }` | `Job` (result: `Verification`) | `verify` + `verification_get` |
| GET | `/api/report` | `?variant=&lang=ja\|en` | `Report` (schema `schemas/report.schema.json`) | `report` (not written) |
| GET | `/api/audio` | `?variant=` | `AudioSet` (+ `before_kind`, `deltas`); file entries are `/api/files/...` URLs | `audio_set` |
| GET | `/api/files/...` | — | project files (audio, deltas, reports) with `Accept-Ranges: bytes`, `Range` → 206 / 416 | — |
| POST | `/api/import` | multipart `files` | `{ "applied", "content_hash", "assets", "check_counts" }`; several files are imported as one folder (export sets) | `import_files` |
| POST | `/api/separate` | `{ "model"?, "source"?, "mode"?, "stems"?, "device"?, "excerpt_s"?, ... }` | `Job` | `separate` |
| GET | `/api/separations` | — | `{ separations[] }` | `separation_list` |
| GET | `/api/status` | — | project summary | `status` |
| GET | `/api/events` | — | Server-Sent Events stream (below) | — |

## Server-Sent Events (`GET /api/events`)

`text/event-stream`. Event names and `data` payloads (JSON):

| event | data | When |
|---|---|---|
| `project_changed` | `{ "seq": 12, "actor": "agent", "op": "set", "content_hash": "...", "summary": "..." }` | project.json or journal.jsonl changed on disk (GUI, CLI, MCP; polled about once a second). The GUI reloads the visible screen and shows who changed it. |
| `proposal` | `{ "proposal_id": "...", "author": "agent", "stage": "mix", "status": "pending", "variant": "..." }` | A new or updated proposal file under `cache/proposals/` (e.g. an agent proposal awaiting approval). |
| `job` | `{ "job": Job }` | Job progress / completion. |

Send a comment line (`: ping`) every ~15 s to keep the connection alive. If `EventSource` is unavailable the GUI falls back to polling `GET /api/history?limit=1`.

## Payload types

Defined in `src/types.ts`. The ones not covered by a JSON Schema in `schemas/`:

- `Capabilities`: `{ mode: "local", editProject, importAudio, runAnalysis, runPlanner, applyPlan, render, runVerify, undo, agentLink, liveUpdates, modelDownload }`.
- `VariantSummary`: `{ id, label?, objectives: string[] (blend order, dominant first), objective?: ObjectiveSpec, profile, deliveries: string[], intensity?, available: bool }`.
- `HistoryEntry`: `{ seq, ts (ISO 8601), actor: "human"|"agent"|"planner", op, reason?, summary?: Label, undone?: bool }`.
- `Proposal`: `{ id, stage, variant?, author, status: "pending"|"applied"|"rejected", created_at?, summary?: Label, steps: [{ target: track id | bus id | "master", processor: Processor (project.schema `processor`; `reason` holds rule ids such as "R-07" or "S-01 S-06"), editable?: string[], alternatives?: Label[], note?: Label }], reject_reason? }`.
- `Analysis`: `{ schema_version: 1, variant, loudness: { hop_s, before[], after[], integrated_lufs, true_peak_dbtp, lra_lu }, ltas: { freqs_hz[], before[], after[], reference?: { label, low[], high[] } }, band_correlation: { bands: [{ id, lo_hz, hi_hz, before, after }] }, stems: [{ track, centroid_hz, depth (0..1, 1 = near), level_db, pan }], masking: [{ a, b, band_hz: [lo, hi], amount_db, severity: "info"|"warning"|"critical" }], diagnostics: [{ id, metric, label, value, unit, threshold, status: "ok"|"warning"|"fail"|"not_run", note }], metrics?: [{ id, label, before, after, unit }] }`. Loudness values are short-term LUFS; before/after metrics are level-matched.
- `Verification`: `{ schema_version: 1, variant, overall, constraints: [{ id: "S-nn", status: "pass"|"fail"|"warning"|"not_run", value, limit, note }], gate: { status, checks: [{ id, label, status, note }] }, profiles: [{ profile, delivery, status, lufs_i, true_peak_dbtp, note }], noise_return: { status, delta_db, tolerance_db, note }, codec: [{ codec, status, true_peak_dbtp, ceiling_dbtp, note }] }`. A check that could not run (e.g. encoder unavailable) is `not_run`, never `pass` (SPEC 6.7).
- `AudioSet`: `{ variant, files: { before, after, delta?, before_level_matched?, fullmix_reference? } (URL or null), match_gain_db, match_target: "before"|"after", measurements?: { before: { lufs_i, true_peak_dbtp }, after: {...} }, note? }`. `match_gain_db` (≤ 0) is applied by the player to `match_target`, the louder side (SPEC 15.2: match by lowering the louder one). The GUI never computes loudness itself.
- `Job`: `{ job_id, kind: "render"|"export"|"analyze"|"verify"|"plan"|"separate"|"model_pull", state: "queued"|"running"|"done"|"failed", progress?: 0..1, result?, error? (message), error_detail? (error object) }`. One job per project at a time (`project_busy`).
- `Label`: a string or `{ "ja": "...", "en": "..." }`.

## OQ-3 read-only observations

These routes use the open project only. They accept no file paths or project
override. The CLI argument parser, command handler and read-only write guard
(`director.commands.execute`) are shared; no observation algorithm is copied.

| Method | Path | Input | Response / shared CLI function |
|---|---|---|---|
| GET | `/api/direction/pitch/notes` | `target` (required), `section?`, `lo_hz?`, `hi_hz?`, `a4?` | Exact JSON from `director.commands.pitch_notes.run` (`direction pitch notes`) |
| GET | `/api/direction/query/meters` | `target?` (default `master`), `section?`, `what?` (comma-separated), `step_ms?`, `max_points?`, `points?`, `octave?` | Exact JSON from `director.commands.query_meters.run` (`direction query meters`) |
| POST | `/api/direction/spectral-repair/preview` | `{target?, section?, step_ms?, max_points?, params}` | `{type: "spectral_repair", params, observation, read_only: true, apply_via}` |

The spectral preview normalizes and validates `params` with
`dsp.processors.validate_params`, the same function used by CLI rendering's
`dsp.engine.validate_chain`. `observation` is the exact `query meters` output
with `what=spectrogram`. It describes the source, without rendering a repaired
signal. Rectangle arrays are named `t0_s`, `t1_s`, `lo_hz`, `hi_hz` (equal lengths,
at most 64, each duration at most 2 seconds); all processor options retain their
CLI defaults and validation. Application uses the existing CLI direction op and
its journal path. No new route writes project, journal, assets or caches.

GUI routes: `#/notes`, `#/spectral`, `#/meters`. The first shows median note
bands/lines and exact numeric rows; keeping an observation permits comparison
after CLI `edit_pitch` and reload. The second supports dragging a rectangle
snapped to API bin boundaries, numeric edits, multiple rectangles and validated
parameter JSON for a CLI direction op. The third draws API spectrum,
spectrogram, loudness, peaks and L/R vectorscope points, with a timeline position
selector and exact numeric JSON. Plot geometry and color scaling are display
transforms only; measured values are never recomputed in the browser. Meters
follow the CLI's first current project variant; the global variant picker does
not override it. No observation data is fabricated in demo mode.
