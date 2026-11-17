"""W2b: BB-10, SD, hall/chamber, nonlinear/keyed gate and reverse."""
import math
import numpy as np
import pytest
from scipy import signal, fft

from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import reverb as R
from mankomix.dspx.bb.selfduck import SelfDuck, duck_wet, sd_params
from mankomix.dspx.procs import reverb_gated as G, reverb_reverse as V
from tests import toolimpl_harness as H

TYPES = ("reverb_hall", "reverb_chamber", "reverb_gated", "reverb_reverse")


@pytest.fixture(autouse=True)
def enable_candidates(monkeypatch):
    # Availability is assessed separately from numerical implementation tests.
    for kind in TYPES:
        monkeypatch.setitem(P.PROCESSORS[kind], "implemented", True)


def params(kind, **p):
    return P.validate_params(kind, p)


def run(kind, x, sr=8000, **p):
    return H.render(kind, x, sr, p)


@pytest.mark.parametrize("lines", [8, 16])
def test_orthogonal_coprime_and_analytic_absorption(lines):
    mat = R.orthogonal_matrix(lines)
    assert np.max(abs(mat.T @ mat - np.eye(lines))) < 1e-15
    ds = R.delay_lengths(48000, 25, lines, 17)
    assert all(math.gcd(int(a), int(b)) == 1 for i,a in enumerate(ds) for b in ds[i+1:])
    assert np.array_equal(ds, R.delay_lengths(48000, 25, lines, 17))
    assert not np.array_equal(ds, R.delay_lengths(48000, 25, lines, 18))
    for d in ds:
        assert abs(float(R.rt60_gain(d, 48000, 2))**(96000/d)-.001) < 1e-15
        sos = R.absorption_sos(d, 48000, (2, 2, 2))
        gain = signal.sosfreqz(sos, worN=[125, 1000, 8000], fs=48000)[1]
        assert np.max(abs(abs(gain)-R.rt60_gain(d,48000,2))) < 1e-12


@pytest.mark.parametrize("component", ["allpass", "fdn", "modulated", "tank"])
def test_stateful_core_chunk_invariance(component):
    sr = 8000
    p = params("reverb_hall", rt60_s=.3, mod_depth=.5 if component == "modulated" else 0)
    x = H.white_noise(sr=sr, seconds=.13, channels=2, seed=48)
    def make():
        if component == "allpass":
            return R.Allpass(17, .65)
        if component == "tank":
            return R.AllpassTank(sr, .3)
        return R.FDN(sr, p)
    expected = make().process(x)
    for chunk in (1, 64, 1024):
        core = make()
        got = np.concatenate([core.process(x[s:s+chunk]) for s in range(0,len(x),chunk)])
        assert got.tobytes() == expected.tobytes()
    if component == "allpass":
        h = make().process(H.impulse(sr=sr,seconds=1,channels=2))
        assert abs(np.sum(h[:,0]**2)-1) < 1e-12


@pytest.mark.parametrize("kind", TYPES)
def test_registration_defaults_and_channel_rejection(kind):
    spec = P.describe(kind)
    assert spec["stages"] == ["track", "bus"] and spec["master_slot"] is None
    assert spec["backends"] == ["reference"] and spec["realtime"]["allocates"]
    assert not spec["channel_ok"]
    p = params(kind)
    assert p == {s["id"]: s["default"] for s in spec["params"]}
    for s in sd_params():
        assert p[s["id"]] == s["default"]
    with pytest.raises((ParamError, ChainError)):
        E.validate_chain([{"type":kind,"channel":"left"}], "bus")
    with pytest.raises((ParamError, ChainError)):
        E.validate_chain([{"type":kind}], "master")
    assert "ducking_reverb" not in P.PROCESSORS


