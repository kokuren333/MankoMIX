"""W4f alignment/quantization acceptance; every project/audio is temporary."""
import copy
import json
import shutil
from types import SimpleNamespace
import numpy as np
import pytest
from scipy import signal
from mankomix.core.project import Project
from mankomix.director import commands as C, derived as B, edit as E, xops as X, direction as D
from mankomix.director.xops import _alignment as A, edit_quantize as Q
from mankomix.dspx.bb import dtw
from mankomix.dspx.bb.alignment_warp import schedule, warp
from tests import test_upgrade2_duck as T, toolimpl_harness as H
from tests.test_tk_w4_0 import move, doc


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path/'home'))


def syllables(sr=24000, count=16, shift=True, detune=False):
    duration = count*.36+.4
    t = np.arange(round(sr*duration))/sr
    true = t+.080*np.sin(2*np.pi*t/duration)
    guide, target = np.zeros(len(t)), np.zeros(len(t))
    starts = .2+np.arange(count)*.36
    for i, start in enumerate(starts):
        freq = 180*2**((i % 5)/12)
        def tone(clock,cents=0):
            local = clock-start
            env = np.where((local>=0)&(local<.30), np.minimum(1,np.maximum(0,local)/.004)*np.exp(-np.maximum(0,local)/.14), 0)
            # Distinct spectral syllables, with the same periodic source pitch.
            return env*sum(np.sin(2*np.pi*freq*2**(cents/1200)*k*(t-start)+.2*k)/(k*(1+abs(k-(i%4+2)))) for k in range(1,13))*.12
        guide += tone(t)
        target += tone(true if shift else t, (40 if i%2 else -40) if detune else 0)
    return target[:,None], guide[:,None], true*sr, starts


def drums(sr=24000, count=64, strength_seed=3):
    rng=np.random.Generator(np.random.PCG64(strength_seed))
    grid=.25+np.arange(count)*.125
    shifts=rng.uniform(-.025,.025,count)
    n=round((grid[-1]+.3)*sr)
    x=np.zeros((n,2))
    for i,start in enumerate(grid+shifts):
        a=round(start*sr)
        u=np.arange(round(.065*sr))/sr
        hit=.3*np.exp(-u/0.012)*(np.sin(2*np.pi*170*u)+.3*rng.standard_normal(len(u)))
        hit[0]=.4
        x[a:a+len(u),0]+=hit
        x[a:a+len(u),1]+=hit*.5
    return x, grid, shifts


def make(tmp_path, audio):
    return T._make(tmp_path/'song', audio)


def apply(root, m, name='dir_w4f'):
    return X.apply_edit(root, {'id':name}, m, X.OPS[m['op']], actor='human')


def test_time_known_map_and_audio():
    x,g,truth,starts=syllables()
    p=A.resolve({'params':{'tightness':1,'protect_sustain':.5}})
    result=dtw.alignment(x,g,T.SR,p)
    knots=np.array(result['map'])
    active=np.max(abs(x),axis=1)>.008
    estimated=np.interp(np.arange(len(x)),knots[:,0],knots[:,1])
    rms=np.sqrt(np.mean((estimated[active]-truth[active])**2))/T.SR*1000
    y=warp(x,T.SR,schedule(x,T.SR,result['map']))
    from mankomix.dspx.bb.onsets import detect_onsets
    on=detect_onsets(y,T.SR,kind='soft')
    errors=[min(abs(e['time_s']-s) for e in on)*1000 for s in starts]
    print(json.dumps({'map_rms_ms':rms,'onset_median_ms':float(np.median(errors)),'onset_max_ms':max(errors)}))
    assert rms<=12
    assert np.median(errors)<=10 and max(errors)<=25
    np.testing.assert_array_equal(y,warp(x,T.SR,schedule(x,T.SR,result['map'])))


