"""W3h: TV freeze conservation and independently checked crossed tank."""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
from scipy import signal
from scipy.fft import rfft, rfftfreq

from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import reverb as R
from mankomix.dspx.bb.vintage import VintageTank
from tests import toolimpl_harness as H


KINDS = ("reverb_freeze", "reverb_vintage")
METRICS = {}


@pytest.fixture(scope="module", autouse=True)
def save_measurements():
    yield
    path = Path("_private/tool_impl/logs/C9a_w3h_measurements.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(METRICS, ensure_ascii=False, indent=2, sort_keys=True,
                               default=lambda v: v.item() if hasattr(v, "item") else str(v))+"\n",
                    encoding="utf-8", newline="\n")


def render(kind, x, sr=8000, *, seed=17, item="room", **p):
    return E.render_chain(x, sr, [dict(id=item, type=kind, params=p)], stage="bus", seed=seed).audio


def defaults(kind, **p):
    return P.validate_params(kind, p)


def core(kind, sr, p, x, seed=17):
    cls = R.FreezeFDN if kind == "reverb_freeze" else VintageTank
    return cls(sr, defaults(kind, **p), seed=seed).process(x)


@pytest.mark.parametrize("kind", KINDS)
def test_registration(kind):
    d = P.describe(kind)
    assert d["stages"] == ["track", "bus"] and d["master_slot"] is None
    assert d["backends"] == ["reference"] and not d["channel_ok"]
    assert d["realtime"] == dict(block_ok=False, latency_samples=0, allocates=True)
    from mankomix.dspx.registry import time_varying_types
    assert kind in time_varying_types()


@pytest.mark.parametrize("kind", KINDS)
def test_accepted_types_are_publicly_enabled(kind):
    from importlib import import_module
    module = import_module("mankomix.dspx.procs."+kind)
    assert module.SPECS[0]["implemented"] is True
    assert P.describe(kind)["implemented"]


@pytest.mark.parametrize("kind", KINDS)
def test_tempo_relationship(kind):
    with pytest.raises(ParamError,match="bpm"):
        defaults(kind,bpm=19)


@pytest.mark.parametrize("kind", KINDS)
def test_r10_stats(kind):
    x=np.zeros((1200,2));x[0]=1
    rendered=E.render_chain(x,4000,[dict(id="r10",type=kind,params=dict(rt60_s=.3,mix=1,bpm=120))],
                            stage="bus",seed=3)
    stats=rendered.steps[0]["stats"]
    for key in ("rt60_measured_s","er_late_measured_db","dr_db_white","mono","wet_energy_db",
                "measurement_modulation_stopped","ir_samples","rt60_note","predelay_note"):
        assert key in stats
    assert stats["measurement_modulation_stopped"] and stats["execution"] == "tv"
    if kind.endswith("freeze"): assert stats["measurement_freeze_disabled"]
    else: assert stats["measurement_quantization_disabled"]


@pytest.mark.parametrize("kind", KINDS)
def test_defaults_and_all_numeric_endpoints(kind):
    expected_rv = dict(rt60_s=4 if kind.endswith("freeze") else 2.5, predelay_ms=20,
                       mix=.2, lowcut_hz=300, highcut_hz=8000, bpm=0, seed=0,
                       duck_db=0, duck_threshold_db=-40, duck_attack_ms=10, duck_release_ms=250)
    extra = (dict(freeze_start_s=[],freeze_end_s=[],freeze_fade_ms=50,freeze_input="mute",
                  size_m=30,diffusion=.8,damping_hz=8000,mod_depth=0) if kind.endswith("freeze") else
             dict(input_diffusion=.75,tank_diffusion=.6,damping_hz=6000,bass_mult=1.2,
                  mod_depth=.3,mod_rate_hz=1,bandwidth_hz=10000,bits="0"))
    assert defaults(kind) == dict(expected_rv, **extra)
    ranges=dict(rt60_s=(.3,60 if kind.endswith("freeze") else 20),predelay_ms=(0,250),
                mix=(0,1),lowcut_hz=(20,2000),highcut_hz=(1000,20000),bpm=(0,400),seed=(0,65535),
                duck_db=(0,24),duck_threshold_db=(-80,0),duck_attack_ms=(.1,200),duck_release_ms=(5,3000))
    ranges.update(dict(freeze_fade_ms=(5,2000),size_m=(3,60),diffusion=(0,1),
                       damping_hz=(1000,20000),mod_depth=(0,1)) if kind.endswith("freeze") else
                  dict(input_diffusion=(0,1),tank_diffusion=(0,1),damping_hz=(1000,20000),
                       bass_mult=(.5,2),mod_depth=(0,1),mod_rate_hz=(.1,3),bandwidth_hz=(4000,20000)))
    declared={s["id"]:(s["min"],s["max"]) for s in P.describe(kind)["params"] if s["type"] in ("float","int")}
    assert declared == ranges
    sr=8000; x=H.white_noise(-12,sr=sr,seconds=.1,channels=2,seed=3)
    cases=[{}]
    for spec in P.describe(kind)["params"]:
        if spec["type"] in ("float", "int"):
            cases += [{spec["id"]:spec[key]} for key in ("min","max")]
        if spec["type"] == "enum":
            cases += [{spec["id"]:value} for value in spec["choices"]]
    for case in cases:
        if kind.endswith("freeze") and case.get("rt60_s", 0) > 24:
            with pytest.raises(ParamError):
                defaults(kind, **case)
            case = dict(rt60_s=24)
        p=defaults(kind,**case)
        # Endpoint test uses the kernel plus full wet filters/SD/mix; long
        # diagnostic IRs are separately checked, without rebuilding one per knob.
        wet=core(kind,sr,p,x)
        wet=R._tv_wet_shape(x,wet,sr,p)
        y,_,_=R.finish(x,wet,sr,p,{})
        assert y.shape == x.shape and y.dtype == np.float64 and np.isfinite(y).all(), case
    METRICS[kind+"_endpoint_cases"]=len(cases)


