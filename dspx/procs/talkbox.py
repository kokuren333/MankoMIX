"""Single-input LPC cross-synthesis with the existing additive carrier."""
import numpy as np
from mankomix.dspx.params import _f, _i, _a, _e
from mankomix.dspx.bb.time_creative import definition, curve_param


def talkbox(x, sr, p, *, seed=0):
    from scipy import signal
    from mankomix.dspx.bb.band_envelopes import carrier
    from mankomix.dspx.bb.psola import lpc_frames, lattice_synthesis
    from mankomix.dspx.bb.nonlinear import oversampled
    if p['mix'] == 0 or not len(x) or not np.any(x):
        return x.copy(), sr, {'latency_samples': 0}
    car = carrier(len(x), sr, p, seed)
    drive = 10**(p['driver_db']/20)
    car = np.sqrt(2)*oversampled(car, 4, lambda v: np.tanh(drive*v))
    car = np.repeat(car, x.shape[1], axis=1)
    centers, ks, gain = lpc_frames(x, sr, p['order'], p['frame_ms'], p['emphasis'])
    wet = lattice_synthesis(car, centers, ks, gain)
    alpha = np.exp(-2*np.pi*1000/sr)
    wet = signal.lfilter([1-alpha], [1, -alpha], wet, axis=0)
    if p['unvoiced']:
        high = signal.sosfilt(signal.butter(2, min(4000, .35*sr), 'highpass', fs=sr, output='sos'), x, axis=0)
        wet += p['unvoiced']*high
    if p['tube']:
        tube = signal.sosfilt(signal.butter(2, [min(300, .05*sr), min(4000, .45*sr)],
                               'bandpass', fs=sr, output='sos'), wet, axis=0)
        b, a = signal.iirpeak(min(1700, .3*sr), 2, fs=sr)
        tube += .3*signal.lfilter(b, a, tube, axis=0)
        wet += p['tube']*(tube-wet)
    wet *= 10**(p['output_db']/20)
    return (wet if p['mix'] == 1 else x+p['mix']*(wet-x)), sr, dict(
        order=ks.shape[1], frames=len(centers), max_abs_reflection=float(np.max(abs(ks), initial=0)),
        latency_samples=0, full_context=True)


SPECS = [definition('talkbox', [
    _e('carrier', ['saw', 'pulse', 'noise', 'saw_noise'], 'saw_noise', 'Internal additive carrier.'),
    _a('notes', 'MIDI', 0, 127, 8, [48, 55, 60, 64], 'Carrier pitches.'),
    curve_param('notes_curve', 1024, 0, 36000, 0, 127),
    _f('a4_hz', 'Hz', 400, 480, 440, 'Carrier reference tuning.'),
    _f('mix', None, 0, 1, 1, 'Wet proportion; zero bypasses.'),
    _f('output_db', 'dB', -24, 24, 0, 'Wet gain.'),
    _i('seed', None, 0, 65535, 0, 'Carrier noise seed.'),
    _i('order', None, 8, 48, 24, 'LPC order at 48 kHz.'),
    _f('frame_ms', 'ms', 10, 40, 20, 'Analysis frame length.'),
    _f('tube', None, 0, 1, .5, 'Band-limited resonant tube proportion.'),
    _f('driver_db', 'dB', 0, 24, 6, 'Oversampled carrier saturation.'),
    _f('emphasis', None, 0, 1, .5, 'Narrow the LPC pole bandwidths.'),
    _f('unvoiced', None, 0, 1, .3, 'High-frequency consonant supplement.')], implemented=True)]
SPECS[0]['realtime']['latency_rule'] = ('Centered LPC frames and reflection smoothing are compensated offline; '
    'no persistent streaming state. Tube/filter phase is part of the effect.')
IMPLS = {'talkbox': talkbox}
TIME_VARYING = {'talkbox'}
