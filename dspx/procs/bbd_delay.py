"""BBD echo with an event queue, analytic filters, and envelope companding."""
import numpy as np
from functools import lru_cache
from mankomix.dspx.params import _b, _e, _f


@lru_cache(maxsize=128)
def repeat_filter_delay(relative_cutoff):
    """Mean excess interval in unit-clock cycles, independent of transport.

    With q=N/2, output steps start at m+q-1/2. Between traversals the two
    filters have step response S2, so their sampled hold kernel is
    g[j]=S2(j+1/2)-S2(j-1/2). The nth output is the convolution of sampled
    input impulse h[m], g**(n-1), and the output hold/filter response.
    All allowed stage counts translate this response by n*q whole cycles.
    This small unit-clock calculation includes finite-clock dispersion;
    it never renders, measures or normalizes the user's audio.
    """
    from scipy import optimize, signal
    b, a = signal.butter(5, 1, analog=True)
    residues, poles, _ = signal.residue(b, a)
    simple = np.array([2*r*np.sum(residues[np.arange(5) != i]/(p-poles[np.arange(5) != i]))
                       for i, (r, p) in enumerate(zip(residues, poles))])
    rate = 2*np.pi*relative_cutoff
    def step(times, squared=False):
        times = np.asarray(times)
        positive = np.maximum(times, 0)[..., None]
        exponential = np.exp(positive*poles)
        if squared:
            values = simple*(exponential-1)/poles + residues**2*(
                exponential*(positive/poles-1/poles**2)+1/poles**2)
        else:
            values = residues/poles*(exponential-1)
        return np.where(times >= 0, np.sum(values, axis=-1).real, 0)
    # exp(-60*sin(pi/10)) < 9e-9; repeated convolution retains the full
    # growing support. Future coefficients cannot affect the causal peaks.
    events = np.arange(int(np.ceil(60/rate)))
    sampled = rate*np.real(np.exp(rate*events[:, None]*poles).dot(residues))
    kernel = step(rate*(events+.5), True)-step(rate*(events-.5), True)
    continuous_modes = (7.348101485, 14.294103031, 21.073980388, 27.781821250, 34.448181929)
    peaks = []
    for mode in continuous_modes:
        def response(time):
            times = rate*(time-np.arange(len(sampled)))
            return np.sum(sampled*(step(times+rate/2)-step(times-rate/2)))
        peak = optimize.minimize_scalar(lambda time: -response(time),
            bounds=(mode/rate-1, mode/rate+1), method='bounded', options={'xatol': 1e-10})
        peaks.append(float(peak.x))
        sampled = np.convolve(sampled, kernel)
    dc_delay = 2/np.sin(np.pi/10)/rate
    dispersion = (peaks[-1]-peaks[0])/4-dc_delay
    return dc_delay+dispersion


def compensated_delay(samples, sr, stages, tone):
    """Convert total repeat time to capacitor transport time, in samples.

    Both fifth-order Butterworth filters contribute DC delay
    2*csc(pi/10)/(2*pi*cutoff). Their dispersive peak modes also move with
    traversal count. For normalized cutoff 1 rad/s, H(s)^(2*n), n=1..5,
    has first positive peak times 7.348101485, 14.294103031, 21.073980388,
    27.781821250, 34.448181929. The mean spacing is 6.775020111084334.
    In the clock-relative branch, include the exact sampled/held response
    instead of the continuous approximation. This preserves the causal
    filters rather than advancing their output.
    """
    dc_phase = 2/np.sin(np.pi/10)
    dispersion_phase = 6.775020111084334-dc_phase
    phase_delay = (dc_phase+dispersion_phase)/(2*np.pi)
    relative_cutoff = .12+.12*tone
    # Solve total time = transport + DC filter delay + dispersive residual.
    relative = np.asarray(samples, dtype=np.float64)/(1+2*repeat_filter_delay(relative_cutoff)/stages)
    capped = np.asarray(samples, dtype=np.float64)-phase_delay/.18
    delay = np.where(relative_cutoff*stages/(2*relative) > .18, capped, relative)
    if np.any(delay <= 0):
        from mankomix.dsp.errors import ParamError
        raise ParamError('time_ms is shorter than the BBD filter delay at this sample rate')
    return delay


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
    base_delay = compensated_delay(duration(p, 1200)*sr/1000, sr, p['stages'], p['tone'])
    ds = base_delay/clock_mod
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
    return finish(x, wet, sr, p, dict(clock_hz=float(p['stages']*sr/(2*base_delay)),
                                    transport_delay_samples=float(base_delay),
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
        _f('mod_rate_hz', 'Hz', .05, 10, .5, 'Clock modulation rate.')], implemented=True)]


SPECS = _declarations()
IMPLS = {'bbd_delay': bbd_delay}
CROSS_VALIDATE = {'bbd_delay': cross_validate}
TIME_VARYING = {'bbd_delay'}
