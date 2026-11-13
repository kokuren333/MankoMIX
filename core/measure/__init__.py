"""Standards-based measurement layer (SPEC 4.2, 4.3, 6.3, 16.1).

Public API (contract for ingest, CLI, mastering and verification):

    from mankomix.core.measure import measure_signal, measure_file, compare
    from mankomix.core.measure.loudness import integrated, true_peak_dbtp, ...

No librosa here: the core path depends only on numpy and scipy.
"""

from __future__ import annotations

from .bands import BANDS_P07, BANDS_P22, Band, Spectrum, clip_bands, split_bands
from .compare import compare
from .loudness import (integrated, k_weighting_sos, loudness_range, loudness_summary, momentary,
                       sample_peak_dbfs, short_term, true_peak_dbtp, true_peak_per_channel)
from .stereo import low_band_negative_persistence
from .vector import ANALYZER_VERSION, json_safe, measure_file, measure_signal

__all__ = [
    "ANALYZER_VERSION", "BANDS_P07", "BANDS_P22", "Band", "Spectrum", "clip_bands", "split_bands",
    "compare", "integrated", "k_weighting_sos", "loudness_range", "loudness_summary", "momentary",
    "sample_peak_dbfs", "short_term", "true_peak_dbtp", "true_peak_per_channel",
    "low_band_negative_persistence", "json_safe", "measure_file", "measure_signal",
]
