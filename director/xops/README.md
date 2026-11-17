# Direction operation extensions

Add one Python module per operation in this package. It must export `OPS`, a
dictionary from a snake_case op name to an `OpSpec` (or a dictionary of its
constructor arguments). Discovery runs in filename order when `direction` is
imported. Names shared by two modules or with **any** built-in `direction.OPS`
key raise `ImportError`. Do not change the built-in table or move existing ops.
Private helper modules start with `_` and are not discovered.

```python
from mankomix.director.xops import OpSpec, MixResult

def validate(move, ctx):
    # Validate raw params, ranges, arrays, target, bounds and unknown keys.
    # ctx.project is direction._Project or None; ctx.block is the direction block.
    if not isinstance(move.get("params"), dict):
        ctx.err("bad_value", "params must be an object")

def expand(project, move):
    # Pure planning: project.root, .data, .rate, .tracks(), .buses(), .sections().
    # Read the source, calculate the curve and measurements without writing.
    return MixResult(
        record={"measurements": {}, "reason": "describe the measured basis"},
        points=[[0, 0.0], [48000, -1.0], [96000, 0.0]],
        chain=[],
        notes=[])

OPS = {"example": OpSpec(
    stage="mix", required=("target", "params"), validate=validate,
    expand=expand, time_varying=True, section=False)}
```

This example documents the contract; no production example op is registered.
Every move still needs its id, aim, basis and origin. Existing document checks,
quantity references, master restrictions and forbidden keys run before/alongside
the callback. `ctx.err(code, message)` adds an error at that move. Callbacks must
handle malformed input without raising. Access project context only when non-null.
`section=True` opts a mix op into existing section syntax checks; edit ops permit
sections by default. The callback must implement its actual section semantics.

`MixResult.record` is a JSON dictionary for op-specific settings, lists and
before/after measurements. `points` is a list of `[project_sample, dB]` pairs,
with finite non-negative ascending sample positions and finite dB values. The op
must impose its specified amount/slope/length limits. Automation targets are
tracks. The registry composes points using `duck.merge_automation` in this order:
floor, section gain, all ducks (including full-band duck_curve), new ops in move
order, gain_curve. Do not overwrite track automation in a callback. Empty points
mean no automation contribution.

`chain` contains declarations `{"type": processor_type, "params": {...}}` for
the move's track or bus target. Processor validation and stage restrictions still
apply. The seam supplies item ids, owner, reason and `move_ref`; an op must not
supply its own chain ids or touch the master. Existing user-owned buses use the
director bus override path. The apply record adds authoritative `op`, `track`
and `trace` fields to the custom record. `check` requires all emitted items and
automation to retain the move's reference. No-output moves are traced by their
record. Declare dependencies (including random seeds), measurements and caveats
explicitly; do not invent gates or check whether someone used a suggestion.

## Optional mix resources (W4_1)

The original `MixResult(record, points=[], chain=[], notes=[])` and every
`OpSpec` declaration remain valid. Additional optional fields are `nodes=None`
and `controls=[]`. Expand/build stay read-only: calculation is in memory;
only direction.apply registers resources, before applying the mix proposal.
An import, placement or mix-apply failure compensates all resource registration
through a core patch, restores ledgers and removes newly created files.
Journal history retains attempts and compensation. Core is unchanged.

```python
from mankomix.director.xops import AudioPlan, NodePlan, MixResult

result = MixResult(record={"hits": 1}, nodes=NodePlan(
    tracks=[{"name": "reinforcement", "role": "drums", "output": "bus_mix"}],
    assets=[AudioPlan("hit", audio, project.rate,
                      params={"seed": 0, "speed": 1.0, "polarity": 1},
                      code_version="1", sources=source_hash_records)],
    clips=[{"track": "reinforcement", "asset": "hit", "timeline_start": 100,
            "source_start": 0, "length": len(audio), "gain_db": -6}]))
```