@pytest.mark.parametrize('feature',['both','spectral','onset_env'])
def test_identity_silence_and_anchor(feature):
    x,g,truth,_=syllables(count=4,shift=False)
    p=A.resolve({'params':{'feature':feature}})
    r=dtw.alignment(x,g,T.SR,p)
    assert r['identity'] and r['shift_ms']['max']<=3
    zero=np.zeros_like(x)
    assert dtw.alignment(zero,zero,T.SR,p)['identity']
    p.update(anchors=[[.6,.64]],tightness=.5,protect_sustain=0)
    # Use a continuous voiced fixture so the fixed point is not in joint silence.
    t=np.arange(T.SR*2)/T.SR
    continuous=(.1*np.sin(2*np.pi*220*t))[:,None]
    r=dtw.alignment(continuous,continuous,T.SR,p)
    k=np.array(r['map'])
    assert abs(np.interp(.6*T.SR,k[:,0],k[:,1])-.64*T.SR)<=.001*T.SR
    slopes=np.diff(k[:,1])/np.diff(k[:,0])
    assert slopes.min()>=.5-1e-8 and slopes.max()<=2+1e-8


@pytest.mark.parametrize('op,params',[('edit_align_time',{'guide':'trk_vocals','tightness':0}),
    ('edit_align_time',{'guide':'trk_vocals'}),('edit_align_pitch',{'guide':'trk_vocals','pitch_tightness':0,'tightness':0}),
    ('edit_quantize',{'bpm':120,'strength':0})])
def test_group_neutral_no_assets(tmp_path,op,params):
    t=np.arange(T.SR)/T.SR
    x=(.1*np.sin(2*np.pi*220*t))[:,None]
    root=make(tmp_path,{'bass':x,'vocals':x*.5,'drums':x*.3})
    before=Project.open(root).data
    m=move(op,**params,group=['trk_drums'])
    validated=D.validate(doc(tmp_path,[m]),root)
    assert validated['ok'], validated['errors']
    r=apply(root,m)
    after=Project.open(root).data
    assert r['kind']=='derived_group'
    assert B._ledger(root,'dir_w4f')['derived_groups']['m01']['plan_kind']=='clip'
    assert before['assets']==after['assets'] and before['tracks']==after['tracks']
    assert not (root/'cache'/'derived').exists()
    assert B.regenerate_group(root,'dir_w4f','m01')=={}
    E.revert(root,'dir_w4f',actor='human')
    assert Project.open(root).data['tracks']==before['tracks']


@pytest.mark.parametrize('strength',[0,.35,.7,1])
def test_quantize_64_hits(tmp_path,strength):
    x,grid,jitter=drums()
    root=make(tmp_path,{'bass':x,'vocals':x*.5})
    plan=Q.derive(root,move('edit_quantize',bpm=120,origin_s=0,strength=strength,min_shift_ms=0,threshold_db=-60,fill='silence'))
    rows=plan.record['onsets']
    assert len(rows)==64
    if strength==0:
        assert isinstance(plan,X.ClipPlan)
        return
    y=Q.calculate(x,T.SR,plan.params)
    from mankomix.dspx.bb.drum_events import drum_onsets
    events=drum_onsets(y,T.SR)
    assert len(events)==64
    original=np.array([r['sample'] for r in rows])
    expected=original+np.rint(strength*(np.array([r['grid_sample'] for r in rows])-original))
    # Measure the copied physical attacks independently of the detector's FFT grid.
    physical=np.rint((grid+jitter)*T.SR).astype(int)+np.array([r['shift_samples'] for r in rows])
    actual=np.array([max(0,s-120)+np.flatnonzero(np.max(abs(y[max(0,s-120):s+120]),axis=1)>1e-8)[0] for s in physical])
    errors=abs(actual-expected)/T.SR*1000
    print(json.dumps({'strength':strength,'hits':len(rows),'max_error_ms':float(errors.max())}))
    assert errors.max()<=2 if strength<1 else errors.max()<=1
    mapping=plan.params['mapping']
    for i,(a,b,shift) in enumerate(zip(mapping['cuts'][:-1],mapping['cuts'][1:],mapping['shifts'])):
        lo,hi=a+round(.010*T.SR),b-round(.010*T.SR)
        if i+1<len(mapping['shifts']):
            hi=min(hi,b+mapping['shifts'][i+1]-shift-round(.010*T.SR))
        if hi>lo and 0<=lo+shift<hi+shift<=len(y):
            np.testing.assert_array_equal(y[lo+shift:hi+shift],x[lo:hi])


