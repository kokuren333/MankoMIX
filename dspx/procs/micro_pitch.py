"""Two slightly detuned delay voices, without waveform phase alignment."""
import numpy as np
from mankomix.dspx.params import _f, _e


def micro_pitch(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.pitchtime import fast_shift
    from mankomix.dspx.bb.delayline import spatial_stats
    if p['mix'] == 0:
        return x.copy(), sr, {'latency_samples': 0}
    stereo = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x
    source = np.repeat(stereo.mean(axis=1, keepdims=True), 2, axis=1) if p['input'] == 'mono_sum' else stereo
    wet = np.column_stack([fast_shift(source[:, i:i+1], sr, 2.**(p[side+'_cents']/1200),
        p['grain_ms'], p[side+'_delay_ms'], p['feedback'], p['highcut_hz'])[:, 0]
        for i, side in enumerate(('left', 'right'))])
    y = wet if p['mix'] == 1 else stereo+(wet-stereo)*p['mix']
    return y, sr, spatial_stats(y, sr)


SPECS = [dict(type='micro_pitch', description='Two detuned rotating delay voices.',
    stages=['track', 'bus'], master_slot=None, offline_only=False,
    backends=['reference'], implemented=True,
    realtime=dict(block_ok=False, latency_samples=0, allocates=True),
    params=[
        _f('left_cents', 'cents', -50, 50, -9, 'Left detuning.'),
        _f('right_cents', 'cents', -50, 50, 9, 'Right detuning.'),
        _f('left_delay_ms', 'ms', 0, 100, 10, 'Left delay.'),
        _f('right_delay_ms', 'ms', 0, 100, 15, 'Right delay.'),
        _f('grain_ms', 'ms', 10, 80, 30, 'Crossfade grain.'),
        _f('feedback', None, 0, .5, 0, 'Per-voice feedback.'),
        _f('highcut_hz', 'Hz', 0, 20000, 0, 'Wet/loop lowpass; zero bypasses.'),
        _e('input', ['mono_sum', 'stereo'], 'mono_sum', 'Input routing.'),
        _f('mix', None, 0, 1, .3, 'Wet proportion.')])]
IMPLS = {'micro_pitch': micro_pitch}
