"""Absolute-grid sequencer with logarithmic glides and TPT SVF."""
import numpy as np
from mankomix.dspx.params import _f, _a, _e
from mankomix.dspx.bb.time_creative import definition, grid_params


def validate(p, *, resolve_tempo=False):
    from mankomix.dspx.bb.time_creative import validate_grid
    validate_grid(p, ('cutoff_oct', 'resonance_db', 'level_db'), resolve_tempo=resolve_tempo)


def controls(frames, sr, p):
    """Return per-sample (cutoff Hz, resonance dB, level dB)."""
    from mankomix.dspx.bb.time_creative import grid
    k, start, end = grid(frames, sr, p)
    def values(name, default):
        return np.asarray(p[name] or [default]*p['steps'])
    octs = values('cutoff_oct', 0)
    octave = np.empty(frames)
    glide = p['glide_ms']*sr/1000
    # Restart long glides from the attained value, preserving continuity when
    # a new step arrives before the preceding transition has finished.
    previous = float(octs[(k[0]-1) % p['steps']]) if frames else 0
    boundaries = np.r_[0, np.flatnonzero(np.diff(k))+1, frames]
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        target = octs[k[a] % p['steps']]
        u = np.ones(b-a) if not glide else np.clip((np.arange(a,b)-start[a])/glide, 0, 1)
        octave[a:b] = previous+(target-previous)*u
        fraction = 1 if not glide else min(1, (end[a]-start[a])/glide)
        previous += (target-previous)*fraction
    if p['env_decay_ms']:
        octave += p['env_oct']*np.exp(-(np.arange(frames)-start)/(p['env_decay_ms']*sr/1000))
    return (np.minimum(.45*sr, p['base_hz']*2**octave),
            values('resonance_db', 6)[k % p['steps']], values('level_db', 0)[k % p['steps']])


def filter_seq(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.time_creative import mix_active
    from mankomix.dspx.bb.svf import svf
    validate(p, resolve_tempo=True)
    if p['mix'] == 0:
        return x.copy(), sr, {}
    cutoff, resonance, level = controls(len(x), sr, p)
    driven = x if p['drive_db'] == 0 else np.tanh(x*10**(p['drive_db']/20))
    wet = svf(driven, sr, cutoff, resonance, p['filter'], int(p['slope_db_oct']))
    wet *= 10**(level[:, None]/20)
    return mix_active(x, wet, p, sr), sr, {'cutoff_min_hz': float(cutoff.min()) if len(x) else None,
                                         'cutoff_max_hz': float(cutoff.max()) if len(x) else None}


SPECS = [definition('filter_seq', grid_params()+[
    _a('cutoff_oct', 'oct', -5, 5, 64, [], 'Empty means zero in every step.'),
    _f('base_hz', 'Hz', 40, 12000, 800, 'Base falling -3 dB cutoff.'),
    _a('resonance_db', 'dB', 0, 24, 64, [], 'Empty means 6 dB.'),
    _a('level_db', 'dB', -60, 6, 64, [], 'Empty means zero.'),
    _e('filter', ['lowpass', 'bandpass', 'highpass', 'notch'], 'lowpass', 'SVF output.'),
    _e('slope_db_oct', [12, 24], 12, 'Filter slope.'),
    _f('glide_ms', 'ms', 0, 500, 10, 'Linear octave-domain transition time.'),
    _f('env_decay_ms', 'ms', 0, 2000, 0, 'Per-step exponential cutoff decay.'),
    _f('env_oct', 'oct', -4, 4, 0, 'Initial envelope excursion.'),
    _f('drive_db', 'dB', 0, 24, 0, 'Input tanh drive; zero bypasses saturation.'),
    _f('mix', None, 0, 1, 1, 'Wet proportion.')], implemented=True)]
IMPLS = {'filter_seq': filter_seq}
TIME_VARYING = {'filter_seq'}
CROSS_VALIDATE = {'filter_seq': validate}
