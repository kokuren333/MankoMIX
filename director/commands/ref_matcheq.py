"""Propose a bounded FIR curve from user-supplied spectral evidence."""
import numpy as np
from mankomix.core.errors import InputError
from . import _eq_reference as E


def add_args(p):
    p.add_argument('--target', required=True)
    p.add_argument('--ref', required=True)
    p.add_argument('--kb', default=E.RS.DEFAULT_KB)
    p.add_argument('--smooth-oct', type=float, default=1/3)
    p.add_argument('--max-db', type=float, default=6.)
    p.add_argument('--band-hz', nargs=2, type=float, default=[30., 18000.])
    p.add_argument('--points', type=int, default=32)
    E.add_section(p)


def run(args):
    E.number(args.smooth_oct, 1/12, 1, '--smooth-oct')
    E.number(args.max_db, 1, 12, '--max-db')
    E.number(args.points, 8, 64, '--points')
    lo, hi = E.band_arg(args.band_hz)
    x, sr, info = E.source(args)
    target = E.spectrum(x, sr)
    refs = E.references(args)
    E.require_spectra(refs)
    ref = refs[0]['spectrum']
    if not target['active_frames'] or not ref.get('active_frames', 1):
        raise InputError('match EQ requires active audio in both signals')
    if target['lufs_i'] is None or ref.get('lufs_i') is None:
        raise InputError('match EQ requires measurable integrated loudness in both signals')
    hi = min(hi, sr/2*.98, ref['sample_rate']/2*.98)
    if lo >= hi:
        raise InputError('comparison band is above the shared Nyquist frequency')
    # Include exact taper anchors and exact band edges in the requested point budget.
    outer_lo, outer_hi = max(10., lo/2**.5), min(24000., hi*2**.5, sr/2*.999)
    grid = np.geomspace(lo, hi, args.points-2)
    difference = E.smooth_db(ref, grid, args.smooth_oct)-E.smooth_db(target, grid, args.smooth_oct)
    limited = np.clip(difference, -args.max_db, args.max_db)
    curve = [[outer_lo, 0.], *[[float(f), float(v)] for f, v in zip(grid, limited)], [outer_hi, 0.]]
    chain_target = args.target if args.target.startswith('trk_') else 'bus_mix'
    result = {'kind': 'direction_ref_matcheq', 'confidence': 'low', 'provenance': info,
              'curve': curve, 'target_spectrum': target, 'reference_spectrum': ref,
              'target_third_db': E.levels(target, 'third'), 'reference_third_db': E.levels(ref, 'third'),
              'measurements': {'normalization': 'integrated_lufs_to_-23', 'smooth_oct': args.smooth_oct,
                               'max_db': args.max_db, 'band_hz': [lo, hi],
                               'clipped_points': int(np.sum(np.abs(difference) > args.max_db))},
              'chain_add': E.move(chain_target, 'fir_eq', {'curve': curve, 'amount': 1., 'phase': 'linear', 'resolution': 'mid'}),
              'notes': ['Curve is a listening candidate; references are measurements, not targets.',
                        'Non-track audio/stage candidates address bus_mix; choose the intended track or bus before use.',
                        'Comparison spectra and curves use the same estimator; this is not independent validation.']}
    return E.clean(result)


COMMANDS = [{'path': ('ref', 'matcheq'), 'help': 'Measure a reference and propose a bounded FIR EQ curve',
             'add_args': add_args, 'run': run, 'writes': False}]
