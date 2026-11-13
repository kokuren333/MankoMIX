"""Error types raised by the DSP engine.

They derive from ValueError so callers that only know the standard library can
catch them. ``rule`` names the SPEC invariant that was violated (``S-05``,
``S-06``, ``S-09``, ``stage``, ``params``, ...).
"""

from __future__ import annotations


class DSPError(ValueError):
    rule = "dsp"

    def __init__(self, message: str, *, rule: str | None = None, step: str | None = None):
        super().__init__(message)
        if rule is not None:
            self.rule = rule
        self.step = step


class ParamError(DSPError):
    rule = "params"


class ChainError(DSPError):
    rule = "chain"


class NumericError(DSPError):
    rule = "S-09"