def test_query_readonly_cli_and_mcp(tmp_path,capsys):
    from mankomix.cli import main as cli
    t=np.arange(T.SR)/T.SR
    x=(.1*np.sin(2*np.pi*220*t))[:,None]
    root=make(tmp_path,{'bass':x,'vocals':x*.5})
    argv=['direction','query','align_time','--project',str(root),'--target','trk_bass','--guide','trk_vocals']
    before=C._snapshot(root)
    assert cli.main(argv)==0
    first=capsys.readouterr().out
    assert cli.main(argv)==0
    assert first==capsys.readouterr().out
    assert C._snapshot(root)==before
    result=json.loads(first)
    assert result['confidence']=='high' and result['alignment']['identity']
    assert C.cli_only()['direction query align_time'][0]=='direction_query_align_time'
    print(json.dumps({'readonly_project_snapshot_equal':True,'repeat_json_identical':True}))


@pytest.mark.parametrize('op,extra',[('edit_align_time',{'guide':'trk_vocals'}),('edit_align_pitch',{'guide':'trk_vocals'}),('edit_quantize',{'bpm':120})])
@pytest.mark.parametrize('bad',[{'unknown':1},{'group':[{}]},{'section':{'t0_s':0,'t1_s':99999}}, {'max_shift_ms':float('nan')}])
def test_validator_malformed(tmp_path,op,extra,bad):
    errors=[]
    A.validate(move(op,**(extra|bad)),X.ValidationContext(None,{},'',lambda w,c,m:errors.append((c,m))),pitch=op.endswith('pitch'),quantize=op.endswith('quantize'))
    # Context-free validation accepts finite section bounds; runtime checks project bounds.
    if 'section' not in bad:
        assert errors


def test_quantize_restrictions_and_grid():
    assert Q.nearest(3000,T.SR,dict(grid_note='1/16',bpm=120,origin_s=0,swing=0))==3000
    assert Q.nearest(1500,T.SR,dict(grid_note='1/16',bpm=120,origin_s=0,swing=0))==0
    assert Q.nearest(4500,T.SR,dict(grid_note='1/16',bpm=120,origin_s=0,swing=.5))==4500
    errors=[]
    A.validate(move('edit_quantize',bpm=120,only=['o_100']),X.ValidationContext(None,{},'',lambda w,c,m:errors.append(m)),quantize=True)
    assert any('explicit detector' in e for e in errors)


def pitch_fixture(sr=24000, seconds=1.2, detune=40, harmony=0, vibrato=0):
    t=np.arange(round(sr*seconds))/sr
    hz=220*2**((harmony+detune/100+vibrato/100*np.sin(2*np.pi*5*t))/12)
    phase=np.cumsum(hz)/sr*2*np.pi
    x=.12*(np.sin(phase)+.3*np.sin(2*phase)+.15*np.sin(3*phase))
    return x[:,None]


def frequency(x,sr):
    # Independent zero-crossing phase regression on a narrow fundamental band.
    sos=signal.butter(3,[140,400],fs=sr,btype='bandpass',output='sos')
    y=signal.sosfiltfilt(sos,x[:,0])
    phase=np.unwrap(np.angle(signal.hilbert(y)))
    a,b=round(.2*sr),len(x)-round(.2*sr)
    return np.polyfit(np.arange(a,b)/sr,phase[a:b],1)[0]/(2*np.pi)


@pytest.mark.parametrize('harmony,interval',[(0,'unison'),(4,'auto'),(3,'auto'),(-3,-3)])
def test_pitch_alignment_cents(harmony,interval):
    from mankomix.dspx.bb.alignment_warp import synthesize_pitch
    sr=T.SR
    x=pitch_fixture(detune=40,harmony=harmony)
    g=pitch_fixture(detune=0)
    p=A.resolve({'params':{'guide':'trk_guide','interval':interval,'pitch_tightness':1,'time':False}},True)
    mapping=[[0,0],[len(x),len(x)]]
    plan,rows=A.pitch_plan(x,g,sr,p,mapping)
    y=synthesize_pitch(x,sr,plan,x)
    wanted=220*2**(harmony/12)
    error=1200*np.log2(frequency(y,sr)/wanted)
    print(json.dumps({'interval':interval,'harmony':harmony,'pitch_error_cents':float(error),'notes':rows}))
    assert abs(error)<=8
    assert len(y)==len(x) and np.isfinite(y).all()
    np.testing.assert_array_equal(y,synthesize_pitch(x,sr,plan,x))


