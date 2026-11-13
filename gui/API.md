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
- Errors: non-2xx status with body `{"error": {"code": "<core error code>", "message": "...", "details": {...}}}`. Suggested status mapping: input error → 400, not found / not generated → 404 (`code: "not_found"` / `"not_generated"`), conflict with a newer canonical (SPEC 9.5) → 409, environment error → 500/503.
- Long operations (render, export, analysis, separation, model pull) return a `Job` immediately and report progress via `GET /api/jobs/{id}` and `job` events.

## Endpoints

| Method | Path | Body / query | Response | Core API |
|---|---|---|---|---|
| GET | `/api/capabilities` | — | `Capabilities` (all booleans; missing keys default to `true`) | — |
| GET | `/api/project` | — | `Project` (project.json, schema `schemas/project.schema.json`) | `project_get` / `status` |
| PATCH | `/api/project` | `{ "ops": PatchOp[], "reason"?: string }` (RFC 6902) | `{ "applied": n, "content_hash": "..." }` | `patch` |
| POST | `/api/import` | multipart, field `files` (one or more audio files) | `Job` or `{ "applied": n, "content_hash" }` | `import_files` |
| GET | `/api/history` | `?limit=50` | `{ "entries": HistoryEntry[] }` newest first | `history` |
| POST | `/api/history/undo` | `{}` | `{ "undone": ..., "content_hash" }` | `undo` |
| GET | `/api/objectives` | — | `objectives/catalog.json` shape (`{ default, objectives[] }`) or an array | `objective_list` |
| GET | `/api/profiles` | — | `{ profiles: MediaProfile[] }` or an array | `profile_list` |
| GET | `/api/deliveries` | — | `{ formats: DeliveryFormat[] }` or an array | delivery list |
| GET | `/api/models` | — | `registry/models.json` shape, entries may add `installed: bool` | `model_list` |
| POST | `/api/models/{id}/pull` | `{}` | `Job` | `model_pull` |
| GET | `/api/variants` | — | `VariantSummary[]` (if 404 the GUI derives it from `project.variants`) | — |
| GET | `/api/analysis` | `?variant=` | `Analysis` | `analyze` (cached result) |
| POST | `/api/analyze` | `{}` | `Job` | `analyze` |
| GET | `/api/proposals` | `?variant=` | `{ proposals: Proposal[] }` (planner and agent proposals, any status) | — |
| POST | `/api/plan/propose` | `{ "stage": "cleanup"\|"mix"\|"master", "variant" }` | `Proposal` | `plan_propose` |
| POST | `/api/plan/apply` | `{ "proposal_id", "edits": { "<processor id>": { "<param>": value } } }` | `{ "applied": n, "content_hash" }` | `plan_apply` |
| POST | `/api/plan/reject` | `{ "proposal_id", "reason" }` | `{}` (journaled) | — |
| POST | `/api/render` | `{ "variant", "range": { "start_s", "end_s" } \| null }` | `Job` | `render_preview` |
| POST | `/api/export` | `{ "variant" }` | `Job` | `export_run` |
| GET | `/api/jobs/{id}` | — | `Job` | — |
| GET | `/api/verify` | `?variant=` | `Verification` (last result) | `verify_run` (cached) |
| POST | `/api/verify` | `{ "variant" }` | `Verification` or `Job` | `verify_run` |
| GET | `/api/report` | `?variant=&lang=ja\|en` | `Report` (schema `schemas/report.schema.json`) | `report_get` |
| GET | `/api/audio` | `?variant=` | `AudioSet` | — |
| GET | `/api/files/...` | — | audio bytes (renders / listening copies), `Accept-Ranges` recommended | — |
| GET | `/api/events` | — | Server-Sent Events stream (below) | — |

## Server-Sent Events (`GET /api/events`)

`text/event-stream`. Event names and `data` payloads (JSON):

| event | data | When |
|---|---|---|
| `project_changed` | `{ "seq": 12, "actor": "agent", "content_hash": "...", "summary": "..." }` | Any journaled change to project.json (GUI, CLI, MCP). The GUI reloads the visible screen and shows who changed it. |
| `proposal` | `{ "proposal_id": "...", "author": "agent", "stage": "mix" }` | A new or updated proposal (e.g. an agent proposal awaiting approval). |
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
- `Job`: `{ job_id, kind: "render"|"export"|"analyze"|"verify", state: "queued"|"running"|"done"|"failed", progress?: 0..1, result?, error? }`.
- `Label`: a string or `{ "ja": "...", "en": "..." }`.