@pytest.mark.parametrize("kind", TYPES)
def test_numeric_endpoints_are_resolved_and_exercised(kind):
    spec = P.describe(kind)
    for s in spec["params"]:
        values = [s["min"],s["max"]] if s["type"] in ("float","int") else s.get("choices",[])
        for value in values:
            options = {s["id"]:value}
            if s["id"] == "note" and value != "none":
                options["bpm"] = 120
            if s["id"] == "bpm" and value == 0:
                options["note"] = "none" if "note" in params(kind) else None
                options = {k:v for k,v in options.items() if v is not None}
            if s["id"] == "low_xover_hz" and value == 1000:
                options["high_xover_hz"] = 4000
            p = params(kind, **options)
            # Probe every legal value at the actual declared rates. A short IR
            # exercises coefficients without allocating 187 s at every endpoint.
            if kind in TYPES[:2]:
                h = R.render_ir(8000,p,chamber=kind.endswith("chamber"),frames=320)
            elif kind == "reverb_gated":
                h = G.gated_ir(8000,p) if p["mode"] == "nonlin" else R.render_ir(8000,p,frames=320)
            else:
                h = V.reverse_source_ir(8000,{**p,"length_ms":100,"note":"none"}) if p["mode"] == "true" else R.velvet_ir(8000,100,p,shape="ramp_up")
            assert np.isfinite(h).all()
    assert params(kind)["rt60_s"] == {"reverb_hall":2.2,"reverb_chamber":1.8,"reverb_gated":2,"reverb_reverse":2}[kind]


@pytest.mark.parametrize("kind,chamber", [("reverb_hall",False),("reverb_chamber",True)])
def test_rt_vector_seed_density_correlation_and_ringing(kind,chamber):
    sr = 32000
    p = params(kind,rt60_s=.8,mix=1,lowcut_hz=20,highcut_hz=20000)
    h = R.render_ir(sr,p,chamber=chamber)
    pair = h.sum(axis=1)
    measurements = H.octave_rt60(pair,sr,centers_hz=(125,1000,8000))
    targets = {125:.8*p["rt60_low_mult"],1000:.8,8000:.8*p["rt60_high_mult"]}
    print(kind,"rt_vector",measurements,"targets",targets)
    for f,t in measurements.items():
        assert abs(t/targets[f]-1) <= .1
    other = R.render_ir(sr,{**p,"seed":1},chamber=chamber)
    assert not np.array_equal(h,other)
    assert np.array_equal(h,R.render_ir(sr,p,chamber=chamber))
    for f,t in measurements.items():
        assert abs(H.rt60(other.sum(axis=1),sr,band_hz=f)/t-1) <= .05
    assert abs(H.late_correlation(pair,sr,start_s=.15)) <= .3
    ring = H.ringing_spectrum(pair,sr,start_s=.15,lo_hz=125,hi_hz=8000)
    print(kind,"ringing",ring["max_adjacent_db"])
    assert ring["max_adjacent_db"] <= 6
    density = H.echo_density(pair,sr)
    limit = .03 if chamber else .15
    for c in (0,1):
        assert density["times_s"][np.flatnonzero(density["density"][:,c] >= .9)[0]] <= limit
    vector = R.measure_ir(h,sr,p)
    assert set(vector) >= {"rt60_measured_s","er_late_measured_db","dr_db_white","mono"}


def test_hall_first_reflection_and_chamber_rise_are_monotonic():
    arrivals=[]
    for size in (3,25,60):
        h = R.early_reflections(16000,16000,size,17)
        arrivals.append(np.flatnonzero(np.any(h != 0,axis=(1,2)))[0])
    assert arrivals == sorted(set(arrivals))
    rises=[]
    p=params("reverb_chamber",rt60_s=.4,predelay_ms=0,lowcut_hz=20,highcut_hz=20000)
    for distance in (0,.5,1):
        h=R.render_ir(16000,{**p,"distance":distance},chamber=True,frames=3200).sum(axis=1)
        env=H.rms_envelope(h,16000,window_ms=5).mean(axis=1)
        rises.append(int(np.argmax(env >= .5*np.max(env))))
        if distance == .5:
            early=H.rms_envelope(h[:800],16000,window_ms=5)[160:].mean(axis=1)
            assert 20*np.log10(np.max(early)/np.median(early)) <= 6
    print("chamber rise samples",rises)
    assert rises == sorted(rises) and rises[-1] > rises[0]