@pytest.mark.parametrize("bad", [
    dict(freeze_start_s=[1],freeze_end_s=[]),
    dict(freeze_start_s=[1],freeze_end_s=[1]),
    dict(freeze_start_s=[2,1],freeze_end_s=[3,4]),
    dict(freeze_start_s=[1,2],freeze_end_s=[2.5,3]),
    dict(freeze_start_s=[1,2],freeze_end_s=[2,3]),
    dict(freeze_start_s=[0]*17,freeze_end_s=[1]*17),
    dict(freeze_start_s=[-1],freeze_end_s=[1]),
])
def test_freeze_arrays_rejected(bad):
    with pytest.raises(ParamError):
        defaults("reverb_freeze",**bad)


def test_freeze_sixteen_intervals_and_sample_grid():
    starts=np.arange(16).tolist(); ends=(np.arange(16)+.5).tolist()
    p=defaults("reverb_freeze",freeze_start_s=starts,freeze_end_s=ends)
    assert p["freeze_start_s"] == starts
    envelope=R.freeze_envelope(0,8000,8000,p)
    assert envelope[0] == 0 and envelope[400] == 1 and envelope[4400] == 0
    p=defaults("reverb_freeze",freeze_start_s=[0],freeze_end_s=[.00001])
    with pytest.raises(ParamError,match="sample grid"):
        R.FreezeFDN(4000,p).process(np.zeros((100,2)))


@pytest.mark.parametrize("kind", KINDS)
def test_engine_seed_replay_excerpt_and_bypass(kind):
    sr=8000; x=H.white_noise(-12,sr=sr,seconds=.4,channels=2,seed=3)
    p=dict(rt60_s=.5,mix=1)
    if kind.endswith("freeze"):
        p.update(freeze_start_s=[.1],freeze_end_s=[.3])
    a=render(kind,x,sr,**p); b=render(kind,x,sr,**p)
    assert a.tobytes() == b.tobytes()
    assert a.tobytes() != render(kind,x,sr,seed=18,**p).tobytes()
    assert a.tobytes() != render(kind,x,sr,item="other",**p).tobytes()
    assert a.tobytes() != render(kind,x,sr,**dict(p,seed=1)).tobytes()
    assert x.tobytes() == render(kind,x,sr,mix=0).tobytes()
    excerpt=H.render_excerpt(kind,x,sr,800,len(x),p,stage="bus",seed=17)
    whole=H.render(kind,x,sr,p,stage="bus",seed=17).audio
    assert whole[800:].tobytes() == excerpt.tobytes()


@pytest.mark.parametrize("kind", KINDS)
def test_common_ct_1_to_8(kind):
    def probe(x,y,sr,p):
        hz=H.fundamental_frequency(y,sr,low_hz=900,high_hz=1100)
        return dict(frequency_hz=hz,passed=abs(hz-1000)<2)
    result=H.assert_common_tests(kind,params=dict(rt60_s=.3,predelay_ms=0),
        neutral=dict(mix=0),seconds=.1,feedback=False,sr_probe=probe,
        srs=(44100,48000,96000),latency_params=dict(mix=0))
    METRICS[kind+"_common"]=result


