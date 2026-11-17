"""T08-06 experimental harmonic-group retuning by peak-region translation."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e, _a


def validate(p):
    if len(p['map']) != 12:
        raise ParamError('poly_retune: map must contain exactly twelve intervals')
    if p['lo_hz'] >= p['hi_hz']:
        raise ParamError('poly_retune: lo_hz must be below hi_hz')


def latency_samples(sr, p):
    from mankomix.dspx.bb.stft import window_samples
    return window_samples(p['window'], sr)


def poly_retune(x, sr, p, *, seed=0, compensate=True):
    from mankomix.dspx.bb import stft, partials
    from mankomix.dspx.bb.pitchtime import _separate_transients, _restore_transients
    validate(p)
    n = latency_samples(sr, p)
    y = x.copy()
    info = dict(group_count_max=0, ambiguous_peak_frames=0, shifted_peak_frames=0)
    if p['strength'] and np.any(p['map']) and len(x) and np.any(x):
        sustained, events = _separate_transients(x, sr) if p['transients'] else (x, [])
        a = stft.analyze(sustained, sr, window=n)
        delta, info = partials.retune_regions(a, p['map'], **{k: p[k] for k in (
            'a4_hz', 'strength', 'lo_hz', 'hi_hz', 'min_peak_db', 'transients')})
        y = sustained+stft.synthesize(a, delta)
        y = _restore_transients(y, events, 1)
    if not compensate:
        y = stft.delay_output(y, n)
    return y, sr, dict(**info, latency_samples=n, latency_compensated=compensate)


SPECS = [dict(type='poly_retune', implemented=False,
    description='Experimental polyphonic harmonic-group peak-region retuning.',
    stages=['track', 'bus'], master_slot=None, offline_only=True, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples='window_scaled', allocates=True),
    params=[
        _a('map', 'semitones', -6, 6, 12, [0]*12, 'C..B intervals; all zero bypasses.'),
        _f('a4_hz', 'Hz', 400, 480, 440, 'Tuning reference.'),
        _f('strength', None, 0, 1, 1, 'Fraction of snapping and mapped interval.'),
        _e('window', [4096, 8192, 16384], 8192, '48 kHz analysis size.'),
        _f('lo_hz', 'Hz', 20, 500, 60, 'Lowest moved peak.'),
        _f('hi_hz', 'Hz', 1000, 20000, 12000, 'Highest moved peak.'),
        _f('min_peak_db', 'dB', -90, -30, -60, 'Peak threshold relative to frame maximum.'),
        _f('transients', None, 0, 1, .7, 'Transient protection.')])]
IMPLS = {'poly_retune': poly_retune}
CROSS_VALIDATE = {'poly_retune': validate}
TIME_VARYING = {'poly_retune'}
