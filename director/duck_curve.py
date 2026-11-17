"""Shaped keyed ducking; legacy duck parameters and detection stay untouched."""
from __future__ import annotations

import copy
import numpy as np

from mankomix.dsp.errors import ParamError


def check_params(move, moves, where, err, *, tracks, buses, bpm=None, has_project=False):
    from . import duck as K
    from . import stemobs as S
    from mankomix.dspx.bb.keyed import validate_shape
    p, target = move.get('params'), move.get('target')
    if not isinstance(p, dict):
        err(where, 'bad_value', 'duck_curve needs params (an object)')
        return
    extras = {'band_lo_hz', 'band_hi_hz', 'shape', 'hold_ms'}
    legacy = {k: v for k, v in p.items() if k not in extras and k != 'depth_db'}
    K.check_params(legacy, target, where, err, tracks=tracks, buses=buses, bpm=bpm, has_project=has_project)
    if isinstance(p.get('key'), str) and not S.is_track_target(p['key']):
        err(where, 'bad_target', 'duck_curve key must be a track id (trk_<stem>)')
    if target == 'master' or not (S.is_track_target(target) or isinstance(target, str) and target.startswith('bus_')):
        err(where, 'bad_target', 'duck_curve needs a track or bus target; master is forbidden')
    elif has_project and target not in tracks and target not in buses and not any(
            m.get('op') == 'bus_add' and m.get('target') == target for m in moves):
        err(where, 'unknown_target', f"unknown target '{target}'")
    if 'section' in move:
        err(where, 'section_scope', 'duck_curve cannot carry section')
    for key, lo, hi, ranges in [('depth_db', .5, 12, True), ('hold_ms', 0, 500, False),
                                ('band_lo_hz', 20, 8000, False), ('band_hi_hz', 60, 20000, False)]:
        if key not in p:
            continue
        v = p[key]
        vals = [v] if K._num(v) else v if ranges and K._is_range(v) else None
        if vals is None:
            err(where, 'bad_value', f'{key} needs a finite number' + (' or range' if ranges else ''))
        elif any(not (lo <= value <= hi or key.startswith('band_') and value == 0) for value in vals):
            err(where, 'param_range', f'{key} outside its allowed range')
    lo, hi = p.get('band_lo_hz', 0), p.get('band_hi_hz', 0)
    if K._num(lo) and K._num(hi) and not (lo == hi == 0) and (lo <= 0 or hi < 1.5 * lo):
        err(where, 'param_range', 'use paired zeros or band_hi_hz >= 1.5 * positive band_lo_hz')
    if 'shape' in p:
        try:
            validate_shape(p['shape'])
        except (ParamError, TypeError, ValueError):
            err(where, 'bad_value', 'shape needs 1..32 normalized, ascending x points and nondecreasing y')


def plan(root, move, params, bpm):
    """Return sample/dB points, band limits, hit times/depths and release record."""
    from . import duck as K
    from mankomix.dspx.bb.keyed import keyed_envelope, validate_band
    p = {k: v for k, v in params.items() if k in K.ALLOWED}
    p.setdefault('depth_db', 3.0)
    out = K.plan(root, move, p, bpm)
    full = K.full_params(p)
    hits, sr = K.key_hits(root, full['key'], full)
    rel, _ = K.release(p, bpm)
    hold = params.get('hold_ms', 0)
    shape = params.get('shape', [[0, 0], [1, 1]])
    lo, hi = params.get('band_lo_hz', 0), params.get('band_hi_hz', 0)
    validate_band(lo, hi, sr, full_band=True)
    out['points'] = keyed_envelope(hits, sr, full['depth_db'], full['attack_ms'], rel, shape=shape, hold_ms=hold)
    out['band'] = [lo, hi]
    out['record'].update({'op': 'duck_curve', 'shape': copy.deepcopy(shape), 'hold_ms': hold,
                          'band_hz': [lo, hi], 'points': len(out['points']),
                          'hit_list': [{'sample': int(h), 'time_s': h / sr, 'depth_db': full['depth_db']}
                                       for h in hits],
                          'recovery': K.recovery(hits, sr, full['attack_ms'], rel + hold)})
    return out