@pytest.mark.parametrize("kind", KINDS)
def test_ct8_default_and_finite_hold(kind):
    sr=4000; x=np.zeros((61*sr,2))
    x[:sr]=np.random.Generator(np.random.PCG64(7)).choice([-1.,1.],(sr,2))
    p=dict(mix=1)
    if kind.endswith("freeze"):
        p.update(freeze_start_s=[.7],freeze_end_s=[11])
    y=render(kind,x,sr,**p)
    peak=H.peak_dbfs(y[-sr:]); METRICS[kind+"_default_ct8_peak_dbfs"]=peak
    assert np.isfinite(y).all() and peak < -120


@pytest.mark.parametrize("kind", KINDS)
def test_ct8_maximum_declared_decay(kind):
    sr=4000; x=np.zeros((61*sr,2))
    x[:sr]=np.random.Generator(np.random.PCG64(7)).choice([-1.,1.],(sr,2))
    rt=24 if kind.endswith("freeze") else 12
    p=dict(rt60_s=rt,mix=1,lowcut_hz=20,highcut_hz=20000,mod_depth=0)
    if kind.endswith("vintage"): p.update(bass_mult=2)
    else: p.update(size_m=60)
    y=core(kind,sr,p,x)
    peak=H.peak_dbfs(y[-sr:]); METRICS[kind+"_maximum_ct8_peak_dbfs"]=peak
    assert peak < -120


def test_freeze_empty_is_normal_and_block_state_conserves():
    sr=4000; p=defaults("reverb_freeze",freeze_start_s=[.2],freeze_end_s=[1.4],
                        rt60_s=2,freeze_fade_ms=50)
    x=np.zeros((round(1.5*sr),2));x[0]=1
    a=R.FreezeFDN(sr,p,seed=1); full=a.process(x)
    b=R.FreezeFDN(sr,p,seed=1)
    parts=[]; energies=[]
    for i in range(0,len(x),64):
        parts.append(b.process(x[i:i+64]))
        if .3*sr < i < 1.3*sr: energies.append(b.state_energy())
    assert full.tobytes() == np.concatenate(parts).tobytes()
    c=R.FreezeFDN(sr,p,seed=1)
    blocks=[c.process(x[i:i+1024]) for i in range(0,len(x),1024)]
    assert full.tobytes() == np.concatenate(blocks).tobytes()
    drift=10*np.log10(max(energies)/min(energies))
    METRICS["freeze_state_energy_drift_db"]=drift
    assert drift <= .1
    p0=defaults("reverb_freeze",rt60_s=1)
    ordinary=R.FreezeFDN(sr,p0,seed=1).process(x[:sr])
    future=R.FreezeFDN(sr,dict(p0,freeze_start_s=[20],freeze_end_s=[30]),seed=1).process(x[:sr])
    assert ordinary.tobytes() == future.tobytes()


@lru_cache(maxsize=1)
def freeze_metrics():
    sr=8000; x=np.zeros((15*sr,2));x[0]=1
    y=render("reverb_freeze",x,sr,mix=1,lowcut_hz=20,highcut_hz=20000,
             freeze_start_s=[.5],freeze_end_s=[11],rt60_s=2,freeze_fade_ms=50)
    windows=[y[i*sr:(i+1)*sr] for i in range(1,11)]
    levels=[H.rms_dbfs(v) for v in windows]
    centroids=[]
    for v in windows:
        power=np.sum(abs(rfft(v,axis=0,workers=1))**2,axis=1)
        centroids.append(float(np.sum(power*rfftfreq(len(v),1/sr))/np.sum(power)))
    result=dict(energy_range_db=max(levels)-min(levels),
                centroid_range_ratio=max(centroids)/min(centroids)-1,
                released_rt60_s=H.rt60(y[round(11.15*sr):],sr))
    METRICS["freeze_output"]=result
    return result


def test_freeze_ten_second_output_energy_and_centroid():
    values=freeze_metrics()
    assert values["energy_range_db"] <= .1 and values["centroid_range_ratio"] <= .01


def test_freeze_release_rt60():
    values=freeze_metrics()
    assert abs(values["released_rt60_s"]/2-1) <= .15


