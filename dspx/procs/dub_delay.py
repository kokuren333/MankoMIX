"""Curve-controlled sends and gliding tape-style feedback echo."""
import numpy as np
from scipy import signal
from mankomix.dspx.params import _f


def curve_parameter(pid, lo, hi, limit, unit):
    return dict(id=pid, type='curve', unit=unit, x_unit='s', x_min=0, x_max=36000,
                y_min=lo, y_max=hi, max_points=limit, default=[],
                description='Absolute-time linear curve with constant endpoint extension.')


def cross_validate(p):
    from mankomix.dspx.bb.delayfx import validate_delay, duration
    maximum = max([v for _, v in p['time_curve']] or [1])
    validate_delay(p, longest=(duration(p)*maximum+p['stereo_offset_ms']), gain=10**(6/20))


def delay_samples(frames, sr, p, *, start_sample=0):
    from mankomix.dspx.bb.curves import sample_curve
    from mankomix.dspx.bb.delayfx import duration
    # Replay from zero if smoothing is active, retaining the intended initial time.
    count = frames+start_sample
    multiplier = sample_curve(p['time_curve'], count, sr) if p['time_curve'] else np.ones(count)
    target = duration(p)*sr/1000*multiplier
    if p['time_glide_ms'] and len(target):
        a = np.exp(-1/(p['time_glide_ms']*.001*sr))
        target, _ = signal.lfilter([1-a], [1, -a], target, zi=[a*duration(p)*sr/1000])
    return target[start_sample:, None] + np.array([0., p['stereo_offset_ms']*sr/1000])


def dub_delay(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.curves import sample_curve
    from mankomix.dspx.bb.delayfx import tape_wet, finish
    cross_validate(p)
    if not p['mix']:
        return finish(x, x, sr, p)
    gain = sample_curve(p['send'], len(x), sr) if p['send'] else np.zeros(len(x))
    # -90 dB is the explicitly closed send, not a finite leak.
    send = np.where(gain <= -90, 0., 10**(gain/20))
    source = np.repeat(x, 2, axis=1) if x.shape[1] == 1 and p['stereo_offset_ms'] else x
    source = source*send[:, None]
    wet = tape_wet(source, sr, p, lambda n, rate: delay_samples(n, rate, p)[:, :source.shape[1]], dub=True)
    return finish(x, wet, sr, p, dict(oversample=2 if p['drive_db'] else 1, send_closed_db=-90))


def _declarations():
    from mankomix.dspx.bb.delayfx import definition, dl_parameters
    return [definition('dub_delay', dl_parameters(feedback=dict(max=.98, default=.6),
                        highcut_hz=dict(default=3500), lowcut_hz=dict(default=200)) + [
        curve_parameter('send', -90, 6, 4096, 'dB'),
        _f('drive_db', 'dB', 0, 24, 6, 'Unity-small-signal loop saturation.'),
        _f('narrow', None, 0, 1, .5, 'Blend one and two loop EQ sections.'),
        _f('diffusion', None, 0, 1, .2, 'Two loop allpasses.'),
        _f('time_glide_ms', 'ms', 0, 2000, 0, 'Delay following time constant.'),
        curve_parameter('time_curve', .25, 4, 256, 'ratio'),
        _f('stereo_offset_ms', 'ms', 0, 30, 0, 'Extra right delay.')], implemented=True)]


SPECS = _declarations()
IMPLS = {'dub_delay': dub_delay}
CROSS_VALIDATE = {'dub_delay': cross_validate}
TIME_VARYING = {'dub_delay'}