def test_hall_lti_tv_agreement_and_modulated_pitch():
    sr=8000
    p=params("reverb_hall",rt60_s=.3,rt60_low_mult=1,rt60_high_mult=1)
    x=H.white_noise(sr=sr,seconds=.35,channels=2,seed=71)
    a=R.process_reverb(x,sr,p,execution="lti")[0]
    b=R.process_reverb(x,sr,p,execution="tv")[0]
    assert H.null(a,b)["rms_dbfs"] <= -100
    tone=H.sine(440,sr=sr,seconds=.8,channels=2)
    y=R.process_reverb(tone,sr,{**p,"mod_depth":1,"mod_rate_hz":5,"mix":1})[0]
    f=H.fundamental_frequency(y[round(.4*sr):],sr,low_hz=400,high_hz=480)
    print("modulated cents",1200*np.log2(f/440))
    assert abs(1200*np.log2(f/440)) <= 10


@pytest.mark.parametrize("shape", ["flat","decay","ramp_up"])
def test_gated_support_and_envelope(shape):
    sr=16000
    p=params("reverb_gated",shape=shape,mix=1,lowcut_hz=20,highcut_hz=20000,predelay_ms=20)
    h=G.gated_ir(sr,p)
    x=H.impulse(sr=sr,seconds=.5,channels=2)
    y=G.reverb_gated(x,sr,p)[0]
    assert H.peak_dbfs(y[round(.28*sr):]) <= H.peak_dbfs(y)-80
    assert np.count_nonzero(h[:320]) == 0
    if shape == "flat":
        pair=h[320:].sum(axis=1)
        levels=np.array([H.rms_dbfs(pair[s:s+800]) for s in range(0,len(pair)-800+1,800)])
        print("flat RMS dB",levels.tolist())
        assert np.max(abs(levels-np.mean(levels))) <= 2
        f=fft.rfftfreq(len(pair),1/sr); power=abs(fft.rfft(pair,axis=0,workers=1))**2
        levels=[]
        for center in 1000*2.**(np.arange(-3,7)/3):
            mask=(f>=center/2**(1/6))&(f<center*2**(1/6))
            levels.append(10*np.log10(power[mask].mean()))
        print("flat spectral dB",levels)
        assert np.max(abs(levels-np.mean(levels))) <= 3


def test_keyed_hold_and_release_time():
    from mankomix.dspx.bb.dynamics import gate_gain
    sr=8000; x=np.zeros((sr,1)); x[:800]=.5
    gp=dict(threshold_db=-30,hold_ms=150,release_ms=30,attack_ms=.1,ratio=100,range_db=-120,knee_db=0,hysteresis_db=0,stereo_link=True)
    gain, states=gate_gain(x,sr,gp)
    closed=np.flatnonzero(states[:,0] == 0)[0]
    assert abs((closed-800)/sr-.15) <= 1/sr
    measured=H.step_response_time(-gain[:,0],sr,closed,0,120)["time_s"]
    assert abs(measured/.03-1) <= .1
    p=params("reverb_gated",mode="keyed",rt60_s=.3)
    burst=H.drum("snare",sr=sr,seconds=.5,channels=2)
    assert np.isfinite(G.reverb_gated(burst,sr,p)[0]).all()


@pytest.mark.parametrize("mode", ["envelope","true"])
def test_reverse_support_rms_spectrum_and_discard(mode):
    sr=8000; t0=sr
    p=params("reverb_reverse",mode=mode,length_ms=800,gap_ms=25,mix=1,lowcut_hz=20,highcut_hz=20000)
    x=np.zeros((2*sr,2));x[t0]=1
    y,_,stats=V.reverb_reverse(x,sr,p)
    if mode == "true":
        start,end=t0-6400-200,t0-200
        assert H.peak_dbfs(y[:start]) < -200 and H.peak_dbfs(y[end+1:]) < -200
        segment=y[start+1:end+1]
        levels=[H.rms_dbfs(segment[s:s+400]) for s in range(0,len(segment),400)]
        print("reverse 50ms RMS",levels)
        assert np.min(np.diff(levels)) >= -2
        forward=V.reverse_source_ir(sr,p).sum(axis=1)
        assert np.max(abs(abs(fft.rfft(segment,axis=0,workers=1))-abs(fft.rfft(forward,axis=0,workers=1)))) < 1e-10
        early=V.reverb_reverse(x[t0:],sr,p)[2]
        assert early["discarded_before_start_energy"] > 0
    else:
        assert H.peak_dbfs(y[:t0]) < -200 and H.peak_dbfs(y[t0+6400:]) < -200
    assert stats["noncausal"] == (mode == "true")


