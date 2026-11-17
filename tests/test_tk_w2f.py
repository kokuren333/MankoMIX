"""W2f acceptance measurements, shared API checks and honest release gates."""
import importlib
import json
import numpy as np
import pytest
from scipy import signal
from scipy.fft import rfft, rfftfreq
from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.errors import ParamError
from tests import toolimpl_harness as H

KINDS = ('autopan', 'doppler', 'ring_mod', 'freq_shifter', 'vibe', 'rotary')


@pytest.fixture(autouse=True)
def enable_pending_diagnostics(monkeypatch):
    for kind in KINDS:
        monkeypatch.setitem(P.PROCESSORS[kind], 'implemented', True)


def p(kind, **kw):
    return P.validate_params(kind, kw)


def direct(kind, x, sr=48000, **kw):
    return getattr(importlib.import_module('mankomix.dspx.procs.'+kind), kind)(x, sr, p(kind, **kw), seed=17)[0]


def run(kind, x, sr=48000, *, seed=17, item='motion', **kw):
    return render_chain(x, sr, [dict(id=item, type=kind, params=kw)], stage='track', seed=seed).audio


def tone(sr=48000, seconds=2, hz=1000, channels=1):
    return np.repeat((.1*np.sin(2*np.pi*hz*np.arange(round(sr*seconds))/sr))[:, None], channels, axis=1)


def amplitude(x, hz, sr):
    n = np.arange(len(x))
    return abs(2*np.mean(np.asarray(x)*np.exp(-2j*np.pi*hz*n/sr)))


def db(x):
    return 20*np.log10(max(float(x), 1e-300))


def record(label, values):
    print(label+': '+json.dumps(values, sort_keys=True))


@pytest.mark.parametrize('kind', KINDS)
def test_registration_and_all_valid_bounds(kind):
    definition = P.describe(kind)
    assert definition['stages'] == ['track', 'bus']
    assert definition['master_slot'] is None
    assert definition['backends'] == ['reference']
    assert definition['realtime'] == dict(block_ok=False, allocates=True, latency_samples=0,
        **({'latency_rule': 'Allpass group delay intentionally not compensated.'} if kind == 'freq_shifter' else {}))
    from mankomix.dspx.registry import time_varying_types
    assert kind in time_varying_types()
    defaults = p(kind)
    assert run(kind, tone(seconds=.02, channels=2)).tobytes() == run(kind, tone(seconds=.02, channels=2), **defaults).tobytes()
    for spec in definition['params']:
        key = spec['id']
        if spec['type'] in ('float', 'int'):
            choices = [spec['min'], spec['max']]
        elif spec['type'] == 'enum':
            choices = spec['choices']
        else:
            continue
        for value in choices:
            kw = {key: value}
            if key == 'note' and value != 'none':
                kw['bpm'] = 120
            if kind == 'doppler' and ((key == 'start_s' and value == 36000) or (key == 'end_s' and value == 0)):
                with pytest.raises(ParamError):
                    p(kind, **kw)
                continue
            y = run(kind, tone(seconds=.004, channels=2), **kw)
            assert np.isfinite(y).all(), (kind, key, value)


