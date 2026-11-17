"""T01-14 composite; fixed child order is incompatible with master HF order."""
from mankomix.dspx.params import _f, _b

SPECS = [{
    'type': 'limiter_chain', 'implemented': True, 'composite': True,
    'description': 'Compressor, soft clipper, optional high-shelf dynamics and adaptive limiter.',
    'stages': ['track', 'bus'], 'master_slot': 5,
    'offline_only': False, 'backends': ['reference'],
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0,
                 'latency_rule': 'Sum of enabled children; compensated offline.'},
    'params': [
        _b('comp_on', True, 'Enable compressor.'),
        _f('comp_threshold_db', 'dBFS', -60, 0, -12, 'Compressor threshold.'),
        _b('clip_on', True, 'Enable soft clipper.'),
        _f('clip_ceiling_db', 'dBFS', -24, 0, -1.5, 'Clipper ceiling.'),
        _f('clip_drive_db', 'dB', 0, 24, 0, 'Clipper drive.'),
        _b('hf_on', False, 'Enable high-shelf dynamic EQ.'),
        _f('hf_freq_hz', 'Hz', 2000, 16000, 8000, 'High-shelf corner.'),
        _f('hf_threshold_db', 'dBFS', -80, 0, -24, 'High-shelf threshold.'),
        _f('hf_range_db', 'dB', -24, 0, -4, 'High-shelf attenuation.'),
        _b('peak_on', True, 'Enable adaptive limiter.'),
        _f('peak_ceiling_db', 'dBFS', -24, 0, -1., 'Adaptive limiter ceiling.'),
        _f('peak_release_ms', 'ms', 5, 200, 30, 'Adaptive limiter minimum release.')]}]


def expand(p):
    """Validated params -> ordinary children; all-off uses an exact unity gain.

    BB-00 requires a nonempty expansion, so the all-off identity is explicit.
    Engine assigns parent.1, parent.2, ... and records composite_of.
    """
    children = []
    if p['comp_on']:
        children.append({'type': 'compressor', 'params': {
            'threshold_db': p['comp_threshold_db'], 'ratio': 2, 'knee_db': 6,
            'attack_ms': 30, 'release_ms': 200}})
    if p['clip_on']:
        children.append({'type': 'clipper', 'params': {
            'ceiling_db': p['clip_ceiling_db'], 'drive_db': p['clip_drive_db'],
            'mode': 'soft', 'softness': .3}})
    if p['hf_on']:
        children.append({'type': 'dynamic_eq', 'params': {
            'shape': 'high_shelf', 'freq_hz': p['hf_freq_hz'],
            'threshold_db': p['hf_threshold_db'], 'range_db': p['hf_range_db']}})
    if p['peak_on']:
        children.append({'type': 'adaptive_limiter', 'params': {
            'ceiling_db': p['peak_ceiling_db'], 'release_min_ms': p['peak_release_ms']}})
    return children or [{'type': 'gain', 'params': {'gain_db': 0}}]


IMPLS = {}
COMPOSITES = {'limiter_chain': expand}