def test_pitch_limit_and_vibrato():
    from mankomix.dspx.bb.alignment_warp import synthesize_pitch
    sr=T.SR
    g=pitch_fixture(detune=0,seconds=2)
    x=pitch_fixture(detune=140,seconds=2)
    p=A.resolve({'params':{'guide':'trk_guide','interval':'unison','pitch_tightness':1}},True)
    mapping=[[0,0],[len(x),len(x)]]
    plan,rows=A.pitch_plan(x,g,sr,p,mapping)
    assert plan is None and all(r['reason']=='max_cents' for r in rows)
    x=pitch_fixture(detune=40,vibrato=40,seconds=2)
    p.update(keep_vibrato=1,max_cents=100)
    plan,rows=A.pitch_plan(x,g,sr,p,mapping)
    y=synthesize_pitch(x,sr,plan,x)
    def width(z):
        from mankomix.dspx.bb.psola import voice_track
        tr=voice_track(z,sr)
        ix=(tr.samples>.3*sr)&(tr.samples<1.7*sr)&tr.voiced
        cents=1200*np.log2(tr.f0_hz[ix]/220)
        return np.percentile(cents,95)-np.percentile(cents,5)
    before,after=width(x),width(y)
    print(json.dumps({'vibrato_width_before':float(before),'vibrato_width_after':float(after),'retained':float(after/before)}))
    assert after>=.8*before


@pytest.mark.parametrize('mode',['slice','stretch'])
def test_apply_regenerate_group_revert(tmp_path,mode):
    x,_,_=drums(count=8)
    # A one-sample delayed peer tests preservation of an existing mic delay.
    peer=np.r_[np.zeros((1,2)),x[:-1]]*.5
    root=make(tmp_path,{'bass':x,'vocals':peer})
    originals={t:E.raw_track(root,t)[0] for t in ('trk_bass','trk_vocals')}
    before_clips={t['id']:copy.deepcopy(t['clips']) for t in Project.open(root).data['tracks']}
    length=Project.open(root).data['timebase']['length_samples']
    m=move('edit_quantize',bpm=120,strength=1,min_shift_ms=0,threshold_db=-60,mode=mode,group=['trk_vocals'])
    before=C._snapshot(root)
    plan=Q.derive(root,m)
    assert isinstance(plan,X.DerivedBundle) and before==C._snapshot(root)
    result=apply(root,m)
    from mankomix.director.xops import _group
    assert _group.check(root,'dir_w4f','m01',result)
    outputs={t:E.raw_track(root,t)[0] for t in originals}
    from mankomix.dspx.bb.align import estimate_delay
    lag=estimate_delay(outputs['trk_bass'][:,0],outputs['trk_vocals'][:,0],T.SR,max_delay_ms=2)['delay_samples']
    print(json.dumps({'mode':mode,'group_lag_samples':float(lag)}))
    assert abs(lag-1)<= (0.01 if mode=='slice' else 1)
    if mode=='slice':
        def integer_lag(signals):
            corr=signal.correlate(signals['trk_vocals'][:,0],signals['trk_bass'][:,0],method='fft')
            return int(np.argmax(corr)-(len(signals['trk_bass'])-1))
        assert integer_lag(outputs)==integer_lag(originals)==1
    assert Project.open(root).data['timebase']['length_samples']==length
    ledger=B._ledger(root,'dir_w4f')
    saved={}
    for tid,member in result['members'].items():
        row=ledger['derived'][member['move']]
        path=Project.open(root).asset_path(row['result']['asset'])
        saved[tid]=(path,path.read_bytes())
        path.unlink()
        cache=B._cache(root,row['key'])
        cache.unlink();cache.with_suffix('.json').unlink()
    B.regenerate_group(root,'dir_w4f','m01',calculators={t:Q.calculate for t in originals})
    assert all(path.read_bytes()==contents for path,contents in saved.values())
    E.revert(root,'dir_w4f',actor='human')
    assert all(E.raw_track(root,t)[0].tobytes()==originals[t].tobytes() for t in originals)
    assert all(t['clips']==before_clips[t['id']] for t in Project.open(root).data['tracks'])


