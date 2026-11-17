"""T10-07 plateau detection and eight-pass inequality-constrained LSAR."""
import numpy as np
from scipy import signal
from mankomix.dspx.params import _e, _f, _i


def _models(v, missing, sr, order):
    """Observed-only forward/reverse fits with well-conditioned sparse lags.

    At high rates, fit a common recurrence across interleaved sample phases
    near 8 kHz. Phase boundaries are masked, never joined as observations.
    Expand its coefficients onto sparse original-rate lags; no audio is
    resampled and every original observed sample remains an exact constant.
    This avoids a nearly singular high-order difference operator at 96 kHz.
    """
    from mankomix.dspx.bb.ar import robust_observed_model
    stride = max(1, round(sr/8000)) if sr > 16000 else 1
    models = []
    for data, holes in ((v, missing), (v[::-1], missing[::-1])):
        if stride > 1:
            data = np.concatenate([np.r_[data[k::stride], np.zeros(order)] for k in range(stride)])
            holes = np.concatenate([np.r_[holes[k::stride], np.ones(order, bool)] for k in range(stride)])
        model = robust_observed_model(data, holes, order)
        expanded = np.zeros((len(model)-1)*stride+1)
        expanded[::stride] = model
        models.append(expanded)
    return models


def declip(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.ar import lsar_gap, observed_model, joint_lsar
    from mankomix.dspx.bb.restoration import runs, region, region_mix, finish
    lo, hi = region(len(x), sr, p)
    wet = x.copy()
    levels, count, solves = [], 0, []
    mask = np.zeros_like(x, dtype=bool)
    unavailable = np.zeros_like(mask)
    if p['amount'] and hi > lo:
        for ch in range(x.shape[1]):
            v = x[:, ch]
            thresholds = []
            if not p['threshold_db'] and len(np.unique(v)) <= 2:
                levels.append({'positive': None, 'negative': None})
                continue
            for sign in (1, -1):
                u = v*sign
                level = 10**(p['threshold_db']/20) if p['threshold_db'] else None
                if level is None and len(u):
                    # The endpoint atom in the signed amplitude histogram is
                    # represented by repeated samples at the positive maximum.
                    top = float(np.max(u))
                    near = abs(u-top) <= max(1e-12, abs(top)*1e-8)
                    flat = [(a, b) for a, b in runs(near) if b-a >= p['min_run']]
                    if top > 0 and sum(b-a for a, b in flat) >= p['min_run']:
                        level = float(np.median(u[near]))
                thresholds.append(level)
                if level is None:
                    continue
                candidate = u >= level*(1-1e-8)
                unavailable[:, ch] |= candidate
                for a, b in runs(candidate):
                    if a < lo or b > hi or not p['min_run'] <= b-a <= round(p['max_run_ms']*sr/1000):
                        continue
                    mask[a:b, ch] = True
            levels.append({'positive': thresholds[0], 'negative': thresholds[1]})
        for ch in range(x.shape[1]):
            spans = runs(mask[:, ch])
            if p['oversample'] == 1 and spans:
                # Fit only observed rows, including exclusion of short plateaus
                # which are not eligible for output repair. Solve neighboring
                # holes together rather than treating clipped neighbors as data.
                size = max(round(.1*sr), 8*p['ar_order'])
                for start in range(lo, hi, size):
                    stop = min(hi, start+size)
                    if not mask[start:stop, ch].any():
                        continue
                    a, b = max(0, start-size), min(len(x), stop+size)
                    v, missing = x[a:b, ch], unavailable[a:b, ch]
                    models = _models(v, missing, sr, p['ar_order'])
                    positive, negative = levels[ch]['positive'], levels[ch]['negative']
                    lower = np.where(v > 0, positive if positive is not None else -np.inf, -np.inf)
                    upper = np.where(v < 0, -negative if negative is not None else np.inf, np.inf)
                    estimate, info = joint_lsar(v, missing, models=models, lower=lower, upper=upper)
                    selected = mask[start:stop, ch]
                    wet[start:stop, ch][selected] = estimate[start-a:stop-a][selected]
                    solves.append(info)
                count += int(np.count_nonzero(mask[:, ch]))
                continue
            model_cache = {}
            for i, (a, b) in enumerate(spans):
                factor = p['oversample']
                context = max(p['ar_order']*8, round(.02*sr))
                left = x[max(0, a-context, spans[i-1][1] if i else 0):a, ch]
                right = x[b:min(len(x), b+context, spans[i+1][0] if i+1 < len(spans) else len(x)), ch]
                sign = np.sign(x[a, ch])
                level = levels[ch]['positive' if sign > 0 else 'negative']
                cell = a//context
                if cell not in model_cache:
                    model_lo, model_hi = max(0, (cell-1)*context), min(len(x), (cell+2)*context)
                    model_cache[cell] = [
                        observed_model(x[model_lo:model_hi, ch], mask[model_lo:model_hi, ch], p['ar_order']),
                        observed_model(x[model_lo:model_hi, ch][::-1], mask[model_lo:model_hi, ch][::-1], p['ar_order'])]
                model, reverse_model = model_cache[cell]
                if factor > 1:
                    # Oversample clean contexts separately so plateau samples
                    # cannot leak into the fitted model through the FIR.
                    left = signal.resample_poly(left, factor, 1) if len(left) else left
                    right = signal.resample_poly(right, factor, 1) if len(right) else right
                estimate, info = lsar_gap(left, right, (b-a)*factor, order=p['ar_order']*factor,
                                          lower=level if sign > 0 else None,
                                          upper=-level if sign < 0 else None, iterations=8,
                                          models=[model, reverse_model] if factor == 1 else None)
                if factor > 1:
                    estimate = signal.resample_poly(estimate, 1, factor)[:b-a]
                    estimate = np.maximum(estimate, level) if sign > 0 else np.minimum(estimate, -level)
                wet[a:b, ch] = estimate
                solves.append(info)
                count += b-a
    peak = float(np.max(abs(wet))) if wet.size else 0
    gain = min(1., 1/peak) if peak and p['headroom'] == 'auto' and count else 1.
    # Headroom applies to the RP region as well, preserving exact samples outside.
    if gain < 1:
        wet *= gain
    y = region_mix(x, wet, sr, p)
    return finish(x, y, sr, p, clip_levels=levels, clipped_sample_fraction=count/max(1, x.size),
                  reconstructed_peak=peak, headroom_db=float(20*np.log10(gain)), ar_solves=solves[:2000])


def _spec():
    from mankomix.dspx.bb.restoration import definition, rp_params
    spec = definition('declip', rp_params()+[
    _f('threshold_db', 'dBFS', -24, 0, 0, 'Zero: estimate positive and negative plateau levels.'),
    _i('min_run', 'samples', 2, 32, 2, 'Minimum clipped run length.'),
    _f('max_run_ms', 'ms', .5, 20, 5, 'Maximum clipped run length.'),
    _i('ar_order', None, 8, 128, 48, 'Maximum AR model order.'),
    _e('headroom', ['auto', 'none'], 'auto', 'Attenuate reconstructed peaks above full scale.'),
    _e('oversample', [1, 2, 4], 1, 'Clean context interpolation factor.')])
    spec['implemented'] = True
    return spec


def validate(p):
    from mankomix.dspx.bb.restoration import validate_region
    validate_region(p)


SPECS = [_spec()]
IMPLS = {'declip': declip}
CROSS_VALIDATE = {'declip': validate}
