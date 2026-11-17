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

`time_varying=True` on a lead mix op gives E3, as for existing time-varying ops.
Every lead edit is E3 regardless of this flag. Other extension moves are at least
E2; existing listen_for warnings apply. Extension parameters are not automatic
calibration knobs: their planners own range resolution and structured arrays.

Keep callbacks deterministic, with no timestamps/network or new dependencies.
Use float64 and the existing seed rules. Test only through monkeypatched registry
entries; do not ship test ops. Run the W4 tests and existing FB2 regression tests.
