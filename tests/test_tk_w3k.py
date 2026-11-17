"""BB-19 / W3k: independent signal measurements and processor contracts.

Original formant_shift acceptance numbers are ordinary closure regressions.
"""
import numpy as np
import pytest
from scipy import fft, signal, linalg
from mankomix.dsp import processors as P, engine as E
from mankomix.dsp.errors import ParamError, ChainError
from mankomix.dspx.bb import psola as B, stft as S
from mankomix.dspx.bb.pitch import PitchTrack
from mankomix.dspx.procs import formant_shift as FS, pitch_correct as PC
from mankomix.dspx.procs import harmony_voices as HV, talkbox as TB
from tests import toolimpl_harness as H

MODULES = dict(formant_shift=FS, pitch_correct=PC, harmony_voices=HV, talkbox=TB)
NEUTRAL = dict(formant_shift={'shift_cents': 0}, pitch_correct={'amount': 0},
               harmony_voices={'level_db': [-60]}, talkbox={'mix': 0})


@pytest.fixture
def enabled(monkeypatch):
    for name in MODULES:
        monkeypatch.setitem(P.PROCESSORS[name], 'implemented', True)


def direct(name, x, params=None, sr=16000):
    return MODULES[name].IMPLS[name](x, sr, P.validate_params(name, params or {}), seed=27)


def render(name, x, params=None, sr=16000, seed=5, item='voice'):
    return E.render_chain(x, sr, [dict(id=item, type=name, params=params or {})], stage='track', seed=seed).audio


def fixed_track(frames, sr, hz):
    hop = round(sr*256/48000)
    centers = np.arange(0, frames, hop)
    return PitchTrack(centers, centers/sr, np.full(len(centers), hz), np.ones(len(centers), bool),
                      np.ones(len(centers)), sr, hop, 2048, 'independent_fixture')


