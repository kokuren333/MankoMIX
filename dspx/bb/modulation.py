"""Shared MOD declarations and absolute-clock modulation utilities.

API: mod_params(rate, depth, stereo_phase, mix) returns fresh declarations;
mod_rate(p) resolves tempo; mod_lfo(frames, sr, p, channels=1,
start_sample=0, seed=0) returns frames x channels bipolar modulation.
pitch_delay(frames, sr, p, channels=1, start_sample=0, seed=0) returns
vibrato displacement in samples, with no base latency. read_modulated(x,
displacement, latency=0, compensate=True) uses the shared cubic delay reader.
Definitions and equations are original; BB-05 and BB-09 are reused.
"""
import numpy as np

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _e, _f, _i
from mankomix.dspx.bb.curves import lfo, period_ms, modulation_seed
from mankomix.dspx.bb.delayline import read_samples


def mod_params(rate, depth, stereo_phase, mix):
    notes = ['none'] + [f'1/{d}{m}' for d in (1, 2, 4, 8, 16, 32, 64) for m in ('', 'd', 't')]
    out = [_f('rate_hz', 'Hz', .01, 20, rate, 'Free-running LFO frequency.'),
           _e('note', notes, 'none', 'One LFO cycle as a note duration.'),
           _f('bpm', 'BPM', 0, 400, 0, 'Tempo; zero means unknown.'),
           _f('depth', None, 0, 1, depth, 'Modulation amount.'),
           _e('lfo_shape', ['sine', 'triangle', 'random'], 'sine', 'LFO waveform.'),
           _f('stereo_phase', None, 0, 1, stereo_phase, 'Right-channel phase in cycles.'),
           _f('origin_s', 's', 0, 36000, 0, 'Absolute time of phase zero.'),
           _f('phase', None, 0, 1, 0, 'Initial phase in cycles.')]
    if mix is not None:
        out.append(_f('mix', None, 0, 1, mix, 'Wet proportion; zero is exact bypass.'))
    return out + [_i('seed', None, 0, 65535, 0, 'Deterministic parameter seed.')]


def mod_rate(p):
    return 1000 / period_ms(1000 / p['rate_hz'], note=p['note'], bpm=p['bpm'])


def validate_mod(p):
    """Cross-validator for tempo relationships after scalar validation."""
    mod_rate(p)


def combined_seed(seed, p):
    """Combine the caller's project/item seed with the parameter seed."""
    return modulation_seed(seed, '', p.get('seed', 0))


def mod_lfo(frames, sr, p, channels=1, *, start_sample=0, seed=0):
    rate = mod_rate(p)
    if p['lfo_shape'] == 'random':
        return np.column_stack([bandlimited_walk(frames, sr, rate, start_sample=start_sample,
                                                phase=p['phase']+c*p['stereo_phase'],
                                                origin_s=p['origin_s'], seed=combined_seed(seed, p))
                                for c in range(channels)])
    return np.column_stack([lfo(frames, sr, shape=p['lfo_shape'], rate_hz=rate,
                               origin_s=p['origin_s'], phase=p['phase'] + c*p['stereo_phase'],
                               start_sample=start_sample, seed=combined_seed(seed, p))
                            for c in range(channels)])


def bandlimited_walk(frames, sr, rate, *, start_sample=0, phase=0., origin_s=0., seed=0):
    """Bounded Fourier random walk, strictly no components above rate Hz.

    Uses the shared tape walk's PCG64 grid and analytic interpolation; the
    Fourier amplitude sum bounds the result without nonlinear clipping.
    """
    from mankomix.dspx.bb.wobble import _random_motion
    samples = np.arange(start_sample, start_sample+frames, dtype=np.int64)
    # Quadrature rotation defines stereo phase for a nonperiodic signal and
    # makes phase=.5 an exact sign reversal, without changing its bandwidth.
    samples = samples - round(origin_s*sr)
    displacement, _, bound = _random_motion(samples, sr, rate, seed, phase)
    return displacement/bound if bound else displacement


def pitch_latency(sr, p):
    """Fixed base for the resolved rate, independent of depth and onset."""
    return int(np.ceil(sr * np.expm1(200*np.log(2)/1200) / (2*np.pi*mod_rate(p)))) + 2


def pitch_delay(frames, sr, p, channels=1, *, start_sample=0, seed=0):
    c = p['depth_cents']*p['depth']*np.log(2)/1200
    omega = 2*np.pi*mod_rate(p)
    if p['lfo_shape'] == 'sine':
        # A small second harmonic keeps BOTH cents extrema exact and the
        # mean speed at unity. A single sinusoidal delay cannot do both at
        # large excursions because cents is logarithmic.
        from mankomix.dspx.bb.curves import phase_positions
        phase = phase_positions(frames, sr, start_sample=start_sample,
                                period_ms=1000/mod_rate(p), origin_s=p['origin_s'],
                                phase=p['phase'])
        angle = 2*np.pi*(phase[:, None] + np.arange(channels)*p['stereo_phase'])
        return sr/omega * (-np.sinh(c)*np.sin(angle) + (1-np.cosh(c))*np.sin(2*angle)/2)
    return sr*np.expm1(c)/omega * mod_lfo(frames, sr, p, channels,
                                       start_sample=start_sample, seed=seed)


def read_modulated(x, displacement, *, latency=0, compensate=True):
    """Cubic reads; compensation removes the integer base only, including tails."""
    d = np.asarray(displacement, dtype=np.float64)
    if not compensate:
        # Controls live on the musical output clock. Delay them with the
        # signal in the causal probe so shifting the raw output removes
        # exactly the declared base, without advancing the modulation phase.
        delayed = np.zeros_like(d)
        if latency == 0:
            delayed = d
        elif latency < len(x):
            delayed[latency:] = d[:-latency]
        d = delayed
    timeline = np.arange(len(x), dtype=np.float64) - (0 if compensate else int(latency))
    positions = timeline[:, None] - d
    return read_samples(x, positions, 'lagrange3')


def modulation_definition(kind, params, *, channel=True, latency_rule=None, implemented=False):
    rt = {'block_ok': False, 'latency_samples': 0, 'allocates': True}
    if latency_rule:
        rt['latency_rule'] = latency_rule
    return {'type': kind, 'description': kind.replace('_', ' '), 'params': params,
            'stages': ['track', 'bus'], 'master_slot': None, 'realtime': rt,
            'offline_only': False, 'backends': ['reference'], 'channel_ok': channel,
            'implemented': implemented}
