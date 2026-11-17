"""T11-07: constant-tempo integer slice quantization and frozen-map stretch."""
import copy
import numpy as np
from . import OpSpec, DerivedPlan, DerivedBundle
from . import _alignment as A

NUMERIC = {'bpm': (20, 400, None), 'origin_s': (0, 36000, 0), 'swing': (0, .75, 0),
           'strength': (0, 1, .7), 'max_shift_ms': (1, 200, 40), 'min_shift_ms': (0, 50, 3),
           'slice_pre_ms': (0, 20, 3), 'threshold_db': (-80, 0, -30),
           'detect_lo_hz': (20, 20000, 20), 'detect_hi_hz': (20, 20000, 20000),
           'min_interval_ms': (5, 500, 30)}
ENUMS = {'mode': (['slice', 'stretch'], 'slice'), 'fill': (['stretch_tail', 'silence'], 'stretch_tail')}


def validate(move, ctx):
    A.validate(move, ctx, quantize=True)


def resolve(move):
    p = {k: d for k, (_, _, d) in NUMERIC.items()} | {k: d for k, (_, d) in ENUMS.items()}
    p.update(grid_note='1/16', group=[], only=[], skip=[], detect_from=move['target'], seed=0)
    p.update(copy.deepcopy(move['params']))
    if isinstance(p['strength'], list):
        lo, hi = p['strength']
        selection = move.get('select', 'mid')
        if isinstance(selection, dict):
            selection = selection.get('strength', 'mid')
        p['strength'] = {'min': lo, 'max': hi}.get(selection, (lo+hi)/2)
    return p


def nearest(sample, sr, p):
    from mankomix.dspx.bb.curves import period_ms
    period = period_ms(1, note=p['grid_note'], bpm=p['bpm'])*sr/1000
    origin = p['origin_s']*sr
    k = int(np.floor((sample-origin)/period))
    candidates = [round(origin+(j+(j % 2)*p['swing'])*period) for j in range(k-2, k+3)]
    return min(candidates, key=lambda n: (abs(n-sample), n))


def cut_at(x, sample, sr, pre_ms):
    mono = x[:, int(np.argmax(np.sum(x*x, axis=0)))]
    nominal = max(0, sample-round(pre_ms*.001*sr))
    a, b = max(0, nominal-round(.001*sr)), min(len(x)-1, nominal+round(.001*sr))
    choices = np.flatnonzero((mono[a:b]*mono[a+1:b+1] <= 0))+a
    return int(min(choices, key=lambda n: (abs(n-nominal), n))) if len(choices) else nominal


def slice_audio(x, sr, mapping, fill, *, freeze=False):
    from mankomix.dspx.bb.alignment_warp import schedule, warp
    out = np.zeros_like(x)
    cuts, shifts = mapping['cuts'], mapping['shifts']
    cross = max(1, round(.005*sr))
    end_previous = 0
    for index, (a, b, shift) in enumerate(zip(cuts[:-1], cuts[1:], shifts)):
        start, end = a+shift, b+shift
        lo, hi = max(0, start), min(len(x), end)
        if hi <= lo:
            continue
        piece = x[a+lo-start:a+hi-start].copy()
        if lo < end_previous:
            # Trim the old tail to a five-millisecond overlap; preserve interiors.
            stop = min(hi, end_previous, lo+cross)
            width = stop-lo
            w = .5-.5*np.cos(np.linspace(0, np.pi, width))
            piece[:width] = out[lo:stop]*(1-w[:, None])+piece[:width]*w[:, None]
        elif lo > end_previous:
            gap = lo-end_previous
            width = min(cross, end_previous)
            if fill == 'stretch_tail' and end_previous > 0:
                tail = min(round(.030*sr), end_previous)
                source_tail = out[end_previous-tail:end_previous]
                if freeze:
                    mapping['tail_synthesis'][str(index)] = schedule(source_tail, sr, [[0, 0], [tail, tail+gap]])
                stretched = warp(source_tail, sr, mapping['tail_synthesis'][str(index)])
                fade = min(cross, tail)
                w = .5-.5*np.cos(np.linspace(0, np.pi, fade))
                out[end_previous-tail:end_previous-tail+fade] = (out[end_previous-tail:end_previous-tail+fade]*(1-w[:, None])+stretched[:fade]*w[:, None])
                out[end_previous-tail+fade:lo] = stretched[fade:tail+gap]
                # Blend at the new head; its body remains a copied slice.
                fade = min(cross, len(piece))
                w = .5-.5*np.cos(np.linspace(0, np.pi, fade))
                piece[:fade] = stretched[-1]*(1-w[:, None])+piece[:fade]*w[:, None]
            else:
                if width:
                    out[end_previous-width:end_previous] *= np.linspace(1, 0, width)[:, None]
                fade = min(cross, len(piece))
                piece[:fade] *= np.linspace(0, 1, fade)[:, None]
        out[lo:hi] = piece
        end_previous = hi
    return out


def calculate(x, sr, p):
    mapping = p.get('group_mapping', p['mapping'])
    if p['mode'] == 'slice':
        return slice_audio(x, sr, mapping, p['fill'])
    from mankomix.dspx.bb.alignment_warp import warp
    return warp(x, sr, mapping['synthesis'])


