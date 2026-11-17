"""W2a2 acceptance: physical analog targets, flux model, CT, and honest flags."""
import importlib
import itertools
import json
import numpy as np
import pytest
from scipy import signal, optimize
from mankomix.dsp import engine as E, processors as P
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import analog_eq as A, nonlinear as N
from tests import toolimpl_harness as H

EQ = ('passive_eq', 'inductor_eq', 'proportional_eq', 'baxandall_eq')
TYPES = EQ+('transformer',)
PUBLIC = dict.fromkeys(EQ, False) | {'baxandall_eq': True, 'transformer': True}
ACTIVE = dict(passive_eq=dict(low_boost_db=6, low_atten_db=6, high_boost_db=9, high_atten_db=4),
              inductor_eq=dict(hpf_hz=80, low_db=6, mid_db=-9, high_db=6),
              proportional_eq=dict(gain_db=9), baxandall_eq=dict(bass_db=5, treble_db=-5),
              transformer=dict(drive_db=12))
EDGE = dict(passive_eq=dict(high_freq_hz=16000, high_boost_db=18, high_bw=0),
            inductor_eq=dict(mid_freq_hz=7200, mid_db=18, high_db=-16),
            proportional_eq=dict(freq_hz=16000, gain_db=12))

# Independent spec transcription: floats are (min,max,default), enums are
# (choices,default). This does not derive the expected values from SPECS.
CONTRACT = dict(
    passive_eq=dict(low_freq_hz=([20,30,60,100],60), low_boost_db=(0,14,0),
        low_atten_db=(0,18,0), high_freq_hz=([3000,4000,5000,8000,10000,12000,16000],8000),
        high_boost_db=(0,18,0), high_bw=(0,1,.5),
        high_atten_freq_hz=([5000,10000,20000],10000), high_atten_db=(0,16,0)),
    inductor_eq=dict(hpf_hz=([0,50,80,160,300],0), low_freq_hz=([35,60,110,220],110),
        low_db=(-16,16,0), mid_freq_hz=([360,700,1600,3200,4800,7200],1600),
        mid_db=(-18,18,0), high_db=(-16,16,0)),
    proportional_eq=dict(freq_hz=(30,20000,1000), gain_db=(-12,12,0),
        shape=(['peak','low_shelf','high_shelf'],'peak'), bw_min_oct=(.3,2,.6), bw_max_oct=(1,4,2.5)),
    baxandall_eq=dict(bass_hz=([74,84,130,166,230,361],84), bass_db=(-5,5,0),
        treble_hz=([1600,2100,3400,4800,7100,18000],7100), treble_db=(-5,5,0)),
    transformer=dict(drive_db=(0,24,0), output_db=(-36,12,0), auto_gain=False,
        mix=(0,1,1), oversample=([1,2,4,8],4), lf_corner_hz=(5,80,20), core=(0,1,.5),
        lf_emphasis=(0,1,.7), hf_resonance_db=(0,6,0), hf_resonance_hz=(15000,60000,30000)))
for _kind in EQ:
    CONTRACT[_kind].update(drive_db=(0,12,0), output_db=(-24,12,0))


@pytest.fixture(autouse=True)
def candidates_through_engine(monkeypatch):
    for kind in TYPES:
        monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)


def render(kind, x, p=None, sr=48000, stage='track'):
    return E.render_chain(x, sr, [{'type':kind, 'params':p or {}}], stage=stage).audio


def tone(f=1000, db=-6, sr=48000, seconds=1.5):
    return (10.0**(db/20)*np.sin(2*np.pi*f*np.arange(round(sr*seconds))/sr))[:,None]


def db(v):
    return float(20*np.log10(max(float(v), 1e-300)))


