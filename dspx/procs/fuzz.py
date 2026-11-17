"""Two-stage asymmetric fuzz, independent generic transfer model."""
import numpy as np
from mankomix.dspx.params import _f, _e
from mankomix.dspx.bb import nonlinear as N

SPECS = [N.specification('fuzz', N.nl_params(60, 30, 8) + [
    _f('bias', None, -1, 1, .2, 'Operating point offset.'),
    _f('gate', '0..1', 0, 1, .2, 'Smooth input dead zone.'),
    _e('shape', ['soft', 'hard', 'octave'], 'hard', 'Second clipping stage.'),
    _f('tone_hz', 'Hz', 200, 20000, 3000, 'Output lowpass.'),
    _f('lowcut_hz', 'Hz', 0, 500, 60, 'Input highpass; zero bypasses.'),
    _f('input_z', '0..1', 0, 1, 0, 'Drive-linked input high frequency loss.')],
    'Two-stage generic asymmetric clipping with a smooth gate.', stages=['track', 'bus'], slot=None)]


def fuzz_curve(x, drive_db=30, bias=.2, gate=.2, shape='hard'):
    """Zero-anchored bias curve; gate threshold is .01*gate before gain.

    Gate is smoothstep from threshold to twice threshold, so a small input
    cannot be reopened by the large drive. It is applied after clipping.
    """
    g = 10**(drive_db/20)
    v = np.abs(x) if shape == 'octave' else x
    first = np.tanh(g*v+bias)-np.tanh(bias)
    shifted = 2*first+2*bias
    if shape == 'soft':
        wet = (np.tanh(shifted)-np.tanh(2*bias)) / 2
    else:
        wet = (np.clip(shifted, -1, 1)-np.clip(2*bias, -1, 1)) / 2
    threshold = .01*gate
    if threshold:
        u = np.clip((np.abs(x)-threshold)/threshold, 0, 1)
        wet *= u*u*(3-2*u)
    slope = (1-np.tanh(bias)**2)
    if shape == 'soft':
        slope *= 1-np.tanh(2*bias)**2
    return wet/(g*slope)


def fuzz(x, sr, p, *, seed=0):
    info = N.oversampling_info(p['oversample'])
    gain = p['output_db'] - (p['drive_db'] if p['auto_gain'] else 0)
    if p['drive_db'] == 0 or p['mix'] == 0:
        return N.mix_output(x, x, 0, gain), sr, info
    factor = int(p['oversample'])
    def process(u):
        u = N.filter_audio(u, sr*factor, p['lowcut_hz'], 'highpass')
        if p['input_z']:
            cutoff = 20000/(1+p['input_z']*p['drive_db']/6)
            u = N.filter_audio(u, sr*factor, cutoff)
        return fuzz_curve(u, p['drive_db'], p['bias'], p['gate'], p['shape'])
    wet = N.oversampled(x, factor, process)
    wet = N.filter_audio(N.dc_block(wet, sr), sr, p['tone_hz'])
    # The output LPF can introduce a finite-record residual after the blocker.
    if len(wet):
        wet -= np.mean(wet, axis=0)
    return N.mix_output(x, wet, p['mix'], gain), sr, dict(info, dc_blocker_hz=5, auto_gain_coefficient=1)


IMPLS = {'fuzz': fuzz}
