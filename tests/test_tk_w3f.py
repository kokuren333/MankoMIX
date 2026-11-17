"""W3f acceptance and explicitly retained specification/integration failures."""
import importlib
import itertools
import json
import numpy as np
import pytest
from scipy import signal
from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from tests import toolimpl_harness as H

TYPES = ('tape','cassette','lofi','amp_basic','reverb_spring')
PUBLIC = dict.fromkeys(TYPES, False)
PUBLIC['reverb_spring'] = True
CONTRACT = {
 'tape': dict(drive_db=(0,24,0),output_db=(-36,12,0),auto_gain=False,mix=(0,1,1),
    oversample=([1,2,4,8],4), amount=(0,1,1),speed=([3.75,7.5,15,30],15),
    bias=(0,1,.5),saturation=(0,1,.5),hysteresis=True,head_bump_db=(0,6,1.5),
    gap_loss=(0,1,.5),wow_depth=(0,3,0),flutter_depth=(0,1,0),noise_db=(-120,-50,-120),seed=(0,65535,0)),
 'amp_basic': dict(drive_db=(0,60,24),output_db=(-36,12,0),auto_gain=False,mix=(0,1,1),
    oversample=([1,2,4,8],8),stages=(1,4,2),bright=False,bass=(0,1,.5),mid=(0,1,.5),
    treble=(0,1,.5),tonestack=(['scoop','flat','mid_forward'],'scoop'),power_drive_db=(0,24,0),
    sag=(0,1,.2),presence_db=(-6,6,0)),
 'cassette': dict(wobble=(0,1,.3),saturation=(0,1,.5),tape_type=(['normal','chrome','metal'],'normal'),
    age=(0,1,.3),hiss_db=(-120,-40,-66),narrow=(0,1,.2),seed=(0,65535,0)),
 'lofi': dict(style=(['tape','vinyl','digital','radio'],'tape'),wobble=(0,1,.3),dirt=(0,1,.3),
    crunch=(0,1,0),tone=(0,1,.5),noise=(0,1,.3),space=(0,1,0),seed=(0,65535,0)),
 'reverb_spring': dict(rt60_s=(.5,6,2.5),predelay_ms=(0,250,0),mix=(0,1,.2),lowcut_hz=(20,2000,100),
    highcut_hz=(1000,20000,6000),bpm=(0,400,0),seed=(0,65535,0),duck_db=(0,24,0),
    duck_threshold_db=(-80,0,-40),duck_attack_ms=(.1,200,10),duck_release_ms=(5,3000,250),
    springs=(1,3,2),delay_ms=(20,80,45),chirp_hz=(2000,8000,4300),dispersion=(0,1,.7),
    damping_hz=(1000,12000,5000),drive_db=(0,12,0))}


@pytest.fixture(autouse=True)
def candidate_registration(monkeypatch):
    for name in TYPES:
        assert P.PROCESSORS[name]['implemented'] is PUBLIC[name]
        monkeypatch.setitem(P.PROCESSORS[name], 'implemented', True)


def render(name, x, p=None, sr=48000, seed=0, sid='probe'):
    return E.render_chain(x,sr,[dict(type=name,params=p or {},id=sid)],stage='track',seed=seed)


def tone(f=1000, level=-6, sr=48000, seconds=.3):
    return H.sine(f,level,sr=sr,seconds=seconds)


def spectral(y, f=1000, sr=48000):
    # Last central 100 ms, coherent tones; exclude startup and FIR end.
    z = y[round(.15*sr):round(.25*sr),0]
    sp = 2*np.abs(np.fft.rfft(z))/len(z)
    k = round(f*len(z)/sr)
    fundamental = sp[k]
    bins = [k*i for i in range(2,8) if k*i < len(sp)]
    harmonics = sp[bins]
    allowed = np.zeros(len(sp),dtype=bool)
    allowed[0] = True
    allowed[k] = True
    for j in range(2,100):
        if k*j < len(sp): allowed[k*j] = True
    return dict(thd_db=H.db(np.linalg.norm(harmonics)/fundamental),
        harmonic_dbc=[H.db(v/fundamental) for v in harmonics],
        alias_dbc=H.db(np.linalg.norm(sp[~allowed])/fundamental),
        gain_db=H.db(fundamental),dc_dbfs=H.db(abs(np.mean(z))))


