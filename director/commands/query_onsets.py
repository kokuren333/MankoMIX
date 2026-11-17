"""Stable BB-22 hit IDs, grid deviations and one-to-one track comparisons."""
import numpy as np
from mankomix.core.errors import InputError
from mankomix.director import _observations_w4b as O, query as Q
from . import _measurement as W


def add_args(parser):
    W.add_source(parser)
    parser.add_argument('--kind', choices=('percussive', 'soft'), default='percussive')
    parser.add_argument('--band', choices=('full', 'low', 'mid', 'high'), default='full')
    parser.add_argument('--threshold', type=float, default=.3)
    parser.add_argument('--min-interval-ms', type=float, default=30)
    parser.add_argument('--grid-note')
    parser.add_argument('--bpm', type=float)
    parser.add_argument('--origin-s', type=float)
    parser.add_argument('--against')


def run(args):
    raw = {k: getattr(args, k) for k in ('kind', 'band', 'threshold', 'min_interval_ms',
                                        'grid_note', 'bpm', 'origin_s') if getattr(args, k) is not None}
    try:
        p = O.params('onsets', raw)
    except Q.QueryError as e:
        raise InputError(str(e)) from None
    x, sr, a, b, meta = W.source(args)
    events = O.onset_events(x, sr, p, offset=a, end=b)
    summary = O.observe(x, sr, {'primitive': 'onsets', 'params': p}, a, b)
    result = {'kind': 'direction_query_onsets', **meta, **summary, 'onsets': events}
    if args.against:
        if not args.against.startswith('trk_'):
            raise InputError('--against must be trk_<stem>')
        y, rate, c, d, _ = W.source(args, args.against)
        if rate != sr:
            raise InputError('comparison sample rates differ')
        peers = O.onset_events(y, sr, p, offset=c, end=d)
        # Global nearest-pair selection, deterministic ties; each hit used once.
        peer_samples = np.array([e['sample'] for e in peers])
        candidates = []
        for i, e in enumerate(events):
            lo = np.searchsorted(peer_samples, e['sample']-.5*sr, side='left')
            hi = np.searchsorted(peer_samples, e['sample']+.5*sr, side='right')
            for j in range(int(lo), int(hi)):
                f = peers[j]
                candidates.append((abs(e['sample']-f['sample']), e['sample'], f['sample'], i, j))
        candidates.sort()
        used, taken, pairs = set(), set(), []
        for _, _, _, i, j in candidates:
            if i in used or j in taken:
                continue
            used.add(i)
            taken.add(j)
            pairs.append({'target': events[i]['id'], 'against': peers[j]['id'],
                          'delta_ms': (events[i]['sample']-peers[j]['sample'])/sr*1000})
        pairs.sort(key=lambda r: int(r['target'][2:]))
        result['comparison'] = {'against': args.against, 'pairs': pairs, 'max_distance_ms': 500,
                                'unmatched_target': [e['id'] for i, e in enumerate(events) if i not in used],
                                'unmatched_against': [e['id'] for j, e in enumerate(peers) if j not in taken],
                                'delta_ms': O.distribution([e['delta_ms'] for e in pairs])}
    return W.clean(result)


COMMANDS = [{'path': ('query', 'onsets'), 'help': 'Measure onsets with stable sample-position IDs',
             'add_args': add_args, 'run': run, 'writes': False}]
