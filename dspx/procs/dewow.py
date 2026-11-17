"""T10-17: common-partial / pilot speed inference and manual inverse curves.

This spec-based estimator and its engineering thresholds are self-contained.
The shared weighting statistic is explicitly NOT a normative IEC detector.
"""
import numpy as np
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _e, _f


def validate(p):
    from mankomix.dspx.bb.restoration import validate_region
    validate_region(p)
    if p['min_rate_hz'] >= p['max_rate_hz']:
        raise ParamError('min_rate_hz must be below max_rate_hz')
    if p['pilot_hz'] and p['pilot_hz'] < 20:
        raise ParamError('pilot_hz must be zero or at least 20 Hz')
    if p['reference'] == 'pilot' and not p['pilot_hz'] and not p['curve']:
        raise ParamError('pilot reference requires pilot_hz or an explicit curve')


def dewow(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.dewow import estimate_speed, resample_inverse
    from mankomix.dspx.bb.curves import sample_curve
    from mankomix.dspx.bb.restoration import region_mix, finish
    from mankomix.dspx.procs.wow_flutter import weighted_measurement
    validate(p)
    if p['reference'] == 'pilot' and not p['curve'] and p['pilot_hz'] >= sr/2:
        raise ParamError('pilot_hz must be below Nyquist')
    speed, count, curve = np.zeros(len(x)), 0, []
    curve_thinned = False
    if p['amount'] and len(x):
        if p['curve']:
            speed = sample_curve(p['curve'], len(x), sr)*.01
            curve = [point.copy() for point in p['curve']]
        else:
            samples, values, count = estimate_speed(x, sr, p)
            speed = np.interp(np.arange(len(x)), samples, values)
            # Export bounded-size curve on an evenly thinned absolute grid.
            selected = np.unique(np.linspace(0, len(samples)-1, min(65536, len(samples))).astype(int))
            curve = [[float(samples[i]/sr), float(values[i]*100)] for i in selected]
            curve_thinned = len(selected) < len(samples)
    wet = resample_inverse(x, speed) if p['amount'] else x.copy()
    y = region_mix(x, wet, sr, p)
    # Remeasure the output audio, rather than assume the inverse removed speed.
    after = np.zeros(len(x))
    after_count = count
    if np.any(speed) and not p['curve']:
        samples, values, after_count = estimate_speed(y, sr, p)
        after = np.interp(np.arange(len(x)), samples, values)
    before_measure = weighted_measurement(speed[:, None], sr)
    required = 1 if p['reference'] == 'pilot' else 3
    measurable = not p['curve'] and after_count >= required
    after_measure = weighted_measurement(after[:, None], sr) if measurable else None
    return finish(x, y, sr, p, curve=curve, curve_thinned=curve_thinned,
                  component_count=count, after_component_count=after_count,
                  speed_peak_percent=float(np.max(abs(speed), initial=0)*100),
                  speed_rms_percent=float(np.sqrt(np.mean(speed**2))*100) if len(x) else 0.,
                  speed_measurement_before=before_measure, speed_measurement_after=after_measure,
                  speed_measurement_floor_percent=.02,
                  measurement_after_status=('audio_reestimated_with_deadband' if measurable else
                                            'not_measured_manual_curve' if p['curve'] else 'insufficient_components'))


from mankomix.dspx.bb.restoration import definition, rp_params
SPECS = [definition('dewow', rp_params()+[
    _e('reference', ['partials', 'pilot'], 'partials', 'Speed inference source.'),
    _f('pilot_hz', 'Hz', 0, 24000, 0, 'Known stable carrier; zero disables.'),
    _f('max_dev', '%', .05, 5, 1, 'Maximum tracked fractional speed in percent.'),
    _f('min_rate_hz', 'Hz', .05, 2, .2, 'Lowest restored modulation rate.'),
    _f('max_rate_hz', 'Hz', 1, 50, 12, 'Highest restored modulation rate.'),
    {'id': 'curve', 'type': 'curve', 'unit': '%', 'x_min': 0, 'x_max': 36000,
     'y_min': -5, 'y_max': 5, 'max_points': 65536, 'default': [],
     'description': 'Time in seconds and observed speed deviation in percent; skips inference.'}])]
SPECS[0]['description'] = 'Offline common-component speed restoration and editable inverse curve.'
SPECS[0]['implemented'] = True
IMPLS = {'dewow': dewow}
CROSS_VALIDATE = {'dewow': validate}
