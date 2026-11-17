"""BB-21 independently written Burg estimation and least-squares AR repair.

burg(x, order) -> coefficients [1,a1,...] for x[t]+sum(a[k]*x[t-k]).
residual(x,a) -> same-length prediction errors; robust_scale -> MAD sigma.
predict(context,a,length) -> forward prediction; bidirectional -> blended
forward/backward predictions. interpolate(x,missing,order=32,context=512,
lower=None,upper=None) fits clean left/right context separately, then solves
joint forward/backward residual least squares only for missing samples.
Bounds (scalars or input-shaped arrays) constrain repaired samples only;
unmasked samples are copied bit for bit. Channels are modeled separately.
"""
import numpy as np
from scipy import signal, sparse, optimize, linalg
from scipy.sparse.linalg import spsolve
from mankomix.dsp.errors import ParamError


def burg(x, order=32):
    v = np.asarray(x, dtype=np.float64)
    if v.ndim != 1 or not np.isfinite(v).all() or not isinstance(order, (int, np.integer)) or order < 0:
        raise ParamError('Burg requires a finite vector and nonnegative integer order')
    order = min(order, max(0, len(v)-2))
    a = np.array([1.])
    f, b = v[1:].copy(), v[:-1].copy()
    for _ in range(order):
        den = float(f@f + b@b)
        if den <= np.finfo(float).tiny:
            break
        k = np.clip(-2*float(b@f)/den, -.999999, .999999)
        a = np.r_[a, 0.] + k*np.r_[0., a[::-1]]
        nf, nb = f+k*b, b+k*f
        f, b = nf[1:], nb[:-1]
    return a


def residual(x, coefficients):
    return signal.lfilter(np.asarray(coefficients, dtype=np.float64), [1.], np.asarray(x, dtype=np.float64), axis=0)


def robust_scale(x):
    v = np.asarray(x, dtype=np.float64)
    return float(1.482602218505602*np.median(np.abs(v-np.median(v)))) if v.size else 0.


def predict(context, coefficients, length):
    a = np.asarray(coefficients, dtype=np.float64)
    v = list(np.asarray(context, dtype=np.float64))
    if length < 0 or not len(a) or a[0] != 1 or not np.isfinite(a).all():
        raise ParamError('invalid prediction model or length')
    order = len(a)-1
    v = [0.]*max(0, order-len(v)) + v
    out = []
    for _ in range(length):
        value = -float(a[1:] @ np.asarray(v[-order:][::-1])) if order else 0.
        v.append(value)
        out.append(value)
    return np.asarray(out)


def bidirectional(left, right, length, *, order=32):
    f = predict(left, burg(left, order), length)
    b = predict(np.asarray(right)[::-1], burg(np.asarray(right)[::-1], order), length)[::-1]
    w = (np.arange(length)+1)/(length+1)
    return (1-w)*f+w*b


