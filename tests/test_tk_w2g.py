"""W2g acceptance: length-preserving time/creative effects and shared APIs."""
import json
import importlib
import numpy as np
import pytest
from scipy import signal
from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.errors import ParamError
from tests import toolimpl_harness as H

TYPES = ('halftime', 'tape_stop', 'vocoder', 'band_envelope', 'filter_seq',
         'env_filter', 'reverse_chunks', 'noise_bed')


def params(name, **kw):
    return P.validate_params(name, kw)


def render(name, x, sr, p=None, seed=12, item='w2g'):
    return render_chain(x, sr, [{'id': item, 'type': name, 'params': p or {}}],
                        stage='bus', seed=seed)


def metric(name, **values):
    print('MEASURE '+name+' '+json.dumps(values, sort_keys=True))


def test_metadata_and_note_vocabulary():
    from mankomix.dspx.registry import time_varying_types
    from mankomix.dspx.bb.time_creative import note_choices
    assert note_choices() == P.NOTE_VALUES
    assert set(TYPES) <= time_varying_types()
    for name in TYPES:
        d = P.describe(name)
        assert d['implemented'] is True
        assert d['stages'] == ['track', 'bus'] and d['master_slot'] is None
        assert d['backends'] == ['reference'] and not d['offline_only']
        assert d['realtime'] == dict(block_ok=False, latency_samples=0, allocates=True)


DEFAULTS = {
    'halftime': dict(loop_note='1/1', bpm=0, loop_ms=2000, origin_s=0, speed='1/2', fade_ms=5,
                     band_lo_hz=0, band_hi_hz=0, active=[], mix=1),
    'tape_stop': dict(stop_s=[], start_s=[], stop_ms=400, start_ms=0, curve=1, resume='live', fade_ms=5),
    'filter_seq': dict(step_note='1/16', bpm=0, step_ms=125, steps=16, origin_s=0, swing=0, active=[],
                       cutoff_oct=[], base_hz=800, resonance_db=[], level_db=[], filter='lowpass',
                       slope_db_oct=12, glide_ms=10, env_decay_ms=0, env_oct=0, drive_db=0, mix=1),
    'env_filter': dict(base_hz=300, range_oct=3, sensitivity_db=0, threshold_db=-40, ceiling_db=-6,
                       attack_ms=10, release_ms=150, filter='bandpass', resonance_db=12,
                       slope_db_oct=12, key_lo_hz=0, key_hi_hz=0, stereo_link=True, mix=1),
    'reverse_chunks': dict(step_note='1/16', bpm=0, step_ms=125, origin_s=0, active=[], fade_ms=5, mix=1, every=1),
    'vocoder': dict(bands=16, lo_hz=100, hi_hz=8000, carrier='saw_noise', notes=[48,55,60,64],
                    notes_curve=[], a4_hz=440, attack_ms=5, release_ms=40, formant_shift=0,
                    unvoiced=.5, band_q=8, envelopes='', mix=1, output_db=0, seed=0),
    'band_envelope': dict(envelopes='', bands=16, lo_hz=100, hi_hz=8000, band_q=8,
                          formant_shift=0, depth=1, mix=1),
    'noise_bed': dict(hiss_db=-120, hiss_color='tape', crackle_db=-120, crackle_rate_hz=8,
                      hum_db=-120, hum_hz=50, rumble_db=-120, spectrum=[], follow=0,
                      follow_release_ms=300, dropout=0, width=1, seed=0),
}


def valid(name):
    if name == 'halftime':
        return dict(loop_note='none')
    if name in ('filter_seq', 'reverse_chunks'):
        return dict(step_note='none')
    if name == 'band_envelope':
        return dict(mix=0)
    return {}


