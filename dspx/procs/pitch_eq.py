"""T02-05 pYIN-following TPT EQ; existing BB-12 and BB-05 are reused."""
import numpy as np
from scipy import ndimage, signal
from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _e


def validate(p):
    if p['f0_min_hz'] >= p['f0_max_hz']:
        raise ParamError('f0_min_hz must be below f0_max_hz')


def centers(x, sr, p):
    """Return sample centers, bypass opening, and the resolved pre-glide F0 curve."""
    from mankomix.dspx.bb.curves import sample_curve
    from mankomix.dspx.bb.pitch import detect_pitch
    validate(p)
    if not len(x):
        return np.empty(0), np.empty(0), []
    if p['track']:
        curve = p['track']
        f0 = sample_curve(curve, len(x), sr)
        voiced = np.ones(len(x), dtype=bool)
    else:
        from importlib.metadata import version
        if version('librosa') != '1.0.0':
            raise ParamError('pitch_eq automatic tracking requires librosa 1.0.0')
        if p['f0_max_hz'] >= sr/2:
            raise ParamError('f0_max_hz must be below Nyquist for automatic tracking')
        frame = 2**int(np.ceil(np.log2(2*sr/p['f0_min_hz']+1)))
        # High partials above the declared tracking range need not dominate
        # the difference function. This filter is only on the analysis input.
        detector = signal.sosfiltfilt(signal.butter(4,p['f0_max_hz'],fs=sr,output='sos'),
                                     x,axis=0,padlen=min(len(x)-1,round(.02*sr))) if len(x)>1 else x
        tr = detect_pitch(detector, sr, method='pyin', fmin=p['f0_min_hz'], frame_length=frame,
                          fmax=p['f0_max_hz'], voiced_threshold=p['confidence'])
        hz = tr.f0_hz.copy()
        good = tr.voiced & (tr.probability >= p['confidence'])
        # Median only within each continuous voiced run; do not bridge silence.
        from mankomix.dspx.bb.restoration import runs
        for a, b in runs(good):
            hz[a:b] = ndimage.median_filter(hz[a:b], size=3, mode='nearest')
        last = p['fallback_hz']
        for i in range(len(hz)):
            if good[i]:
                last = hz[i]
            else:
                hz[i] = last if p['unvoiced'] == 'hold' else p['fallback_hz']
        curve = [[int(n)/sr, float(h)] for n, h in zip(tr.samples, hz)]
        f0 = sample_curve(curve, len(x), sr)
        nearest = np.minimum((np.arange(len(x))+tr.hop_samples//2)//tr.hop_samples, len(good)-1)
        voiced = good[nearest]
    target = np.minimum(.45*sr, f0*p['harmonic']*2**(p['offset_semitones']/12))
    alpha = np.exp(-1/(sr*p['glide_ms']/1000)) if p['glide_ms'] else 0
    f = signal.lfilter([1-alpha], [1, -alpha], target, zi=[alpha*target[0]])[0]
    # Offline centered smoothing avoids the pitch lag of a causal glide.
    if alpha:
        f = signal.lfilter([1-alpha], [1, -alpha], f[::-1], zi=[alpha*f[-1]])[0][::-1]
    opening = np.ones(len(x))
    if p['unvoiced'] == 'bypass' and not p['track']:
        a = np.exp(-1/(.01*sr))
        opening = signal.lfilter([1-a], [1, -a], voiced.astype(float), zi=[a*float(voiced[0])])[0]
    return f, opening, curve


def pitch_eq(x, sr, p, *, seed=0):
    from mankomix.dspx.bb.pitch_filter import equalize
    f, opening, curve = centers(x, sr, p)
    if p['shape'] == 'peak' and p['gain_db'] == 0 or not len(x):
        y = x.copy()
    else:
        wet = equalize(x, sr, f, p['shape'], p['gain_db'], p['bw_oct'])
        y = x+opening[:, None]*(wet-x)
    return y, sr, dict(latency_samples=0, track=curve, track_stage='resolved_f0_before_glide',
                       center_min_hz=float(f.min()) if len(f) else None,
                       center_max_hz=float(f.max()) if len(f) else None,
                       pitch_backend='explicit' if p['track'] else 'librosa.pyin 1.0.0')


SPECS = [dict(type='pitch_eq', implemented=True, description='Offline pitch-following TPT equalizer.',
    stages=['track', 'bus', 'master'], master_slot=1, offline_only=True, backends=['reference'],
    realtime=dict(block_ok=False, latency_samples=0, allocates=True),
    params=[_e('shape', ['peak','notch','low_shelf','high_shelf','hpf'], 'peak', 'Filter shape.'),
        _f('harmonic',None,.25,32,1,'F0 multiplier.'), _f('offset_semitones','semitones',-24,24,0,'Pitch offset.'),
        _f('gain_db','dB',-24,24,0,'Peak/shelf gain.'), _f('bw_oct','oct',.02,6,.5,'Bandwidth.'),
        _f('f0_min_hz','Hz',30,1000,60,'Tracking floor.'), _f('f0_max_hz','Hz',60,4000,1000,'Tracking ceiling.'),
        _f('confidence',None,0,1,.5,'Voicing probability.'),
        _e('unvoiced',['hold','fallback','bypass'],'hold','Unvoiced rule.'),
        _f('fallback_hz','Hz',10,24000,200,'Unvoiced frequency.'), _f('glide_ms','ms',0,500,20,'Center smoothing.'),
        dict(id='track',type='curve',unit='Hz',x_min=0,x_max=36000,y_min=20,y_max=8000,
             max_points=65536,default=[],description='Explicit F0 curve; skips detection.')])]
IMPLS = {'pitch_eq': pitch_eq}
CROSS_VALIDATE = {'pitch_eq': validate}
TIME_VARYING = {'pitch_eq'}
