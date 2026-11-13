"""Cleanup stage (整音, SPEC 6.4): diagnosis, click repair, detection-based
spectral reduction, protection, optional deterministic HF completion,
verification (S-07 null test, P-21 side effects, delta) and the noise-return
guard (S-08).

Policy and thresholds: knowledge/cleanup_policy.json (initial values).
"""

from .clicks import detect_clicks, repair_clicks
from .complete import complete_hf, neural_completion
from .diagnose import diagnose, noise_shimmer_metrics
from .guard import noise_baseline, noise_return_check, reference_selection, side_effects
from .pipeline import CleanupResult, null_test_residual_dbfs, plan_cleanup, run_cleanup

__all__ = [
    "CleanupResult", "complete_hf", "detect_clicks", "diagnose", "neural_completion",
    "noise_baseline", "noise_return_check", "noise_shimmer_metrics", "null_test_residual_dbfs",
    "plan_cleanup", "reference_selection", "repair_clicks", "run_cleanup", "side_effects",
]
