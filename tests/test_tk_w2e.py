"""W2e: keyed curves, absolute dB shaping, bus wiring and legacy byte floor."""
import copy
import json

import numpy as np
import pytest

from mankomix.core.project import Project
from mankomix.core import mixrender as MR
from mankomix.director import direction as D, duck as K, duck_curve as KC, curve
from mankomix.dsp import processors as P
from mankomix.dsp.engine import render_chain
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb import keyed, curves
from mankomix.dspx.procs.volume_shaper import modulation, volume_shaper
from tests import test_upgrade2_duck as T, test_fb2_gain_curve as G
from tests.test_upgrade2_duck import _local_home, _template, song
from tests.toolimpl_harness import assert_common_tests


def move(mid='m01', target='trk_bass', **params):
    m = T._duck(mid, target, **params)
    m['op'] = 'duck_curve'
    return m


def doc(tmp_path, moves):
    return D.parse_document(T._doc(tmp_path / 'doc', T._block(moves)))


def render(kind, x, sr=48000, **params):
    return render_chain(x, sr, [{'type': kind, 'params': params}], stage='bus').audio


def test_legacy_validation_proposal_and_apply_bytes(song, tmp_path):
    # Captured before direction.py was edited, including legacy duck itself.
    for tag, moves, vh, ph in [
        ('duck', [T._duck()], 'b78692bda0eaf4b7', '10a97647f995a5cb'),
        ('curve', [G._move()], '3fdfc316fe463ed2', '49b1f2bf02b84d31'),
        ('both', [T._duck(), G._move('c')], '897234222d6a3bb2', '7bb3870828cd25a8')]:
        parsed = D.parse_document(T._doc(tmp_path / tag, T._block(moves)))
        assert T._h(D.validate(parsed, song)) == vh
        assert T._h(D.build_proposal(D._Project(song), parsed)) == ph
    path = T._doc(tmp_path / 'apply', T._block([T._duck()]))
    out = D.apply(song, path)
    assert T._masked((song / 'directions' / f"{out['id']}.apply.json").read_text(encoding='utf8')) == '0ff53480c4369671'


@pytest.mark.parametrize('hits', [[], [0], [300, 600], [1, 2, 3], [1000, 4000]])
def test_linear_curve_is_exact_legacy_points(hits):
    assert keyed.keyed_envelope(hits, 48000, 3.123456, 5, 120) == K.envelope(hits, 48000, 3.123456, 5, 120)


def test_hold_shape_and_grid_collision():
    pts = keyed.keyed_envelope([1000], 1000, 6, 10, 100,
                               hold_ms=20, shape=[[0, 0], [.5, .25], [1, 1]])
    assert pts == [[990, 0], [1000, -6], [1020, -6], [1070, -4.5], [1120, 0]]
    pts = keyed.keyed_envelope([1], 1000, 6, 1, 1, shape=[[0, 0], [.1, .2], [.2, .5], [1, 1]])
    assert pts == [[0, 0], [1, -3], [2, 0]]  # later rounded knot wins


def test_detected_kicks_and_same_fullband_automation(song, tmp_path):
    m = move(depth_db=3, attack_ms=5, release_ms=120)
    out = KC.plan(song, m, m['params'], 120)
    old = K.plan(song, T._duck(), m['params'], 120)
    assert out['points'] == old['points']
    hits = [h['sample'] for h in out['record']['hit_list']]
    assert len(hits) == T.N_HITS
    assert np.max(np.abs(np.array(hits) - T._hit_samples())) <= 2 * T.HOP
    assert out['points'][0][0] == hits[0] - round(.005 * T.SR)
    assert out['points'][-1][0] == hits[-1] + round(.12 * T.SR)
    d = doc(tmp_path, [m])
    assert D.validate(d, song)['ok']
    prop, rec, _ = D.build_proposal(D._Project(song), d)
    assert prop['changes']['tracks']['trk_bass']['automation']['gain_db'] == out['points']
    assert rec['moves']['m01']['measurements']['after']['rms_dbfs'] < rec['moves']['m01']['measurements']['before']['rms_dbfs']


