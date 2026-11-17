"""T10-04..06 bidirectional robust AR residual detection and LSAR."""
import numpy as np
from scipy import ndimage
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _b, _e, _f, _i

KIND_DEFAULTS = {
    'click': dict(threshold=6., max_len_ms=4., band_lo_hz=0., band_hi_hz=0., voiced_only=False, repair_band='full'),
    'crackle': dict(threshold=3.5, max_len_ms=1., band_lo_hz=0., band_hi_hz=0., voiced_only=False, repair_band='full'),
    'mouth': dict(threshold=4.5, max_len_ms=8., band_lo_hz=1500., band_hi_hz=12000., voiced_only=True, repair_band='detect_band')}


def resolve_kind_params(raw):
    """Return a copy with kind-dependent defaults, retaining explicit values."""
    out = dict(raw or {})
    kind = out.get('kind', 'click')
    defaults = KIND_DEFAULTS.get(kind, {}) if isinstance(kind, str) else {}
    for k, v in defaults.items():
        out.setdefault(k, v)
    return out


def patch_schema(params):
    """Advertise conditional defaults without claiming one scalar fits all kinds."""
    for pid in KIND_DEFAULTS['click']:
        params['properties'][pid].pop('default', None)
    params['allOf'] = [
        {'if': {'properties': {'kind': {'const': kind}}, 'required': ['kind']},
         'then': {'properties': {pid: {'default': value} for pid, value in defaults.items()}}}
        for kind, defaults in KIND_DEFAULTS.items()]
    params['allOf'].append({'if': {'not': {'required': ['kind']}},
                            'then': {'properties': {pid: {'default': value}
                                                    for pid, value in KIND_DEFAULTS['click'].items()}}})


def validate(p):
    from mankomix.dspx.bb.restoration import validate_region
    validate_region(p)
    if p['band_lo_hz'] and p['band_hi_hz'] and p['band_hi_hz'] <= p['band_lo_hz']:
        raise ParamError('band_hi_hz must exceed band_lo_hz')


