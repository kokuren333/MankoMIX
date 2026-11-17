"""Four scattered TPT allpasses driven by an asymmetric thermal light model.

Structural reference: Darabundit et al., DAFx-19, sections 2.2/3,
https://www.dafx.de/paper-archive/2019/DAFx2019_paper_31.pdf .
This is the specification's ideal allpass abstraction, not the paper's
measured unbalanced circuit. Thermal constants are user parameters. Normalized
capacity ratios and power-law sensitivities below are original design choices.
"""
import numpy as np
from mankomix.dspx.params import _e, _f


def lamp_response(target, sr, up_ms, down_ms):
    """Zero-state light output; separate 63.212 percent rise/fall constants."""
    from mankomix.dspx.bb.dynamics import smooth_python, coef
    return smooth_python(np.asarray(target), coef(up_ms, sr), coef(down_ms, sr))


def lamp_motion(frames, sr, p, channels=1, *, seed=0, start_sample=0):
    """Replay the thermal control from zero, returning the requested excerpt."""
    from mankomix.dspx.bb.modulation import mod_lfo
    if p['depth'] == 0:
        return np.full((frames, channels), .5)
    wave = mod_lfo(frames+start_sample, sr, p, channels, seed=seed)
    target = .5+.5*p['depth']*wave
    return np.column_stack([lamp_response(target[:, ch], sr, p['lamp_ms_up'],
                                         p['lamp_ms_down'])[start_sample:] for ch in range(channels)])


def corner_frequencies(frames, sr, p, channels=1, *, seed=0, start_sample=0):
    light = lamp_motion(frames, sr, p, channels, seed=seed, start_sample=start_sample)
    capacities = np.array([1., 15., 220., 4700.])
    sensitivity = 1+p['asym']*np.array([.7, .9, 1.1, 1.3])
    # f proportional to conductance, R proportional to brightness**(-gamma).
    factor = (np.maximum(light[..., None], 1e-9)/.5)**sensitivity
    return np.clip(12000/capacities*factor, 1., .45*sr)


def vibe(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.modulation import validate_mod
    from mankomix.dspx.bb.motion import allpass_cascade
    from mankomix.dspx.bb.nonlinear import oversampled
    from mankomix.dspx.bb.delayline import spatial_stats
    validate_mod(p)
    source = x
    if p['drive_db']:
        gain = 10**(p['drive_db']/20)
        source = oversampled(x, 4, lambda v: np.tanh(gain*v)/gain)
    corners = corner_frequencies(1 if p['depth'] == 0 else len(x), sr, p, x.shape[1], seed=seed)
    wet = allpass_cascade(source, sr, corners)
    y = (source+wet)/2 if p['mode'] == 'chorus' else wet
    if p['output_db']:
        y = y*10**(p['output_db']/20)
    return y, sr, spatial_stats(y, sr)


def _params():
    from mankomix.dspx.bb.modulation import mod_params
    common = mod_params(3, .7, 0, None)
    next(v for v in common if v['id'] == 'rate_hz').update(min=.3, max=12)
    return common + [_e('mode', ['chorus', 'vibrato'], 'chorus', 'Equal dry/wet or allpass only.'),
                     _f('lamp_ms_up', 'ms', 5, 100, 20, 'Light heating time constant.'),
                     _f('lamp_ms_down', 'ms', 20, 400, 120, 'Light cooling time constant.'),
                     _f('asym', None, 0, 1, .5, 'Photoconductor power-law sensitivity.'),
                     _f('drive_db', 'dB', 0, 12, 0, 'Front-end saturation; zero is linear.'),
                     _f('output_db', 'dB', -12, 12, 0, 'Output level.')]


SPECS = [dict(type='vibe', implemented=False, description='Thermal-light-controlled four-section scattered allpass modulation.',
              params=_params(), stages=['track', 'bus'], master_slot=None, channel_ok=True,
              offline_only=False, backends=['reference'],
              realtime=dict(block_ok=False, allocates=True, latency_samples=0))]
IMPLS = {'vibe': vibe}
TIME_VARYING = {'vibe'}


def validate(p):
    from mankomix.dspx.bb.modulation import validate_mod
    validate_mod(p)


CROSS_VALIDATE = {'vibe': validate}