def pitch(v, sr, target):
    """Fixed-support normalized difference, independent of the pYIN detector."""
    x = v[:, 0] if v.ndim == 2 else v
    x = x-np.mean(x)
    lo, hi = max(2, round(sr/target/1.15)), min(len(x)//2-2, round(sr/target/.85))
    width = len(x)-hi-2
    ref = x[:width]
    ac = np.zeros(hi+2)
    for lag in range(lo-1,hi+2):
        other = x[lag:lag+width]
        ac[lag] = np.sum((ref-other)**2)/max(np.sum(ref*ref+other*other),1e-30)
    j = lo+int(np.argmin(ac[lo:hi+1]))
    d = .5*(ac[j-1]-ac[j+1])/(ac[j-1]-2*ac[j]+ac[j+1])
    return sr/(j+d)


def pitch_error(v, sr, target):
    return float(1200*np.log2(pitch(v, sr, target)/target))


def envelope_peaks(v, sr, targets):
    """Independent high-order AR fit on long data, evaluated on a dense grid.

    This uses a direct Toeplitz solve, not BB-19's estimator or its own stats.
    Keeping lags below the excitation period separates the vocal-tract model.
    """
    x = v[len(v)//4:3*len(v)//4, 0]
    x = signal.lfilter([1, -.85], [1], x)
    ac = signal.correlate(x, x, method='fft')[len(x)-1:]
    order = round(sr*.001)
    ac = ac[:order+1]/len(x)
    ac[0] *= 1.0000001
    a = np.r_[1., linalg.solve_toeplitz(ac[:-1], -ac[1:])]
    f, h = signal.freqz([1], a, worN=32768, fs=sr)
    return np.array([f[(f > t*.8) & (f < t*1.2)][np.argmax(abs(h[(f > t*.8) & (f < t*1.2)]))]
                     for t in targets])


def periodic_ripple(v, sr, hz, guard=.25):
    """RMS over a complete carrier period, excluding finite-boundary settling."""
    x = v[:, 0]
    start, stop = round(sr*guard), len(x)-round(sr*guard)-int(np.ceil(sr/hz))
    centers = np.arange(start, stop)
    integrals = np.r_[0., np.cumsum(x*x)]
    env = np.sqrt(np.maximum(1e-30, (np.interp(centers+sr/hz, np.arange(len(integrals)), integrals)
                                    -integrals[centers])/(sr/hz)))
    return float(20*np.log10(np.max(env)/np.min(env)))


@pytest.mark.parametrize('order', [1, 2, 8, 24, 48])
def test_lpc_reflection_stable_roundtrip_and_interpolation(order):
    rng = np.random.Generator(np.random.PCG64(order))
    k0, k1 = rng.uniform(-.55, .55, (2, order))
    for fraction in np.linspace(0, 1, 11):
        a = B.interpolate_lpc(k0, k1, fraction)
        assert np.max(abs(np.roots(a)), initial=0) < 1
        np.testing.assert_allclose(B.lpc_to_reflection(a), (1-fraction)*k0+fraction*k1, atol=2e-9)
    x = rng.standard_normal((1000, 2))*.1
    ks = np.repeat(k0[None, :, None], 2, axis=2)
    y = B.lattice_synthesis(x, np.array([0]), ks, np.ones((1, 2)))
    reference = signal.lfilter([1.], B.reflection_to_lpc(k0), x, axis=0)
    np.testing.assert_allclose(y, reference, atol=1e-8, rtol=1e-10)


@pytest.mark.parametrize('input_kind', ['silence', 'noise', 'vowel', 'impulse'])
def test_lpc_autocorrelation_fit(input_kind):
    sr = 16000
    x = {'silence': np.zeros((2000,1)), 'noise': H.white_noise(-12,sr=sr,seconds=.125),
         'vowel': H.vowel(150,sr=sr,seconds=.125), 'impulse': H.impulse(sr=sr,seconds=.125)}[input_kind]
    a, k, error = B.lpc(x[:, 0], 16)
    assert error >= 0 and np.isfinite(error)
    assert np.max(abs(k), initial=0) < 1
    assert np.max(abs(np.roots(a)), initial=0) < 1
    np.testing.assert_allclose(B.reflection_to_lpc(k), a, atol=1e-12)


@pytest.mark.parametrize('method', ['cepstrum', 'true_env', 'lpc'])
def test_envelope_flat_scale_transfer_and_upper(method):
    m = np.full((513, 2), .25)
    env = B.spectral_envelope(m, 48000, method)
    np.testing.assert_allclose(env, m, rtol=1e-6)
    f = np.arange(513)
    m[:, 0] *= np.exp(3*np.exp(-((f-70)/20)**2))
    shaped = B.spectral_envelope(m, 48000, method)
    scaled = B.spectral_envelope(m*.1, 48000, method)
    np.testing.assert_allclose(scaled, shaped*.1, rtol=1e-6)
    gain = B.envelope_transfer(np.ones(9), np.logspace(-6, 6, 9))
    assert 20*np.log10(gain.max()) <= 24+1e-10
    assert 20*np.log10(gain.min()) >= -24-1e-10
    if method == 'true_env':
        assert np.max(np.log(m/shaped)) <= .006


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('nominal', [1024, 2048, 4096])
def test_stft_identity_phase_and_raw_latency(sr, nominal):
    x = H.white_noise(-18, sr=sr, seconds=.05, channels=2)
    a = S.analyze(x, sr, window=S.window_samples(nominal, sr))
    assert H.null(x, S.synthesize(a))['peak_dbfs'] <= -120
    assert H.null(x, B.shift_envelope(x, sr, 0, window=nominal)[0])['bit_identical']
    pulse = H.impulse(at_s=.01, sr=sr, seconds=.2)
    p = P.validate_params('formant_shift',dict(shift_cents=300,window=nominal))
    y, _, stats = FS.raw_formant_shift(pulse, sr, p)
    assert H.latency(y)-round(.01*sr) == S.window_samples(nominal,sr)
    assert stats['latency_compensated'] is False


@pytest.mark.parametrize('method', ['cepstrum','true_env','lpc'])
def test_formant_shift_vowel_peaks_and_harmonic_frequencies(method):
    sr = 16000
    x = H.vowel(150, formants_hz=(700,1200,2600), sr=sr, seconds=1.4)
    y = direct('formant_shift',x,dict(shift_cents=300,envelope=method))[0]
    peaks = envelope_peaks(y,sr,np.array([700,1200,2600])*2**.25)
    error = np.max(abs(peaks/(np.array([700,1200,2600])*2**.25)-1))
    cents = pitch_error(y[4000:-4000],sr,150)
    print('FS-vowel',method,'peaks',peaks.tolist(),'relative_error',float(error),'cents',cents)
    assert abs(cents) <= 1
    # Individual strong harmonic bins stay on their original frequency grid.
    spec = abs(fft.rfft(y[4000:20000,0]*np.hanning(16000),workers=1))
    f = fft.rfftfreq(16000,1/sr)
    for harmonic in [4,5,8,17]:
        sel = (f >= 150*harmonic-5) & (f <= 150*harmonic+5)
        assert abs(1200*np.log2(f[sel][np.argmax(spec[sel])]/(150*harmonic))) <= 1
    assert error <= .03


@pytest.mark.parametrize('method',['cepstrum','true_env','lpc'])
def test_formant_noise(method):
    x = H.white_noise(-18,sr=16000,seconds=1.)
    y = direct('formant_shift',x,dict(shift_cents=300,envelope=method))[0]
    change = H.rms_dbfs(y)-H.rms_dbfs(x)
    print('FS-noise',method,change)
    assert abs(change) <= 1


@pytest.mark.parametrize('method',['cepstrum','true_env','lpc'])
def test_formant_s4(method):
    x = H.sine(1000,-12,sr=16000,seconds=1.)
    y = direct('formant_shift',x,dict(shift_cents=300,envelope=method))[0]
    ripple = periodic_ripple(y,16000,1000)
    print('FS-S4',method,ripple)
    assert ripple <= .05


@pytest.mark.parametrize('sr', [16000,44100,48000,96000])
def test_pitch_marks_and_psola_unity_length_f0(sr):
    x = H.sine(220,-12,sr=sr,seconds=.6,channels=2)
    tr = fixed_track(len(x),sr,220)
    marks = B.pitch_marks(x,sr,tr)
    period_error = np.max(abs(np.diff(marks)[2:-2]-sr/220))
    assert period_error < .05
    assert H.null(x,B.td_psola(x,sr,1,tr))['bit_identical']
    y = B.td_psola(x,sr,2**(5/12),tr)
    assert y.shape == x.shape and y.dtype == np.float64
    error = pitch_error(y[round(.15*sr):-round(.15*sr)],sr,220*2**(5/12))
    print('PSOLA-sr',sr,error)
    assert abs(error) <= 3


def test_psola_pt3_pt5_pt6_and_envelope_donor():
    sr = 16000
    x = H.sine(440,-12,sr=sr,seconds=1.)
    y = B.td_psola(x,sr,2**(5/12),fixed_track(len(x),sr,440))
    ripple = periodic_ripple(y,sr,440*2**(5/12))
    assert ripple <= .5
    x = H.vowel(100,formants_hz=(700,1200,2600),sr=sr,seconds=1.)
    y = B.td_psola(x,sr,2**(5/12),fixed_track(len(x),sr,100))
    peaks = envelope_peaks(y,sr,[700,1200,2600])
    print('PSOLA-PT6',peaks.tolist(),'ripple',ripple)
    assert np.max(abs(peaks/np.array([700,1200,2600])-1)) <= .03
    clicks = np.zeros((sr//2,1)); clicks[800::1600] = .2
    # With no voiced pitch, transients pass unchanged rather than smear.
    tr = fixed_track(len(clicks),sr,100)
    tr.voiced[:] = False
    assert H.null(clicks,B.td_psola(clicks,sr,1.5,tr))['bit_identical']
    donor = H.vowel(100,formants_hz=(800,1500,3000),sr=sr,seconds=1.)
    z,n = B.shift_envelope(x,sr,0,target=donor)
    assert z.shape == x.shape and n > 0 and not np.array_equal(x,z)


def test_scale_ties_masks_note_hysteresis():
    major = B.scale_notes('C','major')
    assert B.nearest_note(61,major) == 60
    mask = [1,0,0,0,1,0,0,1,0,0,0,0]
    assert set(B.scale_notes('D','custom',mask)%12) == {2,6,9}
    with pytest.raises(ParamError):
        B.scale_notes('C','custom',[0]*12)
    x = np.concatenate([H.vowel(220,sr=16000,seconds=.25),H.vowel(246.94165,sr=16000,seconds=.25)])
    tr, notes = B.track_notes(x,16000)
    print('note-boundaries',notes)
    assert all(n['end_sample'] > n['start_sample'] for n in notes)
    assert any(abs(n['pitch_midi']-57) <= .06 for n in notes)
    assert any(abs(n['pitch_midi']-59) <= .06 for n in notes)
    assert tr.hop_samples == round(16000*256/48000)


@pytest.mark.parametrize('formant',[False,True])
def test_correct_detuned_vowel_and_repeat(formant):
    sr = 16000
    x = H.vowel(220*2**(.3/12),sr=sr,seconds=1.)
    p = dict(formant=formant,retune_ms=80,transition_ms=0,keep_vibrato=0)
    y,_,stats = direct('pitch_correct',x,p)
    error = pitch_error(y[5000:-2000],sr,220)
    print('PC-detune',formant,error,stats)
    assert abs(error) <= 5
    assert stats['notes'] and 0 <= stats['untouched_fraction'] <= 1
    assert np.array_equal(y,direct('pitch_correct',x,p)[0])


def test_retune_tau_custom_targets_tolerance_transition():
    sr, frames = 16000, 16000
    tr = fixed_track(frames,sr,220*2**(.3/12))
    note = dict(start_sample=0,end_sample=frames,t0=0,t1=1,pitch_midi=57.3,confidence=1.)
    p = P.validate_params('pitch_correct',dict(transition_ms=0,keep_vibrato=0))
    cents,notes,_ = PC.correction_curve(tr,[note],frames,p)
    at_tau = abs(cents[round(.08*sr)-tr.hop_samples])/.3/100
    print('PC-tau',at_tau)
    assert at_tau == pytest.approx(1-np.exp(-1),rel=.2)
    assert notes[0]['target_midi'] == 57
    p.update(scale='custom',scale_mask=[1,0,0,0,1,0,0,1,0,0,0,0],retune_ms=0)
    _,records,_ = PC.correction_curve(tr,[note],frames,p)
    assert records[0]['target_midi']%12 in (0,4,7)
    p.update(targets=[[.2,58],[.8,58]])
    cents,_,_ = PC.correction_curve(tr,[note],frames,p)
    assert np.median(cents[4000:12000]) == pytest.approx(70,abs=1e-8)
    p.update(scale='chromatic',targets=[],tolerance_cents=50)
    assert np.max(abs(PC.correction_curve(tr,[note],frames,p)[0])) == 0
    p.update(tolerance_cents=0,transition_ms=60)
    cents,_,_ = PC.correction_curve(tr,[note],frames,p)
    assert cents[0] == 0 and abs(cents[100]) < abs(cents[1000])


@pytest.mark.parametrize('keep',[0.,1.])
def test_correct_vibrato_audio(keep):
    sr = 8000
    t = np.arange(2*sr)/sr
    input_cents = 30+40*np.sin(2*np.pi*5*t)
    x = H.vowel(220*2**(input_cents/1200),sr=sr,seconds=2.)
    y = direct('pitch_correct',x,dict(keep_vibrato=keep,transition_ms=0),sr)[0]
    times = np.arange(.5,1.5,.02)
    observed = np.array([pitch_error(y[round((s-.012)*sr):round((s+.012)*sr)],sr,220) for s in times])
    fit = np.linalg.lstsq(np.column_stack([np.ones(len(times)),np.sin(2*np.pi*5*times),np.cos(2*np.pi*5*times)]),observed,rcond=None)[0]
    amplitude = float(np.hypot(fit[1],fit[2]))
    print('PC-vibrato',keep,'center',float(fit[0]),'amplitude',amplitude)
    assert abs(fit[0]) <= 5
    assert amplitude >= 32 if keep else amplitude <= 12


def test_correct_unvoiced_and_targets_audio():
    sr = 8000
    for x in (np.zeros((sr//2,1)),H.white_noise(-18,sr=sr,seconds=.5)):
        y,_,stats = direct('pitch_correct',x,sr=sr)
        assert H.null(x,y)['peak_dbfs'] <= -120
        assert stats['untouched_fraction'] == 1
    x = H.vowel(220,sr=sr,seconds=1.)
    y = direct('pitch_correct',x,dict(targets=[[.2,58],[.8,58]],retune_ms=0,transition_ms=0),sr)[0]
    error = pitch_error(y[3000:5000],sr,220*2**(1/12))
    print('PC-target',error)
    assert abs(error) <= 5


def test_harmony_c_major_five_note_melody(enabled):
    sr, duration = 8000,.4
    input_midi, expected = [60,62,64,65,67],[64,65,67,69,71]
    x = np.concatenate([H.vowel(440*2**((n-69)/12),sr=sr,seconds=duration) for n in input_midi])
    p = dict(humanize_cents=0,humanize_ms=0,delay_ms=[0],dry_db=-90,level_db=[0])
    y = render('harmony_voices',x,p,sr)
    errors = []
    for i,n in enumerate(expected):
        lo,hi = round((i*duration+.13)*sr),round((i*duration+.32)*sr)
        errors.append(pitch_error(y[lo:hi],sr,440*2**((n-69)/12)))
    print('HV-major',errors)
    assert max(abs(np.asarray(errors))) <= 10


def test_harmony_delay_pan_level_and_seed(enabled):
    sr = 8000
    x = H.vowel(220,sr=sr,seconds=.5,channels=2)
    base = dict(degrees=[0],humanize_cents=0,humanize_ms=0,delay_ms=[0],level_db=[0],dry_db=-90)
    y = render('harmony_voices',x,base,sr)
    z = render('harmony_voices',x,{**base,'delay_ms':[30],'level_db':[-6],'pan':[1]},sr)
    dry = x*10**(-90/20)
    assert np.max(abs(z[:,0]-dry[:,0])) == 0
    np.testing.assert_allclose((z-dry)[240:,1],(y-dry)[:-240,1]*10**(-6/20),atol=1e-12)
    p = dict(degrees=[2],level_db=[0])
    a = render('harmony_voices',x,p,sr,seed=5,item='a')
    assert np.array_equal(a,render('harmony_voices',x,p,sr,seed=5,item='a'))
    for seed,item,ps in [(6,'a',p),(5,'b',p),(5,'a',{**p,'seed':1})]:
        assert not np.array_equal(a,render('harmony_voices',x,ps,sr,seed=seed,item=item))


def test_talkbox_formants_fundamental_and_stability():
    sr = 16000
    x = H.vowel(150,formants_hz=(700,1200,2600),sr=sr,seconds=1.2)
    p = dict(notes=[48],carrier='saw',unvoiced=0,tube=0,driver_db=0)
    y = direct('talkbox',x,p)[0]
    peaks = envelope_peaks(y,sr,[700,1200,2600])
    error = pitch_error(y[4000:-2000],sr,440*2**((48-69)/12))
    print('TB-formants',peaks.tolist(),'cents',error)
    assert np.max(abs(peaks/np.array([700,1200,2600])-1)) <= .05
    assert abs(error) <= 3
    centers,ks,gains = B.lpc_frames(x,sr)
    for j in range(len(ks)-1):
        for fraction in [0,.25,.5,.75,1]:
            a = B.interpolate_lpc(ks[j,:,0],ks[j+1,:,0],fraction)
            assert np.max(abs(np.roots(a))) < 1
    assert np.all(gains >= 0)


def test_talkbox_frame_boundary_ripple():
    sr = 16000
    x = H.vowel(150,sr=sr,seconds=1.2)
    y = direct('talkbox',x,dict(notes=[48],carrier='saw',unvoiced=0,tube=0,driver_db=0))[0]
    ripple = periodic_ripple(y,sr,440*2**((48-69)/12))
    print('TB-frame-ripple',ripple)
    assert ripple <= .2


@pytest.mark.parametrize('name',MODULES)
def test_common_contracts(enabled,name):
    def probe(x,y,sr,p):
        measured = H.fundamental_frequency(y[len(y)//4:3*len(y)//4],sr,low_hz=900,high_hz=1100)
        return dict(passed=abs(measured-1000) <= 1,frequency_hz=measured)
    # Neutral plumbing is tested at every supported sample rate/channel count;
    # active acoustic behavior is measured separately above.
    results = H.assert_common_tests(name,params=NEUTRAL[name],neutral=NEUTRAL[name],seconds=.08,
        stages=['track'] if name in ('pitch_correct','harmony_voices') else ['track','bus'],
        sr_probe=probe,latency_params=NEUTRAL[name])
    assert all(r['passed'] for r in results.values())


DEFAULTS = {
 'formant_shift':dict(shift_cents=0,envelope='true_env',order=40,lo_hz=100,hi_hz=10000,window=2048,mix=1),
 'pitch_correct':dict(key='C',scale='chromatic',scale_mask=[],a4_hz=440,retune_ms=80,amount=1,
    tolerance_cents=0,keep_vibrato=.7,transition_ms=60,formant=True,lo_hz=70,hi_hz=1000,min_confidence=.6,targets=[]),
 'harmony_voices':dict(key='C',scale='major',scale_mask=[],a4_hz=440,degrees=[2],level_db=[],pan=[],delay_ms=[],
    humanize_cents=6,humanize_ms=8,formant=True,dry_db=0,seed=0),
 'talkbox':dict(carrier='saw_noise',notes=[48,55,60,64],notes_curve=[],a4_hz=440,mix=1,output_db=0,seed=0,
    order=24,frame_ms=20,tube=.5,driver_db=6,emphasis=.5,unvoiced=.3)}


@pytest.mark.parametrize('name',MODULES)
def test_defaults_endpoints_enums_and_rejection(enabled,name):
    assert P.validate_params(name,{}) == DEFAULTS[name]
    spec = P.describe(name)
    assert spec['backends'] == ['reference'] and spec['master_slot'] is None
    assert spec['offline_only'] == (name in ('pitch_correct','harmony_voices'))
    x = H.vowel(220,sr=8000,seconds=.035,channels=2)
    np.testing.assert_array_equal(direct(name,x,sr=8000)[0],direct(name,x,DEFAULTS[name],8000)[0])
    for s in spec['params']:
        if s['type'] in ('float','int','float_array'):
            for value in [s['min'],s['max']]:
                params = {s['id']: [value] if s['type'] == 'float_array' else value}
                if s['id'] == 'scale_mask':
                    params[s['id']] = [value]*12
                if s['id'] == 'lo_hz' and name == 'pitch_correct':
                    params['hi_hz'] = 2000
                if s['id'] == 'hi_hz' and name == 'pitch_correct':
                    params['lo_hz'] = 40
                if s['id'] in ('level_db','pan','delay_ms') and name == 'harmony_voices':
                    params['degrees'] = [2]
                # Fractional binary-mask endpoints are rejected separately.
                y = direct(name,x,params,8000)[0]
                assert y.shape == x.shape and np.isfinite(y).all()
        elif s['type'] in ('enum','bool'):
            for value in s.get('choices',[False,True]):
                params = {s['id']:value}
                if s['id'] == 'scale' and value == 'custom':
                    params['scale_mask'] = [1]+[0]*11
                y = direct(name,x,params,8000)[0]
                assert np.isfinite(y).all()
    with pytest.raises(ParamError):
        P.validate_params(name,{'unknown':1})


@pytest.mark.parametrize('params',[
 {'scale':'custom'}, {'scale':'custom','scale_mask':[0]*12}, {'scale_mask':[1]*11},
 {'scale_mask':[.5]*12}, {'lo_hz':400,'hi_hz':200},
 {'targets':[[.2,60],[.1,62]]}, {'targets':[[0,128]]}])
def test_correct_invalid(params):
    with pytest.raises(ParamError):
        P.validate_params('pitch_correct',params)


@pytest.mark.parametrize('params',[{'degrees':[.5]},{'degrees':[1,2],'pan':[0]},
 {'degrees':[1,2],'delay_ms':[0]},{'degrees':[1,2],'level_db':[-6]},
 {'scale':'chromatic'},{'scale':'custom','scale_mask':[0]*12}])
def test_harmony_invalid(params):
    with pytest.raises(ParamError):
        P.validate_params('harmony_voices',params)


@pytest.mark.parametrize('name',MODULES)
def test_tv_registration_and_public_availability(name):
    from mankomix.director.direction import TIME_VARYING
    assert (name in TIME_VARYING) == (name != 'formant_shift')
    if not P.PROCESSORS[name]['implemented']:
        with pytest.raises(ChainError,match='not implemented|not_implemented'):
            render(name,np.zeros((100,1)))


def test_invalid_bb_inputs():
    for call in [lambda:B.reflection_to_lpc([1]),lambda:B.lpc_to_reflection([1,2]),
                 lambda:B.interpolate_lpc([.2],[.3],1.1),lambda:B.lpc([np.nan],8),
                 lambda:B.spectral_envelope(np.ones(20),48000,'invalid'),
                 lambda:B.envelope_transfer([-1],[1])]:
        with pytest.raises(ParamError):
            call()


@pytest.mark.parametrize('name',['pitch_correct','harmony_voices'])
def test_processor_formant_preservation(name):
    sr = 8000
    hz = 440*2**((43-69)/12)
    x = H.vowel(hz,formants_hz=(700,1200,2600),sr=sr,seconds=1.)
    if name == 'pitch_correct':
        params = dict(targets=[[0,48]],retune_ms=0,transition_ms=0)
    else:
        params = dict(degrees=[3],humanize_cents=0,humanize_ms=0,delay_ms=[0],level_db=[0],dry_db=-90)
    y = direct(name,x,params,sr)[0]
    peaks = envelope_peaks(y,sr,[700,1200,2600])
    print('processor-PT6',name,peaks.tolist())
    assert np.max(abs(peaks/np.array([700,1200,2600])-1)) <= .03


@pytest.mark.parametrize('sr',[44100,48000,96000])
def test_active_correction_at_supported_rates(sr):
    x = H.vowel(220*2**(.3/12),sr=sr,seconds=.2,channels=2)
    y = direct('pitch_correct',x,dict(retune_ms=0,transition_ms=0),sr)[0]
    error = pitch_error(y[round(.08*sr):round(.16*sr)],sr,220)
    print('PC-active-sr',sr,error)
    assert abs(error) <= 5
    assert y.shape == x.shape and np.array_equal(y[:,0],y[:,1])


@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.parametrize('name',MODULES)
def test_active_fullscale_silence_empty_and_repeat(sr,name):
    x = np.random.Generator(np.random.PCG64(818)).choice([-1.,1.],size=(round(.025*sr),2))
    p = {'formant_shift':dict(shift_cents=1200,order=80),
         'pitch_correct':dict(amount=1),
         'harmony_voices':dict(degrees=[-14,0,7,14],level_db=[6]*4),
         'talkbox':dict(order=48,driver_db=24,emphasis=1,output_db=24)}[name]
    y = direct(name,x,p,sr)[0]
    assert np.isfinite(y).all() and y.shape == x.shape
    for size in [0,1,97]:
        silence = np.zeros((size,2))
        z = direct(name,silence,p,sr)[0]
        assert z.shape == silence.shape and np.max(abs(z),initial=0) == 0


def test_talkbox_carriers_seed_tube_and_output(enabled):
    sr = 8000
    x = H.vowel(150,sr=sr,seconds=.3)
    for carrier in ['saw','pulse','noise','saw_noise']:
        p = dict(carrier=carrier,notes=[48],tube=0,unvoiced=0)
        y = render('talkbox',x,p,sr,seed=12)
        assert np.array_equal(y,render('talkbox',x,p,sr,seed=12))
        if carrier in ('noise','saw_noise'):
            for changed in [render('talkbox',x,p,sr,seed=13),render('talkbox',x,p,sr,seed=12,item='other'),
                            render('talkbox',x,{**p,'seed':1},sr,seed=12)]:
                assert not np.array_equal(y,changed)
    base = dict(carrier='saw',notes=[48],tube=0,unvoiced=0)
    y = render('talkbox',x,base,sr)
    z = render('talkbox',x,{**base,'output_db':6},sr)
    np.testing.assert_allclose(z,y*10**(.3),atol=1e-14)
    tube = render('talkbox',x,{**base,'tube':1},sr)
    assert H.band_level(tube,sr,0,200)['rms'] < H.band_level(y,sr,0,200)['rms']


def test_lpc_short_frame_stability_and_ripple():
    sr = 16000
    x = H.vowel(150,sr=sr,seconds=.8)
    y = direct('talkbox',x,dict(notes=[48],carrier='saw',frame_ms=10,tube=0,unvoiced=0,driver_db=0))[0]
    ripple = periodic_ripple(y,sr,440*2**((48-69)/12),guard=.25)
    print('TB-short-frame-ripple',ripple)
    assert ripple <= .2


def test_custom_scale_targets_boundaries_and_four_voices(enabled):
    sr = 8000
    x = H.vowel(220,sr=sr,seconds=.5)
    mask = [1,0,0,0,1,0,0,1,0,0,0,0]
    y,_,stats = direct('pitch_correct',x,dict(scale='custom',scale_mask=mask,retune_ms=0,transition_ms=0),sr)
    targets = [n['target_midi'] for n in stats['notes']]
    assert targets and all(t%12 in (0,4,7) for t in targets)
    target = targets[len(targets)//2]
    assert abs(pitch_error(y[1600:3200],sr,440*2**((target-69)/12))) <= 5
    p = dict(degrees=[-14,-3,2,14],pan=[-1,-.5,.5,1],level_db=[-12]*4)
    y = render('harmony_voices',x,p,sr)
    assert y.shape == (len(x),2) and np.isfinite(y).all()
    assert H.null(x,render('harmony_voices',x,dict(degrees=[]),sr))['bit_identical']


def test_correction_time_constant_from_audio():
    sr = 16000
    x = H.vowel(220*2**(.3/12),sr=sr,seconds=1.)
    y = direct('pitch_correct',x,dict(retune_ms=80,keep_vibrato=0,transition_ms=0),sr)[0]
    terminal = pitch_error(y[10000:14000],sr,220)
    times = np.arange(.05,.27,.02)
    error = np.array([pitch_error(y[round((s-.015)*sr):round((s+.015)*sr)],sr,220) for s in times])
    residual = error-terminal
    use = residual > 1
    slope = np.polyfit(times[use],np.log(residual[use]),1)[0]
    tau = float(-1/slope)
    print('PC-audio-tau',tau,'residual',residual.tolist())
    assert tau == pytest.approx(.08,rel=.2)


BOUNDS = {
 'formant_shift':dict(shift_cents=(-1200,1200),order=(8,80),lo_hz=(0,500),hi_hz=(2000,20000),mix=(0,1)),
 'pitch_correct':dict(scale_mask=(0,1),a4_hz=(400,480),retune_ms=(0,500),amount=(0,1),
    tolerance_cents=(0,50),keep_vibrato=(0,1),transition_ms=(0,300),lo_hz=(40,400),hi_hz=(200,2000),min_confidence=(0,1)),
 'harmony_voices':dict(scale_mask=(0,1),a4_hz=(400,480),degrees=(-14,14),level_db=(-60,6),pan=(-1,1),
    delay_ms=(0,60),humanize_cents=(0,30),humanize_ms=(0,40),dry_db=(-90,6),seed=(0,65535)),
 'talkbox':dict(notes=(0,127),a4_hz=(400,480),mix=(0,1),output_db=(-24,24),seed=(0,65535),
    order=(8,48),frame_ms=(10,40),tube=(0,1),driver_db=(0,24),emphasis=(0,1),unvoiced=(0,1))}


@pytest.mark.parametrize('name',MODULES)
def test_independent_bounds_and_arrays(name):
    specs = {s['id']:s for s in P.describe(name)['params']}
    for key,(lo,hi) in BOUNDS[name].items():
        assert (specs[key]['min'],specs[key]['max']) == (lo,hi)
        for outside in [lo-1,hi+1]:
            params = {key:[outside] if specs[key]['type'] == 'float_array' else outside}
            with pytest.raises(ParamError):
                P.validate_params(name,params)
    for key in ('scale_mask','degrees','level_db','pan','delay_ms','notes'):
        if key not in specs:
            continue
        limit = 12 if key == 'scale_mask' else 8 if key == 'notes' else 4
        assert specs[key]['max_len'] == limit
        with pytest.raises(ParamError):
            P.validate_params(name,{key:[0]*(limit+1)})


@pytest.mark.parametrize('name,key,limit',[('pitch_correct','targets',4096),('talkbox','notes_curve',1024)])
def test_curve_capacity_endpoints_and_zero_state(name,key,limit):
    points = [[i/(limit-1),127*i/(limit-1)] for i in range(limit)]
    params = P.validate_params(name,{key:points})
    assert params[key] == points
    with pytest.raises(ParamError):
        P.validate_params(name,{key:points+[[2,127]]})
    if name == 'pitch_correct':
        x = H.vowel(220,sr=16000,seconds=.1)
        y = direct(name,x,dict(targets=[[0,0],[.1,127]],retune_ms=0,transition_ms=0))[0]
        assert np.isfinite(y).all() and y.shape == x.shape
    else:
        from mankomix.dspx.bb.band_envelopes import carrier
        car = carrier(1600,16000,params)
        assert np.isfinite(car).all() and car.shape == (1600,1)


@pytest.mark.parametrize('formant',[False,True])
def test_pitch_nyquist_combination_rejection(formant):
    sr = 8000
    x = H.vowel(220,sr=sr,seconds=.2)
    for name,params in [('pitch_correct',dict(targets=[[0,127]],retune_ms=0,transition_ms=0)),
                        ('harmony_voices',dict(scale='custom',scale_mask=[1]+[0]*11,degrees=[14],
                            humanize_cents=0,humanize_ms=0))]:
        with pytest.raises(ParamError,match='Nyquist'):
            direct(name,x,{**params,'formant':formant},sr)
    # The same top MIDI target is representable at 48 kHz.
    x = H.vowel(220,sr=48000,seconds=.1)
    y = direct('pitch_correct',x,dict(targets=[[0,127]],retune_ms=0,transition_ms=0),48000)[0]
    assert y.shape == x.shape and np.isfinite(y).all()


@pytest.mark.parametrize('formant',[False,True])
def test_low_confidence_voicing_boundaries_are_exact(formant):
    sr = 8000
    x = H.vowel(220,sr=sr,seconds=.5)
    tr = fixed_track(len(x),sr,220)
    holes = (tr.samples >= 1200) & (tr.samples <= 2400)
    tr.probability[holes] = 0
    cents = np.full(len(x),100.)
    cents[1200:2401] = 0
    y = PC.apply_correction(x,sr,cents,tr,formant)
    from mankomix.dspx.bb.pitch import sample_pitch
    _,_,confidence = sample_pitch(tr,np.arange(len(x)))
    assert np.array_equal(x[confidence < .6],y[confidence < .6])