def test_explicit_defaults_and_ranges():
    expected = {
        'autopan': dict(source='lfo', depth=.5, center=0, rate_hz=1, note='none', bpm=0,
                        lfo_shape='sine', shape=[[0,-1],[.5,1],[1,-1]], origin_s=0, phase=0,
                        env_attack_ms=20, env_release_ms=300, env_threshold_db=-40, smooth_ms=5, seed=0),
        'doppler': dict(start_s=0, end_s=4, x0_m=-30, x1_m=30, y_m=5, path=[[0,0],[1,1]],
                        speed_of_sound=343, gain_ref_m=5, max_gain_db=0, air=.5, pan_amount=1,
                        pitch_amount=1, mix=1),
        'ring_mod': dict(freq_hz=440, carrier='sine', freq_curve=[], lfo_depth_oct=0, am=0,
                         diode=0, oversample=2, rate_hz=1, note='none', bpm=0,
                         lfo_shape='sine', origin_s=0, mix=1, seed=0),
        'freq_shifter': dict(shift_hz=5, shift_curve=[], sideband='single', feedback=0,
                             lo_hz=20, rate_hz=1, lfo_shape='sine', depth=0, mix=1, seed=0),
        'vibe': dict(rate_hz=3, note='none', bpm=0, depth=.7, lfo_shape='sine', stereo_phase=0,
                     origin_s=0, phase=0, seed=0, mode='chorus', lamp_ms_up=20, lamp_ms_down=120,
                     asym=.5, drive_db=0, output_db=0),
        'rotary': dict(speed='slow', speed_curve=[], horn_slow_hz=.8, horn_fast_hz=6.8,
                       drum_slow_hz=.7, drum_fast_hz=5.9, horn_accel_s=1, drum_accel_s=4.5,
                       crossover_hz=800, horn_depth=.7, drum_depth=.4, mic_angle_deg=90,
                       mic_distance=.5, drive_db=0, balance=0, mix=1, seed=0)}
    for kind in KINDS:
        assert p(kind) == expected[kind]
    # Independent numerical contract checks, including overwritten MOD ranges.
    bounds = {'autopan': {'center':(-1,1), 'env_attack_ms':(1,500), 'env_release_ms':(10,3000),
                         'env_threshold_db':(-80,0), 'smooth_ms':(0,50)},
              'doppler': {'start_s':(0,36000),'end_s':(0,36000),'x0_m':(-500,500),'x1_m':(-500,500),
                          'y_m':(.5,200),'speed_of_sound':(300,360),'gain_ref_m':(.5,50), 'max_gain_db':(0,12)},
              'ring_mod': {'freq_hz':(.1,10000),'lfo_depth_oct':(0,4)},
              'freq_shifter': {'shift_hz':(-5000,5000),'feedback':(0,.9),'lo_hz':(0,500)},
              'vibe': {'rate_hz':(.3,12),'lamp_ms_up':(5,100),'lamp_ms_down':(20,400),
                       'drive_db':(0,12),'output_db':(-12,12)},
              'rotary': {'horn_slow_hz':(.3,2),'drum_slow_hz':(.3,2),'horn_fast_hz':(4,10),
                         'drum_fast_hz':(4,10),'horn_accel_s':(.1,10),'drum_accel_s':(.1,10),
                         'mic_angle_deg':(0,180),'crossover_hz':(400,1600),'drive_db':(0,24), 'balance':(-1,1)}}
    for kind, fields in bounds.items():
        specs = {v['id']:v for v in P.describe(kind)['params']}
        for key, interval in fields.items():
            assert (specs[key]['min'], specs[key]['max']) == interval


@pytest.mark.parametrize('kind', ['doppler', 'ring_mod', 'freq_shifter', 'rotary'])
def test_exact_mix_zero(kind):
    x = np.random.Generator(np.random.PCG64(7)).normal(size=(2001,2))*.1
    assert run(kind, x, mix=0).tobytes() == x.tobytes()


def test_autopan_pan_law_neutral_and_symmetry():
    from mankomix.dsp.reference.basic import pan
    from mankomix.dspx.procs.autopan import pan_positions
    for channels in (1, 2):
        x = tone(seconds=.8, channels=channels)
        for center in (-1, -.3, 0, .3, 1):
            y = run('autopan', x, depth=0, center=center)
            expected = pan(x, 48000, dict(position=center, center_db=-3))[0]
            assert y.tobytes() == expected.tobytes()
    x = tone(seconds=1.7)
    pp = p('autopan', smooth_ms=0, depth=1)
    pos = pan_positions(x, 48000, pp)
    y = direct('autopan', x, smooth_ms=0, depth=1)
    # -3.000 dB legacy law differs slightly from mathematical -3.0103 dB.
    power = np.sum(y*y, axis=1)/(x[:,0]**2+1e-300)
    valid = abs(x[:,0]) > .01
    ripple = 10*np.log10(np.max(power[valid])/np.min(power[valid]))
    assert ripple < .05
    exponent = -3/(20*np.log10(np.cos(np.pi/4)))
    expected = np.column_stack((np.cos((pos+1)*np.pi/4)**exponent,
                                np.sin((pos+1)*np.pi/4)**exponent))*x
    assert np.max(np.abs(y-expected)) < 1e-14
    stereo = tone(seconds=.3, channels=2)
    a = direct('autopan', stereo, source='shape', center=.1, shape=[[0,-1],[.5,1],[1,-1]])
    b = direct('autopan', stereo[:,::-1].copy(), source='shape', center=-.1, shape=[[0,1],[.5,-1],[1,1]])
    assert a[:,::-1].tobytes() == b.tobytes()
    record('autopan_power_ripple_db', ripple)


