"""Up to four parallel fixed-interval voices, each with causal feedback."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _f, _e, _b


def validate(p):
    count = len(p['semitones'])
    for key in ('cents', 'level_db', 'pan', 'delay_ms', 'feedback'):
        if p[key] and len(p[key]) != count:
            raise ParamError(key+' must be empty or match semitones length')
    if p['quality'] != 'fast' and any(p['feedback']):
        raise ParamError('feedback requires quality=fast')
    from mankomix.dspx.bb.delayline import feedback_limit
    for i in range(count):
        feedback = p['feedback'][i] if p['feedback'] else 0
        delay = p['delay_ms'][i] if p['delay_ms'] else 0
        level = p['level_db'][i] if p['level_db'] else -6
        if level <= -60 or not feedback:
            continue
        maximum = feedback_limit(delay+p['grain_ms'], 10.**(level/20))
        if feedback > maximum:
            raise ParamError('feedback/delay/grain combination exceeds the 60 s CT-8 decay bound')


def voices(p):
    """Resolve parallel arrays without mutating validated parameters."""
    validate(p)
    defaults = dict(cents=0, level_db=-6, pan=0, delay_ms=0, feedback=0)
    return [dict(semitones=interval, **{k: p[k][i] if p[k] else value
                                      for k, value in defaults.items()})
            for i, interval in enumerate(p['semitones'])]


def harmonizer(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.pitchtime import shift, fast_shift, latency_samples
    from mankomix.dspx.bb.delayline import fractional_delay
    resolved = voices(p)
    y = x.copy() if p['dry_db'] == 0 else x*10.**(p['dry_db']/20)
    for v in resolved:
        if v['level_db'] <= -60:
            continue
        if p['quality'] == 'fast':
            wet = fast_shift(x, sr, 2.**((v['semitones']+v['cents']/100)/12),
                             p['grain_ms'], v['delay_ms'], v['feedback'])
        else:
            wet = shift(x, sr, v['semitones'], v['cents'], p['quality'], formant=p['formant'])
            wet = fractional_delay(wet, v['delay_ms']*sr/1000)
        # Stereo balance with unity centre preserves voice level and dry bits.
        if wet.shape[1] == 2:
            wet *= [1-max(0., v['pan']), 1+min(0., v['pan'])]
        y += wet*10.**(v['level_db']/20)
    active = any(v['level_db'] > -60 and v['semitones']+v['cents']/100 != 0 for v in resolved)
    lookahead = latency_samples(sr, p['quality']) if active else 0
    return y, sr, {'quality': p['quality'], 'voices': resolved,
                     'latency_samples': lookahead, 'latency_compensated': True}


SPECS = [dict(type='harmonizer', description='Parallel interval voices with independent feedback.',
    stages=['track', 'bus'], master_slot=None, offline_only=False,
    backends=['reference'], implemented=False,
    realtime=dict(block_ok=False, latency_samples=0, allocates=True,
        latency_rule='Fast: 0; standard: 40 ms; high: 4096*sr/48000 samples. '
                     'Lookahead compensated internally; voice delays are musical delays.'),
    params=[
        _a('semitones', 'semitones', -24, 24, 4, [7], 'Intervals, up to four voices.'),
        _a('cents', 'cents', -100, 100, 4, [], 'Fine intervals; empty means zero.'),
        _a('level_db', 'dB', -60, 6, 4, [], 'Voice gains; empty means -6; -60 is mute.'),
        _a('pan', None, -1, 1, 4, [], 'Voice balance; empty means centre.'),
        _a('delay_ms', 'ms', 0, 1000, 4, [], 'Voice delay; empty means zero.'),
        _a('feedback', None, 0, .9, 4, [], 'Loop gain; empty means zero; fast only.'),
        _e('quality', ['fast', 'standard', 'high'], 'fast', 'Pitch algorithm.'),
        _f('grain_ms', 'ms', 10, 200, 40, 'Fast crossfade grain.'),
        _b('formant', False, 'Preserve envelope in standard/high.'),
        _f('dry_db', 'dB', -90, 6, 0, 'Independent dry gain.')])]
IMPLS = {'harmonizer': harmonizer}
CROSS_VALIDATE = {'harmonizer': validate}
