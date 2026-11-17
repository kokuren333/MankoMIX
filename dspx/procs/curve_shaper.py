"""Six built-in shape targets, with no arbitrary-parameter dispatch.

modulation returns normalized control and absolute reset sample per frame;
target_control maps that shape into target units. render_with_history replays
full context before slicing, retaining filter/hold/read-clock state.
"""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _a, _f, _e
from mankomix.dspx.bb.time_creative import definition, note_choices

TARGETS = {
    'filter': (20, 20000, 200, 8000), 'pan': (-1, 1, -1, 1),
    'width': (0, 2, 0, 1), 'drive': (0, 36, 0, 18),
    'crush': (200, 48000, 2000, 48000), 'time': (0, 1, 0, 1)}


def resolve_target_params(params):
    """Fill only missing lo/hi with the selected built-in target's defaults.

    The caller's dictionary is never mutated. Explicit endpoints, including
    the filter defaults 200/8000 when used for crush, remain explicit.
    """
    out = dict(params or {})
    target = out.get('target', 'filter')
    if isinstance(target, str) and target in TARGETS:
        out.setdefault('lo', TARGETS[target][2])
        out.setdefault('hi', TARGETS[target][3])
    return out


def target_schema():
    """JSON Schema conditions for the six built-in endpoint units/ranges."""
    conditions = []
    for target, (lower, upper, lo, hi) in TARGETS.items():
        match = {'properties': {'target': {'const': target}}}
        if target != 'filter':
            match['required'] = ['target']
        endpoints = {key: dict(minimum=lower, maximum=upper, default=default)
                     for key, default in (('lo', lo), ('hi', hi))}
        conditions.append({'if': match, 'then': {'properties': endpoints}})
    return conditions


def patch_schema(params):
    """Attach target conditions, leaving defaults only on matching branches."""
    params['allOf'] = target_schema()
    for endpoint in ('lo', 'hi'):
        params['properties'][endpoint].pop('default', None)


def validate(p):
    from mankomix.dspx.bb.curves import period_ms
    from mankomix.dspx.bb.keyed import validate_shape, validate_band
    period_ms(p['period_ms'], note=p['note'] if p['bpm'] else 'none', bpm=p['bpm'])
    validate_shape(p['shape'], 64, monotone=False)
    validate_band(p['band_lo_hz'], p['band_hi_hz'], full_band=True)
    lower, upper, _, _ = TARGETS[p['target']]
    if not all(lower <= p[key] <= upper for key in ('lo', 'hi')):
        raise ParamError('lo and hi must lie within the selected target range')
    if any(b <= a for a, b in zip(p['one_shot'], p['one_shot'][1:])):
        raise ParamError('one_shot must be strictly ascending')


def modulation(frames, sr, p, *, start_sample=0):
    """Return (normalized y, cycle reset samples); replay smoothing from zero.

    One-shots restart on the newest trigger, even when cycles overlap. Outside
    the triggered cycle, hold the shape endpoint; phase offsets the running
    cycle and clamps rather than wrapping it in one-shot mode.
    """
    from mankomix.dspx.bb.curves import period_ms, phase_positions, evaluate_curve
    from mankomix.dspx.bb.dynamics import envelope_signed
    duration = period_ms(p['period_ms'], note=p['note'], bpm=p['bpm'])*sr/1000
    count = frames+start_sample
    ids = np.arange(count)
    unwrapped = phase_positions(count, sr, period_ms=p['period_ms'], note=p['note'],
        bpm=p['bpm'], origin_s=p['origin_s'], phase=p['phase'], wrap=False)
    phase = np.remainder(unwrapped, 1)
    resets = np.rint(round(p['origin_s']*sr)+(np.floor(unwrapped)-p['phase'])*duration).astype(np.int64)
    running = np.ones(count, dtype=bool)
    if p['one_shot']:
        triggers = np.rint(np.asarray(p['one_shot'])*sr).astype(np.int64)
        ix = np.searchsorted(triggers, ids, side='right')-1
        resets = triggers[np.maximum(ix, 0)]
        running = (ix >= 0) & (ids-resets < duration)
        phase = np.clip((ids-resets)/duration+p['phase'], 0, 1)
        phase[~running] = 1
    knots = {int(round(float(u)*duration)): y for u, y in p['shape']}
    shape = [[at/duration, y] for at, y in sorted(knots.items())]
    if not p['one_shot']:
        # Reuse the accepted T01-09 clock/shape kernel, with normalized y.
        from mankomix.dspx.procs.volume_shaper import modulation as volume_modulation
        values = 1+volume_modulation(count, sr, dict(p, depth_db=1))
    else:
        values = evaluate_curve(shape, phase, p['interp'])
        if p['smooth_ms']:
            values = 1+envelope_signed(values-1, sr, p['smooth_ms'])
        values[~running] = p['shape'][-1][1]
    # A held endpoint outside a one-shot starts its read clock at the end of
    # the most recent cycle; pre-trigger endpoint playback starts at zero.
    if p['one_shot']:
        resets = np.where(running, resets, np.where(ids < triggers[0], 0, np.rint(resets+duration)))
    return values[start_sample:], resets[start_sample:]


