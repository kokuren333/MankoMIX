"""W2a3 spectral, temporal, declaration and whole-context acceptance tests."""
import importlib
import json
import numpy as np
import pytest
from scipy import signal
from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from tests import toolimpl_harness as H

TYPES = ('phase_enhancer', 'console_bus', 'bass_enhancer', 'sub_synth')
ACTIVE = dict(phase_enhancer=dict(amount=1), console_bus=dict(drive_db=12),
              bass_enhancer=dict(amount_db=-6), sub_synth=dict(amount_db=-6))
NEUTRAL = dict(phase_enhancer=dict(amount=0), console_bus=dict(drive_db=0),
               bass_enhancer=dict(amount_db=-60, original_db=0), sub_synth=dict(amount_db=-60))
DEFAULTS = dict(
    phase_enhancer=dict(amount=0, lo_xover_hz=150, hi_xover_hz=2400, lo_delay_ms=2.5,
        mid_delay_ms=.5, lo_contour_db=0, hi_process_db=4, hi_dynamic=.5, mid_invert=True),
    console_bus=dict(crosstalk_db=-120, crosstalk_slope=6, drive_db=0, character=.5,
        tolerance=0, lf_corner_hz=0, hf_corner_hz=0, noise_db=-120, oversample=4, output_db=0, seed=0),
    bass_enhancer=dict(freq_hz=90, amount_db=-60, original_db=0, harmonics='integrator',
        hi_limit_hz=400, decay=.5, attack_ms=10, release_ms=120, oversample=4),
    sub_synth=dict(mode='divider', lo_hz=50, hi_hz=110, amount_db=-60,
        sub_highcut_hz=60, attack_ms=10, release_ms=150, threshold_db=-45, mono=True))
RANGES = dict(
    phase_enhancer=dict(amount=(0,1), lo_xover_hz=(80,400), hi_xover_hz=(1200,5000),
        lo_delay_ms=(0,5), mid_delay_ms=(0,2), lo_contour_db=(0,12), hi_process_db=(0,12), hi_dynamic=(0,1)),
    console_bus=dict(crosstalk_db=(-120,-40), crosstalk_slope=(0,6), drive_db=(0,18),
        character=(0,1), tolerance=(0,1), lf_corner_hz=(0,30), hf_corner_hz=(0,80000),
        noise_db=(-120,-70), output_db=(-36,12), seed=(0,65535)),
    bass_enhancer=dict(freq_hz=(40,250), amount_db=(-60,12), original_db=(-60,0),
        hi_limit_hz=(150,1000), decay=(0,1), attack_ms=(1,100), release_ms=(20,500)),
    sub_synth=dict(lo_hz=(30,120), hi_hz=(60,250), amount_db=(-60,6),
        sub_highcut_hz=(30,120), attack_ms=(1,100), release_ms=(20,1000), threshold_db=(-80,0)))


@pytest.fixture(autouse=True)
def candidate_registration(monkeypatch):
    for name in TYPES:
        monkeypatch.setitem(P.PROCESSORS[name], 'implemented', True)


def render(name, x, p=None, sr=48000, seed=0, item_id='probe'):
    stage = 'bus' if name == 'console_bus' else 'track'
    return E.render_chain(x, sr, [dict(id=item_id, type=name, params=p or {})], stage=stage, seed=seed).audio


def tone(f=60, db=-6, sr=48000, seconds=1.5):
    return (10**(db/20)*np.sin(2*np.pi*f*np.arange(round(sr*seconds))/sr))[:, None]


def db(v):
    return float(20*np.log10(max(float(v), 1e-300)))


