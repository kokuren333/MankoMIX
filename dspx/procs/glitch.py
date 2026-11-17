"""Four PCG64 draws per numbered step; composed built-in glitch effects."""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _f, _i
from mankomix.dspx.bb.time_creative import definition, grid_params

KINDS = ('repeat', 'reverse', 'gate', 'stop', 'crush', 'shift', 'shuffle')
WEIGHTS = (1, .5, .5, .3, .3, .3, .5)


def validate(p, *, resolve_tempo=False):
    from mankomix.dspx.bb.time_creative import validate_grid
    validate_grid(p, ('chance_pattern',), resolve_tempo=resolve_tempo)
    if not any(p['w_'+name] for name in KINDS):
        raise ParamError('glitch weights must not all be zero')


def step_draws(step, seed=0, parameter_seed=0):
    """Exactly four uniforms, indexed by nonnegative absolute grid step."""
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(
        [int(seed) & 0xffffffff, (int(seed) >> 32) & 0xffffffff,
         int(parameter_seed), int(step)])))
    return rng.random(4)


def events(first, last, p, *, seed=0):
    """Return occupied-step records in [first,last), replaying overlap history.

    A continuing event owns its steps; probability-zero pattern slots interrupt
    it. Every step still draws four values. Length is uniform 1..length_max.
    Each occupied step is listed so unlisted steps are exact bypasses.
    """
    weights = np.asarray([p['w_'+name] for name in KINDS], dtype=float)
    cumulative = np.cumsum(weights)/weights.sum()
    out, pending, until = [], None, -1
    for k in range(max(0, last)):
        fire, kind, strength, length = step_draws(k, seed, p['seed'])
        probability = p['chance']*(p['chance_pattern'][k % p['steps']] if p['chance_pattern'] else 1)
        if probability == 0:
            pending, until = None, -1
        elif k >= until:
            pending = None
            if fire < probability:
                duration = 1+int(length*p['length_max'])
                until = k+duration
                pending = dict(onset_step=k, effect=KINDS[min(6, np.searchsorted(cumulative, kind, side='right'))],
                               strength=float(strength*p['intensity']), length=duration)
        if pending is not None and first <= k < last:
            out.append(dict(step=k, **pending))
    return out


def apply_event(x, sr, start, end, previous, record, p, *, seed=0):
    """Render one recorded step, calling stutter/bitcrush/tape_stop kernels."""
    from mankomix.dspx.bb.creative_rack import repeat_step, read_positions
    from mankomix.dspx.bb.time_creative import seam_gain
    effect, strength = record['effect'], record['strength']
    n = min(end, len(x))-start
    if effect == 'repeat':
        counts = (2, 3, 4, 6, 8, 12, 16, 32)
        return repeat_step(x, sr, start, end, counts[min(7, int(strength*8))], fade_ms=p['fade_ms'])
    if effect == 'gate':
        return np.zeros((n, x.shape[1]))
    if effect == 'crush':
        from mankomix.dspx.procs.bitcrush import bitcrush
        q = dict(bits=24-23*strength, rate_hz=max(100, sr*(1-.98*strength)),
                 antialias=False, hold='zoh', jitter=0, dither=0, quantizer='midtread',
                 mix=1, output_db=0, seed=0)
        wet = bitcrush(x[start:start+n], sr, q, seed=seed)[0]
    elif effect == 'stop':
        from mankomix.dspx.procs.tape_stop import tape_stop
        q = dict(stop_s=[0], start_s=[], stop_ms=(end-start)/sr*1000,
                 start_ms=0, curve=4-3.75*strength, resume='live', fade_ms=p['fade_ms'])
        wet = tape_stop(x[start:start+n], sr, q)[0]
    else:
        back = 1+min(3, int(strength*4)) if effect == 'shuffle' else 1
        a, b = previous(back)
        source = x[max(0, a):max(0, b)] if a >= 0 else x[:0]
        wet = np.zeros((n, x.shape[1]))
        if len(source):
            if effect == 'reverse':
                wet[:min(n, len(source))] = source[::-1][:n]
            else:
                speed = 2.**(2*strength-p['intensity']) if effect == 'shift' else 1
                pos = np.arange(n)*speed
                use = pos < len(source)
                wet[use] = read_positions(source, pos[use], start+np.arange(n)[use]-a)
    wet *= seam_gain(np.arange(n), end-start, p['fade_ms']*sr/1000)[:, None]
    return wet


def glitch(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.time_creative import grid, mix_active, active_mask
    validate(p, resolve_tempo=True)
    if not len(x):
        return x.copy(), sr, dict(events=[], random_draws_per_step=4)
    k, starts, ends = grid(len(x), sr, p)
    boundaries = {int(step): (int(starts[at]), int(ends[at]))
                  for at, step in zip(np.r_[0, np.flatnonzero(np.diff(k))+1], np.unique(k))}
    records = events(0, max(0, int(k[-1])+1), p, seed=seed)
    if p['mix'] == 0 or not records:
        return x.copy(), sr, dict(events=[], random_draws_per_step=4)
    wet, log = x.copy(), []
    active = active_mask(p, len(x), sr)
    for record in records:
        step = record['step']
        if step not in boundaries:
            continue
        start, end = boundaries[step]
        if start < 0 or not np.any(active[start:min(end, len(x))]):
            continue
        previous = lambda back, step=step: boundaries.get(step-back, (-1, -1))
        wet[start:min(end, len(x))] = apply_event(x, sr, start, end, previous, record, p, seed=seed)
        log.append(dict(record, start_sample=start, end_sample=min(end, len(x))))
    return mix_active(x, wet, p, sr), sr, dict(events=log, random_draws_per_step=4,
        overlap_rule='continuation owns step; zero-probability slots interrupt')


SPECS = [definition('glitch', grid_params()+[
    _f('chance', None, 0, 1, 0, 'Event probability per step.')]+[
    _f('w_'+kind, None, 0, 1, default, 'Relative event weight.') for kind, default in zip(KINDS, WEIGHTS)]+[
    _f('intensity', None, 0, 1, .5, 'Upper strength limit.'),
    _a('chance_pattern', None, 0, 1, 64, [], 'Empty or one multiplier per pattern step.'),
    _i('length_max', 'steps', 1, 8, 1, 'Maximum consecutive duration.'),
    _f('fade_ms', 'ms', .2, 20, 2, 'Linear step seam fade.'),
    _f('mix', None, 0, 1, 1, 'Wet fraction.'),
    _i('seed', None, 0, 65535, 0, 'Additional PCG64 seed.')], implemented=True)]
TIME_VARYING = {'glitch'}
IMPLS = {'glitch': glitch}
CROSS_VALIDATE = {'glitch': validate}
