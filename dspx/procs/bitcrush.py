"""Absolute-grid sample reduction and quantization, deliberately no oversampling.

render_with_history(x, sr, p, seed=0, history=None) supports an excerpt by
replaying its prefix; the engine has no persistent streaming render API.
No fresh RNG is seeded at an excerpt boundary. PCG64 uses separate deterministic
streams for holding jitter and TPDF, parameter seed added to the engine seed.
"""
import numpy as np
from scipy import signal
from mankomix.dspx.params import _f, _e, _b, _i
from mankomix.dspx.bb import nonlinear as N

SPECS = [N.specification('bitcrush', [
    _f('bits', 'bit', 1, 24, 24, 'Real-valued bits; 24 bypasses quantization.'),
    _f('rate_hz', 'Hz', 100, 192000, 192000, 'Sampling clock; >=sr bypasses.'),
    _b('antialias', False, 'Lowpass before rate reduction.'),
    _e('hold', ['zoh', 'linear'], 'zoh', 'Reconstruction.'),
    _f('jitter', '0..1', 0, 1, 0, 'Bounded seeded clock-point jitter.'),
    _f('dither', '0..1', 0, 1, 0, 'TPDF amplitude in quantizer steps.'),
    _e('quantizer', ['midtread', 'midrise'], 'midtread', 'Quantizer topology.'),
    _f('mix', '0..1', 0, 1, 1, 'Wet/dry mix.'),
    _f('output_db', 'dB', -36, 12, 0, 'Output gain.'),
    _i('seed', None, 0, 65535, 0, 'Additional random seed.')],
    'Intentional sample-rate and amplitude resolution reduction.', stages=['track', 'bus'], slot=None)]
SPECS[0]['realtime']['latency_rule'] = 'Zero fixed delay; antialias lowpass retains frequency-dependent phase.'
SPECS[0]['silence_exception'] = 'bits<24 and quantizer=midrise emits a positive half step at zero input.'
SPECS[0]['implemented'] = True


def quantize(x, bits, quantizer='midtread', dither=0, seed=0):
    """round(x*L)/L with 2**bits intervals across bipolar full scale [-1,1]."""
    if bits >= 24:
        return x.copy()
    levels = 2.0**(bits-1)
    v = x*levels
    if dither:
        rng = np.random.Generator(np.random.PCG64(seed))
        draws = rng.random((*x.shape, 2))
        v = v+dither*(draws[..., 0]-draws[..., 1])
    return (np.floor(v)+.5)/levels if quantizer == 'midrise' else np.rint(v)/levels


def bitcrush(x, sr, p, *, seed=0):
    if not len(x) or p['mix'] == 0 or (p['bits'] == 24 and p['rate_hz'] >= sr):
        return N.mix_output(x, x, 0, p['output_db']), sr, {'latency_samples': 0}
    wet = x.copy()
    local_seed = (int(seed)+int(p['seed'])) % (1 << 63)
    if p['rate_hz'] < sr:
        if p['antialias']:
            # Explicit transition below the new Nyquist, 80 dB stopband.
            sos = signal.cheby2(12, 80, p['rate_hz']*.49, fs=sr, output='sos')
            wet = signal.sosfilt(sos, wet, axis=0)
        interval = sr/p['rate_hz']
        count = int(np.ceil(len(x)/interval))+2
        points = np.arange(count, dtype=np.float64)*interval
        if p['jitter']:
            rng = np.random.Generator(np.random.PCG64(local_seed ^ 0x43524C4B))
            points += (rng.random(count)-.5)*interval*.9*p['jitter']
            points[0] = 0
        points = np.rint(points).astype(np.int64)
        # interval>1 and jitter<one interval preserves strict time ordering.
        points = np.unique(np.maximum(points, 0))
        points = points[points < len(x)]
        positions = np.arange(len(x))
        if p['hold'] == 'linear':
            wet = np.column_stack([np.interp(positions, points, wet[points, ch]) for ch in range(x.shape[1])])
        else:
            wet = wet[points[np.searchsorted(points, positions, side='right')-1]]
    wet = quantize(wet, p['bits'], p['quantizer'], p['dither'], local_seed)
    return N.mix_output(x, wet, p['mix'], p['output_db']), sr, {
        'latency_samples': 0, 'quantizer_step': 2.0**(1-p['bits']) if p['bits'] < 24 else 0,
        'silence_exception': p['quantizer'] == 'midrise' and p['bits'] < 24,
        'intentional_aliasing': not p['antialias']}


def render_with_history(x, sr, p, *, seed=0, history=None):
    if history is None:
        return bitcrush(x, sr, p, seed=seed)
    y, rate, stats = bitcrush(np.concatenate([history, x]), sr, p, seed=seed)
    return y[len(history):], rate, stats


IMPLS = {'bitcrush': bitcrush}
