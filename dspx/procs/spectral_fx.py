"""T09-02 single-operation spectral effect, on the unchanged BB-06 grid.

Shift/scale use interpolated complex bins and analytic phase rotation for
each destination frequency. Amplitudes blend in dB; transformed phase is
used for every nonzero amount. Random events use PCG64 absolute event ids.
"""
import numpy as np
from scipy import signal
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _i, _e, _b


def validate(p):
    if p['lo_hz'] >= p['hi_hz']:
        raise ParamError('spectral_fx: lo_hz must be below hi_hz')


def latency_samples(sr, p):
    from mankomix.dspx.bb.stft import window_samples
    return window_samples(p['window'], sr)


def event_rng(seed, parameter_seed, event):
    """Independent PCG64 stream per absolute frame/permutation event."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(
        [int(seed) & ((1 << 64)-1), int(parameter_seed), int(event)])))


def transform(a, p, *, seed=0):
    """Return transformed complex spectra; bins outside the band are exact."""
    from mankomix.dspx.bb.stft import smooth_frequency, band_weights
    z = a.spectra
    mag, phase = abs(z), np.angle(z)
    outmag, outphase = mag.copy(), phase.copy()
    f, time = a.frequencies_hz, a.samples/a.sr
    op = p['op']
    inside = (f >= p['lo_hz']) & (f <= p['hi_hz'])
    if op == 'blur' and len(z):
        alpha = np.exp(-a.hop_samples/(a.sr*p['time_ms']*.001))
        outmag, _ = signal.lfilter([1-alpha], [1, -alpha], mag, axis=0,
                                   zi=np.zeros_like(mag[:1]))
    elif op == 'gate':
        threshold = np.max(mag[:, inside], axis=1, keepdims=True, initial=0)*10**(p['threshold_db']/20)
        keep = mag >= threshold
        if p['invert']:
            keep = ~keep
        outmag = np.where(keep, mag, 0)
    elif op in ('shift', 'scale'):
        source = f-p['shift_hz'] if op == 'shift' else f/p['ratio']
        coord = source/(f[1]-f[0])
        lower = np.floor(coord).astype(int)
        frac = coord-lower
        valid = (coord >= 0) & (coord <= len(f)-1)
        lo = np.clip(lower, 0, len(f)-1)
        hi = np.clip(lower+1, 0, len(f)-1)
        mapped = z[:, lo]*(1-frac)[None, :, None]+z[:, hi]*frac[None, :, None]
        mapped[:, ~valid] = 0
        outmag = abs(mapped)
        outphase = np.angle(mapped)+2*np.pi*time[:, None, None]*(f-source)[None, :, None]
    elif op == 'scramble':
        bins = np.flatnonzero(inside)
        width = max(1, round(p['block_hz']/(f[1]-f[0])))
        last = None
        for t in range(len(z)):
            event = int(np.floor(time[t]*p['rate_hz'])) if p['rate_hz'] else 0
            if event != last:
                rng = event_rng(seed, p['seed'], event)
                permutation = bins.copy()
                for j in range(0, len(bins), width):
                    permutation[j:j+width] = rng.permutation(bins[j:j+width])
                last = event
            outmag[t, bins] = mag[t, permutation]
            outphase[t, bins] = phase[t, permutation]
    elif op == 'contrast':
        reference = np.max(mag[:, inside], axis=1, keepdims=True, initial=0)
        outmag = reference*(mag/np.maximum(reference, 1e-30))**p['exponent']
    elif op == 'phase':
        if p['phase_mode'] == 'zero':
            outphase.fill(0)
        elif p['phase_mode'] == 'hold' and len(z):
            outphase[:] = phase[:1]
        else:
            for t in range(len(z)):
                outphase[t] = event_rng(seed, p['seed'], t).uniform(-np.pi, np.pi, z.shape[1:])
    elif op == 'smear_freq':
        outmag = smooth_frequency(mag, f, p['width_oct'])
    weight = p['amount']*band_weights(f, p['lo_hz'], p['hi_hz'])
    # A zero target remains exactly zero at full amount (gate's true silence).
    blended = np.exp((1-weight[None, :, None])*np.log(np.maximum(mag, 1e-30))
                     +weight[None, :, None]*np.log(np.maximum(outmag, 1e-30)))
    blended = np.where((outmag == 0) & (weight[None, :, None] == 1), 0, blended)
    blended = np.where((mag == 0) & (outmag == 0), 0, blended)
    transformed = blended*np.exp(1j*outphase)
    # Edge weights also interpolate the phase displacement on the unit circle.
    # Full interior weight uses the transformed phase as required.
    edge = (weight > 0) & (weight < p['amount'])
    if np.any(edge):
        delta = np.angle(np.exp(1j*(outphase[:, edge]-phase[:, edge])))
        transformed[:, edge] = blended[:, edge]*np.exp(1j*(phase[:, edge]
                                  +delta*(weight[edge]/p['amount'])[None, :, None]))
    out = z.copy()
    out[:, weight > 0] = transformed[:, weight > 0]
    # Real-valued inverse FFT endpoints cannot carry arbitrary complex phase.
    out[:, 0] = out[:, 0].real
    if len(a.window) % 2 == 0:
        out[:, -1] = out[:, -1].real
    return out


def spectral_fx(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft
    validate(p)
    n = latency_samples(sr, p)
    y = x.copy()
    if p['amount'] and p['mix'] and len(x):
        a = stft.analyze(x, sr, window=n)
        correction = stft.synthesize(a, transform(a, p, seed=seed)-a.spectra)
        y += p['mix']*correction
    if not compensate:
        y = stft.delay_output(y, n)
    return y, sr, dict(latency_samples=n, latency_compensated=compensate, op=p['op'])


SPECS = [dict(type='spectral_fx', implemented=False,
    description='Eight deterministic single-operation spectral effects.',
    stages=['track', 'bus'], master_slot=None, offline_only=False, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples='window_scaled', allocates=True),
    params=[
        _e('window', [1024, 2048, 4096], 2048, '48 kHz analysis size.'),
        _f('lo_hz', 'Hz', 20, 20000, 20, 'Lower effect edge.'),
        _f('hi_hz', 'Hz', 20, 24000, 20000, 'Upper effect edge.'),
        _f('mix', None, 0, 1, 1, 'Wet fraction.'),
        _e('op', ['blur', 'gate', 'shift', 'scale', 'scramble', 'contrast', 'phase', 'smear_freq'], 'blur', 'One operation per item.'),
        _f('amount', None, 0, 1, 0, 'dB-amplitude blend; zero bypasses.'),
        _i('seed', None, 0, 65535, 0, 'Parameter seed.'),
        _f('time_ms', 'ms', 10, 5000, 200, 'Blur amplitude tau at amount one.'),
        _f('threshold_db', 'dB', -80, 0, -30, 'Gate threshold relative to frame maximum.'),
        _b('invert', False, 'Keep the weak bins.'),
        _f('shift_hz', 'Hz', -4000, 4000, 100, 'Frequency translation.'),
        _f('ratio', None, .25, 4, 1.5, 'Frequency scale ratio.'),
        _f('block_hz', 'Hz', 20, 2000, 200, 'Permutation block width.'),
        _f('rate_hz', 'Hz', 0, 50, 0, 'Permutation redraw rate; zero holds.'),
        _f('exponent', None, .25, 4, 2, 'Contrast exponent.'),
        _e('phase_mode', ['zero', 'random', 'hold'], 'zero', 'Replacement phase.'),
        _f('width_oct', 'oct', .05, 2, .3, 'Frequency smear width.')])]
IMPLS = {'spectral_fx': spectral_fx}
TIME_VARYING = {'spectral_fx'}
CROSS_VALIDATE = {'spectral_fx': validate}