def test_autopan_envelope_times_period_and_excerpt():
    from mankomix.dspx.procs.autopan import pan_positions
    sr = 8000
    pp = p('autopan', source='envelope', env_threshold_db=-20, smooth_ms=0, depth=1)
    x = np.r_[np.full(sr, .1), np.zeros(3*sr)][:,None]
    pos = pan_positions(x, sr, pp)
    attack = np.flatnonzero(pos >= 1-np.exp(-1))[0]/sr
    release = (np.flatnonzero(pos[sr:] <= np.exp(-1))[0]+1)/sr
    assert abs(attack/.02-1) < .1 and abs(release/.3-1) < .1
    from mankomix.dspx.bb.curves import period_ms
    for note in P.NOTE_VALUES:
        period = period_ms(1000, note=note, bpm=123)
        final = round(1000*period*sr/1000)
        pp = p('autopan', note=note, bpm=123, smooth_ms=0)
        values = pan_positions(np.ones((3,1)), sr, pp, start_sample=final-1)
        assert np.min(np.abs(values)) <= 2*np.pi/(period*sr/1000)
    pp = p('autopan', smooth_ms=0, source='shape')
    full = pan_positions(np.ones((10000,1)), sr, pp)
    part = pan_positions(np.ones((5000,1)), sr, pp, start_sample=5000)
    assert full[5000:].tobytes() == part.tobytes()
    record('autopan_tau_seconds', dict(attack=attack, release=release))


@pytest.mark.parametrize('kind, settings', [
    ('autopan',dict(lfo_shape='random')), ('ring_mod',dict(lfo_shape='random', lfo_depth_oct=1)),
    ('freq_shifter',dict(lfo_shape='random', depth=1)), ('vibe',dict(lfo_shape='random'))])
def test_engine_random_seed_and_item(kind, settings):
    x = tone(sr=8000, seconds=.3, channels=2)
    a = run(kind,x,8000,**settings)
    assert a.tobytes() == run(kind,x,8000,**settings).tobytes()
    assert a.tobytes() != run(kind,x,8000,seed=19,**settings).tobytes()
    assert a.tobytes() != run(kind,x,8000,item='other',**settings).tobytes()
    changed=render_chain(x,8000,[dict(id='motion',type=kind,params=dict(settings,seed=1))],
                         stage='track',seed=17).audio
    assert a.tobytes() != changed.tobytes()


def test_doppler_static_gain_geometry_and_frequency():
    from mankomix.dspx.procs.doppler import propagation, trajectory
    from mankomix.dsp.reference.basic import pan
    x = tone(seconds=1, channels=2)
    y = run('doppler',x,x0_m=12,x1_m=12,y_m=5,gain_ref_m=5,pan_amount=0,pitch_amount=0,air=0)
    assert np.max(np.abs(y-x*(5/13))) < 1e-16
    sr=12000
    pp=p('doppler',x0_m=-60,x1_m=60,end_s=4,air=0,pan_amount=0)
    e,pos,r,g=propagation(5*sr,sr,pp)
    x=tone(sr,5)
    y=run('doppler',x,sr,x0_m=-60,x1_m=60,end_s=4,air=0,pan_amount=0)[:,0]
    phase=np.unwrap(np.angle(signal.hilbert(y)))
    instantaneous=np.gradient(phase)*sr/(2*np.pi)
    radial=trajectory(e,pp)[2]
    theoretical=1000*343/(343+radial)
    selected=((e>.5)&(e<1.4))|((e>2.6)&(e<3.4))
    error=np.max(np.abs(instantaneous[selected]/theoretical[selected]-1))
    assert error < .005
    assert abs(e[np.argmax(g)]-2) < .002
    assert np.max(np.abs(g-5/r)) < 1e-15
    # Geometric pan is independent of the propagation clock normalization.
    qp=p('doppler',pitch_amount=0)
    ee,pos,r,g=propagation(sr*4,sr,qp)
    xx=trajectory(ee,qp)[0]
    assert np.max(np.abs(pos-np.arctan2(xx,5)/(np.pi/2))) < 1e-15
    part=propagation(1000,sr,pp,start_sample=30000)
    full=propagation(31000,sr,pp)
    assert all(a.tobytes()==b[30000:].tobytes() for a,b in zip(part,full))
    # Reflection swaps lateral coordinates and stereo channels exactly.
    a=direct('doppler',tone(sr,1,channels=2),sr,air=0)
    b=direct('doppler',tone(sr,1,channels=2)[:,::-1],sr,x0_m=30,x1_m=-30,air=0)
    assert a[:,::-1].tobytes()==b.tobytes()
    record('doppler_max_relative_frequency_error',error)