@pytest.mark.parametrize('sr',[44100,48000,96000])
@pytest.mark.parametrize('channels',[1,2])
def test_warp_pitch_transients_sr_channels(sr,channels):
    t=np.arange(round(.7*sr))/sr
    x=H.sine(220,seconds=.7,sr=sr,channels=channels)
    mapping=[[0,0],[.2*sr,.24*sr],[.5*sr,.48*sr],[len(x),len(x)]]
    y=warp(x,sr,schedule(x,sr,mapping))
    cents=1200*np.log2(frequency(y,sr)/220)
    assert abs(cents)<=3
    click=np.zeros_like(x)
    positions=np.arange(.1,.65,.1)*sr
    click[np.rint(positions).astype(int)]=.5
    y=warp(click,sr,schedule(click,sr,mapping))
    expected=np.interp(positions,np.array(mapping)[:,0],np.array(mapping)[:,1])
    for s in expected:
        a,b=max(0,round(s-.01*sr)),min(len(y),round(s+.01*sr))
        power=np.sum(y[a:b]**2,axis=1)
        cumulative=np.cumsum(power)/max(power.sum(),1e-20)
        width=(np.searchsorted(cumulative,.95)-np.searchsorted(cumulative,.05))/sr*1000
        assert width<=5
        assert abs(a+np.argmax(power)-s)<=.005*sr


@pytest.mark.parametrize('quality',['standard','high'])
def test_time_group_lag_and_quality(quality):
    sr=24000
    x=H.sine(223,seconds=1,sr=sr,channels=2)
    peer=np.r_[np.zeros((1,2)),x[:-1]]*.7
    mapping=[[0,0],[6000,7200],[18000,17000],[24000,24000]]
    s=schedule(x,sr,mapping,quality)
    y=warp(x,sr,s);z=warp(peer,sr,s)
    from mankomix.dspx.bb.align import estimate_delay
    lag=estimate_delay(y[:,0],z[:,0],sr,max_delay_ms=2)['delay_samples']
    error=1200*np.log2(frequency(y,sr)/223)
    print(json.dumps({'quality':quality,'lag_samples':float(lag),'pitch_error_cents':float(error)}))
    assert abs(lag-1)<=1 and abs(error)<=3
    np.testing.assert_array_equal(y,warp(x,sr,s))


@pytest.mark.parametrize('pitch',[False,True])
def test_all_numeric_ranges_defaults(pitch):
    numeric=A.TIME_NUMERIC | (A.PITCH_NUMERIC if pitch else {})
    for key,(lo,hi,default) in numeric.items():
        for value in (lo,hi,default):
            errors=[]
            A.validate(move('edit_align_pitch' if pitch else 'edit_align_time',guide='trk_g',**{key:value}),X.ValidationContext(None,{},'',lambda *a:errors.append(a)),pitch=pitch)
            assert not errors,(key,value,errors)
        errors=[]
        A.validate(move('edit_align_time',guide='trk_g',**{key:hi+1}),X.ValidationContext(None,{},'',lambda *a:errors.append(a)),pitch=pitch)
        assert errors
    for key,(lo,hi,default) in Q.NUMERIC.items():
        for value in (lo,hi,default) if default is not None else (lo,hi):
            errors=[]
            p={'bpm':120,key:value}
            if key=='detect_lo_hz' and value==20000:
                continue # Coupled band ordering has no valid high endpoint here.
            if key=='detect_hi_hz' and value==20:
                continue
            A.validate(move('edit_quantize',**p),X.ValidationContext(None,{},'',lambda *a:errors.append(a)),quantize=True)
            assert not errors,(key,value,errors)


