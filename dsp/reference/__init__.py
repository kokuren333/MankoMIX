"""Reference backend: numpy/scipy implementations, float64 internally, deterministic.

Every implementation has the signature ``fn(x, sr, params, *, seed=0) -> (y, sr_out, stats)``
with ``x`` shaped (frames, channels) float64 and ``params`` already validated
by ``mankomix.dsp.processors.validate_params``.
"""

from __future__ import annotations

from . import basic, dynamics, dyneq, export, filters, nonlinear, space, stereo
from .truepeak import peak_per_sample, sample_peak_dbfs, true_peak_dbtp, true_peak_linear

BACKEND = "reference"

IMPLEMENTATIONS = {
    "gain": basic.gain,
    "pan": basic.pan,
    "loudness_gain": basic.loudness_gain,
    "filter": filters.filt,
    "eq": filters.eq,
    "dynamic_eq": dyneq.dynamic_eq,
    "compressor": dynamics.compressor,
    "deesser": dyneq.deesser,
    "limiter": dynamics.limiter,
    "saturator": nonlinear.saturator,
    "clipper": nonlinear.clipper,
    "stereo": stereo.stereo,
    "reverb": space.reverb,
    "delay": space.delay,
    "resample": export.resample,
    "dither": export.dither,
}


def version() -> dict:
    import numpy
    import scipy

    return {"backend": BACKEND, "numpy": numpy.__version__, "scipy": scipy.__version__}


__all__ = ["IMPLEMENTATIONS", "BACKEND", "version", "peak_per_sample", "true_peak_dbtp",
           "true_peak_linear", "sample_peak_dbfs"]

from mankomix.dspx.registry import implementations as _extension_implementations

for _type, _fn in _extension_implementations().items():
    if _type in IMPLEMENTATIONS:
        raise ImportError(f"duplicate reference implementation: {_type}")
    IMPLEMENTATIONS[_type] = _fn