def test_sd_bursts_recovery_disabled_and_chunk_invariance():
    sr=8000; dry=np.zeros((3*sr,2)); t=np.arange(sr//2)/sr
    for start in (0,sr,2*sr):
        dry[start:start+sr//2]=(.2*np.sin(2*np.pi*440*t))[:,None]
    wet=np.ones((len(dry),2))*.1
    p={"duck_db":12,"duck_attack_ms":10,"duck_release_ms":50,"duck_threshold_db":-40}
    y=duck_wet(dry,wet,sr,p)
    for start in (0,sr,2*sr):
        delta=H.rms_dbfs(y[start+1600:start+3200])-H.rms_dbfs(wet[start+1600:start+3200])
        assert abs(delta+12) <= 1
        assert abs(20*np.log10(y[start+5200,0]/wet[start+5200,0])) <= 1
    assert duck_wet(dry,wet,sr,{"duck_db":0}) is wet
    for chunk in (64,1024):
        state=SelfDuck(sr,p)
        pieces=[state.process(dry[s:s+chunk],wet[s:s+chunk]) for s in range(0,len(dry),chunk)]
        assert np.concatenate(pieces).tobytes() == y.tobytes()


@pytest.mark.parametrize("kind", TYPES)
def test_all_types_sd_zero_and_only_wet_changes(kind):
    p=params(kind,rt60_s=.3,mix=.4)
    x=np.ones((4000,2))*.1
    from mankomix.dspx.registry import implementations
    fn=implementations()[kind]
    a=fn(x,8000,p)[0]
    assert a.tobytes() == fn(x,8000,{**p,"duck_db":0})[0].tobytes()
    b=fn(x,8000,{**p,"duck_db":12,"duck_attack_ms":.1})[0]
    expected=.6*x+(a-.6*x)*10**(-12/20)
    assert H.null(b[1600:],expected[1600:])["rms_dbfs"] <= -100


@pytest.mark.parametrize("kind", TYPES)
def test_common_ct1_through_ct8(kind):
    p={"rt60_s":.3,"lowcut_hz":20,"highcut_hz":20000}
    rates = {}
    def probe(x,y,sr,p):
        # Independent active impulse support/predelay in seconds at every rate.
        pulse=H.impulse(sr=sr,seconds=.12,channels=x.shape[1])
        r=run(kind,pulse,sr,**{**p,"mix":1}).audio
        first=int(np.flatnonzero(np.any(abs(r)>1e-10,axis=1))[0])
        expected=round(p.get("predelay_ms",0)*sr/1000)
        upper=expected+round(.06*sr)
        good = expected <= first <= upper
        measurement = {"first_sample":first,"predelay_samples":expected}
        if kind in TYPES[:2]:
            if sr not in rates:
                h=R.render_ir(sr,p,chamber=kind.endswith("chamber")).sum(axis=1)
                rates[sr]=H.rt60(h,sr,band_hz=1000)
            measurement["t20_1000_s"] = rates[sr]
            good = good and abs(rates[sr]/p["rt60_s"]-1) <= .1
        measurement["passed"] = good
        return measurement
    H.assert_common_tests(kind,params=p,neutral={"mix":0},latency_params={"mix":0},
        sr_probe=probe,seconds=.08,srs=(44100,48000,96000),feedback=False,
        invalid_params=[{"bpm":1}])


@pytest.mark.parametrize("kind", TYPES[:2])
def test_full_scale_feedback_60s_default_decay(kind):
    # Full CT-8 with the same state/context; lower sr keeps the suite bounded.
    H.assert_common_tests(kind,params={"rt60_s":.3,"lowcut_hz":20,"highcut_hz":20000},
        neutral={"mix":0},latency_params={"mix":0},seconds=.025,srs=(4000,),
        stages=("bus",),feedback=True,
        sr_probe=lambda x,y,sr,p: {"passed":np.isfinite(y).all(),"active_t20_s":H.rt60(R.render_ir(sr,p,chamber=kind.endswith("chamber")).sum(axis=1),sr,band_hz=500)})


@pytest.mark.parametrize("kind,rt", [("reverb_hall",20),("reverb_chamber",8)])
@pytest.mark.xfail(strict=True, reason="Legal maximum RT60 multipliers fail the 60 s / -120 dBFS CT-8 condition")
def test_maximum_decay_ct8_blocker(kind,rt):
    sr=4000
    p=params(kind,rt60_s=rt,rt60_low_mult=4,rt60_high_mult=4,lowcut_hz=20,highcut_hz=20000,mix=1)
    x=np.zeros((61*sr,2))
    x[:sr]=np.random.Generator(np.random.PCG64(15)).choice([-1.,1.],(sr,2))
    y=R.FDN(sr,p,chamber=kind.endswith("chamber")).process(x,offline_diffusion=True)
    tail=H.peak_dbfs(y[-sr:])
    print(kind,"maximum decay CT8 core tail dBFS",tail)
    assert np.isfinite(y).all() and tail < -120


@pytest.mark.parametrize("kind,mode", [("reverb_gated","nonlin"),("reverb_gated","keyed"),
                                      ("reverb_reverse","envelope"),("reverb_reverse","true")])
def test_finite_types_seed_width_and_common_modes(kind,mode):
    from mankomix.dspx.registry import implementations
    sr=8000; x=H.impulse(at_s=.5,sr=sr,seconds=1.6,channels=2)
    p=params(kind,mode=mode,rt60_s=.3,mix=1)
    fn=implementations()[kind]
    a=fn(x,sr,p)[0]; b=fn(x,sr,p)[0]; c=fn(x,sr,{**p,"seed":1})[0]
    assert a.tobytes() == b.tobytes() and a.tobytes() != c.tobytes()
    mono=fn(x,sr,{**p,"width":0})[0]
    assert mono[:,0].tobytes() == mono[:,1].tobytes()
    # In reverse mode the underlying forward decay is the RT reference.
    if kind == "reverb_reverse" and mode == "true":
        a=V.reverse_source_ir(sr,p).sum(axis=1)
        c=V.reverse_source_ir(sr,{**p,"seed":1}).sum(axis=1)
    assert abs(H.rt60(a,sr)/H.rt60(c,sr)-1) <= .05


def test_note_sync_and_reject_missing_tempo():
    for kind in TYPES[2:]:
        with pytest.raises(ParamError):
            params(kind,note="1/4")
        p=params(kind,note="1/4",bpm=120)
        if kind == "reverb_gated":
            h=G.gated_ir(8000,p)
            assert len(h) == 4000+160
        else:
            h=V.reverse_source_ir(8000,p)
            assert len(h) == 4000


def test_sd_valid_endpoints_process_and_silent_key():
    x=np.full((1600,2),.1); wet=x.copy()
    for s in sd_params():
        for v in (s["min"],s["max"]):
            p={"duck_db":12,s["id"]:v}
            assert np.isfinite(duck_wet(x,wet,8000,p)).all()
    assert np.array_equal(duck_wet(np.zeros_like(x),wet,8000,{"duck_db":24}),wet)


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.xfail(strict=True, reason="The engine passes project seed only; the processor call has no chain item ID")
def test_chain_item_id_participates_in_random_seed(kind):
    x=H.impulse(sr=8000,seconds=.2,channels=2)
    p={"mix":1,"rt60_s":.3}
    a=E.render_chain(x,8000,[{"id":"room_a","type":kind,"params":p}],stage="bus",seed=81).audio
    b=E.render_chain(x,8000,[{"id":"room_b","type":kind,"params":p}],stage="bus",seed=81).audio
    assert a.tobytes() != b.tobytes()
