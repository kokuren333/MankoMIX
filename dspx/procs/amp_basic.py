"""Deterministic coupling stages, passive tone network and push-pull output."""
import numpy as np
from scipy import signal
from mankomix.dspx.params import _f, _i, _b, _e


def amp_basic(x, sr, p, *, seed=0):
    from mankomix.dspx.bb import nonlinear as N
    from mankomix.dspx.bb.amp_circuit import triode, tone_coefficients, reference_makeup, alignment_samples
    output = p['output_db']-(p['drive_db'] if p['auto_gain'] else 0)
    if not len(x) or p['mix'] == 0 or (p['drive_db'] == 0 and p['power_drive_db'] == 0):
        return N.mix_output(x, x, 0, output), sr, {'latency_samples': 0}
    factor = p['oversample']
    operating_sr = sr*factor
    strength = .08*10**(p['drive_db']/20/p['stages'])
    def process(u):
        wet = u.copy()
        if p['bright']:
            low = N.filter_audio(wet, operating_sr, 1600, order=1)
            wet = low+1.6*(wet-low)
        for _ in range(p['stages']):
            wet = N.filter_audio(wet, operating_sr, 12, 'highpass', 1)
            wet = triode(wet, strength)
            wet = N.filter_audio(wet, operating_sr, 14000, order=1)
        wet = signal.sosfilt(tone_coefficients(operating_sr, p), wet, axis=0)
        wet *= reference_makeup(operating_sr, p['stages'])
        if p['power_drive_db']:
            power = .4*10**(p['power_drive_db']/20)
            wet = np.tanh(power*wet)/power
        return wet
    wet = N.precision_oversampled(x, factor, process)
    sag_db = np.zeros(len(x))
    if p['sag']:
        # 80 ms charge envelope, 0..3 dB voltage droop at unit drive.
        a = np.exp(-1/(.080*sr))
        envelope = signal.lfilter([1-a], [1, -a], np.max(np.abs(x), axis=1))
        sag_db = 3*p['sag']*np.clip(envelope, 0, 1)
        wet *= 10**(-sag_db[:, None]/20)
    if p['presence_db']:
        from mankomix.dsp.reference.filters import rbj_biquad
        wet = signal.sosfilt(rbj_biquad('high_shelf', 3000, p['presence_db'], 1, sr), wet, axis=0)
    # A double DC zero removes the area of the asymmetric turn-on
    # transient; subtracting a one-pole record mean alone leaves a
    # constant offset in otherwise settled portions of long records.
    wet = N.filter_audio(wet, sr, 20, 'highpass', 2)
    wet -= np.mean(wet, axis=0)
    advance = alignment_samples(sr, factor, *(p[k] for k in (
        'stages', 'bright', 'bass', 'mid', 'treble', 'tonestack', 'presence_db')))
    if advance > 0:
        wet = np.pad(wet[advance:], ((0, min(advance, len(wet))), (0, 0)))
    return N.mix_output(x, wet, p['mix'], output), sr, dict(
        latency_samples=0, internal_oversample=factor, latency_compensated=True,
        circuit_delay_samples=advance,
        sag_tau_ms=80., sag_max_db=float(np.max(sag_db, initial=0.)), cabinet_included=False)


SPECS = [dict(type='amp_basic', implemented=True, description='Deterministic generic amplifier.',
    stages=['track'], master_slot=None, offline_only=False, backends=['reference'], channel_ok=True,
    realtime=dict(block_ok=False, allocates=True, latency_samples=0,
                  latency_rule='Resampling and integer circuit peak delay compensated offline; residual circuit phase retained.'),
    params=[_f('drive_db','dB',0,60,24,'Preamp drive.'), _f('output_db','dB',-36,12,0,'Output gain.'),
        _b('auto_gain',False,'Subtract drive_db.'), _f('mix',None,0,1,1,'Aligned mix.'),
        _e('oversample',[1,2,4,8],8,'Operating rate.'), _i('stages',None,1,4,2,'Amplifying stages.'),
        _b('bright',False,'First-stage brightness.'), _f('bass',None,0,1,.5,'Bass resistance.'),
        _f('mid',None,0,1,.5,'Mid resistance.'), _f('treble',None,0,1,.5,'Treble resistance.'),
        _e('tonestack',['scoop','flat','mid_forward'],'scoop','Generic component ratios.'),
        _f('power_drive_db','dB',0,24,0,'Symmetric output saturation.'),
        _f('sag',None,0,1,.2,'Power supply envelope droop.'),
        _f('presence_db','dB',-6,6,0,'High shelf.')])]
IMPLS = {'amp_basic': amp_basic}
TIME_VARYING = {'amp_basic'}