def test_freeze_input_mute_and_pass():
    sr=8000; x=np.zeros((2*sr,2)); x[sr:sr+100]=.5
    p=dict(mix=1,freeze_start_s=[.2],freeze_end_s=[1.8],freeze_fade_ms=50,rt60_s=.5)
    assert np.max(abs(render("reverb_freeze",x,sr,**p))) == 0
    assert np.max(abs(render("reverb_freeze",x,sr,**dict(p,freeze_input="pass")))) > 0


def test_subtractive_tpdf_snr_and_gate():
    bits=12; t=np.arange(128000)/32000; x=np.sin(2*np.pi*997*t)
    y=R.quantize_tpdf(x,bits,np.random.Generator(np.random.PCG64(17)))
    snr=H.rms_dbfs(x)-H.rms_dbfs(y-x)
    METRICS["quantizer_12bit_snr_db"]=snr
    assert abs(snr-(6.02*bits+1.76)) <= 3
    assert np.array_equal(R.quantize_tpdf(np.zeros(500),bits,np.random.Generator(np.random.PCG64(1))),np.zeros(500))
    z=render("reverb_vintage",np.zeros((4000,2)),4000,bits="12",rt60_s=.3)
    assert np.max(abs(z)) == 0


def test_vintage_bandwidth_octave_attenuation():
    sr=48000; x=H.white_noise(-12,sr=sr,seconds=2,channels=2,seed=3)
    p=dict(bandwidth_hz=4000,highcut_hz=20000,lowcut_hz=20,mod_depth=0,rt60_s=.5)
    a=core("reverb_vintage",sr,p,x)
    b=core("reverb_vintage",sr,dict(p,bandwidth_hz=20000),x)
    loss=H.band_level(a,sr,7500,8500)["dbfs"]-H.band_level(b,sr,7500,8500)["dbfs"]
    METRICS["vintage_bandwidth_octave_loss_db"]=loss
    assert loss <= -24


