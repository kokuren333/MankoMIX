"""W2d2 acceptance, measurements, and explicit unresolved requirements."""
import importlib
import json
import numpy as np
import pytest
from scipy import signal
from scipy.fft import rfft, rfftfreq

from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb.delayline import fractional_delay
from mankomix.dspx.bb.delayfx import render_with_history
from tests import toolimpl_harness as H

KINDS = ('tape_delay','bbd_delay','mod_delay','freeze_delay','dub_delay','chorus')
SD = dict(duck_db=0, duck_threshold_db=-40, duck_attack_ms=10, duck_release_ms=250)
DL = dict(time_ms=250, note='none', bpm=0, feedback=.3, mix=.2, lowcut_hz=0, highcut_hz=0, seed=0, **SD)
DEFAULTS = {
    'tape_delay': dict(DL, highcut_hz=5000, lowcut_hz=80, wow_depth=.2, wow_rate_hz=.8,
                       flutter_depth=.05, flutter_rate_hz=9, drift=.3, drive_db=6, head_bump_db=2),
    'bbd_delay': dict(DL, time_ms=300, stages=4096, compander=True, tone=.5, noise_db=-120,
                      mod_depth=0, mod_rate_hz=.5),
    'mod_delay': dict(DL, mod_depth_ms=1, mod_rate_hz=.5, mod_note='none', mod_shape='sine',
                      stereo_phase=.25, filter_hz=0, filter_mod_oct=0, filter_res_db=0),
    'freeze_delay': dict(DL, time_ms=500, freeze_start_s=[], freeze_end_s=[], freeze_fade_ms=10,
                         freeze_input='mute', overdub_decay=1, quantize='off', origin_s=0, dry_in_freeze='pass'),
    'dub_delay': dict(DL, feedback=.6, highcut_hz=3500, lowcut_hz=200, send=[], drive_db=6,
                      narrow=.5, diffusion=.2, time_glide_ms=0, time_curve=[], stereo_offset_ms=0),
    'chorus': dict(rate_hz=.6, note='none', bpm=0, depth=.5, lfo_shape='sine', stereo_phase=.25,
                   origin_s=0, phase=0, mix=.5, seed=0, model='clean', delay_ms=12, depth_ms=3,
                   voices=2, feedback=0, highcut_hz=0, lowcut_hz=0, width=1),
}


@pytest.fixture(autouse=True)
def candidate(monkeypatch):
    # Evaluate candidates through the real engine without publishing a failed type.
    for kind in KINDS:
        monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)


def run(kind, x, sr=8000, *, item='echo', seed=71, **p):
    return render_chain(x, sr, [dict(id=item, type=kind, params=p)], stage='track', seed=seed)


def tone(sr=48000, seconds=2, hz=1000, channels=1, level=.1):
    return np.repeat((level*np.sin(2*np.pi*hz*np.arange(round(sr*seconds))/sr))[:,None], channels, axis=1)


def pulse(sr=8000, seconds=1):
    x = np.zeros((round(sr*seconds), 1)); x[0] = 1
    return x


def measure(label, value):
    print(label+': '+json.dumps(value, sort_keys=True))


def clean(kind, **p):
    base = dict(time_ms=40, feedback=.5, mix=1, lowcut_hz=0, highcut_hz=0)
    if kind=='tape_delay':
        base.update(wow_depth=0, flutter_depth=0, drive_db=0, head_bump_db=0)
    elif kind=='mod_delay':
        base.update(mod_depth_ms=0)
    elif kind=='dub_delay':
        base.update(drive_db=0, narrow=0, diffusion=0)
    base.update(p)
    return base