@pytest.mark.parametrize('name', TYPES)
def test_defaults_bounds_enums_and_rejections(name, monkeypatch):
    specs = P.describe(name)['params']
    assert {s['id']: s['default'] for s in specs} == DEFAULTS[name]
    sr, x = 48000, H.sine(sr=48000, seconds=.006)
    base = valid(name)
    if name == 'band_envelope':
        from mankomix.dspx import assets
        monkeypatch.setitem(assets.RESOLVERS, 'derived', lambda key: dict(kind='control', values=[[1]*16]))
        base['envelopes'] = 'unit-control'
    # All legal scalar endpoints and enum/bool values are actually rendered.
    for s in specs:
        if s['type'] in ('float', 'int'):
            values = [s['min'], s['max']]
        elif s['type'] == 'enum':
            values = s['choices']
        elif s['type'] == 'bool':
            values = [False, True]
        else:
            continue
        for value in values:
            p = {**base, s['id']: value}
            if s['id'] in ('step_note', 'loop_note') and value != 'none':
                p['bpm'] = 120
            if name == 'env_filter':
                if s['id'] == 'threshold_db' and value == 0:
                    with pytest.raises(ParamError):
                        render(name, x, sr, p)
                    continue
                if s['id'] == 'ceiling_db' and value == -40:
                    p['threshold_db'] = -80
                if s['id'] == 'key_lo_hz':
                    p['key_hi_hz'] = 0
            y = render(name, x, sr, p).audio
            assert y.shape == x.shape and np.isfinite(y).all(), (name, s['id'], value)
    with pytest.raises(ParamError):
        render(name, x, sr, {**base, 'unknown': 1})


@pytest.mark.parametrize('name', TYPES)
def test_common_contract(name):
    p = valid(name)
    neutral = {'mix': 0} if name not in ('noise_bed', 'tape_stop') else {}
    # CT-5 isolates algorithmic latency from intentional chunk/filter phase.
    latency_params = {**p, **neutral}
    probe_params = {**p, **neutral}
    def sr_probe(x, y, sr, vp):
        # Additional active processing probes at every required sr are below.
        tone = H.sine(sr=sr, seconds=.1, channels=x.shape[1])
        out = render(name, tone, sr, probe_params).audio
        freq = H.fundamental_frequency(out, sr, low_hz=900, high_hz=1100)
        gain = H.rms_dbfs(out)-H.rms_dbfs(tone)
        return dict(passed=abs(freq-1000) < 1 and abs(gain) < .01,
                    frequency_hz=freq, gain_db=gain)
    # Vocoder/noise active behaviour is separately measured; neutral is still CT tested.
    if name == 'band_envelope':
        p['mix'] = 0
    H.assert_common_tests(name, params=p, neutral=neutral, seconds=.025,
                          latency_params=latency_params, sr_probe=sr_probe)


@pytest.mark.parametrize('name', ['halftime', 'filter_seq', 'reverse_chunks'])
def test_tempo_active_and_array_validation(name):
    x = H.white_noise(sr=8000, seconds=.1)
    with pytest.raises(ParamError):
        render(name, x, 8000)
    base = valid(name)
    assert np.array_equal(render(name, x, 8000, {**base, 'active': [[0, 0]]}).audio, x)
    with pytest.raises(ParamError):
        render(name, x, 8000, {**base, 'active': [[0, .5]]})
    if name == 'filter_seq':
        for key in ('cutoff_oct', 'resonance_db', 'level_db'):
            with pytest.raises(ParamError):
                render(name, x, 8000, {**base, key: [0, 0]})


def test_absolute_grid_and_swing_no_drift():
    from mankomix.dspx.bb.time_creative import grid
    # 10,000 steps, deliberately noninteger sample duration and origin.
    sr = 1000
    p = dict(step_note='none', step_ms=5.1234, bpm=0, origin_s=.0004, swing=.3)
    k, start, end = grid(51240, sr, p)
    for index in (0, 1, 2, 99, 1000, 9999):
        expected = round(p['origin_s']*sr+(index+(index % 2)*.3)*5.1234)
        assert start[expected] == expected and k[expected] == index
    metric('grid', last_boundary=int(start[-1]), step_index=int(k[-1]))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('speed,ratio', [('1/2', .5), ('1/4', .25), ('2/3', 2/3), ('3/4', .75)])
