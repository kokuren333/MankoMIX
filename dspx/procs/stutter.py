"""Causal grid stutter: the initial capture is live, reverse starts on pass two."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _f, _e
from mankomix.dspx.bb.time_creative import definition, grid_params

ARRAYS = ('repeat', 'gate', 'level_db', 'pitch_semitones', 'reverse', 'pan')
REPEATS = (0, 1, 2, 3, 4, 6, 8, 12, 16, 32)


def validate(p, *, resolve_tempo=False):
    from mankomix.dspx.bb.time_creative import validate_grid
    validate_grid(p, ARRAYS, resolve_tempo=resolve_tempo)
    if any(v not in REPEATS for v in p['repeat']):
        raise ParamError('repeat entries must be one of 0,1,2,3,4,6,8,12,16,32')
    if any(v not in (0, 1) for v in p['reverse']):
        raise ParamError('reverse entries must be binary')


def stutter(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.time_creative import grid, mix_active, active_mask
    from mankomix.dspx.bb.creative_rack import repeat_step
    validate(p, resolve_tempo=True)
    stats = dict(first_pass='live forward; reverse and pitch apply from pass two',
                 latency_samples=0)
    if not len(x) or not any(p['repeat']) or p['mix'] == 0 or not np.any(active_mask(p, len(x), sr)):
        return x.copy(), sr, stats
    # Balance requires two sides. Centered mono and complete bypass retain mono;
    # an explicitly panned mono effect uses dual-mono dry for exact center unity.
    if x.shape[1] == 1 and any(p['pan']):
        x = np.repeat(x, 2, axis=1)
    k, starts, ends = grid(len(x), sr, p)
    wet = x.copy()
    defaults = dict(repeat=0, gate=1, level_db=0, pitch_semitones=0, reverse=0, pan=0)
    unique, first = np.unique(k, return_index=True)
    locations = dict(zip(unique.tolist(), first.tolist()))
    for step, at in zip(unique, first):
        if step < 0:
            continue
        start, end = int(starts[at]), int(ends[at])
        values = {name: p[name][step % p['steps']] if p[name] else default
                  for name, default in defaults.items()}
        count = int(values.pop('repeat'))
        if not count:
            continue
        source = start
        if p['hold_source'] == 'pattern':
            pattern = int(step-step % p['steps'])
            source = int(starts[locations[pattern]])
        wet[start:min(end, len(x))] = repeat_step(
            x, sr, start, end, count, source_start=source, **values,
            decay_db=p['decay_db'], fade_ms=p['fade_ms'])
    return mix_active(x, wet, p, sr), sr, stats


SPECS = [definition('stutter', grid_params()+[
    _a('repeat', None, 0, 32, 64, [], 'Empty means all zero; allowed subdivision counts only.'),
    _a('gate', None, 0, 1, 64, [], 'Empty means one.'),
    _a('level_db', 'dB', -60, 6, 64, [], 'Empty means zero.'),
    _a('pitch_semitones', 'semitones', -24, 24, 64, [], 'Playback pitch from pass two.'),
    _a('reverse', None, 0, 1, 64, [], 'Reverse from pass two.'),
    _a('pan', None, -1, 1, 64, [], 'Stereo balance; empty means centered.'),
    _f('decay_db', 'dB', 0, 24, 0, 'Attenuation per successive repeat.'),
    _e('hold_source', ['step', 'pattern'], 'step', 'Capture source origin.'),
    _f('fade_ms', 'ms', .2, 20, 2, 'Linear seam rise/fall time.'),
    _f('mix', None, 0, 1, 1, 'Wet fraction.')], implemented=True)]
TIME_VARYING = {'stutter'}
IMPLS = {'stutter': stutter}
CROSS_VALIDATE = {'stutter': validate}
