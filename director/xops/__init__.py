"""File-discovered direction operations. Built-in operations stay in direction.py."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from importlib import import_module
from pkgutil import iter_modules
import re
from typing import Callable


@dataclass(frozen=True)
class OpSpec:
    stage: str
    required: tuple[str, ...]
    validate: Callable
    expand: Callable | None = None
    derive: Callable | None = None
    code_version: str = ""
    time_varying: bool = False
    section: bool = False


@dataclass
class ValidationContext:
    project: object
    block: dict
    where: str
    error: Callable

    def err(self, code, message):
        self.error(self.where, code, message)


@dataclass
class MixResult:
    """Sample/dB automation, processor declarations, and a JSON measurement record."""
    record: dict
    points: list = field(default_factory=list)
    chain: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    nodes: NodePlan | None = None
    controls: list[ControlPlan] = field(default_factory=list)


@dataclass
class AudioPlan:
    """Generated, already tuned/polarity-adjusted project-rate audio."""
    name: str
    audio: object
    sample_rate: int
    params: dict = field(default_factory=dict)
    code_version: str = "1"
    sources: list[dict] = field(default_factory=list)


@dataclass
class NodePlan:
    """Local names join assets, new tracks and additive clip placements."""
    tracks: list[dict] = field(default_factory=list)
    assets: list[AudioPlan] = field(default_factory=list)
    clips: list[dict] = field(default_factory=list)


@dataclass
class ControlPlan:
    name: str
    track: str
    start: int
    end: int
    params: dict
    calculate: Callable
    code_version: str


@dataclass
class DerivedBundle:
    """One frozen JSON mapping/cut list, with a DerivedPlan per affected track."""
    plans: dict[str, DerivedPlan]
    mapping: dict
    record: dict = field(default_factory=dict)


@dataclass
class DerivedPlan:
    start: int
    end: int
    params: dict
    calculate: Callable
    fit: str = "keep_length"
    timeline_start: int | None = None
    record: dict = field(default_factory=dict)


@dataclass
class ClipPlan:
    """Clip-only edit: clip id -> existing fade_in/fade_out/gain_db fields."""
    changes: dict[str, dict]
    params: dict
    record: dict = field(default_factory=dict)


@dataclass
class ClipBundle:
    """One frozen group mapping and a clip-only plan per affected track."""
    plans: dict[str, ClipPlan]
    mapping: dict
    record: dict = field(default_factory=dict)


OPS: dict[str, OpSpec] = {}
_loaded = False


def _checked(name, value):
    if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None:
        raise ImportError(f"invalid direction op name: {name!r}")
    if isinstance(value, dict):
        try:
            value = OpSpec(**value)
        except TypeError as exc:
            raise ImportError(f"{name}: invalid op spec: {exc}") from exc
    if not isinstance(value, OpSpec) or value.stage not in ("edit", "mix"):
        raise ImportError(f"{name}: expected an edit/mix OpSpec")
    if not isinstance(value.required, tuple) or not all(isinstance(k, str) for k in value.required):
        raise ImportError(f"{name}: required must be a tuple of keys")
    if not callable(value.validate) or not all(type(v) is bool for v in (value.time_varying, value.section)):
        raise ImportError(f"{name}: invalid validator or flags")
    if value.stage == "mix" and (not callable(value.expand) or value.derive is not None):
        raise ImportError(f"{name}: mix ops need expand only")
    if value.stage == "edit" and (not callable(value.derive) or value.expand is not None
                                  or not isinstance(value.code_version, str) or not value.code_version
                                  or "target" not in value.required):
        raise ImportError(f"{name}: edit ops need target, derive and code_version")
    return value


def load(builtins=()):
    """Discover in filename order, atomically reject duplicate/built-in names."""
    global _loaded
    if not _loaded:
        found = dict(OPS)
        for module in sorted(iter_modules(__path__), key=lambda m: m.name):
            if module.name.startswith("_"):
                continue
            declarations = getattr(import_module(f"{__name__}.{module.name}"), "OPS", None)
            if not isinstance(declarations, dict):
                raise ImportError(f"{module.name}: expected OPS dict")
            for name, value in declarations.items():
                if name in found or name in builtins:
                    raise ImportError(f"duplicate direction op: {name}")
                found[name] = _checked(name, value)
        OPS.update(found)
        _loaded = True
    return specs(builtins)


def specs(builtins=()):
    conflict = set(OPS).intersection(builtins)
    if conflict:
        raise ImportError(f"duplicate direction op: {', '.join(sorted(conflict))}")
    return {name: _checked(name, value) for name, value in sorted(OPS.items())}


def apply_edit(root, doc, move, spec, *, actor):
    """All derived edits use BB-18's cache, source checks, placement and ledger."""
    from .. import derived, edit
    targets = {move['target'], *(move.get('params', {}).get('group') or [])}
    foreign = edit._live_foreign_edit(root, doc['id'], targets)
    if foreign is not None:
        raise ValueError('track still holds another direction edit; revert it first')
    for path in sorted((root / 'directions').glob('*.edits.json')):
        ledger = json.loads(path.read_text(encoding='utf-8'))
        if ledger.get('direction') != doc['id'] and any(
                row.get('track') in targets and row.get('status') == 'applied'
                for kind in ('derived', 'clip_edits') for row in ledger.get(kind, {}).values()):
            raise ValueError('track still holds another direction extension edit; revert it first')
    plan = spec.derive(root, copy.deepcopy(move))
    if not isinstance(plan, (ClipPlan, DerivedPlan, DerivedBundle, ClipBundle)) or not isinstance(plan.record, dict):
        raise ValueError(f"{move['op']}: expected an edit plan with a JSON record")
    if isinstance(plan, ClipBundle):
        with derived.transaction(root, actor=actor):
            return _apply_plan(root, doc, move, spec, plan, targets, actor=actor)
    return _apply_plan(root, doc, move, spec, plan, targets, actor=actor)


