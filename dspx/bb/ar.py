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