Names are local identifiers. The seam supplies stable track/clip IDs, owner
and move_ref. Tracks accept only name/role/output; output is an existing bus
(normally the source track's output). Clips accept track/asset/timeline_start/
length and optional source_start/gain_db/fade_in/fade_out. Integer sample
positions must stay inside source and project bounds. Overlapping hits add.
Audio must be finite float64 (frames,1/2) at project.rate. Core has no clip
speed/polarity processing: bake those into the waveform and record the values
in params. Include every default and seed, plus all `{id, sha256}` dependencies
in sources. Full-timeline DOUBLE carriers avoid short-source ingest exceptions.
Content hashes and recipe keys identify the local cache under cache/derived/.
Existing staged import and validated/journaled core patches register/place
resources. Duplicate audio reuses assets without claiming foreign ownership.

Node ledger rows live under `nodes`; apply records keep IDs, keys and hashes.
Check verifies ownership, routing, clips and registered audio hashes.
`derived.regenerate_node(root, direction, move, name, audio=None)` restores
missing audio from cache. After deleting cache, supply the exact version's
generated waveform: waveform and carrier hashes must both match. Existing
corrupt files are errors, never silently replaced.

### Persistent non-audio control assets

```python
from mankomix.director.xops import ControlPlan

result = MixResult(record={"confidence": "high"}, controls=[
    ControlPlan("env", "trk_modulator", start, end, resolved_params,
                calculate_control, "1")], chain=[
    {"type": "band_envelope", "params": {
        "bands": 16, "envelopes": {"control": "env"}}}])
```

`calculate_control(raw_segment_float64, sample_rate, params)` returns
`{"kind":"control", "values": array, "hop_s": .005, "origin_s": 0,
"centers_hz": centers}`. Values are finite/nonnegative (time,bands) or
(time,bands,1/2); hop_s is positive and origin_s nonnegative. Optional centers
must match the processor layout. Supply absolute origin_s for a section.
Each plan has its own code_version and complete resolved params. The seam
freezes raw clips/source hashes, calculates in memory, replaces explicit
`{"control": local_name}` parameter references with `ctl_<content_sha256>`
and validates against temporary in-memory payloads. Ordinary params are intact.

Apply writes hashed JSON under assets/derived/ and a recipe-keyed local cache.
`controls` ledger rows track sources, op, params, version, key, result hash,
owner and move_ref. Controls are separate from core audio assets.
`derived.install_control_resolver()` connects to band_envelopes' installer
(`asset` registry `derived`), retaining the empty-ID sentinel. Processor
discovery installs a lazy persistent fallback for fresh processes. Each read
verifies the content hash embedded in the ID.

The CLI scopes resolution to --project. Library callers handling project
copies/moves use `with derived.control_context(root): ...` (ContextVar, reset
on exit). Without context, resolution tries the project at cwd, then a user
settings locator saved on apply. This locator holds only the last registered
project location; project files remain authoritative. Chain params/ledgers
contain no absolute project paths. On another machine, select project context
instead of relying on a locator. Build/read-only commands never write locators
or regenerate files.

`derived.regenerate_control(root, direction, move, name, calculate=None)`
repairs missing asset/cache JSON. Cache misses require the exact version's
calculator; recorded raw layout, source hashes, raw hash and result hash must
match before saving. Check also detects missing/corrupt control data.

Direction edit revert removes new node tracks/clips and resource-owned chain
items, and marks node/control rows reverted. Reusable core audio assets remain
unused (as with stem_remove); control/cache files remain. Modified node tracks
are refused. Automation restores its pre-apply value only when every ref in
that composed curve belongs to selected resource moves; other dependencies
are refused before mutation. Revert dependencies first. Repeat revert is inert.

## Derived edits

```python
from mankomix.director.xops import OpSpec, DerivedPlan

def derive(root, move):
    params = move["params"]  # validate and resolve defaults/ranges yourself
    return DerivedPlan(start=0, end=48000, params=params, calculate=calculate,
                       fit="keep_length", timeline_start=None)

def calculate(segment_float64, sample_rate, params):
    return segment_float64.copy()  # replace with the specified processing

OPS = {"edit_example": OpSpec(
    stage="edit", required=("target", "params"), validate=validate,
    derive=derive, code_version="1", time_varying=True)}
```

For a `DerivedPlan`, the seam calls `director.derived.apply` (BB-18), never the calculator directly.
`derive(root, move)` only plans; `calculate` receives a copied raw input segment
(frames, channels), before cleanup/chain/fader, and must return finite audio.
`params` must include every resolved default, source dependency and seed used by
the calculation. Change `code_version` when processing changes. Positions are
integer project-rate samples. `fit` is `keep_length` or `keep_start`; BB-18 keeps
the project timeline fixed, refuses unrelated overlaps and creates a full-length
DOUBLE carrier through existing asset import and range-replace APIs. Sources
are not overwritten. Failures propagate as direction errors.
Both edit plan classes also accept `record={...}` for op-specific measurements,
lists and caveats. This finite JSON object is saved as ledger `details` and merged
into the apply record; authoritative op/track/kind/status/result fields win.

Existing edit_trim/edit_gate moves run first as one unchanged FB2 stage. New
derived edits then run in document order, before calibration/cleanup/mix. The
shared `directions/<id>.edits.json` stores full recipes under `derived`; the apply
record stores the result/key/clip/relative ledger path. `direction edit revert`
dispatches BB-18 before earlier FB2 edits, preserving its stale-layout check and
reverse application order. Single-move revert also dispatches by ledger kind.
`check` checks the derived ledger and result against the apply record. Use
`derived.regenerate` with the exact versioned calculator to repair missing audio.

### Clip-only plans

The same `derive(root, move)` planner may return
`ClipPlan(changes={clip_id: {"fade_in": samples, "fade_out": samples, "gain_db": dB}}, params=resolved)`
instead. Only the listed existing fields of existing clips on the target track
may change; an entry may contain a subset of these fields. The core validates
and journals the patch. This supports the worklog's edit_fade/edit_normalize rule
without manufacturing an audio asset. Do not implement those operations here;
their modules supply the calculations and measurements.

Clip-only before/after layouts, params and code versions live under `clip_edits`
in the same ledger. New edits record `xop_order` across both kinds. Revert walks
that order backwards, restores clip-only layouts with stale-layout checks and
dispatches derived rows to BB-18, then restores the older FB2 stage. Attempting
to revert an earlier native edit while a later extension on its track is active
is refused. Applying over another direction's active edit is also refused.

### Group derived plans

A planner may return `DerivedBundle(plans={track_id: DerivedPlan(...)},
mapping={...}, record={})`. Include target and exactly every unique peer in
move.params.group. The seam supports 16 peers plus target; op validators must
enforce their own 8/16-peer limits. Every member shares start/end,
timeline_start and fit=keep_length. Mapping is a nonempty finite JSON object
holding the common time map and/or reference-track cuts and integer shifts:
calculate it once, never separately for each track.

The seam deep-copies the frozen mapping into each calculator's resolved params
as `group_mapping`. A conflicting per-track mapping is refused. Calculators
must use that supplied map/cut list; remaining params may differ (e.g. pitch).
Mapping is part of every cache key. The seam enforces shared inputs; callbacks
remain responsible for their processing algorithm.

All targets are checked for foreign native/extension edits before planning or
registration. A failure compensates all preceding members and leaves no
registered assets, clips or ledger rows. Journal attempts/compensation remain.
`derived_groups[move]` stores mapping/hash and member results. Linked child
BB-18 recipes use internal move IDs; xop_order contains only the parent.
Never revert children directly. Check verifies every member's mapping,
registered result hash, recipe linkage and clip presence.

`derived.regenerate_group(root, direction, move, calculators={track: fn})`
repairs members via recorded recipes; cached members need no calculator.
Regeneration changes no project registration/layout. Individual file repairs
may remain if a later member cannot regenerate. Group revert preflights all
layouts, restores all members through one core patch, then updates statuses.
A stale peer prevents the whole revert. Later single/group edits sharing any
member must revert first; whole-direction revert walks mixed kinds backwards.

### Group clip-only plans

Return `ClipBundle(plans={track_id: ClipPlan(...)}, mapping={...}, record={})`
when the entire group needs no derived audio. Include exactly target and every
unique peer, up to 16 peers plus target, using a nonempty finite shared mapping.
All members must be ClipPlans; mixing DerivedPlans into this bundle is refused.
Only existing clip fade_in/fade_out/gain_db fields can change. Empty changes on
every member express a measured no-op, with its reason/evidence in record.

The wrapper preflights all foreign edits before calling the planner, freezes
`group_mapping` in every member's params and submits all clip changes in one
validated core patch. A failed member or ledger save restores the entire group;
journal attempts/compensation remain. No audio assets, derived caches or replacement
clips are created, including for a no-op.

The parent remains in `derived_groups` with optional `plan_kind="clip"`; children
live in `clip_edits`, and only the parent enters `xop_order`. Member before/after
layout and params hashes, source asset hashes, code version, owner/move_ref and mapping links are checked against the
apply record. Check follows later extension layouts in memory. Revert preflights
every member and restores all layouts in one patch, respecting the same mixed-kind
reverse order. Use ordinary `direction edit revert`, never child IDs.
`derived.regenerate_group` returns `{}` for these groups because no files exist
to regenerate. Existing DerivedBundle declarations and records are unchanged.

`time_varying=True` on a lead mix op gives E3, as for existing time-varying ops.
Every lead edit is E3 regardless of this flag. Other extension moves are at least
E2; existing listen_for warnings apply. Extension parameters are not automatic
calibration knobs: their planners own range resolution and structured arrays.

Keep callbacks deterministic, with no timestamps/network or new dependencies.
Use float64 and the existing seed rules. Test only through monkeypatched registry
entries; do not ship test ops. Run the W4 tests and existing FB2 regression tests.
