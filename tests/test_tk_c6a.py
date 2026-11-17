"""C6a closure: high-frequency corners, absolute delays and output ballistics."""
import itertools
import json
import numpy as np
import pytest
from scipy import signal
from mankomix.dsp import processors as P
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import analog_eq as A, nonlinear as N
from mankomix.dspx.procs.phase_enhancer import delay_sos
from mankomix.dspx.bb.lowend import amplitude_envelope
from tests.test_tk_w2a3 import tone, render


def eq_cases(kind):
    if kind == 'passive_eq':
        for hz, gain, bw, atten_hz, atten in itertools.product(
                [3000,4000,5000,8000,10000,12000,16000], [0,18], [0,1],
                [5000,10000,20000], [0,16]):
            yield dict(high_freq_hz=hz, high_boost_db=gain, high_bw=bw,
                       high_atten_freq_hz=atten_hz, high_atten_db=atten,
                       low_freq_hz=100, low_boost_db=14, low_atten_db=18)
        for hz, boost, cut in itertools.product([20,30,60,100], [0,14], [0,18]):
            yield dict(low_freq_hz=hz, low_boost_db=boost, low_atten_db=cut)
    elif kind == 'inductor_eq':
        for hz, mid, high in itertools.product([360,700,1600,3200,4800,7200], [-18,18], [-16,16]):
            yield dict(mid_freq_hz=hz, mid_db=mid, high_db=high, low_db=16, hpf_hz=300)
        for hp, hz, low in itertools.product([0,50,80,160,300], [35,60,110,220], [-16,16]):
            yield dict(hpf_hz=hp, low_freq_hz=hz, low_db=low, high_db=-16)
    else:
        for hz, gain, shape, bw_min, bw_max in itertools.product(
                [30,60,1000,8000,12000,16000,19000,20000], [-12,12],
                ['peak','low_shelf','high_shelf'], [.3,2], [1,4]):
            if bw_min <= bw_max:
                yield dict(freq_hz=hz, gain_db=gain, shape=shape,
                           bw_min_oct=bw_min, bw_max_oct=bw_max)


@pytest.mark.parametrize('kind',['passive_eq','inductor_eq','proportional_eq'])
@pytest.mark.parametrize('sr',[44100,48000,96000])
def test_physical_response_range(kind,sr):
    f = np.geomspace(20,20000,2001)
    # Full precision resampling response, evaluated once on the shared grid.
    fir = abs(signal.freqz(N._precision_os_filter(32),worN=f,fs=32*sr)[1])
    fir *= abs(signal.freqz(N._precision_os_filter(16),worN=f,fs=32*sr)[1])
    fir *= abs(signal.freqz(N._precision_final_filter(),worN=f,fs=2*sr)[1])
    worst, count = 0., 0
    for overrides in eq_cases(kind):
        p = P.validate_params(kind,overrides)
        sos = A.precision_design_sos(kind,p,sr)
        h = signal.sosfreqz(sos,worN=f,fs=32*sr)[1] if len(sos) else np.ones(len(f))
        error = float(np.max(abs(20*np.log10(abs(h*fir/A.analog_response(kind,p,f))))))
        assert error <= .2, (kind,sr,overrides,error)
        worst, count = max(worst,error), count+1
    print('C6A_ANALOG_RANGE',json.dumps(dict(kind=kind,sr=sr,cases=count,max_error_db=worst)))


@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.parametrize('lo,hi',[(80,1200),(80,5000),(150,2400),(400,5000)])
def test_absolute_delay_range(sr,lo,hi):
    rows=[]
    for low,mid in [(0,0),(5,0),(0,2),(5,2),(2.5,.5),(.25,.05),(.025,.005),(.5,1)]:
        sos=delay_sos(sr,lo,hi,low,mid)
        delays=[]
        for hz in (lo/3.75,np.sqrt(lo*hi),10000):
            h=signal.sosfreqz(sos,worN=[hz-.001,hz+.001],fs=sr)[1] if len(sos) else np.ones(2)
            delays.append(float(-np.angle(h[1]/h[0])/(.002*2*np.pi)*1000))
        # A requested zero is resolved to one sample, as in W2a3's high-band test.
        for actual,target in zip(delays[:2],[low,mid]):
            assert abs(actual-target) <= (.15*target if target else 1000/sr), (sr,lo,hi,low,mid,delays)
        assert abs(delays[2]) < 1000/sr, (sr,lo,hi,low,mid,delays)
        f=np.geomspace(20,20000,2001)
        h=signal.sosfreqz(sos,worN=f,fs=sr)[1] if len(sos) else np.ones(len(f))
        assert np.max(abs(20*np.log10(abs(h)))) <= .3
        rows.append(dict(request_ms=[low,mid],measured_ms=delays))
    print('C6A_PHASE_RANGE',json.dumps(dict(sr=sr,crossovers=[lo,hi],rows=rows)))


@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.parametrize('mode',['divider','tracked'])
@pytest.mark.parametrize('attack,release',[(10,20),(20,150),(50,150),(100,1000)])
def test_final_sub_envelope_range(sr,mode,attack,release):
    x=tone(80,sr=sr,seconds=6);x[:sr//2]=0;x[2*sr:]=0
    d=render('sub_synth',x,dict(amount_db=0,mode=mode,attack_ms=attack,release_ms=release),sr)-x
    env=amplitude_envelope(d,sr,.1,.1)[:,0]
    steady=float(np.median(env[sr:3*sr//2]))
    a=float(np.flatnonzero(env[sr//2:]>=steady*(1-np.exp(-1)))[0]/sr*1000)
    r=float(np.flatnonzero(env[2*sr:]<=steady/np.e)[0]/sr*1000)
    print('C6A_SUB_TIMES',json.dumps(dict(sr=sr,mode=mode,request_ms=[attack,release],actual_ms=[a,r])))
    assert abs(a/attack-1)<=.2 and abs(r/release-1)<=.2


def test_sub_attack_range_rejects_unverified_fast_ballistics():
    assert P.validate_params('sub_synth',{})['attack_ms'] == 10
    for ms in (1,5,9.99):
        with pytest.raises(ParamError):
            P.validate_params('sub_synth',dict(attack_ms=ms))


@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.parametrize('mode',['divider','tracked'])
@pytest.mark.parametrize('cut',[30,60,120])
def test_sub_carrier_highcut_harmonics(sr,mode,cut):
    x=tone(80,sr=sr)
    d=render('sub_synth',x,dict(amount_db=0,mode=mode,sub_highcut_hz=cut),sr)-x
    v=d[sr//2:sr,0]
    def amp(f):
        return 2*abs(np.dot(v,np.exp(-2j*np.pi*f*np.arange(len(v))/sr)))/len(v)
    ratio=float(20*np.log10(np.linalg.norm([amp(f) for f in (80,120,160,200,240,280)])/amp(40)))
    print('C6A_SUB_CUT',sr,mode,cut,ratio)
    assert ratio <= -40


@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.parametrize('mode',['divider','tracked'])
def test_sub_outside_band_whole_record(sr,mode):
    from tests import toolimpl_harness as H
    for f in (30,200):
        x=tone(f,sr=sr)
        d=render('sub_synth',x,dict(amount_db=0,mode=mode),sr)-x
        value=H.rms_dbfs(d)
        print('C6A_SUB_OUTSIDE_FULL',sr,mode,f,value)
        assert value <= -80