def test_simultaneous_pitch_time_melody(tmp_path):
    x,g,_,starts=syllables(detune=True)
    root=make(tmp_path,{'bass':x,'vocals':g})
    from mankomix.director.xops.edit_align_pitch import derive
    m=move('edit_align_pitch',guide='trk_vocals',tightness=1,pitch_tightness=1,interval='unison')
    before=C._snapshot(root)
    plan=derive(root,m)
    assert C._snapshot(root)==before
    y=A.calculate(E.raw_track(root,'trk_bass')[0],T.SR,plan.params)
    from mankomix.dspx.bb.onsets import detect_onsets
    on=detect_onsets(y,T.SR,kind='soft')
    errors=[min(abs(e['time_s']-s) for e in on)*1000 for s in starts]
    pitch_errors=[]
    for i,s in enumerate(starts):
        expected=180*2**((i%5)/12)
        block=y[round((s+.08)*T.SR):round((s+.24)*T.SR)]
        measured=H.fundamental_frequency(block,T.SR,low_hz=expected*.85,high_hz=expected*1.15)
        pitch_errors.append(1200*np.log2(measured/expected))
    print(json.dumps({'combined_pitch_max_cents':float(max(abs(np.array(pitch_errors)))),'combined_onset_median_ms':float(np.median(errors)),'combined_onset_max_ms':max(errors)}))
    assert max(abs(np.array(pitch_errors)))<=8
    assert np.median(errors)<=10 and max(errors)<=25


@pytest.mark.parametrize('preserve',[True,False])
def test_formant_preservation(preserve):
    # PT6's +5-semitone kernel stress exceeds the op's 300-cent correction cap.
    # Exercise the same single-pass synthesizer directly, and test the op's cap above.
    from mankomix.dspx.bb.psola import voice_track
    from mankomix.dspx.bb.alignment_warp import pitch_schedule,synthesize_pitch
    from tests.test_tk_w3b import envelope_peaks
    sr=16000
    x=H.vowel(sr=sr,seconds=1.5,f0=100)
    tr=voice_track(x,sr)
    # PT6 is a synthesis test with known synthetic pitch; it must not pass
    # merely because a conservative voicing decision returned the dry vowel.
    from dataclasses import replace
    tr=replace(tr,f0_hz=np.full(len(tr.samples),100.),voiced=np.ones(len(tr.samples),bool),probability=np.ones(len(tr.samples)))
    plan=pitch_schedule(x,sr,tr,np.full(len(tr.samples),500.),[[0,0],[len(x),len(x)]],preserve)
    y=synthesize_pitch(x,sr,plan,x)
    original=envelope_peaks(x,sr,[700,1200,2500])
    targets=original*(1 if preserve else 2**(5/12))
    measured=envelope_peaks(y,sr,targets)
    errors=abs(measured/targets-1)
    print(json.dumps({'formant_preserve':preserve,'input_peaks_hz':original.tolist(),'output_peaks_hz':measured.tolist(),'max_relative_error':float(errors.max())}))
    assert errors.max()<=.03


def test_max_shift_selection_tail_fill_and_section(tmp_path):
    x,grid,jitter=drums(count=8)
    root=make(tmp_path,{'bass':x,'vocals':x*.5})
    p=dict(bpm=120,strength=1,max_shift_ms=10,min_shift_ms=0,threshold_db=-60,detect_lo_hz=20,detect_hi_hz=20000,min_interval_ms=30)
    m=move('edit_quantize',**p)
    plan=Q.derive(root,m)
    for r in plan.record['onsets']:
        if abs(r['grid_sample']-r['sample'])>240:
            assert r['shift_samples']==0 and r['reason']=='max_shift'
    rows=plan.record['onsets']
    selected=next(r['id'] for r in rows if r['shift_samples'])
    m=move('edit_quantize',**p,only=[selected],group=['trk_vocals'])
    plan=Q.derive(root,m)
    assert all(not r['shift_samples'] for r in plan.record['onsets'] if r['id']!=selected)
    # Default stretch_tail is measured on the same copied slices, including seams.
    y=Q.calculate(x,T.SR,plan.plans['trk_bass'].params)
    assert np.isfinite(y).all()
    # Every 5 ms output energy cell stays below the maximum source cell by 3 dB.
    def peak_energy(z):
        return np.max(H.rms_envelope(z,T.SR,window_ms=5,hop_ms=1))
    ratio=peak_energy(y)/peak_energy(x)
    print(json.dumps({'seam_max_energy_change_db':float(20*np.log10(ratio))}))
    assert 20*np.log10(ratio)<=3
    bad=move('edit_quantize',**p)
    bad['section']={'t0_s':0,'t1_s':99999}
    with pytest.raises(ValueError,match='duration'):
        Q.derive(root,bad)


