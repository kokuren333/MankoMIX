"""W4e note inspection, BB-18 pitch edits and persistent vocoder controls."""
import copy
import hashlib
import json
import shutil
import subprocess
import sys

import numpy as np
import pytest

from mankomix.core.project import Project
from mankomix.core import mixrender as mr
from mankomix.core.errors import InputError
from mankomix.director import direction as D, edit as E, derived as B, commands as C, xops as X
from mankomix.director.xops import edit_pitch as P, vocode as V
from mankomix.director.xops._pitch_notes import observe
from mankomix.director.commands.pitch_notes import COMMANDS
from tests import test_upgrade2_duck as T
from tests.test_tk_w4_0 import song, doc, move, invoke
from tests import toolimpl_harness as H


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path / 'home'))


def tone(sr, seconds, midi=57, drift=0):
    t = np.arange(round(sr*seconds))/sr
    hz = 440*2**((midi-69+(drift/100)*(t/seconds-.5))/12)
    phase = 2*np.pi*np.cumsum(hz)/sr
    return (.12*np.sin(phase))[:, None]


def emit(name, **values):
    print(name, json.dumps(values, sort_keys=True))


def test_eight_notes_cli_readonly_repeat_and_section(tmp_path, monkeypatch, capsys):
    sr = T.SR
    midis = [57, 60, 62, 64, 65, 67, 69, 72]
    audio = np.concatenate([tone(sr, .4, m) for m in midis])
    root = T._make(tmp_path / 'melody', {'vocals': np.repeat(audio, 2, axis=1)})
    monkeypatch.setattr(C, 'COMMANDS', list(COMMANDS))
    monkeypatch.setattr(C, '_loaded', True)
    before = C._snapshot(root)
    a = invoke(COMMANDS[0], root, ['--target', 'trk_vocals'])
    assert a == invoke(COMMANDS[0], root, ['--target', 'trk_vocals'])
    assert C._snapshot(root) == before
    assert a['count'] == 8, a
    errors = [100*(row['pitch_midi']-m) for row, m in zip(a['notes'], midis)]
    boundaries = [abs(row['t0']-i*.4)*1000 for i, row in enumerate(a['notes'])]
    boundaries += [abs(row['t1']-(i+1)*.4)*1000 for i, row in enumerate(a['notes'])]
    assert max(abs(v) for v in errors) <= 5
    assert max(boundaries) <= 20
    assert all(r['id'] == f"n_{r['start_sample']}" for r in a['notes'])
    assert all({'cents_off', 'drift_cents', 'vibrato', 'confidence', 'level_db'} <= r.keys() for r in a['notes'])
    assert 'direction pitch notes' in C.cli_only()
    from mankomix.cli import main as cli
    assert cli.main(['--project', str(root), 'direction', 'pitch', 'notes', '--target', 'trk_vocals']) == 0
    assert json.loads(capsys.readouterr().out) == a
    section = invoke(COMMANDS[0], root, ['--target', 'trk_vocals', '--section', 'sec1'])
    assert all(r in a['notes'] for r in section['notes'])
    section = invoke(COMMANDS[0], root, ['--target', 'trk_vocals', '--section', '{"t0_s":0.4,"t1_s":1.2}'])
    assert section['section_samples'] == [round(.4*sr), round(1.2*sr)]
    assert C._snapshot(root) == before
    emit('NOTES', count=a['count'], max_pitch_error_cents=max(map(abs, errors)), max_boundary_error_ms=max(boundaries))


@pytest.mark.parametrize('extra', [['--a4', '399'], ['--lo-hz', 'nan'], ['--hi-hz', '100'],
                                  ['--target', 'bus_mix'], ['--section', 'unknown']])
