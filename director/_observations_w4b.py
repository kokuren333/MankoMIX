"""Read-only W4b quantities; existing stereo and onset meters are authoritative.

Undefined levels (silence or complete cancellation) remain null with explicit
flags, as in P-06. Signed mono loss is P-06's level_change_db, not its positive
loss magnitude. Structured quantities have no invented scalar verdict.
"""
import math
import numpy as np

from mankomix.core.measure.bands import Band
from mankomix.core.master_analysis import windowed_correlation
from mankomix.dspx.bb import meters, onsets

PRIMITIVES = ('mono_loss', 'correlation_bands', 'onsets')
CORRELATION_BANDS = (Band('low', 0, 120), Band('lowmid', 120, 500),
                     Band('mid', 500, 2000), Band('high', 2000, 8000),
                     Band('air', 8000, 20000))


def params(primitive, raw):
    from .query import QueryError
    if not isinstance(raw, dict):
        raise QueryError('params must be an object')
    allowed = {'mono_loss': {'band'}, 'correlation_bands': set(),
               'onsets': {'kind', 'band', 'threshold', 'min_interval_ms',
                          'grid_note', 'bpm', 'origin_s'}}[primitive]
    if set(raw) - allowed:
        raise QueryError('unknown parameters: '+', '.join(sorted(set(raw)-allowed)))
    p = dict(raw)
    if primitive == 'mono_loss':
        b = p.setdefault('band', 'full')
        valid = isinstance(b, str) and b == 'full'
        if isinstance(b, (int, float)) and not isinstance(b, bool):
            valid = math.isfinite(b) and 20 <= b <= 20000
        if isinstance(b, (list, tuple)):
            valid = (len(b) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                      and math.isfinite(v) for v in b) and 0 <= b[0] < b[1] <= 20000)
        if not valid:
            raise QueryError('band must be full, a 20..20000 Hz third-octave center, or [lo, hi]')
    if primitive != 'onsets':
        return p
    p = dict(kind='percussive', band='full', threshold=.3, min_interval_ms=30) | p
    if p['kind'] not in ('percussive', 'soft') or p['band'] not in ('full', 'low', 'mid', 'high'):
        raise QueryError('invalid onset kind or band')
    for key, lo, hi in [('threshold', 0, 1), ('min_interval_ms', 5, 500),
                         ('bpm', 20, 400), ('origin_s', 0, 36000)]:
        if key in p and (not isinstance(p[key], (int, float)) or isinstance(p[key], bool)
                         or not math.isfinite(p[key]) or not lo <= p[key] <= hi):
            raise QueryError(f'{key} must be a finite number in [{lo}, {hi}]')
    if any(k in p for k in ('grid_note', 'bpm', 'origin_s')):
        from mankomix.dsp.processors import NOTE_VALUES
        if p.get('grid_note') not in NOTE_VALUES[1:] or 'bpm' not in p:
            raise QueryError('grid requires grid_note and bpm')
        p.setdefault('origin_s', 0.)
    return p


def distribution(values):
    v = np.asarray(values, dtype=np.float64)
    if not len(v):
        return {'median': None, 'q1': None, 'q3': None, 'max': None, 'max_abs': None}
    q1, med, q3 = map(float, np.percentile(v, [25, 50, 75]))
    return {'median': med, 'q1': q1, 'q3': q3, 'max': float(v.max()),
            'max_abs': float(np.max(np.abs(v)))}


def onset_events(x, sr, p, *, offset=0, end=None):
    # Detect with full preceding context; section selection never renumbers IDs.
    events = onsets.detect_onsets(x, sr, **{k: p[k] for k in ('kind', 'band', 'threshold', 'min_interval_ms')})
    return [e for e in events if offset <= e['sample'] < (end if end is not None else len(x))]


def grid_deviations(events, p):
    note = p['grid_note']
    suffix = note[-1] if note[-1] in 'dt' else ''
    denominator = float(note[2:-1] if suffix else note[2:])
    interval = 60/p['bpm']*4/denominator*({'d': 1.5, 't': 2/3}.get(suffix, 1))
    # A tie selects the earlier grid point, matching alignment operations.
    return [(e['time_s']-p['origin_s']-math.ceil((e['time_s']-p['origin_s'])/interval-.5)*interval)*1000
            for e in events]


def mono(x, sr, band='full'):
    if isinstance(band, str) and band == 'full':
        return meters.stereo_bands(x, sr)['full_band']
    lo, hi = (band*10**(-.05), band*10**(.05)) if isinstance(band, (int, float)) else band
    if lo >= sr/2:
        from .query import QueryError
        raise QueryError('band is above Nyquist')
    return meters.stereo_bands(x, sr, [Band('selected', lo, hi)])['bands']['selected']


def correlation(x, sr):
    out = []
    for b in CORRELATION_BANDS:
        if b.lo_hz >= sr/2:
            continue
        values = windowed_correlation(x, sr, b.lo_hz or None,
                                      min(b.hi_hz, sr/2*.999), .4)
        active = values[np.isfinite(values)]
        out.append({'band_hz': [b.lo_hz, min(b.hi_hz, sr/2)],
                    'median': float(np.median(active)) if len(active) else None,
                    'p05': float(np.percentile(active, 5)) if len(active) else None,
                    'negative_fraction': float(np.mean(active < 0)) if len(active) else None,
                    'active_windows': len(active), 'values': values.tolist()})
    return out


def observe(x, sr, obs, start, end):
    prim = obs['primitive']
    p = params(prim, obs.get('params', {}))
    seg = x[start:end]
    base = {'status': 'ok', 'value': None, 'confidence': 'high', 'params': p}
    if prim == 'mono_loss':
        row = mono(seg, sr, p['band'])
        base.update(value=row['level_change_db'], unit='dB', stereo=row,
                    confidence='low' if row['silent'] else 'high',
                    convention='P-06 level_change_db; null with cancelled=true means negative infinity')
    elif prim == 'correlation_bands':
        base.update(bands=correlation(seg, sr), window_ms=400, unit='',
                    note='Silent windows are omitted from percentiles and fractions.')
    else:
        events = onset_events(x, sr, p, offset=start, end=end)
        base.update(value=len(events), unit='count', count=len(events),
                    per_second=len(events)/((end-start)/sr),
                    strength=distribution([e['strength'] for e in events]),
                    confidence='medium' if events else 'low',
                    note='Heuristic detector confidence; no quality verdict.')
        if 'grid_note' in p:
            base['grid_deviation_ms'] = distribution(grid_deviations(events, p))
    return base