def test_vintage_reference_graph_ir():
    # Independent whole-array evaluation of the published graph. Each outer
    # iteration propagates one more causal branch traversal. No tank class,
    # delay-line or allpass helper is used by this reference calculation.
    sr=4000; n=3200; p=defaults("reverb_vintage",mod_depth=0,bass_mult=1,rt60_s=.7,
                              bandwidth_hz=20000,damping_hz=20000)
    length=lambda d: max(1,round(d*sr/29761*min(1., p["rt60_s"]/1.5)))
    def delay(v,d):
        out=np.zeros(n)
        if d<n: out[d:]=v[:n-d]*np.exp(-np.log(1000)*d/(sr*p["rt60_s"]))
        return out
    def ap(v,d,g):
        a=np.zeros(d+1);a[0]=1;a[-1]=-g*np.exp(-np.log(1000)*d/(sr*p["rt60_s"]))
        z=signal.lfilter([1.],a,v)
        return -g*v+(1-g*g)*delay(z,d),z
    pulse=np.zeros(n);pulse[0]=1
    # Full bandwidth and flat absorption: every delayed edge, including
    # lattice memory taps, is independently weighted by r**delay.
    mono=pulse
    for d,g in zip((142,107,379,277),(-.75,-.75,-.625,-.625)):
        mono,_=ap(mono,length(d),g)
    gain=1.
    feedback=[np.zeros(n),np.zeros(n)];nodes=[]
    for _ in range(1+n//min(length(4453)+length(3720),length(4217)+length(3163))):
        nodes=[];new=[]
        for j,(d1,d2,d3,d4) in enumerate(((672,4453,1800,3720),(908,4217,2656,3163))):
            first,_=ap(mono+gain*feedback[1-j],length(d1),.7)
            damp=delay(first,length(d2))*gain
            second,internal=ap(damp,length(d3),-.5)
            new.append(delay(second,length(d4)))
            nodes.append((first,internal,second))
        feedback=new
    taps=(((1,0,266,1),(1,0,2974,1),(1,1,1913,-1),(1,2,1996,1),
           (0,0,1990,-1),(0,1,187,-1),(0,2,1066,-1)),
          ((0,0,353,1),(0,0,3627,1),(0,1,1228,-1),(0,2,2673,1),
           (1,0,2111,-1),(1,1,335,-1),(1,2,121,-1)))
    expected=np.zeros((n,2))
    for c in range(2):
        for branch,location,offset,sign in taps[c]:
            expected[:,c]+=.6*sign*delay(nodes[branch][location],length(offset))
    actual=VintageTank(sr,p,seed=0).process(np.repeat(pulse[:,None],2,axis=1))
    measured=H.null(expected,actual)
    METRICS["vintage_reference_null"]=measured
    assert measured["rms_dbfs"] <= -100


@pytest.mark.parametrize("bits",["0","12"])
def test_vintage_stateful_block_invariance(bits):
    sr=8000; x=H.white_noise(-12,sr=sr,seconds=.25,channels=2,seed=2)
    p=defaults("reverb_vintage",bits=bits)
    full=VintageTank(sr,p,seed=3).process(x)
    for size in (64,1024):
        tank=VintageTank(sr,p,seed=3)
        y=np.concatenate([tank.process(x[a:a+size]) for a in range(0,len(x),size)])
        assert full.tobytes() == y.tobytes()


@pytest.mark.parametrize("kind", KINDS)
def test_modulated_tail_pitch(kind):
    sr=16000; x=np.zeros((3*sr,2))
    x[:sr]=np.sin(2*np.pi*1000*np.arange(sr)/sr)[:,None]*.2
    p=dict(rt60_s=2,mod_depth=1)
    if kind.endswith("vintage"): p.update(mod_rate_hz=3)
    y=core(kind,sr,p,x)
    hz=H.fundamental_frequency(y[round(1.1*sr):round(1.8*sr)],sr,low_hz=950,high_hz=1050)
    cents=1200*np.log2(hz/1000)
    METRICS[kind+"_modulated_tail_cents"]=cents
    assert abs(cents) <= 15


def test_vintage_processor_quantization_noise_floor():
    sr=16000; x=np.sin(2*np.pi*997*np.arange(3*sr)/sr)[:,None]
    x=np.repeat(x,2,axis=1)
    p=dict(rt60_s=.5,mod_depth=0,bandwidth_hz=20000,damping_hz=20000,bass_mult=1)
    a=core("reverb_vintage",sr,dict(p,bits="0"),x)[sr:]
    b=core("reverb_vintage",sr,dict(p,bits="12"),x)[sr:]
    # 6.02*B+1.76 is relative to a unit-peak full-scale sine (RMS=-3.01
    # dBFS), not the tank's frequency-dependent output level. Compare the
    # measured added-noise floor to that theoretical full-scale reference.
    floor=H.rms_dbfs(b-a)
    reference=H.rms_dbfs(x[sr:])
    METRICS["vintage_processor_12bit_noise"]=dict(noise_dbfs=floor,
        input_referred_snr_db=reference-floor,output_snr_db=H.rms_dbfs(a)-floor,
        theoretical_floor_dbfs=reference-(6.02*12+1.76))
    assert abs((reference-floor)-(6.02*12+1.76)) <= 3


@pytest.mark.parametrize("kind", KINDS)
def test_seed_rt60_and_stereo_correlation(kind):
    sr=12000; x=np.zeros((3*sr,2));x[0]=1
    p=dict(rt60_s=.6,mod_depth=0 if kind.endswith("freeze") else .3,lowcut_hz=20,highcut_hz=20000)
    a=render(kind,x,sr,seed=17,mix=1,**p); b=render(kind,x,sr,seed=18,mix=1,**p)
    ta,tb=H.rt60(a,sr),H.rt60(b,sr)
    rho=H.late_correlation(a,sr,start_s=.1,end_s=1)
    METRICS[kind+"_seed_rt60"]=dict(a=ta,b=tb,rho=rho)
    assert a.tobytes() != b.tobytes()
    assert abs(ta/tb-1) <= .05
    assert abs(rho) <= .3


def test_vintage_unmodulated_seed_ir():
    sr=8000; x=np.zeros((sr,2));x[0]=1
    p=dict(rt60_s=.5,mod_depth=0,mix=1)
    a=render("reverb_vintage",x,sr,seed=17,**p)
    b=render("reverb_vintage",x,sr,seed=18,**p)
    METRICS["vintage_unmodulated_seed_ir_identical"]=a.tobytes() == b.tobytes()
    assert a.tobytes() != b.tobytes()


@pytest.mark.parametrize("kind", ["reverb_vintage"])
def test_band_rt60_default(kind):
    sr=24000; p=defaults(kind,mod_depth=0)
    x=np.zeros((round(7*sr),2));x[0]=1
    y=core(kind,sr,p,x)
    times=H.octave_rt60(y,sr,centers_hz=(125,1000,8000))
    targets={125:p["rt60_s"]*p.get("bass_mult",1),1000:p["rt60_s"],8000:p["rt60_s"]}
    METRICS[kind+"_band_rt60"]=dict(measured=times,targets=targets)
    for band in targets:
        assert times[band] is not None and abs(times[band]/targets[band]-1) <= .15
