"""Integrated tape speed motion using the reusable BB wobble generator."""
import numpy as np
from scipy import signal

from mankomix.dspx.params import _f, _i
from mankomix.dspx.bb.wobble import wobble_from_params, base_latency
from mankomix.dspx.bb.modulation import read_modulated, modulation_definition
from mankomix.dspx.bb.delayline import spatial_stats


def weighting_sos(sr):
    """Self-contained weighting, NOT a verified normative IEC filter.

    H(s)=K*s**2/((s+2*pi*.5)*(s+2*pi*4)**2), |H(j*2*pi*4)|=1.
    Two low-frequency zeros, -6 dB/oct high-frequency slope. Bilinear
    transform, normalised digitally at 4 Hz. Constants and detector are
    explicitly defined in C3_report.md under the authorised fallback.
    """
    low, centre = 2*np.pi*.5, 2*np.pi*4
    zeros, poles, gain = signal.bilinear_zpk([0., 0.], [-low, -centre, -centre], 1., fs=sr)
    sos = signal.zpk2sos(zeros, poles, gain)
    _, response = signal.sosfreqz(sos, worN=[4.], fs=sr)
    sos[0, :3] /= abs(response[0])
    return sos


def weighted_measurement(speed, sr):
    """Filter known fractional speed; report per-channel two-sigma %, max overall.

    Zero initial state, all supplied frames, population standard deviation.
    Durations below 5 s are explicitly marked diagnostic. Measuring the
    generator avoids carrier demodulation/interpolation error in R-10.
    """
    filtered = signal.sosfilt(weighting_sos(sr), speed, axis=0) if len(speed) else speed
    vector = 200*np.std(filtered, axis=0) if len(speed) else np.zeros(speed.shape[1])
    return {'iec_60386_weighted_percent': float(np.max(vector, initial=0.)),
            'weighted_percent_by_channel': vector.tolist(),
            'weighting_status': 'self_contained_spec_fallback; IEC coefficients/detector unverified',
            'weighting_detector': '2 * population_std(filtered_speed) * 100',
            'weighting_duration_s': len(speed)/sr,
            'weighting_minimum_5s': len(speed) >= 5*sr}


def raw_wow_flutter(x, sr, p, *, seed=0, compensate=False):
    displacement, speed = wobble_from_params(len(x), sr, p, channels=x.shape[1], seed=seed, close_60s=True)
    latency = base_latency(sr, p)
    y = read_modulated(x, displacement, latency=latency, compensate=compensate)
    stats = {'latency_samples': latency, 'latency_compensated': compensate,
             'speed_peak_percent': float(abs(speed).max()*100) if speed.size else 0.,
             'speed_mean_percent': float(speed.mean()*100) if speed.size else 0.}
    stats.update(weighted_measurement(speed, sr))
    return y, sr, stats


def wow_flutter(x, sr, p, *, seed=0):
    y, _, stats = raw_wow_flutter(x, sr, p, seed=seed, compensate=True)
    stats.update({k: v for k, v in spatial_stats(y, sr).items() if k != 'latency_samples'})
    return y, sr, stats


SPECS = [modulation_definition('wow_flutter', [
    _f('wow_depth', '%', 0, 3, .2, 'Peak slow speed deviation.'),
    _f('wow_rate_hz', 'Hz', .1, 4, .6, 'Slow modulation rate.'),
    _f('flutter_depth', '%', 0, 1, .05, 'Peak fast speed deviation.'),
    _f('flutter_rate_hz', 'Hz', 4, 50, 9, 'Fast modulation rate.'),
    _f('drift', None, 0, 1, .3, 'Band-limited irregular proportion.'),
    _f('scrape', None, 0, 1, 0, 'Small high-frequency speed noise.'),
    _f('stereo_link', None, 0, 1, 1, 'Shared left/right motion.'),
    _i('seed', None, 0, 65535, 0, 'Deterministic parameter seed.')],
    latency_rule='bb.wobble.base_latency(sr, params); compensated offline', implemented=True)]
TIME_VARYING = {'wow_flutter'}
IMPLS = {'wow_flutter': wow_flutter}