def _apply_plan(root, doc, move, spec, plan, targets, *, actor):
    from .. import derived, edit
    details = json.loads(derived._json(plan.record))
    if isinstance(plan, (DerivedBundle, ClipBundle)):
        from . import _group
        row = _group.apply(root, doc, move, spec, plan, actor=actor)
    elif len(targets) > 1:
        raise ValueError('group edits require a DerivedBundle or ClipBundle')
    elif isinstance(plan, ClipPlan):
        row = _apply_clips(root, doc, move, spec, plan, actor)
    else:
        row = derived.apply(root, doc["id"], move["id"], move["target"], plan.start, plan.end,
                            op=move["op"], params=plan.params, code_version=spec.code_version,
                            calculate=plan.calculate, fit=plan.fit, timeline_start=plan.timeline_start, actor=actor)
    # Record cross-kind order so interleaved clip-only and derived edits revert safely.
    path = edit.ledger_path(root, doc['id'])
    ledger = derived._ledger(root, doc['id'])
    group = 'derived_groups' if isinstance(plan, (DerivedBundle, ClipBundle)) else 'clip_edits' if isinstance(plan, ClipPlan) else 'derived'
    ledger[group][move['id']]['details'] = details
    ledger.setdefault('xop_order', []).append(move['id'])
    derived._save(path, ledger)
    if isinstance(plan, (DerivedBundle, ClipBundle)):
        return {**details, **{k: copy.deepcopy(row[k]) for k in
                ('kind', 'op', 'track', 'members', 'mapping', 'mapping_sha256', 'status')},
                'ledger': f"directions/{doc['id']}.edits.json"}
    if isinstance(plan, ClipPlan):
        return {**details, "op": move['op'], "track": move['target'], "kind": "clip_edit", "status": row['status'],
                "params": row['params'], "ledger": f"directions/{doc['id']}.edits.json"}
    return {**details, "op": move["op"], "track": move["target"], "kind": "derived", "status": row["status"],
            "key": row["key"], "result": row["result"], "clip": row["clip"],
            "ledger": f"directions/{doc['id']}.edits.json"}


def _apply_clips(root, doc, move, spec, plan, actor):
    from mankomix.core import api
    from mankomix.core.project import Project
    from .. import derived, edit
    ledger = derived._ledger(root, doc['id'])
    if any(move['id'] in ledger.get(key, {}) for key in ('moves', 'derived', 'clip_edits', 'derived_groups')):
        raise ValueError('move already has an edit ledger record')
    project = Project.open(root)
    ti = next(i for i, t in enumerate(project.data['tracks']) if t['id'] == move['target'])
    clips = project.data['tracks'][ti]['clips']
    entry = _clip_entry(clips, move, spec, plan)
    after = entry['after_clips']
    # The core still validates ranges/types and journals the ordinary clip fields.
    result = api.patch(root, [{'op': 'replace', 'path': f'/tracks/{ti}/clips', 'value': after}], actor=actor,
                       reason=f"direction {doc['id']} move {move['id']}: clip edit")
    entry['journal_seq'] = result.get('journal_seq')
    ledger.setdefault('clip_edits', {})[move['id']] = entry
    ledger['reverted'] = False
    derived._save(edit.ledger_path(root, doc['id']), ledger)
    return entry


