"""BB-02 multiband saturation, numerically identical to the original curves."""
import math
import numpy as np
from mankomix.dspx.params import _a, _e, _f
from mankomix.dspx.bb import nonlinear as N, crossover as C

PARAMS = C.mb_params()
PARAMS[1]['default'] = 'linear'
SPECS = [N.specification('mb_saturator', PARAMS + [
    _a('drive_db', 'dB', 0, 24, 6, [], 'Empty means zero per band.'),
    _a('level_db', 'dB', -24, 12, 6, [], 'Empty means zero per band.'),
    _a('mix', '0..1', 0, 1, 6, [], 'Empty means one per band.'),
    _e('mode', ['tanh', 'asymmetric'], 'tanh', 'Same curves as saturator; asymmetry fixed at its default .3.'),
    _e('oversample', [1, 2, 4, 8], 4, 'Oversampling factor.', unit='x'),
    _f('output_db', 'dB', -36, 12, 0, 'Output gain.')],
    'Independent saturation before band summation; generated harmonics are not re-split.')]


def validate(p):
    C.validate_mb(p)
    C.expand_band_params(p, dict(drive_db=0, level_db=0, mix=1))


def saturate_band(x, sr, drive_db, mode, factor):
    """Clone original saturator equations, including its causal DC blocker."""
    g = 10.0**(drive_db/20.0)
    if mode == 'tanh':
        curve = lambda u: np.tanh(g*u)/g
    else:
        bias = .5*.3
        tb = math.tanh(bias)
        slope = 1.0-tb*tb
        curve = lambda u: (np.tanh(g*u+bias)-tb)/(g*slope)
    wet = N.oversampled(x, factor, curve)
    if mode == 'asymmetric':
        # Preserve the original arithmetic for the <=-120 dBFS null test.
        from scipy import signal
        b, a = signal.butter(1, 5.0, btype='highpass', fs=sr)
        wet = signal.lfilter(b, a, wet, axis=0)
    return wet


def mb_saturator(x, sr, p, *, seed=0):
    C.validate_mb(p, sr)
    bp = C.expand_band_params(p, dict(drive_db=0, level_db=0, mix=1))
    info = N.oversampling_info(p['oversample'])
    if not any(bp['drive_db']):
        return N.mix_output(x, x, 0, p['output_db']), sr, info
    bands, meta = C.split_mb(x, sr, p)
    for i, band in enumerate(bands):
        wet = saturate_band(band, sr, bp['drive_db'][i], p['mode'], p['oversample']) if bp['drive_db'][i] else band
        bands[i] = N.mix_output(band, wet, bp['mix'][i], bp['level_db'][i])
    y = C.recombine_bands(bands)
    return N.mix_output(y, y, 1, p['output_db']), sr, dict(info,
        crossover_latency_samples=meta['latency_samples'], harmonics_resplit=False)


IMPLS = {'mb_saturator': mb_saturator}
CROSS_VALIDATE = {'mb_saturator': validate}
