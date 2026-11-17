"""BB-23: deterministic banded cosine DTW and constrained source->destination maps.

Independent implementation of the recurrences described by Sakoe & Chiba
(1978) and Mueller, Fundamentals of Music Processing (2015). No code copied.
Features use repository BB-06/22, 24 triangular mel bands and a 5 ms clock.
All positions returned by alignment() are section-local samples.
"""
import numpy as np
from scipy import ndimage
from .stft import analyze
from .onsets import onset_features, detect_onsets


def features(x, sr, feature='both'):
    hop = max(1, round(.005*sr))
    st = analyze(x, sr, window=max(32, round(1024*sr/48000)), hop=hop)
    power = np.mean(abs(st.spectra)**2, axis=2)
    mel = lambda f: 2595*np.log10(1+f/700)
    edges = 700*(10**(np.linspace(mel(20), mel(min(20000, sr/2)), 26)/2595)-1)
    f = st.frequencies_hz
    bank = np.array([np.maximum(0, np.minimum((f-a)/(b-a), (c-f)/(c-b)))
                     for a, b, c in zip(edges[:-2], edges[1:-1], edges[2:])])
    energy = np.einsum('tf,bf->tb', power, bank, optimize=False)
    # Per-band reference normalization removes overall and spectral level bias.
    log = np.log1p(energy/np.maximum(np.max(energy, axis=0, initial=0), 1e-24)*100)
    delta = np.diff(log, axis=0, prepend=log[:1])
    of = onset_features(x, sr)
    flux = np.interp(st.samples, of.samples, of.flux['full']) if len(of.samples) else np.zeros(len(log))
    flux /= max(float(np.max(flux, initial=0)), 1e-24)
    # Envelope context disambiguates the many zero-flux frames between attacks.
    env = np.sqrt(np.maximum(0, power.sum(axis=1)))
    env /= max(float(env.max(initial=0)), 1e-24)
    onset = np.column_stack([flux, env, np.maximum(0, np.diff(env, prepend=env[:1]))*5])
    spectral = np.column_stack([log/np.sqrt(24), delta/np.sqrt(24)])
    values = onset if feature == 'onset_env' else spectral if feature == 'spectral' else np.column_stack([onset, spectral])
    norms = np.linalg.norm(values, axis=1)
    values = values/np.maximum(norms[:, None], 1e-24)
    silent = power.sum(axis=1) < max(float(power.sum(axis=1).max(initial=0))*1e-10, 1e-24)
    return st.samples, values, silent


def path(a, b, band, stretch_min=.5, stretch_max=2):
    """Banded DP; equal costs prefer diagonal, horizontal, then vertical.

    Compound steps limit local destination/source slope to the stated bounds.
    Each traversed frame contributes cosine cost; storage is O(frames*band).
    """
    n, m = len(a), len(b)
    if not n or not m:
        return np.empty((0, 2), int), np.empty(0)
    width = 2*band+1
    costs = np.full((n, width), np.inf)
    back = np.full((n, width), -1, np.int8)
    steps = [(1, 1)]+[(1, k) for k in range(2, 5) if k <= stretch_max]+[(k, 1) for k in range(2, 5) if 1/k >= stretch_min]
    if 1 < stretch_max < 2:
        k = int(np.ceil(1/(stretch_max-1)-1e-10))
        if k < n and k+1 < m:
            steps.insert(1, (k, k+1))
    if .5 < stretch_min < 1:
        k = int(np.ceil(stretch_min/(1-stretch_min)-1e-10))
        if k+1 < n and k < m:
            steps.append((k+1, k))
    # Vectorized costs within each band, scalar deterministic DP traceback.
    local_rows = []
    for i in range(n):
        lo, hi = max(0, i-band), min(m, i+band+1)
        js = np.arange(lo, hi)
        row = np.clip(1-np.sum(b[js]*a[i], axis=1), 0, 2)
        row[(np.linalg.norm(b[js], axis=1) == 0) & (np.linalg.norm(a[i]) == 0)] = 0
        local_rows.append((lo, row))
        for j, value in zip(js, row):
            col = j-i+band
            if i == j == 0:
                costs[i, col] = value
                continue
            best, chosen = np.inf, -1
            for k, (di, dj) in enumerate(steps):
                pi, pj = i-di, j-dj
                pc = pj-pi+band
                if pi < 0 or pj < 0 or not 0 <= pc < width:
                    continue
                trial = costs[pi, pc]+value*(di+dj)/2
                if trial < best:
                    best, chosen = trial, k
            costs[i, col], back[i, col] = best, chosen
    i, j = n-1, m-1
    if not 0 <= j-i+band < width or not np.isfinite(costs[i, j-i+band]):
        raise ValueError('anchors, band and stretch limits admit no DTW path')
    pairs, values = [], []
    while True:
        pairs.append((i, j))
        lo, row = local_rows[i]
        values.append(float(row[j-lo]))
        if i == j == 0:
            break
        k = back[i, j-i+band]
        di, dj = steps[k]
        i, j = i-di, j-dj
    return np.array(pairs[::-1]), np.array(values[::-1])


def constrain(x, y, fixed, lo, hi, max_shift):
    """Feasible forward projection between exact fixed points, bounded slopes."""
    y = np.asarray(y, float).copy()
    knots = sorted(fixed)
    for left, right in zip(knots[:-1], knots[1:]):
        a, b = fixed[left], fixed[right]
        if not lo-1e-10 <= (b-a)/(x[right]-x[left]) <= hi+1e-10:
            raise ValueError('fixed points violate stretch limits')
        y[left], y[right] = a, b
        for k in range(left+1, right):
            dx, remain = x[k]-x[k-1], x[right]-x[k]
            low = max(y[k-1]+lo*dx, b-hi*remain, x[k]-max_shift)
            high = min(y[k-1]+hi*dx, b-lo*remain, x[k]+max_shift)
            if low > high+1e-7:
                raise ValueError('fixed points violate max_shift_ms')
            y[k] = np.clip(y[k], low, high)
    if np.any(abs(y-x) > max_shift+1e-6):
        raise ValueError('anchors exceed max_shift_ms')
    return y


