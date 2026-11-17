"""Recording emphasis, oversampled magnetization, playback loss and motion."""
import numpy as np
from scipy import signal
from mankomix.dspx.params import _f, _e, _b, _i


def tape(x, sr, p, *, seed=0):
    from mankomix.dspx.bb import nonlinear as N
    from mankomix.dspx.bb.tape_model import (
        magnetize, loss_fir, recording_eq, head_bump_sos, playback_makeup)
    from mankomix.dspx.bb.fir import apply_fir
    if p['amount'] == 0 or not len(x):
        return x.copy(), sr, {'latency_samples': 0, 'bypassed': True}
    output = p['output_db']-(p['drive_db'] if p['auto_gain'] else 0)
    if p['mix'] == 0:
        return N.mix_output(x, x, 0, output), sr, {'latency_samples': 0}
    factor = 8 if p['hysteresis'] else 2*p['oversample']
    gain = 10**(p['drive_db']/20)
    b, a = recording_eq(sr*factor, p['speed'])
    def record(u):
        field = signal.lfilter(b, a, u, axis=0)
        return magnetize(field*gain, p['saturation'], p['bias'], p['hysteresis'])/gain
    wet = N.precision_oversampled(x, factor, record)
    h = loss_fir(sr, p['speed'], p['gap_loss'], p['bias'])
    wet, info = apply_fir(wet, h, sr)
    if p['head_bump_db']:
        wet = signal.sosfilt(head_bump_sos(sr, p['speed'], p['head_bump_db']), wet, axis=0)
    # Playback uses the exact reciprocal at the same operating rate.
    wet = N.precision_oversampled(wet, factor, lambda u: signal.lfilter(a, b, u, axis=0))
    wet = N.dc_block(wet, sr)
    makeup = playback_makeup(sr, p['speed'], p['gap_loss'], p['bias'], p['head_bump_db'])
    wet *= makeup
    if p['wow_depth'] or p['flutter_depth']:
        from mankomix.dspx.bb.wobble import wobble_from_params, base_latency
        from mankomix.dspx.bb.modulation import read_modulated
        controls = dict(p, wow_rate_hz=.6, flutter_rate_hz=9, drift=.3)
        displacement, _ = wobble_from_params(len(x), sr, controls, channels=x.shape[1], seed=seed)
        wet = read_modulated(wet, displacement, latency=base_latency(sr, controls), compensate=True)
    if p['noise_db'] > -120:
        rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(seed), p['seed']])))
        noise = N.filter_audio(rng.standard_normal(x.shape), sr, min(.4*sr, 700*p['speed']))
        noise -= np.mean(noise, axis=0)
        noise /= np.maximum(np.sqrt(np.mean(noise*noise, axis=0)), 1e-30)
        wet += noise*10**(p['noise_db']/20)
    amount = p['amount']*p['mix']
    info.update(internal_oversample=factor, loss_latency_samples=(len(h)-1)//2,
                latency_compensated=True, ode='fixed_RK4' if p['hysteresis'] else 'memoryless',
                head_bump_hz=60*p['speed']/15)
    info['reference_makeup_db'] = 20*np.log10(makeup)
    return N.mix_output(x, wet, amount, output), sr, info


SPECS = [dict(type='tape', implemented=True, description='Generic physical tape model.',
    stages=['track', 'bus', 'master'], master_slot=3, offline_only=False,
    backends=['reference'], channel_ok=True,
    realtime=dict(block_ok=False, allocates=True, latency_samples='variable',
                  latency_rule='Loss FIR half length; resampling and optional motion compensated offline.'),
    params=[_f('drive_db','dB',0,24,0,'Magnetic drive.'),
        _f('output_db','dB',-36,12,0,'Output gain.'), _b('auto_gain',False,'Subtract drive_db.'),
        _f('mix',None,0,1,1,'Aligned mix.'), _e('oversample',[1,2,4,8],4,'Memoryless rate control; internal rate is twice this value.'),
        _f('amount',None,0,1,1,'Zero bypasses all stages.'),
        _e('speed',[3.75,7.5,15,30],15,'Tape speed.',unit='ips'),
        _f('bias',None,0,1,.5,'Model bias.'), _f('saturation',None,0,1,.5,'Magnetization strength.'),
        _b('hysteresis',True,'Fixed RK4 at 8x.'), _f('head_bump_db','dB',0,6,1.5,'Speed-scaled peak.'),
        _f('gap_loss',None,0,1,.5,'Playback losses.'), _f('wow_depth','%',0,3,0,'Slow motion.'),
        _f('flutter_depth','%',0,1,0,'Fast motion.'), _f('noise_db','dBFS',-120,-50,-120,'Noise floor.'),
        _i('seed',None,0,65535,0,'Parameter seed.')])]
IMPLS = {'tape': tape}
