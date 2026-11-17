"""Absolute-clock dB tremolo and inverse-band LR4 harmonic tremolo.

Stereo phase .5 produces opposed dB envelopes, unlike equal-power autopan.
Square corners use the shared zero-initial-state one-pole, with the specified
63.212% tau. Excerpts replay that control history. Random uses BB-05's bounded
Fourier walk with bandwidth below the free or tempo-resolved rate. The engine
binds the item ID into seed; this type combines it with the seed parameter.
"""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e, _i
from mankomix.dspx.bb import crossover as C, curves as Q, dynamics as D
from mankomix.dspx.bb.delayline import spatial_stats

_notes = ['none'] + [f'1/{d}{m}' for d in (1, 2, 4, 8, 16, 32, 64) for m in ('', 'd', 't')]
SPECS = [{
    'type': 'tremolo', 'implemented': True,
    'description': 'Amplitude or harmonic dB tremolo; opposed stereo envelopes use a different law from autopan.',
    'params': [_f('rate_hz', 'Hz', .01, 20, 5, 'Free LFO frequency.'),
               _e('note', _notes, 'none', 'Synchronized LFO period.'),
               _f('bpm', 'BPM', 0, 400, 0, 'Tempo; note needs known tempo.'),
               _f('depth', None, 0, 1, .5, 'Depth multiplier.'),
               _f('stereo_phase', None, 0, 1, 0, 'Right LFO phase offset in cycles.'),
               _f('origin_s', 's', 0, 36000, 0, 'Absolute phase origin.'),
               _f('phase', None, 0, 1, 0, 'LFO phase in cycles.'),
               _i('seed', None, 0, 65535, 0, 'Random-walk seed.'),
               _e('mode', ['amplitude', 'harmonic'], 'amplitude', 'Modulation routing.'),
               _f('depth_db', 'dB', 0, 48, 6, 'Valley depth at full depth.'),
               _e('lfo_shape', ['sine', 'triangle', 'square', 'random'], 'sine', 'Modulation shape.'),
               _f('square_smooth_ms', 'ms', .5, 20, 3, 'Square corner time constant.'),
               _f('crossover_hz', 'Hz', 200, 4000, 800, 'Harmonic LR4 split.'),
               _f('bias', None, 0, 1, 0, 'Amplitude valley extension by a power warp.')],
    'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': False,
    'backends': ['reference'], 'channel_ok': True,
    'realtime': {'block_ok': False, 'allocates': True, 'latency_samples': 0}}]
TIME_VARYING = {'tremolo'}


def modulation(frames, sr, p, *, channels=2, seed=0, start_sample=0, item_id=None):
    """Bipolar LFO at absolute samples; square replays from zero for exact state."""
    Q.period_ms(1000/p['rate_hz'], note=p['note'], bpm=p['bpm'])
    square = p['lfo_shape'] == 'square'
    start, count = (0, start_sample+frames) if square else (start_sample, frames)
    values = []
    for ch in range(channels):
        generator = Q.bandlimited_random if p['lfo_shape'] == 'random' else Q.lfo
        shape = {} if p['lfo_shape'] == 'random' else {'shape': p['lfo_shape']}
        m = generator(count, sr, **shape, rate_hz=p['rate_hz'],
                  note=p['note'], bpm=p['bpm'], start_sample=start,
                  origin_s=p['origin_s'], phase=p['phase']+(p['stereo_phase'] if ch else 0),
                  seed=seed, item_id=item_id, parameter_seed=p['seed'])
        if square:
            m = D.envelope_signed(m, sr, p['square_smooth_ms'])[start_sample:]
        if p['mode'] == 'amplitude' and p['bias']:
            m = 2*((m+1)/2)**(1+3*p['bias'])-1
        values.append(m)
    return np.column_stack(values)


def tremolo(x, sr, p, *, seed=0, start_sample=0, item_id=None):
    Q.period_ms(1000/p['rate_hz'], note=p['note'], bpm=p['bpm'])
    if p['mode'] == 'harmonic' and p['crossover_hz'] >= .98*sr/2:
        raise ParamError('crossover_hz must be below 0.98 * Nyquist')
    if p['depth'] == 0 or p['depth_db'] == 0:
        y = x.copy()
    else:
        m = modulation(len(x), sr, p, channels=x.shape[1], seed=seed,
                       start_sample=start_sample, item_id=item_id)
        depth = p['depth_db']*p['depth']
        low_gain = -depth*(1-m)/2
        if p['mode'] == 'amplitude':
            y = D.apply_gain(x, low_gain)
        else:
            bands, _ = C.split_bands(x, sr, [p['crossover_hz']], 'minimum')
            y = D.apply_gain(bands[0], low_gain) + D.apply_gain(bands[1], -depth*(1+m)/2)
    return y, sr, spatial_stats(y, sr)


IMPLS = {'tremolo': tremolo}
