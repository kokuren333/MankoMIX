"""One-sided integer delay, protecting low frequencies with BB-02a."""
import numpy as np
from scipy import signal

from mankomix.dspx.params import _e, _f
from mankomix.dspx.bb.crossover import split_bands, taps_for
from mankomix.dspx.bb.delayline import definition, fractional_delay, spatial_stats


def latency_samples(sr, p):
    return (taps_for(p["lo_keep_hz"], sr) - 1) // 2 if p["delay_ms"] and p["lo_keep_hz"] else 0


def haas(x, sr, p, *, seed=0, compensate=True):
    if not p["delay_ms"]:
        return x.copy(), sr, spatial_stats(x, sr, 0)
    source = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x.copy()
    if p["input"] == "mono_sum":
        source = np.repeat(np.mean(x, axis=1)[:, None], 2, axis=1)
    if p["lo_keep_hz"]:
        edge = p["lo_keep_hz"]
        if edge >= 20:
            bands, meta = split_bands(source, sr, [edge], "linear", compensate=compensate)
            low, high = bands
        else:
            # BB-02's MB contract starts at 20 Hz; Haas explicitly allows (0,20).
            # Use the same complementary FIR construction for this extra range.
            taps = taps_for(edge, sr)
            latency = (taps - 1) // 2
            kernel = signal.firwin(taps, edge, fs=sr, window=("kaiser", signal.kaiser_beta(90)))
            begin = latency if compensate else 0
            low = signal.oaconvolve(source, kernel[:, None], mode="full", axes=0)[begin:begin+len(x)]
            full = source if compensate else np.pad(source, ((latency, 0), (0, 0)))[:len(x)]
            high = full - low
            meta = {"latency_samples": latency, "latency_compensated": compensate, "fir_taps": taps}
    else:
        low, high = np.zeros_like(source), source.copy()
        meta = {"latency_samples": 0, "latency_compensated": True}
    side = 0 if p["side"] == "left" else 1
    d = round(p["delay_ms"] * sr / 1000)
    delayed = fractional_delay(high[:, side:side+1], d, "integer")
    cutoff = p["delayed_highcut_hz"]
    if 0 < cutoff < sr / 2:
        delayed = signal.sosfilt(signal.butter(1, cutoff, fs=sr, output="sos"), delayed, axis=0)
    high[:, side] = delayed[:, 0] * 10 ** (p["delayed_db"] / 20)
    y = low + high
    stats = spatial_stats(y, sr, p["delay_ms"])
    stats.update(meta, delay_samples=d)
    return y, sr, stats


SPECS = [definition("haas", [
    _f("delay_ms", "ms", 0, 40, 12, "Delay on selected side; zero is exact bypass."),
    _e("side", ["left", "right"], "right", "Delayed side."),
    _f("delayed_db", "dB", -12, 6, 0, "Delayed high-band level."),
    _f("delayed_highcut_hz", "Hz", 0, 20000, 0, "6 dB/oct lowpass on delayed side only."),
    _f("lo_keep_hz", "Hz", 0, 500, 120, "Protected low band; zero bypasses split."),
    _e("input", ["mono_sum", "stereo"], "mono_sum", "Source routing."),
], latency_rule="delay_ms>0 and lo_keep_hz>0: (BB-02a FIR taps-1)/2; offline compensated")]
IMPLS = {"haas": haas}
