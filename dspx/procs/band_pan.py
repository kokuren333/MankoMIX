"""Stereo-only band balance/width; BB-02 owns splitting and compensation."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _f
from mankomix.dspx.bb import crossover as C
from mankomix.dspx.bb.delayline import spatial_stats

_mb = C.mb_params()
_mb[0]['default'], _mb[1]['default'] = [200, 2000], 'linear'
SPECS = [{
    'type': 'band_pan', 'implemented': True,
    'description': 'Stereo band balance, side width and level; mono input is rejected.',
    'params': _mb + [_a('pan', None, -1, 1, 6, [], 'Balance; empty means zero.'),
                     _a('width', None, 0, 2, 6, [], 'Side gain; empty means one.'),
                     _a('level_db', 'dB', -12, 12, 6, [], 'Band gain; empty means zero.'),
                     _f('lo_protect_hz', 'Hz', 0, 300, 120, 'Ignore pan/width in bands whose upper edge is at or below this frequency.')],
    'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': False,
    'backends': ['reference'], 'channel_ok': False,
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0,
                 'latency_rule': 'linear with edges: (BB-02 FIR taps-1)/2; compensated offline'}}]


def band_pan(x, sr, p, *, seed=0, compensate=True):
    if x.ndim != 2 or x.shape[1] != 2:
        raise ParamError('band_pan requires stereo input')
    C.validate_mb(p, sr)
    bp = C.expand_band_params(p, dict(pan=0, width=1, level_db=0))
    bands, info = C.split_mb(x, sr, p, compensate=compensate)
    ignored = []
    for i, band in enumerate(bands):
        pan, width = bp['pan'][i], bp['width'][i]
        if p['lo_protect_hz'] and i < len(p['crossovers_hz']) and p['crossovers_hz'][i] <= p['lo_protect_hz']:
            ignored.append(i)
            pan, width = 0, 1
        if width != 1:
            mid, side = (band[:, 0]+band[:, 1])/2, (band[:, 0]-band[:, 1])/2
            band = np.column_stack([mid+width*side, mid-width*side])
        if pan:
            # Reuse the existing pan law and exact hard-side mute.
            from mankomix.dsp.reference.basic import pan_gains
            far, _ = pan_gains(abs(pan), -3)
            center, _ = pan_gains(0, -3)
            far = min(1., far/center)
            band = band*np.array([far, 1.] if pan > 0 else [1., far])
        if bp['level_db'][i]:
            band = band*10**(bp['level_db'][i]/20)
        bands[i] = band
    y = C.recombine_bands(bands)
    stats = spatial_stats(y, sr)
    stats.update(info, ignored_pan_width_bands=ignored)
    return y, sr, stats


IMPLS = {'band_pan': band_pan}