def _clip_entry(clips, move, spec, plan):
    from .. import derived
    after = copy.deepcopy(clips)
    if not isinstance(plan.changes, dict) or not isinstance(plan.params, dict):
        raise ValueError('ClipPlan needs changes and params dictionaries')
    by_id = {c['id']: c for c in after}
    for cid, fields in plan.changes.items():
        if cid not in by_id or not isinstance(fields, dict) or not fields or set(fields) - {'fade_in', 'fade_out', 'gain_db'}:
            raise ValueError('ClipPlan may change only existing clip fades/gain_db on its target')
        by_id[cid].update(copy.deepcopy(fields))
    entry = {'kind': 'clip_edit', 'op': move['op'], 'track': move['target'], 'params': plan.params,
             'code_version': spec.code_version, 'before_clips': copy.deepcopy(clips), 'after_clips': after,
             'status': 'applied'}
    return json.loads(derived._json(entry))


def revert_edits(root, direction, move=None, *, actor='human'):
    """Revert registered edit kinds in reverse order, retaining BB-18 stale checks."""
    from .. import derived
    ledger = derived._ledger(root, direction)
    if any(row.get('plan_kind') == 'clip' and row.get('status') == 'applied'
           and (move is None or mid == move) for mid, row in ledger.get('derived_groups', {}).items()):
        with derived.transaction(root, actor=actor):
            return _revert_edits(root, direction, move, actor=actor)
    return _revert_edits(root, direction, move, actor=actor)


def _revert_edits(root, direction, move=None, *, actor='human'):
    from mankomix.core import api, journal
    from mankomix.core.project import Project
    from .. import derived, edit
    ledger = derived._ledger(root, direction)
    from . import _group
    rows = {**ledger.get('derived', {}), **ledger.get('clip_edits', {}), **ledger.get('derived_groups', {})}
    order = ledger.get('xop_order', [])
    if move in order and any(rows[mid].get('status') == 'applied' and _group.tracks(rows[mid]) & _group.tracks(rows[move])
                             for mid in order[order.index(move) + 1:]):
        raise ValueError(f'{move}: revert later moves on this track first')
    targets = [mid for mid in order
               if (move is None or mid == move) and rows[mid]['status'] == 'applied']
    for mid in reversed(targets):
        row = rows[mid]
        if row['kind'] == 'derived_group':
            _group.revert(root, direction, mid, actor=actor)
        elif row['kind'] == 'derived':
            derived.revert(root, direction, mid, actor=actor)
            current = derived._ledger(root, direction)
            current['reverted'] = not any(entry.get('status') == 'applied'
                                          for kind in ('moves', 'derived', 'clip_edits', 'derived_groups', 'nodes', 'controls')
                                          for entry in current.get(kind, {}).values())
            derived._save(edit.ledger_path(root, direction), current)
        else:
            project = Project.open(root)
            ti = next(i for i, t in enumerate(project.data['tracks']) if t['id'] == row['track'])
            if project.data['tracks'][ti]['clips'] != row['after_clips']:
                raise ValueError(f'{mid}: clip layout changed; revert later moves first')
            api.patch(root, [{'op': 'replace', 'path': f'/tracks/{ti}/clips', 'value': row['before_clips']}],
                      actor=actor, reason=f'direction {direction} move {mid}: revert clip edit')
            current = derived._ledger(root, direction)
            current['clip_edits'][mid].update(status='reverted', reverted_journal_seq=journal.last_seq(root))
            derived._save(edit.ledger_path(root, direction), current)
    ledger = derived._ledger(root, direction)
    ledger['reverted'] = not any(row.get('status') == 'applied'
                                  for kind in ('moves', 'derived', 'clip_edits', 'derived_groups', 'nodes', 'controls')
                                  for row in ledger.get(kind, {}).values())
    if targets:
        derived._save(edit.ledger_path(root, direction), ledger)
    return {'kind': 'direction_edit_revert', 'direction': direction, 'move': move, 'reverted_moves': targets,
            'journal_seq': journal.last_seq(root), 'ledger_reverted': ledger['reverted'],
            'ledger': f'directions/{direction}.edits.json'}