def test_exact_composition_order(song, tmp_path, monkeypatch):
    p = Project.open(song)
    tracks = copy.deepcopy(p.data['tracks'])
    base = [[0, -.5], [T.SR, -1], [2*T.SR, 0]]
    next(t for t in tracks if t['id'] == 'trk_bass')['automation'] = {'gain_db': base, 'owner': 'human'}
    p.set('/tracks', tracks, actor='human')
    monkeypatch.setattr(K, 'key_hits', lambda *args: ([6000, 18000], T.SR))
    gain = {'id': 'g', 'aim': 'a1', 'op': 'gain', 'target': 'trk_bass', 'section': 'sec2',
            'params': {'delta_db': -1}, 'basis': 'balance', 'origin': 'new'}
    moves = [G._move('c'), move('dc', depth_db=4), gain, T._duck('dk', depth_db=2)]
    d = doc(tmp_path, moves)
    assert D.validate(d, song)['ok']
    prop, _, _ = D.build_proposal(D._Project(song), d)
    want = K.merge_automation(base, D._automation(T.SR, [(3, T.SECS, -1)], None))
    want = K.merge_automation(want, K.envelope([6000, 18000], T.SR, 4, 5, 250))
    want = K.merge_automation(want, K.envelope([6000, 18000], T.SR, 2, 5, 250))
    want = K.merge_automation(want, curve.points(T.SR, [G._segment()], 20, T.SECS))
    assert prop['changes']['tracks']['trk_bass']['automation']['gain_db'] == want


@pytest.mark.parametrize('params', [
    {'depth_db': .49}, {'depth_db': 12.01}, {'depth_db': [1, 13]}, {'hold_ms': -1}, {'hold_ms': 501},
    {'hold_ms': [0, 20]}, {'shape': []}, {'shape': [[0, .5], [1, .4]]}, {'shape': [[0, 0], [0, 1]]},
    {'shape': [[i/32, i/32] for i in range(33)]}, {'shape': [[0, float('nan')]]},
    {'shape': [[0, 0, 1]]}, {'band_lo_hz': 0, 'band_hi_hz': 200}, {'band_lo_hz': 20},
    {'band_lo_hz': 10, 'band_hi_hz': 200}, {'band_lo_hz': 8001, 'band_hi_hz': 20000},
    {'band_lo_hz': 100, 'band_hi_hz': 149}, {'band_hi_hz': 20001}, {'extra': 1},
    {'key': 'bus_mix'}, {'key': 'trk_bass'}, {'release_note': '1/8', 'release_ms': 100}])
def test_invalid_op_params(tmp_path, params):
    assert not D.validate(doc(tmp_path, [move(**params)]))['ok']


@pytest.mark.parametrize('section', [None, 'all', 'sec1'])
def test_forbid_every_section_spelling(tmp_path, section):
    m = move(); m['section'] = section
    assert 'section_scope' in T._codes(D.validate(doc(tmp_path, [m])))


def test_target_validation_tier_and_legacy_isolation(song, tmp_path):
    for target in ('master', 'bus_missing', 'trk_missing'):
        r = D.validate(doc(tmp_path, [move(target=target)]), song)
        assert not r['ok']
    assert D.validate(doc(tmp_path, [move(target='trk_vocals')]), song)['tiers']['m01'] == 'E3'
    for params in ({'depth_db': 12, 'hold_ms': 500}, {'depth_db': [.5, 12]},
                   {'band_lo_hz': 20, 'band_hi_hz': 20000}):
        assert D.validate(doc(tmp_path, [move(**params)]), song)['ok']
    old = T._duck(band_lo_hz=100, band_hi_hz=400)
    assert not D.validate(doc(tmp_path, [old]), song)['ok']


