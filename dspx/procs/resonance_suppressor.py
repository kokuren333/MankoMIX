"""T02-03 log-frequency envelope excess suppression; no product model."""
import numpy as np
from mankomix.dspx.params import _f


def validate(p):
    from mankomix.dspx.bb.spectral_control import validate_band
    validate_band(p)


def latency_samples(sr, p):
    from mankomix.dspx.bb.spectral_control import latency_samples as resolve
    return resolve(sr, p)


def control(analysis, p):
    """Return (smoothed bin gain dB, target attenuation dB), time/bin/ch."""
    from mankomix.dspx.bb.spectral_control import spectral_envelope, widen_notches, frame_smooth
    power = abs(analysis.spectra)**2
    if p['stereo_link']:
        power = np.max(power, axis=2, keepdims=True)
    envelope = spectral_envelope(power, analysis.frequencies_hz, p['envelope_oct'])
    db = 10*np.log10(np.maximum(power, 1e-30))
    tilt = p['tilt_db_oct']*np.log2(np.maximum(analysis.frequencies_hz, 20)/1000)
    demand = np.clip(db-envelope-p['excess_db']+tilt[None, :, None], 0, p['depth_db'])
    demand = widen_notches(demand, analysis.frequencies_hz, p['notch_oct'])
    return frame_smooth(-demand, analysis.sr, analysis.hop_samples, p['attack_ms'], p['release_ms']), demand


def resonance_suppressor(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft
    from mankomix.dspx.bb.spectral_control import finish
    validate(p)
    a, db = None, np.empty((0, 0, 1))
    if p['depth_db'] and p['mix'] and len(x) and np.any(x):
        a = stft.analyze(x, sr, window=latency_samples(sr, p))
        db, _ = control(a, p)
    return finish(x, sr, p, a, db, compensate=compensate)


# Imports of BB modules are delayed until discovery has completed.
from mankomix.dspx.params import _e, _b
_COMMON = [_e('window', [1024, 2048, 4096], 2048, '48 kHz analysis size.'),
    _f('lo_hz', 'Hz', 20, 20000, 200, 'Lower effect edge.'),
    _f('hi_hz', 'Hz', 20, 24000, 16000, 'Upper effect edge.'),
    _f('mix', None, 0, 1, 1, 'Processed fraction.'), _b('delta', False, 'Removed signal.'),
    _b('stereo_link', True, 'Common per-bin gain across channels.')]
SPECS = [dict(type='resonance_suppressor', implemented=True,
    description='Dynamic suppression of excess over a log-frequency envelope.',
    stages=['track', 'bus', 'master'], master_slot=2, offline_only=False, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples='window_scaled', allocates=True),
    params=_COMMON+[
        _f('depth_db', 'dB', 0, 24, 6, 'Maximum attenuation.'),
        _f('excess_db', 'dB', 0, 24, 8, 'Envelope excess threshold; calibrated for noise preservation.'),
        _f('envelope_oct', 'oct', .1, 2, .5, 'Log-frequency envelope width.'),
        _f('notch_oct', 'oct', .02, .5, .1, 'Maximum and mean widening width.'),
        _f('attack_ms', 'ms', 0, 200, 5, 'Gain attack time constant.'),
        _f('release_ms', 'ms', 5, 2000, 80, 'Gain release time constant.'),
        _f('tilt_db_oct', 'dB/oct', -6, 6, 0, 'Sensitivity tilt about 1 kHz.')])]
IMPLS = {'resonance_suppressor': resonance_suppressor}
TIME_VARYING = set(IMPLS)
CROSS_VALIDATE = {'resonance_suppressor': validate}
