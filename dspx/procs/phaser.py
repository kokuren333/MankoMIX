"""First-order TPT allpass cascade with explicitly delayed feedback."""
import numpy as np
from scipy import signal

from mankomix.dspx.params import _f, _b, _e
from mankomix.dspx.bb.modulation import mod_params, mod_lfo, mod_rate, modulation_definition, validate_mod
from mankomix.dspx.bb.delayline import spatial_stats


def corner_frequencies(frames, sr, p, channels=1, *, start_sample=0, seed=0):
    wave = mod_lfo(frames, sr, p, channels, start_sample=start_sample, seed=seed)
    center = p['center_hz'] * 2**(wave*p['depth']*p['range_oct']/2)
    offsets = np.linspace(-.5, .5, int(p['stages'])) * p['spread'] * p['range_oct']
    return np.clip(center[..., None] * 2**offsets, 1., sr*.49)


def phaser(x, sr, p, *, seed=0):
    mod_rate(p)
    if not p['mix']:
        return x.copy(), sr, {'latency_samples': 0}
    constant = not p['depth'] or not p['range_oct']
    corners = corner_frequencies(1 if constant else len(x), sr, p, x.shape[1], seed=seed)
    stages, feedback = int(p['stages']), p['feedback']
    wet = np.empty_like(x)
    if constant and not feedback:
        # The identical TPT transfer, evaluated by an LTI recursion when static.
        for c in range(x.shape[1]):
            sections = []
            for freq in (corners[0, c] if len(x) else np.full(stages, p['center_hz'])):
                g = np.tan(np.pi*freq/sr)
                k = (g-1)/(g+1)
                sections.append([k, 1, 0, 1, k, 0])
            wet[:, c] = signal.sosfilt(sections, x[:, c])
    else:
        gain = np.tan(np.pi*corners/sr)
        gain /= 1+gain
        for c in range(x.shape[1]):
            state = [0.]*stages
            previous = 0.
            coefficients = gain[:, c, :].tolist()
            rendered = []
            for n, sample in enumerate(x[:, c].tolist()):
                value = sample + feedback*previous
                row = coefficients[0 if constant else n]
                for j in range(stages):
                    v = (value-state[j])*row[j]
                    low = v+state[j]
                    state[j] = low+v
                    value = 2*low-value
                previous = value
                rendered.append(value)
            wet[:, c] = rendered
    y = (1-p['mix'])*x + p['mix']*(-wet if p['invert'] else wet)
    stats = spatial_stats(y, sr)
    stats.update(corner_min_hz=float(corners.min()) if corners.size else None,
                 corner_max_hz=float(corners.max()) if corners.size else None,
                 feedback_delay_samples=1)
    return y, sr, stats


SPECS = [modulation_definition('phaser', mod_params(.4, .7, .1, .5) + [
    _e('stages', [2, 4, 6, 8, 12], 4, 'Number of allpass sections.'),
    _f('center_hz', 'Hz', 100, 8000, 800, 'Geometric sweep center.'),
    _f('range_oct', 'oct', 0, 6, 3, 'Full sweep width at unit depth.'),
    _f('feedback', None, -.95, .95, .3, 'Signed one-sample-delayed feedback.'),
    _f('spread', None, 0, 1, 0, 'Section corner spread.'),
    _b('invert', False, 'Invert wet polarity.')], implemented=True)]
TIME_VARYING = {'phaser'}
IMPLS = {'phaser': phaser}
CROSS_VALIDATE = {'phaser': validate_mod}