def test_cli_bad_inputs_still_readonly(song, monkeypatch, extra):
    monkeypatch.setattr(C, 'COMMANDS', list(COMMANDS))
    monkeypatch.setattr(C, '_loaded', True)
    before = C._snapshot(song)
    with pytest.raises(InputError):
        invoke(COMMANDS[0], song, ['--target', 'trk_bass', *extra])
    assert C._snapshot(song) == before


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
@pytest.mark.parametrize('channels', [1, 2])
def test_selected_note_shift_and_untouched_null(sr, channels):
    x = np.concatenate([tone(sr, .4, m) for m in (57, 60, 64)])
    x = np.repeat(x, channels, axis=1)
    p = P.resolve({'notes': [{'t0': .4, 't1': .8, 'shift_cents': 100}]})
    p['time_map'] = P.time_map(p['notes'], len(x), sr)
    y = P.process(x, sr, p)
    hz = H.fundamental_frequency(y[round(.5*sr):round(.7*sr)], sr, low_hz=260, high_hz=300)
    cents = float(1200*np.log2(hz/(440*2**((61-69)/12))))
    assert abs(cents) <= 5
    assert np.array_equal(x[:round(.38*sr)], y[:round(.38*sr)])
    assert np.array_equal(x[round(.82*sr):], y[round(.82*sr):])
    assert y.tobytes() == P.process(x, sr, p).tobytes()
    emit('SHIFT', sr=sr, channels=channels, error_cents=cents, untouched_null_dbfs=-300)


def test_flatten_and_vibrato():
    sr = 48000
    x = tone(sr, 1.6, drift=70)
    p = P.resolve({'notes': [{'t0': 0, 't1': 1.6, 'flatten': 1}], 'transition_ms': 0})
    p['time_map'] = [[0, 0], [len(x), len(x)]]
    y = P.process(x, sr, p)
    from mankomix.dspx.bb.psola import voice_track
    old, new = [voice_track(v, sr) for v in (x, y)]
    ix = (old.samples > .25*sr) & (old.samples < 1.35*sr) & old.voiced & new.voiced
    old_c = 1200*np.log2(old.f0_hz[ix])
    new_c = 1200*np.log2(new.f0_hz[ix])
    ratio = float(np.std(new_c)/np.std(old_c))
    assert ratio <= .2
    emit('FLATTEN', input_std_cents=float(np.std(old_c)), output_std_cents=float(np.std(new_c)), ratio=ratio)


def test_vibrato_observation_and_amplitude_edit():
    sr = 24000
    t = np.arange(sr*2)/sr
    frequency = 220*2**((40*np.sin(2*np.pi*5*t))/1200)
    x = (.12*np.sin(2*np.pi*np.cumsum(frequency)/sr))[:, None]
    _, rows = observe(x, sr)
    assert len(rows) == 1
    assert abs(rows[0]['vibrato']['hz']-5) <= .5
    assert 55 <= rows[0]['vibrato']['width_cents'] <= 100
    p = P.resolve({'notes': [{'t0': 0, 't1': 2, 'vibrato': 0}], 'transition_ms': 0})
    p['time_map'] = [[0, 0], [len(x), len(x)]]
    y = P.process(x, sr, p)
    from mankomix.dspx.bb.psola import voice_track
    a, b = [voice_track(v, sr) for v in (x, y)]
    ix = a.voiced & b.voiced & (a.samples > .4*sr) & (a.samples < 1.6*sr)
    ratio = float(np.std(np.log2(b.f0_hz[ix]))/np.std(np.log2(a.f0_hz[ix])))
    assert ratio <= .3
    emit('VIBRATO', measured_hz=rows[0]['vibrato']['hz'], width_cents=rows[0]['vibrato']['width_cents'], remaining_std_ratio=ratio)


def test_move_head_50ms_and_later_identity():
    sr = 48000
    x = np.zeros((sr*2, 1))
    for t in (.5, 1.3):
        x[round(t*sr), 0] = .8
    p = P.resolve({'notes': [{'t0': .5, 't1': 1., 'move_ms': 50}]})
    p['time_map'] = P.time_map(p['notes'], len(x), sr)
    y = P.process(x, sr, p)
    head = int(np.argmax(abs(y[:sr, 0])))/sr
    assert abs(head-.55) <= .005
    assert len(y) == len(x)
    assert np.array_equal(y[sr:], x[sr:])
    emit('MOVE', head_s=head, later_head_s=1.3, frames=len(y))


@pytest.mark.parametrize('key, bad', [('shift_cents', 1201), ('flatten', -.1), ('vibrato', 2.01),
                                    ('formant_cents', -601), ('move_ms', 201), ('gain_db', 12.01),
                                    ('flatten', True), ('gain_db', float('inf'))])
