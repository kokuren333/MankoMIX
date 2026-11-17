"""T10-04..06 bidirectional robust AR residual detection and local LSAR.

resolve_kind_params(raw) fills only omitted kind-dependent defaults. The
current engine fills scalar defaults before cross-validation; callers needing
kind-specific defaults must use this helper until a generic resolver exists.
"""
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
    for k, v in KIND_DEFAULTS.get(out.get('kind', 'click'), {}).items():
        out.setdefault(k, v)
    return out


def validate(p):
    from mankomix.dspx.bb.restoration import validate_region
    validate_region(p)
    if p['band_lo_hz'] and p['band_hi_hz'] and p['band_hi_hz'] <= p['band_lo_hz']:
        raise ParamError('band_hi_hz must exceed band_lo_hz')


def _detect(v, sr, p):
    from mankomix.dspx.bb.ar import local_model, residual, robust_scale
    n = len(v)
    size = max(32, round(.02*sr))
    hop = max(1, size//2)
    order = max(2, round(p['ar_order']*sr/48000))
    score = np.zeros(n)
    weight = np.zeros(n)
    for start in range(-hop, n, hop):
        a, b = max(0, start), min(n, start+size)
        # Wider fitting context, with median-based impulsive winsorization.
        lo, hi = max(0, a-size), min(n, b+size)
        training = v[lo:hi]
        if len(training) < order*2+4 or not np.any(training):
            continue
        med = ndimage.median_filter(training, size=5, mode='nearest')
        diff = training-med
        cap = max(robust_scale(diff)*8, np.sqrt(np.mean(training**2))*.02, 1e-12)
        clean = med+np.clip(diff, -cap, cap)
        af, ab = local_model(clean, order), local_model(clean[::-1], order)
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


def declick(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.ar import lsar_gap
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
                score = _detect(source[:, ch], sr, p)
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
                hot &= ndimage.maximum_filter1d(corroborated, size=5)
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
                candidates = [(a, b) for a, b in runs(hot) if b-a <= maxlen]
                mask = np.zeros(len(x), bool)
                for a, b in candidates:
                    a, b = max(lo, a-guard), min(hi, b+guard)
                    mask[a:b] = True
                spans = runs(mask)
                for i, (a, b) in enumerate(spans):
                    context = max(round(.02*sr), p['ar_order']*8)
                    lc = max(0, a-context, spans[i-1][1] if i else 0)
                    rc = min(len(x), b+context, spans[i+1][0] if i+1 < len(spans) else len(x))
                    estimate, info = lsar_gap(wet[lc:a, ch], wet[b:rc, ch], b-a,
                                              order=max(2, round(p['ar_order']*sr/48000)))
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
    return definition('declick', rp_params()+[
        _e('kind', ['click', 'crackle', 'mouth'], 'click', 'Detector kind; use resolve_kind_params for dependent defaults.'),
        _f('threshold', 'sigma', 1.5, 20, 6, 'Robust prediction-error multiplier.'),
        _f('max_len_ms', 'ms', .1, 20, 4, 'Maximum detected event duration.'),
        _i('ar_order', None, 8, 128, 32, 'Maximum AR order at 48 kHz; scales with sample rate.'),
        _f('band_lo_hz', 'Hz', 0, 20000, 0, 'Detector low edge; zero is open.'),
        _f('band_hi_hz', 'Hz', 0, 24000, 0, 'Detector high edge; zero is open.'),
        _b('voiced_only', False, 'Restrict to voiced regions and 300 ms margins.'),
        _f('protect_transients', None, 0, 1, .7, 'Onset protection strength.'),
        _f('guard_ms', 'ms', 0, 2, .3, 'Expand detected events on both sides.'),
        _e('repair_band', ['full', 'detect_band'], 'full', 'Constrain the correction to the detector band.')])


SPECS = [_spec()]
IMPLS = {'declick': declick}
CROSS_VALIDATE = {'declick': validate}
