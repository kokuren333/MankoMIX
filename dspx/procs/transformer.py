"""Memoryless magnetization in a leaky flux path; no hysteresis model."""
import numpy as np
from scipy import signal
from mankomix.dspx.params import _f


def transformer(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.nonlinear import (oversampled, oversampling_info,
                                           transformer_flux, mix_output)
    factor = int(p['oversample'])
    bypass = p['drive_db'] == 0 or p['mix'] == 0
    resonance = p['hf_resonance_db'] != 0 and p['hf_resonance_hz'] < .45*sr
    if bypass:
        wet = x.copy()
    else:
        def callback(u):
            v = transformer_flux(u, sr*factor, p['drive_db'], p['lf_corner_hz'],
                                 p['core'], p['lf_emphasis'])
            if resonance:
                # A generic damped LC peak, unity low/high asymptotes, Q=1.
                # Prewarped only at its center, inside the nonlinear OS path.
                a = 10.0**(p['hf_resonance_db']/40)
                w = 2*sr*factor*np.tan(np.pi*p['hf_resonance_hz']/(sr*factor))
                b, d = signal.bilinear([1, a*w, w*w], [1, w/a, w*w], fs=sr*factor)
                v = signal.sosfilt(signal.tf2sos(b, d), v, axis=0)
            return v
        wet = oversampled(x, factor, callback)
    output_db = p['output_db']-p['drive_db']*int(p['auto_gain'])
    y = mix_output(x, wet, p['mix'], output_db)
    stats = dict(oversampling_info(1 if bypass else factor), flux_reference_hz=200,
                 flux_bias=.002*p['core'], hysteresis=False,
                 hf_resonance_applied=resonance and not bypass,
                 dc_method='flux_differentiation_and_direct_arm_highpass',
                 saturation_bypassed=bypass, model='leaky_flux_chain_rule',
                 auto_gain_coefficient=1)
    return y, sr, stats


def _spec():
    from mankomix.dspx.bb.nonlinear import nl_params, specification
    return specification('transformer', nl_params(drive_max=24)+[
        _f('lf_corner_hz', 'Hz', 5, 80, 20, 'Primary-inductance low corner.'),
        _f('core', '0..1', 0, 1, .5, 'Magnetization hardness.'),
        _f('lf_emphasis', '0..1', 0, 1, .7, 'Flux-path share; zero is frequency-independent drive.'),
        _f('hf_resonance_db', 'dB', 0, 6, 0, 'Generic leakage/capacitance resonance gain.'),
        _f('hf_resonance_hz', 'Hz', 15000, 60000, 30000, 'Resonance center; disabled at or above .45*sr.')],
        'Leaky voltage-to-flux integration, magnetization saturation, and differentiated output.')


SPECS = [dict(_spec(), implemented=True)]
IMPLS = {'transformer': transformer}
