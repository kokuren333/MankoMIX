"""Conservative stereo alignment with a fixed, offline-compensated delay.

raw_azimuth_fix(..., compensate=False) exposes the buffered response for CT-5.
Positive correction_us means delay the right channel. Both causal paths
include the fixed base; after removing it only the earlier side is delayed.
"""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _e, _f


def latency_samples(sr, p=None):
    return int(np.ceil(sr*.0005))+128


def raw_azimuth_fix(x, sr, p, *, seed=0, compensate=False):
    from mankomix.dspx.bb.align import estimate_delay
    from mankomix.dspx.bb.delayline import fractional_delay, read_samples
    from mankomix.dspx.bb.restoration import region_mix, finish, validate_region
    validate_region(p)
    if x.shape[1] != 2:
        raise ParamError('azimuth_fix requires stereo input')
    if p['band_lo_hz'] >= sr/2:
        raise ParamError('band_lo_hz must be below Nyquist')
    latency = latency_samples(sr)
    cells, anchors, corrections = [], [], []
    n = len(x)
    if p['mode'] == 'manual':
        correction = p['delay_us']
        confidence = 'manual'
    else:
        size = max(8, round(p['track_s']*sr)) if p['track_s'] else max(8, n)
        hop = max(1, size//2)
        starts = range(0, max(1, n-size+1), hop) if p['track_s'] else [0]
        starts = sorted(set([*starts, max(0, n-size)]))
        for start in starts:
            stop = min(n, start+size)
            cell = estimate_delay(x[start:stop, 0], x[start:stop, 1], sr,
                                  max_delay_ms=p['max_us']*.001,
                                  band_hz=(p['band_lo_hz'], sr/2))
            # Opposite-polarity or independent stereo is not an azimuth fault.
            accepted = cell['reliable'] and cell['polarity'] == 1
            value = -cell['delay_samples']/sr*1e6 if accepted else 0.
            if abs(value) < .1:
                value = 0.
            cells.append(dict(start_s=start/sr, length_s=(stop-start)/sr,
                              correction_us=value, accepted=accepted, **cell))
            anchors.append((start+stop-1)/2)
            corrections.append(value)
        correction = float(np.median(corrections))
        confidence = 'high' if cells and all(c['accepted'] for c in cells) else 'low'
    wet = x.copy()
    if p['amount'] and n:
        if p['mode'] == 'auto' and p['track_s'] and len(anchors) > 1:
            curve = np.interp(np.arange(n), anchors, corrections)*sr/1e6
            if np.any(curve):
                delays = np.column_stack((np.maximum(-curve, 0), np.maximum(curve, 0)))
                positions = np.arange(n)[:, None]-delays
                for start in range(0, n, 2048):
                    stop = min(n, start+2048)
                    block = read_samples(x, positions[start:stop], 'sinc256')
                    active = delays[start:stop] > 0
                    wet[start:stop][active] = block[active]
        elif correction:
            d = correction*sr/1e6
            # Fixed nonnegative delays followed by exact common-delay removal.
            for c, delta in enumerate((max(-d, 0), max(d, 0))):
                if not delta:
                    continue
                pad = np.pad(x[:, c:c+1], ((0, latency), (0, 0)))
                wet[:, c] = fractional_delay(pad, latency+delta, 'sinc256')[latency:latency+n, 0]
    y = region_mix(x, wet, sr, p)
    # RP mixing must also preserve signed zeros on the unprocessed side.
    np.copyto(y, x, where=wet == x)
    out, _, stats = finish(x, y, sr, p, correction_us=correction, confidence=confidence,
                           delay_estimates=cells, latency_samples=latency, latency_compensated=compensate)
    if not compensate and latency:
        out = np.pad(out, ((latency, 0), (0, 0)))[:n]
    return out, sr, stats


def azimuth_fix(x, sr, p, *, seed=0):
    return raw_azimuth_fix(x, sr, p, seed=seed, compensate=True)


def validate(p):
    from mankomix.dspx.bb.restoration import validate_region
    validate_region(p)


from mankomix.dspx.bb.restoration import definition, rp_params
SPECS = [definition('azimuth_fix', rp_params()+[
    _e('mode', ['auto', 'manual'], 'auto', 'Estimate or specify differential delay.'),
    _f('delay_us', 'us', -500, 500, 0, 'Manual differential delay; positive delays right.'),
    _f('band_lo_hz', 'Hz', 1000, 8000, 3000, 'Analysis high-pass edge.'),
    _f('track_s', 's', 0, 60, 0, 'Zero uses a fixed estimate; otherwise tracking window.'),
    _f('max_us', 'us', 10, 500, 200, 'Maximum absolute estimated delay.')])]
SPECS[0]['description'] = 'Offline conservative high-frequency stereo alignment.'
SPECS[0]['implemented'] = True
SPECS[0]['realtime'].update(latency_samples='variable', latency_rule='ceil(sr * 0.0005) + 128; compensated offline')
IMPLS = {'azimuth_fix': azimuth_fix}
CROSS_VALIDATE = {'azimuth_fix': validate}
