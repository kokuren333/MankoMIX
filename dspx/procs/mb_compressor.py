"""Multiband forward compressor using BB-02 and BB-03 unchanged."""
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _f, _e, _b
from mankomix.dspx.bb import crossover as C, dynamics as D

DEFAULTS = dict(threshold_db=-24, ratio=2, attack_ms=10, release_ms=150,
                makeup_db=0, range_db=48, up_ratio=2, up_max_gain_db=6)
SPECS = [{
    'type': 'mb_compressor', 'implemented': True,
    'description': 'LR4 or complementary FIR multiband compression and optional upward gain.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 2,
    'offline_only': False, 'backends': ['reference'], 'channel_ok': True,
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0,
                 'latency_rule': 'linear with edges: (BB-02 FIR taps-1)/2; compensated offline'},
    'params': C.mb_params() + [
        _a(k, unit, lo, hi, 6, [], desc) for k, unit, lo, hi, desc in [
            ('threshold_db', 'dBFS', -60, 0, 'Downward threshold; empty means -24.'),
            ('ratio', ':1', 1, 30, 'Downward ratio; empty means 2.'),
            ('attack_ms', 'ms', .05, 300, 'Attack tau; empty means 10.'),
            ('release_ms', 'ms', 5, 3000, 'Release tau; empty means 150.'),
            ('makeup_db', 'dB', -12, 24, 'Makeup; empty means zero.'),
            ('range_db', 'dB', 0, 48, 'Maximum GR; empty means 48.'),
            ('up_threshold_db', 'dBFS', -80, 0, 'Upward threshold; empty disables.'),
            ('up_ratio', ':1', 1, 10, 'Upward ratio; empty means 2.'),
            ('up_max_gain_db', 'dB', 0, 24, 'Upward ceiling; empty means 6.')]]
        + [_f('knee_db', 'dB', 0, 24, 6, 'Knee width.'),
           _e('detector', ['peak', 'rms'], 'rms', 'Detector.'),
           _f('rms_window_ms', 'ms', 1, 300, 10, 'RMS window.'),
           _b('stereo_link', True, 'Maximum-linked detector.')]}]
TIME_VARYING = {'mb_compressor'}


def latency_samples(sr, p):
    return (C.taps_for(min(p['crossovers_hz']), sr)-1)//2 if p['phase'] == 'linear' and p['crossovers_hz'] else 0


def mb_compressor(x, sr, p, *, seed=0, compensate=True):
    C.validate_mb(p, sr)
    defaults = dict(DEFAULTS)
    if p['up_threshold_db']:
        defaults['up_threshold_db'] = -30
    bp = C.expand_band_params(p, defaults)
    if 'up_threshold_db' in bp and any(u > d for u, d in zip(bp['up_threshold_db'], bp['threshold_db'])):
        raise ParamError('up_threshold_db must not exceed threshold_db')
    bands, info = C.split_mb(x, sr, p, compensate=compensate)
    stats = []
    for i, band in enumerate(bands):
        local = dict(p, **{k: v[i] for k, v in bp.items()})
        gr = D.compressor_gain(band, sr, local)
        gain = -gr
        if 'up_threshold_db' in bp:
            levels = D.level_db(D.detector(band, sr, p['detector'], p['rms_window_ms'], p['stereo_link']))
            up = D.upward_gain_db(levels, local['up_threshold_db'], local['up_ratio'],
                                  local['up_max_gain_db'], -60, p['knee_db'])
            gain += D.smooth_gain(up, sr, local['attack_ms'], local['release_ms'])
        bands[i] = D.apply_gain(band, gain, local['makeup_db'])
        stats.append(D.gr_stats(gr))
    return C.recombine_bands(bands), sr, dict(info, band_gain_reduction=stats)


IMPLS = {'mb_compressor': mb_compressor}
