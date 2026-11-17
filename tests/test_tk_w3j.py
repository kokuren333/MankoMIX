"""W3j measured acceptance, including the D-23(a) hum-domain closure."""
import importlib
import json
import numpy as np
import pytest
from scipy import fft, signal
from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError
from tests import toolimpl_harness as H

TYPES = ['pitch_eq','hf_restore','spectral_repair','dewind','guitar_denoise','interpolate']


@pytest.fixture(autouse=True)
def diagnostic(monkeypatch):
    for kind in TYPES:
        monkeypatch.setitem(P.PROCESSORS[kind],'implemented',True)


def render(kind,x,sr=16000,p=None,seed=0,item='probe'):
    return E.render_chain(x,sr,[dict(type=kind,id=item,params=p or {})],stage='track',seed=seed)


def direct(kind,x,sr=16000,p=None):
    mod = importlib.import_module('mankomix.dspx.procs.'+kind)
    return mod.IMPLS[kind](x,sr,P.validate_params(kind,p or {}),seed=0)


def tones(sr=16000,seconds=1):
    t = np.arange(round(sr*seconds))/sr
    return (.15*np.sin(2*np.pi*223*t)+.08*np.sin(2*np.pi*503*t)+.04*np.sin(2*np.pi*997*t))[:,None]


def sdr(x,y):
    return 10*np.log10(np.sum(x*x)/max(np.sum((x-y)**2),1e-30))


def level(x,sr,lo,hi):
    return H.band_level(x,sr,lo,hi)['dbfs']


def emit(name,value):
    print(name,json.dumps(value,sort_keys=True))


@pytest.mark.parametrize('material',['tones','vowel','noise'])
@pytest.mark.parametrize('ms,limit',[(5,20),(20,12),(100,6)])
def test_spectral_gap_quality(material,ms,limit):
    sr = 16000
    x = tones(sr) if material == 'tones' else H.vowel(sr=sr,seconds=1) if material == 'vowel' else H.white_noise(sr=sr,seconds=1,seed=32)
    a,b = 6400,6400+round(ms*sr/1000)
    z = x.copy()
    z[a:b] = 0
    p = dict(method='spectral',t0_s=[a/sr],t1_s=[b/sr])
    y = render('interpolate',z,sr,p).audio
    assert y[:a].tobytes() == z[:a].tobytes() and y[b:].tobytes() == z[b:].tobytes()
    d = render('interpolate',z,sr,{**p,'delta':True}).audio
    assert H.null(y+d,z)['rms_dbfs'] <= -120
    if material == 'noise':
        value = H.rms_dbfs(y[a:b])-H.rms_dbfs(np.r_[x[a-3200:a],x[b:b+3200]])
        emit('SPECTRAL_NOISE_'+str(ms),value)
        assert abs(value) <= 3
    else:
        value = sdr(x[a:b],y[a:b])
        emit('SPECTRAL_SDR_'+material+'_'+str(ms),value)
        assert value >= limit
        for edge in (a,b):
            sl = slice(edge-16,edge+16)
            assert H.rms_dbfs(np.diff(y[sl],axis=0))-H.rms_dbfs(np.diff(x[sl],axis=0)) <= 3
    assert y.tobytes() == render('interpolate',z,sr,p).audio.tobytes()


def test_auto_uses_ar_or_spectral_and_boundaries():
    x = tones()
    for ms,method in [(20,'ar'),(100,'spectral')]:
        p = dict(t0_s=[.3],t1_s=[.3+ms/1000])
        y = render('interpolate',x,p=p).audio
        assert y.tobytes() == render('interpolate',x,p={**p,'method':method}).audio.tobytes()
    for a,b in [(0,.05),(.95,1),(0,.5)]:
        y = render('interpolate',x,p=dict(method='spectral',t0_s=[a],t1_s=[b])).audio
        assert np.isfinite(y).all()


