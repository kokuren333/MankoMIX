"""T08-08 external-carrier vocoding using persistent BB-18 control data."""
import numpy as np
from . import OpSpec, MixResult, ControlPlan
from ._pitch_notes import number, clean

DEFAULTS = {'bands': 16, 'lo_hz': 100, 'hi_hz': 8000, 'attack_ms': 5,
            'release_ms': 40, 'formant_shift': 0, 'depth': 1}
RANGES = {'bands': (4, 40), 'lo_hz': (50, 500), 'hi_hz': (2000, 16000),
          'attack_ms': (.5, 50), 'release_ms': (5, 500), 'formant_shift': (-12, 12), 'depth': (0, 1)}
VERSION = 'w4e-vocode-1'


def validate(move, ctx):
    p = move.get('params')
    if not isinstance(p, dict):
        ctx.err('bad_value', 'params must be an object')
        return
    if set(p)-set(DEFAULTS)-{'key'}:
        ctx.err('bad_value', 'unknown vocode parameter')
    for key, (lo, hi) in RANGES.items():
        v = p.get(key, DEFAULTS[key])
        if not number(v) or not lo <= v <= hi or (key == 'bands' and int(v) != v):
            ctx.err('bad_value', f'{key} must be in [{lo}, {hi}]')
    for key, target in [('target', move.get('target')), ('key', p.get('key'))]:
        if not isinstance(target, str) or not target.startswith('trk_'):
            ctx.err('bad_target', f'{key} must be a track ID')
        elif ctx.project is not None and target not in ctx.project.tracks():
            ctx.err('unknown_target', f'unknown {key} track')
    if p.get('key') == move.get('target'):
        ctx.err('bad_target', 'key and carrier must be distinct tracks')
    hi = p.get('hi_hz', DEFAULTS['hi_hz'])
    if ctx.project is not None and number(hi) and hi >= .49*ctx.project.rate:
        ctx.err('bad_value', 'hi_hz must be below .49*sample_rate')
    if 'section' in move:
        ctx.err('bad_value', 'vocode operates on the full timeline')


def calculate_control(x, sr, p):
    from mankomix.dspx.bb import band_envelopes as B
    # A mono control works for both mono and stereo carriers, without phase cancellation.
    envelopes = B.analyze(x, sr, p).mean(axis=2)
    times = np.arange(int(np.ceil(len(x)/sr/.005))+1)*.005
    values = np.column_stack([np.interp(times*sr, np.arange(len(x)), envelopes[:, b], right=0)
                              for b in range(p['bands'])])
    return {'kind': 'control', 'values': values, 'hop_s': .005, 'origin_s': 0.,
            'centers_hz': B.centers(p, sr)}


def expand(project, move):
    from mankomix.director.edit import raw_track
    p = {**DEFAULTS, **move['params'], 'band_q': 8, 'seed': 0}
    p['bands'] = int(p['bands'])
    x, sr, _ = raw_track(project.root, p['key'])
    payload = calculate_control(x, sr, p)
    values = payload['values']
    return MixResult(record=clean({'params': p, 'confidence': 'measured',
        'measurements': {'frames': len(x), 'hop_s': .005, 'control_frames': len(values),
                         'centers_hz': payload['centers_hz'], 'envelope_max': float(values.max()),
                         'envelope_mean_by_band': values.mean(axis=0)},
        'caveats': ['Raw key clips precede cleanup, chain and fader.',
                    'Channel envelopes are averaged; control is sampled every 5 ms.']}),
        controls=[ControlPlan('envelopes', p['key'], 0, len(x), p, calculate_control, VERSION)],
        chain=[{'type': 'band_envelope', 'params': {k: p[k] for k in
               ('bands', 'lo_hz', 'hi_hz', 'band_q', 'formant_shift', 'depth')} |
               {'envelopes': {'control': 'envelopes'}, 'mix': 1}}])


OPS = {'vocode': OpSpec('mix', ('target', 'params'), validate, expand=expand, time_varying=True)}
