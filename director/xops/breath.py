"""T10-12: fixed-feature breath candidates and explicit gain automation.

The fixed linear weights are calibrated on synthetic band-noise mountains
and short fricative probes, not a learned model. Real-recording calibration
is unavailable; confidence is evidence strength, not a calibrated probability.
"""
import re
import numpy as np
from mankomix.dspx.bb.pitch import detect_pitch
from mankomix.dspx.bb.stft import analyze
from mankomix.dspx.bb.onsets import detect_onsets
from . import OpSpec, MixResult
from . import _w4g as W

NUMERIC = {
    'reduce_db': (0, 24, 6, True), 'target_db': (-40, -6, -24, False),
    'sensitivity': (0, 1, .5, False), 'min_ms': (50, 500, 120, False),
    'max_ms': (200, 2000, 900, False), 'fade_ms': (5, 100, 25, False)}
ENUMS = {'mode': (('reduce', 'target'), 'reduce')}
WEIGHTS = {'flatness': .25, 'band_ratio': .30, 'zero_crossing': .20, 'mountain': .25}


def validate(move, ctx):
    p = W.validate(move, ctx, NUMERIC, ENUMS, ('only', 'skip'))
    if W.number(p.get('min_ms', 120)) and W.number(p.get('max_ms', 900)) and p.get('min_ms', 120) > p.get('max_ms', 900):
        ctx.err('param_range', 'min_ms must not exceed max_ms')
    for key in ('only', 'skip'):
        values = p.get(key, [])
        if (not isinstance(values, list) or len(values)>256 or
                any(not isinstance(v, str) or not re.fullmatch(r'b_[0-9]+', v) for v in values)):
            ctx.err('bad_value', f'{key} needs at most 256 query breath IDs')


def detect(x, sr, p):
    starts, powers, hop = W.frames(x, sr)
    if not len(starts) or not np.any(x):
        return []
    level = W.db(powers)
    # A top-quartile anchor avoids treating long low-level pauses as speech.
    anchor = float(np.percentile(level[level > -150], 90))
    pitch = detect_pitch(x, sr, method='yin', fmin=100, fmax=min(1000, sr*.4),
                         hop_ms=10, frame_length=max(512, 2**int(np.ceil(np.log2(sr*.05)))),
                         silence_db=anchor-45)
    voiced = pitch.voiced[:len(starts)] & (level > anchor-8)
    ref = float(np.median(level[voiced])) if voiced.any() else anchor
    candidates = (~pitch.voiced[:len(starts)]) & (level >= ref-40) & (level <= ref-8)
    st = analyze(x, sr, window=max(16, 4*round(.02*sr/4)), hop=hop)
    power = np.mean(abs(st.spectra)**2, axis=2)
    band = (st.frequencies_hz >= 1000) & (st.frequencies_hz <= 6000)
    onsets = detect_onsets(x, sr, kind='soft', threshold=.4)
    rows = []
    for first, last in W.runs(candidates):
        duration = (last-first)*hop*1000/sr
        if not p['min_ms'] <= duration <= p['max_ms']:
            continue
        margin = max(1, round(.2*sr/hop))
        if not voiced[max(0, first-margin):min(len(voiced), last+margin)].any():
            continue
        spec = power[first:last]
        flat = float(np.mean(np.exp(np.mean(np.log(spec[:, band]+1e-30), axis=1))/(np.mean(spec[:, band], axis=1)+1e-30))) if band.any() else 0.
        ratio = float(np.sum(spec[:, band])/(np.sum(spec)+1e-30))
        a, b = int(starts[first]), min(len(x), int(last*hop))
        mono = x[a:b, int(np.argmax(np.mean(x[a:b]**2, axis=0)))]
        zcr = float(np.mean(mono[1:]*mono[:-1] < 0)) if len(mono)>1 else 0.
        env = np.sqrt(powers[first:last])
        mountain = np.sin(np.linspace(0, np.pi, len(env)))
        shape = max(0., float(np.corrcoef(env, mountain)[0, 1])) if np.std(env)>1e-15 and len(env)>2 else 0.
        features = {'flatness': flat, 'band_ratio': ratio,
                    'zero_crossing': zcr, 'mountain': shape}
        normalized = {**features, 'flatness': min(1., flat/.5), 'zero_crossing': min(1., zcr/.15)}
        score = sum(WEIGHTS[k]*normalized[k] for k in WEIGHTS)
        eligible = score >= .8-.4*p['sensitivity']
        rows.append({'id': f'b_{a}', 'start_sample': a, 'end_sample': b,
                     'start_s': a/sr, 'end_s': b/sr, 'duration_ms': (b-a)*1000/sr,
                     'level_dbfs': float(W.db(np.mean(x[a:b]**2))), 'relative_db': float(W.db(np.mean(x[a:b]**2)))-ref,
                     'score': score, 'confidence': 'high' if score >= .75 else 'medium' if score >= .6 else 'low',
                     'eligible': bool(eligible), 'features': features,
                     'onset_count': sum(a <= e['sample'] < b for e in onsets)})
    return rows


def envelope(rows, sr, p, start, end, total):
    only, skip = p.get('only', []), p.get('skip', [])
    selected, points = [], {start: 0., end-1: 0.}
    for row in rows:
        if not start <= row['start_sample'] < row['end_sample'] <= end:
            continue
        if row['id'] in skip or (only and row['id'] not in only):
            continue
        if not only and (not row['eligible'] or row['confidence'] == 'low'):
            continue
        depth = p['reduce_db'] if p['mode'] == 'reduce' else max(0., row['relative_db']-p['target_db'])
        a, b = row['start_sample'], row['end_sample']
        fade = min(round(p['fade_ms']*sr/1000), (b-a-1)//2)
        points.update({a: 0., a+fade: -depth, b-1-fade: -depth, b-1: 0.})
        selected.append({**row, 'applied_reduce_db': depth, 'fade_samples': fade})
    return W.fence(sorted(points.items()), start, end, total), selected


def expand(project, move):
    p = W.params(move, NUMERIC, ENUMS)
    x, sr = W.audio(project.root, move['target'])
    a, b = W.scope(project, move, x, sr)
    rows = detect(x, sr, p)
    points, selected = envelope(rows, sr, p, a, b, len(x))
    return MixResult(W.clean({'params': p, 'candidates': rows[:2000], 'candidate_count': len(rows),
                              'selected': selected[:2000], 'selected_count': len(selected),
                              'feature_weights': WEIGHTS, 'calibration': 'synthetic_only',
                              'notes': ['Confidence is heuristic; no bundled real-recording ground truth.']}), points=points)


OPS = {'breath': OpSpec('mix', ('target',), validate, expand=expand, section=True)}
