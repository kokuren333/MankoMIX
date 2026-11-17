"""T01-03: BB-02 multiband routing around the existing BB-03 transient core."""
from mankomix.dspx.bb import crossover as C, dynamics as D
from mankomix.dspx.params import _a, _b, _f

SPECS = [{
    'type': 'mb_transient', 'implemented': True,
    'description': 'Multiband difference-envelope transient shaping.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 2,
    'offline_only': False, 'backends': ['reference'],
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0,
                 'latency_rule': 'linear: (BB-02 FIR taps-1)/2; compensated offline'},
    'params': C.mb_params()+[
        _a('attack_db', 'dB', -12, 12, 6, [], 'Per-band attack; empty means zero.'),
        _a('sustain_db', 'dB', -12, 12, 6, [], 'Per-band sustain; empty means zero.'),
        _f('fast_ms', 'ms', .1, 10, 1, 'Fast envelope time constant.'),
        _f('slow_ms', 'ms', 5, 100, 20, 'Slow envelope time constant.'),
        _f('sustain_release_ms', 'ms', 50, 2000, 300, 'Sustain release.'),
        _f('max_gain_db', 'dB', 0, 18, 12, 'Absolute gain limit.'),
        _b('stereo_link', True, 'Maximum-linked detector.')]}]
TIME_VARYING = {'mb_transient'}


def latency_samples(sr, p):
    return (C.taps_for(min(p['crossovers_hz']), sr)-1)//2 if p['phase'] == 'linear' and p['crossovers_hz'] else 0


def mb_transient(x, sr, p, *, seed=0, compensate=True):
    C.validate_mb(p, sr)
    bp = C.expand_band_params(p, {'attack_db': 0, 'sustain_db': 0})
    bands, info = C.split_mb(x, sr, p, compensate=compensate)
    stats = []
    for i, band in enumerate(bands):
        local = dict(p, **{k: v[i] for k, v in bp.items()})
        if len(band) and (local['attack_db'] or local['sustain_db']):
            gain = D.transient_gain(band, sr, local)
            bands[i] = D.apply_gain(band, gain)
            stats.append(D.gr_stats(-gain))
        else:
            stats.append({'max_db': 0.})
    return C.recombine_bands(bands), sr, dict(info, band_gain_reduction=stats)


IMPLS = {'mb_transient': mb_transient}


def _validate(p):
    C.validate_mb(p)
    C.expand_band_params(p, {'attack_db': 0, 'sustain_db': 0})


CROSS_VALIDATE = {'mb_transient': _validate}
