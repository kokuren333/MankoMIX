"""T10-19 explicit AR gaps; spectral is reserved for the W3j implementation."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _b, _e, _f, _i


def validate(p):
    if len(p['t0_s']) != len(p['t1_s']):
        raise ParamError('t0_s and t1_s must have the same length')
    last = -1
    for a, b in zip(p['t0_s'], p['t1_s']):
        if b <= a or b-a > .500000000001 or a < last:
            raise ParamError('gaps must be ordered, nonoverlapping and at most 500 ms')
        if p['method'] == 'spectral' or p['method'] == 'auto' and b-a > .030000000001:
            raise ParamError('spectral interpolation is not implemented; select method=ar explicitly')
        last = b
    if p['method'] == 'spectral':
        raise ParamError('spectral interpolation is not implemented')


def interpolate(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.ar import lsar_gap, local_model, predict, innovation_gap
    from mankomix.dspx.bb.restoration import finish
    validate(p)
    y = x.copy()
    ncontext = max(2, round(p['context_ms']*sr/1000))
    gaps = [(min(len(x), round(a*sr)), min(len(x), round(b*sr)))
            for a, b in zip(p['t0_s'], p['t1_s'])]
    orders = []
    for i, (a, b) in enumerate(gaps):
        if b <= a:
            continue
        lo = max(0, a-ncontext, gaps[i-1][1] if i else 0)
        hi = min(len(x), b+ncontext, gaps[i+1][0] if i+1 < len(gaps) else len(x))
        for ch in range(x.shape[1]):
            left, right = x[lo:a, ch], x[b:hi, ch]
            texture, unpredictability = innovation_gap(left, right, b-a, order=p['ar_order'])
            if unpredictability >= .3:
                estimate = texture
                info = {'iterations': 0, 'orders': [], 'solver': 'residual_replay'}
            else:
                estimate, info = lsar_gap(left, right, b-a, order=p['ar_order'])
            info['innovation_power_ratio'] = unpredictability
            info['residual_replay'] = unpredictability >= .3
            # Blend the LS solution into the one-sided boundary predictions,
            # using only unknown samples. Known samples are never faded.
            fade = min((b-a)//2, round(p['fade_ms']*sr/1000))
            if fade and unpredictability < .3:
                f = predict(left, local_model(left, p['ar_order'], error_floor=1e-20), fade)
                r = predict(right[::-1], local_model(right[::-1], p['ar_order'], error_floor=1e-20), fade)[::-1]
                w = .5-.5*np.cos(np.linspace(0, np.pi, fade))
                estimate[:fade] = f*(1-w)+estimate[:fade]*w
                estimate[-fade:] = estimate[-fade:]*(1-w)+r*w
            y[a:b, ch] = estimate
            orders.append(info)
    return finish(x, y, sr, p, gap_count=sum(b > a for a, b in gaps), ar_solves=orders[:128])


SPECS = [{'type': 'interpolate', 'implemented': True,
          'description': 'Offline explicit AR gap interpolation; spectral is unavailable.',
          'stages': ['track', 'bus'], 'master_slot': None, 'offline_only': True,
          'backends': ['reference'], 'realtime': {'block_ok': False, 'latency_samples': 0, 'allocates': True},
          'params': [_b('delta', False, 'Output the removed signal.'),
                     _a('t0_s', 's', 0, 36000, 64, [], 'Ordered gap start times.'),
                     _a('t1_s', 's', 0, 36000, 64, [], 'Ordered gap end times, each at most 500 ms.'),
                     _e('method', ['auto', 'ar', 'spectral'], 'auto', 'Auto chooses AR up to 30 ms, otherwise spectral.'),
                     _i('ar_order', None, 16, 512, 512, 'Maximum AR model order; increased after voiced-gap measurements.'),
                     _f('context_ms', 'ms', 20, 2000, 300, 'Clean context on each side.'),
                     _f('fade_ms', 'ms', 0, 20, 2, 'Boundary prediction blend inside gaps.')]}]
IMPLS = {'interpolate': interpolate}
CROSS_VALIDATE = {'interpolate': validate}