def alignment(target, guide, sr, p):
    frames = len(target)
    if len(guide) != frames or frames < 2:
        raise ValueError('alignment needs equal nonempty timeline intervals')
    t, a, sa = features(target, sr, p['feature'])
    _, b, sb = features(guide, sr, p['feature'])
    hop = max(1, round(.005*sr))
    anchors = np.array(p.get('anchors') or [], float).reshape(-1, 2)*sr
    if len(anchors) and (np.any(anchors < 0) or np.any(anchors > frames)):
        raise ValueError('anchor outside the selected interval')
    boundaries = [[0., 0.]]+[list(v) for v in anchors if 0 < v[0] < frames]+[[float(frames), float(frames)]]
    if len(anchors) and any((v[0] == 0 and v[1] != 0) or (v[0] == frames and v[1] != frames) for v in anchors):
        raise ValueError('map endpoints must retain the selected interval')
    source, dest, local_cost, cost_times = [], [], [], []
    for (u, v), (w, z) in zip(boundaries[:-1], boundaries[1:]):
        ia, ib = round(u/hop), min(len(t)-1, round(w/hop))
        ja, jb = round(v/hop), min(len(t)-1, round(z/hop))
        if ib <= ia or jb <= ja:
            # Sub-hop manual corrections retain their exact clocks; there is
            # no extra minimum spacing requirement on the public anchor array.
            source.extend([u, w]); dest.extend([v, z])
            local_cost.append(float(np.clip(1-np.dot(a[min(ia, len(a)-1)], b[min(ja, len(b)-1)]), 0, 2)))
            cost_times.append(u/sr)
            continue
        band = int(np.ceil(p['max_shift_ms']*.001*sr/hop))+abs(ja-ia)+2
        route, costs = path(a[ia:ib+1], b[ja:jb+1], band, p['stretch_min'], p['stretch_max'])
        source.extend(t[route[:, 0]+ia]); dest.extend(t[route[:, 1]+ja])
        local_cost.extend(costs); cost_times.extend(t[route[:, 0]+ia]/sr)
    grid = np.unique(np.r_[t, frames, anchors[:, 0] if len(anchors) else []]).astype(float)
    y = np.interp(grid, source, dest)
    y[-1] = frames
    if p['smooth_ms']:
        y = grid+ndimage.gaussian_filter1d(y-grid, max(.01, p['smooth_ms']/5/2), mode='nearest')
    y = grid+p['tightness']*(y-grid)
    fixed = {0: 0., len(grid)-1: float(frames)}
    for u, v in anchors:
        fixed[int(np.searchsorted(grid, u))] = float(v)
    # Both silent means identity. Retain every silent sample support boundary.
    for k, u in enumerate(grid[:-1]):
        i = min(len(sa)-1, round(u/hop))
        if sa[i] and sb[i] and k not in fixed:
            fixed[k] = u
    y = constrain(grid, y, fixed, p['stretch_min'], p['stretch_max'], p['max_shift_ms']*.001*sr)
    if p['protect_sustain']:
        # Hold attack correspondences; put displacement changes in stable frames.
        events = detect_onsets(target, sr, kind='soft')
        attack = np.array([e['sample'] for e in events])
        for s in attack:
            k = int(np.argmin(abs(grid-s)))
            fixed[k] = y[k]
        for left, right in zip(sorted(fixed)[:-1], sorted(fixed)[1:]):
            if right-left < 2:
                continue
            mid = (grid[left:right]+grid[left+1:right+1])/2
            stability = np.ones(len(mid))
            if len(attack):
                stability = np.minimum(1, np.min(abs(mid[:, None]-attack), axis=1)/(.030*sr))
            ix = np.minimum(len(a)-1, np.rint(mid/hop).astype(int))
            change = np.linalg.norm(a[ix]-a[np.maximum(0, ix-1)], axis=1)
            stability /= 1+5*change
            weight = np.diff(grid[left:right+1])*((1-p['protect_sustain'])+p['protect_sustain']*(.05+stability))
            displacement = (y[right]-grid[right])-(y[left]-grid[left])
            y[left+1:right] = grid[left+1:right]+y[left]-grid[left]+displacement*np.cumsum(weight)[:-1]/weight.sum()
        y = constrain(grid, y, fixed, p['stretch_min'], p['stretch_max'], p['max_shift_ms']*.001*sr)
    if p['tightness'] == 0:
        y = grid.copy()
    shift = (y-grid)/sr*1000
    slopes = np.diff(y)/np.diff(grid)
    cost = float(np.mean(local_cost)) if local_cost else 0.
    uncertain = [{'t0_s': float(t), 't1_s': float(min(frames/sr, t+hop/sr)), 'cost': float(c), 'confidence': 'low'}
                 for t, c in zip(cost_times, local_cost) if c > .35]
    return {'map': np.column_stack([grid, y]).tolist(), 'mean_cost': cost,
            'confidence': 'low' if cost > .2 else 'high', 'uncertain_intervals': uncertain,
            'shift_ms': {'median': float(np.median(abs(shift))), 'max': float(np.max(abs(shift)))},
            'stretch_range': [float(slopes.min()), float(slopes.max())],
            'feature_hop_samples': hop, 'identity': bool(np.max(abs(shift)) <= (1e-9 if len(anchors) and p['tightness'] else 3))}