def test_halftime_frequency_interpolation_fades(sr, speed, ratio):
    x = H.sine(1000, sr=sr, seconds=.3)
    p = dict(loop_note='none', loop_ms=150, speed=speed, fade_ms=5)
    y = render('halftime', x, sr, p).audio
    a, b = round(.02*sr), round(.13*sr)
    f = H.fundamental_frequency(y[a:b], sr, low_hz=200, high_hz=900)
    cents = 1200*np.log2(f/(1000*ratio))
    assert abs(cents) < 1
    reference = .1*np.sin(2*np.pi*1000*np.arange(a,b)*ratio/sr)
    err = H.rms_dbfs(y[a:b,0]-reference)
    assert err < -80
    # A DC plateau isolates seam rise time from finite causal interpolation.
    plateau = np.ones((round(.3*sr),1))
    envelope = render('halftime',plateau,sr,p).audio[:,0]
    start = round(.15*sr)
    a,b=start+128,start+round(.005*sr)
    assert np.max(abs(envelope[a:b]-np.arange(128,b-start)/(.005*sr)))<1e-12
    metric('halftime', sr=sr, speed=speed, cents=float(cents), error_dbfs=err)


def test_halftime_band_protection_and_origin():
    sr = 16000
    x = H.sine(100, sr=sr, seconds=.6)+H.sine(3000, sr=sr, seconds=.6)
    y = render('halftime', x, sr, dict(loop_note='none', loop_ms=300,
                                     band_lo_hz=1000, band_hi_hz=6000, origin_s=.1)).audio
    assert np.array_equal(y[:1600], x[:1600])
    before = H.band_level(x[3200:7200],sr,95,105)
    after = H.band_level(y[3200:7200],sr,95,105)
    assert abs(after['dbfs']-before['dbfs']) < .2


@pytest.mark.parametrize('power', [.25, 1, 4])
def test_tape_stop_instantaneous_frequency_and_silence(power):
    sr = 16000
    x = H.sine(1000, sr=sr, seconds=.9)
    p = dict(stop_s=[.1], stop_ms=500, curve=power, fade_ms=2)
    y = render('tape_stop', x, sr, p).audio[:,0]
    # Subsample upward zero crossings measure each local cycle independently;
    # a global Hilbert transform rings around the intentional stop discontinuity.
    crossings=np.flatnonzero((y[:-1]<0)&(y[1:]>=0))
    crossings=crossings-y[crossings]/(y[crossings+1]-y[crossings])
    f=sr/np.diff(crossings)
    time=(crossings[:-1]+crossings[1:])/(2*sr)
    expected = 1000*(1-np.clip((time-.1)/.5,0,1)**power)
    use = (time > .15) & (time < .45)
    error = np.quantile(np.abs(f[use]/expected[use]-1), .99)
    assert error < .01
    assert not np.any(y[round(.6*sr):])
    metric('tape_stop', power=power, frequency_relative_error_99=float(error))


@pytest.mark.parametrize('resume', ['live', 'catchup'])
@pytest.mark.parametrize('start_ms', [0, 100])
def test_tape_restart_and_bad_intervals(resume, start_ms):
    sr = 8000
    x = H.white_noise(sr=sr, seconds=1)
    p = dict(stop_s=[.05], start_s=[.4], stop_ms=200, start_ms=start_ms, resume=resume)
    y = render('tape_stop',x,sr,p).audio
    if resume == 'live':
        at = round((.4+start_ms/1000+.005)*sr)
        assert np.array_equal(y[at:], x[at:])
    else:
        assert np.array_equal(y[round(.9*sr):], x[round(.9*sr):])
    assert not np.any(y[round(.25*sr):round(.4*sr)])
    for bad in [dict(stop_s=[.2,.1]), dict(stop_s=[.1],start_s=[.2]),
                dict(stop_s=[.1,.5],start_s=[]), dict(stop_s=[.1,.5],start_s=[.6,.8])]:
        with pytest.raises(ParamError):
            render('tape_stop',x,sr,bad)


