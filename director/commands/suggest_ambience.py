"""T10-18: Welch room-tone evidence and a pasteable noise_bed candidate."""
import numpy as np
from scipy.signal import welch
from mankomix.core.errors import InputError
from mankomix.director.direction import _Project
from mankomix.director.xops import _w4g as W
from mankomix.dspx.bb.stft import smooth_frequency


def add_args(parser):
    parser.add_argument('--target', required=True)
    parser.add_argument('--region', help='Explicit noise-only interval t0,t1 in seconds')
    parser.add_argument('--find-quiet', action='store_true')
    parser.add_argument('--points', type=int, default=32)
    parser.add_argument('--smooth-oct', type=float, default=1/3)


def measure(x, sr, points=32, smooth_oct=1/3):
    n = min(len(x), max(256, round(sr*.34)))
    f, psd = welch(x, sr, nperseg=n, noverlap=n//2, axis=0)
    power = np.mean(psd, axis=1)
    db = smooth_frequency(W.db(power)[None, :], f, smooth_oct)[0]
    hz = np.geomspace(20, min(sr/2, 24000), points)
    values = np.interp(np.log2(hz), np.log2(np.maximum(f, .001)), db)
    values -= np.max(values)
    spectrum = [[float(a), float(np.clip(v, -120, 24))] for a, v in zip(hz, values)]
    level = float(W.db(np.mean(x*x)))
    if x.shape[1] >= 2:
        left, right = x[:, 0]-np.mean(x[:, 0]), x[:, 1]-np.mean(x[:, 1])
        correlation = float(np.sum(left*right)/max(1e-30, np.sqrt(np.sum(left*left)*np.sum(right*right))))
    else:
        correlation = 1.
    _, powers, _ = W.frames(x, sr, 100)
    spread = float(np.percentile(W.db(powers), 95)-np.percentile(W.db(powers), 5))
    return {'spectrum': spectrum, 'level_dbfs': level, 'correlation': correlation,
            'confidence': 'low' if spread > 6 or level < -119 else 'high',
            'measurements': {'frame_level_p95_p05_db': spread, 'welch_window_samples': n,
                             'welch_frames': 1+max(0, (len(x)-n)//(n//2)), 'samples': len(x)}}


def run(args):
    if not 8 <= args.points <= 64 or not W.number(args.smooth_oct) or not 0 <= args.smooth_oct <= 3:
        raise InputError('points needs 8..64; smooth-oct needs 0..3')
    project = _Project(args.project or '.')
    if args.target not in project.tracks():
        raise InputError('--target must be an existing track ID')
    x, sr = W.audio(project.root, args.target)
    if args.find_quiet:
        starts, powers, hop = W.frames(x, sr, 500)
        indices = sorted(range(len(powers)), key=lambda i: (powers[i], i))[:8]
        return W.clean({'kind': 'direction_suggest_ambience', 'confidence': 'low', 'candidates': [],
                        'quiet_regions': [{'region_s': [int(starts[i])/sr, min(len(x), int(starts[i])+hop)/sr],
                                           'level_dbfs': float(W.db(powers[i]))} for i in indices],
                        'notes': ['Quiet regions are candidates only; explicitly select a noise-only region.']})
    try:
        a, b = map(float, (args.region or '').split(','))
        if not np.isfinite([a, b]).all() or not 0 <= a < b <= len(x)/sr or b-a < .2:
            raise ValueError
    except ValueError:
        raise InputError('--region t0,t1 is required and must be in bounds, at least 0.2 seconds') from None
    result = measure(x[round(a*sr):round(b*sr)], sr, args.points, args.smooth_oct)
    params = {'spectrum': result['spectrum'], 'hiss_db': result['level_dbfs'],
              'width': float(np.clip(1-result['correlation'], 0, 1)), 'seed': 0}
    valid = -120 <= params['hiss_db'] <= -30
    move = {'id': 'ambience_1', 'op': 'chain_add', 'target': args.target, 'aim': 'ambience',
            'basis': 'explicit noise-only Welch region', 'origin': 'new',
            'processor': 'noise_bed', 'params': params}
    notes = ['Measured values only; no audio or project changes are saved.',
             'For edit gaps, use a separate ambience track and gain_curve to delimit the gap.']
    if not valid:
        notes.append('Measured level is outside noise_bed hiss_db limits; no candidate emitted.')
    if result['correlation'] < 0:
        notes.append('noise_bed width is limited to 1; negative correlation cannot be reproduced.')
    return W.clean({'kind': 'direction_suggest_ambience', 'target': args.target, 'region_s': [a, b],
                    'sample_rate': sr, **result, 'candidates': [move] if valid else [], 'notes': notes})


COMMANDS = [{'path': ('suggest', 'ambience'), 'help': 'Measure an explicit room-tone region and suggest noise_bed',
             'add_args': add_args, 'run': run, 'writes': False}]
