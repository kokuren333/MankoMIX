"""Tape echo with shared absolute-clock wobble and a 2x nonlinear loop."""
import numpy as np
from mankomix.dspx.params import _f


def cross_validate(p):
    from mankomix.dspx.bb.delayfx import duration, validate_delay
    validate_delay(p, longest=duration(p)*(1+(p['wow_depth']+p['flutter_depth'])/100))


def delay_samples(frames, sr, p, *, seed=0, start_sample=0):
    """Tape depths are delay percentages; shared wobble supplies unit waves.

    Request each component separately so its rate does not change its depth.
    The generator's speed waveform, not its integrated displacement, is used.
    """
    from mankomix.dspx.bb.wobble import wobble_from_params
    from mankomix.dspx.bb.delayfx import duration
    q = dict(p, wow_depth=p['wow_depth'], flutter_depth=0, stereo_link=1)
    _, wow = wobble_from_params(frames, sr, q, seed=seed, start_sample=start_sample)
    q.update(wow_depth=0, flutter_depth=p['flutter_depth'])
    _, flutter = wobble_from_params(frames, sr, q, seed=seed, start_sample=start_sample)
    return duration(p)*sr/1000*(1+wow+flutter)


def tape_delay(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.delayfx import tape_wet, finish
    cross_validate(p)
    if not p['mix']:
        return finish(x, x, sr, p)
    wet = tape_wet(x, sr, p, lambda n, rate: delay_samples(n, rate, p, seed=seed))
    return finish(x, wet, sr, p, dict(oversample=2 if p['drive_db'] else 1,
                                    head_peak_normalization_db=-p['head_bump_db']))


def _declarations():
    from mankomix.dspx.bb.delayfx import definition, dl_parameters
    return [definition('tape_delay', dl_parameters(highcut_hz=dict(default=5000), lowcut_hz=dict(default=80)) + [
        _f('wow_depth', '%', 0, 2, .2, 'Peak delay percentage deviation.'),
        _f('wow_rate_hz', 'Hz', .1, 4, .8, 'Wow rate.'),
        _f('flutter_depth', '%', 0, .5, .05, 'Peak delay percentage deviation.'),
        _f('flutter_rate_hz', 'Hz', 4, 30, 9, 'Flutter rate.'),
        _f('drift', None, 0, 1, .3, 'Irregular fraction of wow.'),
        _f('drive_db', 'dB', 0, 24, 6, 'Unity-small-signal loop saturation.'),
        _f('head_bump_db', 'dB', 0, 6, 2, 'Relative head resonance at 100 Hz.')], implemented=True)]


SPECS = _declarations()
IMPLS = {'tape_delay': tape_delay}
CROSS_VALIDATE = {'tape_delay': cross_validate}
TIME_VARYING = {'tape_delay'}
