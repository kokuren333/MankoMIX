"""W4g bounded automation, fixed-feature breaths, ambience and BB-18 debleed."""
import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import signal

from mankomix.cli import main as CLI
from mankomix.core.errors import InputError
from mankomix.core.project import Project
from mankomix.core.measure import loudness as L
from mankomix.director import direction as D, edit, derived, commands as C, xops as X
from mankomix.director.xops import ride as R, level_phrases as P, breath as B, edit_debleed as E, _w4g as W
from mankomix.director.commands import suggest_ambience as A
from mankomix.dspx.procs.noise_bed import noise_bed, SPECS
from mankomix.dsp import processors as DSP
from tests import test_upgrade2_duck as T
from tests import toolimpl_harness as H

SR = T.SR


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path/'home'))


def tone(seconds, db=-20, hz=220, sr=SR):
    t = np.arange(round(seconds*sr))/sr
    return (10**(db/20)*np.sqrt(2)*np.sin(2*np.pi*hz*t))[:, None]


def move(op, params=None, target='trk_vocals', mid='m01', **extra):
    return {'id': mid, 'op': op, 'target': target, 'aim': 'a1', 'origin': 'new',
            'basis': 'synthetic measurement', 'params': params or {}, **extra}


def document(tmp_path, moves):
    return D.parse_document(T._doc(tmp_path/'doc', T._block(moves)))


def knots(points, count):
    a = np.asarray(points)
    return np.interp(np.arange(count), a[:, 0], a[:, 1]) if len(a) else np.zeros(count)


def test_ride_steps_slope_hold_and_repeat():
    x = np.concatenate([tone(3, -20), tone(3, -26), np.zeros((SR, 1)), tone(3, -20)])
    p = W.params(move('ride', {'range_up_db': 3, 'range_down_db': 3}), R.NUMERIC, R.ENUMS)
    points, record = R.curve(x, SR, p)
    assert points == R.curve(x, SR, p)[0]
    gain = knots(points, len(x))
    assert gain.min() >= -3 and gain.max() <= 3
    assert np.max(abs(np.diff(gain)))*SR <= 12+1e-8
    assert np.ptp(gain[6*SR:7*SR]) < 1e-10
    y = x*10**(gain[:, None]/20)
    before = [float(L.integrated(x[a*SR:b*SR], SR)) for a, b in [(1, 2), (4, 5)]]
    after = [float(L.integrated(y[a*SR:b*SR], SR)) for a, b in [(1, 2), (4, 5)]]
    assert np.ptp(before)-np.ptp(after) >= 2.7
    print('ride', W.clean(record))


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_ride_rates_and_silence(sr, channels):
    x = np.tile(np.r_[tone(.5, sr=sr), tone(.5, -26, sr=sr)], (1, channels))
    p = W.params(move('ride'), R.NUMERIC, R.ENUMS)
    points, _ = R.curve(x, sr, p, bounded=True)
    gain = knots(points, len(x))
    assert abs(gain).max() <= 2
    assert np.max(abs(np.diff(gain)))*sr <= 12+1e-8
    assert R.curve(np.zeros_like(x), sr, p)[0] == []


def test_rdp_tolerance():
    samples = np.arange(1000)*240
    values = 2*np.sin(np.arange(1000)*.01)
    points = R.simplify(samples, values, .05)
    approximation = np.interp(samples, np.array(points)[:, 0], np.array(points)[:, 1])
    assert max(abs(approximation-values)) <= .05


def phrases():
    return np.concatenate([np.r_[tone(1.4, level), np.zeros((round(.6*SR), 1))]
                           for level in [-30, -26, -22, -18, -16, -14]])


def test_phrase_width_constant_gain_and_transitions():
    x = phrases()
    p = W.params(move('level_phrases', {'amount': .7, 'range_up_db': 18, 'range_down_db': 18}), P.NUMERIC, P.ENUMS)
    points, record = P.curve(x, SR, p)
    assert points == P.curve(x, SR, p)[0]
    assert len(record['phrases']) == 6
    gain = knots(points, len(x))
    after = []
    for row in record['phrases']:
        a, b = row['start_sample'], row['end_sample']
        assert np.ptp(gain[a:b]) == 0
        after.append(L.integrated(x[a:b]*10**(gain[a:b, None]/20), SR))
    before_width = record['before']['width_db']
    assert abs(np.ptp(after)-before_width*.3) <= .5
    print('phrases', W.clean(record))