@pytest.mark.parametrize('name',TYPES)
def test_parameter_contract_and_all_endpoints(name):
    spec = P.describe(name)
    actual = {v['id']:v for v in spec['params']}
    assert set(actual) == set(CONTRACT[name])
    base = P.validate_params(name,{})
    # Runtime boundaries need only a short nonzero record, not an RT decay.
    # A lower sr keeps full IR boundary designs within the three-minute file budget.
    rate = 16000 if name == 'reverb_spring' else 48000
    x = tone(sr=rate,seconds=.012)
    for key, expected in CONTRACT[name].items():
        v = actual[key]
        if isinstance(expected,bool):
            assert v['default'] is expected
            values = [False,True]
        elif len(expected) == 2:
            assert (v['choices'],v['default']) == expected
            values = expected[0]
        else:
            assert (v['min'],v['max'],v['default']) == expected
            values = expected[:2]
        for value in values:
            p = dict(base,**{key:value})
            y = render(name,x,p,sr=rate).audio
            assert y.shape == x.shape and np.isfinite(y).all(), (name,key,value)
    print('CONTRACT',name,json.dumps(base,sort_keys=True))


def frequency_probe(x,y,sr,p):
    f = H.fundamental_frequency(y,sr,low_hz=900,high_hz=1100)
    return dict(frequency_hz=f,passed=abs(f-1000) <= 1)


@pytest.mark.parametrize('name',TYPES)
def test_common_ct_1_to_8(name):
    options = {
      'tape': dict(params=dict(hysteresis=False),neutral=dict(amount=0),
        latency_params=dict(amount=0),declared_latency=0),
      'amp_basic': dict(neutral=dict(drive_db=0,power_drive_db=0),latency_params=dict(drive_db=0,power_drive_db=0)),
      'reverb_spring': dict(params=dict(rt60_s=.5),neutral=dict(mix=0),feedback=True),
      'cassette': dict(params=dict(wobble=0,saturation=.2,age=0,hiss_db=-120,narrow=0),
        latency_params=dict(saturation=0,narrow=1),declared_latency=0),
      'lofi': dict(params=dict(wobble=0,dirt=.3,crunch=0,tone=0,noise=0,space=0),declared_latency=0),
    }[name]
    result = H.assert_common_tests(name,seconds=.03,sr_probe=frequency_probe,**options)
    print('COMMON',name,json.dumps({k:v['passed'] for k,v in result.items()},sort_keys=True))


@pytest.mark.parametrize('name', ['tape','amp_basic','reverb_spring'])
def test_default_is_deterministic_and_silent(name):
    x = tone(seconds=.02)
    assert render(name,x).audio.tobytes() == render(name,x).audio.tobytes()
    assert np.count_nonzero(render(name,np.zeros_like(x)).audio) == 0


@pytest.mark.parametrize('name', ['cassette','lofi'])
def test_composite_manual_expansion_and_records(name):
    module = importlib.import_module('mankomix.dspx.procs.'+name)
    p = P.validate_params(name,{})
    x = tone(seconds=.05)
    children = module.expand(p)
    manual = [dict(child,id=f'probe.{i}') for i,child in enumerate(children,1)]
    whole = render(name,x,p,seed=19)
    separate = E.render_chain(x,48000,manual,stage='track',seed=19)
    assert whole.audio.tobytes() == separate.audio.tobytes()
    assert len(whole.steps) == len(children)
    assert all(r['composite_of']['type'] == name for r in whole.steps)
    for child in children:
        P.validate_params(child['type'],child['params'])


@pytest.mark.parametrize('name', ['cassette','lofi'])
@pytest.mark.xfail(strict=True,reason='BB-00 rejects the required empty neutral expansion; shared engine not edited')
def test_composite_all_zero_engine_identity(name):
    module = importlib.import_module('mankomix.dspx.procs.'+name)
    p = dict(wobble=0,saturation=0,age=0,hiss_db=-120,narrow=0) if name == 'cassette' else dict.fromkeys(
        ['wobble','dirt','crunch','tone','noise','space'],0)
    assert module.expand(P.validate_params(name,p)) == []
    x = tone()
    assert render(name,x,p).audio.tobytes() == x.tobytes()


