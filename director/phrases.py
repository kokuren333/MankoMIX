"""Read-only phrase descriptions using the shared edit-stage activity (X-06)."""
from __future__ import annotations

import math

import numpy as np

from mankomix.core.errors import MankoError
from . import edit as E
from . import placement as P
from . import query as Q
from . import stemobs as S
from .relate import _source


DEFAULT_MIN_GAP_MS = 250.0
NOTE = "先に計算して書いても、見つけ間違いと直しすぎは起きる。効き目は実証していない"
RELIABILITY = {"phrases": "medium", "syllables": "not_provided"}


class PhrasesInputError(S.StemObsError):
    """Invalid phrase inputs; no cleanup cache may be generated."""


def _intervals(x, sr):
    """Use first/last active window centres, retaining the signal endpoints.

    Shared runs cover entire 50 ms windows. Centre boundaries remove their
    half-window overhang without adding another detector or activity threshold.
    """
    mask, times, _ = P.activity(x, sr)
    duration = len(x) / sr
    half = E.FRAME_MS / 2000.0
    return [(0.0 if a == 0 else a + half,
             duration if b >= duration else b - half)
            for a, b in P.runs(mask, times)]


def _powers(x):
    """Prefix channel-mean power for stable, constant-cost interval RMS."""
    return np.r_[0.0, np.cumsum(E._power(x), dtype=np.float64)]


def _db(power, a, b):
    return Q._db((power[b] - power[a]) / (b - a)) if b > a else None


def phrases(project, track: str, *, min_gap_ms: float = DEFAULT_MIN_GAP_MS) -> dict:
    """Describe an audible mix-stage dry track; never suggest a gain.

    Gaps strictly shorter than min_gap_ms join active runs. Levels are full-band
    RMS dBFS, relative to the median phrase level. Head/tail cover at most 150 ms.
    Margin is target minus the coherent sum of all other audible dry tracks in
    1--4 kHz, using query's bandpass and dB floor. Low-margin windows are complete
    100 ms windows on the project-zero grid whose centres lie in active runs;
    they are sorted by reported margin, then time, and limited to 32.
    """
    if (isinstance(min_gap_ms, (bool, np.bool_)) or
            not isinstance(min_gap_ms, (int, float, np.integer, np.floating)) or
            not math.isfinite(min_gap_ms) or min_gap_ms < 0):
        raise PhrasesInputError("min_gap_ms must be a finite non-negative number")
    try:
        src = _source(project, None)
        src.check_track(track)
        stems, sr = src.dry()
        if sr / 2 <= 1000:
            raise PhrasesInputError("sample rate is too low for the 1--4 kHz margin")
        x = stems[track]
        active = _intervals(x, sr)
        joined = []
        for a, b in active:
            if joined and a - joined[-1][1] < min_gap_ms / 1000.0 - 1e-12:
                joined[-1] = (joined[-1][0], b)
            else:
                joined.append((a, b))
        other = np.zeros_like(x, dtype=np.float64)
        for tid in sorted(stems):
            if tid != track:
                other[:len(stems[tid])] += stems[tid]

        def band_power(y):
            # query's zero-phase filter needs padding for very short signals.
            padded = np.pad(y, ((0, max(0, 64 - len(y))), (0, 0)))
            return _powers(Q._bandpass(padded, sr, [1000, 4000])[:len(y)])

        full, target, against = _powers(x), band_power(x), band_power(other)

        def margin(a, b):
            return _db(target, a, b) - _db(against, a, b)

        rows = []
        edge = max(1, round(0.150 * sr))
        for n, (a, b) in enumerate(joined, 1):
            i, j = max(0, round(a * sr)), min(len(x), round(b * sr))
            if j <= i:
                continue
            rows.append({"n": n, "t0_s": a, "t1_s": b, "level_db": _db(full, i, j),
                         "level_rel_median_db": 0.0, "head_db": _db(full, i, min(j, i + edge)),
                         "tail_db": _db(full, max(i, j - edge), j), "margin_db": margin(i, j)})
        median = float(np.median([r["level_db"] for r in rows])) if rows else 0.0
        for row in rows:
            row["level_rel_median_db"] = row["level_db"] - median

        low = []
        window = max(1, round(0.100 * sr))
        run = 0
        for i in range(0, len(x) - window + 1, window):
            centre = (i + window / 2) / sr
            while run < len(active) and active[run][1] <= centre:
                run += 1
            if run < len(active) and active[run][0] <= centre < active[run][1]:
                low.append({"t_s": centre, "margin_db": margin(i, i + window)})
        low.sort(key=lambda r: (round(r["margin_db"], 3), r["t_s"]))

        def rounded(row):
            return {k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()}

        return {"kind": "direction_stem_phrases", "signal": "mix_stage_dry", "track": track,
                "phrases": [rounded(r) for r in rows], "low_margin": [rounded(r) for r in low[:32]],
                "reliability": dict(RELIABILITY), "note": NOTE}
    except (MankoError, OSError, ValueError, S.StemObsError) as exc:
        if isinstance(exc, PhrasesInputError):
            raise
        raise PhrasesInputError(str(exc)) from exc