def spectral(y, f=1000, sr=48000):
    """Central .5s, rectangular coherent FFT; no startup or resampler edges."""
    n = sr//2
    y = y[sr//2:sr//2+n, 0]
    assert len(y) == n
    sp = 2*abs(np.fft.rfft(y))/n
    amps = [sp[round(k*f*n/sr)] for k in range(1,8) if k*f < sr/2]
    aliases = sp.copy()
    for k in range(1, int(sr/2//f)+1):
        j = round(k*f*n/sr)
        aliases[max(0,j-1):j+2] = 0
    aliases[:2] = 0
    return dict(thd_db=db(np.linalg.norm(amps[1:])/amps[0]),
                harmonic_dbc=[db(a/amps[0]) for a in amps[1:]],
                alias_dbc=db(np.linalg.norm(aliases)/amps[0]),
                fundamental_dbfs=db(amps[0]), dc_dbfs=db(abs(np.mean(y))))


def digital_response(kind, p, hz, sr):
    """Steady-state physical Hz response, including both resampling FIRs."""
    h = signal.sosfreqz(A.design_sos(kind,p,sr), worN=hz, fs=2*sr)[1]
    fir = abs(signal.freqz(N._os_filter(2), worN=hz, fs=2*sr)[1])**2
    return h*fir


def response_error(kind, overrides, sr):
    p = P.validate_params(kind, overrides)
    f = np.geomspace(20,20000,4001)
    error = 20*np.log10(abs(digital_response(kind,p,f,sr)/A.analog_response(kind,p,f)))
    i = np.argmax(abs(error))
    return dict(error_db=float(abs(error[i])), frequency_hz=float(f[i]))


@pytest.mark.parametrize('kind', TYPES)
def test_spec_contract_and_real_parameter_endpoints(kind):
    specs = {v['id']:v for v in P.describe(kind)['params']}
    assert specs.keys() == CONTRACT[kind].keys()
    expected = {}
    x = np.random.Generator(np.random.PCG64(72)).uniform(-.2,.2,(2048,2))
    for pid, entry in CONTRACT[kind].items():
        spec = specs[pid]
        if isinstance(entry,bool):
            assert spec['type'] == 'bool'
            values, default = [False,True], entry
        elif len(entry) == 2:
            values, default = entry
            assert spec['type'] == 'enum' and spec['choices'] == values
        else:
            lo, hi, default = entry
            assert spec['type'] == 'float' and (spec['min'],spec['max']) == (lo,hi)
            values = [lo,hi]
        expected[pid] = default
        for value in values:
            p = {**ACTIVE[kind],pid:value}
            y = render(kind,x,p,sr=96000)
            assert y.shape == x.shape and y.dtype == np.float64 and np.isfinite(y).all()
    assert P.validate_params(kind,{}) == expected
    assert np.isfinite(render(kind,x,sr=96000)).all()


@pytest.mark.parametrize('kind', TYPES)
def test_neutral_and_registration(kind):
    spec = importlib.import_module('mankomix.dspx.procs.'+kind).SPECS[0]
    assert spec['implemented'] is PUBLIC[kind]
    assert spec['master_slot'] == (3 if kind == 'transformer' else 1)
    assert spec['stages'] == ['track','bus','master']
    assert spec['backends'] == ['reference'] and spec['offline_only'] is False
    assert spec['realtime']['block_ok'] is False
    assert spec['realtime']['latency_samples'] == 0
    assert kind not in importlib.import_module('mankomix.dspx.registry').time_varying_types()
    x = np.random.Generator(np.random.PCG64(13)).normal(size=(4000,2))
    assert render(kind,x).tobytes() == x.tobytes()
    assert render(kind,x,dict(output_db=-6)).tobytes() == (x*10**(-6/20)).tobytes()
    assert render(kind,np.empty((0,2))).shape == (0,2)


@pytest.mark.parametrize('kind', TYPES)
def test_ct_1_through_8(kind):
    def probe(x,y,sr,p):
        f = H.fundamental_frequency(y,sr,low_hz=900,high_hz=1100)
        return dict(frequency_hz=f, passed=abs(f-1000) < 1)
    neutral = P.validate_params(kind,{})
    result = H.assert_common_tests(kind, params=ACTIVE[kind],neutral=neutral,
        latency_params=neutral,seconds=.07,sr_probe=probe)
    print('CT',kind,json.dumps(result,sort_keys=True,default=str))


@pytest.mark.parametrize('kind', TYPES)
def test_master_order(kind):
    E.validate_chain([{'type':kind},{'type':'limiter'}],stage='master')
    with pytest.raises(ChainError):
        E.validate_chain([{'type':'limiter'},{'type':kind}],stage='master')
    if kind in EQ:
        with pytest.raises(ChainError):
            E.validate_chain([{'type':'compressor'},{'type':kind}],stage='master')


def test_proportional_width_relationship():
    with pytest.raises(ParamError):
        P.validate_params('proportional_eq',dict(bw_min_oct=2,bw_max_oct=1))


@pytest.mark.parametrize('kind',EDGE)
def test_unmet_candidates_are_not_publicly_renderable(kind,monkeypatch):
    monkeypatch.setitem(P.PROCESSORS[kind],'implemented',False)
    with pytest.raises(ChainError,match='not implemented'):
        render(kind,np.zeros((100,1)))


@pytest.mark.parametrize('kind',EQ)
def test_zero_drive_is_linear_and_post_eq_tanh(kind):
    x = tone(db=-18, seconds=.1)
    y = render(kind,x,ACTIVE[kind])
    quiet = render(kind,x*.1,ACTIVE[kind])
    np.testing.assert_allclose(quiet,y*.1,atol=3e-12,rtol=2e-10)
    p = P.validate_params(kind,{**ACTIVE[kind], 'drive_db':9})
    sos = A.design_sos(kind,p,48000)
    g = 10**(9/20)
    expected = N.oversampled(x,2,lambda u:np.tanh(g*signal.sosfilt(sos,u,axis=0))/g)
    assert render(kind,x,p).tobytes() == expected.tobytes()
    assert not np.allclose(expected,y,atol=1e-5)


@pytest.mark.parametrize('kind',EQ)
@pytest.mark.parametrize('sr',[44100,48000,96000])
def test_measured_audio_matches_prewarped_sos(kind,sr):
    # This checks implementation vs its SOS without conflating it with the
    # separate unwarped physical-target acceptance below.
    p = P.validate_params(kind,ACTIVE[kind])
    for f in (40,1000,16000,20000):
        x = tone(f,-24,sr,seconds=1.5)
        measured = spectral(render(kind,x,p,sr),f,sr)['fundamental_dbfs']+24
        expected = db(abs(digital_response(kind,p,np.array([f]),sr)[0]))
        assert measured == pytest.approx(expected,abs=.005), (kind,sr,f,measured,expected)


@pytest.mark.parametrize('kind', ['passive_eq','inductor_eq','proportional_eq'])
@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.xfail(strict=True,reason='2x center-prewarped SOS exceeds 0.2 dB against unwarped physical H(jw) at allowed high settings')
def test_unmet_physical_analog_response(kind,sr):
    result = response_error(kind,EDGE[kind],sr)
    print('UNMET_ANALOG',kind,sr,json.dumps(result,sort_keys=True))
    assert result['error_db'] <= .2


def test_baxandall_all_switches_gains_and_slope():
    worst = dict(error_db=0)
    f = np.geomspace(20,20000,2001)
    for sr,bass,treble,bg,tg in itertools.product([44100,48000,96000],
            [74,84,130,166,230,361],[1600,2100,3400,4800,7100,18000],[-5,5],[-5,5]):
        p = P.validate_params('baxandall_eq',dict(bass_hz=bass,treble_hz=treble,bass_db=bg,treble_db=tg))
        ha = A.analog_response('baxandall_eq',p,f)
        hd = digital_response('baxandall_eq',p,f,sr)
        error = np.max(abs(20*np.log10(abs(hd/ha))))
        if error > worst['error_db']:
            worst = dict(error_db=float(error),sr=sr,bass_hz=bass,treble_hz=treble,bass_db=bg,treble_db=tg)
        assert error <= .2, worst
        slope = np.diff(20*np.log10(abs(hd)))/np.diff(np.log2(f))
        assert np.max(abs(slope)) <= 6
    print('BAXANDALL_WORST',json.dumps(worst,sort_keys=True))


def test_passive_low_boost_cut_dip():
    f = np.geomspace(10,10000,10000)
    for low,gain,sr in itertools.product([20,30,60,100],[3,6,12],[44100,48000,96000]):
        p = P.validate_params('passive_eq',dict(low_freq_hz=low,low_boost_db=gain,low_atten_db=gain))
        hd = 20*np.log10(abs(digital_response('passive_eq',p,f,sr)))
        # Refine the minimum rather than putting a strict boundary on the
        # nearest logarithmic FFT grid point (whose center is near 2*low).
        minimum = optimize.minimize_scalar(lambda hz: abs(digital_response(
            'passive_eq',p,np.array([hz]),sr)[0]),bounds=(low,10*low),method='bounded')
        where = np.argmin(hd)
        assert 2*low-low*1e-5 <= minimum.x <= 10*low
        assert hd[where] < -1 and hd[where] < hd[0] and hd[where] < hd[-1]


@pytest.mark.parametrize('sign',[-1,1])
def test_proportional_relative_3db_width_decreases(sign):
    f = np.geomspace(100,10000,40001)
    widths = []
    for gain in [4,6,9,12]:
        p = P.validate_params('proportional_eq',dict(gain_db=sign*gain))
        h = sign*20*np.log10(abs(digital_response('proportional_eq',p,f,48000)))
        selected = f[h >= gain-3]
        widths.append(float(np.log2(selected[-1]/selected[0])))
    assert np.all(np.diff(widths) < 0), widths
    print('PROPORTIONAL_WIDTH',sign,widths)


def test_os_transport_and_mix_alignment():
    pulse = np.zeros((4096,1)); pulse[1024] = 1
    for factor in [1,2,4,8]:
        wet = N.oversampled(pulse,factor,lambda u:u)
        assert np.argmax(abs(wet[:,0])) == 1024
        if factor > 1:
            h = N._os_filter(factor)
            raw = signal.upfirdn(h,signal.upfirdn(h*factor,pulse,up=factor,axis=0),down=factor,axis=0)
            assert np.argmax(abs(raw[:,0]))-1024 == N.oversampling_info(factor)['uncompensated_latency_samples']
        x = tone(db=-24,seconds=.1)
        p = dict(drive_db=12,oversample=factor)
        wet = render('transformer',x,p)
        mixed = render('transformer',x,{**p,'mix':.5})
        assert mixed.tobytes() == (.5*wet+.5*x).tobytes()


def test_transformer_flux_preference_and_odd_harmonics():
    vectors = {}
    for emphasis in [0,.7]:
        values = []
        for f in [40,1000]:
            y = render('transformer',tone(f),dict(drive_db=12,lf_emphasis=emphasis))
            v = spectral(y,f)
            vectors[f'{emphasis}/{f}'] = v
            values.append(v['thd_db'])
            assert v['harmonic_dbc'][1] > v['harmonic_dbc'][0]
            assert v['dc_dbfs'] <= -80
        assert values[0]-values[1] >= 12 if emphasis else abs(values[0]-values[1]) <= 1
    print('FLUX_PREFERENCE',json.dumps(vectors,sort_keys=True))


@pytest.mark.parametrize('sr',[44100,48000,96000])
def test_transformer_small_signal_corner_and_flat_mid(sr):
    records = []
    for corner in [5,20,80]:
        # Exact coherent frequency bins and sufficiently long settling at 5 Hz.
        for f in [corner,1000,5000]:
            x = tone(f,-60,sr,seconds=3)
            y = render('transformer',x,dict(drive_db=12,lf_corner_hz=corner),sr)
            # 1-second window: integer Hz, start after a whole second.
            sample = y[sr:2*sr,0]
            amplitude = 2*abs(np.dot(sample,np.exp(-2j*np.pi*f*np.arange(sr)/sr)))/sr
            gain = db(amplitude)+60
            assert gain == pytest.approx(-3.01029995664 if f == corner else 0,abs=.5 if f == corner else .05)
            records.append(dict(corner_hz=corner,frequency_hz=f,gain_db=gain))
    print('SMALL_SIGNAL',sr,json.dumps(records,sort_keys=True))


def test_transformer_nt2_nt3_nt4_nt5_and_bounds():
    records = []
    for drive in [0,6,12,18,24]:
        p = dict(drive_db=drive)
        v = spectral(render('transformer',tone(),p))
        aliases = {str(f):spectral(render('transformer',tone(f),p),f)['alias_dbc'] for f in [5000,10000,15000]}
        assert max(aliases.values()) <= -80
        small = spectral(render('transformer',tone(db=-60),p))['fundamental_dbfs']+60
        assert abs(small) <= .05
        records.append(dict(drive_db=drive,**v,alias_dbc_by_hz=aliases,small_signal_gain_db=small))
    for core,drive,factor in itertools.product([0,.5,1],[6,24],[1,2,4,8]):
        p = dict(drive_db=drive,core=core,oversample=factor)
        y = render('transformer',tone(50,0),p)
        assert np.max(abs(y)) < 2
        assert spectral(y,50)['dc_dbfs'] <= -80
        assert np.count_nonzero(render('transformer',np.zeros((4096,2)),p)) == 0
    print('NT_VECTOR',json.dumps(records,sort_keys=True))


def test_transformer_resonance_disable_auto_gain_and_flux_safety():
    x = tone(db=-60,sr=96000)
    for sr in [44100,48000,96000]:
        p = P.validate_params('transformer',dict(drive_db=12,hf_resonance_db=6))
        _,_,stats = importlib.import_module('mankomix.dspx.procs.transformer').transformer(x,sr,p)
        assert stats['hf_resonance_applied'] is (30000 < .45*sr)
    base = render('transformer',x,dict(drive_db=12),sr=96000)
    auto = render('transformer',x,dict(drive_db=12,auto_gain=True,output_db=3),sr=96000)
    assert auto.tobytes() == (base*10**(-9/20)).tobytes()
    for bad in [dict(drive_db=-1),dict(lf_corner_hz=0),dict(core=2),dict(lf_emphasis=np.nan)]:
        with pytest.raises(ParamError):
            N.transformer_flux(x,48000,**(dict(drive_db=12)|bad))
    assert N.transformer_flux(np.empty((0,2)),48000,12).shape == (0,2)
