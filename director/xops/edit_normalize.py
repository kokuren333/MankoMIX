"""Measured static clip gain; no limiter and no derived audio assets."""
import copy
import json
import numpy as np
from mankomix.core import mixrender as mr
from mankomix.core.measure import loudness as L
from . import OpSpec, ClipPlan, ClipBundle
from . import _clip_edit as H


def resolve(move):
    p = H.resolve(move, {'to_db': (-60, 0, None), 'max_gain_db': (0, 40, 20),
                          'ceiling_db': (-12, 0, -1)},
                  {'mode': (['peak', 'true_peak', 'lufs_i', 'lufs_active', 'rms'], None),
                   'scope': (['clip', 'track', 'group'], 'track')}, {'group'}, required=('mode', 'to_db'))
    if 'section' in p:
        raise ValueError('normalize measures complete clips/tracks; section is not supported')
    peers = p.setdefault('group', [])
    if p['scope'] != 'group' and peers:
        raise ValueError('group is only valid with scope=group')
    return p


def validate(move, ctx):
    H.validate(move, ctx, resolve)


def measure(x, sr, mode):
    if mode == 'peak':
        return float(L.sample_peak_dbfs(x))
    if mode == 'true_peak':
        return float(L.true_peak_dbtp(x, sr))
    if mode in ('lufs_i', 'lufs_active'):
        # The existing BS.1770 absolute/relative gates exclude inactive blocks.
        return float(L.integrated(x, sr))
    power = float(np.mean(x*x)) if len(x) else 0.
    return 10*np.log10(power) if power > 0 else float('-inf')


def gain(x, sr, p):
    before = measure(x, sr, p['mode'])
    peak = float(L.true_peak_dbtp(x, sr))
    reasons = []
    if not np.isfinite(before):
        amount = 0.
        reasons.append('silence' if not np.any(x) else 'insufficient_gated_loudness')
    else:
        amount = p['to_db']-before
        if amount > p['max_gain_db']:
            amount = p['max_gain_db']
            reasons.append('max_gain_db')
        if p['mode'] in ('lufs_i', 'lufs_active', 'rms') and amount+peak > p['ceiling_db']:
            amount = p['ceiling_db']-peak
            reasons.append('ceiling_db')
    if abs(amount) < 1e-10:
        amount = 0.
    y = x.copy() if amount == 0 else x*10**(amount/20)
    return amount, {'gain_db': float(amount), 'before_db': H.finite(before),
                    'after_db': H.finite(measure(y, sr, p['mode'])),
                    'before_true_peak_dbtp': H.finite(peak),
                    'after_true_peak_dbtp': H.finite(L.true_peak_dbtp(y, sr)),
                    'limited_by': reasons}


def reference_clips(root, tid, clips, params):
    """Undo identical active normalize recipes in memory, including capped gains.

    A later unrelated layout ends the match. Source clips and the reference
    gains stay in the ordinary clip ledger; no additional persistent state.
    """
    reference = copy.deepcopy(clips)
    for path in sorted((root/'directions').glob('*.edits.json')):
        ledger = json.loads(path.read_text(encoding='utf-8'))
        order = ledger.get('xop_order', [])
        rows = ledger.get('clip_edits', {})
        for parent in reversed(order):
            members = [rows[parent]] if parent in rows else [
                row for row in rows.values() if row.get('group') == parent]
            for row in members:
                if (row.get('op') == 'edit_normalize' and row.get('status') == 'applied'
                        and row.get('track') == tid and row.get('after_clips') == reference
                        and all(row.get('params', {}).get(k) == v for k, v in params.items())):
                    reference = copy.deepcopy(row['before_clips'])
    return reference


def actual_before(row, x, sr, p):
    row['reference_before_db'] = row['before_db']
    row['before_db'] = H.finite(measure(x, sr, p['mode']))
    row['before_true_peak_dbtp'] = H.finite(L.true_peak_dbtp(x, sr))
    return row


def derive(root, move):
    from mankomix.director.edit import raw_track
    p = resolve(move)
    tids = [move['target']]+p['group']
    # Also enforce the public contract for direct library planner callers.
    if not isinstance(p['group'], list) or len(p['group']) > 32 or len(set(tids)) != len(tids):
        raise ValueError('group needs at most 32 unique peers, excluding target')
    signals, current, plans, rows, references = {}, {}, {}, {}, {}
    sr = None
    for tid in tids:
        x, sr, data = raw_track(root, tid)
        current[tid] = x
        clips = mr.find_track(data, tid)['clips']
        references[tid] = reference_clips(root, tid, clips, p)
        signals[tid] = H.render_clips(root, tid, references[tid]) if references[tid] != clips else x
    if p['scope'] == 'group':
        combined = sum(signals.values(), np.zeros_like(signals[tids[0]]))
        amount, row = gain(combined, sr, p)
        actual_before(row, sum(current.values(), np.zeros_like(combined)), sr, p)
        for tid in tids:
            clips = references[tid]
            changes = {c['id']: {'gain_db': c.get('gain_db', 0)+amount} for c in clips if not c.get('muted')}
            rows[tid] = {'before_db': H.finite(measure(current[tid], sr, p['mode'])),
                         'after_db': H.finite(measure(signals[tid]*10**(amount/20), sr, p['mode']))}
            plans[tid] = ClipPlan(changes, dict(p, gain_db=amount), rows[tid])
        rec = {'confidence': 'measured', 'measurement': row, 'members': rows,
               'group_measure': 'simultaneous raw sum; one common gain preserves relative balance'}
        # The authoritative group record owns the members key.
        rec['member_levels'] = rec.pop('members')
        return ClipBundle(plans, {'gain_db': amount, 'mode': p['mode'], 'tracks': tids}, rec)
    tid = tids[0]
    clips = references[tid]
    changes = {}
    if p['scope'] == 'track':
        amount, row = gain(signals[tid], sr, p)
        rows['track'] = actual_before(row, current[tid], sr, p)
        for c in clips:
            if not c.get('muted'):
                changes[c['id']] = {'gain_db': c.get('gain_db', 0)+amount}
    else:
        for c in clips:
            if c.get('muted'):
                continue
            x = H.render_clips(root, tid, [c])
            start, length = c['timeline_start'], mr.clip_length(data, c, sr)
            amount, rows[c['id']] = gain(x[start:start+length], sr, p)
            actual = next(v for v in mr.find_track(data, tid)['clips'] if v['id'] == c['id'])
            current_clip = H.render_clips(root, tid, [actual])[start:start+length]
            actual_before(rows[c['id']], current_clip, sr, p)
            changes[c['id']] = {'gain_db': c.get('gain_db', 0)+amount}
    return ClipPlan(changes, p, {'confidence': 'measured', 'measurements': rows})


OPS = {'edit_normalize': OpSpec('edit', ('target', 'params'), validate,
                                 derive=derive, code_version='w4d-normalize-1', group_limit=32)}