def amp(x, f, sr=48000):
    a = x[len(x)//3:2*len(x)//3, 0]
    return float(2*abs(np.dot(a, np.exp(-2j*np.pi*f*np.arange(len(a))/sr)))/len(a))


def aliases(x, f, sr=48000):
    a = x[len(x)//3:2*len(x)//3, 0]
    spectrum = abs(np.fft.rfft(a))/len(a)
    reference = spectrum[round(f*len(a)/sr)]
    for k in range(1, int(sr/2/f)+1):
        i = round(k*f*len(a)/sr)
        spectrum[max(0,i-1):i+2] = 0
    spectrum[:2] = 0
    return db(np.linalg.norm(spectrum)/max(reference, 1e-300))


@pytest.mark.parametrize('name', TYPES)
def test_declarations_defaults_boundaries_neutral(name):
    spec = P.describe(name)
    assert P.validate_params(name, {}) == DEFAULTS[name]
    assert spec['master_slot'] == P.describe('saturator')['master_slot'] == 3
    assert spec['stages'] == (['bus', 'master'] if name == 'console_bus' else ['track','bus','master'])
    assert spec['offline_only'] == (name == 'sub_synth')
    assert spec['backends'] == ['reference'] and spec['channel_ok']
    assert spec['realtime']['block_ok'] is False
    x = np.random.Generator(np.random.PCG64(3)).normal(0,.05,(1536,2))
    assert render(name, x, NEUTRAL[name]).tobytes() == x.tobytes()
    for definition in spec['params']:
        pid = definition['id']
        if definition['type'] in ('float','int'):
            assert (definition['min'],definition['max']) == RANGES[name][pid]
            values = RANGES[name][pid]
        elif definition['type'] == 'enum':
            values = definition['choices']
        else:
            values = (False,True)
        for value in values:
            p = dict(ACTIVE[name], **{pid:value})
            if name == 'bass_enhancer' and pid == 'freq_hz': p['hi_limit_hz'] = 1000
            if name == 'sub_synth' and pid == 'lo_hz': p['hi_hz'] = 250
            if name == 'sub_synth' and pid == 'hi_hz': p['lo_hz'] = 30
            y = render(name, x, p, sr=96000)
            assert y.shape == x.shape and np.isfinite(y).all(), (name,pid,value)


@pytest.mark.parametrize('name', TYPES)
def test_common_ct(name):
    def probe(x,y,sr,p):
        f = H.fundamental_frequency(y, sr)
        return dict(passed=abs(f-1000)<1, frequency_hz=f)
    result = H.assert_common_tests(name, params=ACTIVE[name], neutral=NEUTRAL[name],
        stages=P.describe(name)['stages'], sr_probe=probe, seconds=.12,
        latency_params=NEUTRAL[name])
    print('CT', name, json.dumps({key:row['passed'] for key,row in result.items()}))


def test_cross_validation_tv_and_master():
    from mankomix.dspx.registry import time_varying_types
    assert 'phase_enhancer' in time_varying_types()
    for name,p in [('bass_enhancer',dict(freq_hz=250,hi_limit_hz=150)),
                   ('sub_synth',dict(lo_hz=120,hi_hz=60))]:
        with pytest.raises(ParamError): P.validate_params(name,p)
    for name in TYPES:
        E.validate_chain([dict(type=name),dict(type='limiter')],stage='master')
        with pytest.raises(ChainError):
            E.validate_chain([dict(type='limiter'),dict(type=name)],stage='master')
    with pytest.raises(ChainError): E.validate_chain([dict(type='console_bus')],stage='track')


def phase_response(p, sr=48000):
    pulse = np.zeros((sr,1)); pulse[0] = 1
    y = render('phase_enhancer',pulse,p,sr)
    response = np.fft.rfft(y[:,0])
    f = np.fft.rfftfreq(len(y),1/sr)
    gd = -np.gradient(np.unwrap(np.angle(response)),2*np.pi*f)*1000
    return f, response, gd


def test_phase_no_delay_allpass_and_lti():
    p = dict(amount=1,hi_process_db=0,lo_contour_db=0,lo_delay_ms=0,mid_delay_ms=0,hi_dynamic=0)
    f,h,_ = phase_response(p)
    assert np.max(abs(20*np.log10(abs(h)))) < .001
    x = tone(1000,seconds=.3)
    z = np.zeros_like(x)
    a = render('phase_enhancer',np.r_[x,z],p)
    b = render('phase_enhancer',np.r_[z,x],p)
    assert np.max(abs(a[:len(x)]-b[len(x):])) < 1e-12


@pytest.mark.xfail(strict=True, reason='Independent SVF band delays cause 13 dB combing, exceeding the 0.3 dB specification.')
def test_phase_equalization_zero_flatness():
    f,h,gd = phase_response(dict(amount=1,hi_process_db=0,hi_dynamic=0))
    selected = (f>=20)&(f<=20000)
    ripple = float(np.max(abs(20*np.log10(abs(h[selected])))))
    delays = [float(gd[np.argmin(abs(f-v))]) for v in (40,600,10000)]
    print('PHASE_RESPONSE',json.dumps(dict(max_abs_db=ripple,centers_hz=[40,600,10000],group_delay_ms=delays)))
    assert ripple <= .3


@pytest.mark.xfail(strict=True, reason='SVF group delay adds to the musical delays; the requested absolute delay limits are unmet.')
def test_phase_group_delay():
    f,h,gd = phase_response(dict(amount=1,hi_process_db=0,hi_dynamic=0))
    delays = [float(gd[np.argmin(abs(f-v))]) for v in (40,600,10000)]
    print('PHASE_GROUP_DELAY_MS',delays)
    assert abs(delays[0]/2.5-1)<.15 and abs(delays[1]/.5-1)<.15
    assert abs(delays[2]) < 1/48000*1000


def test_phase_dynamic_high_gain_and_arrival():
    changes=[]
    for level in (-40,-10):
        x = tone(10000,level)+tone(600,level)
        y = render('phase_enhancer',x,dict(amount=1,hi_dynamic=1,hi_process_db=12,lo_delay_ms=0,mid_delay_ms=0))
        changes.append(db(amp(y,10000)/amp(x,10000)))
    print('PHASE_DYNAMIC_DB',changes)
    assert changes[0]-changes[1] >= 6
    from mankomix.dspx.procs.phase_enhancer import svf_bands
    from mankomix.dspx.bb.delayline import fractional_delay
    pulse = np.zeros((8192,1)); pulse[1024]=1
    low,mid,high = svf_bands(pulse,48000,150,2400)
    low = fractional_delay(low,120,'sinc256')
    assert np.argmax(abs(high)) < np.argmax(abs(low))


@pytest.mark.parametrize('slope',[0,3,6])
@pytest.mark.parametrize('f',[1000,10000])
def test_console_crosstalk(slope,f):
    left=tone(f); x=np.c_[left[:,0],np.zeros(len(left))]
    y=render('console_bus',x,dict(crosstalk_db=-40,crosstalk_slope=slope))
    measured=db(amp(y[:,1:],f)/amp(left,f))
    expected=-40-slope*np.log2(20000/f)
    print('CROSSTALK',f,slope,measured,expected)
    assert abs(measured-expected)<.5
    assert y[:,0].tobytes()==x[:,0].tobytes()


def test_console_tolerance_noise_seeds_mono():
    left=tone(1000,seconds=.3); x=np.repeat(left,2,axis=1)
    p=dict(tolerance=1)
    y=render('console_bus',x,p,seed=14)
    difference=db(amp(y,1000)/amp(y[:,1:],1000))
    assert abs(difference)<=.1
    assert y.tobytes()==render('console_bus',x,p,seed=14).tobytes()
    for override in (dict(seed=15),dict(item_id='other')):
        assert y.tobytes()!=render('console_bus',x,p,**override).tobytes()
    assert y.tobytes()!=render('console_bus',x,dict(p,seed=7),seed=14).tobytes()
    noisy=dict(noise_db=-70)
    for seed in (14,15):
        a=render('console_bus',x,noisy,seed=seed)
        assert a.tobytes()==render('console_bus',x,noisy,seed=seed).tobytes()
    assert render('console_bus',x,noisy,seed=14).tobytes()!=render('console_bus',x,noisy,seed=15).tobytes()
    a=render('console_bus',left,dict(crosstalk_db=-40,tolerance=1))
    assert a.tobytes()==left.tobytes()
    from mankomix.dspx.procs.console_bus import console_bus
    _,_,stats=console_bus(left,48000,P.validate_params('console_bus',dict(tolerance=1)))
    assert stats['crosstalk_disabled_mono'] and stats['tolerance_disabled_mono']


def test_console_harmonic_ratio_small_signal_dc_alignment():
    ratios=[]
    for character in (0,.25,.5,.75,1):
        y=render('console_bus',tone(1000),dict(drive_db=12,character=character))
        ratios.append(db(amp(y,2000)/max(amp(y,3000),1e-300)))
        assert db(abs(np.mean(y))) <= -80
    assert np.all(np.diff(ratios)>0)
    y=render('console_bus',tone(1000,-60),dict(drive_db=18))
    small_gain=db(amp(y,1000)/.001)
    assert abs(small_gain)<.05
    filtered=render('console_bus',tone(1000),dict(drive_db=18,lf_corner_hz=30,hf_corner_hz=3000))
    assert db(abs(np.mean(filtered)))<=-80
    gained=render('console_bus',tone(1000,-60),dict(drive_db=18,output_db=6))
    assert abs(db(amp(gained,1000)/.001)-6)<.05
    print('CONSOLE_SMALL_SIGNAL_DB',small_gain)
    x=tone(1000)
    wet=render('console_bus',x,dict(drive_db=12))
    assert H.latency((x+wet)*.5,x,method='correlation',max_lag=24)==0
    print('CONSOLE_CHARACTER_RATIO_DB',ratios)


@pytest.mark.parametrize('drive',[0,4.5,9,13.5,18])
def test_console_nt_vector(drive):
    y=render('console_bus',tone(1000),dict(drive_db=drive))
    amps=[amp(y,1000*k) for k in range(1,8)]
    row=dict(drive_db=drive,thd_db=db(np.linalg.norm(amps[1:])/amps[0]),
        harmonic_db=[db(a/amps[0]) for a in amps[1:]])
    print('NT_VECTOR',json.dumps(row))


@pytest.mark.parametrize('f',[5000,10000,15000])
def test_console_alias(f):
    value=aliases(render('console_bus',tone(f),dict(drive_db=18)),f)
    print('CONSOLE_ALIAS_DBC',f,value)
    assert value<=-80


def test_bass_harmonics_limit_decay_level_replacement():
    x=tone()
    vectors=[]
    for decay in (0,.25,.5,.75,1):
        d=render('bass_enhancer',x,dict(amount_db=0,decay=decay))-x
        values=[amp(d,k*60) for k in range(2,13)]
        vectors.append([db(v/max(values[0],1e-300)) for v in values])
        assert min(values[:3])>1e-5
        assert max(vectors[-1][5:])<=-60
        assert db(abs(np.mean(d)))<=-80
    print('BASS_VECTORS_DB',json.dumps(vectors))
    assert np.all(np.diff(np.array(vectors)[:,:3],axis=0)[:,1:]<0)
    base=render('bass_enhancer',x,dict(amount_db=0))-x
    gains=[]
    for level in (-30,-18,-6):
        quiet=tone(db=level)
        d=render('bass_enhancer',quiet,dict(amount_db=0))-quiet
        gains.append(db(amp(d,120)/amp(quiet,60)))
    assert max(gains)-min(gains)<=2
    replaced=render('bass_enhancer',x,dict(amount_db=0,original_db=-60))
    rejection=db(amp(replaced,60)/amp(x,60))
    print('BASS_LEVEL_GAINS_DB',gains,'REPLACEMENT_DB',rejection)
    assert rejection<=-50 and amp(replaced,120)>1e-5


@pytest.mark.parametrize('generator',['integrator','rectifier','clipper'])
def test_bass_modes_high_input_alias_dc(generator):
    d=render('bass_enhancer',tone(1000),dict(amount_db=0,harmonics=generator))-tone(1000)
    assert H.rms_dbfs(d[len(d)//3:2*len(d)//3])<=-90
    for f in (5000,10000,15000):
        x=tone(f)
        y=render('bass_enhancer',x,dict(amount_db=0,harmonics=generator))
        assert aliases(y,f)<=-80
    assert not np.any(render('bass_enhancer',np.zeros((8000,1)),dict(amount_db=0,harmonics=generator)))


def test_bass_burst_attack():
    sr=48000
    x=tone(60,seconds=1.5); x[:sr//2]=0
    d=render('bass_enhancer',x,dict(amount_db=0))-x
    env=H.rms_envelope(d,sr,window_ms=10)[:,0]
    target=np.median(env[sr:5*sr//4])*(1-np.exp(-1))
    crossing=np.flatnonzero(env[sr//2:]>=target)[0]/sr*1000
    print('BASS_ATTACK_MS',crossing)
    assert crossing<=15


@pytest.mark.parametrize('mode',['divider','tracked'])
def test_sub_frequency_harmonics_threshold_outside_mono_dc(mode):
    x=tone(80)
    d=render('sub_synth',x,dict(amount_db=0,mode=mode))-x
    measured=H.fundamental_frequency(d[len(d)//3:2*len(d)//3],48000,low_hz=20,high_hz=200)
    ratio=db(np.linalg.norm([amp(d,f) for f in (80,120,160,200,240,280)])/amp(d,40))
    print('SUB_SPECTRUM',mode,measured,ratio)
    assert abs(measured-40)<=.5
    if mode == 'tracked':
        assert ratio<=-40
    assert db(abs(np.mean(d)))<=-80
    quiet=tone(80,-60)
    assert render('sub_synth',quiet,dict(amount_db=0,mode=mode)).tobytes()==quiet.tobytes()
    stereo=np.c_[x[:,0],x[:,0]*.5]
    delta=render('sub_synth',stereo,dict(amount_db=0,mode=mode,mono=True))-stereo
    assert np.max(abs(delta[:,0]-delta[:,1]))<2e-16


@pytest.mark.parametrize('mode',[
    pytest.param('divider',marks=pytest.mark.xfail(strict=True,
        reason='Boundary-excited divider release and finite-record DC correction leak into steady out-of-band input.')),
    'tracked'])
def test_sub_outside_band(mode):
    values=[]
    for f in (30,200):
        a=tone(f); delta=render('sub_synth',a,dict(amount_db=0,mode=mode))-a
        values.append(H.rms_dbfs(delta[len(delta)//3:2*len(delta)//3]))
    print('SUB_OUTSIDE_DBFS',mode,values)
    assert max(values)<=-80


@pytest.mark.xfail(strict=True, reason='Default four-pole divider output does not suppress its 120 Hz third harmonic by 40 dB.')
def test_sub_divider_harmonic_rejection():
    x=tone(80)
    d=render('sub_synth',x,dict(amount_db=0))-x
    ratio=db(np.linalg.norm([amp(d,f) for f in (80,120,160,200,240,280)])/amp(d,40))
    print('SUB_DIVIDER_HARMONICS_DBC',ratio)
    assert ratio<=-40


@pytest.mark.parametrize('mode',['divider','tracked'])
@pytest.mark.xfail(strict=True, reason='Band selection, held divider polarity or unvoiced tracking and output LPF alter the end-to-end envelope times.')
def test_sub_burst_times(mode):
    sr=48000
    x=tone(80,seconds=3); x[:sr//2]=0; x[2*sr:]=0
    from mankomix.dspx.bb.lowend import amplitude_envelope
    d=render('sub_synth',x,dict(amount_db=0,mode=mode))-x
    env=amplitude_envelope(d,sr,.1,.1)[:,0]
    steady=float(np.median(env[sr:3*sr//2]))
    attack=np.flatnonzero(env[sr//2:]>=steady*(1-np.exp(-1)))[0]/sr*1000
    release=np.flatnonzero(env[2*sr:]<=steady/np.e)[0]/sr*1000
    print('SUB_TIMES_MS',mode,attack,release)
    assert abs(attack/10-1)<=.2 and abs(release/150-1)<=.2


def test_public_flags_match_acceptance(monkeypatch):
    for name in TYPES:
        module=importlib.import_module('mankomix.dspx.procs.'+name)
        expected = name in ('console_bus','bass_enhancer')
        assert module.SPECS[0]['implemented'] == expected
        monkeypatch.setitem(P.PROCESSORS[name],'implemented',expected)
        if not expected:
            with pytest.raises(Exception,match='not implemented|not_implemented'):
                render(name,tone(seconds=.1))


@pytest.mark.parametrize('sr',[44100,48000,96000])
def test_active_bass_and_sub_sample_rates(sr):
    for name,f,target in [('bass_enhancer',60,120),('sub_synth',80,40)]:
        x=tone(f,sr=sr,seconds=.6)
        d=render(name,x,dict(amount_db=0),sr)-x
        if name=='bass_enhancer':
            measured=H.fundamental_frequency(d[len(d)//3:2*len(d)//3],sr,low_hz=100,high_hz=250)
        else:
            measured=H.fundamental_frequency(d[len(d)//3:2*len(d)//3],sr,low_hz=20,high_hz=100)
        print('ACTIVE_SR_HZ',name,sr,measured)
        assert abs(measured-target)<.5


def test_fir_and_oversampling_uncompensated_latency():
    from mankomix.dspx.bb.lowend import band_fir, _kernel
    from mankomix.dspx.bb.fir import fft_convolve
    from mankomix.dspx.bb import nonlinear as N
    x=np.zeros((24000,1));x[12000]=1
    y,meta=band_fir(x,48000,hi=90)
    assert np.argmax(abs(y[:,0]))==12000
    h=_kernel(48000,0.,90.,0.)
    raw=fft_convolve(x,h)
    assert np.argmax(abs(raw[:,0]))-12000==meta['uncompensated_latency_samples']
    for factor in (1,2,4,8,16,32):
        z=N.precision_oversampled(x,factor,lambda v:v)
        assert np.argmax(abs(z[:,0]))==12000
    print('FIR_LATENCY',json.dumps(meta))


def test_tracked_replay_and_independent_sub_channels():
    from mankomix.dspx.procs.sub_synth import sub_synth
    from tests.toolimpl_harness import render_excerpt
    x=tone(80,seconds=.6)
    p=dict(amount_db=0,mode='tracked')
    a=render('sub_synth',x,p)
    assert a.tobytes()==render('sub_synth',x,p).tobytes()
    b=render_excerpt('sub_synth',x,48000,1001,len(x),p,stage='track',seed=0)
    assert a[1001:].tobytes()==b.tobytes()
    stereo=np.c_[x[:,0],tone(100,seconds=.6)[:,0]]
    q=P.validate_params('sub_synth',dict(amount_db=0,mono=False))
    y,_,_=sub_synth(stereo,48000,q)
    d=y-stereo
    assert amp(d,40)>amp(d,50)
    assert amp(d[:,1:],50)>amp(d[:,1:],40)