def _detect(v, sr, p):
    from mankomix.dspx.bb.ar import robust_observed_model, residual, robust_scale
    n = len(v)
    size = max(32, round(.02*sr))
    hop = max(1, size//2)
    order = max(2, round(p['ar_order']*sr/48000))
    score = np.zeros(n)
    weight = np.zeros(n)
    models = {}
    for start in range(-hop, n, hop):
        a, b = max(0, start), min(n, start+size)
        # Wider fitting context and trimmed observed-row covariance refinement.
        lo, hi = max(0, a-size), min(n, b+size)
        training = v[lo:hi]
        if len(training) < order*2+4 or not np.any(training):
            continue
        cell = a//(2*size)
        if cell not in models:
            missing = np.zeros(len(training), bool)
            models[cell] = [robust_observed_model(training, missing, order, trim=.8, score_fraction=.8),
                            robust_observed_model(training[::-1], missing, order, trim=.8, score_fraction=.8)]
        af, ab = models[cell]
        ef = residual(training, af)
        eb = residual(training[::-1], ab)[::-1]
        valid = slice(max(len(af), len(ab)), -max(len(af), len(ab)))
        scale_f = max(robust_scale(ef[valid]), np.sqrt(np.mean(training**2))*1e-5, 1e-12)
        scale_b = max(robust_scale(eb[valid]), np.sqrt(np.mean(training**2))*1e-5, 1e-12)
        local = np.minimum(abs(ef)/scale_f, abs(eb)/scale_b)[a-lo:b-lo]
        w = np.sin(np.pi*(np.arange(a, b)-start+.5)/size)**2
        score[a:b] += local*w
        weight[a:b] += w
    return score/np.maximum(weight, 1e-20)


def _periodic_reference(v, sr):
    """Verify an integer seasonal AR lag using robust repeated observations.

    A tightly agreeing cluster of at least three neighboring periods supplies
    a reference only for strongly periodic material. This distinguishes voiced
    excitation, which repeats, from impulsive corruption. Unverified signals
    use the short-term Burg detector and covariance LSAR instead.
    """
    rms = float(np.sqrt(np.mean(v*v))) if len(v) else 0
    if not rms or len(v) < round(.08*sr):
        return None
    low, high = max(2, round(sr/500)), min(round(sr/60), len(v)//8)
    samples = np.linspace(high, len(v)-1, min(4096, len(v)-high), dtype=int)
    local_rms = np.sqrt(np.maximum(0., ndimage.uniform_filter1d(v*v, max(3, round(.01*sr)))))
    normalization = np.maximum(local_rms[samples], rms*.01)
    errors = np.array([np.median(abs(v[samples]-v[samples-lag])/normalization)
                       for lag in range(low, high+1)])
    if not len(errors) or np.min(errors) > .002:
        return None
    lag = low+int(np.flatnonzero(errors <= np.min(errors)*1.1+1e-8)[0])
    values = np.full((8, len(v)), np.nan)
    for row, offset in enumerate((-4, -3, -2, -1, 1, 2, 3, 4)):
        shift = offset*lag
        a, b = max(0, -shift), min(len(v), len(v)-shift)
        values[row, a:b] = v[a+shift:b+shift]
    values.sort(axis=0)
    widths = values[2:]-values[:-2]
    widths[~np.isfinite(widths)] = np.inf
    choice = np.argmin(widths, axis=0)
    indices = np.arange(len(v))
    reference = sum(values[choice+k, indices] for k in range(3))/3
    reliable = np.min(widths, axis=0) <= rms*.002
    # A nonstationary attack is not a periodic defect. Require matching local
    # background as well as repeated reference values.
    error = abs(v-reference)
    background = ndimage.median_filter(error, size=max(3, 2*lag+1), mode='nearest')
    reliable &= background < np.maximum(local_rms, rms*.01)*.002
    return reference, reliable, lag


def declick(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.ar import lsar_gap, robust_observed_model, joint_lsar
    from mankomix.dspx.bb.restoration import band, runs, region, region_mix, finish
    from mankomix.dspx.bb.onsets import detect_onsets
    validate(p)
    lo, hi = region(len(x), sr, p)
    wet = x.copy()
    detect = band(x, sr, p['band_lo_hz'], p['band_hi_hz']) if p['amount'] and len(x) else x
    allowed = np.zeros(len(x), bool)
    allowed[lo:hi] = True
    # Both directions require a complete analysis half-window.
    edge = round(.02*sr)
    allowed[:edge] = False
    allowed[max(0, len(x)-edge):] = False
    if p['voiced_only'] and p['amount'] and len(x) and np.any(x):
        from mankomix.dspx.bb.pitch import detect_pitch
        track = detect_pitch(x, sr, method='yin', fmax=min(1000, sr*.45), hop_ms=20)
        voice = np.zeros(len(x), bool)
        low = band(x, sr, 0, min(1500, sr*.4))
        power = ndimage.uniform_filter1d(np.mean(low**2, axis=1), max(1, round(.01*sr)))
        active = power[track.samples] > max(float(np.max(power))*1e-4, 1e-10)
        for n in track.samples[track.voiced & active]:
            voice[max(0, n-round(.3*sr)):min(len(x), n+round(.3*sr)+1)] = True
        allowed &= voice
    maxlen = max(1, round(p['max_len_ms']*sr/1000))
    guard = round(p['guard_ms']*sr/1000)
    protection = np.ones(len(x))
    if p['protect_transients'] and p['amount'] and len(x) >= 32:
        for event in detect_onsets(x, sr):
            a = max(0, event['sample'])
            protection[a:min(len(x), a+maxlen)] *= 1-p['protect_transients']
    detected, solves = [], []
    passes = 2 if p['kind'] == 'crackle' else 1
    if p['amount'] and len(x) >= 32:
        for iteration in range(passes):
            source = detect if iteration == 0 else band(wet, sr, p['band_lo_hz'], p['band_hi_hz'])
            for ch in range(x.shape[1]):
                periodic = _periodic_reference(wet[:, ch], sr)
                score = _detect(source[:, ch], sr, p) if periodic is None else np.zeros(len(x))
                hot = (score*protection > p['threshold']) & allowed
                # High-curvature samples corroborate residuals; this prevents
                # smooth voiced-envelope changes from becoming short repairs.
                curvature = np.diff(source[:, ch], n=2, prepend=[source[0, ch], source[0, ch]])
                size = max(9, round(.02*sr))
                grid = np.arange(0, len(x)+size//2, max(1, size//2))
                scales = [1.482602218505602*np.median(abs(curvature[max(0, n-size//2):min(len(x), n+size//2)]))
                          if n-size//2 < len(x) else 0 for n in grid]
                sigma = np.interp(np.arange(len(x)), grid, scales)
                corroborated = abs(curvature) > p['threshold']*np.maximum(sigma, 1e-10)
                hot &= ndimage.maximum_filter1d(corroborated, size=5) | (score > p['threshold']*4)
                # Pair the opposite edges of a short offset impulse. A step
                # whose return edge exceeds max_len is deliberately excluded.
                jumps = np.flatnonzero(corroborated & allowed)
                for j, a in enumerate(jumps[:-1]):
                    if j and a-jumps[j-1] <= 2:
                        continue
                    for b in jumps[j+1:]:
                        if b-a > maxlen:
                            break
                        if b-a > 2 and curvature[a]*curvature[b] < 0:
                            hot[a:b+1] = allowed[a:b+1] & (protection[a:b+1] > .29)
                            break
                # Group residual lobes across a short click's interior.
                hot = ndimage.binary_closing(hot, structure=np.ones(max(1, round(.00015*sr))))
                if periodic is not None:
                    reference, reliable, lag = periodic
                    innovation = wet[:, ch]-reference
                    if p['band_lo_hz'] or p['band_hi_hz']:
                        innovation = band(innovation[:, None], sr, p['band_lo_hz'], p['band_hi_hz'])[:, 0]
                    difference = abs(innovation)
                    scale = max(float(np.sqrt(np.mean(source[:, ch]**2)))*.002, 1e-12)
                    # Seasonal forward/backward innovations corroborate each
                    # other through the three-period agreement requirement.
                    score = difference/scale
                    hot = (score*protection > p['threshold']) & reliable & allowed
                candidates = [(a, b) for a, b in runs(hot) if b-a <= maxlen]
                mask = np.zeros(len(x), bool)
                for a, b in candidates:
                    a, b = max(lo, a-guard), min(hi, b+guard)
                    mask[a:b] = True
                spans = runs(mask)
                if spans and periodic is not None:
                    model = np.zeros(lag+1)
                    model[0], model[-1] = 1., -1.
                    estimate, info = joint_lsar(wet[:, ch], mask, models=[model, model])
                    for a, b in spans:
                        change = estimate[a:b]-wet[a:b, ch]
                        if p['repair_band'] == 'detect_band':
                            padded = np.zeros((len(x), 1))
                            padded[a:b, 0] = change
                            change = band(padded, sr, p['band_lo_hz'], p['band_hi_hz'])[a:b, 0]
                        wet[a:b, ch] += change
                        detected.append({'start_s': a/sr, 'length_s': (b-a)/sr, 'channel': ch,
                                         'strength': float(np.max(score[a:b])), 'pass': iteration+1})
                    solves.append(info)
                    continue
                model_cache = {}
                for i, (a, b) in enumerate(spans):
                    context = max(round(.02*sr), p['ar_order']*8)
                    lc = max(0, a-context, spans[i-1][1] if i else 0)
                    rc = min(len(x), b+context, spans[i+1][0] if i+1 < len(spans) else len(x))
                    order = max(2, round(p['ar_order']*sr/48000))
                    cell = a//context
                    if cell not in model_cache:
                        ca, cb = max(0, (cell-1)*context), min(len(x), (cell+2)*context)
                        v, missing = wet[ca:cb, ch], mask[ca:cb]
                        model_cache[cell] = [robust_observed_model(v, missing, order),
                                             robust_observed_model(v[::-1], missing[::-1], order)]
                    estimate, info = lsar_gap(wet[lc:a, ch], wet[b:rc, ch], b-a,
                                              order=order, models=model_cache[cell])
                    change = estimate-wet[a:b, ch]
                    if p['repair_band'] == 'detect_band':
                        padded = np.zeros((len(x), 1))
                        padded[a:b, 0] = change
                        change = band(padded, sr, p['band_lo_hz'], p['band_hi_hz'])[a:b, 0]
                    wet[a:b, ch] += change
                    detected.append({'start_s': a/sr, 'length_s': (b-a)/sr, 'channel': ch,
                                     'strength': float(np.max(score[a:b])), 'pass': iteration+1})
                    solves.append(info)
    y = region_mix(x, wet, sr, p)
    return finish(x, y, sr, p, kind=p['kind'], passes=passes,
                  detected_event_count=len(detected), detected_events=detected[:2000], ar_solves=solves[:2000])


def _spec():
    from mankomix.dspx.bb.restoration import definition, rp_params
    spec = definition('declick', rp_params()+[
        _e('kind', ['click', 'crackle', 'mouth'], 'click', 'Detector kind; omitted dependent values follow kind.'),
        _f('threshold', 'sigma', 1.5, 20, 6, 'Robust prediction-error multiplier.'),
        _f('max_len_ms', 'ms', .1, 20, 4, 'Maximum detected event duration.'),
        _i('ar_order', None, 8, 128, 32, 'Maximum AR order at 48 kHz; scales with sample rate.'),
        _f('band_lo_hz', 'Hz', 0, 20000, 0, 'Detector low edge; zero is open.'),
        _f('band_hi_hz', 'Hz', 0, 24000, 0, 'Detector high edge; zero is open.'),
        _b('voiced_only', False, 'Restrict to voiced regions and 300 ms margins.'),
        _f('protect_transients', None, 0, 1, .7, 'Onset protection strength.'),
        _f('guard_ms', 'ms', 0, 2, .3, 'Expand detected events on both sides.'),
        _e('repair_band', ['full', 'detect_band'], 'full', 'Constrain the correction to the detector band.')])
    spec['implemented'] = True
    return spec


SPECS = [_spec()]
IMPLS = {'declick': declick}
CROSS_VALIDATE = {'declick': validate}
RESOLVE_PARAMS = {'declick': resolve_kind_params}
SCHEMA_PATCH = {'declick': patch_schema}