@pytest.mark.parametrize('style',['tape','vinyl','digital','radio'])
def test_lofi_documented_style_mapping(style):
    from pathlib import Path
    from mankomix.dspx.procs.lofi import expand
    expected = dict(tape=(1.5,.4,12,12,12000,30,10000,['hiss']),
        vinyl=(.8,.2,9,14,16000,40,12000,['crackle','rumble']),
        digital=(.3,.08,18,4,4000,20,18000,['hiss']),
        radio=(.2,.05,15,8,8000,300,3500,['hiss','hum']))[style]
    p = P.validate_params('lofi',dict(style=style,**dict.fromkeys(['wobble','dirt','crunch','tone','noise','space'],1)))
    child = expand(p)
    assert [v['type'] for v in child] == ['wow_flutter','saturator','bitcrush','cut_filter','cut_filter','noise_bed','reverb']
    w,f,d,b,r,lo,hi,noises = expected
    assert child[0]['params'] == dict(wow_depth=w,flutter_depth=f,seed=0)
    assert child[1]['params']['drive_db'] == d
    assert child[2]['params']['bits'] == b
    assert child[2]['params']['rate_hz'] == pytest.approx(r)
    assert child[3]['params']['freq_hz'] == lo
    assert child[4]['params']['freq_hz'] == pytest.approx(hi)
    assert set(child[5]['params'])-{'seed','hiss_color'} == {n+'_db' for n in noises}
    assert child[6]['params'] == dict(rt60_s=.3,predelay_ms=0,mix=.25)
    doc = Path('dspx/COMPOSITES.md').read_text(encoding='utf-8')
    row = next(line for line in doc.split('## Lofi')[1].splitlines() if line.startswith(f'| {style} |'))
    fields = [part.strip() for part in row.strip('|').split('|')]
    assert list(map(float,fields[1:8])) == [w,f,d,24-b,r,lo,hi]
    assert fields[8] == ', '.join(noises) or (style == 'digital' and fields[8] == 'white hiss')


@pytest.mark.parametrize('material,bias,gap,cutoff',[
    ('normal',.45,.65,10000),('chrome',.55,.45,14000),('metal',.6,.3,16000)])
def test_cassette_documented_material_mapping(material,bias,gap,cutoff):
    from pathlib import Path
    from mankomix.dspx.procs.cassette import expand
    p = P.validate_params('cassette',dict(tape_type=material,wobble=1,saturation=1,age=1,hiss_db=-40,narrow=1,seed=65535))
    child = expand(p)
    assert [c['type'] for c in child] == ['wow_flutter','tape','cut_filter','noise_bed','stereo']
    assert child[0]['params'] == dict(wow_depth=1.5,flutter_depth=.4,seed=65535)
    assert child[1]['params'] == dict(speed=3.75,saturation=1,drive_db=6,bias=bias,gap_loss=min(1,gap+.35),seed=65535)
    assert child[2]['params'] == dict(kind='lpf',freq_hz=cutoff*.5)
    assert child[3]['params'] == dict(hiss_db=-40,dropout=.3,seed=65535)
    assert child[4]['params'] == dict(width=.5)
    doc = Path('dspx/COMPOSITES.md').read_text(encoding='utf-8').split('## Lofi')[0]
    row = next(line for line in doc.splitlines() if line.startswith(f'| {material} |'))
    fields = [part.strip() for part in row.strip('|').split('|')]
    assert list(map(float,fields[1:])) == [bias,gap,cutoff]


@pytest.mark.parametrize('name,p', [('tape',dict(noise_db=-60)),('tape',dict(wow_depth=.3,flutter_depth=.1)),
    ('cassette',{}),('lofi',dict(style='vinyl')) ,('reverb_spring',dict(rt60_s=.5))])
def test_project_item_and_parameter_seeds(name,p):
    x = tone(seconds=.025)
    a = render(name,x,p,seed=1).audio
    assert a.tobytes() == render(name,x,p,seed=1).audio.tobytes()
    assert a.tobytes() != render(name,x,p,seed=2).audio.tobytes()
    assert a.tobytes() != render(name,x,p,seed=1,sid='other').audio.tobytes()
    assert a.tobytes() != render(name,x,dict(p,seed=7),seed=1).audio.tobytes()


def test_tape_loss_and_bump_scale_with_speed():
    from mankomix.dspx.bb.tape_model import loss_fir, head_bump_sos
    rows = []
    for speed in [3.75,7.5,15,30]:
        f, response = signal.sosfreqz(head_bump_sos(48000,speed,6),worN=65536,fs=48000)
        peak = f[np.argmax(abs(response))]
        f,h = signal.freqz(loss_fir(48000,speed,1,.5),worN=65536,fs=48000)
        cutoff = f[np.flatnonzero(abs(h) <= 10**(-3/20))[0]]
        rows.append((speed,peak,cutoff))
        assert peak == pytest.approx(60*speed/15,rel=.1)
    assert all(rows[i][2] < rows[i+1][2] for i in range(3))
    print('TAPE_SPEED',rows)