@pytest.mark.parametrize('target', ['trk_bass', 'bus_mix', 'bus_user', 'bus_new'])
def test_band_bus_and_track_apply(song, tmp_path, target):
    p = Project.open(song)
    if target == 'bus_user':
        buses = copy.deepcopy(p.data['buses'])
        buses.append({'id': target, 'kind': 'fx', 'output': 'bus_mix', 'chain': []})
        p.set('/buses', buses, actor='human')
    moves = [move(target=target, band_lo_hz=40, band_hi_hz=300)]
    if target == 'bus_new':
        moves.append({'id': 'b', 'aim': 'a1', 'op': 'bus_add', 'target': target,
                      'params': {'kind': 'fx', 'chain': []}, 'basis': 'room', 'origin': 'new'})
    # A later chain_add must precede the generated automation at the tail.
    if target != 'bus_user':
        moves.append({'id': 'a', 'aim': 'a1', 'op': 'chain_add', 'target': target, 'processor': 'gain',
                      'params': {'gain_db': 0}, 'basis': 'level', 'origin': 'new'})
    d = doc(tmp_path, moves)
    assert D.validate(d, song)['ok']
    key0 = MR.render_track(p, 'trk_drums')[0]
    applied = D.apply(song, d['path'])
    p = Project.open(song)
    holder = next(t for t in p.data['tracks' if target.startswith('trk_') else 'buses'] if t['id'] == target)
    assert holder['chain'][-1]['type'] == 'band_automation'
    assert holder['chain'][-1]['move_ref'] == f"{d['id']}/m01"
    assert MR.render_track(p, 'trk_drums')[0].tobytes() == key0.tobytes()
    assert applied['record']['moves']['m01']['measurements']['after'] is not None
    assert any(it.get('move_ref') == f"{d['id']}/m01" for it in D._director_items(p.data))


@pytest.mark.parametrize('depths', [[2, 3], [12, 12, 12]])
def test_fullband_bus_sum(song, tmp_path, depths):
    moves = [move(f'd{i}', target='bus_mix', depth_db=depth) for i, depth in enumerate(depths)]
    d = doc(tmp_path, moves)
    before = MR.render_mix(Project.open(song))[0]
    assert D.validate(d, song)['ok']
    prop, _, _ = D.build_proposal(D._Project(song), d)
    chain = prop['changes']['mix_chain']
    assert len(chain) == 1 and chain[0]['type'] == 'gain_automation'
    assert len(chain[0]['move_ref']) == len(depths)
    expected = []
    for m in moves:
        expected = K.merge_automation(expected, KC.plan(song, m, m['params'], 120)['points'])
    assert [[round(at*T.SR), db] for at, db in chain[0]['params']['gain']] == expected
    D.apply(song, d['path'])
    after = MR.render_mix(Project.open(song))[0]
    assert after == pytest.approx(before * np.power(10., K.evaluate(expected, np.arange(len(before)))/20)[:, None])


@pytest.mark.parametrize('kind,params', [('band_automation', {}), ('gain_automation', {}),
                                      ('volume_shaper', {'bpm': 120, 'depth_db': 0})])
def test_neutral_bytes(kind, params):
    x = np.random.Generator(np.random.PCG64(5)).normal(0, .1, (4800, 2))
    assert render(kind, x, **params).tobytes() == x.tobytes()


