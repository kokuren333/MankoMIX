"""Protection stage (SPEC 6.4.2 step 4): keep sibilants, breaths and cymbals.

Detection runs on the input mid signal per STFT frame:

* sibilant event: the 5-8 kHz per-bin power density is close to (or above)
  the 1-5 kHz density, the band is noise-like (spectral flatness) and it
  stands clearly above its own quiet level;
* breath/cymbal event: noise-like 2-8 kHz energy clearly above its quiet
  level.

The result is a cap on the total reduction (dB) per STFT cell, applied by
the spectral stage on top of the band policy's own total caps (R-29: the
counter-weight to "remove shimmer" is "do not eat the consonants").
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from ._util import EPS, bin_range, v


def _flatness(p: np.ndarray) -> np.ndarray:
    """Spectral flatness per frame (geometric / arithmetic mean of power)."""
    lp = np.log(p.astype(np.float64) + EPS)
    gm = np.exp(lp.mean(axis=1))
    am = p.mean(axis=1) + EPS
    return gm / am


def detect_events(power: np.ndarray, freqs: np.ndarray, frame_rate: float, policy: dict) -> dict:
    """Per-frame boolean masks ``sibilant`` and ``noise_event``."""
    pol = policy["protection"]
    t = power.shape[0]
    out = {"sibilant": np.zeros(t, bool), "noise_event": np.zeros(t, bool)}
    if t == 0:
        return out
    sp = pol["sibilant"]
    s_sl = bin_range(freqs, *v(sp["band_hz"]))
    r_sl = bin_range(freqs, *v(sp["ref_band_hz"]))
    if s_sl.stop - s_sl.start >= 2 and r_sl.stop - r_sl.start >= 2:
        ps = power[:, s_sl]
        dens_s = ps.mean(axis=1) + EPS
        dens_r = power[:, r_sl].mean(axis=1) + EPS
        ratio = 10.0 * np.log10(dens_s / dens_r)
        flat = _flatness(ps)
        floor = np.percentile(dens_s, 20.0)
        above = 10.0 * np.log10(dens_s / (floor + EPS))
        sib = ((ratio >= float(v(sp["density_ratio_db"])))
               & (flat >= float(v(sp["min_flatness"])))
               & (above >= float(v(sp["level_above_floor_db"]))))
        dil = max(1, int(round(float(v(sp["dilate_s"])) * frame_rate)))
        out["sibilant"] = ndimage.maximum_filter1d(sib, 2 * dil + 1)
    ne = pol["noise_event"]
    n_sl = bin_range(freqs, *v(ne["band_hz"]))
    if n_sl.stop - n_sl.start >= 2:
        pn = power[:, n_sl]
        lvl = pn.mean(axis=1) + EPS
        floor = np.percentile(lvl, 20.0)
        above = 10.0 * np.log10(lvl / (floor + EPS))
        noise = (_flatness(pn) >= float(v(ne["min_flatness"]))) & (above >= float(v(ne["level_above_floor_db"])))
        out["noise_event"] = ndimage.maximum_filter1d(noise & ~out["sibilant"], 3)
    return out


def protection_caps(power: np.ndarray, freqs: np.ndarray, frame_rate: float, policy: dict) -> tuple[np.ndarray, dict]:
    """Cap on the total reduction in dB, [frames, bins] float32 (inf = no cap
    from protection; the band policy's own caps still apply)."""
    pol = policy["protection"]
    ev = detect_events(power, freqs, frame_rate, policy)
    t, k = power.shape
    caps = np.full((t, k), np.inf, dtype=np.float32)
    sp = pol["sibilant"]
    lo, hi = v(sp["cap_band_hz"])
    sib_bins = (freqs >= lo) & (freqs < hi)
    up_bins = (freqs >= hi) & (freqs < float(v(sp["upper_cap_hz"])))
    sib = ev["sibilant"]
    if np.any(sib):
        caps[np.ix_(sib, sib_bins)] = float(v(sp["cap_db"]))
        caps[np.ix_(sib, up_bins)] = float(v(sp["upper_cap_db"]))
    ne = ev["noise_event"]
    if np.any(ne):
        caps[ne, :] = np.minimum(caps[ne, :], float(v(pol["noise_event"]["cap_db"])))
    info = {
        "sibilant_frames": int(np.sum(sib)),
        "noise_event_frames": int(np.sum(ne)),
        "sibilant_seconds": round(float(np.sum(sib)) / frame_rate, 3),
        "noise_event_seconds": round(float(np.sum(ne)) / frame_rate, 3),
        "sibilant_cap_db": float(v(sp["cap_db"])),
        "noise_event_cap_db": float(v(pol["noise_event"]["cap_db"])),
    }
    return caps, info


class Protector:
    """Callable for :func:`spectral.reduce` that remembers its last info."""

    def __init__(self, policy: dict):
        self.policy = policy
        self.info: dict = {}

    def __call__(self, power: np.ndarray, freqs: np.ndarray, frame_rate: float) -> np.ndarray:
        caps, self.info = protection_caps(power, freqs, frame_rate, self.policy)
        return caps
