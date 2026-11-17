"""Compare eight low bands with a user-measured reference distribution."""
import numpy as np
from . import _eq_reference as E


def add_args(p):
    p.add_argument('--target', default='mix', help='Default: premaster mix bus; master reads an existing render')
    E.add_references(p, required=True)
    p.add_argument('--max-db', type=float, default=3.)
    E.add_section(p)


def run(args):
    E.number(args.max_db, 1, 6, '--max-db')
    refs = E.references(args)
    E.require_spectra(refs)
    x, sr, info = E.source(args)
    spec = E.spectrum(x, sr)
    current = E.levels(spec, 'lowend')
    reference = [E.levels(r['spectrum'], 'lowend') for r in refs]
    rows = []
    for i, (lo, hi) in enumerate(E.bands('lowend', sr)):
        row = {'band_hz': [lo, hi], **E.distribution(current[i], [r[i] for r in reference])}
        row['proposed_gain_db'] = float(np.clip(-(row['outside_db'] or 0.), -args.max_db, args.max_db))
        rows.append(row)
    choices = sorted((r for r in rows if abs(r['proposed_gain_db']) > 1e-6),
                     key=lambda r: (-abs(r['proposed_gain_db']), r['band_hz'][0]))[:4]
    target = args.target if args.target.startswith('trk_') else 'bus_mix'
    moves = [E.move(target, 'eq', {'shape': 'peak', 'freq_hz': float(np.sqrt(np.prod(r['band_hz']))),
                                 'bw_oct': .5, 'gain_db': r['proposed_gain_db']}, i+1)
             for i, r in enumerate(choices)]
    return E.clean({'kind': 'direction_suggest_lowend', 'confidence': E.confidence(len(refs)),
                    'reference_count': len(refs), 'provenance': info, 'bands': rows,
                    'normalization': 'band_power_relative_to_300_3000_hz', 'candidates': moves,
                    'target_spectrum': spec,
                    'notes': [E.LOW_NOTE, 'Up to four largest departures are listening candidates; no move is applied.']})


COMMANDS = [{'path': ('suggest', 'lowend'), 'help': 'Suggest low-band EQ against measured reference quartiles',
             'add_args': add_args, 'run': run, 'writes': False}]