def test_reverse_exact_every_and_fades():
    sr = 8000
    x = H.white_noise(sr=sr, seconds=.4)
    p = dict(step_note='none',step_ms=100,fade_ms=5)
    y = render('reverse_chunks',x,sr,p).audio
    assert not np.any(y[:800])
    for k in range(1,4):
        assert np.array_equal(y[k*800+40:(k+1)*800-40], x[(k-1)*800:k*800][::-1][40:-40])
    y = render('reverse_chunks',x,sr,{**p,'every':2}).audio
    assert np.array_equal(y[800:1600],x[800:1600])
    assert np.array_equal(y[2400:3200],x[2400:3200])


@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.parametrize('slope',[12,24])
def test_svf_measured_cutoff_resonance_and_state(sr,slope):
    from mankomix.dspx.bb.svf import svf, SVF
    x = H.impulse(sr=sr,seconds=.15)
    for resonance in (0,6,24):
        y = svf(x,sr,1200,resonance,slope=slope)
        f = np.fft.rfftfreq(len(y),1/sr)
        db = 20*np.log10(np.maximum(abs(np.fft.rfft(y[:,0])),1e-15))
        crossing = np.flatnonzero((f>1000)&(db<=-3.01029995664))[0]
        cutoff = np.interp(-3.01029995664, db[crossing-1:crossing+1][::-1], f[crossing-1:crossing+1][::-1])
        peak = db.max()
        assert abs(cutoff/1200-1)<.03
        assert abs(peak-resonance)<1
        metric('svf',sr=sr,slope=slope,resonance=resonance,cutoff_hz=float(cutoff),peak_db=float(peak))
    rng=np.random.default_rng(9)
    noise=rng.uniform(-1,1,(512,2))
    cutoff=np.where(np.arange(512)%2,40,.45*sr)
    full=svf(noise,sr,cutoff,24,slope=slope)
    state=SVF(sr,2,slope=slope)
    parts=np.concatenate([state.process(noise[a:a+37],cutoff[a:a+37],24) for a in range(0,512,37)])
    assert full.tobytes()==parts.tobytes()
    assert np.isfinite(full).all()


def test_filter_controls_glide_and_spectrum():
    from mankomix.dspx.procs.filter_seq import controls
    sr=8000
    p=params('filter_seq',step_note='none',step_ms=200,steps=2,cutoff_oct=[-1,1],glide_ms=20)
    f,_,_=controls(3200,sr,p)
    assert f[1600]==400 and f[1760]==1600
    midpoint=np.flatnonzero(f[1600:1761]>=800)[0]/sr
    assert abs(midpoint-.01)<1/sr
    long,_,_=controls(3200,sr,{**p,'glide_ms':500})
    assert abs(np.log2(long[1600]/long[1599])) < .001
    noise=H.white_noise(sr=sr,seconds=1)
    y=render('filter_seq',noise,sr,dict(step_note='none',step_ms=1000,base_hz=800,resonance_db=[0]*16,glide_ms=0)).audio
    f,transfer=signal.csd(noise[:,0],y[:,0],fs=sr,nperseg=2048)
    _,power=signal.welch(noise[:,0],fs=sr,nperseg=2048)
    db=20*np.log10(np.maximum(abs(transfer)/power,1e-12))
    cross=np.flatnonzero((f>700)&(db<=-3.01))[0]
    assert abs(f[cross]/800-1)<.03


