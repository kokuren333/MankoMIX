"""Piecewise-linear dB curves for the optional gain_curve move."""

from __future__ import annotations

import numpy as np


def points(rate: int, segments: list[dict], ramp_ms: float = 20.0,
           duration_s: float | None = None) -> list[list]:
    """Generate sample/dB points, omitting held segments and clipping to the song.

    Overlapping ramps become one straight bridge centered on the gap midpoint.
    Its endpoints cannot pass either segment's midpoint, so even short adjacent
    segments retain their requested value. Separate moves are summed by the caller.
    """
    active = sorted((float(s["t0_s"]), float(s["t1_s"]), float(s["delta_db"]))
                    for s in segments if not s.get("hold", False))
    if not active:
        return []
    ramp = float(ramp_ms) / 1000.0
    starts = [s[0] for s in active]
    ends = [s[1] for s in active]
    bridges = set()
    for i, (left, right) in enumerate(zip(active, active[1:])):
        if right[0] - left[1] < 2 * ramp:
            middle = (left[1] + right[0]) / 2
            ends[i] = max((left[0] + left[1]) / 2, min(left[1], middle - ramp))
            starts[i + 1] = min((right[0] + right[1]) / 2, max(right[0], middle + ramp))
            bridges.add(i)
    raw = [(active[0][0] - ramp, 0.0)]
    for i, (_, end, value) in enumerate(active):
        raw.extend([(starts[i], value), (ends[i], value)])
        if i not in bridges:
            raw.append((end + ramp, 0.0))
            if i + 1 < len(active):
                raw.append((active[i + 1][0] - ramp, 0.0))
    # Round to the renderer's sample grid; coincident anchors use the later value.
    grid = {int(round(t * rate)): value for t, value in raw}
    xs = sorted(grid)
    ys = [grid[x] for x in xs]
    last = int(round(duration_s * rate)) if duration_s is not None else max(0, xs[-1])
    inside = sorted({0, last} | {x for x in xs if 0 <= x <= last})
    vals = np.interp(inside, xs, ys)
    return [[x, round(float(v), 9) + 0.0] for x, v in zip(inside, vals)]