@pytest.mark.parametrize('kind', KINDS)
def test_declarations_defaults_boundaries(kind):
    from mankomix.dspx.registry import time_varying_types
    assert P.validate_params(kind,{}) == DEFAULTS[kind]
    spec = P.describe(kind)
    assert spec['stages']==['track','bus'] and spec['master_slot'] is None
    assert spec['backends']==['reference'] and not spec['channel_ok']
    assert not spec['realtime']['block_ok'] and spec['realtime']['allocates']
    assert kind in time_varying_types()
    x = tone(seconds=.025)
    for entry in spec['params']:
        values = []
        if entry['type'] in ('float','int'): values = [entry['min'],entry['max']]
        if entry['type']=='enum': values = entry['choices']
        if entry['type']=='bool': values = [False,True]
        for value in values:
            p = dict(feedback=0, mix=1)
            if kind=='chorus': p.update(depth=0)
            else: p['time_ms']=10
            if kind=='mod_delay': p.update(mod_depth_ms=0)
            if entry['id'] in ('note','mod_note') and value!='none':
                p['bpm']=400
            if entry['id']=='feedback':
                if kind!='chorus': p['time_ms']=10
                if kind=='tape_delay': p.update(wow_depth=0, flutter_depth=0)
            p[entry['id']] = value
            y = run(kind,x,48000,**p).audio
            assert np.isfinite(y).all() and len(y)==len(x), (kind,entry['id'],value)
    with pytest.raises(ChainError):
        render_chain(x,48000,[dict(type=kind)], stage='master')
    with pytest.raises(ParamError):
        render_chain(np.repeat(x,2,axis=1),48000,[dict(type=kind,channel='left')],stage='track')


@pytest.mark.parametrize('kind', ('tape_delay','mod_delay','freeze_delay','dub_delay'))
def test_integer_echo_timing_decay_and_notes(kind):
    x=pulse()
    y=run(kind,x,**clean(kind)).audio[:,0]
    peaks=signal.find_peaks(np.abs(y),height=.01)[0]
    assert np.array_equal(peaks[:6],320*np.arange(1,7))
    assert np.allclose(y[peaks[:6]], .5**np.arange(6), atol=1e-13)
    q=clean(kind,time_ms=125,feedback=.3)
    assert run(kind,x,**q).audio.tobytes()==run(kind,x,**dict(q,note='1/16',bpm=120)).audio.tobytes()
    measure(kind+'_DT',dict(interval_samples=np.diff(peaks[:6]).tolist(), repeats=y[peaks[:6]].tolist()))


