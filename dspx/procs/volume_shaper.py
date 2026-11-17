"""Periodic dB shape on the absolute sample clock, with replayable smoothing."""
from mankomix.dspx.params import _f, _e

_notes = ['none'] + [f'1/{d}{m}' for d in (1, 2, 4, 8, 16, 32, 64) for m in ('', 'd', 't')]
SPECS = [{
    'type': 'volume_shaper', 'implemented': True,
    'description': 'Periodic normalized curve mapped linearly to dB gain.',
    'params': [{'id': 'shape', 'type': 'curve', 'unit': None, 'x_min': 0, 'x_max': 1,
                'y_min': 0, 'y_max': 1, 'max_points': 64, 'default': [[0, 0], [.25, 1], [1, 1]],
                'description': 'Cycle phase and normalized recovery.'},
               _f('depth_db', 'dB', 0, 48, 6, 'Maximum attenuation.'),
               _e('note', _notes, '1/4', 'Synchronized period.'),
               _f('bpm', 'BPM', 0, 400, 0, 'Tempo; required with a note.'),
               _f('period_ms', 'ms', 10, 8000, 500, 'Free period when note is none.'),
               _f('origin_s', 's', 0, 36000, 0, 'Absolute phase-zero origin.'),
               _f('phase', None, 0, 1, 0, 'Phase offset in cycles.'),
               _f('smooth_ms', 'ms', 0, 50, 2, 'Symmetric one-pole dB smoothing.'),
               _f('band_lo_hz', 'Hz', 0, 20000, 0, 'Lower band edge; paired zeros select full band.'),
               _f('band_hi_hz', 'Hz', 0, 24000, 0, 'Upper band edge.'),
               _e('interp', ['linear', 'smooth'], 'linear', 'Linear dB or monotone cubic.')],
    'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': False,
    'backends': ['reference'], 'channel_ok': True,
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0}}]
TIME_VARYING = {'volume_shaper'}


def check(p):
    from mankomix.dspx.bb.curves import period_ms
    from mankomix.dspx.bb.keyed import validate_shape, validate_band
    # The specified defaults carry an unresolved quarter note at BPM=0.
    # Keep that declaration valid; execution must resolve its tempo first.
    period_ms(p['period_ms'], note='none' if p['bpm'] == 0 else p['note'], bpm=p['bpm'])
    validate_shape(p['shape'], 64, monotone=False)
    validate_band(p['band_lo_hz'], p['band_hi_hz'], full_band=True)


def modulation(frames, sr, p, *, start_sample=0):
    """Return dB gain at absolute samples, replaying smoothing from sample zero."""
    from mankomix.dspx.bb.curves import phase_positions, evaluate_curve, period_ms
    from mankomix.dspx.bb.dynamics import envelope_signed
    start = 0 if p['smooth_ms'] else start_sample
    count = frames + start_sample if p['smooth_ms'] else frames
    phase = phase_positions(count, sr, start_sample=start, period_ms=p['period_ms'],
                            note=p['note'], bpm=p['bpm'], origin_s=p['origin_s'], phase=p['phase'])
    # Quantize phase anchors with the same sample rounding and later-value
    # collision rule as director.curve, retaining fractional cycle periods.
    duration = period_ms(p['period_ms'], note=p['note'], bpm=p['bpm']) * sr / 1000
    knots = {int(round(float(u) * duration)): y for u, y in p['shape']}
    normalized = [[at / duration, y] for at, y in sorted(knots.items())]
    gain = -p['depth_db'] * (1 - evaluate_curve(normalized, phase, p['interp']))
    if p['smooth_ms']:
        gain = envelope_signed(gain, sr, p['smooth_ms'])[start_sample:]
    return gain


def volume_shaper(x, sr, p, *, seed=0, start_sample=0):
    from mankomix.dspx.bb.curves import period_ms
    from mankomix.dspx.bb.keyed import band_gain, validate_band
    period_ms(p['period_ms'], note=p['note'], bpm=p['bpm'])
    validate_band(p['band_lo_hz'], p['band_hi_hz'], sr, full_band=True)
    y = x.copy() if p['depth_db'] == 0 else band_gain(
        x, sr, modulation(len(x), sr, p, start_sample=start_sample), p['band_lo_hz'], p['band_hi_hz'])
    return y, sr, {'latency_samples': 0, 'depth_db': p['depth_db']}


CROSS_VALIDATE = {'volume_shaper': check}
IMPLS = {'volume_shaper': volume_shaper}