def target_control(frames, sr, p, *, start_sample=0):
    """Return (target-unit values, reset samples), with log Hz interpolation."""
    y, resets = modulation(frames, sr, p, start_sample=start_sample)
    if p['target'] in ('filter', 'crush'):
        return np.exp(np.log(p['lo'])+y*np.log(p['hi']/p['lo'])), resets
    return p['lo']+(p['hi']-p['lo'])*y, resets


def variable_crush(x, sr, rate):
    """ZOH clock reduction; constant controls delegate to T07-12 verbatim.

    Variable clocks interpolate cumulative clock cycles, then round absolute
    crossing times to samples (the same rounding as bitcrush). No dithering,
    jitter, prefilter or amplitude quantization is enabled in this target.
    """
    from mankomix.dspx.procs.bitcrush import bitcrush
    if not len(x):
        return x.copy()
    if np.all(rate == rate[0]):
        p = dict(bits=24, rate_hz=float(rate[0]), antialias=False, hold='zoh',
                 jitter=0, dither=0, quantizer='midtread', mix=1, output_db=0, seed=0)
        return bitcrush(x, sr, p)[0]
    clock = np.r_[0, np.cumsum(np.minimum(rate[:-1], sr)/sr)]
    crossings = np.arange(int(np.floor(clock[-1]))+1)
    points = np.unique(np.rint(np.interp(crossings, clock, np.arange(len(x)))).astype(int))
    ix = points[np.searchsorted(points, np.arange(len(x)), side='right')-1]
    return x[ix]


def time_positions(speed, resets):
    """Integrate read speed in sample units, resetting at each absolute cycle.

    Left-endpoint sample integration; a constant rate uses direct multiplication
    for exact agreement with the fixed halftime read clock.
    """
    positions = np.empty(len(speed))
    for a, b in zip(np.r_[0, np.flatnonzero(np.diff(resets))+1],
                    np.r_[np.flatnonzero(np.diff(resets))+1, len(speed)]):
        if a == b:
            continue
        if np.all(speed[a:b] == speed[a]):
            positions[a:b] = resets[a]+(np.arange(a, b)-resets[a])*speed[a]
        else:
            positions[a:b] = resets[a]+np.r_[0, np.cumsum(speed[a:b-1])]
    return positions


def process_target(x, sr, p, control, resets):
    """Apply exactly one of the six built-in kernels to a whole input band."""
    target = p['target']
    if target == 'filter':
        from mankomix.dspx.bb.svf import svf
        return svf(x, sr, control, p['resonance_db'], mode=p['filter_type'])
    if target == 'pan':
        from mankomix.dsp.reference.basic import pan
        from mankomix.dspx.bb.motion import pan_audio
        if len(control) and np.all(control == control[0]):
            return pan(x, sr, dict(position=float(control[0]), center_db=-3))[0]
        return pan_audio(x, control)
    if target == 'width':
        if x.shape[1] != 2:
            return x.copy()
        mid, side = .5*(x[:, 0]+x[:, 1]), .5*(x[:, 0]-x[:, 1])
        return np.column_stack((mid+control*side, mid-control*side))
    if target == 'drive':
        from mankomix.dspx.bb.nonlinear import oversampled
        if not len(x):
            return x.copy()
        def curve(up):
            db = np.interp(np.arange(len(up))/4, np.arange(len(x)), control)
            gain = 10.**(db[:, None]/20)
            return np.tanh(gain*up)/gain
        return oversampled(x, 4, curve)
    if target == 'crush':
        return variable_crush(x, sr, control)
    from mankomix.dspx.bb.creative_rack import read_positions
    wet = read_positions(x, time_positions(control, resets))
    wet[control == 0] = 0
    return wet


