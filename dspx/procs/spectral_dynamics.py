"""T02-04 per-bin downward compression or expansion with coherent dBFS."""
import numpy as np
from mankomix.dspx.params import _f, _e, _b


def validate(p):
    from mankomix.dspx.bb.spectral_control import validate_band
    validate_band(p)


def latency_samples(sr, p):
    from mankomix.dspx.bb.spectral_control import latency_samples as resolve
    return resolve(sr, p)


def control(analysis, p):
    """Return smoothed/target gain dB, using the BB-03 static curves."""
    from mankomix.dspx.bb.spectral_control import frame_smooth
    from mankomix.dspx.bb.spectral_components import lobes
    from mankomix.dspx.bb.stft import smooth_frequency
    from mankomix.dspx.bb.dynamics import downward_gain_db, expander_gain_db
    peaks, amplitude = lobes(analysis, linked=p['stereo_link'])
    power = smooth_frequency(amplitude**2, analysis.frequencies_hz, p['smooth_oct'])
    # Sample the smoothed detector at each component and apply one gain to
    # its entire window response, including the sidelobes.
    power = np.take_along_axis(power, peaks, axis=1)
    level = 10*np.log10(np.maximum(power, 1e-30))
    center = analysis.frequencies_hz[peaks]
    tilt = p['threshold_tilt_db_oct']*np.log2(np.maximum(center, 20)/1000)
    shifted = level-tilt
    if p['mode'] == 'compress':
        target = downward_gain_db(shifted, p['threshold_db'], p['ratio'], p['knee_db'], p['range_db'])
    else:
        target = expander_gain_db(shifted, p['threshold_db'], p['ratio'], -p['range_db'], p['knee_db'])
    return frame_smooth(target, analysis.sr, analysis.hop_samples, p['attack_ms'], p['release_ms']), target


def spectral_dynamics(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft
    from mankomix.dspx.bb.spectral_control import finish
    validate(p)
    a, db = None, np.empty((0, 0, 1))
    if p['ratio'] != 1 and p['range_db'] and p['mix'] and len(x) and np.any(x):
        a = stft.analyze(x, sr, window=latency_samples(sr, p))
        db, _ = control(a, p)
    return finish(x, sr, p, a, db, compensate=compensate)


SPECS = [dict(type='spectral_dynamics', implemented=True,
    description='Coherent-normalized per-bin compressor or downward expander.',
    stages=['track', 'bus', 'master'], master_slot=2, offline_only=False, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples='window_scaled', allocates=True),
    params=[_e('window', [1024, 2048, 4096], 2048, '48 kHz analysis size.'),
        _f('lo_hz', 'Hz', 20, 20000, 20, 'Lower effect edge.'),
        _f('hi_hz', 'Hz', 20, 24000, 20000, 'Upper effect edge.'),
        _f('mix', None, 0, 1, 1, 'Processed fraction.'), _b('delta', False, 'Removed signal.'),
        _b('stereo_link', True, 'Common per-bin gain across channels.'),
        _e('mode', ['compress', 'expand'], 'compress', 'Downward gain curve.'),
        _f('threshold_db', 'dBFS', -100, 0, -40, 'Coherent peak bin threshold.'),
        _f('threshold_tilt_db_oct', 'dB/oct', -6, 6, -3, 'Threshold tilt about 1 kHz.'),
        _f('ratio', None, 1, 20, 3, 'Static compression or expansion ratio.'),
        _f('knee_db', 'dB', 0, 24, 6, 'Quadratic knee width.'),
        _f('range_db', 'dB', 0, 36, 12, 'Maximum attenuation.'),
        _f('smooth_oct', 'oct', 0, 1, .1, 'Detection power averaging width.'),
        _f('attack_ms', 'ms', 0, 200, 10, 'Gain attack time constant.'),
        _f('release_ms', 'ms', 5, 2000, 100, 'Gain release time constant.')])]
IMPLS = {'spectral_dynamics': spectral_dynamics}
TIME_VARYING = set(IMPLS)
CROSS_VALIDATE = {'spectral_dynamics': validate}
