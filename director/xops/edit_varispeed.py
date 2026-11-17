"""Band-limited speed/pitch-linked source playback on a fixed project timeline."""
from fractions import Fraction
import numpy as np
from scipy import signal
from mankomix.dsp.reference.export import resample_poly_hq
from mankomix.dspx.bb.pitchtime import _read
from . import OpSpec, DerivedPlan, ClipPlan
from . import _clip_edit as H


def resolve(move):
    p = H.resolve(move, {'speed': (.25, 4, None), 'semitones': (-24, 24, None)},
                  {'fit': (['keep_start', 'keep_length'], 'keep_start')}, {'section', 'ramp'})
    ramp = p.setdefault('ramp', [])
    if not isinstance(ramp, list) or len(ramp) > 1024 or any(
            not isinstance(v, list) or len(v) != 2 or not H.number(v[0]) or v[0] < 0
            or not H.number(v[1]) or not .25 <= v[1] <= 4 for v in ramp):
        raise ValueError('ramp needs at most 1024 [source_seconds, speed .25..4] points')
    if ramp and (len(ramp) < 2 or any(a[0] >= b[0] for a, b in zip(ramp, ramp[1:]))):
        raise ValueError('ramp source times must increase strictly')
    if sum(k in p for k in ('speed', 'semitones')) + bool(ramp) != 1:
        raise ValueError('choose exactly one of speed, semitones or ramp')
    if not ramp:
        p['speed'] = p.get('speed', 2**(p.get('semitones', 0)/12))
    return p


def validate(move, ctx):
    H.validate(move, ctx, resolve)
    if ctx.project is not None:
        try:
            p = resolve(move)
            a, b = H.interval(ctx.project.data, move['target'], p, ctx.project.rate)
            if p['ramp']:
                endpoints(p['ramp'], b-a, ctx.project.rate)
        except (ValueError, TypeError, KeyError) as exc:
            ctx.err('bad_value', str(exc))


def endpoints(ramp, n, sr):
    knots = np.asarray(ramp, dtype=float)
    if abs(knots[0, 0]) > .5/sr or abs(knots[-1, 0]-n/sr) > .5/sr:
        raise ValueError('ramp must cover exactly source time 0 through interval duration')
    return knots


def ramp_clock(ramp, n, sr):
    knots = endpoints(ramp, n, sr)
    spans = np.diff(knots[:, 0])
    slopes = np.diff(knots[:, 1])/spans
    durations = np.array([d/v if abs(k) < 1e-12 else np.log(w/v)/k
                          for d, v, w, k in zip(spans, knots[:-1, 1], knots[1:, 1], slopes)])
    ends = np.r_[0., np.cumsum(durations)]
    clock = np.arange(round(ends[-1]*sr))/sr
    i = np.minimum(np.searchsorted(ends, clock, side='right')-1, len(slopes)-1)
    dt = clock-ends[i]
    k, v = slopes[i], knots[i, 1]
    ds = v*dt
    active = abs(k) >= 1e-12
    ds[active] = v[active]*np.expm1(k[active]*dt[active])/k[active]
    return (knots[i, 0]+ds)*sr


def calculate(x, sr, p):
    if not p['ramp']:
        speed = p['speed']
        if speed == 1:
            return x.copy()
        frac = Fraction(1/speed).limit_denominator(4096)
        y = resample_poly_hq(x, frac.denominator, frac.numerator)
        return H.fitted(y, round(len(x)/speed))
    positions = ramp_clock(p['ramp'], len(x), sr)
    maximum = max(v for _, v in p['ramp'])
    if maximum > 1:
        taps, beta = signal.kaiserord(120, .06/maximum)
        kernel = signal.firwin(taps | 1, .97/maximum, window=('kaiser', beta))
        x = signal.fftconvolve(x, kernel[:, None], mode='same', axes=0)
    return _read(x, positions, 'sinc256')


def derive(root, move):
    p = resolve(move)
    x, sr, data, a, b = H.source(root, move, p)
    p.update(seed=0, requested_fit=p['fit'], fit='keep_length')
    if not p['ramp'] and p['speed'] == 1:
        return ClipPlan({}, p, H.record(x[a:b], x[a:b], sr, reason='unity speed; no derived asset'))
    y = calculate(x[a:b].copy(), sr, p)
    rec = H.record(x[a:b], H.fitted(y, b-a), sr, natural_frames=len(y), requested_fit=p['requested_fit'])
    rec['calculated_frames'] = len(y)
    return DerivedPlan(a, b, p, calculate, record=rec)


OPS = {'edit_varispeed': OpSpec('edit', ('target', 'params'), validate,
                                 derive=derive, code_version='w4d-varispeed-1')}
