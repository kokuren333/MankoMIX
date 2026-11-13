"""Gain-computer ballistics shared by the dynamics processors (reference backend).

The decoupled attack/release one-pole smoother is a data-dependent recursion
(the branch depends on the previous output), so it cannot be written as a
plain ``lfilter``. It runs in the native core when the library exports the
kernel (``mmx_smooth_attack_release``, library >= 0.2.0) and otherwise in a
Python loop with the same operation order; both give bit-identical results
(the native core is built without FMA contraction or fast-math).

``impl``:

- ``"auto"``   native kernel when available, else the Python loop;
- ``"native"`` native kernel required (raises ``DSPError`` rule ``backend``);
- ``"python"`` always the Python loop.
"""

from __future__ import annotations

import math

import numpy as np

from ..errors import DSPError


def coef(ms: float, sr: int) -> float:
    """One-pole coefficient for a time constant in milliseconds (63 % step response)."""
    return math.exp(-1.0 / (ms * 1e-3 * sr))


def native_kernel_available() -> bool:
    try:
        from .. import native_backend
        return native_backend.has_smoother()
    except Exception:  # pragma: no cover - probing must never break rendering
        return False


def smooth_python(gr: np.ndarray, a_att: float, a_rel: float, state: float = 0.0) -> np.ndarray:
    """Reference loop: y = a*y + (1-a)*g with a = a_att while g > y, else a_rel."""
    prev = float(state)
    ia, ir = 1.0 - a_att, 1.0 - a_rel
    vals = np.asarray(gr, dtype=np.float64).reshape(-1).tolist()
    res = [0.0] * len(vals)
    for i, g in enumerate(vals):
        if g > prev:
            prev = a_att * prev + ia * g
        else:
            prev = a_rel * prev + ir * g
        res[i] = prev
    return np.asarray(res, dtype=np.float64)


def smooth(gr: np.ndarray, a_att: float, a_rel: float, *, impl: str = "auto",
           state: float = 0.0) -> tuple[np.ndarray, str]:
    """Smooth a 1-D trace; returns (smoothed, implementation used: "native" | "python")."""
    if impl not in ("auto", "native", "python"):
        raise ValueError(f"unknown ballistics implementation {impl!r}")
    use_native = impl == "native" or (impl == "auto" and native_kernel_available())
    if use_native:
        from .. import native_backend
        if not native_backend.has_smoother():
            raise DSPError("native ballistics kernel unavailable: "
                           f"{native_backend.load_error() or 'library lacks mmx_smooth_attack_release'}",
                           rule="backend")
        return native_backend.smooth_attack_release(gr, a_att, 1.0 - a_att, a_rel, 1.0 - a_rel,
                                                    state), "native"
    return smooth_python(gr, a_att, a_rel, state), "python"


def smooth_columns(gr: np.ndarray, a_att: float, a_rel: float, *, impl: str = "auto"
                   ) -> tuple[np.ndarray, str]:
    """Smooth each column of a (frames, k) trace independently."""
    gr = np.asarray(gr, dtype=np.float64)
    if gr.ndim == 1:
        return smooth(gr, a_att, a_rel, impl=impl)
    cols, used = [], "python"
    for c in range(gr.shape[1]):
        y, used = smooth(gr[:, c], a_att, a_rel, impl=impl)
        cols.append(y)
    return np.stack(cols, axis=1), used