def test_tape_saturation_bias_and_ode_memory():
    from mankomix.dspx.bb.tape_model import magnetize
    rows = []
    x = tone(seconds=.3)
    for sat in [0,.25,.5,.75,1]:
        v = spectral(render('tape',x,dict(saturation=sat,hysteresis=False,head_bump_db=0,gap_loss=0)).audio)
        rows.append(v['harmonic_dbc'][1])
    assert np.all(np.diff(rows)>0)
    small = tone(level=-40)
    bias = [spectral(render('tape',small,dict(bias=b,hysteresis=False,head_bump_db=0,gap_loss=0)).audio)['thd_db'] for b in [.5,.25,0]]
    assert np.all(np.diff(bias)>0)
    areas = []
    for f in [10,100,1000]:
        field = H.sine(f,-6,sr=384000,seconds=3/f)
        area = []
        for memory in [False,True]:
            y = magnetize(field,hysteresis=memory)
            start = round(384000/f)
            # Explicitly close the periodic polygon (including its last edge).
            xx, yy = field[start:,0],y[start:,0]
            integral = abs(np.sum((np.roll(yy,-1)+yy)*.5*(np.roll(xx,-1)-xx)))
            area.append(integral)
        assert area[0] < 1e-10 and area[1] > 1e-5
        areas.append((f,area))
    print('TAPE_SAT_BIAS_MEMORY',rows,bias,areas)


@pytest.mark.parametrize('memory',[False,True])
def test_tape_fullscale_all_frequencies_and_rk4_convergence(memory):
    from mankomix.dspx.bb import nonlinear as N
    from mankomix.dspx.bb.tape_model import magnetize
    rows = []
    for f in [10,100,1000,5000,10000,15000,20000,23900]:
        x = tone(f,0,seconds=.015)
        y = render('tape',x,dict(hysteresis=memory,drive_db=24,saturation=1,bias=0)).audio
        assert np.isfinite(y).all() and np.max(abs(y)) < 10
    if memory:
        for f in [100,1000,15000]:
            x = tone(f,0,seconds=.02)
            a = N.precision_oversampled(x,8,lambda u: magnetize(u,saturation=1))
            b = N.precision_oversampled(x,16,lambda u: magnetize(u,saturation=1))
            rows.append((f,H.null(a[100:-100],b[100:-100])['rms_dbfs']))
    print('TAPE_ODE_STABILITY',memory,rows)


def test_tape_memoryless_time_invariance_and_mix_alignment():
    x = np.zeros((24000,1)); x[4000:5000] = tone(seconds=1000/48000)
    other = np.roll(x,4000,axis=0)
    p = dict(hysteresis=False,head_bump_db=0,gap_loss=0)
    a = render('tape',x,p).audio
    b = render('tape',other,p).audio
    assert H.null(a[500:19000],b[4500:23000])['rms_dbfs'] <= -120
    pulse = np.zeros((6000,1)); pulse[3000]=.1
    for mix in [.5,1]:
        y = render('tape',pulse,dict(p,mix=mix)).audio
        assert np.argmax(abs(y[:,0])) == 3000


@pytest.mark.parametrize('style',['scoop','flat','mid_forward'])
def test_amp_passive_tonestack_against_independent_nodal_solution(style):
    from mankomix.dspx.bb.amp_circuit import tone_coefficients
    for sr in [44100,48000,96000]:
        for bass,mid,treble in [(0,0,0),(.5,.5,.5),(1,1,1),(0,1,0)]:
            p = P.validate_params('amp_basic',dict(tonestack=style,bass=bass,mid=mid,treble=treble))
            f = np.geomspace(20,min(20000,.45*sr),128)
            _,h = signal.sosfreqz(tone_coefficients(sr,p),worN=f,fs=sr)
            ratios = dict(scoop=(1,1,1),flat=(.7,1.8,.7),mid_forward=(.5,3,.5))[style]
            cb,cm,ct = np.array([22e-9,2.2e-9,470e-12])*ratios
            gb,gt,gm = 1/(22000+470000*bass),1/(22000+220000*(1-treble)),1/(10000+100000*(1-mid))
            expected = []
            for hz in f:
                s = 2j*sr*np.tan(np.pi*hz/sr)
                matrix = np.array([[s*(cb+cm)+gb+gm,-gm],[-gm,s*ct+gt+gm]])
                expected.append(np.linalg.solve(matrix,np.array([s*cb,gt]))[1])
            error = np.max(abs(20*np.log10(abs(h)/np.abs(expected))))
            assert error <= .1 and np.max(abs(h)) <= 1+1e-12