def test_phrase_limits_guard_short_merge_and_neutral():
    rng = np.random.Generator(np.random.PCG64(27))
    x = np.r_[tone(1.2, -20), rng.normal(0, .002, (SR, 1)), tone(1.2, -48)]
    p = W.params(move('level_phrases', {'gate_below_db': -20, 'to_lufs': -18,
                                      'noise_floor_guard_db': 24}), P.NUMERIC, P.ENUMS)
    _, rows = P.curve(x, SR, p)
    assert all(-6 <= r['gain_db'] <= 6 for r in rows['phrases'])
    # An explicit low phrase above the activity gate but close to the pause floor.
    x = np.r_[tone(1.2, -40), rng.normal(0, .0008, (SR, 1)), tone(1.2, -20)]
    p['gate_below_db'] = -20
    _, rows = P.curve(x, SR, p)
    assert rows['phrases'][0]['not_raised_reason'] == 'noise_floor_guard'
    p['amount'] = 0
    points, _ = P.curve(x, SR, p)
    assert not np.any(knots(points, len(x)))
    short = np.r_[tone(1.2), np.zeros((SR//2, 1)), tone(.3), np.zeros((SR, 1))]
    _, rows = P.curve(short, SR, W.params(move('level_phrases'), P.NUMERIC, P.ENUMS))
    assert len(rows['phrases']) == 1


def breath_fixture(count=20):
    rng = np.random.Generator(np.random.PCG64(78))
    parts, breaths, fricatives = [], [], []
    position = 0
    sos = signal.butter(3, [1000, 6000], fs=SR, btype='bandpass', output='sos')
    for _ in range(count):
        for duration, dest in ((.35, breaths), (.065, fricatives)):
            vowel = tone(.3, -15, 180)+tone(.3, -22, 360)+tone(.3, -27, 540)
            parts.append(vowel)
            position += len(vowel)
            noise = signal.sosfilt(sos, rng.standard_normal(round(duration*SR)))
            noise *= np.sin(np.linspace(0, np.pi, len(noise)))
            noise *= 10**(-34/20)/np.sqrt(np.mean(noise*noise))
            dest.append([position, position+len(noise)])
            parts.append(noise[:, None])
            position += len(noise)
    return np.concatenate(parts), breaths, fricatives


def test_breath_detection_recall_false_positive_and_repeat():
    x, breaths, fricatives = breath_fixture()
    p = W.params(move('breath'), B.NUMERIC, B.ENUMS)
    rows = B.detect(x, SR, p)
    assert rows == B.detect(x, SR, p)
    eligible = [r for r in rows if r['eligible'] and r['confidence'] != 'low']
    found = sum(any(max(a, r['start_sample']) < min(b, r['end_sample']) for r in eligible) for a, b in breaths)
    false = sum(any(max(a, r['start_sample']) < min(b, r['end_sample']) for r in eligible) for a, b in fricatives)
    assert found/20 >= .85
    assert false/20 <= .1
    points, selected = B.envelope(rows, SR, p, 0, len(x), len(x))
    gain = knots(points, len(x))
    for row in selected:
        a, b, f = row['start_sample'], row['end_sample'], row['fade_samples']
        assert gain[a] == gain[b-1] == 0
        assert np.all(gain[a+f:b-f] == -6)
        assert f == round(.025*SR)
    print('breaths', {'found': found, 'false': false, 'candidates': len(rows),
                      'score_range': [min(r['score'] for r in rows), max(r['score'] for r in rows)]})


def test_breath_only_skip_target_and_low_confidence():
    rows = [{'id': f'b_{a}', 'start_sample': a, 'end_sample': a+10000,
             'relative_db': -18, 'eligible': True, 'confidence': 'high'} for a in (1000, 15000)]
    p = W.params(move('breath', {'only': ['b_1000'], 'mode': 'target'}), B.NUMERIC, B.ENUMS)
    points, selected = B.envelope(rows, SR, p, 0, 30000, 30000)
    assert [r['id'] for r in selected] == ['b_1000']
    assert min(v for _, v in points) == -6
    p['skip'] = ['b_1000']
    assert B.envelope(rows, SR, p, 0, 30000, 30000)[1] == []
    p.update(only=[], skip=[])
    rows[0]['relative_db'] = -30
    rows[1]['confidence'] = 'low'
    points, selected = B.envelope(rows, SR, p, 0, 30000, 30000)
    assert not np.any(np.array(points)[:, 1])
    rows[0]['relative_db'] = -12
    points, selected = B.envelope(rows, SR, p, 0, 30000, 30000)
    assert min(v for _, v in points) == -12


def debleed_fixture():
    t = np.arange(6*SR)/SR
    a = sum(np.sin(2*np.pi*f*t)/i for i, f in enumerate([211, 422, 633], 1))*.1
    b = sum(np.sin(2*np.pi*f*t)/i for i, f in enumerate([367, 734, 1101], 1))*.1
    a *= ((t>=2)&(t<5))
    b *= ((t>=.4)&(t<5.7))
    delay = round(.003*SR)
    colored = signal.lfilter([.8, .2], [1], b)
    leak = np.r_[np.zeros(delay), colored[:-delay]]*10**(-12/20)
    target = (a+leak)[:, None]
    source = (b+np.r_[np.zeros(delay), a[:-delay]]*10**(-12/20))[:, None]
    return target, source, a[:, None], b[:, None]


def amplitude(x, hz, a=2.5, b=4.5):
    x = x[round(a*SR):round(b*SR), 0]
    t = np.arange(len(x))/SR
    return 2*abs(np.dot(x, np.exp(-2j*np.pi*hz*t)))/len(x)


def test_debleed_quality_delay_no_bleed_and_repeat():
    x, source, a, b = debleed_fixture()
    p = W.params(move('edit_debleed', {'sources': ['trk_source']}), E.NUMERIC)
    y, record = E.process(x, [('trk_source', source)], SR, p)
    assert np.array_equal(y, E.process(x, [('trk_source', source)], SR, p)[0])
    reduction = 20*np.log10(amplitude(y, 367)/amplitude(x, 367))
    own = 20*np.log10(amplitude(y, 211)/amplitude(x, 211))
    assert reduction <= -8
    assert abs(own) <= 1.5
    assert abs(record['sources'][0]['delay_ms']-3) <= .1
    innocent, stats = E.process(a, [('trk_source', b)], SR, p)
    removed = float(W.db(np.sum((a-innocent)**2)/np.sum(a*a)))
    assert removed <= -45
    print('debleed', {'bleed_change_db': reduction, 'own_change_db': own,
                      'no_bleed_removed_db': removed, **record})


@pytest.mark.parametrize('op,module', [('ride', R), ('level_phrases', P), ('breath', B), ('edit_debleed', E)])
def test_parameter_contracts(op, module):
    for key, (lo, hi, default, ranged) in module.NUMERIC.items():
        for value, valid in ((lo, True), (hi, True), (lo-1, False), (hi+1, False), (True, False), (float('nan'), False), ([lo, hi], ranged)):
            errors = []
            m = move(op, {key: value, **({'sources': ['trk_source']} if op == 'edit_debleed' else {})})
            module.validate(m, X.ValidationContext(None, {}, '', lambda w, c, msg: errors.append(c)))
            assert bool(errors) != valid, (op, key, value, errors)
    errors = []
    module.validate(move(op, {'unknown': 1}), X.ValidationContext(None, {}, '', lambda w, c, msg: errors.append(c)))
    assert errors


@pytest.fixture
def song(tmp_path):
    rng = np.random.Generator(np.random.PCG64(8))
    return T._make(tmp_path/'song', {'vocals': tone(2), 'source': tone(2, -24, 367),
                                   'room': rng.normal(0, .001, (2*SR, 2))})


def test_real_ops_proposal_composition_and_legacy_inert(song, tmp_path, monkeypatch):
    ops = X.load(D.OPS)
    old = document(tmp_path, [move('gain', {'delta_db': 1})])
    enabled = D.validate(old, song), D.build_proposal(D._Project(song), old)
    with monkeypatch.context() as patch:
        patch.setattr(X, 'OPS', {})
        patch.setattr(X, '_loaded', True)
        disabled = D.validate(old, song), D.build_proposal(D._Project(song), old)
    assert enabled == disabled
    moves = [move('ride'), move('level_phrases', mid='m02'), move('breath', mid='m03')]
    parsed = document(tmp_path, moves)
    v = D.validate(parsed, song)
    assert v['ok'], v['errors']
    prop, record, _ = D.build_proposal(D._Project(song), parsed)
    assert prop['changes']['tracks']['trk_vocals']['automation']['move_ref'] == [f"{parsed['id']}/m0{i}" for i in (1, 2, 3)]
    assert set(record['moves']) == {'m01', 'm02', 'm03'}


def test_section_and_against_bus(song):
    project = D._Project(song)
    for op, module in [('ride', R), ('level_phrases', P), ('breath', B)]:
        m = move(op, section={'t0_s': .5, 't1_s': 1.5})
        if op == 'ride':
            m['params'] = {'mode': 'against', 'against': 'bus_mix'}
        result = module.expand(project, m)
        gain = knots(result.points, 2*SR)
        assert np.all(gain[:SR//2] == 0)
        assert np.all(gain[round(1.5*SR):] == 0)
    result = P.expand(project, move('level_phrases', {'to_lufs': -12},
                                   section={'t0_s': .5, 't1_s': 1.5}))
    assert result.record['phrases'][0]['not_raised_reason'] == 'section_boundary_without_pause'
    assert not np.any(knots(result.points, 2*SR))


def test_against_sub_bus_preserves_routing_and_send_math(song):
    from mankomix.core import mixrender as MR
    project = Project.open(song)
    buses = copy.deepcopy(project.data['buses'])
    buses.append({'id': 'bus_voice', 'kind': 'group', 'output': 'bus_mix',
                  'chain': [], 'gain_db': -3})
    project.set('/buses', buses, actor='human')
    tracks = copy.deepcopy(project.data['tracks'])
    for track in tracks:
        if track['id'] == 'trk_vocals':
            track['output'] = 'bus_voice'
    project.set('/tracks', tracks, actor='human')
    before = C._snapshot(song)
    y, sr = W.audio(song, 'bus_voice')
    source = W.audio(song, 'trk_vocals')[0]
    track = next(t for t in tracks if t['id'] == 'trk_vocals')
    pos, width = MR.track_pan(track)
    expected = MR.pan_stereo(source, pos, width, MR.DEFAULT_PAN_LAW_DB, mono=True)*10**(-3/20)
    assert np.allclose(y, expected, atol=1e-15, rtol=0)
    assert before == C._snapshot(song)


def test_mix_apply_and_edit_real_calculation_revert(tmp_path):
    from mankomix.core import mixrender as MR
    x, source, a, b = debleed_fixture()
    song = T._make(tmp_path/'applied', {'vocals': x, 'source': source})
    original, sr, _ = edit.raw_track(song, 'trk_vocals')
    m = move('edit_debleed', {'sources': ['trk_source']})
    parsed = document(tmp_path, [m])
    result = D.apply(song, parsed['path'], actor='human')
    assert result['applied'], result
    changed = edit.raw_track(song, 'trk_vocals')[0]
    assert len(changed) == len(original)
    # Raw rendering is stereo after the core's mono expansion.
    assert 20*np.log10(amplitude(changed, 367)/amplitude(original, 367)) <= -8
    ledger = derived._ledger(song, parsed['id'])['derived']['m01']
    assert len(ledger['details']['sources']) == 1
    edit.revert(song, parsed['id'], actor='human')
    assert np.array_equal(original, edit.raw_track(song, 'trk_vocals')[0])
    moves = [move('ride', {'range_up_db': 3}), move('level_phrases', {'amount': .5}, mid='m02')]
    parsed = document(tmp_path, moves)
    assert D.apply(song, parsed['path'], actor='human')['applied']
    audio, rate, _ = MR.render_mix(Project.open(song), measure=False)
    assert len(audio) == len(original) and np.isfinite(audio).all()
    refs = next(t for t in Project.open(song).data['tracks'] if t['id'] == 'trk_vocals')['automation']['move_ref']
    assert refs == [f"{parsed['id']}/m0{i}" for i in (1, 2)]


def test_query_breath_ids_match_op_and_no_cache_write(tmp_path, capsys):
    x, _, _ = breath_fixture(2)
    song = T._make(tmp_path/'breaths', {'vocals': x})
    before = C._snapshot(song)
    assert CLI.main(['direction', 'query', 'breaths', '--project', str(song), '--target', 'trk_vocals']) == 0
    query = json.loads(capsys.readouterr().out)
    assert query['count'] == 2
    selected = query['breaths'][0]['id']
    result = B.expand(D._Project(song), move('breath', {'only': [selected]}))
    assert [r['id'] for r in result.record['selected']] == [selected]
    assert before == C._snapshot(song)


def test_no_new_op_validation_checks_usage_or_order(song, tmp_path):
    for ops in (('ride', 'breath', 'level_phrases'), ('level_phrases', 'breath', 'ride'), ('ride', 'ride')):
        parsed = document(tmp_path, [move(op, mid=f'm{i+1:02}') for i, op in enumerate(ops)])
        assert D.validate(parsed, song)['ok']


def test_missing_cleanup_cache_stays_readonly(song):
    project = Project.open(song)
    tracks = copy.deepcopy(project.data['tracks'])
    track = next(t for t in tracks if t['id'] == 'trk_room')
    asset = track['clips'][0]['asset']
    # Use the same cache-preflight contract as StemSource.
    track['cleanup'] = {'applied': {'assets': {asset: {'plan_hash': '0'*64, 'skipped': False}}}}
    project.set('/tracks', tracks, actor='human')
    before = C._snapshot(song)
    from mankomix.director.stemobs import cleanup_cache_error
    assert cleanup_cache_error(Project.open(song), tracks) is not None
    with pytest.raises(InputError):
        W.audio(song, 'trk_room')
    assert C._snapshot(song) == before


def test_muted_target_still_has_pre_fader_measurements(song):
    project = Project.open(song)
    original = W.audio(song, 'trk_vocals')[0]
    tracks = copy.deepcopy(project.data['tracks'])
    next(t for t in tracks if t['id'] == 'trk_vocals')['muted'] = True
    project.set('/tracks', tracks, actor='human')
    before = C._snapshot(song)
    assert np.array_equal(W.audio(song, 'trk_vocals')[0], original)
    assert C._snapshot(song) == before


@pytest.mark.parametrize('section', [{'t0_s': 1, 't1_s': .5}, {'t0_s': 0, 't1_s': float('inf')},
                                      {'t0_s': 0, 't1_s': .1}, ['bad'], 'missing_section'])
def test_invalid_sections_rejected(song, tmp_path, section):
    parsed = document(tmp_path, [move('ride', {'range_up_db': 2}, section=section)])
    assert not D.validate(parsed, song)['ok']


def test_fullscale_and_neutral_with_common_harness():
    x = H.sine(220, 0, sr=48000, seconds=1, channels=2)
    for module, op in ((R, 'ride'), (P, 'level_phrases')):
        p = W.params(move(op, {'range_up_db': 0, 'range_down_db': 0}), module.NUMERIC, module.ENUMS)
        points, _ = module.curve(x, 48000, p)
        y = x*10**(knots(points, len(x))[:, None]/20)
        assert np.array_equal(x, y)
        assert H.rms(y) == H.rms(x)
    p = W.params(move('breath'), B.NUMERIC, B.ENUMS)
    assert not B.detect(x, 48000, p)
    p = W.params(move('edit_debleed', {'sources': ['trk_source']}), E.NUMERIC)
    y, _ = E.process(x, [('trk_source', np.zeros_like(x))], 48000, p)
    assert np.array_equal(x, y)


def test_debleed_bb18_revert_and_source_dependency(song, tmp_path):
    before, sr, _ = edit.raw_track(song, 'trk_vocals')
    m = move('edit_debleed', {'sources': ['trk_source'], 'reduction_db': 0}, section={'t0_s': .4, 't1_s': 1.4})
    doc = document(tmp_path, [m])
    assert D.validate(doc, song)['ok']
    spec = X.load(D.OPS)['edit_debleed']
    row = X.apply_edit(song, doc, m, spec, actor='human')
    ledger = derived._ledger(song, doc['id'])['derived']['m01']
    assert ledger['fit'] == 'keep_length'
    assert ledger['result']['fitted_frames'] == SR
    assert ledger['params']['source_dependencies'][0]['raw_sha256']
    derived.regenerate(song, doc['id'], 'm01', calculate=E.make_calculator(song, ledger['params']))
    edit.revert(song, doc['id'], actor='human')
    assert np.array_equal(before, edit.raw_track(song, 'trk_vocals')[0])
    changed = copy.deepcopy(ledger['params'])
    changed['source_dependencies'][0]['raw_sha256'] = '0'*64
    with pytest.raises(ValueError, match='dependency'):
        E.make_calculator(song, changed)


@pytest.mark.parametrize('params', [{'sources': ['trk_vocals']}, {'sources': ['trk_missing']},
                                    {'sources': []}, {'sources': ['trk_source']*2}])
def test_debleed_invalid_sources(song, tmp_path, params):
    assert not D.validate(document(tmp_path, [move('edit_debleed', params)]), song)['ok']


@pytest.mark.parametrize('path,extra', [(('query', 'breaths'), []),
                                      (('suggest', 'ambience'), ['--region', '0,2']),
                                      (('suggest', 'ambience'), ['--find-quiet'])])
def test_cli_readonly_repeat_and_planned_names(song, tmp_path, capsys, path, extra):
    target = 'trk_vocals' if path[0] == 'query' else 'trk_room'
    before = C._snapshot(song)
    argv = ['direction', *path, '--project', str(song), '--target', target, *extra]
    assert CLI.main(argv) == 0
    first = capsys.readouterr().out
    assert CLI.main(argv) == 0
    assert first == capsys.readouterr().out
    result = json.loads(first)
    assert 'confidence' in result
    assert before == C._snapshot(song)
    assert C.cli_only()['direction '+' '.join(path)][0] == 'direction_'+'_'.join(path)
    if path == ('suggest', 'ambience') and '--region' in extra:
        candidate = result['candidates'][0]
        candidate['aim'] = 'a1'
        result = D.validate(document(tmp_path, [candidate]), song)
        assert result['ok'], result['errors']


def test_ambience_known_colour_roundtrip_and_voice_confidence():
    rng = np.random.Generator(np.random.PCG64(63))
    x = signal.lfilter([1, -.4], [1, -.85], rng.normal(0, .001, (12*SR, 2)), axis=0)
    measured = A.measure(x, SR, 64)
    p = DSP.validate_params('noise_bed', {'hiss_db': measured['level_dbfs'], 'spectrum': measured['spectrum'],
                                         'width': 1, 'seed': 0})
    y = noise_bed(np.zeros_like(x), SR, p, seed=321)[0]
    def third_octaves(z):
        f, psd = signal.welch(z, SR, nperseg=8192, axis=0)
        return np.array([np.sum(np.mean(psd[(f>=c/2**(1/6))&(f<c*2**(1/6))], axis=1))
                         for c in 100*2**(np.arange(20)/3)])
    error = W.db(third_octaves(y)/third_octaves(x))
    level_error = float(W.db(np.mean(y*y)/np.mean(x*x)))
    assert max(abs(error)) <= 1.5
    assert abs(level_error) <= .5
    assert A.measure(np.r_[x[:SR], x[SR:2*SR]*20], SR)['confidence'] == 'low'
    print('ambience', {'max_third_octave_error_db': float(max(abs(error))), 'level_error_db': level_error})


def test_ambience_region_required(song):
    with pytest.raises(InputError, match='region'):
        A.run(SimpleNamespace(project=str(song), target='trk_room', region=None,
                              points=32, smooth_oct=1/3, find_quiet=False))
