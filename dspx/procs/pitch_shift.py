"""Fixed interval pitch shift, with explicitly declared quality tiers."""
from mankomix.dspx.params import _f, _e, _b


def definition(name, params, *, latency_rule=None):
    """Fresh reference-only pitch processor declaration, pending acceptance."""
    rt = dict(block_ok=False, latency_samples=0, allocates=True)
    if latency_rule:
        rt['latency_rule'] = latency_rule
    return dict(type=name, description=name.replace('_', ' '), params=params,
                stages=['track', 'bus'], master_slot=None, offline_only=False,
                backends=['reference'], implemented=False, realtime=rt)


def pitch_shift(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.pitchtime import shift, latency_samples
    lookahead = latency_samples(sr, p['quality'], p['window'])
    if p['mix'] == 0 or p['semitones']+p['cents']/100 == 0:
        return x.copy(), sr, {'latency_samples': 0, 'quality': p['quality']}
    wet = shift(x, sr, track_glides=True, **{k: p[k] for k in (
        'semitones', 'cents', 'quality', 'formant', 'formant_cents',
        'transients', 'window', 'stereo_link')})
    y = wet if p['mix'] == 1 else x+(wet-x)*p['mix']
    return y, sr, dict(quality=p['quality'], latency_samples=lookahead,
                      latency_compensated=True, formant=p['formant'] and p['quality'] != 'fast')


def raw_pitch_shift(x, sr, p, *, seed=0):
    """Buffered uncompensated output for latency probes, retaining input length.

    The offline entry above returns centred, compensated processing. This
    exposes its declared one-window buffering, using the BB-06 convention.
    """
    import numpy as np
    y, _, stats = pitch_shift(x, sr, p, seed=seed)
    delay = stats['latency_samples']
    raw = np.zeros_like(y)
    if delay == 0:
        raw = y
    elif delay < len(y):
        raw[delay:] = y[:-delay]
    return raw, sr, {**stats, 'latency_compensated': False}


SPECS = [definition('pitch_shift', [
    _f('semitones', 'semitones', -24, 24, 0, 'Fixed pitch interval.'),
    _f('cents', 'cents', -100, 100, 0, 'Fine pitch interval.'),
    _e('quality', ['fast', 'standard', 'high'], 'high', 'Pitch/time algorithm.'),
    _b('formant', False, 'Preserve spectral envelope in standard/high.'),
    _f('formant_cents', 'cents', -1200, 1200, 0, 'Preserved envelope offset.'),
    _f('transients', None, 0, 1, .7, 'High-quality transient phase reset sensitivity.'),
    _e('window', [1024, 2048, 4096, 8192], 4096, 'High-quality window at 48 kHz.'),
    _b('stereo_link', True, 'Shared mid-based alignment, peaks and resets.'),
    _f('mix', None, 0, 1, 1, 'Wet proportion.')], latency_rule=
    'Neutral/mix=0: 0; fast: 0; standard: round(.040*sr); high: round(window*sr/48000). '
    'Offline centered processing compensates the lookahead internally.')]
IMPLS = {'pitch_shift': pitch_shift}
SPECS[0]['implemented'] = True