def test_edit_note_ranges(song, key, bad):
    m = move('edit_pitch', notes=[{'t0': .1, 't1': .8, key: bad}])
    errors = []
    P.validate(m, X.ValidationContext(D._Project(song), {}, '', lambda *args: errors.append(args)))
    assert errors


@pytest.mark.parametrize('params', [{}, {'notes': [None]}, {'notes': [{'t0': .4, 't1': .2}]},
    {'notes': [{'t0': 0, 't1': .6}, {'t0': .5, 't1': .8}]}, {'notes': [], 'bogus': 1},
    {'notes': [], 'formant': 1}, {'notes': [], 'transition_ms': 201}, {'notes': [{}]*257}])
def test_malformed_pitch_params(params):
    errors = []
    P.validate(move('edit_pitch', **params), X.ValidationContext(None, {}, '', lambda *args: errors.append(args)))
    assert errors


def test_defaults_bounds_and_neutral_without_derived(song, tmp_path):
    assert P.resolve({'notes': []})['transition_ms'] == 30
    m = move('edit_pitch', notes=[{'t0': .1, 't1': .8}])
    assert P.resolve(m['params'])['notes'][0] == {'t0': .1, 't1': .8, **P.DEFAULTS}
    plan = P.derive(song, m)
    assert isinstance(plan, X.ClipPlan) and not plan.changes and plan.record['identical']
    before = E.raw_track(song, 'trk_bass')[0]
    assets = copy.deepcopy(Project.open(song).data['assets'])
    parsed = doc(tmp_path, [m])
    result = D.apply(song, parsed['path'])
    assert result['applied'], result
    assert Project.open(song).data['assets'] == assets
    assert not B._ledger(song, parsed['id'])['derived']
    assert E.raw_track(song, 'trk_bass')[0].tobytes() == before.tobytes()
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01']


def test_nonoverlapping_note_order_is_canonical(song):
    notes = [{'t0': .6, 't1': .8}, {'t0': .1, 't1': .3}]
    errors = []
    P.validate(move('edit_pitch', notes=notes), X.ValidationContext(D._Project(song), {}, '', lambda *a: errors.append(a)))
    assert not errors
    assert [n['t0'] for n in P.resolve({'notes': notes})['notes']] == [.1, .6]


@pytest.mark.parametrize('key', list(P.RANGES))
def test_edit_pitch_parameter_endpoints(song, key):
    for value in P.RANGES[key]:
        errors = []
        P.validate(move('edit_pitch', notes=[{'t0': .3, 't1': .8, key: value}]),
                   X.ValidationContext(D._Project(song), {}, '', lambda *a: errors.append(a)))
        assert not errors


def test_standard_pitch_path_without_formant_preservation():
    sr = 24000
    x = tone(sr, .8)
    p = P.resolve({'notes': [{'t0': 0, 't1': .8, 'shift_cents': 100}], 'formant': False})
    p['time_map'] = [[0, 0], [len(x), len(x)]]
    y = P.process(x, sr, p)
    hz = H.fundamental_frequency(y[6000:14000], sr, low_hz=220, high_hz=250)
    error = float(1200*np.log2(hz/(220*2**(1/12))))
    assert abs(error) <= 5
    emit('STANDARD_SHIFT', error_cents=error)


def test_edit_apply_regenerate_and_revert(song, tmp_path):
    before = E.raw_track(song, 'trk_bass')[0]
    original_clips = copy.deepcopy(Project.open(song).data['tracks'][0]['clips'])
    m = move('edit_pitch', notes=[{'t0': .1, 't1': .8, 'shift_cents': 100, 'gain_db': -2}])
    plan = P.derive(song, m)
    assert isinstance(plan, X.DerivedPlan) and plan.fit == 'keep_length'
    parsed = doc(tmp_path, [m])
    result = D.apply(song, parsed['path'])
    assert result['applied'], result
    row = B._ledger(song, parsed['id'])['derived']['m01']
    assert row['details']['measurements']['before_frames'] == row['details']['measurements']['after_frames']
    project = Project.open(song)
    path = project.asset_path(row['result']['asset'])
    contents = path.read_bytes()
    path.unlink()
    cache = B._cache(song, row['key'])
    cache.unlink()
    cache.with_suffix('.json').unlink()
    assert B.regenerate(song, parsed['id'], 'm01', calculate=P.process)['regenerated']
    assert path.read_bytes() == contents
    E.revert(song, parsed['id'])
    assert E.raw_track(song, 'trk_bass')[0].tobytes() == before.tobytes()
    assert Project.open(song).data['tracks'][0]['clips'] == original_clips