def test_env_filter_mapping_time_constants_sign_and_ceiling():
    from mankomix.dspx.procs.env_filter import cutoff_control
    sr=8000
    # Constant absolute alternating carrier has no rectifier ripple.
    levels=np.repeat([-60.,-23.,-6.,0.,-60.],sr)
    x=(10**(levels/20)*np.where(np.arange(len(levels))%2,1,-1))[:,None]
    p=params('env_filter',attack_ms=10,release_ms=100)
    f,env=cutoff_control(x,sr,p)
    expected=[]
    for i,level in enumerate([-60,-23,-6,0,-60]):
        want=300*2**(3*np.clip((level+40)/34,0,1))
        measured=float(f[(i+1)*sr-1,0])
        assert abs(measured/want-1)<.001
        expected.append(measured)
    for start,initial,final,tau in [(sr,-60,-23,.01),(4*sr,0,-60,.1)]:
        response=H.step_response_time(env[:,0],sr,start,initial,final)
        assert abs(response['time_s']/tau-1)<.15
    down,_=cutoff_control(x,sr,{**p,'range_oct':-3})
    assert down[3*sr-1,0] < down[sr-1,0]
    assert abs(f[3*sr-1,0]-f[4*sr-1,0])<1e-3
    metric('env_filter',cutoffs_hz=expected)


def test_env_filter_audio_cutoff_mapping_with_probe_noise():
    sr=8000
    rng=np.random.default_rng(30)
    for level in (-50,-23,-6):
        tone=np.where(np.arange(sr)%2,1.,-1.)*10**(level/20)
        noise=rng.standard_normal(sr)*10**((level-40)/20)
        x=(tone+noise)[:,None]
        p=dict(filter='lowpass',resonance_db=0,attack_ms=.5,base_hz=200,range_oct=2)
        y=render('env_filter',x,sr,p).audio[:,0]
        f,h=signal.csd(noise[2000:],y[2000:],fs=sr,nperseg=1024)
        _,power=signal.welch(noise[2000:],fs=sr,nperseg=1024)
        db=20*np.log10(np.maximum(abs(h)/power,1e-15))
        want=200*2**(2*np.clip((level+40)/34,0,1))
        index=np.flatnonzero((f>want*.8)&(db < -3.0103))[0]
        assert abs(f[index]/want-1)<.05


