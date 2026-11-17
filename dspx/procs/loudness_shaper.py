"""The exact polynomial family specified in T07-07; no measured curve fit."""
import numpy as np
from mankomix.dspx.params import _f, _b, _e
from mankomix.dspx.bb import nonlinear as N, crossover as C

SPECS = [N.specification('loudness_shaper', [
    _f('effect', '0..1', 0, 1, 0, 'Polynomial strength; zero bypasses all stages.'),
    _f('curve', '0..1', 0, 1, .5, 'Second/third-order family blend.'),
    _f('input_db', 'dB', -12, 12, 0, 'Input gain.'),
    _b('clip', True, 'Clip before the polynomial; false extends linearly.'),
    _b('band_split', False, 'Linear-phase 240/2400 Hz three-band shaping.'),
    _f('output_db', 'dB', -12, 0, 0, 'Output gain.'),
    _e('oversample', [1, 2, 4, 8], 4, 'Oversampling factor.', unit='x')],
    'Monotone odd polynomial loudness shaping.', slot=5)]


def loudness_shaper(x, sr, p, *, seed=0):
    info = N.oversampling_info(p['oversample'])
    if p['effect'] == 0:
        return x.copy(), sr, info
    u = x*10**(p['input_db']/20)
    bands, meta = C.split_bands(u, sr, [240, 2400], 'linear') if p['band_split'] else ([u], {})
    ys = [N.oversampled(b, p['oversample'],
          lambda v: N.loudness_curve(v, p['effect'], p['curve'], p['clip'])) for b in bands]
    y = C.recombine_bands(ys)*10**(p['output_db']/20)
    return y, sr, dict(info, crossover_latency_samples=meta.get('latency_samples', 0),
                      true_peak_guaranteed=False)


IMPLS = {'loudness_shaper': loudness_shaper}
