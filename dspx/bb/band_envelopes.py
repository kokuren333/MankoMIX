"""Four-pole analysis/synthesis bank and external control-asset interface.

API: centers(p,sr), filter_band(x,sr,hz,q), analyze(x,sr,p), synthesize(x,
sr,p,envelopes), carrier(frames,sr,p,seed=0). Control records are dictionaries
with kind='control', values shaped (time,bands[,channels]), hop_s (default
.005), optional origin_s (default 0), and optional centers_hz. resolve_control
interpolates them onto absolute sample times and checks their layout.
install_control_resolver(fn) connects a persistent derived resolver while
retaining the empty-ID sentinel used for internal analysis. No assets are
written and no direction ops are registered here.
"""
import numpy as np
from scipy import signal
from mankomix.dsp.errors import ParamError


def install_control_resolver(resolver):
    from mankomix.dspx import assets
    def optional(asset_id):
        return {'kind': 'control', 'empty': True} if asset_id == '' else resolver(asset_id)
    assets.RESOLVERS['derived'] = optional


def _missing(asset_id):
    # Lazy import keeps processor discovery independent of the direction layer.
    from mankomix.director.derived import resolve_control
    return resolve_control(asset_id)


def ensure_optional_registry():
    from mankomix.dspx import assets
    if 'derived' not in assets.RESOLVERS:
        install_control_resolver(_missing)


def asset_param(required=False):
    ensure_optional_registry()
    return dict(id='envelopes', type='asset', registry='derived', default='',
                description=('Required derived control asset ID.' if required else
                             'Derived control asset ID; empty uses input analysis.'), unit=None)


def validate(p):
    if p['lo_hz'] >= p['hi_hz']:
        raise ParamError('lo_hz must be below hi_hz')


def centers(p, sr):
    validate(p)
    if p['hi_hz'] >= .49*sr:
        raise ParamError('hi_hz must be below .49*sr')
    return np.geomspace(p['lo_hz'], p['hi_hz'], p['bands'])


def filter_band(x, sr, hz, q):
    # Cascade identical two-pole constant-peak bandpasses: four poles total.
    b, a = signal.iirpeak(hz, q, fs=sr)
    return signal.lfilter(b, a, signal.lfilter(b, a, x, axis=0), axis=0)


def analyze(x, sr, p):
    from mankomix.dspx.bb.dynamics import envelope
    bands = []
    for f in centers(p, sr):
        rectified = np.abs(filter_band(x, sr, f, p['band_q']))
        # Suppress the rectified carrier cycle before asymmetric ballistics.
        # Otherwise different rise/fall coefficients bias both the settled
        # level and the measured attack time (even for a stationary sine).
        window = max(1, round(sr/f))
        averaged = signal.lfilter(np.ones(window)/window, [1], rectified, axis=0)
        bands.append(envelope(averaged, sr, p['attack_ms'], p['release_ms']))
    return np.stack(bands, axis=1)


def resolve_control(asset_id, frames, sr, p):
    from mankomix.dspx.assets import resolve
    record = resolve('derived', asset_id)
    if not isinstance(record, dict) or record.get('kind') != 'control':
        raise ParamError('envelopes must refer to a control asset')
    try:
        values = np.asarray(record['values'], dtype=np.float64)
        hop, origin = float(record.get('hop_s', .005)), float(record.get('origin_s', 0))
    except (KeyError, TypeError, ValueError):
        raise ParamError('invalid control asset payload') from None
    if values.ndim == 2:
        values = values[:, :, None]
    if (values.ndim != 3 or not len(values) or values.shape[1] != p['bands'] or values.shape[2] not in (1, 2)
            or not np.isfinite(values).all() or np.any(values < 0) or not np.isfinite(hop) or hop <= 0
            or not np.isfinite(origin) or origin < 0):
        raise ParamError('invalid envelope dimensions, times or amplitudes')
    frequencies = centers(p, sr)
    if 'centers_hz' in record and not np.allclose(record['centers_hz'], frequencies, rtol=1e-9, atol=0):
        raise ParamError('control band layout differs from processor')
    times = origin+np.arange(len(values))*hop
    out = np.empty((frames, p['bands'], values.shape[2]))
    for b in range(p['bands']):
        for c in range(values.shape[2]):
            out[:, b, c] = np.interp(np.arange(frames)/sr, times, values[:, b, c], left=0, right=values[-1, b, c])
    return out


def synthesize(x, sr, p, envelopes):
    freqs = centers(p, sr)
    e = np.asarray(envelopes)
    if e.shape[2] not in (1, x.shape[1]):
        raise ParamError('control channel count does not match input')
    out = np.zeros_like(x)
    logf = np.log2(freqs)
    for b, f in enumerate(freqs):
        # Shift envelope positions, retaining synthesis centers.
        target = logf[b]-p.get('formant_shift', 0)/12
        if target < logf[0]-1e-12 or target > logf[-1]+1e-12:
            continue
        ix = min(len(freqs)-2, max(0, int(np.searchsorted(logf, target)-1)))
        u = np.clip((target-logf[ix])/(logf[ix+1]-logf[ix]), 0, 1)
        env = e[:, ix]*(1-u)+e[:, ix+1]*u
        out += filter_band(x, sr, f, p['band_q'])*env
    return out


def carrier(frames, sr, p, seed=0):
    """Additive bandlimited oscillator; phase integrates step-held MIDI notes."""
    notes = p['notes']
    curves = p['notes_curve']
    samples = np.arange(frames)
    out = np.zeros(frames)
    pitches = [np.full(frames, n) for n in notes]
    if curves:
        knots = np.rint(np.asarray(curves)[:, 0]*sr).astype(np.int64)
        ix = np.clip(np.searchsorted(knots, samples, side='right')-1, 0, len(knots)-1)
        pitches = [np.asarray(curves)[ix, 1]]
    for midi in pitches:
        freq = p['a4_hz']*2**((midi-69)/12)
        phase = np.r_[0, np.cumsum(freq[:-1]/sr)]
        for h in range(1, int(.45*sr/max(float(freq.min()), 1))+1):
            if p['carrier'] == 'pulse' and h % 2 == 0:
                continue
            keep = h*freq <= .45*sr
            out += np.where(keep, np.sin(2*np.pi*h*phase)/h, 0)/len(pitches)
    noise = np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(seed), p['seed'], 80]))).standard_normal(frames)
    if p['carrier'] == 'noise':
        return noise[:, None]
    if p['carrier'] == 'saw_noise':
        out = .8*out+.2*noise
    return out[:, None]