def derive(root, move):
    from mankomix.dspx.bb.drum_events import band_audio, drum_onsets
    from mankomix.director._observations_w4b import distribution
    from mankomix.dspx.bb.alignment_warp import schedule
    full, sr, data, a, b = A.source(root, move)
    p = resolve(move)
    detector, dep = A.dependency(root, p['detect_from'])
    p['detector_source'] = dep
    filtered = band_audio(detector, sr, p['detect_lo_hz'], p['detect_hi_hz'])
    # Primary BB-22 IDs are unchanged; reuse W4c's supplemental flux candidates.
    events = [e for e in drum_onsets(detector, sr, min_interval_ms=p['min_interval_ms']) if a <= e['sample'] < b]
    known = {e['id'] for e in events}
    unknown = (set(p['only']) | set(p['skip']))-known
    if unknown:
        raise ValueError('onset IDs not found with pinned detector: '+', '.join(sorted(unknown)))
    rows = []
    for e in events:
        s = e['sample']
        grid = nearest(s, sr, p)
        delta = grid-s
        level = 20*np.log10(max(1e-15, float(np.max(abs(filtered[s:min(len(filtered), s+round(.030*sr))]), initial=0))))
        reason = ('not_selected' if p['only'] and e['id'] not in p['only'] else
                  'skipped' if e['id'] in p['skip'] else 'below_threshold' if level < p['threshold_db'] else
                  'max_shift' if abs(delta) > p['max_shift_ms']*.001*sr else
                  'min_shift' if abs(delta) < p['min_shift_ms']*.001*sr else
                  'strength_zero' if p['strength'] == 0 else 'moved')
        shift = round(p['strength']*delta) if reason == 'moved' else 0
        if not a < s+shift < b:
            shift, reason = 0, 'section_boundary'
        rows.append({'id': e['id'], 'sample': s, 'grid_sample': grid, 'shift_samples': shift,
                     'time_s': s/sr, 'grid_s': grid/sr,
                     'detect_peak_dbfs': float(level), 'reason': reason})
    # Reject both sides of a crossing, using the original candidate list.
    moved = [r['sample']+r['shift_samples'] for r in rows]
    reject = {i for i in range(len(rows)) if (i and moved[i] <= moved[i-1]) or (i+1 < len(rows) and moved[i] >= moved[i+1])}
    for i in reject:
        rows[i].update(shift_samples=0, reason='would_reorder')
    # Recheck after resetting candidates: a rejected neighbor must remain fixed.
    while any(rows[i]['sample']+rows[i]['shift_samples'] >= rows[i+1]['sample']+rows[i+1]['shift_samples'] for i in range(len(rows)-1)):
        for i in range(len(rows)-1):
            if rows[i]['sample']+rows[i]['shift_samples'] >= rows[i+1]['sample']+rows[i+1]['shift_samples']:
                rows[i].update(shift_samples=0, reason='would_reorder')
                rows[i+1].update(shift_samples=0, reason='would_reorder')
    x = full[a:b]
    cuts, shifts = [0], [0]
    for row in rows:
        cut = cut_at(x, row['sample']-a, sr, p['slice_pre_ms'])
        shift = row['shift_samples']
        if cut <= cuts[-1] or cut+shift < 0 or cut+shift >= len(x):
            row.update(shift_samples=0, reason='slice_boundary')
            continue
        cuts.append(cut); shifts.append(shift)
    cuts.append(len(x))
    for row in rows:
        row.update(shift_ms=row['shift_samples']*1000/sr, after_s=(row['sample']+row['shift_samples'])/sr)
    points = [[0, 0]]+[[r['sample']-a, r['sample']-a+r['shift_samples']] for r in rows if a < r['sample'] < b]+[[len(x), len(x)]]
    mapping = {'map': points, 'cuts': cuts, 'shifts': shifts, 'synthesis': None, 'tail_synthesis': {}}
    neutral = not any(r['shift_samples'] for r in rows)
    if p['mode'] == 'stretch' and not neutral:
        mapping['synthesis'] = schedule(x, sr, points)
    params = {t: {**copy.deepcopy(p), 'mapping': mapping} for t in [move['target']]+p['group']}
    if neutral:
        y = x.copy()
    elif p['mode'] == 'slice':
        y = slice_audio(x, sr, mapping, p['fill'], freeze=True)
    else:
        y = calculate(x, sr, params[move['target']])
    after = drum_onsets(y, sr, min_interval_ms=p['min_interval_ms'])
    record = A.clean({'confidence': 'high' if rows else 'low', 'reason': 'constant_tempo_grid',
                      'tempo_assumption': 'constant', 'onsets': rows, 'mapping': mapping,
                      'grid_delta_ms': {'before': distribution([(r['sample']-r['grid_sample'])*1000/sr for r in rows]),
                                        'planned_after': distribution([(r['sample']+r['shift_samples']-r['grid_sample'])*1000/sr for r in rows]),
                                        'measured_after': distribution([(e['sample']+a-nearest(e['sample']+a, sr, p))*1000/sr for e in after])},
                      'measurements': A.accounting(x, y, sr), 'sample_rate': sr, 'section_samples': [a, b]})
    if neutral:
        return A.bundle(move, a, b, params, mapping, record, True)
    plans = {t: DerivedPlan(a, b, local, calculate, record=record) for t, local in params.items()}
    return DerivedBundle(plans, mapping, record) if p['group'] else plans[move['target']]


OPS = {'edit_quantize': OpSpec('edit', ('target', 'params'), validate, derive=derive,
                              code_version='w4f-quantize-1', time_varying=True)}
