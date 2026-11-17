"""Artificial double tracking: independently wandering delay and voice level."""
import numpy as np

from mankomix.dspx.params import _f, _i, _e
from mankomix.dspx.bb.curves import lfo
from mankomix.dspx.bb.modulation import combined_seed, modulation_definition, bandlimited_walk
from mankomix.dspx.bb.delayline import fractional_delay, LoopFilter, spatial_stats


def voice_motion(frames, sr, p, voice=0, *, start_sample=0, seed=0):
    """Return (delay_samples, level_db) on the absolute clock for one voice."""
    clock = dict(rate_hz=p['wander_rate_hz'], start_sample=start_sample)
    key = combined_seed(seed, p)+voice*65537
    if p['wander_shape'] == 'random':
        wander = bandlimited_walk(frames, sr, p['wander_rate_hz'], start_sample=start_sample,
                                  seed=key, phase=.5*voice)
    else:
        wander = lfo(frames, sr, shape='sine', seed=key, phase=.5*voice, **clock)
    level = bandlimited_walk(frames, sr, p['wander_rate_hz'], start_sample=start_sample, seed=key+101)
    delay = np.maximum(0., p['delay_ms'] + p['wander_ms']*wander)*sr/1000
    return delay, level*p['level_wander_db']


def adt(x, sr, p, *, seed=0):
    stereo = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x
    spread = p['spread']
    # Linear balance keeps the near side at unity, with no endpoint gain jump.
    def pan(position):
        return np.array([1-max(0., position), 1+min(0., position)])
    dry_pan = pan(-spread if p['voices'] == 1 else 0)
    y = stereo*dry_pan
    extrema = []
    for voice in range(p['voices']):
        delay, level = voice_motion(len(x), sr, p, voice, seed=seed)
        wet = fractional_delay(stereo, np.broadcast_to(delay[:, None], stereo.shape), 'lagrange3')
        wet = LoopFilter(sr, 2, highcut=p['highcut_hz'])(wet)
        wet *= (10**((p['double_db']+level)/20))[:, None] / np.sqrt(p['voices'])
        position = spread if p['voices'] == 1 or voice else -spread
        gain = pan(position)
        y += wet*gain
        extrema.append([float(delay.min()) if len(delay) else None,
                        float(delay.max()) if len(delay) else None])
    stats = spatial_stats(y, sr, p['delay_ms'])
    stats.update(voice_delay_ranges_samples=extrema,
                 pitch_deviation_bound_ratio=2*np.pi*p['wander_rate_hz']*p['wander_ms']/1000)
    return y, sr, stats


SPECS = [modulation_definition('adt', [
    _f('delay_ms', 'ms', 5, 80, 30, 'Center delay.'),
    _f('wander_ms', 'ms', 0, 20, 4, 'Delay excursion.'),
    _f('wander_rate_hz', 'Hz', .05, 5, .4, 'Wander rate.'),
    _e('wander_shape', ['random', 'sine'], 'random', 'Delay motion waveform.'),
    _f('level_wander_db', 'dB', 0, 3, .5, 'Double level excursion.'),
    _i('voices', None, 1, 2, 1, 'Number of doubles.'),
    _f('spread', None, 0, 1, .7, 'Dry/double pan separation.'),
    _f('double_db', 'dB', -24, 6, -3, 'Double level.'),
    _f('highcut_hz', 'Hz', 0, 20000, 0, 'Double lowpass; zero bypasses.'),
    _i('seed', None, 0, 65535, 0, 'Deterministic parameter seed.')], channel=False, implemented=True)]
TIME_VARYING = {'adt'}
IMPLS = {'adt': adt}