def test_dissimilar_low_confidence_and_subhop_anchors():
    x,g,_,_=syllables(count=4)
    rng=np.random.Generator(np.random.PCG64(66))
    y=rng.standard_normal(g.shape)*.02
    p=A.resolve({'params':{'guide':'trk_g'}})
    r=dtw.alignment(x,y,T.SR,p)
    print(json.dumps({'dissimilar_cost':r['mean_cost'],'confidence':r['confidence']}))
    assert r['confidence']=='low' and r['uncertain_intervals']
    t=np.arange(T.SR)/T.SR
    continuous=(.1*np.sin(2*np.pi*220*t))[:,None]
    p.update(anchors=[[.5,.51],[.502,.512]],protect_sustain=0)
    r=dtw.alignment(continuous,continuous,T.SR,p)
    knots=np.array(r['map'])
    for a,b in p['anchors']:
        assert abs(np.interp(a*T.SR,knots[:,0],knots[:,1])-b*T.SR)<1e-6


@pytest.mark.parametrize('op',['edit_align_time','edit_align_pitch'])
def test_alignment_full_apply_regenerate_revert(tmp_path,op):
    x,g,_,_=syllables(count=3,detune=op.endswith('pitch'))
    root=make(tmp_path,{'bass':x,'vocals':g})
    original=E.raw_track(root,'trk_bass')[0]
    original_clips=copy.deepcopy(Project.open(root).data['tracks'][0]['clips'])
    params={'guide':'trk_vocals','tightness':1}
    if op.endswith('pitch'):
        params.update(pitch_tightness=1,interval='unison')
    m=move(op,**params)
    parsed=doc(tmp_path,[m])
    result=D.apply(root,parsed['path'])
    assert result['applied'],result
    row=B._ledger(root,parsed['id'])['derived']['m01']
    path=Project.open(root).asset_path(row['result']['asset'])
    contents=path.read_bytes()
    path.unlink()
    cache=B._cache(root,row['key'])
    cache.unlink();cache.with_suffix('.json').unlink()
    assert B.regenerate(root,parsed['id'],'m01',calculate=A.calculate)['regenerated']
    assert path.read_bytes()==contents
    E.revert(root,parsed['id'],actor='human')
    assert E.raw_track(root,'trk_bass')[0].tobytes()==original.tobytes()
    assert Project.open(root).data['tracks'][0]['clips']==original_clips


def test_validation_arrays_options_and_strength_range():
    from mankomix.dsp.processors import NOTE_VALUES
    def errors(p,pitch=False,quantize=False):
        out=[]
        A.validate({'target':'trk_t','params':p},X.ValidationContext(None,{},'',lambda *a:out.append(a)),pitch=pitch,quantize=quantize)
        return out
    for note in NOTE_VALUES[1:]:
        assert not errors({'bpm':120,'grid_note':note},quantize=True)
    assert errors({'bpm':120,'grid_note':'none'},quantize=True)
    assert not errors({'bpm':120,'strength':[.2,.8]},quantize=True)
    assert Q.resolve(move('edit_quantize',bpm=120,strength=[.2,.8]))['strength']==.5
    assert Q.resolve({**move('edit_quantize',bpm=120,strength=[.2,.8]),'select':'max'})['strength']==.8
    assert errors({'bpm':120,'strength':[.8,.2]},quantize=True)
    assert not errors({'guide':'trk_g','anchors':[[i*.01,i*.01] for i in range(64)],'group':['trk_'+str(i) for i in range(8)]})
    assert errors({'guide':'trk_g','anchors':[[i*.01,i*.01] for i in range(65)]})
    assert errors({'guide':'trk_g','group':['trk_'+str(i) for i in range(9)]})
    assert not errors({'bpm':120,'group':['trk_'+str(i) for i in range(16)]},quantize=True)
    assert errors({'bpm':120,'group':['trk_'+str(i) for i in range(17)]},quantize=True)
    assert errors({'guide':'trk_g','anchors':[[1,1],[1,2]]})
    assert errors({'guide':'trk_g','time':1},pitch=True)
    assert errors({'guide':'trk_g','interval':25},pitch=True)