@pytest.mark.parametrize('slope', [12, 24])
@pytest.mark.parametrize('f', [25, 200, 1600])
def test_band_center_and_two_octaves_outside(slope, f):
    sr = 48000; t = np.arange(sr)/sr
    x = .1*np.sin(2*np.pi*f*t)[:, None]
    y = render('band_automation', x, lo_hz=100, hi_hz=400, gain=[[0, -6]], slope_db_oct=slope)
    measured = 20*np.log10(np.linalg.norm(y[sr//2:])/np.linalg.norm(x[sr//2:]))
    assert measured == pytest.approx(-6 if f == 200 else 0, abs=.2)


def test_band_dynamic_knots_and_filtered_context_excerpt(song):
    sr = 48000; t = np.arange(sr)/sr
    x = .1*np.column_stack((np.sin(2*np.pi*200*t), np.cos(2*np.pi*200*t)))
    gain = [[0, -6], [.2, -6], [.3, -3], [.4, 0], [1, 0]]
    y = render('band_automation', x, lo_hz=100, hi_hz=400, gain=gain)
    samples = np.array([.2, .3, .4])*sr
    level = 20*np.log10(np.linalg.norm(y[samples.astype(int)], axis=1)/.1)
    assert level == pytest.approx([-6, -3, 0], abs=.2)
    p = Project.open(song)
    tracks = copy.deepcopy(p.data['tracks'])
    next(v for v in tracks if v['id'] == 'trk_bass')['chain'] = [
        {'id': 'band', 'type': 'band_automation', 'reason': 'test', 'params': {'lo_hz': 40, 'hi_hz': 300, 'gain': [[0, -6], [1, 0]]}},
        {'id': 'shape', 'type': 'volume_shaper', 'reason': 'test', 'params': {'bpm': 137, 'band_lo_hz': 40, 'band_hi_hz': 300}}]
    p.set('/tracks', tracks, actor='human')
    full = MR.render_track(p, 'trk_bass')[0]
    part = MR.render_track(p, 'trk_bass', start=4000, length=3000)[0]
    assert part.tobytes() == full[4000:7000].tobytes()


def test_shaper_knots_db_linear_smooth_and_band():
    sr = 48000; x = np.full((sr, 1), .1)
    for interp in ('linear', 'smooth'):
        p = P.validate_params('volume_shaper', {'bpm': 120, 'smooth_ms': 0, 'interp': interp})
        y = volume_shaper(x, sr, p)[0]
        indices = [0, 6000, 12000, 23999, 24000]
        db = 20*np.log10(y[indices, 0]/.1)
        assert db == pytest.approx([-6, 0, 0, 0, -6], abs=.1)
    p = P.validate_params('volume_shaper', {'note': 'none', 'period_ms': 1000, 'smooth_ms': 0, 'shape': [[0, 0], [1, 1]]})
    assert modulation(sr, sr, p)[sr//2] == pytest.approx(-3)  # y interpolation is dB-linear
    for f in (25, 1600):
        x = (.1*np.sin(2*np.pi*f*np.arange(sr)/sr))[:, None]
        y = render('volume_shaper', x, note='none', shape=[[0, 0], [1, 0]],
                   smooth_ms=0, band_lo_hz=100, band_hi_hz=400)
        assert abs(20*np.log10(np.linalg.norm(y[sr//2:])/np.linalg.norm(x[sr//2:]))) <= .2


@pytest.mark.parametrize('interp', ['linear', 'smooth'])
@pytest.mark.parametrize('smooth', [0, 2])
def test_shaper_block_and_excerpt_bytes(interp, smooth):
    p = P.validate_params('volume_shaper', {'bpm': 137, 'origin_s': .12345, 'phase': .31,
                                           'smooth_ms': smooth, 'interp': interp})
    full = modulation(5000, 44100, p)
    for size in (64, 1024):
        blocks = np.concatenate([modulation(min(size, 5000-s), 44100, p, start_sample=s)
                                 for s in range(0, 5000, size)])
        assert blocks.tobytes() == full.tobytes()
    assert modulation(901, 44100, p, start_sample=3099).tobytes() == full[3099:4000].tobytes()


@pytest.mark.parametrize('note', P.NOTE_VALUES[1:])
def test_thousand_periods_without_drift(note):
    sr = 44100; bpm = 137
    p = P.validate_params('volume_shaper', {'bpm': bpm, 'note': note, 'smooth_ms': 0})
    period = P.note_ms(note, bpm)*sr/1000
    at = round(1000*period)
    phases = curves.phase_positions(3, sr, start_sample=at-1, note=note, bpm=bpm)
    assert np.min(np.minimum(phases, 1-phases))*period <= .5 + 1e-6
    assert np.isfinite(modulation(3, sr, p, start_sample=at-1)).all()


def test_sample_grid_later_wins_and_gain_excerpts():
    x = np.full((10, 1), .1)
    gain = [[0, -2], [.000001, -4], [.1, 0]]
    y = render('gain_automation', x, gain=gain)
    assert y[0, 0] == pytest.approx(.1*10**(-4/20))
    from mankomix.dspx.procs.gain_automation import gain_automation
    p = P.validate_params('gain_automation', {'gain': gain})
    assert gain_automation(x[3:8], 48000, p, start_sample=3)[0].tobytes() == y[3:8].tobytes()


def test_defaults_limits_and_registration():
    specs = {k: P.PROCESSORS[k] for k in ('volume_shaper', 'band_automation', 'gain_automation')}
    expected = {'shape': [[0, 0], [.25, 1], [1, 1]], 'depth_db': 6, 'note': '1/4', 'bpm': 0,
                'period_ms': 500, 'origin_s': 0, 'phase': 0, 'smooth_ms': 2,
                'band_lo_hz': 0, 'band_hi_hz': 0, 'interp': 'linear'}
    assert {p['id']: p['default'] for p in specs['volume_shaper']['params']} == expected
    assert {p['id']: p['default'] for p in specs['band_automation']['params']} == {'lo_hz': 60, 'hi_hz': 250, 'gain': [], 'slope_db_oct': 12}
    assert specs['volume_shaper']['stages'] == specs['band_automation']['stages'] == ['track', 'bus']
    for k, spec in specs.items():
        assert spec['implemented'] and spec['master_slot'] is None and k in D.TIME_VARYING
    # Metadata defaults validate; unresolved default tempo is rejected at execution.
    assert P.validate_params('volume_shaper', {}) == expected
    with pytest.raises(ParamError):
        render('volume_shaper', np.zeros((100, 1)))
    x = np.zeros((100, 1))
    for kind, spec in specs.items():
        base = {'note': 'none'} if kind == 'volume_shaper' else {}
        for item in spec['params']:
            if item['type'] in ('float', 'int'):
                for value in (item['min'], item['max']):
                    params = {**base, item['id']: value}
                    if item['id'] == 'band_lo_hz' and value:
                        params['band_hi_hz'] = 23000
                    if item['id'] == 'band_hi_hz' and value:
                        params['band_lo_hz'] = 20
                    if item['id'] == 'lo_hz' and value == 8000:
                        params['hi_hz'] = 20000
                    if item['id'] == 'hi_hz' and value == 60:
                        params['lo_hz'] = 20
                    if item['id'] == 'bpm' and value == 0:
                        params['note'] = 'none'
                    assert np.isfinite(render(kind, x, sr=96000, **params)).all()
        bad = {'gain': [[0, -25 if kind == 'band_automation' else -1e12-1]]}
        for params in ({'unknown': 1}, bad if kind != 'volume_shaper' else {'shape': []}):
            with pytest.raises(ParamError):
                render(kind, x, **{**base, **params})


def test_curve_cardinality_and_cross_parameter_limits():
    x = np.full((100, 1), .1)
    shape = [[i/63, i/63] for i in range(64)]
    assert np.isfinite(render('volume_shaper', x, note='none', shape=shape)).all()
    knots = [[i/48000, -3] for i in range(65536)]
    for kind in ('band_automation', 'gain_automation'):
        assert np.isfinite(render(kind, x, gain=knots)).all()
        with pytest.raises(ParamError):
            render(kind, x, gain=knots + [[2, 0]])
    for params in ({'shape': [[i/64, 0] for i in range(65)]}, {'bpm': 19},
                   {'band_lo_hz': 100, 'band_hi_hz': 0}, {'band_hi_hz': 24000, 'band_lo_hz': 100}):
        with pytest.raises(ParamError):
            render('volume_shaper', x, **{'note': 'none', **params})
    with pytest.raises(ParamError):
        render('band_automation', x, lo_hz=400, hi_hz=100)


@pytest.mark.parametrize('kind', ['volume_shaper', 'band_automation', 'gain_automation'])
def test_common_contract(kind):
    params = ({'bpm': 120, 'smooth_ms': 0, 'shape': [[0, .5], [1, .5]]} if kind == 'volume_shaper'
              else {'gain': [[0, -3]], **({'lo_hz': 500, 'hi_hz': 2000} if kind == 'band_automation' else {})})
    neutral = {'depth_db': 0, 'bpm': 120} if kind == 'volume_shaper' else {'gain': []}
    def probe(x, y, sr, p):
        sl = slice(sr//10, None)
        level = 20*np.log10(np.linalg.norm(y[sl])/np.linalg.norm(x[sl]))
        return {'passed': abs(level+3) < .2, 'gain_db': float(level)}
    assert_common_tests(kind, params=params, neutral=neutral, sr_probe=probe, seconds=.2,
                        stages=P.PROCESSORS[kind]['stages'], latency_params=neutral)