@pytest.mark.parametrize('kind', KINDS)
def test_common(kind,monkeypatch):
    params = dict(mix=.2,feedback=0)
    if kind!='chorus': params['time_ms']=20
    if kind=='bbd_delay': params.update(compander=False)
    if kind=='chorus': params.update(depth=0,voices=1)
    if kind=='chorus':
        original=H.sine
        def stereo_fixture(*args,**kw):
            # This type intentionally converts mono to stereo. Test the
            # harness on stereo; exercise mono separately at all three rates.
            kw['channels']=2
            return original(*args,**kw)
        monkeypatch.setattr(H,'sine',stereo_fixture)
    def probe(x,y,sr,p):
        # Measure intentional delay through phase of a wet-only fixed path.
        f = H.fundamental_frequency(y[len(y)//2:],sr,low_hz=900,high_hz=1100)
        return dict(passed=abs(f-1000)<1, frequency_hz=f)
    report=H.assert_common_tests(kind,params=params,neutral=dict(mix=0),
        latency_params=dict(mix=0),sr_probe=probe,seconds=.025)
    assert all(v['passed'] for v in report.values())


@pytest.mark.parametrize('kind', ('tape_delay','mod_delay','dub_delay','freeze_delay'))
def test_sixty_second_tail_and_relationship_validation(kind):
    sr=2000
    x=np.zeros((60*sr+100,1)); x[:100,0]=np.random.Generator(np.random.PCG64(3)).choice([-1.,1.],100)
    p=clean(kind,time_ms=10,feedback=.95 if kind!='dub_delay' else .98)
    if kind=='dub_delay': p.update(drive_db=24)
    y=run(kind,x,sr,**p).audio
    peak=np.max(np.abs(y[-sr:]))
    assert peak<1e-6 and np.isfinite(y).all()
    with pytest.raises(ParamError): P.validate_params(kind,dict(time_ms=1000,feedback=.95))
    measure(kind+'_CT8',dict(peak=float(np.max(np.abs(y))),tail_peak=float(peak)))


@pytest.mark.parametrize('kind', ('tape_delay','mod_delay','bbd_delay','chorus'))
def test_random_seeds_through_engine(kind):
    x=tone(sr=8000,seconds=.25,hz=440)
    if kind=='tape_delay': p=dict(time_ms=20,feedback=0,drift=1)
    elif kind=='mod_delay': p=dict(time_ms=20,feedback=0,mod_shape='random')
    elif kind=='bbd_delay': p=dict(time_ms=20,feedback=0,noise_db=-60)
    else: p=dict(lfo_shape='random',voices=1)
    a=run(kind,x,**p).audio
    assert a.tobytes()==run(kind,x,**p).audio.tobytes()
    assert a.tobytes()!=run(kind,x,seed=72,**p).audio.tobytes()
    assert a.tobytes()!=run(kind,x,item='other',**p).audio.tobytes()
    other=render_chain(x,8000,[dict(id='echo',type=kind,params=dict(p,seed=1))],stage='track',seed=71).audio
    assert a.tobytes()!=other.tobytes()


@pytest.mark.parametrize('kind', KINDS)
def test_history_replay_excerpt(kind):
    x=tone(sr=8000,seconds=.15,hz=440,channels=2)
    q=dict(mix=.7,feedback=.2)
    if kind!='chorus': q['time_ms']=20
    if kind=='mod_delay': q['mod_shape']='random'
    p=P.validate_params(kind,q)
    module=importlib.import_module('mankomix.dspx.procs.'+kind)
    fn=getattr(module,kind)
    full=fn(x,8000,p,seed=9)[0]
    part=render_with_history(fn,x[517:],8000,p,seed=9,history=x[:517])[0]
    assert part.tobytes()==full[517:].tobytes()


@pytest.mark.parametrize('kind', ('tape_delay','mod_delay','dub_delay','freeze_delay','bbd_delay','pingpong_delay','multitap_delay'))
def test_t04_08_duck_bursts(kind):
    sr=4000
    x=tone(sr,2,500)
    x[2000:4000]=0; x[6000:]=0
    p=dict(mix=1,feedback=0)
    if kind=='multitap_delay': p.update(tap_ms=[20],tap_db=[0])
    else: p['time_ms']=20
    if kind=='tape_delay': p.update(wow_depth=0,flutter_depth=0)
    a=run(kind,x,sr,**p).audio
    b=run(kind,x,sr,**dict(p,duck_db=12,duck_attack_ms=1,duck_release_ms=40)).audio
    ratio=20*np.log10(np.linalg.norm(b[1000:1800])/np.linalg.norm(a[1000:1800]))
    assert abs(ratio+12)<1
    assert run(kind,x,sr,**dict(p,duck_db=0)).audio.tobytes()==a.tobytes()
    measure(kind+'_SD_db',float(ratio))


def frequency_motion(y,sr,hz=1000,start=.3,end=None):
    z=signal.hilbert(y[:,0])
    inst=np.diff(np.unwrap(np.angle(z)))*sr/(2*np.pi)
    return inst[round(start*sr):round(end*sr) if end else -round(.2*sr)]-hz


@pytest.mark.parametrize('kind', ('tape_delay','mod_delay','chorus'))
def test_pitch_motion_depth_and_stereo(kind):
    sr=48000; x=tone(sr,3,channels=2)
    if kind=='tape_delay':
        p=clean(kind,time_ms=100,feedback=0,wow_depth=1,wow_rate_hz=2,drift=0)
        expected=1000*2*np.pi*2*.001
    elif kind=='mod_delay':
        p=clean(kind,time_ms=40,feedback=0,mod_depth_ms=1,mod_rate_hz=2,stereo_phase=.5)
        expected=1000*2*np.pi*2*.001
    else:
        p=dict(mix=1,voices=1,depth=1,depth_ms=1,rate_hz=2,stereo_phase=.5)
        expected=1000*2*np.pi*2*.001
    y=run(kind,x,sr,**p).audio
    deviation=frequency_motion(y,sr)
    peak=float(np.max(np.abs(deviation)))
    assert abs(peak/expected-1)<.1
    if kind!='tape_delay':
        other=frequency_motion(y[:,1:2],sr)
        assert np.corrcoef(deviation,other)[0,1]<-.99
    measure(kind+'_pitch_hz',dict(peak=peak,expected=expected))


def test_tape_harmonics_and_spectral_darkening():
    sr=16000; d=1600; x=np.zeros((8*d,1))
    x[:d]=tone(sr,.1,1000,level=.8)
    thds=[]
    for drive in (0,6,12,24):
        y=run('tape_delay',x,sr,**clean('tape_delay',time_ms=100,drive_db=drive)).audio
        thds.append(H.thd(y[2*d+200:3*d-200],sr,1000)['thd_db'])
    assert np.all(np.diff(thds)>0)
    y=run('tape_delay',pulse(sr,1),sr,**clean('tape_delay',time_ms=100,feedback=.6,highcut_hz=2000)).audio
    freq=rfftfreq(d,1/sr)
    centroids=[]
    for k in range(1,6):
        mag=np.abs(rfft(y[k*d:(k+1)*d,0]))
        centroids.append(float(np.sum(freq*mag)/np.sum(mag)))
    assert np.all(np.diff(centroids)<0)
    measure('tape_THD_db',thds); measure('tape_centroids_hz',centroids)


def test_mod_filter_limit_and_absolute_controls():
    from mankomix.dspx.procs.mod_delay import motion
    p=P.validate_params('mod_delay',dict(time_ms=10,mod_depth_ms=0,feedback=.95,filter_hz=800,filter_res_db=12))
    y=run('mod_delay',tone(8000,.1,440,level=1),**p)
    stats=y.steps[0]['stats']
    assert stats['feedback_effective']*10**(.6)<=.98+1e-14
    assert stats['feedback_reduction_db']<0
    full=motion(4000,8000,p,2,seed=4)
    excerpt=motion(1234,8000,p,2,seed=4,start_sample=2766)
    assert all(a[2766:].tobytes()==b.tobytes() for a,b in zip(full,excerpt))
    measure('mod_feedback',stats)


def test_freeze_empty_matches_legacy_and_sixty_second_repeat():
    x=tone(4000,.5,333)
    p=clean('freeze_delay',time_ms=50,feedback=.3,mix=.4,highcut_hz=1000)
    y=run('freeze_delay',x,4000,**p).audio
    legacy=run('delay',x,4000,**p).audio
    assert y.tobytes()==legacy.tobytes()
    x=np.pad(x,((0,60*4000),(0,0)))
    p=clean('freeze_delay',time_ms=50,feedback=.3,freeze_start_s=[.4],freeze_end_s=[60.4],freeze_fade_ms=5)
    y=run('freeze_delay',x,4000,**p).audio
    assert y[4000:4200].tobytes()==y[60*4000:60*4000+200].tobytes()


def test_freeze_mute_overdub_quantize_validation():
    from mankomix.dspx.procs.freeze_delay import check_runtime
    sr=4000; x=np.zeros((4000,1)); x[2400]=.1
    p=clean('freeze_delay',time_ms=50,freeze_start_s=[.2],freeze_end_s=[.9],freeze_fade_ms=1)
    mute=run('freeze_delay',x,sr,**p).audio
    assert np.max(np.abs(mute))==0
    overdub=run('freeze_delay',x,sr,**dict(p,freeze_input='overdub',overdub_decay=.8)).audio
    assert overdub[2600,0]==.1 and np.isclose(overdub[2800,0],.08)
    q=P.validate_params('freeze_delay',dict(p,quantize='loop',origin_s=.013,freeze_start_s=[.183],freeze_end_s=[.847]))
    windows=check_runtime(q,sr,.1)
    assert all((a-round(.013*sr))%200==0 and (b-round(.013*sr))%200==0 for a,b in windows)
    with pytest.raises(ParamError):
        check_runtime(P.validate_params('freeze_delay',dict(p,freeze_input='overdub')),sr,1)
    for bad in (dict(freeze_end_s=[]),dict(freeze_start_s=[.5],freeze_end_s=[.4]),
                dict(freeze_start_s=[.1,.3],freeze_end_s=[.4,.6])):
        with pytest.raises(ParamError): P.validate_params('freeze_delay',dict(p,**bad))


def test_freeze_seam_and_exit_decay():
    sr=8000; d=400; x=tone(sr,1,333)
    p=clean('freeze_delay',time_ms=50,feedback=.5,freeze_start_s=[.4],freeze_end_s=[.8],freeze_fade_ms=5)
    y=run('freeze_delay',x,sr,**p).audio[:,0]
    lap=y[4800:5200]
    differences=np.diff(np.r_[lap,lap[0]])
    seam=float(differences[-1]**2)
    average=float(np.mean(differences**2))
    assert seam<=average*10**(.6)
    x[6400:]=0
    y=run('freeze_delay',x,sr,**p).audio
    levels=[np.linalg.norm(y[a:a+d]) for a in range(6800,8000,d)]
    assert np.allclose(np.array(levels[1:])/levels[:-1],.5,atol=.02)
    measure('freeze_seam',dict(seam_difference_energy=seam,mean_difference_energy=average))


def test_dub_send_bandwidth_and_glide():
    sr=8000; x=pulse(sr,1)
    p=clean('dub_delay',time_ms=50,send=[[0,-90],[.3,-90]])
    assert np.max(np.abs(run('dub_delay',x,sr,**p).audio))<1e-5
    p['send']=[[0,0],[1,0]]
    assert np.max(np.abs(run('dub_delay',x,sr,**p).audio))>.5
    from mankomix.dspx.procs.dub_delay import delay_samples
    q=P.validate_params('dub_delay',clean('dub_delay',time_ms=100,time_glide_ms=30,time_curve=[[0,1],[.2,1],[.4,.5],[1,.5]]))
    delays=delay_samples(8000,8000,q)
    assert np.mean(np.diff(delays[2000:3000,0]))<0
    # At .875 s the one-pole is >15 time constants past the ramp, so
    # its residual delay slope is bounded by the analytic exponential.
    residual=np.max(np.abs(np.diff(delays[7000:,0])))
    assert residual < (400/1600)*np.exp(-(.875-.4)/.03)
    assert delay_samples(1234,8000,q,start_sample=6766).tobytes()==delays[6766:].tobytes()
    sr=24000; y=run('dub_delay',tone(sr,2,1000),sr,**dict(q,feedback=0)).audio
    inst=frequency_motion(y,sr,start=.23,end=.4)
    final=frequency_motion(y,sr,start=1,end=1.8)
    assert np.median(inst)>10 and abs(np.median(final))<1000*(2**(5/1200)-1)
    measure('dub_glide_hz',dict(during=float(np.median(inst)),after=float(np.median(final))))


def test_chorus_fixed_voice_phases_and_dual():
    from mankomix.dspx.procs.chorus import voice_motion
    sr=48000; x=tone(sr,3,channels=2)
    p=dict(depth=0,voices=3,width=0,mix=1)
    y=run('chorus',x,sr,**p).audio
    expected=fractional_delay(x,576,'lagrange3')*np.sqrt(3)
    assert np.max(np.abs(y-expected))<1e-12
    q=P.validate_params('chorus',dict(model='tri',depth=1,depth_ms=1,rate_hz=2))
    m=voice_motion(sr,sr,q)[:,0]
    phases=np.angle(rfft(m-m.mean(axis=0),axis=0)[2])
    assert np.allclose(np.mod(np.diff(phases),2*np.pi),2*np.pi/3,atol=np.deg2rad(2))
    a=run('chorus',x,sr,mix=1,model='clean',voices=1,depth=1,depth_ms=.1,rate_hz=2).audio
    b=run('chorus',x,sr,mix=1,model='dual',depth=1,depth_ms=.1,rate_hz=2).audio.mean(axis=1,keepdims=True)
    single=np.std(frequency_motion(a,sr)); dual=np.std(frequency_motion(b,sr))
    assert dual/single<.2
    measure('chorus_dual_ratio',float(dual/single))


@pytest.mark.parametrize('feedback', [-.5,.5])
def test_chorus_feedback(feedback):
    sr=2000; x=np.zeros((60*sr+100,2)); x[:100]=1
    y=run('chorus',x,sr,mix=1,delay_ms=10,depth=0,feedback=feedback).audio
    assert np.isfinite(y).all() and np.max(np.abs(y[-sr:]))<1e-6


def test_bbd_bandwidth_compander_noise_alias():
    sr=16000
    from mankomix.dspx.bb.bbd import bbd_audio
    bands=[]
    for ms in (150,300):
        x=pulse(sr,1)
        y=bbd_audio(x,sr,ms*sr/1000,stages=1024,compander=False)
        mag=np.abs(rfft(y[:,0])); f=rfftfreq(len(y),1/sr)
        bands.append(float(f[np.flatnonzero(mag<mag[0]/np.sqrt(2))[0]]))
    assert abs(bands[1]/bands[0]-.5)<.075
    x=tone(sr,1,100,level=.1)
    gains=[]
    for comp in (False,True):
        y=bbd_audio(x,sr,800,stages=4096,compander=comp)
        gains.append(float(20*np.log10(np.linalg.norm(y[8000:])/np.linalg.norm(x[8000:]))))
    assert abs(gains[1])<.5
    z=np.zeros((sr,1)); levels=[]
    for comp in (False,True):
        y=bbd_audio(z,sr,1600,stages=1024,compander=comp,noise_db=-60,seed=8)
        levels.append(H.rms_dbfs(y))
    assert levels[1]<levels[0]-10
    fc=1024/(2*.3)
    y=bbd_audio(tone(sr,1,fc*.7),sr,4800,stages=1024,compander=False)
    attenuation=20*np.log10(np.linalg.norm(y[8000:])/np.linalg.norm(x[8000:]))
    assert attenuation < -40
    measure('bbd',dict(bandwidth_hz=bands,compander_gain_db=gains,noise_dbfs=levels,alias_db=float(attenuation)))


@pytest.mark.xfail(strict=True, reason='BBD analog filter group delay exceeds DT2 one-sample interval tolerance')
def test_pending_bbd_dt2():
    y=run('bbd_delay',pulse(seconds=1),time_ms=100,stages=1024,compander=False,feedback=.5,mix=1).audio[:,0]
    peaks=signal.find_peaks(abs(y),height=.001,distance=600)[0][:5]
    measure('bbd_DT2',dict(peaks=peaks.tolist(),intervals=np.diff(peaks).tolist(),expected_samples=800))
    assert np.max(abs(np.diff(peaks)-800))<=1


@pytest.mark.xfail(strict=True, reason='1/sqrt(N) fixed normalization cannot keep coherent coincident voices within 1 dB')
def test_pending_chorus_coherent_voice_rms():
    x=np.random.Generator(np.random.PCG64(4)).normal(size=(16000,2))*.1
    values=[H.rms_dbfs(run('chorus',x,voices=n,mix=1,depth=0,width=0).audio) for n in range(1,5)]
    measure('chorus_coherent_rms_dbfs',values)
    assert max(values)-min(values)<=1


def test_chorus_bbd_zero_delay():
    # At phase .75 the first BBD voice clips its requested delay to zero.
    y=run('chorus',tone(sr=8000,seconds=.01),model='bbd',delay_ms=2,depth_ms=10,
          depth=1,phase=.75,voices=1).audio
    assert np.isfinite(y).all()


@pytest.mark.parametrize('kind', ('tape_delay','mod_delay','dub_delay','freeze_delay'))
def test_fractional_intervals_and_tempo_rejections(kind):
    p=clean(kind,time_ms=40.0625,feedback=0)
    y=run(kind,pulse(),**p).audio[:,0]
    weight=np.abs(y)
    measured=float(np.sum(np.arange(len(y))*weight)/sum(weight))
    # Freeze is explicitly integer; the other time-varying paths use cubic.
    assert abs(measured-40.0625*8)<=.5
    for invalid in (dict(note='1/4',bpm=0),dict(bpm=1),dict(note='1/1d',bpm=20)):
        if kind=='freeze_delay' and invalid.get('bpm')==20:
            invalid=dict(note='1/1d',bpm=20)
        with pytest.raises(ParamError): P.validate_params(kind,dict(p,**invalid))


@pytest.mark.parametrize('model', ('clean','bbd','dual','tri','ensemble'))
def test_chorus_topologies_and_mono_rates(model):
    for sr in (44100,48000,96000):
        x=tone(sr,.04,1000)
        y=run('chorus',x,sr,model=model,depth=0,mix=1,voices=1).audio
        assert y.shape==(len(x),2) and np.isfinite(y).all()
        f=H.fundamental_frequency(y[len(y)//2:],sr,low_hz=900,high_hz=1100)
        assert abs(f-1000)<1


def test_controls_mt_absolute_period_phase_and_ensemble():
    from mankomix.dspx.procs.chorus import voice_motion
    from mankomix.dspx.procs.mod_delay import motion
    from mankomix.dspx.procs.tape_delay import delay_samples
    sr=8000
    for shape in ('sine','triangle','random'):
        q=P.validate_params('chorus',dict(rate_hz=2,lfo_shape=shape,voices=1))
        full=voice_motion(16000,sr,q,seed=3)
        part=voice_motion(1234,sr,q,seed=3,start_sample=14766)
        assert full[14766:].tobytes()==part.tobytes()
        if shape!='random':
            assert np.max(abs(full[:8000]-full[8000:]))<1e-11
        q['stereo_phase']=0
        same=voice_motion(8000,sr,q,seed=3)
        assert same[:,0].tobytes()==same[:,1].tobytes()
        q['stereo_phase']=.5
        inverse=voice_motion(8000,sr,q,seed=3)
        assert np.max(abs(inverse[:,0]+inverse[:,1]-2*q['delay_ms']*sr/1000))<1e-9
    q=P.validate_params('chorus',dict(model='ensemble',rate_hz=1,depth=1,depth_ms=1))
    d=voice_motion(sr,sr,q)[:,0,0]
    spectral=np.abs(rfft(d-d.mean()))
    assert set(np.argsort(spectral)[-2:])=={1,10}
    q=P.validate_params('mod_delay',dict(mod_note='1/4',bpm=120))
    a=motion(1000,sr,q)[0]
    q.update(mod_note='none',mod_rate_hz=2)
    assert np.max(abs(a-motion(1000,sr,q)[0]))<1e-11
    p=P.validate_params('tape_delay',{})
    full=delay_samples(2000,sr,p,seed=4)
    assert full[500:].tobytes()==delay_samples(1500,sr,p,seed=4,start_sample=500).tobytes()


def test_dub_repeated_bandwidth():
    sr=16000; d=1600
    x=pulse(sr,1)
    y=run('dub_delay',x,sr,**clean('dub_delay',time_ms=100,feedback=.6,narrow=1,highcut_hz=2500)).audio[:,0]
    widths=[]
    f=rfftfreq(d,1/sr)
    for k in range(1,6):
        h=np.abs(rfft(y[k*d:(k+1)*d]))
        below=np.flatnonzero(h<h[0]/np.sqrt(2))
        widths.append(float(f[below[0]]) if len(below) else sr/2)
    assert np.all(np.diff(widths)<0)
    measure('dub_bandwidth_hz',widths)


def test_bbd_tail_and_clock_modulation():
    sr=1000; x=np.zeros((61*sr,1)); x[:100,0]=np.random.Generator(np.random.PCG64(8)).choice([-1,1],100)
    y=run('bbd_delay',x,sr,time_ms=1000,stages=1024,feedback=.01,mix=1,compander=False).audio
    peak=float(np.max(abs(y[-sr:])))
    assert np.isfinite(y).all() and peak<1e-6
    a=run('bbd_delay',tone(8000,.3,440),time_ms=40,mod_depth=2,feedback=0).audio
    b=run('bbd_delay',tone(8000,.3,440),time_ms=40,mod_depth=0,feedback=0).audio
    assert a.tobytes()!=b.tobytes()
    measure('bbd_CT8_tail_peak',peak)


@pytest.mark.parametrize('kind', ('tape_delay','mod_delay','freeze_delay','dub_delay'))
def test_delay_time_measurement_at_all_rates(kind):
    values=[]
    for sr in (44100,48000,96000):
        y=run(kind,pulse(sr,.08),sr,**clean(kind,time_ms=12.5,feedback=0)).audio
        location=int(np.argmax(abs(y[:,0])))
        assert abs(location-.0125*sr)<=.5
        values.append(dict(sr=sr,peak_sample=location,expected_sample=.0125*sr))
    measure(kind+'_CT7_delay',values)


@pytest.mark.parametrize('kind', ('tape_delay','mod_delay','dub_delay'))
def test_maximum_loop_processing_fullscale_tail(kind):
    sr=2000; x=np.zeros((60*sr+100,1))
    x[:100,0]=np.random.Generator(np.random.PCG64(3)).choice([-1,1],100)
    p=dict(time_ms=10,mix=1,feedback=.95)
    if kind=='tape_delay': p.update(drive_db=24,head_bump_db=6,wow_depth=2,flutter_depth=.5)
    elif kind=='mod_delay': p.update(mod_depth_ms=0,filter_res_db=12,filter_hz=500)
    else: p.update(feedback=.98,drive_db=24,narrow=1,diffusion=1)
    y=run(kind,x,sr,**p).audio
    assert np.isfinite(y).all() and np.max(abs(y[-sr:]))<1e-6
    measure(kind+'_max_CT8',dict(peak=float(np.max(abs(y))),tail_peak=float(np.max(abs(y[-sr:])))))


def test_new_delay_maximum_durations_and_curve_validation():
    for kind,ms in (('tape_delay',4000),('mod_delay',4000),('freeze_delay',8000),('dub_delay',4000)):
        q=clean(kind,time_ms=ms,feedback=0)
        y=run(kind,pulse(1000,ms/1000+.1),1000,**q).audio
        assert int(np.argmax(abs(y[:,0])))==int(ms)
    for invalid in (dict(send=[[0,-91]]),dict(send=[[0,0],[0,-3]]),dict(time_curve=[[0,0]]),
                    dict(time_curve=[[0,1],[1,5]]),dict(send=[[i/100,0] for i in range(4097)])):
        with pytest.raises(ParamError): P.validate_params('dub_delay',invalid)


def test_sd_release_and_unmodified_dry_path():
    sr=4000; x=tone(sr,2,500); x[2000:]=0
    q=clean('mod_delay',time_ms=600,feedback=0,mix=1)
    a=run('mod_delay',x,sr,**q).audio
    b=run('mod_delay',x,sr,**dict(q,duck_db=12,duck_release_ms=40)).audio
    assert np.linalg.norm(b[3000:4000])/np.linalg.norm(a[3000:4000])>.99
    q.update(time_ms=20,mix=.5)
    wet=run('mod_delay',x,sr,**dict(q,mix=1,duck_db=12)).audio
    y=run('mod_delay',x,sr,**dict(q,duck_db=12)).audio
    assert np.max(abs(y-(x+wet)/2))<1e-14


def test_published_flags_and_no_extra_duck_type(monkeypatch):
    from mankomix.dspx.registry import specs
    declared={s['type']:s for s in specs()}
    for kind in KINDS:
        expected=kind not in ('bbd_delay','chorus')
        assert declared[kind]['implemented']==expected
        monkeypatch.setitem(P.PROCESSORS[kind],'implemented',expected)
        if not expected:
            with pytest.raises(ChainError): run(kind,pulse(seconds=.01))
    assert 'ducking_delay' not in declared and 'duck_delay' not in declared


def test_freeze_array_limit_and_sd_endpoints():
    starts=[i*2 for i in range(32)]; ends=[i*2+1 for i in range(32)]
    y=run('freeze_delay',tone(sr=8000,seconds=.03),freeze_start_s=starts,freeze_end_s=ends).audio
    assert np.isfinite(y).all()
    with pytest.raises(ParamError):
        P.validate_params('freeze_delay',dict(freeze_start_s=starts+[64],freeze_end_s=ends+[65]))
    from mankomix.dspx.bb.selfduck import duck_wet
    dry=np.ones((400,2)); wet=dry.copy()
    for depth in (0,24):
        for attack in (.1,200):
            for release in (5,3000):
                p=dict(duck_db=depth,duck_threshold_db=-80,duck_attack_ms=attack,duck_release_ms=release)
                assert np.isfinite(duck_wet(dry,wet,8000,p)).all()


def test_lfo_thousand_cycle_clock():
    from mankomix.dspx.procs.chorus import voice_motion
    sr=8000
    for model in ('clean','dual','tri','ensemble'):
        p=P.validate_params('chorus',dict(model=model,rate_hz=2))
        a=voice_motion(1000,sr,p)
        b=voice_motion(1000,sr,p,start_sample=1000*4000)
        assert np.max(abs(a-b))<1e-10
