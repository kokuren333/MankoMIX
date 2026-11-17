"""BBD echo with an event queue, analytic filters, and envelope companding."""
import numpy as np
from mankomix.dspx.params import _b, _e, _f


def cross_validate(p):
    from mankomix.dspx.bb.delayfx import duration, validate_delay
    validate_delay(p, 1200, longest=duration(p, 1200)/(1-p['mod_depth']/100))


def bbd_delay(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.bbd import BBDPlan, envelope_compand
    from mankomix.dspx.bb.delayline import LoopFilter
    from mankomix.dspx.bb.delayfx import duration, finish
    from mankomix.dspx.bb.modulation import combined_seed
    cross_validate(p)
    if not p['mix']:
        return finish(x, x, sr, p)
    clock_mod = 1+p['mod_depth']/100*np.sin(2*np.pi*p['mod_rate_hz']*np.arange(len(x))/sr)
    ds = duration(p, 1200)*sr/1000/clock_mod
    plan = BBDPlan(len(x), sr, ds, p['stages'], p['tone'])
    noise = np.zeros_like(x)
    if p['noise_db'] > -120:
        noise = np.random.Generator(np.random.PCG64(combined_seed(seed, p))).standard_normal(x.shape)*10**(p['noise_db']/20)
    wet = np.zeros_like(x)
    # All traversals share the same absolute-clock lattice. Each fixed-point
    # iteration starts filters at zero; no state is accidentally reused.
    for iteration in range(2048):
        eq = LoopFilter(sr, x.shape[1], min(p['lowcut_hz'], .49*sr), p['highcut_hz'])
        source = x+p['feedback']*eq(wet)
        if p['compander']:
            source = envelope_compand(source, sr)
        updated = plan.process(source)+noise
        if p['compander']:
            updated = envelope_compand(updated, sr, inverse=True)
        difference = np.max(np.abs(updated-wet), initial=0)
        wet = updated
        if not p['feedback'] or difference < 2e-14:
            break
    else:
        from mankomix.dsp.errors import ParamError
        raise ParamError('BBD full-context feedback solve did not converge')
    return finish(x, wet, sr, p, dict(clock_hz=p['stages']/(2*duration(p, 1200)/1000),
                                    bbd_filter_order=5, iterations=iteration+1,
                                    bbd_filter_model='analytic_modal_piecewise_clock'))


def _declarations():
    from mankomix.dspx.bb.delayfx import definition, dl_parameters
    return [definition('bbd_delay', dl_parameters(time_ms=dict(min=5, max=1200, default=300)) + [
        _e('stages', [1024,2048,4096,8192], 4096, 'Capacitor stage count.'),
        _b('compander', True, 'Envelope-following 2:1 / 1:2 compander.'),
        _f('tone', None, 0, 1, .5, 'Clock-relative input/output cutoff scale.'),
        _f('noise_db', 'dBFS', -120, -50, -120, 'Internal noise; -120 bypasses.'),
        _f('mod_depth', '%', 0, 2, 0, 'Clock rate deviation.'),
        _f('mod_rate_hz', 'Hz', .05, 10, .5, 'Clock modulation rate.')])]


SPECS = _declarations()
IMPLS = {'bbd_delay': bbd_delay}
CROSS_VALIDATE = {'bbd_delay': cross_validate}
TIME_VARYING = {'bbd_delay'}
