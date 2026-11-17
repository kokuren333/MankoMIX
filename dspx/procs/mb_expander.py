"""Multiband downward expansion with shared gate hold and gain ballistics."""
import numpy as np
from mankomix.dspx.params import _a, _f, _b
from mankomix.dspx.bb import crossover as C, dynamics as D

DEFAULTS = dict(threshold_db=-45, ratio=2, range_db=-24, attack_ms=2,
                hold_ms=20, release_ms=150, up_gain_db=0)
SPECS = [{
    'type': 'mb_expander', 'implemented': True,
    'description': 'Bandwise downward expansion, hold and optional capped upward expansion.',
    'stages': ['track', 'bus', 'master'], 'master_slot': 2,
    'offline_only': False, 'backends': ['reference'], 'channel_ok': True,
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0,
                 'latency_rule': 'linear with edges: (BB-02 FIR taps-1)/2; compensated offline'},
    'params': C.mb_params() + [_a(k, unit, lo, hi, 6, [], desc) for k, unit, lo, hi, desc in [
        ('threshold_db', 'dBFS', -80, 0, 'Threshold; empty means -45.'),
        ('ratio', ':1', 1, 100, 'Ratio; empty means 2.'),
        ('range_db', 'dB', -90, 0, 'Attenuation floor; empty means -24.'),
        ('attack_ms', 'ms', .05, 300, 'Opening tau; empty means 2.'),
        ('hold_ms', 'ms', 0, 2000, 'Hold; empty means 20.'),
        ('release_ms', 'ms', 5, 3000, 'Closing tau; empty means 150.'),
        ('up_gain_db', 'dB', 0, 12, 'Maximum above-threshold expansion; empty disables.')]]
        + [_f('knee_db', 'dB', 0, 24, 6, 'Knee width.'), _b('stereo_link', True, 'Linked detector.')]}]
TIME_VARYING = {'mb_expander'}


def mb_expander(x, sr, p, *, seed=0, compensate=True):
    C.validate_mb(p, sr)
    bp = C.expand_band_params(p, DEFAULTS)
    bands, info = C.split_mb(x, sr, p, compensate=compensate)
    reductions = []
    for i, band in enumerate(bands):
        local = dict(p, **{k: v[i] for k, v in bp.items()}, hysteresis_db=0)
        levels = D.level_db(D.detector(band, sr, 'peak', stereo_link=p['stereo_link']))
        gain, _ = D.GateState(sr, local).process(levels)
        if local['up_gain_db']:
            # Mirror the shared expander curve above the threshold; cap its gain.
            up = -D.expander_gain_db(-levels, -local['threshold_db'], local['ratio'],
                                     -local['up_gain_db'], p['knee_db'])
            gain += D.smooth_gain(up, sr, local['attack_ms'], local['release_ms'])
        bands[i] = D.apply_gain(band, gain)
        reductions.append(D.gr_stats(np.maximum(-gain, 0)))
    return C.recombine_bands(bands), sr, dict(info, band_gain_reduction=reductions)


IMPLS = {'mb_expander': mb_expander}
