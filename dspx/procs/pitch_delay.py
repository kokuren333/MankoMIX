"""Dual-tap pitch / IIR single-sideband frequency translation in a delay loop."""
import numpy as np
from mankomix.dspx.params import _b, _e, _f


def cross_validate(p):
    from mankomix.dspx.bb.delayfx import validate_delay, duration
    extra = p['grain_ms'] if p['mode'] == 'pitch' and p['shift_in_loop'] and (p['shift_semitones'] or p['shift_cents'] or p['reverse']) else 0
    validate_delay(p, longest=duration(p)+extra)


def pitch_delay(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.delayline import DelayLine, LoopFilter
    from mankomix.dspx.bb.delayfx import duration, feedback_audio, finish
    from mankomix.dspx.bb.shiftloop import LoopShift
    cross_validate(p)
    if not p['mix'] or not len(x):
        return finish(x, x, sr, p)
    delay = duration(p)*sr/1000
    shifter = LoopShift(sr, x.shape[1], mode=p['mode'], semitones=p['shift_semitones'],
                        cents=p['shift_cents'], hz=p['shift_hz'], grain_ms=p['grain_ms'],
                        reverse=p['reverse'], highcut_hz=p['highcut_hz'])
    eq = LoopFilter(sr, x.shape[1], min(p['lowcut_hz'], .49*sr), p['highcut_hz'])
    if shifter.neutral or not p['shift_in_loop'] or not p['feedback']:
        wet = feedback_audio(x, delay, p['feedback'],
                             lambda: LoopFilter(sr, x.shape[1], min(p['lowcut_hz'], .49*sr), p['highcut_hz']),
                             method='sinc8')
        wet = eq(wet)
        if not shifter.neutral:
            wet = shifter.process(wet)
    else:
        # sinc8 feedback is causal above four samples. Smaller musical delays
        # retain their exact value through the existing full-context solver.
        if delay < 5 and delay != round(delay):
            from mankomix.dsp.errors import ParamError
            raise ParamError('active shift with fractional feedback requires time_ms * sr / 1000 >= 5 samples')
        chunks = []
        def loop(block):
            v = shifter.process(eq(block))
            chunks.append(v)
            return v
        DelayLine(max(1., delay), x.shape[1], 'sinc8').process(x, max(1., delay), p['feedback'], loop)
        wet = np.concatenate(chunks)
    return finish(x, wet, sr, p, dict(mode=p['mode'], shift_in_loop=p['shift_in_loop'],
                                    shifter_gain_bound=1., group_delay_compensated=False,
                                    safety_highcut_hz=p['highcut_hz'] or .45*sr))


def _specs():
    from mankomix.dspx.bb.delayfx import definition, dl_parameters
    return [definition('pitch_delay', dl_parameters()+[
        _e('mode', ['pitch', 'freq'], 'pitch', 'Pitch ratio or single-sideband frequency shift.'),
        _f('shift_semitones', 'semitones', -24, 24, 12, 'Pitch shift per traversal.'),
        _f('shift_cents', 'cents', -100, 100, 0, 'Fine pitch added to semitones.'),
        _f('shift_hz', 'Hz', -2000, 2000, 50, 'Signed frequency translation.'),
        _f('grain_ms', 'ms', 10, 500, 100, 'Two-tap grain length.'),
        _b('reverse', False, 'Reverse the pitch grains.'),
        _b('shift_in_loop', True, 'Apply the shift on every traversal.')], implemented=True)]


SPECS = _specs()
IMPLS = {'pitch_delay': pitch_delay}
CROSS_VALIDATE = {'pitch_delay': cross_validate}
TIME_VARYING = {'pitch_delay'}