def interpolate(x, missing, *, order=32, context=512, lower=None, upper=None):
    a = np.asarray(x, dtype=np.float64)
    mono = a.ndim == 1
    a = a[:, None] if mono else a
    mask = np.asarray(missing)
    if mask.shape == (len(a),):
        mask = np.broadcast_to(mask[:, None], a.shape)
    if a.ndim != 2 or mask.shape != a.shape or mask.dtype != bool or context < 2 or order < 0 or not np.isfinite(a).all():
        raise ParamError('invalid AR interpolation input, mask, order or context')
    result = a.copy()
    bounds = []
    for value, default in ((lower, -np.inf), (upper, np.inf)):
        if value is None:
            bounds.append(np.full(a.shape, default))
        else:
            v = np.asarray(value, dtype=np.float64)
            if mono and v.ndim == 1:
                v = v[:, None]
            bounds.append(np.broadcast_to(v, a.shape))
    if np.any(bounds[0] >= bounds[1]) or any(np.isnan(v).any() for v in bounds):
        raise ParamError('lower bounds must be strictly below upper bounds')
    for channel in range(a.shape[1]):
        unknown = np.flatnonzero(mask[:, channel])
        if not len(unknown):
            continue
        # Solve each connected gap with local, uncontaminated model contexts.
        cuts = np.r_[0, np.flatnonzero(np.diff(unknown)>1)+1, len(unknown)]
        for start, stop in zip(cuts[:-1], cuts[1:]):
            idx = unknown[start:stop]
            lo, hi = int(idx[0]), int(idx[-1]+1)
            lc = lo
            while lc > max(0, lo-context) and not mask[lc-1, channel]:
                lc -= 1
            rc = hi
            while rc < min(len(a), hi+context) and not mask[rc, channel]:
                rc += 1
            left, right = a[lc:lo, channel], a[hi:rc, channel]
            rows, cols, vals, targets = [], [], [], []
            for reverse, training in ((False, left), (True, right[::-1])):
                if len(training) < 3:
                    continue
                model = burg(training, order)
                p = len(model)-1
                times = range(lo, min(rc, hi+p)) if not reverse else range(max(lc, lo-p), hi)
                for t in times:
                    positions = t+np.arange(p+1) if reverse else t-np.arange(p+1)
                    if positions.min() < lc or positions.max() >= rc:
                        continue
                    u = (positions >= lo) & (positions < hi)
                    if not u.any():
                        continue
                    row = len(targets)
                    rows.extend([row]*int(u.sum()))
                    cols.extend((positions[u]-lo).tolist())
                    vals.extend(model[u].tolist())
                    targets.append(-float(model[~u] @ a[positions[~u], channel]))
            if not targets:
                estimate = np.interp(idx, np.r_[lo-1, hi], [left[-1] if len(left) else 0., right[0] if len(right) else 0.])
                estimate = np.clip(estimate, bounds[0][idx, channel], bounds[1][idx, channel])
            else:
                mat = sparse.csr_matrix((vals, (rows, cols)), shape=(len(targets), len(idx)))
                low, high = bounds[0][idx, channel], bounds[1][idx, channel]
                if np.isfinite(low).any() or np.isfinite(high).any():
                    fit = optimize.lsq_linear(mat.toarray() if len(idx) <= 512 else mat, targets,
                                              bounds=(low, high), tol=1e-10, lsmr_tol=1e-12, max_iter=500)
                    if not fit.success:
                        raise ParamError('constrained AR interpolation did not converge')
                    estimate = fit.x
                elif len(idx) <= 512:
                    estimate = linalg.lstsq(mat.toarray(), targets, cond=1e-10, lapack_driver='gelsy')[0]
                else:
                    # High-order tonal models make long-gap normal equations
                    # nearly singular. A tiny prediction-centered ridge keeps
                    # the sparse solve well posed without a zero-signal prior.
                    prior = bidirectional(left, right, len(idx), order=order)
                    normal = mat.T @ mat
                    ridge = max(1., float(np.mean(normal.diagonal())))*1e-10
                    estimate = spsolve(normal+sparse.eye(len(idx), format='csc')*ridge,
                                      mat.T @ np.asarray(targets)+ridge*prior)
                    if not np.isfinite(estimate).all():
                        raise ParamError('AR interpolation did not converge')
            result[idx, channel] = estimate
    return result[:, 0] if mono else result