@pytest.mark.parametrize('key', list(V.RANGES))
def test_vocode_ranges_and_defaults(song, key):
    for value in (V.RANGES[key][0], V.RANGES[key][1], V.DEFAULTS[key]):
        errors = []
        V.validate(move('vocode', key='trk_vocals', **{key: value}),
                   X.ValidationContext(D._Project(song), {}, '', lambda *a: errors.append(a)))
        if key == 'hi_hz' and value >= .49*T.SR:
            assert errors
        else:
            assert not errors
    errors = []
    V.validate(move('vocode', key='trk_vocals', **{key: V.RANGES[key][1]+1}),
               X.ValidationContext(D._Project(song), {}, '', lambda *a: errors.append(a)))
    assert errors


def test_vocode_control_equivalence_apply_persistence_regenerate_revert(song, tmp_path):
    from mankomix.dspx.bb import band_envelopes as bank
    from mankomix.director.xops import _resources
    m = move('vocode', key='trk_vocals')
    plan = V.expand(D._Project(song), m)
    x, sr, _ = E.raw_track(song, 'trk_vocals')
    p = plan.controls[0].params
    payload = V.calculate_control(x, sr, p)
    internal = bank.analyze(x, sr, p).mean(axis=2)
    times = np.arange(len(payload['values']))*.005*sr
    for b in range(p['bands']):
        assert np.array_equal(payload['values'][:, b], np.interp(times, np.arange(len(x)), internal[:, b], right=0))
    assert np.array_equal(payload['values'], V.calculate_control(x, sr, p)['values'])
    assert not np.any(V.calculate_control(np.zeros_like(x), sr, p)['values'])
    parsed = doc(tmp_path, [m])
    before = C._snapshot(song)
    prop, rec, _ = D.build_proposal(D._Project(song), parsed)
    assert (prop, rec) == D.build_proposal(D._Project(song), parsed)[:2]
    assert C._snapshot(song) == before
    original = mr.render_mix(Project.open(song))[0]
    applied = D.apply(song, parsed['path'])
    assert applied['applied'], applied
    resources = applied['record']['moves']['m01']['resources']
    assert _resources.check(song, parsed['id'], 'm01', resources)
    row = B._ledger(song, parsed['id'])['controls']['m01__envelopes']
    aid = row['result']['asset']
    assert not any(a['id'] == aid for a in Project.open(song).data['assets'])
    with B.control_context(song):
        wet = mr.render_mix(Project.open(song))[0]
        from mankomix.dsp import processors
        from mankomix.dspx.procs.vocoder import vocoder
        from mankomix.dspx.procs.band_envelope import band_envelope
        vp = processors.validate_params('vocoder', {'unvoiced': 0})
        carrier = np.repeat(bank.carrier(len(x), sr, vp), x.shape[1], axis=1)
        bp = processors.validate_params('band_envelope', {'envelopes': aid})
        external = band_envelope(carrier, sr, bp)[0]
        direct = vocoder(x, sr, vp)[0].mean(axis=1, keepdims=True)
        region = slice(round(.2*sr), round(.9*sr))
        relative = float(np.sqrt(np.mean((external[region]-direct[region])**2)/np.mean(direct[region]**2)))
        assert relative < .01
        emit('VOCODER_EQUIVALENCE', relative_rms_error=relative)
    code = ('import sys,hashlib; from mankomix.core.project import Project; '
            'from mankomix.core.mixrender import render_mix; '
            'print(hashlib.sha256(render_mix(Project.open(sys.argv[1]))[0].tobytes()).hexdigest())')
    child = subprocess.run([sys.executable, '-B', '-c', code, str(song)], capture_output=True, text=True, timeout=60, check=True)
    assert child.stdout.strip() == hashlib.sha256(wet.tobytes()).hexdigest()
    dest, cache = B._control_paths(song, row)
    contents = dest.read_bytes()
    dest.unlink()
    cache.unlink()
    assert B.regenerate_control(song, parsed['id'], 'm01', 'envelopes', calculate=V.calculate_control)['regenerated']
    assert dest.read_bytes() == contents
    dest.write_text('{}', encoding='utf-8')
    assert not _resources.check(song, parsed['id'], 'm01', resources)
    dest.write_bytes(contents)
    E.revert(song, parsed['id'])
    assert mr.render_mix(Project.open(song))[0].tobytes() == original.tobytes()
    emit('CONTROL', asset=aid, result_sha256=row['result']['sha256'], frames=len(payload['values']), hop_s=.005)