def test_pitch_explicit_centers_static_and_neutral():
    from mankomix.dspx.procs.pitch_eq import centers
    from mankomix.dspx.bb.pitch_filter import equalize
    sr=16000
    x=tones(sr,.3)
    p=P.validate_params('pitch_eq',dict(track=[[0,100],[.3,400]],harmonic=2,offset_semitones=12,glide_ms=0))
    f,opening,curve=centers(x,sr,p)
    expected = np.interp(np.arange(len(x)),[0,len(x)],[400,1600])
    assert np.max(abs(f/expected-1)) < .01
    assert render('pitch_eq',x,sr,dict(track=[[0,200]])).audio.tobytes() == x.tobytes()
    for shape in ('peak','notch','low_shelf','high_shelf','hpf'):
        params=dict(track=[[0,223]],shape=shape,gain_db=6)
        y=render('pitch_eq',x,sr,params).audio
        static=equalize(x,sr,223,shape,6,.5)
        assert H.null(y,static)['rms_dbfs'] <= -80
        if shape in ('peak','low_shelf','high_shelf'):
            assert np.any(y != x)


def test_pitch_automatic_chirp_and_unvoiced():
    from mankomix.dspx.procs.pitch_eq import centers
    sr=8000
    t=np.arange(2*sr)/sr
    chirp=.2*np.sin(2*np.pi*(100*t+75*t*t))
    fixed=.05*np.sin(2*np.pi*3000*t)
    x=(chirp+fixed)[:,None]
    y=render('pitch_eq',x,sr,dict(shape='notch')).audio
    # Demodulation removes the unrelated 3 kHz tone before RMS measurement.
    low=signal.sosfiltfilt(signal.butter(6,800,fs=sr,output='sos'),y[:,0])
    residual=H.rms_dbfs(low[800:])-H.rms_dbfs(chirp[800:])
    high_change=level(y[800:],sr,2900,3100)-level(x[800:],sr,2900,3100)
    emit('PITCH_CHIRP',dict(residual_db=residual,high_change_db=high_change))
    assert residual <= -20 and abs(high_change) <= .2
    # The three policies share the detector and differ only after voicing decisions.
    x=np.r_[.2*np.sin(2*np.pi*220*np.arange(sr//2)/sr),np.zeros(sr//2)][:,None]
    for rule in ('hold','fallback','bypass'):
        p=P.validate_params('pitch_eq',dict(unvoiced=rule,glide_ms=0,fallback_hz=330))
        f,opening,curve=centers(x,sr,p)
        if rule == 'hold':
            assert abs(f[-1]-220) < 3
        else:
            assert f[-1] == 330
        if rule == 'bypass':
            assert opening[-1] < 1e-10
    stats=render('pitch_eq',x,sr).steps[0]['stats']
    assert stats['track'] and stats['pitch_backend'] == 'librosa.pyin 1.0.0'


def test_pitch_tail_has_no_unstable_growth():
    # A resonator rings in the waveform; the envelope, rather than individual
    # oscillating samples, must decay after switching input to zero.
    sr=16000
    x=H.sine(sr=sr,seconds=.4,freq=250)
    x[len(x)//2:]=0
    y=render('pitch_eq',x,sr,dict(track=[[0,250]],gain_db=12)).audio
    blocks=np.array([np.max(abs(v)) for v in np.array_split(y[len(x)//2:],20)])
    assert np.all(np.diff(blocks) <= 1e-12)


@pytest.mark.parametrize('mode',['attenuate','replace_time','replace_freq','pattern'])
def test_repair_bin_preservation_modes_and_delta(mode):
    from mankomix.dspx.bb.stft import analyze
    from mankomix.dspx.bb.spectral_repair import repair_spectra
    x=tones()
    a=analyze(x,16000,window=684)
    regions=[(.3,.5,800,1400)]
    z=repair_spectra(a,regions,mode=mode,feather_oct=0)
    outside=(a.frequencies_hz < 800) | (a.frequencies_hz > 1400)
    assert z[:,outside].tobytes() == a.spectra[:,outside].tobytes()
    p=dict(mode=mode,t0_s=[.3],t1_s=[.5],lo_hz=[800],hi_hz=[1400])
    y=render('spectral_repair',x,p=p).audio
    d=render('spectral_repair',x,p={**p,'delta':True}).audio
    assert H.null(y+d,x)['rms_dbfs'] <= -120
    assert y[:4640].tobytes()==x[:4640].tobytes()
    assert np.isfinite(y).all()
    assert y.tobytes()==render('spectral_repair',x,p=p).audio.tobytes()
    outside_tone=H.sine(sr=16000,seconds=1,freq=3000)
    out=render('spectral_repair',outside_tone,p=p).audio
    assert abs(H.rms_dbfs(out)-H.rms_dbfs(outside_tone)) <= .05


def test_repair_attenuation_and_time_spectrum():
    sr=16000
    x=tones(sr)
    t=np.arange(len(x))/sr
    disturbance=(.4*np.sin(2*np.pi*1000*t))[:,None]
    z=x.copy()
    z[4800:8000]+=disturbance[4800:8000]
    p=dict(mode='attenuate',t0_s=[.3],t1_s=[.5],lo_hz=[900],hi_hz=[1100],attenuate_db=40)
    y=render('spectral_repair',z,sr,p).audio
    reduction=level(y[5200:7600],sr,980,1020)-level(z[5200:7600],sr,980,1020)
    preserved=level(y[5200:7600],sr,210,240)-level(x[5200:7600],sr,210,240)
    emit('REPAIR_ATTENUATE',dict(reduction_db=reduction,harmonic_change_db=preserved))
    assert reduction <= -20 and abs(preserved)<=2
    # A single missing harmonic band, with no spectral information in the hole.
    clean=H.sine(sr=sr,seconds=1,freq=1000,dbfs=-12)
    broken=clean.copy()
    broken[6400:8000]=0
    out=render('spectral_repair',broken,sr,dict(t0_s=[.4],t1_s=[.5],lo_hz=[700],hi_hz=[1300])).audio
    change=level(out[6600:7800],sr,900,1100)-level(clean[6600:7800],sr,900,1100)
    emit('REPAIR_REPLACE_TIME',change)
    assert abs(change)<=3
    for edge in (6400,8000):
        sl=slice(edge-16,edge+16)
        assert H.rms_dbfs(np.diff(out[sl],axis=0))-H.rms_dbfs(np.diff(clean[sl],axis=0))<=3


def lowpass_exact(x,sr,cutoff=8000):
    z=fft.rfft(x,axis=0,workers=1)
    z[fft.rfftfreq(len(x),1/sr)>=cutoff]=0
    return fft.irfft(z,n=len(x),axis=0,workers=1)


@pytest.mark.parametrize('material',['pink','mix'])
def test_hf_cliff_levels_lowband_and_random_seed(material):
    sr=48000
    x=H.pink_noise(sr=sr,seconds=2,seed=17)
    if material=='mix':
        x+=tones(sr,2)*.2
    broken=lowpass_exact(x,sr)
    result=render('hf_restore',broken,sr)
    y=result.audio
    stats=result.steps[0]['stats']
    emit('HF_CLIFF_'+material,stats['cutoff_hz'])
    assert abs(stats['cutoff_hz']/8000-1)<=.05
    changes=[]
    for center in (9000,11339,14287):
        lo,hi=center/2**(1/6),min(16000,center*2**(1/6))
        changes.append(level(y,sr,lo,hi)-level(x,sr,lo,hi))
    emit('HF_BANDS_'+material,changes)
    assert max(abs(np.array(changes)))<=4
    assert level(y-broken,sr,0,8000/2**(1/3)) <= -100
    assert y.tobytes()==render('hf_restore',broken,sr).audio.tobytes()
    for seed,item,pseed in [(1,'probe',0),(0,'other',0),(0,'probe',1)]:
        assert y.tobytes()!=render('hf_restore',broken,sr,dict(seed=pseed),seed,item).audio.tobytes()
    assert 'estimate' in stats['caveat']


def test_hf_bursts_and_harmonic_source():
    sr=48000
    x=H.white_noise(sr=sr,seconds=1,seed=31)
    t=np.arange(len(x))/sr
    env=sum(np.exp(-.5*((t-center)/.01)**2) for center in (.2,.5,.8))
    x*=env[:,None]
    broken=lowpass_exact(x,sr)
    p=dict(cutoff_hz=8000,amount=1,transient_follow=1)
    y=render('hf_restore',broken,sr,p).audio
    from mankomix.dspx.bb.stft import analyze
    a=analyze(y-broken,sr,window=1024)
    b=analyze(broken,sr,window=1024)
    high=np.sum(abs(a.spectra)**2,axis=(1,2))
    low=np.sum(abs(b.spectra[:,(b.frequencies_hz>4000)&(b.frequencies_hz<8000)])**2,axis=(1,2))
    for center in (.2,.5,.8):
        k=(a.samples/sr>center-.04)&(a.samples/sr<center+.04)
        delay=abs(a.samples[k][np.argmax(high[k])]-a.samples[k][np.argmax(low[k])])/sr
        emit('HF_BURST_DELAY',delay)
        assert delay <= .003
    assert np.isfinite(render('hf_restore',broken,sr,{**p,'source':'harmonic'}).audio).all()


def wind_fixture(sr=16000):
    t=np.arange(3*sr)/sr
    rng=np.random.Generator(np.random.PCG64(18))
    z=rng.standard_normal((len(t),2))
    z=signal.sosfiltfilt(signal.butter(4,80,fs=sr,output='sos'),z,axis=0)
    z/=np.sqrt(np.mean(z*z,axis=0))
    env=(.5+.5*np.sin(2*np.pi*2.3*t))*(t>.5)*(t<2.5)
    wind=z*env[:,None]
    voice=np.repeat(H.vowel(sr=sr,seconds=3),2,axis=1)*.1
    return wind+voice


def test_dewind_wind_reduction_and_coherent_bass():
    sr=16000
    x=wind_fixture(sr)
    r=render('dewind',x,sr)
    sl=slice(sr,2*sr)
    low=level(r.audio[sl],sr,0,300)-level(x[sl],sr,0,300)
    # Isolate the full-length band before selecting the wind interval, so
    # low-frequency window leakage cannot masquerade as a high-band change.
    def high_band(v):
        spec=fft.rfft(v,axis=0,workers=1)
        spec[fft.rfftfreq(len(v),1/sr)<=300]=0
        return fft.irfft(spec,n=len(v),axis=0,workers=1)
    high=H.rms_dbfs(high_band(r.audio)[sl])-H.rms_dbfs(high_band(x)[sl])
    emit('DEWIND',dict(low_db=low,high_db=high,frames=r.steps[0]['stats']['wind_frame_count']))
    assert low<=-12 and abs(high)<=1
    bass=np.repeat(H.sine(sr=sr,seconds=1,freq=80),2,axis=1)
    r=render('dewind',bass,sr)
    assert r.audio.tobytes()==bass.tobytes() and r.steps[0]['stats']['wind_frame_count']==0
    assert render('dewind',x[:,:1],sr).steps[0]['stats']['confidence']=='low'


@pytest.mark.parametrize('kind',['hf_restore','dewind'])
@pytest.mark.parametrize('material',['tones','pink','vowel','bursts'])
def test_rp4(kind,material):
    sr=16000
    if material=='tones':x=tones(sr)
    elif material=='pink':x=H.pink_noise(sr=sr,seconds=1)
    elif material=='vowel':x=H.vowel(sr=sr,seconds=1)
    else:
        x=H.tone_burst(sr=sr,seconds=1,freq=500)
    r=render(kind,x,sr)
    rel=r.steps[0]['stats']['removed_energy_rel_db']
    emit('RP4_'+kind+'_'+material,rel)
    assert rel is None or rel<=-60


@pytest.mark.parametrize('kind',['hf_restore','dewind'])
def test_rp_active_bypass_region_and_records(kind):
    sr=48000 if kind=='hf_restore' else 16000
    x=lowpass_exact(H.pink_noise(sr=sr,seconds=1),sr) if kind=='hf_restore' else wind_fixture(sr)
    p=dict(start_s=.2,end_s=.8)
    if kind=='hf_restore':p['cutoff_hz']=8000
    y=render(kind,x,sr,p)
    assert y.audio[:round(.2*sr)].tobytes()==x[:round(.2*sr)].tobytes()
    assert y.audio[round(.8*sr):].tobytes()==x[round(.8*sr):].tobytes()
    delta=render(kind,x,sr,{**p,'delta':True}).audio
    assert H.null(delta+y.audio,x)['rms_dbfs']<=-120
    assert render(kind,x,sr,{**p,'amount':0,'delta':True}).audio.tobytes()==x.tobytes()
    stats=y.steps[0]['stats']
    from mankomix.dspx.bb.restoration import runs
    assert stats['event_count']==len(runs(np.any(y.audio!=x,axis=1)))
    assert 'before' in stats and 'after' in stats and 'removed_energy_bands' in stats


def test_guitar_exact_mapping_records_and_manual_chain():
    from mankomix.dspx.procs.guitar_denoise import expand
    p=P.validate_params('guitar_denoise',{})
    assert expand(p)==[dict(type='dehum',params=dict(depth_db=30.,harmonics=16,base_hz=0.)),
        dict(type='denoise',params=dict(profile='auto',reduction_db=9.)),
        dict(type='gate',params=dict(range_db=-9.,threshold_db=-55.))]
    x=tones(seconds=.1)
    y=render('guitar_denoise',x,p=p)
    children=[dict(c,id='probe.'+str(i)) for i,c in enumerate(expand(p),1)]
    manual=E.render_chain(x,16000,children,stage='track',seed=0)
    assert y.audio.tobytes()==manual.audio.tobytes()
    assert all(s['composite_of']['type']=='guitar_denoise' for s in y.steps)
    assert expand({**p,'pick':1})[-1]==dict(type='transient_shaper',params=dict(attack_db=-9))
    assert expand({**p,'squeak':1})[-1]==dict(type='resonance_suppressor',params=dict(depth_db=24,lo_hz=2000,hi_hz=8000))


def test_guitar_all_zero():
    from mankomix.dspx.procs.guitar_denoise import expand
    p=dict(hum=0,amp_noise=0,squeak=0,pick=0)
    assert expand(P.validate_params('guitar_denoise',p))==[]
    x=tones()
    assert render('guitar_denoise',x,p=p).audio.tobytes()==x.tobytes()


@pytest.mark.parametrize('bad',[dict(hum=.001), dict(hum=np.nextafter(.05, 0))])
def test_guitar_all_positive_domain(bad):
    with pytest.raises(ParamError, match='hum must be zero or 0.05'):
        render('guitar_denoise',tones(seconds=.1),p=bad)


def test_guitar_squeak_dependency():
    from mankomix.dsp.errors import ChainError
    if P.PROCESSORS['resonance_suppressor']['implemented']:
        assert np.isfinite(render('guitar_denoise',tones(seconds=.1),p=dict(squeak=1)).audio).all()
    else:
        with pytest.raises(ChainError,match='not implemented'):
            render('guitar_denoise',tones(seconds=.1),p=dict(squeak=1))


@pytest.mark.parametrize('kind',['pitch_eq','hf_restore','spectral_repair','dewind','interpolate'])
def test_common(kind):
    params=dict(track=[[0,200]]) if kind=='pitch_eq' else {}
    neutral=dict(amount=0) if kind in ('hf_restore','dewind') else params
    def probe(x,y,sr,p):
        hz=H.fundamental_frequency(y,sr,low_hz=900,high_hz=1100)
        return dict(passed=abs(hz-1000)<=1 and H.null(x,y)['rms_dbfs']<=-120,frequency_hz=hz)
    r=H.assert_common_tests(kind,params=params,neutral=neutral,latency_params=neutral,
        sr_probe=probe,seconds=.05)
    assert r['CT-2']['mode']=='full_repeat_and_context_replay_excerpt'


@pytest.mark.parametrize('kind',TYPES)
def test_bounds_and_defaults(kind):
    defaults={s['id']:s['default'] for s in P.describe(kind)['params']}
    assert P.validate_params(kind,{})==defaults
    x=tones(48000,.03)
    base=dict(track=[[0,200]]) if kind=='pitch_eq' else {}
    for s in P.describe(kind)['params']:
        if s['type'] not in ('int','float','enum','bool'):continue
        values=[s['min'],s['max']] if s['type'] in ('int','float') else s['choices'] if s['type']=='enum' else [False,True]
        for value in values:
            p={**base,s['id']:value}
            if s['id']=='start_s' and value:
                with pytest.raises(ParamError):P.validate_params(kind,p)
                continue
            if kind=='pitch_eq' and s['id']=='f0_min_hz':p['f0_max_hz']=4000
            if kind=='pitch_eq' and s['id']=='f0_max_hz':p['f0_min_hz']=30
            if kind=='hf_restore' and s['id']=='cutoff_hz' and value:p['top_hz']=22000
            if kind=='guitar_denoise':
                P.validate_params(kind,p)
                continue
            assert np.isfinite(render(kind,x,48000,p).audio).all()
    with pytest.raises(ParamError):P.validate_params(kind,{'unknown_w3j':0})


@pytest.mark.parametrize('kind,bad',[
    ('spectral_repair',dict(t0_s=[0],t1_s=[])),
    ('spectral_repair',dict(t0_s=[0],t1_s=[2.1],lo_hz=[0],hi_hz=[1000])),
    ('spectral_repair',dict(t0_s=[0],t1_s=[1],lo_hz=[1000],hi_hz=[1000])),
    ('interpolate',dict(t0_s=[0],t1_s=[.501])),
    ('hf_restore',dict(cutoff_hz=1000)),('hf_restore',dict(cutoff_hz=8000,top_hz=4000)),
    ('pitch_eq',dict(f0_min_hz=1000,f0_max_hz=1000)),('guitar_denoise',dict(hum_hz=20))])
def test_relationships(kind,bad):
    with pytest.raises(ParamError):P.validate_params(kind,bad)


@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.parametrize('channels',[1,2])
def test_active_rates_centers_and_gap_samples(sr,channels):
    # Independent frequency-response minimum, rather than comparing two
    # calls of the same filter function. The impulse tail is fully captured.
    x=np.zeros((round(sr*.12),channels))
    x[0]=.5
    y=render('pitch_eq',x,sr,dict(shape='notch',track=[[0,1000]])).audio
    nfft=2**18
    spectrum=abs(fft.rfft(y[:,0],n=nfft,workers=1))
    f=fft.rfftfreq(nfft,1/sr)
    k=np.flatnonzero((f>900)&(f<1100))
    center=f[k[np.argmin(spectrum[k])]]
    assert abs(center/1000-1)<.01
    clean=np.repeat(tones(sr,.5),channels,axis=1)
    a,b=round(sr*.2),round(sr*.25)
    broken=clean.copy()
    broken[a:b]=0
    y=render('interpolate',broken,sr,dict(method='spectral',t0_s=[.2],t1_s=[.25])).audio
    assert y[:a].tobytes()==broken[:a].tobytes() and y[b:].tobytes()==broken[b:].tobytes()
    value=sdr(clean[a:b],y[a:b])
    emit('SR_GAP_'+str(sr)+'_'+str(channels),value)
    assert value>=6


def test_independent_spec_ranges_defaults_and_registration():
    expected={
        'pitch_eq':dict(harmonic=(.25,32,1),offset_semitones=(-24,24,0),gain_db=(-24,24,0),bw_oct=(.02,6,.5),
            f0_min_hz=(30,1000,60),f0_max_hz=(60,4000,1000),confidence=(0,1,.5),fallback_hz=(10,24000,200),glide_ms=(0,500,20)),
        'hf_restore':dict(amount=(0,1,.7),start_s=(0,36000,0),end_s=(0,36000,0),cutoff_hz=(0,20000,0),top_hz=(4000,22000,16000),
            slope_db_oct=(-24,0,0),level_db=(-12,6,0),noise_mix=(0,1,.3),transient_follow=(0,1,.7),seed=(0,65535,0)),
        'dewind':dict(amount=(0,1,1),start_s=(0,36000,0),end_s=(0,36000,0),max_hz=(80,1000,300),threshold_db=(0,24,6),
            max_reduce_db=(3,40,24),release_ms=(20,1000,150)),
        'spectral_repair':dict(attenuate_db=(0,60,12),context_ms=(20,2000,200),feather_ms=(0,100,10),feather_oct=(0,.5,.05)),
        'guitar_denoise':dict(hum=(0,1,.5),hum_hz=(0,70,0),amp_noise=(0,1,.3),gate_threshold_db=(-80,0,-55),squeak=(0,1,0),pick=(0,1,0))}
    for kind,wanted in expected.items():
        specs={s['id']:s for s in P.describe(kind)['params']}
        assert {k:(specs[k]['min'],specs[k]['max'],specs[k]['default']) for k in wanted}==wanted
    for kind in ('hf_restore','dewind','spectral_repair','interpolate','guitar_denoise'):
        d=P.describe(kind)
        assert d['stages']==['track','bus'] and d['master_slot'] is None and d['offline_only']
    d=P.describe('pitch_eq')
    assert d['master_slot']==1 and d['stages']==['track','bus','master'] and d['offline_only']
    from mankomix.dspx.registry import time_varying_types
    assert 'pitch_eq' in time_varying_types()
    assert not (set(TYPES)-{'pitch_eq'}) & time_varying_types()
    for kind in ('spectral_repair','interpolate'):
        x=tones()
        assert render(kind,x).audio.tobytes()==x.tobytes()
    for kind in TYPES:
        for s in P.describe(kind)['params']:
            if s['type'] in ('float','int'):
                for invalid in (s['min']-1,s['max']+1):
                    with pytest.raises(ParamError):P.validate_params(kind,{s['id']:invalid})


def test_rectangle_limit_arrays_and_untouched_time_bins():
    from mankomix.dspx.bb.spectral_repair import repair_spectra
    from mankomix.dspx.bb.stft import analyze
    a=analyze(tones(),16000,window=684)
    z=repair_spectra(a,[(.3,.5,500,1500)],mode='replace_time',feather_ms=10)
    outside=(a.samples/16000<.29)|(a.samples/16000>.51)
    assert z[outside].tobytes()==a.spectra[outside].tobytes()
    for kind,keys in [('spectral_repair',('t0_s','t1_s','lo_hz','hi_hz')),('interpolate',('t0_s','t1_s'))]:
        for key in keys:
            with pytest.raises(ParamError):P.validate_params(kind,{key:[0]*65})


@pytest.mark.parametrize('lo,hi',[(30,60),(30,4000),(1000,4000)])
def test_automatic_pitch_range_endpoints(lo,hi):
    x=tones(16000,.08)
    assert np.isfinite(render('pitch_eq',x,16000,dict(shape='notch',f0_min_hz=lo,f0_max_hz=hi)).audio).all()


def test_pitch_record_replays_and_explicit_skips_backend(monkeypatch):
    from mankomix.dspx.procs.pitch_eq import centers
    import importlib.metadata
    import mankomix.dspx.bb.pitch as pitch
    # A resolved held F0 line can be reused without a pitch dependency.
    x=tones(8000,.3)
    p=P.validate_params('pitch_eq',dict(shape='notch'))
    f,_,curve=centers(x,8000,p)
    def forbidden(*args,**kw):raise AssertionError('explicit curve called pitch backend')
    monkeypatch.setattr(pitch,'detect_pitch',forbidden)
    monkeypatch.setattr(importlib.metadata,'version',forbidden)
    replay,_,_=centers(x,8000,{**p,'track':curve})
    np.testing.assert_array_equal(f,replay)


def test_final_publication_flags(monkeypatch):
    from mankomix.dsp.errors import ChainError
    for kind in set(TYPES)-{'guitar_denoise'}:
        assert importlib.import_module('mankomix.dspx.procs.'+kind).SPECS[0]['implemented']
    from mankomix.dspx.procs.guitar_denoise import SPECS
    assert SPECS[0]['implemented']
    monkeypatch.setitem(P.PROCESSORS['guitar_denoise'],'implemented',False)
    with pytest.raises(ChainError,match='not implemented'):
        render('guitar_denoise',tones(seconds=.01))