def test_doppler_invalid_speed_and_paths():
    for kw in [dict(end_s=0),dict(x0_m=-500,x1_m=500,end_s=.1),
               dict(path=[[0,0],[.5,.8],[.6,.2],[1,1]]),dict(path=[])]:
        with pytest.raises(ParamError):
            p('doppler',**kw)
    for curve in ([[.2,.3],[.8,.7]],[[.4,.6]]):
        assert np.isfinite(run('doppler',tone(12000,.2),12000,path=curve)).all()


def test_hilbert_pair_design_state_and_zero_shift():
    from mankomix.dspx.bb.hilbert import pair_response,HilbertPair,hilbert_pair
    maximum=0.
    for sr in (44100,48000,96000):
        f=np.geomspace(20,.45*sr,12000)
        a,b=pair_response(f,sr)
        error=np.max(np.abs(np.angle(b/a)+np.pi/2))*180/np.pi
        maximum=max(maximum,error)
        assert error <= .1
        assert np.max(np.abs(20*np.log10(np.abs(a)))) < .05
    x=tone(seconds=1,channels=2)
    expected=hilbert_pair(x)
    for size in (64,1024):
        state=HilbertPair(2)
        blocks=[state.process(x[i:i+size]) for i in range(0,len(x),size)]
        assert all(np.concatenate([v[j] for v in blocks]).tobytes()==expected[j].tobytes() for j in (0,1))
    y=run('freq_shifter',x,shift_hz=0,lo_hz=0)
    assert y.tobytes()==expected[0].tobytes()
    record('hilbert_max_phase_error_degrees',maximum)


@pytest.mark.parametrize('hz',np.geomspace(100,10000,10))
def test_frequency_shifter_ten_tones(hz):
    sr=48000
    # Fit arbitrary non-FFT-bin tones jointly after one second of settling.
    x=tone(sr,2,hz)
    y=run('freq_shifter',x,sr,shift_hz=37,lo_hz=0)[sr:,0]
    t=np.arange(sr)/sr
    freqs=[hz+37,abs(hz-37),hz]
    basis=np.column_stack([fn(2*np.pi*f*t) for f in freqs for fn in (np.cos,np.sin)])
    weights=np.linalg.lstsq(basis,y,rcond=None)[0]
    levels=np.hypot(weights[::2],weights[1::2])
    rejection=db(levels[1]/levels[0])
    original=db(levels[2]/levels[0])
    frequency=H.fundamental_frequency(y[:,None],sr,low_hz=hz+30,high_hz=hz+44)
    assert abs(frequency-(hz+37)) <= .1
    assert rejection <= -60 and original <= -60
    record('ssb_'+str(round(float(hz),6)),dict(frequency=frequency,image_db=rejection,original_db=original))


def test_frequency_shifter_sidebands_feedback_and_phase():
    from mankomix.dspx.procs.freq_shifter import shift_phase
    sr=8000
    y=run('freq_shifter',tone(sr,2),sr,shift_hz=100,sideband='both',lo_hz=0)
    assert abs(H.fundamental_frequency(y[sr:,0:1],sr)-1100) < .1
    assert abs(H.fundamental_frequency(y[sr:,1:2],sr)-900) < .1
    pp=p('freq_shifter',shift_curve=[[0,-20],[.4,90],[1,-10]],depth=.5,lfo_shape='random')
    whole=shift_phase(20000,sr,pp,seed=17)
    part=shift_phase(5000,sr,pp,start_sample=15000,seed=17)
    assert whole[15000:].tobytes()==part.tobytes()
    excited=np.random.Generator(np.random.PCG64(19)).choice([-1.,1.],(round(sr*.1),2))
    x=np.concatenate((excited,np.zeros((sr*60,2))))
    tails=[]
    for shift in (37,-37):
        out=run('freq_shifter',x,sr,feedback=.9,shift_hz=shift)
        assert np.isfinite(out).all() and np.max(np.abs(out[-sr:])) < 1e-6
        tails.append(db(np.max(np.abs(out[-sr:]))))
    record('ssb_feedback_tail_dbfs',tails)


