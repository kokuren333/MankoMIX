"""Pitch vibrato via cubic fractional delay, with declared integer base latency."""
import numpy as np

from mankomix.dspx.params import _f
from mankomix.dspx.bb.modulation import (mod_params, mod_rate, pitch_delay, pitch_latency,
                                        read_modulated, modulation_definition, validate_mod)
from mankomix.dspx.bb.delayline import spatial_stats


def onset_envelope(x, sr, onset_ms):
    """Wait onset_ms after a -50 dBFS upward crossing; 10 ms smooth entry."""
    if not onset_ms:
        return np.ones(len(x))
    active = np.max(np.abs(x), axis=1) > 10**(-50/20)
    # Ignore individual zero crossings; a 20 ms silence re-arms the onset.
    release = max(1, round(.02*sr))
    last, began = -release, None
    out = np.zeros(len(x))
    wait = round(onset_ms*.001*sr)
    for n in range(len(x)):
        if active[n]:
            if n-last >= release:
                began = n
            last = n
        if began is not None:
            u = np.clip((n-began-wait)/max(1, round(.01*sr)), 0, 1)
            out[n] = u*u*(3-2*u)
    return out


def raw_vibrato(x, sr, p, *, seed=0, compensate=False):
    mod_rate(p)
    latency = pitch_latency(sr, p)
    d = pitch_delay(len(x), sr, p, x.shape[1], seed=seed)
    d *= onset_envelope(x, sr, p['onset_ms'])[:, None]
    y = read_modulated(x, d, latency=latency, compensate=compensate)
    return y, sr, {'latency_samples': latency, 'latency_compensated': compensate,
                   'base_delay_ms': 1000*latency/sr}


def vibrato(x, sr, p, *, seed=0):
    y, _, stats = raw_vibrato(x, sr, p, seed=seed, compensate=True)
    stats.update({k: v for k, v in spatial_stats(y, sr).items() if k != 'latency_samples'})
    return y, sr, stats


SPECS = [modulation_definition('vibrato', mod_params(5, .5, 0, None) + [
    _f('depth_cents', 'cent', 0, 200, 20, 'One-sided pitch excursion before depth scaling.'),
    _f('onset_ms', 'ms', 0, 2000, 0, 'Delay after silence before modulation begins.')],
    latency_rule='ceil(sr * expm1(200*ln(2)/1200) / (2*pi*resolved_rate_hz)) + 2; compensated offline', implemented=True)]
TIME_VARYING = {'vibrato'}
IMPLS = {'vibrato': vibrato}
CROSS_VALIDATE = {'vibrato': validate_mod}