def bus_chain(proj, changes, target):
    """Get a new/planner bus chain, or a director-only existing-bus override."""
    if target == changes.get('mix_bus'):
        changes['mix_chain_changed'] = True
        return changes.setdefault('mix_chain', copy.deepcopy(proj.buses()[target].get('chain') or []))
    bus = next((b for b in changes['buses'] if b['id'] == target), None)
    if bus is not None:
        return bus.setdefault('chain', [])
    # The floor apply path cannot edit a user-owned bus. Keep the overlay
    # explicit in the proposal and apply it in director, leaving core unchanged.
    overrides = changes.setdefault('bus_overrides', {})
    return overrides.setdefault(target, {'chain': copy.deepcopy(proj.buses()[target].get('chain') or [])})['chain']


def merge_bus_ducks(proj, changes, dir_id, target, ducks, moves, record):
    """Sum full-band bus curves in the same duck column and add one adapter."""
    from .duck import merge_automation
    from .direction import _item
    from mankomix.dsp import processors as P
    total, refs = [], []
    for mid, pts in ducks:
        if pts:
            total = merge_automation(total, pts)
            refs.append(mid)
    if not refs:
        return
    move = next(m for m in moves if m['id'] == refs[0])
    gain = [[at / proj.rate, db] for at, db in total]
    item = _item(dir_id, move, 'gain_automation', P.validate_params('gain_automation', {'gain': gain}), target)
    item['move_ref'] = [f'{dir_id}/{mid}' for mid in refs]
    bus_chain(proj, changes, target).append(item)
    for mid in refs:
        record['moves'][mid]['item'] = item['id']


def apply_bus_overrides(root, overrides, actor):
    """Apply the proposal's explicit bus chains through the public Project API."""
    from mankomix.core.project import Project
    project = Project.open(root)
    buses = copy.deepcopy(project.data['buses'])
    for bus in buses:
        if bus['id'] in overrides:
            bus.update(copy.deepcopy(overrides[bus['id']]))
    project.set('/buses', buses, actor=actor, reason='direction duck_curve bus chains')


def measure_proposal(proj, changes, record):
    """Measure floor/result target renders in memory; never touch project files.

    Measurements are of the combined direction, not causal attribution to an
    isolated move. New buses have no floor measurement, explicitly recorded.
    """
    from mankomix.core.project import Project
    from mankomix.core.mixrender import render_track, render_mix
    before = Project.open(proj.root)
    after = copy.copy(before)
    after.data = copy.deepcopy(before.data)
    for t in after.data['tracks']:
        t.update(copy.deepcopy(changes['tracks'].get(t['id'], {})))
    replacement = {b['id']: copy.deepcopy(b) for b in changes['buses']}
    after.data['buses'] = [replacement.pop(b['id'], b) for b in after.data['buses']]
    after.data['buses'].extend(replacement.values())
    for b in after.data['buses']:
        if b['id'] == changes.get('mix_bus'):
            b['chain'] = copy.deepcopy(changes.get('mix_chain') or [])
        b.update(copy.deepcopy(changes.get('bus_overrides', {}).get(b['id'], {})))
    bus_records = None
    targets = {}
    for rec in record['moves'].values():
        if rec.get('op') != 'duck_curve':
            continue
        target = rec['track']
        if target not in targets:
            if target in proj.tracks():
                pair = [render_track(p, target)[0] for p in (before, after)]
                def levels(x):
                    rms = float(np.sqrt(np.mean(x * x))) if x.size else 0
                    peak = float(np.max(np.abs(x))) if x.size else 0
                    return {'rms_dbfs': round(20 * np.log10(rms), 9) if rms else None,
                            'peak_dbfs': round(20 * np.log10(peak), 9) if peak else None}
                measured = [levels(x) for x in pair]
            else:
                if bus_records is None:
                    bus_records = [{r['id']: r for r in render_mix(p)[2]['buses']} for p in (before, after)]
                measured = [{k: rs[target].get(k) for k in ('peak_dbfs', 'lufs_i')} if target in rs else None
                            for rs in bus_records]
            targets[target] = {'scope': 'combined_direction_on_target', 'before': measured[0], 'after': measured[1]}
        rec['measurements'] = copy.deepcopy(targets[target])
