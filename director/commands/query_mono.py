"""Band/time decomposition of existing P-06 stereo evidence."""
import numpy as np
from mankomix.core.errors import InputError
from mankomix.core.measure.bands import third_octave_grid
from mankomix.dspx.bb import meters
from mankomix.director import _observations_w4b as O
from . import _measurement as W


def add_args(parser):
    W.add_source(parser)
    parser.add_argument('--by-track', action='store_true')
    parser.add_argument('--worst', type=int, default=10)


def run(args):
    W.number(args.worst, 1, 2000, '--worst')
    x, sr, a, b, meta = W.source(args)
    x = x[a:b]
    bands = third_octave_grid(sr)
    stereo = meters.stereo_bands(x, sr, bands)
    windows = []
    n = round(.4*sr)
    for i in range(0, len(x)-n+1, n):
        rows = meters.stereo_bands(x[i:i+n], sr, bands)['bands']
        for name, row in rows.items():
            if row['silent']:
                continue
            windows.append({'time_s': (a+i)/sr, 'end_s': (a+i+n)/sr,
                            'band': name, 'band_hz': row['range_hz'],
                            'level_change_db': row['level_change_db'], 'cancelled': row['cancelled']})
    windows.sort(key=lambda r: (0 if r['cancelled'] else 1,
                               r['level_change_db'] if r['level_change_db'] is not None else 0,
                               r['time_s'], r['band_hz'][0]))
    contributions = []
    if args.by_track:
        if args.target != 'master':
            raise InputError('--by-track requires --target master')
        p, v = W.project(args)
        from mankomix.core import routes, mixrender as MR
        route = (v or {}).get('master', {}).get('route')
        if route != 'stem_mix':
            raise InputError('--by-track requires the current master stem_mix route')
        baseline = stereo['full_band']['level_change_db']
        for t in sorted(MR.stem_tracks(p.data), key=lambda t: t['id']):
            if t.get('muted'):
                continue
            other, rate = W.master(p, v, mute=[t['id']])
            if rate != sr:
                raise InputError('master rate changed during track comparison')
            row = O.mono(other[a:b], sr)
            loss = row['level_change_db']
            contributions.append({'track': t['id'], 'without_track_db': loss,
                                  'improvement_db': loss-baseline if loss is not None and baseline is not None else None,
                                  'cancelled': row['cancelled'], 'silent': row['silent']})
        contributions.sort(key=lambda r: (-(r['improvement_db'] if r['improvement_db'] is not None else -np.inf), r['track']))
    return W.clean({'kind': 'direction_query_mono', **meta, 'confidence': 'high',
                    'full': stereo['full_band'], 'third_octave': stereo['bands'],
                    'worst': windows[:args.worst], 'correlation_bands': O.correlation(x, sr),
                    'by_track': contributions,
                    'note': 'Signed mono loss is level_change_db; null/cancelled means negative infinity. Measurement only.'})


COMMANDS = [{'path': ('query', 'mono'), 'help': 'Measure mono fold loss by band, time and track',
             'add_args': add_args, 'run': run, 'writes': False}]
