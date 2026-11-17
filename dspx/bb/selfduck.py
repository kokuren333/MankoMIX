"""BB-14 SD: dry-key RMS ducking of a wet signal, also usable by delays.

sd_params() returns fresh SD declarations. SelfDuck(sr, params).process(dry,
wet) retains its 10 ms RMS history and dB ballistics across arbitrary chunks.
duck_wet(dry, wet, sr, params) starts from zero. Disabled ducking returns the
original wet object without arithmetic. The linked key is the maximum RMS
across dry channels; the wet channel count may differ from the dry count.
"""
import numpy as np
from scipy import signal

from mankomix.dspx.params import _f
from mankomix.dspx.bb.dynamics import GainSmoother


def sd_params():
    return [_f("duck_db", "dB", 0, 24, 0, "Maximum wet attenuation."),
            _f("duck_threshold_db", "dBFS", -80, 0, -40, "Dry RMS threshold."),
            _f("duck_attack_ms", "ms", .1, 200, 10, "Ducking attack time constant."),
            _f("duck_release_ms", "ms", 5, 3000, 250, "Ducking release time constant.")]


class SelfDuck:
    """Zero-state causal rectangular RMS detector and signed-dB smoother."""
    def __init__(self, sr, params):
        self.p = {s["id"]: params.get(s["id"], s["default"]) for s in sd_params()}
        self.window = max(1, round(.01 * sr))
        self.state = None
        self.smoother = GainSmoother(sr, self.p["duck_attack_ms"], self.p["duck_release_ms"])
        self.last_gain_db = np.zeros((0, 1))

    def process(self, dry, wet):
        if not self.p["duck_db"]:
            return wet
        dry, wet = np.asarray(dry, dtype=np.float64), np.asarray(wet, dtype=np.float64)
        if dry.ndim != 2 or wet.ndim != 2 or len(dry) != len(wet):
            raise ValueError("dry and wet must have equal frame counts")
        if self.state is None:
            self.state = np.zeros((self.window - 1, dry.shape[1]))
        if not len(dry):
            return wet.copy()
        power, self.state = signal.lfilter(np.ones(self.window) / self.window,
                                          [1.], dry * dry, axis=0, zi=self.state)
        key = np.sqrt(np.maximum(power, 0)).max(axis=1, keepdims=True)
        target = np.where(key > 10 ** (self.p["duck_threshold_db"] / 20), -self.p["duck_db"], 0.)
        self.last_gain_db = self.smoother.process(target)
        return wet * 10 ** (self.last_gain_db / 20)


def duck_wet(dry, wet, sr, params):
    """Apply SD once; duck_db=0 is an exact bypass."""
    return SelfDuck(sr, params).process(dry, wet)
