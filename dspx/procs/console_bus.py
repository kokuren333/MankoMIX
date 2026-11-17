"""Stereo-only interchannel coupling and generic bus amplifier coloration.

No other tracks are read. Coupling uses the sampled analog one-pole response
s/(s+2*pi*200000), normalized at 20 kHz, with fractional order slope/6.
The whole-context frequency-domain realization avoids bilinear HF warping.
"""
import numpy as np
from scipy import fft
from mankomix.dspx.params import _f, _e, _i


def coupling(x, sr, slope):
    """Normalized analog HP response, zero-extended FFT, fractional order 0..1."""
    if not len(x) or slope == 0:
        return x.copy()
    n = fft.next_fast_len(2*len(x))
    f = fft.rfftfreq(n, 1/sr)
    response = (1j*f/(200000+1j*f))**(slope/6)
    response /= abs((1j*20000/(200000+1j*20000))**(slope/6))
    return fft.irfft(fft.rfft(x, n, axis=0, workers=1)*response[:, None],
                     n, axis=0, workers=1)[:len(x)]


def amplifier(x, drive_db, character):
    """Zero-anchored slope-one tanh with a bounded even-order component."""
    g = 10**(drive_db/20)
    t = np.tanh(g*x)
    return (t+.25*character*t*t)/g


def console_bus(x, sr, p, *, seed=0):
    from mankomix.dspx.bb import nonlinear as N
    from mankomix.dspx.bb.curves import modulation_seed
    stereo = x.shape[1] == 2
    factor = int(p['oversample'])*4
    info = N.precision_oversampling_info(factor)
    info['oversample'] = p['oversample']
    info.update(crosstalk_disabled_mono=not stereo, tolerance_disabled_mono=not stereo,
                channel_gain_db=[0.0]*x.shape[1], hf_tolerance_ratio=[1.0]*x.shape[1])
    y = x.copy()
    if stereo and p['crosstalk_db'] > -120:
        y += 10**(p['crosstalk_db']/20)*coupling(x[:, ::-1], sr, p['crosstalk_slope'])
    if p['drive_db'] and len(x):
        y = N.precision_oversampled(y, factor,
            lambda u: amplifier(u, p['drive_db'], p['character']))
        y = N.dc_block(y, sr)
    rng = np.random.Generator(np.random.PCG64(modulation_seed(seed, 'console_bus', p['seed'])))
    if stereo and p['tolerance']:
        # Differential bounds: the total channel difference is at most .1 dB.
        gain = float(rng.uniform(-.05, .05))*p['tolerance']
        hf = float(rng.uniform(-.03, .03))*p['tolerance']
        info.update(channel_gain_db=[gain, -gain], hf_tolerance_ratio=[1+hf, 1-hf])
    for c in range(x.shape[1]):
        v = y[:, c:c+1]
        if p['lf_corner_hz']:
            v = N.filter_audio(v, sr, p['lf_corner_hz'], 'highpass', 1)
        cutoff = p['hf_corner_hz']*info['hf_tolerance_ratio'][c]
        if 0 < cutoff < .45*sr:
            v = N.filter_audio(v, sr, cutoff, 'lowpass', 1)
        y[:, c:c+1] = v*10**(info['channel_gain_db'][c]/20)
    if p['drive_db'] and len(y):
        y -= np.mean(y, axis=0)
    if p['noise_db'] > -120:
        y += rng.standard_normal(y.shape)*10**(p['noise_db']/20)
    if p['output_db']:
        y *= 10**(p['output_db']/20)
    return y, sr, info


def _spec():
    from mankomix.dspx.bb.lowend import definition
    return definition('console_bus', [
        _f('crosstalk_db', 'dB', -120, -40, -120, 'Stereo leakage at 20 kHz; -120 disables.'),
        _f('crosstalk_slope', 'dB/oct', 0, 6, 6, 'Coupling highpass slope.'),
        _f('drive_db', 'dB', 0, 18, 0, 'Bus amplifier drive.'),
        _f('character', '0..1', 0, 1, .5, 'Even-harmonic weight.'),
        _f('tolerance', '0..1', 0, 1, 0, 'Seeded differential gain and HF tolerance.'),
        _f('lf_corner_hz', 'Hz', 0, 30, 0, 'Output highpass; zero disables.'),
        _f('hf_corner_hz', 'Hz', 0, 80000, 0, 'Output lowpass; >=.45*sr disables.'),
        _f('noise_db', 'dBFS', -120, -70, -120, 'Seeded white noise; -120 disables.'),
        _e('oversample', [1, 2, 4, 8], 4, 'Nonlinear oversampling.', unit='x'),
        _f('output_db', 'dB', -36, 12, 0, 'Output gain.'),
        _i('seed', None, 0, 65535, 0, 'Parameter seed.')],
        'Stereo coupling and channel variation only; no intertrack routing.', stages=['bus', 'master'])


SPECS = [_spec()]
SPECS[0]['implemented'] = True
IMPLS = {'console_bus': console_bus}
