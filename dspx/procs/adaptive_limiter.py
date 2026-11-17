"""T01-13 / T12-01 program-dependent two-stage limiter, measured TP only.

Detection reuses reference.truepeak, including its finite 16-sample FIR
future context. Program state uses past detector samples only. The slow
stage handles persistent demand; bounded lookahead handles its residual.
Two bounded local correction passes address interpolation after modulation;
there is no whole-track normalization or true-peak guarantee. Offline output
is compensated; raw output delays the same result by latency_samples().
"""
import numpy as np
from mankomix.dspx.params import _f, _e

SPECS = [{
    'type': 'adaptive_limiter', 'implemented': True,
    'description': 'Causal program-dependent release with bounded lookahead; measured true peak only.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 5,
    'offline_only': False, 'backends': ['reference'],
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0,
                 'latency_rule': '3*(2*floor(round(lookahead_ms*sr/1000)/2)+16*(oversample>1)); compensated offline'},
    'params': [
        _f('ceiling_db', 'dBFS', -24, 0, -1., 'Output detection-grid ceiling.'),
        _f('drive_db', 'dB', 0, 24, 0, 'Gain before limiting.'),
        _f('lookahead_ms', 'ms', 1, 10, 4, 'Bounded lookahead per pass.'),
        _f('release_min_ms', 'ms', 5, 200, 30, 'Fast release time constant.'),
        _f('release_max_ms', 'ms', 100, 3000, 600, 'Slow release upper bound.'),
        _f('adapt', '0..1', 0, 1, .7, 'Program dependence; zero gives fixed release.'),
        _f('transient', '0..1', 0, 1, .3, 'Isolated demand assigned to the fast stage.'),
        _f('stereo_link', '0..1', 0, 1, 1, 'Blend independent demand toward channel maximum.'),
        _e('oversample', [1, 2, 4, 8], 4, 'Detector oversampling.', unit='x')]}]
TIME_VARYING = {'adaptive_limiter'}


def validate(p):
    """Reject release_min_ms > release_max_ms during chain validation."""
    from mankomix.dsp.errors import ParamError
    if p['release_min_ms'] > p['release_max_ms']:
        raise ParamError('release_min_ms must not exceed release_max_ms')


def latency_samples(sr, p):
    """Bounded future context in input samples; offline audio has zero delay."""
    return 3*(2*(round(p['lookahead_ms']*sr/1000)//2)+16*(p['oversample'] > 1))


def detect(x, factor, link):
    """Existing oversampled detector per channel, blended toward linked max."""
    from mankomix.dsp.reference.truepeak import peak_per_sample
    peak = np.column_stack([peak_per_sample(x[:, c:c+1], factor) for c in range(x.shape[1])])
    return peak + link*(np.max(peak, axis=1, keepdims=True)-peak) if len(x) else peak


def adaptive_limiter(x, sr, p, *, seed=0, compensate=True):
    """Return (audio, sr, stats); fresh zero state for each full-context render."""
    from mankomix.dspx.bb import dynamics as D
    from mankomix.dsp.reference import truepeak as TP
    validate(p)
    x = np.asarray(x, dtype=np.float64)
    driven = x.copy() if p['drive_db'] == 0 else x*10**(p['drive_db']/20)
    peak = detect(driven, p['oversample'], p['stereo_link'])
    ceiling = 10**(p['ceiling_db']/20)
    demand = np.maximum(0., 20*np.log10(np.maximum(peak, 1e-30)/ceiling))
    state = D.AdaptiveReleaseState(sr, p['release_min_ms'], p['release_max_ms'], p['adapt'], p['transient'])
    slow, tau, _ = state.process(demand, peak)
    slow_gain = 10**(-slow/20)
    required = np.minimum(1., 10**(-demand/20)/slow_gain)
    # Fast release is fixed and uses the existing BB-03 zero-attack follower.
    held = np.column_stack([D.smooth_python(c, 0., D.coef(p['release_min_ms'], sr)) for c in (1-required).T])
    gain = slow_gain*D.bounded_lookahead_gain(1-held, sr, p['lookahead_ms'])
    y = driven*gain
    for _ in range(2):
        post_peak = detect(y, p['oversample'], p['stereo_link'])
        correction = np.minimum(1., ceiling/np.maximum(post_peak, 1e-30))
        correction = D.bounded_lookahead_gain(correction, sr, p['lookahead_ms'])
        y = y*correction
        gain *= correction
    gr = -20*np.log10(np.maximum(gain, 1e-30))
    tp = TP.true_peak_dbtp(y, sr)
    delay = latency_samples(sr, p)
    stats = {'gain_reduction': D.gr_stats(gr),
             'frac_gr_over_3db': float(np.mean(np.max(gr, axis=1) > 3)) if len(x) else 0.,
             'true_peak_dbtp': float(tp) if np.isfinite(tp) else None,
             'detector_peak_dbfs': TP.true_peak_dbtp(y, factor=p['oversample']) if np.any(y) else None,
             'true_peak_guaranteed': False, 'detector_oversample': p['oversample'],
             'release_ms_min': float(np.min(tau)) if len(x) else p['release_min_ms'],
             'release_ms_max': float(np.max(tau)) if len(x) else p['release_min_ms'],
             'latency_samples': delay, 'latency_compensated': compensate,
             'state_initialization': 'zero; excerpts replay preceding context',
             'correction_passes': 2}
    return (y if compensate else D.delay_audio(y, delay)), sr, stats


IMPLS = {'adaptive_limiter': adaptive_limiter}
CROSS_VALIDATE = {'adaptive_limiter': validate}