def local_model(x, order=32, *, error_floor=1e-10):
    """Burg model with a prediction-error floor to avoid tonal overfitting.

    order is an upper bound. Stop when innovation energy is below error_floor
    (default 1e-10) of input power, or coefficients exceed 1e4.
    Existing burg/interpolate behavior is unchanged.
    """
    v = np.asarray(x, dtype=np.float64)
    a = np.array([1.])
    f, b = v[1:].copy(), v[:-1].copy()
    power = float(np.mean(v*v)) if len(v) else 0
    for _ in range(min(order, max(0, len(v)//4))):
        den = float(f @ f+b @ b)
        if not len(f) or den <= max(np.finfo(float).tiny, 2*len(f)*power*error_floor):
            break
        k = np.clip(-2*float(b @ f)/den, -.999999, .999999)
        new = np.r_[a, 0.]+k*np.r_[0., a[::-1]]
        if np.max(abs(new)) > 1e4:
            break
        a = new
        nf, nb = f+k*b, b+k*f
        f, b = nf[1:], nb[:-1]
    return a


def masked_burg(x, missing, order=32):
    """Burg estimation pooling only contiguous observed windows of a vector.

    Invalid windows are excluded at every recursion, never concatenated across
    missing samples. Returns a bounded-order model; no input is modified.
    """
    v = np.asarray(x, dtype=np.float64)
    good = ~np.asarray(missing, dtype=bool)
    a = np.array([1.])
    f, b = v[1:].copy(), v[:-1].copy()
    valid = good[1:] & good[:-1]
    power = float(np.mean(v[good]**2)) if good.any() else 0
    for _ in range(min(order, max(0, len(v)-2))):
        if np.count_nonzero(valid) < max(8, 2*len(a)):
            break
        den = float(f[valid] @ f[valid]+b[valid] @ b[valid])
        if den <= max(np.finfo(float).tiny, 2*np.count_nonzero(valid)*power*1e-10):
            break
        k = np.clip(-2*float(b[valid] @ f[valid])/den, -.999999, .999999)
        new = np.r_[a, 0.]+k*np.r_[0., a[::-1]]
        if np.max(abs(new)) > 1e4:
            break
        a = new
        nf, nb = f+k*b, b+k*f
        f, b = nf[1:], nb[:-1]
        valid = valid[1:] & valid[:-1]
    return a


def observed_model(x, missing, order=32):
    """Refine an observed-only Burg model by reliable-window covariance LS.

    Try orders up to the Burg order, selecting the smallest with relative
    innovation below 1e-16; otherwise use the minimum BIC. Clipped windows are
    omitted. This avoids Burg boundary bias on many short clean fragments.
    """
    v = np.asarray(x, dtype=np.float64)
    missing = np.asarray(missing, dtype=bool)
    initial = masked_burg(v, missing, order)
    best, criterion = initial, np.inf
    for p in range(1, min(order, max(4, len(initial)-1))+1):
        if len(v) <= p:
            break
        frames = np.lib.stride_tricks.sliding_window_view(v, p+1)
        valid = ~np.lib.stride_tricks.sliding_window_view(missing, p+1).any(axis=1)
        if np.count_nonzero(valid) < max(16, 3*p):
            break
        data = frames[valid]
        coeff = linalg.lstsq(data[:, :-1][:, ::-1], -data[:, -1], cond=1e-9, lapack_driver='gelsy')[0]
        model = np.r_[1., coeff]
        if np.max(abs(model)) > 1e4 or np.max(abs(np.roots(model))) > 1.00001:
            continue
        error = data[:, -1]+data[:, :-1][:, ::-1] @ coeff
        ratio = float(np.sum(error**2))/max(float(np.sum(data[:, -1]**2)), 1e-30)
        bic = len(data)*np.log(max(ratio, 1e-30))+p*np.log(len(data))
        if bic < criterion:
            best, criterion = model, bic
        if ratio < 1e-16:
            return model
    return best


def innovation_gap(left, right, length, *, order=32):
    """AR continuation driven by deterministically replayed context residuals.

    Returns (continuation, residual/input power ratio). It supplies variance
    missing from the conditional-mean LSAR solution on noise-like contexts.
    No random generator or external state is used. Directional continuations
    use equal-power mixing, then match the clean-context RMS.
    """
    values, ratios = [], []
    for context in (np.asarray(left), np.asarray(right)[::-1]):
        model = local_model(context, order)
        p = len(model)-1
        errors = residual(context, model)[p:]
        power = float(np.mean(context**2)) if len(context) else 0
        ratios.append(float(np.mean(errors**2))/power if power and len(errors) else 0)
        drive = np.resize(errors, length) if len(errors) else np.zeros(length)
        zi = signal.lfiltic([1.], model, context[-p:][::-1]) if p else np.empty(0)
        values.append(signal.lfilter([1.], model, drive, zi=zi)[0])
    w = (np.arange(length)+1)/(length+1)
    y = np.cos(w*np.pi/2)*values[0]+np.sin(w*np.pi/2)*values[1][::-1]
    target = np.r_[left, right]
    power = float(np.mean(target**2)) if len(target) else 0
    actual = float(np.mean(y*y)) if len(y) else 0
    if actual:
        y *= np.sqrt(power/actual)
    return y, min(ratios)


def lsar_gap(left, right, length, *, order=32, lower=None, upper=None, iterations=8, models=None):
    """Joint bidirectional LSAR for a mono gap, optional active-set bounds.

    Clean left/right contexts exclude all other gaps. Constraints apply to
    the unknowns only. At each of at most eight solves, newly violated bounds
    are fixed, then free variables are solved again. Returns (estimate, info).
    The unconstrained sparse normal solve uses a 1e-12 diagonal ridge centered
    on the forward/backward prediction blend. No randomness is introduced.
    models=[forward,backward] optionally supplies observed-only coefficients.
    Unbounded gaps above 4096 samples use an implicit FFT normal operator
    (CG, at most 512 steps); info includes convergence. Local fits here use
    local_model(error_floor=1e-20).
    """
    left, right = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if length < 0 or order < 1 or not 1 <= iterations <= 8:
        raise ParamError('invalid gap length, order or iteration count')
    low = np.broadcast_to(-np.inf if lower is None else lower, (length,)).copy()
    high = np.broadcast_to(np.inf if upper is None else upper, (length,)).copy()
    if np.any(low > high) or np.isnan(low).any() or np.isnan(high).any():
        raise ParamError('invalid gap bounds')
    if not length:
        return np.empty(0), {'iterations': 0, 'orders': [0, 0]}
    models = [local_model(left, order, error_floor=1e-20), local_model(right[::-1], order, error_floor=1e-20)] if models is None else models
    f = predict(left, models[0], length)
    b = predict(right[::-1], models[1], length)[::-1]
    w = (np.arange(length)+1)/(length+1)
    prior = (1-w)*f+w*b
    source = np.r_[left, np.zeros(length), right]
    lo, hi = len(left), len(left)+length
    if (length > 4096 and len(left) >= max(map(len, models))-1 and
            len(right) >= max(map(len, models))-1 and
            not np.isfinite(low).any() and not np.isfinite(high).any()):
        # Full convolution support permits an implicit normal operator. This
        # avoids materializing O(length*order) Python entries on 500 ms gaps.
        from scipy.sparse.linalg import LinearOperator, cg
        ridge = max(1., sum(float(a @ a) for a in models))*1e-12
        rhs = np.zeros(length)
        for reverse, model in zip((False, True), models):
            known = source[::-1] if reverse else source
            start = len(right) if reverse else lo
            error = residual(known, model)[start:start+length+len(model)-1]
            contribution = -signal.correlate(error, model, mode='valid', method='fft')
            rhs += contribution[::-1] if reverse else contribution
        def multiply(v):
            result = ridge*v
            for reverse, model in zip((False, True), models):
                u = v[::-1] if reverse else v
                error = signal.fftconvolve(u, model)
                value = signal.correlate(error, model, mode='valid', method='fft')
                result = result+(value[::-1] if reverse else value)
            return result
        operator = LinearOperator((length, length), matvec=multiply, dtype=np.float64)
        estimate, status = cg(operator, rhs+ridge*prior, x0=prior, rtol=1e-9, atol=1e-12, maxiter=512)
        if status < 0 or not np.isfinite(estimate).all():
            raise ParamError('implicit LSAR solve failed')
        return estimate, {'iterations': 1, 'orders': [len(a)-1 for a in models],
                          'solver': 'implicit_cg', 'converged': status == 0}
    rows, cols, vals, targets = [], [], [], []
    for reverse, model in zip((False, True), models):
        p = len(model)-1
        times = range(max(0, lo-p), hi) if reverse else range(lo, min(len(source), hi+p))
        for t in times:
            pos = t+np.arange(p+1) if reverse else t-np.arange(p+1)
            if pos.min() < 0 or pos.max() >= len(source):
                continue
            unknown = (pos >= lo) & (pos < hi)
            row = len(targets)
            rows.extend([row]*int(unknown.sum()))
            cols.extend((pos[unknown]-lo).tolist())
            vals.extend(model[unknown].tolist())
            targets.append(-float(model[~unknown] @ source[pos[~unknown]]))
    if not targets:
        estimate = np.linspace(left[-1] if len(left) else 0, right[0] if len(right) else 0, length+2)[1:-1]
        return np.clip(estimate, low, high), {'iterations': 0, 'orders': [0, 0]}
    mat = sparse.csr_matrix((vals, (rows, cols)), shape=(len(targets), length))
    normal = (mat.T @ mat).tocsc()
    ridge = max(1., float(np.mean(normal.diagonal())))*1e-12
    normal = normal+sparse.eye(length, format='csc')*ridge
    rhs = np.asarray(mat.T @ np.asarray(targets))+ridge*prior
    fixed = np.zeros(length, bool)
    estimate = prior.copy()
    count = 0
    for count in range(1, iterations+1):
        free = ~fixed
        if free.any():
            estimate[free] = spsolve(normal[free][:, free], rhs[free]-normal[free][:, fixed] @ estimate[fixed])
        if not np.isfinite(estimate).all():
            raise ParamError('LSAR gap solve produced nonfinite samples')
        violated = (estimate < low) | (estimate > high)
        if not violated.any():
            break
        estimate = np.clip(estimate, low, high)
        fixed |= violated
    return np.clip(estimate, low, high), {'iterations': count, 'orders': [len(a)-1 for a in models]}


def robust_observed_model(x, missing, order=32, *, trim=.9, score_fraction=.98):
    """Trimmed covariance refinement of an observed-only Burg model.

    Fit contiguous observed regression rows, by default trimming 10 percent
    of innovations for at most eight deterministic refinements. Score the best 98
    percent with BIC; this retains excitation decay without fitting isolated
    excitation impulses. Local reverse-time models may have growing poles.
    Existing model estimators are deliberately unchanged.
    """
    v = np.asarray(x, dtype=np.float64)
    missing = np.asarray(missing)
    if (v.ndim != 1 or missing.shape != v.shape or missing.dtype != bool or
            not np.isfinite(v).all() or not isinstance(order, (int, np.integer)) or order < 1 or
            not .5 <= trim <= 1 or not .5 <= score_fraction <= 1):
        raise ParamError('invalid robust observed AR input or fitting fractions')
    best = masked_burg(v, missing, order)
    # Unmasked noise-like blocks have no accurate low-order continuation to
    # refine. Keep Burg there; exhaustive trimmed fits only add variance.
    if not missing.any() and len(v) > len(best):
        innovation = residual(v, best)[len(best)-1:]
        if float(np.mean(innovation**2)) >= .3*max(float(np.mean(v*v)), 1e-30):
            return best
    criterion = np.inf
    for p in range(1, min(order, len(v)-2)+1):
        frames = np.lib.stride_tricks.sliding_window_view(v, p+1)
        good = ~np.lib.stride_tricks.sliding_window_view(missing, p+1).any(axis=1)
        data = frames[good]
        if len(data) < max(16, 2*p):
            break
        keep = np.ones(len(data), bool)
        floor = max(float(np.sqrt(np.mean(data[:, -1]**2)))*1e-12, 1e-15)
        for _ in range(8):
            coeff = linalg.lstsq(data[keep, :-1][:, ::-1], -data[keep, -1],
                                 cond=1e-12, lapack_driver='gelsy')[0]
            model = np.r_[1., coeff]
            error = abs(data @ model[::-1])
            selected = error <= max(float(np.quantile(error, trim)), floor)
            if np.array_equal(keep, selected):
                break
            keep = selected
            if np.count_nonzero(keep) < p+2:
                break
        if np.max(abs(model)) > 1e4:
            continue
        trimmed = np.sort(error**2)[:max(1, int(score_fraction*len(error)))]
        ratio = float(np.mean(trimmed))/max(float(np.mean(data[:, -1]**2)), 1e-30)
        bic = len(data)*np.log(max(ratio, 1e-30))+p*np.log(len(data))
        if bic < criterion:
            best, criterion = model, bic
        if ratio < 1e-20:
            return model
    return best


def joint_lsar(x, missing, *, models, lower=None, upper=None, iterations=8):
    """Solve all mono missing samples together with fixed AR models.

    Regression rows can cross several neighboring holes. All observed samples
    are exact constants. Bounds use at most eight active-set solves, as in
    lsar_gap; this additive API does not change that function's behavior.
    """
    v = np.asarray(x, dtype=np.float64)
    missing = np.asarray(missing)
    if (v.ndim != 1 or missing.shape != v.shape or missing.dtype != bool or
            not np.isfinite(v).all() or not 1 <= iterations <= 8 or len(models) != 2 or
            any(not len(a) or a[0] != 1 or not np.isfinite(a).all() for a in models)):
        raise ParamError('invalid joint LSAR input, models or iteration count')
    idx = np.flatnonzero(missing)
    if not len(idx):
        return v.copy(), {'iterations': 0, 'orders': [len(a)-1 for a in models]}
    low = np.broadcast_to(-np.inf if lower is None else lower, v.shape)[idx]
    high = np.broadcast_to(np.inf if upper is None else upper, v.shape)[idx]
    if np.any(low > high) or np.isnan(low).any() or np.isnan(high).any():
        raise ParamError('invalid joint LSAR bounds')
    known = v.copy()
    known[idx] = 0
    operators, targets = [], []
    for reverse, model in zip((False, True), models):
        p = len(model)-1
        times = np.arange(0, len(v)-p) if reverse else np.arange(p, len(v))
        taps = np.flatnonzero(model)
        offsets = taps if reverse else -taps
        positions = times[:, None]+offsets
        active = missing[positions].any(axis=1)
        positions = positions[active]
        rows = np.repeat(np.arange(len(positions)), len(taps))
        op = sparse.csr_matrix((np.tile(model[taps], len(positions)),
                                (rows, positions.ravel())), shape=(len(positions), len(v)))
        operators.append(op[:, idx])
        targets.append(-op @ known)
    mat = sparse.vstack(operators, format='csr')
    normal = (mat.T @ mat).tocsc()
    ridge = max(1., float(np.mean(normal.diagonal())))*1e-12
    normal += sparse.eye(len(idx), format='csc')*ridge
    rhs = mat.T @ np.concatenate(targets)+ridge*v[idx]
    estimate = v[idx].copy()
    fixed = np.zeros(len(idx), bool)
    for count in range(1, iterations+1):
        free = ~fixed
        if free.any():
            estimate[free] = spsolve(normal[free][:, free], rhs[free]-normal[free][:, fixed] @ estimate[fixed])
        violated = (estimate < low) | (estimate > high)
        if not violated.any():
            break
        estimate = np.clip(estimate, low, high)
        fixed |= violated
    if not np.isfinite(estimate).all():
        raise ParamError('joint LSAR produced nonfinite samples')
    result = v.copy()
    result[idx] = np.clip(estimate, low, high)
    return result, {'iterations': count, 'orders': [len(a)-1 for a in models]}
