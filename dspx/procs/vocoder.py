"""Single-input channel vocoder with internal bandlimited carrier."""
import numpy as np
from mankomix.dspx.params import _i, _f, _a, _e
from mankomix.dspx.bb.time_creative import definition, curve_param
from mankomix.dspx.bb.band_envelopes import asset_param


def vocoder(x, sr, p, *, seed=0):
    from mankomix.dspx.bb import band_envelopes as B
    B.centers(p, sr)
    if p['mix'] == 0:
        return x.copy(), sr, {}
    env = B.resolve_control(p['envelopes'], len(x), sr, p) if p['envelopes'] else B.analyze(x, sr, p)
    car = np.repeat(B.carrier(len(x), sr, p, seed), x.shape[1], axis=1)
    wet = B.synthesize(car, sr, p, env)
    if p['unvoiced']:
        from scipy import signal
        high = signal.sosfilt(signal.butter(2, min(4000, .35*sr), 'highpass', fs=sr, output='sos'), x, axis=0)
        # Only genuinely broadband high-frequency frames supplement consonants.
        from mankomix.dspx.bb.dynamics import envelope
        hf = envelope(np.abs(high), sr, p['attack_ms'], p['release_ms'])
        total = envelope(np.abs(x), sr, p['attack_ms'], p['release_ms'])
        fraction = np.clip((hf/np.maximum(total, 1e-12)-.5)*2, 0, 1)
        wet += p['unvoiced']*high*fraction
    wet *= 10**(p['output_db']/20)
    return (wet if p['mix'] == 1 else x+p['mix']*(wet-x)), sr, {'bands': p['bands'], 'carrier': p['carrier']}


SPECS = [definition('vocoder', [
    _i('bands', None, 4, 40, 16, 'Log-spaced analysis/synthesis bands.'),
    _f('lo_hz', 'Hz', 50, 500, 100, 'Lowest band center.'),
    _f('hi_hz', 'Hz', 2000, 16000, 8000, 'Highest band center.'),
    _e('carrier', ['saw', 'pulse', 'noise', 'saw_noise'], 'saw_noise', 'Internal carrier.'),
    _a('notes', 'MIDI', 0, 127, 8, [48, 55, 60, 64], 'Carrier chord.'),
    curve_param('notes_curve', 1024, 0, 36000, 0, 127),
    _f('a4_hz', 'Hz', 400, 480, 440, 'Tuning reference.'),
    _f('attack_ms', 'ms', .5, 50, 5, 'Band envelope attack tau.'),
    _f('release_ms', 'ms', 5, 500, 40, 'Band envelope release tau.'),
    _f('formant_shift', 'semitones', -12, 12, 0, 'Analysis-to-synthesis shift.'),
    _f('unvoiced', None, 0, 1, .5, 'High-frequency consonant supplement.'),
    _f('band_q', None, 2, 20, 8, 'Bandpass Q.'), asset_param(),
    _f('mix', None, 0, 1, 1, 'Wet proportion.'),
    _f('output_db', 'dB', -24, 24, 0, 'Wet output gain.'),
    _i('seed', None, 0, 65535, 0, 'Carrier noise seed.')], implemented=True)]
TIME_VARYING = {'vocoder'}
IMPLS = {'vocoder': vocoder}


def validate(p):
    from mankomix.dspx.bb.band_envelopes import validate as check
    check(p)


CROSS_VALIDATE = {'vocoder': validate}