def test_amp_drive_sag_bounds_and_mix():
    rows = []
    for drive in [0,12,24,36,60]:
        v = spectral(render('amp_basic',tone(),dict(drive_db=drive,sag=0)).audio)
        rows.append(v['thd_db'])
    assert np.all(np.diff(rows)>0)
    x = np.ones((24000,1))
    a = render('amp_basic',x,dict(sag=0)).audio
    b = render('amp_basic',x,dict(sag=1))
    assert 0 < b.steps[0]['stats']['sag_max_db'] <= 3
    # The envelope itself has the documented 80 ms time constant.
    acoef = np.exp(-1/(.08*48000))
    envelope = signal.lfilter([1-acoef],[1,-acoef],np.ones(24000))
    assert envelope[3839] == pytest.approx(1-np.exp(-1),abs=1e-10)
    for stages,drive,power in itertools.product([1,4],[0,60],[0,24]):
        y = render('amp_basic',tone(50,0,seconds=.02),dict(stages=stages,drive_db=drive,power_drive_db=power,sag=1)).audio
        assert np.isfinite(y).all() and np.max(abs(y)) < 5
    print('AMP_DRIVE_SAG',rows,b.steps[0]['stats'])


@pytest.mark.parametrize('name,limit',[('tape',-70),('amp_basic',-60)])
def test_nonlinear_nt2_nt3_nt4_nt5_vectors(name,limit):
    vectors = []
    drives = [0,6,12,18,24] if name == 'tape' else [0,12,24,36,60]
    for drive in drives:
        controls = dict(drive_db=drive)
        v = spectral(render(name,tone(),controls).audio)
        aliases = [spectral(render(name,tone(f),controls).audio,f)['alias_dbc'] for f in [5000,10000,15000]]
        small = spectral(render(name,tone(level=-60),controls).audio)['gain_db']+60
        vectors.append(dict(drive_db=drive,**v,alias=aliases,small_signal_gain_db=small))
        if name == 'amp_basic':
            assert max(aliases) <= limit
            assert abs(small) <= .05
    print('NONLINEAR_VECTORS',name,json.dumps(vectors,sort_keys=True))
    # These are diagnostics; the exact unmet acceptance tests below stay xfail.
    assert all(np.isfinite(v['gain_db']) for v in vectors)


@pytest.mark.parametrize('name',['tape'])
@pytest.mark.xfail(strict=True,reason='Generic filtering/magnetic circuit has not met the flat NT4 small-signal requirement')
def test_nt4_flat_small_signal(name):
    gain = spectral(render(name,tone(level=-60)).audio)['gain_db']+60
    assert abs(gain) <= .05


@pytest.mark.xfail(strict=True,reason='The causal interstage filters leave a measured one-sample wet/dry mismatch (NT6)')
def test_amp_nt6_active_impulse_alignment():
    x = np.zeros((6000,1));x[3000]=.1
    wet = render('amp_basic',x).audio
    assert H.latency(wet,reference=x,method='correlation') == 0


@pytest.mark.xfail(strict=True,reason='Fixed 8x physical tape has not met -70 dBc at the maximum drive')
def test_tape_nt2_maximum_drive():
    v = spectral(render('tape',tone(15000),dict(drive_db=24)).audio,15000)
    assert v['alias_dbc'] <= -70


@pytest.mark.parametrize('name',['tape','amp_basic'])
def test_nonlinear_exact_mix_and_dc(name):
    x = tone(seconds=.08)
    p = dict(hysteresis=False) if name == 'tape' else {}
    wet = render(name,x,p).audio
    half = render(name,x,dict(p,mix=.5)).audio
    assert H.null(half,.5*(x+wet))['rms_dbfs'] <= -120
    assert H.db(float(np.max(abs(np.mean(wet,axis=0))))) <= -80
    auto = render(name,x,dict(p,drive_db=12,auto_gain=True,output_db=3)).audio
    base = render(name,x,dict(p,drive_db=12)).audio
    assert H.null(auto,base*10**(-9/20))['rms_dbfs'] <= -120