def test_frequency_shifter_antialias_and_dc_crossing():
    sr=48000
    y=direct('freq_shifter',tone(sr,2,22000),sr,shift_hz=5000,lo_hz=0)[sr:,0]
    attenuation=db(amplitude(y,21000,sr)/.1)
    assert attenuation <= -80
    folded=direct('freq_shifter',tone(sr,2,300),sr,shift_hz=-400,lo_hz=0)[sr:]
    assert abs(H.fundamental_frequency(folded,sr,low_hz=80,high_hz=120)-100) < .1
    record('ssb_upward_alias_db',attenuation)


def test_ring_mod_spectra_am_diode_and_phase():
    from mankomix.dspx.procs.ring_mod import carrier_phase,carrier_wave
    sr=48000
    x=tone(sr,2)
    wet=run('ring_mod',x,sr,freq_hz=300)[sr//2:sr*3//2,0]
    peaks=[amplitude(wet,f,sr) for f in (700,1000,1300)]
    spectrum=abs(rfft(wet))
    mask=np.ones(len(spectrum),bool)
    for f in (700,1300):
        mask[f]=False
    alias=db(np.max(spectrum[mask])/max(spectrum))
    assert db(peaks[1]/peaks[0]) < -80 and alias < -80
    am=run('ring_mod',x,sr,freq_hz=300,am=1)[sr//2:sr*3//2,0]
    assert abs(amplitude(am,1000,sr)/.05-1) < .001
    assert abs(amplitude(am,700,sr)/.025-1) < .001
    square=run('ring_mod',x,sr,freq_hz=300,carrier='square')[sr//2:sr*3//2,0]
    # Every allowed square sideband is integral here; inspect all remaining bins.
    spectrum=abs(rfft(square)); mask=np.ones(len(spectrum),bool)
    for h in range(1,int(.45*sr/300)+1,2):
        for f in (abs(1000-h*300),1000+h*300):
            if f < len(mask): mask[f]=False
    square_alias=db(np.max(spectrum[mask])/max(spectrum))
    assert square_alias < -70
    # Pure carrier itself contains no harmonics past .45*sr.
    cyc=np.arange(sr)*300/sr
    carrier=carrier_wave(cyc,np.full(sr,300.),sr,'square')
    cs=abs(rfft(carrier))
    assert db(np.max(cs[int(.45*sr)+1:])/max(cs)) < -100
    higher=[]
    for amount in (0,.25,.5,1):
        d=run('ring_mod',x,sr,freq_hz=300,diode=amount)[sr//2:sr*3//2,0]
        higher.append(amplitude(d,1900,sr))
    assert np.all(np.diff(higher)>0)
    for depth in (0,1):
        pp=p('ring_mod',freq_curve=[[0,100],[.4,400],[1,90]],lfo_depth_oct=depth,lfo_shape='random')
        whole=carrier_phase(30000,sr,pp,seed=17)
        part=carrier_phase(5000,sr,pp,seed=17,start_sample=25000)
        assert whole[25000:].tobytes()==part.tobytes()
    record('ring_spectrum',dict(original_db=db(peaks[1]/peaks[0]),alias_db=alias,
                               square_alias_db=square_alias,diode_1900_amplitudes=higher))


def test_vibe_static_allpass_notches_and_linear_thd():
    from mankomix.dspx.procs.vibe import corner_frequencies
    sr=48000
    x=tone(sr,3)
    y=run('vibe',x,sr,mode='vibrato',depth=0)[sr:,0]
    level=db(np.sqrt(np.mean(y*y))/np.sqrt(np.mean(x[sr:,0]**2)))
    thd=H.thd(y[:,None],sr,1000)['thd_db']
    assert abs(level) <= .05 and thd <= -100
    f=np.geomspace(1,.45*sr,65536)
    corners=corner_frequencies(1,sr,p('vibe',depth=0))[0,0]
    response=np.ones(len(f),complex)
    for cutoff in corners:
        k=(np.tan(np.pi*cutoff/sr)-1)/(np.tan(np.pi*cutoff/sr)+1)
        response*=signal.freqz([k,1],[1,k],worN=f,fs=sr)[1]
    chorus=abs((1+response)/2)
    minima=signal.find_peaks(-chorus)[0]
    assert len(minima) <= 2
    # Independent matching four-section phaser, all corners at 800 Hz.
    k=(np.tan(np.pi*800/sr)-1)/(np.tan(np.pi*800/sr)+1)
    phaser=abs((1+signal.freqz([k,1],[1,k],worN=f,fs=sr)[1]**4)/2)
    record('vibe_static',dict(level_db=level,thd_db=thd,notches=len(minima),
                            notch_hz=f[minima].tolist(),depth_db=db(chorus.min()),
                            phaser_depth_db=db(phaser.min())))
    assert db(chorus.min()) > db(phaser.min())


def test_pending_autopan_legacy_symmetry_conflict():
    from mankomix.dsp.reference.basic import pan
    x=np.array([[.13,.27],[.47,-.55]])
    a=direct('autopan',x,depth=0,center=.3)
    b=direct('autopan',x[:,::-1],depth=0,center=-.3)
    assert a.tobytes()==pan(x,48000,dict(position=.3,center_db=-3))[0].tobytes()
    difference=float(np.max(abs(a[:,::-1]-b)))
    assert a[:,::-1].tobytes()!=b.tobytes()
    record('autopan_unmet_ST3_peak_difference',difference)


def test_pending_vibe_continuous_notch_depth_conflict():
    from scipy.optimize import brentq
    from mankomix.dspx.procs.vibe import corner_frequencies
    sr=48000
    values={}
    for label,corners in [('vibe',corner_frequencies(1,sr,p('vibe',depth=0))[0,0]),
                           ('phaser',np.full(4,800.))]:
        def phase(f):
            return -2*np.sum(np.arctan(np.tan(np.pi*f/sr)/np.tan(np.pi*corners/sr)))
        roots=[brentq(lambda f: phase(f)+target,1e-8,sr/2-1e-8,xtol=1e-11)
               for target in (np.pi,3*np.pi)]
        residual=[abs((1+np.exp(1j*phase(f)))/2) for f in roots]
        assert max(residual)<1e-12
        values[label]=dict(notch_hz=roots,residual=residual)
    # Four ideal sections wind through -pi and -3pi whatever their spacing.
    # Equal dry/wet therefore has exact zeros in BOTH designs. Grid depth
    # differences above cannot establish the requested intrinsic shallowness.
    record('vibe_unmet_continuous_notch_comparison',values)


def test_vibe_thermal_phase_and_bandwidth():
    from mankomix.dspx.procs.vibe import lamp_response,lamp_motion,corner_frequencies
    sr=4000
    target=np.r_[np.ones(sr),np.zeros(sr)]
    light=lamp_response(target,sr,20,120)
    # Recover brightness from measured allpass instantaneous phase at 1 kHz.
    # Static phase-to-corner map is monotone, checked below against actual audio.
    up=np.flatnonzero(light>=1-np.exp(-1))[0]/sr
    down=(np.flatnonzero(light[sr:]<=np.exp(-1))[0]+1)/sr
    assert up < down and abs(up/.02-1)<.1 and abs(down/.12-1)<.1
    widths=[]
    for rate in (.5,1,3,6,12):
        values=lamp_motion(sr*8,sr,p('vibe',rate_hz=rate))[-sr*4:,0]
        widths.append(float(np.ptp(values)))
    assert np.all(np.diff(widths)<0)
    pp=p('vibe')
    full=corner_frequencies(12000,sr,pp)
    part=corner_frequencies(2000,sr,pp,start_sample=10000)
    assert full[10000:].tobytes()==part.tobytes()
    record('vibe_thermal',dict(up_s=up,down_s=down,widths=widths))


def test_vibe_measured_instantaneous_phase_and_linearity():
    sr=12000
    x=tone(sr,6)
    settings=dict(mode='vibrato',lfo_shape='triangle',rate_hz=1,depth=.8)
    y=run('vibe',x,sr,**settings)
    t=np.arange(len(x))/sr
    phase=np.unwrap(np.angle(signal.hilbert(y[:,0])))-2*np.pi*1000*t
    phase=signal.savgol_filter(phase,201,2)
    peaks=signal.find_peaks(phase[3*sr:5*sr])[0]
    troughs=signal.find_peaks(-phase[3*sr:5*sr])[0]
    peak=peaks[0]
    before=troughs[troughs<peak][-1]
    after=troughs[troughs>peak][0]
    up=(peak-before)/sr
    down=(after-peak)/sr
    assert up < down
    # Control is independent of the audio; drive=0 is a linear time-varying map.
    a=tone(sr,.3,700); b=tone(sr,.3,1300)
    whole=direct('vibe',a+b,sr,**settings)
    summed=direct('vibe',a,sr,**settings)+direct('vibe',b,sr,**settings)
    assert np.max(abs(whole-summed))<1e-14
    record('vibe_audio_sweep_seconds',dict(up=up,down=down))


def test_rotary_analytic_angles_acceleration_and_stop():
    from mankomix.dspx.procs.rotary import rotor_angles
    from mankomix.dspx.bb.motion import rotor_motion
    sr=1000
    t=np.arange(sr*30)/sr
    points=[[0,.8],[1,.8],[1.01,6.8]]
    cycles,hz=rotor_motion(t,points,1)
    # End-of-ramp analytic state; subsequent 63.212% increment takes exactly tau.
    end=round(1.01*sr)
    target=hz[end]+(6.8-hz[end])*(1-np.exp(-1))
    measured=(np.flatnonzero(hz[end:]>=target)[0])/sr
    assert abs(measured-1)<.002
    pp=p('rotary',speed_curve=[[0,1],[1,1],[1.01,2]])
    for rotor in ('horn','drum'):
        angle,speed=rotor_angles(30000,sr,pp,rotor)
        part=rotor_angles(3000,sr,pp,rotor,start_sample=27000)
        assert angle[27000:].tobytes()==part[0].tobytes()
        tau=pp[rotor+'_accel_s']
        fast=pp[rotor+'_fast_hz']
        threshold=speed[end]+(fast-speed[end])*(1-np.exp(-1))
        found=np.flatnonzero(speed[end:]>=threshold)[0]/sr
        assert abs(found/tau-1)<.1
    out=run('rotary',tone(12000,2,hz=3000),12000,speed='stop')
    envelope=abs(signal.hilbert(out[:,0]))
    ripple=db(np.max(envelope[6000:18000])/np.min(envelope[6000:18000]))
    assert ripple < .01
    record('rotary_acceleration_stop',dict(horn_63_s=measured,stop_ripple_db=ripple))


def test_rotary_audio_periods_and_mic_phase():
    sr=12000
    values={}
    for freq,rotor in ((3000,'horn'),(100,'drum')):
        out=run('rotary',tone(sr,4,hz=freq),sr,speed='fast')
        analytic=signal.hilbert(out,axis=0)
        control=np.gradient(np.unwrap(np.angle(analytic),axis=0),axis=0)*sr/(2*np.pi) if rotor=='horn' else abs(analytic)
        control=control[sr:3*sr]
        target=p('rotary')[rotor+'_fast_hz']
        measured=H.fundamental_frequency((control[:,0]-np.mean(control[:,0]))[:,None],sr,low_hz=4,high_hz=10)
        assert abs(measured/target-1) < .01
        c=[np.mean((control[:,ch]-np.mean(control[:,ch]))*np.exp(-2j*np.pi*target*np.arange(len(control))/sr)) for ch in (0,1)]
        phase=abs(np.angle(c[1]/c[0]))*180/np.pi
        assert abs(phase-90) < 5
        values[rotor]=dict(frequency=measured,mic_phase_degrees=phase)
    record('rotary_audio',values)


@pytest.mark.parametrize('kind',KINDS)
def test_spatial_record_and_full_context_excerpt(kind):
    x=tone(12000,.3,channels=2)
    rendered=render_chain(x,12000,[dict(id='motion',type=kind)],stage='track',seed=17)
    stats=rendered.steps[0]['stats']
    assert 'mono' in stats and 'mono_worst_third_octave_db' in stats
    a=run(kind,x,12000)
    b=run(kind,x,12000)
    assert a[1000:2000].tobytes()==b[1000:2000].tobytes()


@pytest.mark.parametrize('kind', ['autopan','doppler','rotary'])
def test_mono_expansion(kind):
    x=tone(12000,.3)
    a=run(kind,x,12000)
    assert a.shape==(len(x),2)
    assert np.isfinite(a).all()


@pytest.mark.parametrize('kind', ['autopan','doppler'])
def test_independent_spatial_vector(kind):
    x=np.random.Generator(np.random.PCG64(8)).normal(0,.03,(8192,2))
    result=render_chain(x,12000,[dict(id='motion',type=kind)],stage='track',seed=17)
    y=result.audio
    st=result.steps[0]['stats']
    den=np.mean(y*y)
    loss=10*np.log10(np.mean(np.mean(y,axis=1)**2)/den)
    assert abs(st['mono']['mono_loss_db']-loss)<.001
    spectrum=rfft(y,axis=0,workers=1)
    frequencies=rfftfreq(len(y),1/12000)
    losses=[]
    for center in 1000*2.**(np.arange(-17,14)/3):
        band=spectrum[(frequencies>=center/2**(1/6))&(frequencies<center*2**(1/6))]
        if np.sum(abs(band)**2)>0:
            losses.append(10*np.log10(np.sum(abs(np.mean(band,axis=1))**2)/(np.sum(abs(band)**2)/2)))
    assert abs(min(losses)-st['mono_worst_third_octave_db'])<.1
    record(kind+'_spatial',st)


@pytest.mark.parametrize('kind',KINDS)
def test_curve_contracts(kind):
    for spec in P.describe(kind)['params']:
        if spec['type']!='curve':
            continue
        lo,hi=spec['y_min'],spec['y_max']
        for points in ([[spec['x_min'],lo-1]],[[spec['x_min'],hi+1]],
                       [[spec['x_min']-1,lo]],[[0,lo],[0,hi]],
                       [[0,lo]]*(spec['max_points']+1)):
            with pytest.raises(ParamError):
                p(kind,**{spec['id']:points})


def test_independent_analytic_integrals_and_long_clock():
    from mankomix.dspx.bb.motion import curve_integral,rotor_motion
    # Linear 100->300 Hz in one second, including constant endpoint extensions.
    times=np.array([0,.25,.5,1.,2.])
    assert np.max(abs(curve_integral([[0,100],[1,300]],times)-
                      np.where(times<=1,100*times+100*times**2,200+300*(times-1))))<1e-12
    log=curve_integral([[0,100],[1,400]],times,logarithmic=True)
    expected=np.where(times<=1,100*np.expm1(np.log(4)*times)/np.log(4),
                       300/np.log(4)+400*(times-1))
    assert np.max(abs(log-expected))<1e-12
    # Closed-form rotor integral checked by differentiating at a late time.
    times=np.array([35000-1e-3,35000.,35000+1e-3])
    angle,hz=rotor_motion(times,[[0,.8],[1,6.8]],1)
    assert abs((angle[-1]-angle[0])/.002-6.8)<1e-6
    assert abs(hz[1]-6.8)<1e-12


def test_dynamic_defaults_silence_and_full_scale():
    for kind in KINDS:
        silence=run(kind,np.zeros((1200,2)),12000)
        assert np.max(abs(silence))==0
        x=np.random.Generator(np.random.PCG64(5)).choice([-1.,1.],(2400,2))
        assert np.isfinite(run(kind,x,12000)).all()


def test_release_flags_and_pending_rejection(monkeypatch):
    from mankomix.dsp.errors import ChainError
    for kind in KINDS:
        released=kind not in ('autopan','vibe')
        module=importlib.import_module('mankomix.dspx.procs.'+kind)
        assert module.SPECS[0]['implemented'] is released
        monkeypatch.setitem(P.PROCESSORS[kind],'implemented',released)
        if not released:
            with pytest.raises(ChainError,match='not implemented'):
                run(kind,tone(seconds=.01))


@pytest.mark.parametrize('kind',KINDS)
def test_common_contract(kind,monkeypatch):
    # Harness assumes shape preservation. Its mono sine probes are promoted for
    # the three explicitly stereo-producing types; native mono is tested above.
    if kind in ('autopan','doppler','rotary'):
        original=H.sine
        def stereo_sine(*args,**kw):
            kw['channels']=2
            return original(*args,**kw)
        monkeypatch.setattr(H,'sine',stereo_sine)
    settings={'autopan':dict(depth=0),
              'doppler':dict(x0_m=0,x1_m=0,pitch_amount=0,air=0,pan_amount=0),
              'ring_mod':dict(freq_hz=300),
              'freq_shifter':dict(shift_hz=100,lo_hz=0),
              'vibe':dict(depth=0), 'rotary':dict(mix=0)}[kind]
    neutral={'autopan':dict(depth=0), 'doppler':dict(mix=0), 'ring_mod':dict(mix=0),
             'freq_shifter':dict(mix=0),'vibe':None,'rotary':dict(mix=0)}[kind]
    def probe(x,y,sr,params):
        expected=1100 if kind=='freq_shifter' else 700 if kind=='ring_mod' else 1000
        f=H.fundamental_frequency(y[len(y)//2:],sr,low_hz=expected-30,high_hz=expected+30)
        return dict(passed=abs(f-expected)<2,frequency_hz=f,expected_hz=expected)
    checks=H.assert_common_tests(kind,params=settings,neutral=neutral,seconds=.12,sr_probe=probe,
                                  latency_params=settings if kind in ('autopan','doppler','vibe') else dict(mix=0))
    assert all(v['passed'] for v in checks.values())
