"""TV FDN with parallel bounded dual-tap pitch feedback."""
from mankomix.dspx.params import _f


def reverb_shimmer(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.shimmer import process_shimmer
    return process_shimmer(x, sr, p, seed=seed)


def _specs():
    from mankomix.dspx.bb.reverb import definition, rv_params
    return [definition('reverb_shimmer', rv_params(.5, 30, 6)+[
        _f('shift_semitones', 'semitones', -12, 24, 12, 'Pitch added in parallel feedback.'),
        _f('shimmer', None, 0, 1, .5, 'Shifted fraction of the feedback.'),
        _f('grain_ms', 'ms', 20, 200, 80, 'Dual-tap grain length.'),
        _f('diffusion', None, 0, 1, .8, 'Allpass input diffusion.'),
        _f('damping_hz', 'Hz', 1000, 20000, 7000, 'Feedback high-band absorption and shift safety edge.'),
        _f('mod_depth', None, 0, 1, .2, 'FDN delay modulation depth.')], implemented=False)]


SPECS = _specs()
IMPLS = {'reverb_shimmer': reverb_shimmer}
TIME_VARYING = {'reverb_shimmer'}