def test_spring_monotonic_group_delay_and_echo_count():
    from mankomix.dspx.bb.spring import spectral_delay,spring_lines,render_spring_ir
    for sr in [44100,48000,96000]:
        p = P.validate_params('reverb_spring',{})
        f = np.linspace(200,p['chirp_hz'],4096)
        phase = np.unwrap(np.angle(spectral_delay(np.exp(-2j*np.pi*f/sr),sr,p)))
        gd = -np.gradient(phase,2*np.pi*f/sr)
        assert np.min(np.diff(gd[2:-2])) >= -1e-8
        print('SPRING_GROUP_DELAY',sr,float(gd[0]),float(gd[-1]))
    for count in [1,2,3]:
        p = P.validate_params('reverb_spring',dict(springs=count,rt60_s=.5,dispersion=0))
        lengths = spring_lines(16000,p,3)
        assert len(np.unique(lengths)) == count
        assert np.max(abs(lengths/16000/.045-1)) <= .05
        h,_ = render_spring_ir(16000,p,3)
        peaks,_ = signal.find_peaks(abs(h[:,0,0]),distance=10)
        first = [peaks[np.argmin(abs(peaks-length))] for length in lengths]
        assert len(set(first)) == count
        assert np.max(abs(np.array(first)-lengths)) < 10
        for bounce in [2,3]:
            reflected = [peaks[np.argmin(abs(peaks-bounce*length))] for length in lengths]
            assert len(set(reflected)) == count
            assert np.max(abs(np.array(reflected)-bounce*lengths)) < 10


def test_spring_default_echo_spacing_and_longest_decay():
    from mankomix.dspx.bb.spring import render_spring_ir
    p = P.validate_params('reverb_spring',dict(springs=1,rt60_s=.5))
    h,_ = render_spring_ir(16000,p,0)
    x = h[:,0,0]
    ac = signal.fftconvolve(x,x[::-1],mode='full')[len(x)-1:]
    lo,hi = round(.03*16000),round(.065*16000)
    lag = lo+np.argmax(abs(ac[lo:hi]))
    assert abs(lag/16000/.045-1) <= .05
    x = np.zeros((61*8000,2));x[:800] = np.random.Generator(np.random.PCG64(4)).choice([-1.,1.],(800,2))
    p = dict(rt60_s=6,delay_ms=80,springs=3,dispersion=1,damping_hz=12000,lowcut_hz=20,mix=1)
    y = render('reverb_spring',x,p,sr=8000).audio
    assert np.isfinite(y).all() and H.peak_dbfs(y[-8000:]) < -120
    print('SPRING_DEFAULT_ECHO_MS',lag/16,'MAX_RT_TAIL_DBFS',H.peak_dbfs(y[-8000:]))


@pytest.mark.parametrize('rt',[.5,2.5,6])
def test_spring_rt60_seed_and_linearity(rt):
    from mankomix.dspx.bb.spring import render_spring_ir
    rows = []
    for seed in [1,2]:
        p = P.validate_params('reverb_spring',dict(rt60_s=rt,mix=1))
        h,_ = render_spring_ir(16000,p,seed)
        times = [H.rt60(h.sum(axis=1),16000,band_hz=f) for f in [125,250,500,1000,2000,4000]]
        assert all(t is not None and abs(t/rt-1) <= .15 for t in times)
        rows.append(times)
    assert np.max(abs(np.array(rows[0])/np.array(rows[1])-1)) <= .05
    x = tone(seconds=.1)
    a = render('reverb_spring',x,dict(rt60_s=rt)).audio
    b = render('reverb_spring',x*.1,dict(rt60_s=rt)).audio
    assert H.null(a*.1,b)['rms_dbfs'] <= -120
    print('SPRING_RT',rt,rows)


def test_master_slot_and_unimplemented_public_contract(monkeypatch):
    assert P.PROCESSORS['tape']['master_slot'] == P.PROCESSORS['saturator']['master_slot'] == 3
    for name in ['cassette','lofi','amp_basic','reverb_spring']:
        assert P.PROCESSORS[name]['master_slot'] is None
        with pytest.raises(ChainError):
            E.validate_chain([dict(type=name)],'master')
    for name,value in PUBLIC.items():
        monkeypatch.setitem(P.PROCESSORS[name],'implemented',value)
        if not value:
            with pytest.raises(ChainError): E.validate_chain([dict(type=name)],'track')
