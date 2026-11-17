"""Integrated tape speed motion using the reusable BB wobble generator."""
from mankomix.dspx.params import _f, _i
from mankomix.dspx.bb.wobble import wobble_from_params, base_latency
from mankomix.dspx.bb.modulation import read_modulated, modulation_definition
from mankomix.dspx.bb.delayline import spatial_stats


def raw_wow_flutter(x, sr, p, *, seed=0, compensate=False):
    displacement, speed = wobble_from_params(len(x), sr, p, channels=x.shape[1], seed=seed)
    latency = base_latency(sr, p)
    y = read_modulated(x, displacement, latency=latency, compensate=compensate)
    stats = {'latency_samples': latency, 'latency_compensated': compensate,
             'speed_peak_percent': float(abs(speed).max()*100) if speed.size else 0.,
             'speed_mean_percent': float(speed.mean()*100) if speed.size else 0.,
             'iec_60386_weighted_percent': None,
             'weighting_status': 'unverified: normative weighting and detector unavailable'}
    return y, sr, stats


def wow_flutter(x, sr, p, *, seed=0):
    y, _, stats = raw_wow_flutter(x, sr, p, seed=seed, compensate=True)
    stats.update({k: v for k, v in spatial_stats(y, sr).items() if k != 'latency_samples'})
    return y, sr, stats


SPECS = [modulation_definition('wow_flutter', [
    _f('wow_depth', '%', 0, 3, .2, 'Peak slow speed deviation.'),
    _f('wow_rate_hz', 'Hz', .1, 4, .6, 'Slow modulation rate.'),
    _f('flutter_depth', '%', 0, 1, .05, 'Peak fast speed deviation.'),
    _f('flutter_rate_hz', 'Hz', 4, 50, 9, 'Fast modulation rate.'),
    _f('drift', None, 0, 1, .3, 'Band-limited irregular proportion.'),
    _f('scrape', None, 0, 1, 0, 'Small high-frequency speed noise.'),
    _f('stereo_link', None, 0, 1, 1, 'Shared left/right motion.'),
    _i('seed', None, 0, 65535, 0, 'Deterministic parameter seed.')],
    latency_rule='bb.wobble.base_latency(sr, params); compensated offline')]
TIME_VARYING = {'wow_flutter'}
IMPLS = {'wow_flutter': wow_flutter}