def test_unused_ops_are_inert(song, tmp_path, monkeypatch):
    parsed = doc(tmp_path, [move('gain', delta_db=-1)])
    # Production discovery is complete before the empty extension registry comparison.
    X.load(D.OPS)
    a = D.validate(parsed, song)
    proposal = D.build_proposal(D._Project(song), parsed)
    monkeypatch.setattr(X, 'OPS', {})
    assert D.validate(parsed, song) == a
    assert D.build_proposal(D._Project(song), parsed) == proposal


def test_unused_validation_apply_check_bytes(song, tmp_path, monkeypatch):
    twin, floor = tmp_path / 'twin', tmp_path / 'floor'
    shutil.copytree(song, twin)
    shutil.copytree(song, floor)
    T._render(floor)
    parsed = doc(tmp_path, [move('gain', delta_db=-1)])
    def capture(root):
        validation = D.canonical_block(D.validate(parsed, root)).encode()
        proposal = D.canonical_block(D.build_proposal(D._Project(root), parsed)).encode()
        D.apply(root, parsed['path'])
        applied = (root / 'directions' / f"{parsed['id']}.apply.json").read_bytes()
        T._render(root)
        checked = D.canonical_block(D.check(root, floor, parsed['path'])).encode()
        outcome = (root / 'directions' / f"{parsed['id']}.outcome.json").read_bytes()
        return validation, proposal, applied, checked, outcome
    with monkeypatch.context() as disabled:
        disabled.setattr(X, 'specs', lambda builtins=(): {})
        before = capture(song)
    assert capture(twin) == before


def test_formant_gain_and_extreme_note_controls_are_finite():
    sr = 24000
    x = tone(sr, .5)
    p = P.resolve({'notes': [{'t0': 0, 't1': .5, 'formant_cents': 600, 'gain_db': 12}]})
    p['time_map'] = [[0, 0], [len(x), len(x)]]
    y = P.process(x, sr, p)
    assert np.isfinite(y).all() and y.shape == x.shape
    p['notes'][0]['formant_cents'] = 0
    y = P.process(x, sr, p)
    ratio = np.sqrt(np.mean(y[2000:-2000]**2)/np.mean(x[2000:-2000]**2))
    assert abs(20*np.log10(ratio)-12) < 1e-9
    for cents in (-1200, 1200):
        p = P.resolve({'notes': [{'t0': 0, 't1': .5, 'shift_cents': cents}]})
        p['time_map'] = [[0, 0], [len(x), len(x)]]
        assert np.isfinite(P.process(x, sr, p)).all()


def test_clip_local_offset_and_ambiguous_clip_rejection(song):
    project = Project.open(song)
    tracks = copy.deepcopy(project.data['tracks'])
    c = tracks[0]['clips'][0]
    c['timeline_start'] = round(.1*T.SR)
    c['length'] = round(.8*T.SR)
    project.set('/tracks', tracks, actor='human')
    m = move('edit_pitch', notes=[{'t0': .1, 't1': .7, 'gain_db': -3}])
    plan = P.derive(song, m)
    assert [plan.start, plan.end] == [round(.1*T.SR), round(.9*T.SR)]
    tracks[0]['clips'].append({**c, 'id': 'clp_second'})
    Project.open(song).set('/tracks', tracks, actor='human')
    errors = []
    P.validate(m, X.ValidationContext(D._Project(song), {}, '', lambda *a: errors.append(a)))
    assert errors
