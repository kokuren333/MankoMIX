"""Apply a derived channel-vocoder control asset to one carrier input."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _i, _f
from mankomix.dspx.bb.time_creative import definition
from mankomix.dspx.bb.band_envelopes import asset_param


def band_envelope(x, sr, p, *, seed=0):
    from mankomix.dspx.bb import band_envelopes as B
    B.centers(p, sr)
    if p['mix'] == 0 or p['depth'] == 0:
        return x.copy(), sr, {}
    if not p['envelopes']:
        raise ParamError('band_envelope requires a nonempty control asset ID')
    env = B.resolve_control(p['envelopes'], len(x), sr, p)
    wet = B.synthesize(x, sr, p, env)
    amount = p['mix']*p['depth']
    y = wet if amount == 1 else x+amount*(wet-x)
    return y, sr, {'bands': p['bands'], 'envelopes': p['envelopes']}


SPECS = [definition('band_envelope', [asset_param(True),
    _i('bands', None, 4, 40, 16, 'Log-spaced analysis/synthesis bands.'),
    _f('lo_hz', 'Hz', 50, 500, 100, 'Lowest band center.'),
    _f('hi_hz', 'Hz', 2000, 16000, 8000, 'Highest band center.'),
    _f('band_q', None, 2, 20, 8, 'Four-pole bandpass Q.'),
    _f('formant_shift', 'semitones', -12, 12, 0, 'Envelope frequency shift.'),
    _f('depth', None, 0, 1, 1, 'Envelope depth; zero bypasses.'),
    _f('mix', None, 0, 1, 1, 'Wet proportion.')], implemented=True)]
TIME_VARYING = {'band_envelope'}
IMPLS = {'band_envelope': band_envelope}
