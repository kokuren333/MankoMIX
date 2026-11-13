"""Stem separation (SPEC 6.2). See pipeline.py; the model code runs in worker.py (a subprocess).

Exports are resolved lazily so that the worker process does not import the
core pipeline (and the core process never imports torch or model code).
"""

from __future__ import annotations

__all__ = ["separate", "separation_records", "run_worker", "RESTRICTION"]


def __getattr__(name: str):
    if name in __all__:
        from . import pipeline

        return getattr(pipeline, name)
    raise AttributeError(name)