@pytest.mark.parametrize('sr',[44100,48000,96000])
def test_carrier_harmonic_frequency_and_alias(sr):
    from mankomix.dspx.bb.band_envelopes import carrier
    for mode in ('saw','pulse'):
        p=params('vocoder',notes=[69],carrier=mode,unvoiced=0)
        y=carrier(sr//5,sr,p)[:,0]
        f=np.fft.rfftfreq(len(y),1/sr)
        power=abs(np.fft.rfft(y))**2
        harmonic=np.zeros(len(f),dtype=bool)
        for n in range(1,int(.45*sr/440)+1):
            harmonic |= abs(f-440*n)<1
        ratio=10*np.log10(power[~harmonic].sum()/power[harmonic].sum())
        assert ratio < -70
        freq=H.fundamental_frequency(y,sr,low_hz=400,high_hz=480)
        assert abs(1200*np.log2(freq/440))<2
        metric('carrier',sr=sr,mode=mode,off_harmonic_db=float(ratio),frequency_hz=freq)


def test_vocoder_band_localization_shift_silence_and_envelope_tau():
    from mankomix.dspx.bb import band_envelopes as B
    sr=24000
    p=params('vocoder',bands=8,lo_hz=100,hi_hz=8000,band_q=20,carrier='noise',unvoiced=0)
    centers=B.centers(p,sr)
    k=3
    x=H.sine(centers[k],sr=sr,seconds=.5)
    for shift in (0,12*np.log2(centers[k+1]/centers[k])):
        # A one-band shift is >12 semitones at this sparse layout; use 16 bands below instead.
        if shift>12:
            continue
        y=render('vocoder',x,sr,{**p,'formant_shift':shift}).audio[4000:,0]
        target=k+(shift!=0)
        f=np.fft.rfftfreq(len(y),1/sr)
        energy=abs(np.fft.rfft(y))**2
        lo=np.sqrt(centers[target-1]*centers[target]); hi=np.sqrt(centers[target]*centers[target+1])
        fraction=energy[(f>=lo)&(f<hi)].sum()/energy.sum()
        assert fraction>=.9
        metric('vocoder_band',shift=shift,energy_fraction=float(fraction))
    assert not np.any(render('vocoder',np.zeros_like(x),sr,p).audio)
    from mankomix.dspx.bb.dynamics import envelope
    e=envelope(np.r_[np.zeros(100),np.ones(1000),np.zeros(2000)],8000,5,40)
    for at,a,b,tau in [(100,0,1,.005),(1100,1,0,.04)]:
        response=H.step_response_time(e,8000,at,a,b)
        assert abs(response['time_s']/tau-1)<.15


def test_band_control_assets_and_shared_direct_path(monkeypatch):
    from mankomix.dspx.bb import band_envelopes as B
    from mankomix.dspx import assets
    sr=24000
    p=params('vocoder',unvoiced=0,carrier='saw',notes=[69])
    x=H.sine(1000,sr=sr,seconds=.1)
    env=B.analyze(x,sr,p)
    # Full-rate record demonstrates exact processing equivalence; W4 may write 5 ms hops.
    record=dict(kind='control',values=env,hop_s=1/sr,centers_hz=B.centers(p,sr))
    monkeypatch.setitem(assets.RESOLVERS,'derived',lambda key: record if key=='ctrl' else {'kind':'control','empty':True})
    car=B.carrier(len(x),sr,p)
    out=render('band_envelope',car,sr,dict(envelopes='ctrl')).audio
    direct=B.synthesize(car,sr,p,env)
    assert np.max(abs(out-direct))<1e-12
    voc=render('vocoder',x,sr,p).audio
    assert np.max(abs(voc-direct))<1e-12
    with pytest.raises(ParamError):
        render('band_envelope',x,sr)
    for bad in [dict(kind='clip'),dict(kind='control',values=[[float('nan')]*16]),
                dict(kind='control',values=[[1]*15]), dict(kind='control',values=[[1]*16],hop_s=0)]:
        monkeypatch.setitem(assets.RESOLVERS,'derived',lambda key:bad)
        with pytest.raises(ParamError):
            render('band_envelope',x,sr,dict(envelopes='bad'))


@pytest.mark.parametrize('component',['hiss','crackle','hum','rumble'])
def test_noise_rms_and_poisson_rate_60_seconds(component):
    sr=8000
    x=np.zeros((60*sr,1))
    p={component+'_db':-50}
    r=render('noise_bed',x,sr,p)
    level=H.rms_dbfs(r.audio)
    assert abs(level+50)<.5
    metric('noise_level',component=component,dbfs=level)
    if component=='crackle':
        rate=r.steps[0]['stats']['click_count']/60
        assert abs(rate/8-1)<.05
        metric('poisson',rate_hz=rate)


def test_pink_and_spectrum_shapes_and_random_access():
    from mankomix.dspx.procs.noise_bed import noise_components
    sr=16000
    p=params('noise_bed',hiss_db=-50,hiss_color='pink',crackle_db=-60,rumble_db=-60)
    full=noise_components(10*sr,sr,p,seed=30)
    part=noise_components(15001,sr,p,seed=30,start_sample=12023)
    for key in ('hiss','crackle','rumble'):
        assert full[key][12023:27024].tobytes()==part[key].tobytes()
    f,power=signal.welch(full['hiss'][:,0],fs=sr,nperseg=4096)
    bands=[]
    for center in (125,250,500,1000,2000,4000):
        use=(f>=center/np.sqrt(2))&(f<center*np.sqrt(2))
        bands.append(10*np.log10(power[use].mean()))
    slope=np.polyfit(np.arange(len(bands)),bands,1)[0]
    assert abs(slope+3.0103)<.5
    metric('pink',slope_db_oct=float(slope))
    p=params('noise_bed',hiss_db=-50,spectrum=[[20,-12],[250,-6],[2000,3],[7000,0]])
    shaped=noise_components(10*sr,sr,p,seed=30)['hiss'][:,0]
    f,power=signal.welch(shaped,fs=sr,nperseg=4096)
    measured=[];expected=[]
    for center in (125,250,500,1000,2000,4000):
        use=(f>=center/2**(1/6))&(f<center*2**(1/6))
        measured.append(10*np.log10(power[use].mean()))
        expected.append(np.interp(np.log(center),np.log([20,250,2000,7000]),[-12,-6,3,0]))
    err=np.asarray(measured)-expected
    err-=err.mean()
    assert max(abs(err))<1
    metric('spectrum',max_shape_error_db=float(max(abs(err))))


def test_noise_engine_seed_item_width_follow_and_dropout():
    x=np.zeros((8000,2)); sr=8000
    p=dict(hiss_db=-50,crackle_db=-60,rumble_db=-60)
    a=render('noise_bed',x,sr,p)
    assert a.audio.tobytes()==render('noise_bed',x,sr,p).audio.tobytes()
    assert a.audio.tobytes()!=render('noise_bed',x,sr,p,seed=13).audio.tobytes()
    assert a.audio.tobytes()!=render('noise_bed',x,sr,{**p,'seed':1}).audio.tobytes()
    assert a.audio.tobytes()!=render('noise_bed',x,sr,p,item='other').audio.tobytes()
    mono=render('noise_bed',x,sr,{**p,'width':0}).audio
    assert mono[:,0].tobytes()==mono[:,1].tobytes()
    assert not np.any(render('noise_bed',x,sr,{**p,'follow':1}).audio)
    tone=np.full_like(x,.1)
    dropout=render('noise_bed',tone,sr,dict(dropout=1)).audio
    assert np.any(dropout<tone) and np.all(dropout<=tone)


@pytest.mark.parametrize('name',TYPES)
def test_context_replay_excerpt_and_bit_neutral(name):
    sr=24000
    x=H.white_noise(sr=sr,seconds=.08,channels=2)
    p=valid(name)
    if name=='noise_bed': p['hiss_db']=-60
    if name=='tape_stop': p.update(stop_s=[.01],stop_ms=30)
    full=H.render(name,x,sr,p).audio
    part=H.render_excerpt(name,x,sr,701,len(x),p)
    assert full[701:].tobytes()==part.tobytes()
    neutral={**valid(name),'mix':0} if name not in ('tape_stop','noise_bed') else {}
    assert render(name,x,sr,neutral).audio.tobytes()==x.tobytes()


def test_causal_reading_and_stop_clock_integral():
    from mankomix.dspx.procs.tape_stop import speed_map
    sr=16000
    x=H.white_noise(sr=sr,seconds=.2)
    changed=x.copy(); changed[1000:]*=-3
    for name,p in [('halftime',dict(loop_note='none',loop_ms=80)),
                   ('tape_stop',dict(stop_s=[.01],stop_ms=100))]:
        assert render(name,x,sr,p).audio[:1000].tobytes()==render(name,changed,sr,p).audio[:1000].tobytes()
    p=params('tape_stop',stop_s=[.01],stop_ms=100,curve=2)
    position,speed,used=speed_map(3000,sr,p)
    n=np.arange(162,1700)
    measured=(position[n+1]-position[n-1])/2
    # Exact central-difference correction for this cubic position polynomial.
    correction=1/(3*(.1*sr)**2)
    assert np.max(abs(measured-speed[n]+correction)) < 1e-12


def test_active_intervals_preserve_exact_samples():
    sr=24000
    x=H.white_noise(sr=sr,seconds=.15)
    for name in ('halftime','filter_seq','reverse_chunks'):
        p={**valid(name),'active':[[0,0],[.03,1],[.1,0]]}
        y=render(name,x,sr,p).audio
        assert y[:720].tobytes()==x[:720].tobytes()
        assert y[2400:].tobytes()==x[2400:].tobytes()


def test_array_extremes_and_external_asset_rejection():
    sr=48000
    x=H.white_noise(sr=sr,seconds=.008)
    for name in TYPES:
        for s in P.describe(name)['params']:
            if s['type']!='float_array':
                continue
            for endpoint in (s['min'],s['max']):
                p=valid(name)
                if name=='tape_stop':
                    if s['id']=='start_s':
                        # start=0 cannot follow a nonnegative stop; the endpoint is relationally invalid.
                        with pytest.raises(ParamError):
                            render(name,x,sr,{s['id']:[endpoint]})
                        continue
                    p.update(stop_s=[endpoint],stop_ms=10)
                elif name=='filter_seq':
                    p.update(steps=64,**{s['id']:[endpoint]*64})
                else:
                    p[s['id']]=[endpoint]*s['max_len']
                y=render(name,x,sr,p).audio
                assert np.isfinite(y).all() and y.shape==x.shape
    with pytest.raises(ParamError):
        render('vocoder',x,sr,dict(envelopes='unknown-control'))


def test_noise_width_level_and_sr_consistency():
    for sr in (44100,48000,96000):
        x=np.zeros((round(.4*sr),2))
        for width in (0,.5,1):
            y=render('noise_bed',x,sr,dict(hiss_db=-40,hiss_color='white',width=width)).audio
            levels=[H.rms_dbfs(y[:,c]) for c in range(2)]
            assert max(abs(np.asarray(levels)+40))<.5
        y=render('noise_bed',x,sr,dict(hum_db=-40,hum_hz=60)).audio
        f=H.fundamental_frequency(y,sr,low_hz=40,high_hz=80)
        assert abs(f-60)<1


def test_vocoder_notes_curve_and_chord():
    from mankomix.dspx.bb.band_envelopes import carrier
    sr=24000
    p=params('vocoder',carrier='saw',notes_curve=[[0,69],[.1,81]])
    y=carrier(4800,sr,p)
    for a,b,want in [(400,2200,440),(2800,4600,880)]:
        f=H.fundamental_frequency(y[a:b],sr,low_hz=want*.9,high_hz=want*1.1)
        assert abs(1200*np.log2(f/want))<2
    p=params('vocoder',carrier='saw',notes=[69,76])
    y=carrier(4800,sr,p)
    f,power=signal.periodogram(y[:,0],fs=sr)
    for want in (440,440*2**(7/12)):
        peak=f[np.argmax(np.where(abs(f-want)<10,power,0))]
        assert abs(peak-want)<5


def test_vocoder_actual_band_envelope_times():
    from mankomix.dspx.bb.band_envelopes import analyze
    sr=24000
    p=params('vocoder',attack_ms=50,release_ms=200)
    t=np.arange(sr)/sr
    x=(.1*np.sin(2*np.pi*8000*t))[:,None]
    x[:2400]=0; x[14400:]=0
    e=analyze(x,sr,p)[:,-1,0]
    steady=float(np.mean(e[12000:14000]))
    measured=[]
    for at,a,b,tau in [(2400,0,steady,.05),(14400,steady,0,.2)]:
        r=H.step_response_time(e,sr,at,a,b)
        assert abs(r['time_s']/tau-1)<.15
        measured.append(r['time_s'])
    metric('vocoder_band_tau',attack_s=measured[0],release_s=measured[1])


def test_vocoder_engine_randomness_uses_all_seed_sources():
    sr=24000
    x=H.sine(1000,sr=sr,seconds=.08)
    p=dict(carrier='noise',unvoiced=0)
    a=render('vocoder',x,sr,p).audio
    assert a.tobytes()==render('vocoder',x,sr,p).audio.tobytes()
    assert a.tobytes()!=render('vocoder',x,sr,p,seed=13).audio.tobytes()
    assert a.tobytes()!=render('vocoder',x,sr,{**p,'seed':1}).audio.tobytes()
    assert a.tobytes()!=render('vocoder',x,sr,p,item='other').audio.tobytes()
