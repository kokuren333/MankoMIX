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
SPECS[0]['implemented'] = True


def fuzz_curve(x, drive_db=30, bias=.2, gate=.2, shape='hard'):
    """Zero-anchored bias curve; gate threshold is .01*gate**4 before gain.

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
    threshold = .01*gate**4
    if threshold:
        u = np.clip((np.abs(x)-threshold)/threshold, 0, 1)
        wet *= u*u*(3-2*u)
    slope = (1-np.tanh(bias)**2)
    if shape == 'soft':
        slope *= 1-np.tanh(2*bias)**2
    return wet/(g*slope)


def hard_fuzz_primitive(x, drive_db=30, bias=.2, shape='hard'):
    """Analytic integral of the ungated hard second stage (also octave)."""
    g = 10**(drive_db/20)
    tb = np.tanh(bias)
    offset = bias-tb
    lo = (np.arctanh(-.5-offset)-bias)/g
    hi = (np.arctanh(.5-offset)-bias)/g

    def integral(v):
        u = np.clip(v, lo, hi)
        return (N.tanh_primitive(g*u+bias)/g + offset*u
                -.5*np.minimum(v-lo, 0)+.5*np.maximum(v-hi, 0)
                -np.clip(bias, -.5, .5)*v)/(g*(1-tb*tb))

    if shape == 'octave':
        return np.sign(x)*(integral(np.abs(x))-integral(0))
    return integral(x)


def gated_fuzz_primitive(drive_db=30, bias=.2, gate=.2, shape='hard'):
    """Return a gate-aware integral: cubic quadrature locally, analytic tails.

    4096 fixed intervals cover the gate region, with its breakpoints and
    clipping knees inserted explicitly. Outside it, the ungated analytic
    primitive is exact. No audio-dependent fit or iterative solver is used.
    """
    from scipy.interpolate import CubicSpline
    threshold = .01*gate**4
    base = lambda v: hard_fuzz_primitive(v, drive_db, bias, shape)
    if threshold == 0:
        return base
    edge = 2*threshold
    g = 10**(drive_db/20)
    offset = bias-np.tanh(bias)
    knees = (np.arctanh(np.array([-.5, .5])-offset)-bias)/g
    if shape == 'octave':
        knees = np.concatenate([knees, -knees])
    nodes = np.unique(np.concatenate([np.linspace(-edge, edge, 4097),
        [-threshold, 0, threshold], knees[abs(knees) < edge]]))
    integral = CubicSpline(nodes, fuzz_curve(nodes, drive_db, bias, gate, shape)).antiderivative()
    left, right = float(base(-edge)), float(base(edge))
    total = float(integral(edge)-integral(-edge))
    origin = float(integral(-edge))

    def primitive(v):
        v = np.asarray(v)
        y = np.asarray(base(v)-np.where(v < 0, left, right-total)).copy()
        inside = abs(v) < edge
        y[inside] = integral(v[inside])-origin
        return y
    return primitive


def antialiased_fuzz_curve(x, drive_db=30, bias=.2, gate=.2, shape='hard'):
    """Centered ADAA of the complete gated hard/octave transfer curve."""
    curve = lambda v: fuzz_curve(v, drive_db, bias, gate, shape)
    if shape != 'soft':
        return N.centered_adaa1(x, curve,
            gated_fuzz_primitive(drive_db, bias, gate, shape))
    return curve(x)


def fuzz(x, sr, p, *, seed=0):
    """Render with an internal 4x quality multiplier, doubled per 15 dB >30."""
    factor = int(p['oversample'])*4*2**max(0, int(np.ceil((p['drive_db']-30)/15)))
    info = N.precision_oversampling_info(factor)
    info['oversample'] = p['oversample']
    gain = p['output_db'] - (p['drive_db'] if p['auto_gain'] else 0)
    if p['drive_db'] == 0 or p['mix'] == 0:
        return N.mix_output(x, x, 0, gain), sr, info
    def process(u):
        u = N.filter_audio(u, sr*factor, p['lowcut_hz'], 'highpass')
        if p['input_z']:
            cutoff = 20000/(1+p['input_z']*p['drive_db']/6)
            u = N.filter_audio(u, sr*factor, cutoff)
        return antialiased_fuzz_curve(u, p['drive_db'], p['bias'], p['gate'], p['shape'])
    wet = N.precision_oversampled(x, factor, process)
    wet = N.filter_audio(N.dc_block(wet, sr), sr, p['tone_hz'], order=3)
    # The output LPF can introduce a finite-record residual after the blocker.
    if len(wet):
        wet -= np.mean(wet, axis=0)
    return N.mix_output(x, wet, p['mix'], gain), sr, dict(info, dc_blocker_hz=5, auto_gain_coefficient=1)


IMPLS = {'fuzz': fuzz}
