"""Single-sideband frequency translation using the reusable causal IIR pair."""
import numpy as np
from mankomix.dspx.params import _f, _e


def shift_phase(frames, sr, p, *, start_sample=0, seed=0):
    """Absolute integrated shift in cycles, including deterministic LFO motion."""
    from mankomix.dspx.bb.motion import curve_integral
    from mankomix.dspx.bb.modulation import mod_lfo
    t = np.arange(start_sample, start_sample+frames, dtype=np.int64)/sr
    points = p['shift_curve'] or [[0, p['shift_hz']]]
    phase = curve_integral(points, t)
    if p['depth'] and len(t):
        grid = np.arange(int(np.ceil(t[-1]*2560))+2)/2560
        wave = mod_lfo(len(grid), 2560,
                       dict(p, note='none', bpm=0, phase=0, origin_s=0, stereo_phase=0),
                       seed=seed)[:, 0]
        phase += curve_integral(np.column_stack((grid, wave*p['shift_hz']*p['depth'])), t)
    return phase


def freq_shifter(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.hilbert import frequency_shift
    from mankomix.dspx.bb.delayline import spatial_stats
    if not p['mix']:
        return x.copy(), sr, {'latency_samples': 0}
    cycles = shift_phase(len(x), sr, p, seed=seed)
    largest = max([p['shift_hz']] if not p['shift_curve'] else [v[1] for v in p['shift_curve']])
    if p['sideband'] == 'both':
        largest = max(abs(v[1]) for v in (p['shift_curve'] or [[0, p['shift_hz']]]))
    largest += abs(p['shift_hz'])*p['depth']
    upper, lower = frequency_shift(x, sr, cycles, feedback=p['feedback'], lo_hz=p['lo_hz'],
                                   max_up_hz=max(0, largest))
    if p['sideband'] == 'both':
        wet = np.column_stack((np.mean(upper, axis=1), np.mean(lower, axis=1)))
        dry = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x
    else:
        wet, dry = upper, x
    y = wet if p['mix'] == 1 else (1-p['mix'])*dry+p['mix']*wet
    st = spatial_stats(y, sr)
    st.update(latency_samples=0, group_delay_compensated=False,
              dc_crossing='Negative frequency components fold at zero Hz.', feedback_delay_ms=10)
    return y, sr, st


def _params():
    from mankomix.dspx.bb.motion import curve_param
    from mankomix.dspx.bb.modulation import mod_params
    common = [v for v in mod_params(1, 0, 0, 1) if v['id'] in ('rate_hz', 'lfo_shape', 'depth', 'mix', 'seed')]
    return [_f('shift_hz', 'Hz', -5000, 5000, 5, 'Signed frequency translation.'),
            curve_param('shift_curve', 's', 0, 36000, -5000, 5000, 1024, []),
            _e('sideband', ['single', 'both'], 'single', 'Single or upper-left/lower-right.'),
            _f('feedback', None, 0, .9, 0, 'Ten millisecond delayed feedback.'),
            _f('lo_hz', 'Hz', 0, 500, 20, 'Input highpass; zero disables it.')] + common


SPECS = [dict(type='freq_shifter', implemented=True, description='Causal IIR quadrature frequency shifter; DC crossings fold.',
              params=_params(), stages=['track', 'bus'], master_slot=None, channel_ok=True,
              offline_only=False, backends=['reference'],
              realtime=dict(block_ok=False, allocates=True, latency_samples=0,
                            latency_rule='Allpass group delay intentionally not compensated.'))]
IMPLS = {'freq_shifter': freq_shifter}
TIME_VARYING = {'freq_shifter'}