def curve_shaper(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.keyed import validate_band
    from mankomix.dspx.bb.curves import period_ms
    validate(p)
    period_ms(p['period_ms'], note=p['note'], bpm=p['bpm'])
    validate_band(p['band_lo_hz'], p['band_hi_hz'], sr, full_band=True)
    stats = dict(target=p['target'], latency_samples=0, drive_oversample=4,
                 time_reset='absolute cycle start; zero speed is silent')
    if p['amount'] == 0 or p['mix'] == 0 or not len(x):
        return x.copy(), sr, stats
    source = x
    if p['band_lo_hz']:
        from mankomix.dspx.bb.crossover import split_bands
        bands, _ = split_bands(x, sr, [p['band_lo_hz'], p['band_hi_hz']], 'linear')
        source = bands[1]
    control, resets = target_control(len(x), sr, p)
    wet = process_target(source, sr, p, control, resets)
    dry, original = source, x
    if wet.shape[1] != x.shape[1]:
        dry, original = np.repeat(source, 2, axis=1), np.repeat(x, 2, axis=1)
    fraction = p['amount']*p['mix']
    if not p['band_lo_hz'] and fraction == 1:
        return wet, sr, stats
    return original+fraction*(wet-dry), sr, stats


def render_with_history(x, sr, p, *, seed=0, history=None):
    """Replay the prefix and return its following excerpt, preserving all state."""
    if history is None:
        return curve_shaper(x, sr, p, seed=seed)
    y, rate, stats = curve_shaper(np.concatenate([history, x]), sr, p, seed=seed)
    return y[len(history):], rate, stats


def parameters():
    """T01-09 shape/clock contract, without its volume-only depth parameter."""
    params = [dict(id='shape', type='curve', unit=None, x_min=0, x_max=1,
                   y_min=0, y_max=1, max_points=64, default=[[0, 0], [.25, 1], [1, 1]],
                   description='Normalized cycle shape.'),
        _e('note', note_choices(), '1/4', 'Synchronized period.'),
        _f('bpm', 'BPM', 0, 400, 0, 'Explicit fixed tempo.'),
        _f('period_ms', 'ms', 10, 8000, 500, 'Free period.'),
        _f('origin_s', 's', 0, 36000, 0, 'Absolute phase origin.'),
        _f('phase', None, 0, 1, 0, 'Cycle phase offset.'),
        _f('smooth_ms', 'ms', 0, 50, 2, 'One-pole smoothing.'),
        _f('band_lo_hz', 'Hz', 0, 20000, 0, 'Lower band edge; both zero selects full band.'),
        _f('band_hi_hz', 'Hz', 0, 24000, 0, 'Upper band edge.'),
        _e('interp', ['linear', 'smooth'], 'linear', 'Shape interpolation.')]
    return params+[
        _e('target', list(TARGETS), 'filter', 'One built-in target.'),
        _f('amount', None, 0, 1, 0, 'Effect proportion; zero bypasses bit exactly.'),
        _f('lo', None, -1, 48000, 200, 'Target-specific lower shape endpoint.'),
        _f('hi', None, -1, 48000, 8000, 'Target-specific upper shape endpoint.'),
        _a('one_shot', 's', 0, 36000, 256, [], 'Strictly ascending trigger times.'),
        _e('filter_type', ['lowpass', 'bandpass', 'highpass'], 'lowpass', 'SVF output.'),
        _f('resonance_db', 'dB', 0, 24, 6, 'SVF peak gain.'),
        _f('mix', None, 0, 1, 1, 'Wet proportion.')]


SPECS = [definition('curve_shaper', parameters(), implemented=True)]
TIME_VARYING = {'curve_shaper'}
IMPLS = {'curve_shaper': curve_shaper}
CROSS_VALIDATE = {'curve_shaper': validate}
RESOLVE_PARAMS = {'curve_shaper': resolve_target_params}
SCHEMA_PATCH = {'curve_shaper': patch_schema}
