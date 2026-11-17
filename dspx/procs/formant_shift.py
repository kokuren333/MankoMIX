"""Spectral-envelope translation with phase and harmonic bins preserved."""
from mankomix.dspx.params import _f, _i, _e


def validate(p):
    from mankomix.dsp.errors import ParamError
    if p['lo_hz'] >= p['hi_hz']:
        raise ParamError('lo_hz must be below hi_hz')


def formant_shift(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.psola import shift_envelope
    if p['mix'] == 0 or p['shift_cents'] == 0:
        return x.copy(), sr, {'latency_samples': 0}
    wet, delay = shift_envelope(x, sr, p['shift_cents'], method=p['envelope'],
        order=p['order'], window=p['window'], lo_hz=p['lo_hz'], hi_hz=p['hi_hz'])
    return (wet if p['mix'] == 1 else x+p['mix']*(wet-x)), sr, dict(
        latency_samples=delay, latency_compensated=True, envelope=p['envelope'])


def raw_formant_shift(x, sr, p, *, seed=0):
    """Expose the uncompensated one-window BB-06 output for latency probes."""
    from mankomix.dspx.bb.stft import delay_output
    y, _, stats = formant_shift(x, sr, p, seed=seed)
    return delay_output(y, stats['latency_samples']), sr, {**stats,'latency_compensated':False}


SPECS = [dict(type='formant_shift', description='Translate the spectral envelope.',
    stages=['track', 'bus'], master_slot=None, offline_only=False,
    backends=['reference'], implemented=False,
    realtime=dict(block_ok=False, latency_samples=0, allocates=True,
        latency_rule='Nonzero shift and mix: one window scaled to sr, internally compensated; bypass: 0.'),
    params=[_f('shift_cents', 'cents', -1200, 1200, 0, 'Envelope shift; zero bypasses.'),
        _e('envelope', ['cepstrum', 'lpc', 'true_env'], 'true_env', 'Envelope estimator.'),
        _i('order', None, 8, 80, 40, 'Estimator order at 48 kHz.'),
        _f('lo_hz', 'Hz', 0, 500, 100, 'Lowest affected frequency.'),
        _f('hi_hz', 'Hz', 2000, 20000, 10000, 'Highest affected frequency.'),
        _e('window', [1024, 2048, 4096], 2048, 'Window at 48 kHz.'),
        _f('mix', None, 0, 1, 1, 'Wet proportion.')])]
IMPLS = {'formant_shift': formant_shift}
CROSS_VALIDATE = {'formant_shift': validate}
