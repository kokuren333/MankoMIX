"""W4a measured suggestion quality, CLI contracts and reference invariants."""
import argparse
import hashlib
import json

import numpy as np
import pytest

from mankomix.cli.main import main
from mankomix.core import audio_io
from mankomix.core.errors import InputError
from mankomix.core.measure.bands import Band, Spectrum
from mankomix.core.measure.spectral import band_crest
from mankomix.director import commands as C, direction as D
from mankomix.director.commands import _eq_reference as E
from mankomix.director.commands import ref_matcheq as M, ref_balance as B, suggest_lowend as L, suggest_eq as S
from tests import toolimpl_harness as H
from tests import test_upgrade2_duck as T

SR = T.SR


def args(module, root, *flags):
    p = argparse.ArgumentParser()
    module.add_args(p)
    ns = p.parse_args(list(flags))
    ns.project = str(root)
    return ns


def snapshot(root):
    return C._snapshot(root)


@pytest.fixture
def material(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path/'home'))
    x = H.pink_noise(sr=SR, seconds=3, channels=2, seed=73, dbfs=-24)
    root = T._make(tmp_path/'song', {'bass': x})
    p = tmp_path/'reference.wav'
    audio_io.write(p, x, SR, subtype='DOUBLE')
    return root, x, p


def shape(x, lo, hi, gain):
    from scipy import fft
    f = fft.rfftfreq(len(x), 1/SR)
    z = fft.rfft(x, axis=0, workers=1)
    z[(f >= lo) & (f < hi)] *= 10**(gain/20)
    return fft.irfft(z, n=len(x), axis=0, workers=1)


def test_registration_and_cli_only():
    rows = {r['path']: r for r in C.declarations()}
    for path in [('suggest', 'eq'), ('suggest', 'lowend'), ('ref', 'matcheq'), ('ref', 'balance')]:
        assert rows[path]['writes'] is False
        assert 'direction '+' '.join(path) in C.cli_only()
    # No new operation is registered; these commands propose built-in chain_add.


@pytest.mark.parametrize('module,flags', [
    (M, ['--target', 'mix', '--ref', 'REF']),
    (L, ['--ref-kb', 'REF']),
    (B, ['--ref', 'REF', '--over-time', '1']),
    (S, ['--target', 'trk_bass']),
])
def test_readonly_repeat_and_cli(material, module, flags, capsys):
    root, _, ref = material
    flags = [str(ref) if f == 'REF' else f for f in flags]
    ns = args(module, root, *flags)
    before = snapshot(root)
    first = C.execute(module.COMMANDS[0], ns, root)
    second = C.execute(module.COMMANDS[0], ns, root)
    assert first == second
    assert snapshot(root) == before
    path = list(module.COMMANDS[0]['path'])
    assert main(['direction', *path, *flags, '--project', str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert snapshot(root) == before


def test_spectrum_uses_existing_loudness_and_welch(material):
    _, x, _ = material
    spec = E.spectrum(x, SR)
    assert spec['lufs_i'] == E.RS._lufs(x, SR)
    pieces = []
    for i in range(0, len(x)-8192+1, 4096):
        pieces.append(np.mean([E.RS._welch(x[i:i+8192, c:c+1], SR)[1] for c in range(2)], axis=0))
    expected = np.mean(pieces, axis=0)*10**(spec['gain_db']/10)
    assert np.array_equal(expected, spec['power_density'])
    anti = np.stack([x[:, 0], -x[:, 0]], axis=1)
    assert E.power(E.spectrum(anti, SR), 20, 10000) > 0


def test_silence_frames_omitted_and_silence_is_finite(material):
    _, x, _ = material
    spec = E.spectrum(np.concatenate([np.zeros_like(x), x]), SR)
    assert 0 < spec['active_frames'] < spec['total_frames']
    silence = E.spectrum(np.zeros_like(x), SR)
    assert silence['active_frames'] == 0
    json.dumps(E.clean(silence), allow_nan=False)


def test_resonance_location_and_clean_noise(material):
    _, x, _ = material
    clean, _ = S.resonance(x, SR, 20, 10000, 6)
    assert clean == []
    shaped = shape(x, 3000/2**.025, 3000*2**.025, 12)
    candidates, evidence = S.resonance(shaped, SR, 20, 10000, 6)
    assert evidence['active_frames'] > 0
    assert any(abs(np.log2(c['freq_hz']/3000)) <= 1/12 for c in candidates), candidates
    print('W4a resonance:', json.dumps(candidates[0], sort_keys=True))


def test_flat_noise_no_suggestions(material):
    root, _, _ = material
    result = S.run(args(S, root, '--target', 'trk_bass'))
    assert result['candidates'] == []
    assert result['measurements']['reference_tilt'] is None


def test_candidate_moves_validate(material, tmp_path):
    root, x, _ = material
    shaped = shape(x, 3000/2**.025, 3000*2**.025, 12)
    source_root = T._make(tmp_path/'resonant', {'bass': shaped})
    result = S.run(args(S, source_root, '--target', 'trk_bass'))
    assert result['candidates']
    for candidate in result['candidates']:
        block = T._block([candidate['chain_add']])
        parsed = D.parse_document(T._doc(tmp_path/'doc', block))
        validation = D.validate(parsed, source_root)
        assert validation['ok'], validation['errors']


def test_masking_offers_both_sides(material, tmp_path):
    _, x, _ = material
    root = T._make(tmp_path/'masked', {'bass': x*.1, 'drums': x})
    ns = args(S, root, '--target', 'trk_bass', '--against', 'trk_drums')
    candidates, evidence = S.masking(ns, 20, 10000)
    assert candidates and evidence['model'] == 'P-02'
    for i in range(0, len(candidates), 2):
        assert {c['target'] for c in candidates[i:i+2]} == {'trk_bass', 'trk_drums'}


def test_matcheq_known_curve_and_applied_error(material, tmp_path):
    root, x, _ = material
    # A broad known shelf; make an RMS-neutral shape and compare after LUFS matching.
    ref_audio = shape(x, 400, 10000, 4)
    ref = tmp_path/'eq.wav'
    audio_io.write(ref, ref_audio, SR, subtype='DOUBLE')
    result = M.run(args(M, root, '--target', 'mix', '--ref', str(ref), '--band-hz', '100', '10000', '--points', '64'))
    curve = result['curve']
    assert len(curve) == 64 and curve[0][1] == curve[-1][1] == 0
    gain_diff = result['reference_spectrum']['gain_db']-result['target_spectrum']['gain_db']
    inside = [(f, g) for f, g in curve if 120 <= f <= 300 or 600 <= f <= 8000]
    assert max(abs(g-(4*(f >= 400)+gain_diff)) for f, g in inside) <= 1
    rendered = H.render('fir_eq', x, SR, result['chain_add']['params'])
    # Harness render returns audio (with engine latency compensation).
    out = rendered.audio if hasattr(rendered, 'audio') else rendered
    spec = E.spectrum(out, SR)
    ref_spec = result['reference_spectrum']
    grid = np.geomspace(120, 8000, 40)
    error = E.smooth_db(ref_spec, grid, 1/3)-E.smooth_db(spec, grid, 1/3)
    assert np.max(np.abs(error)) < 1., float(np.max(np.abs(error)))
    print('W4a match maximum error dB:', float(np.max(np.abs(error))))


def test_lowend_distribution_direction_and_limit(material, tmp_path):
    root, x, ref = material
    result = L.run(args(L, root, '--ref-kb', str(ref)))
    # The imported project uses FLOAT source audio; tolerate its numerical floor.
    assert result['candidates'] == []
    changed = shape(x, 40, 80, 6)
    p = tmp_path/'changed.wav'
    audio_io.write(p, changed, SR, subtype='DOUBLE')
    result = L.run(args(L, root, '--target', str(p), '--ref-kb', str(ref), '--max-db', '3'))
    affected = [r for r in result['bands'] if r['band_hz'][0] >= 40 and r['band_hz'][1] <= 80.01]
    assert affected and all(r['proposed_gain_db'] == -3 for r in affected)
    assert len(result['candidates']) <= 4
    assert E.LOW_NOTE in result['notes']
    assert result['confidence'] == 'low'


def test_balance_identity_third_and_crest(material):
    root, x, ref = material
    result = B.run(args(B, root, '--audio', str(ref), '--ref', str(ref), '--bands', 'third'))
    assert all(row['inside'] for row in result['bands'])
    match = M.run(args(M, root, '--target', str(ref), '--ref', str(ref)))
    assert [r['target_db'] for r in result['bands']] == match['target_third_db']
    expected = band_crest(Spectrum(x, SR), [Band('low', 20., 250.)], x=x)['bands']['low']['crest_db']
    assert E.low_crest(x, SR) == expected
    assert result['low_crest']['target_db'] == expected
    assert 'candidates' not in result and 'chain_add' not in result


def test_balance_low_shift_only(material, tmp_path):
    root, _, _ = material
    # Keep low power small, with activity away from band edges, so that whole-
    # power normalization changes the other bands by less than 0.2 dB.
    x = H.sine(60, -44, sr=SR, seconds=3, channels=2)
    for freq in (1000, 4000, 10000):
        x += H.sine(freq, -24, sr=SR, seconds=3, channels=2)
    ref, target = tmp_path/'small_low.wav', tmp_path/'boosted.wav'
    audio_io.write(ref, x, SR, subtype='DOUBLE')
    audio_io.write(target, shape(x, 20, 250, 6), SR, subtype='DOUBLE')
    result = B.run(args(B, root, '--audio', str(target), '--ref', str(ref)))
    delta = [r['outside_db'] for r in result['bands']]
    assert delta[0] == pytest.approx(6., abs=.5)
    assert max(abs(v) for v in delta[1:]) < .2
    print('W4a balance outside dB:', delta)


def test_sections_windows_and_deduplicated_refs(material):
    root, _, ref = material
    ns = args(B, root, '--audio', str(ref), '--ref', str(ref), str(ref), '--section', '0.5,2.5', '--over-time', '.5')
    result = B.run(ns)
    assert result['reference_count'] == 1 and len(result['over_time']) == 4
    assert result['over_time'][0]['start_s'] == .5
    assert result['over_time'][-1]['end_s'] == 2.5
    with pytest.raises(InputError):
        B.run(args(B, root, '--ref', str(ref), '--section', 'nan,2'))


def test_measurement_only_reference_and_old_digest_error(material, tmp_path):
    root, x, ref = material
    saved = tmp_path/'measured.json'
    saved.write_text(json.dumps({'spectrum': E.spectrum(x, SR), 'low_crest_db': E.low_crest(x, SR)}), encoding='utf-8')
    result = B.run(args(B, root, '--audio', str(ref), '--ref-kb', str(saved)))
    assert all(r['inside'] for r in result['bands'])
    study = tmp_path/'kb/references/works/test/refstudy.md'
    study.parent.mkdir(parents=True)
    study.write_text('# 測定資料（refstudy）\n- origin: `measured`\n', encoding='utf-8')
    with pytest.raises(InputError, match='no full Welch spectrum'):
        M.run(args(M, root, '--target', 'mix', '--ref', 'work_test', '--kb', str(tmp_path/'kb')))
    assert study.read_text(encoding='utf-8').endswith('`measured`\n')


@pytest.mark.parametrize('module,flags', [
    (M, ['--target', 'mix', '--ref', 'REF', '--points', '7']),
    (M, ['--target', 'mix', '--ref', 'REF', '--smooth-oct', 'nan']),
    (M, ['--target', 'mix', '--ref', 'REF', '--max-db', '13']),
    (L, ['--ref-kb', 'REF', '--max-db', '7']),
    (B, ['--ref', 'REF', '--over-time', '0']),
    (S, ['--target', 'trk_bass', '--max-candidates', '13']),
    (S, ['--target', 'trk_bass', '--min-excess-db', '2']),
    (S, ['--target', 'trk_bass', '--band-hz', '500', '20']),
    (S, ['--target', 'trk_bass', '--against', 'trk_bass']),
])
def test_ranges_reject_without_writes(material, module, flags):
    root, _, ref = material
    flags = [str(ref) if f == 'REF' else f for f in flags]
    before = snapshot(root)
    with pytest.raises(InputError):
        C.execute(module.COMMANDS[0], args(module, root, *flags), root)
    assert snapshot(root) == before


def test_missing_references_are_explicit_cli_error(material, capsys):
    root, _, _ = material
    for path in [('ref', 'balance'), ('suggest', 'lowend')]:
        assert main(['direction', *path, '--project', str(root)]) != 0
        capsys.readouterr()


def test_protected_files_and_profiles_unchanged(material):
    from mankomix import repo_data_root
    base = repo_data_root()
    paths = [p for d in ['profiles', 'knowledge'] for p in (base/d).glob('*.json')]
    before = {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    root, _, ref = material
    B.run(args(B, root, '--ref', str(ref)))
    assert before == {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_loudest_uses_existing_weighted_30s_blocks(material):
    from mankomix.core.measure.loudness import _Blocks
    root, _, _ = material
    x = H.sine(1000, -30, sr=SR, seconds=32, channels=1)
    x[SR:] *= 2
    _, interval = E.section_audio(x, SR, root, 'loudest')
    start = int(np.argmax(_Blocks(x, SR).lufs(30)))*round(.1*SR)
    assert interval == [start/SR, (start+30*SR)/SR]


def test_range_endpoints_defaults_and_reusable_spectrum(material, tmp_path):
    root, x, ref = material
    ns = args(M, root, '--target', str(ref), '--ref', str(ref))
    assert ns.smooth_oct == 1/3 and ns.max_db == 6 and ns.points == 32
    for smooth, maximum, points in [(1/12, 1., 8), (1., 12., 64)]:
        ns.smooth_oct, ns.max_db, ns.points = smooth, maximum, points
        result = M.run(ns)
        assert len(result['curve']) == points
        assert max(abs(g) for _, g in result['curve']) < 1e-10
        snapshot_file = tmp_path/'snapshot.json'
        snapshot_file.write_text(json.dumps({'spectrum': result['reference_spectrum']}), encoding='utf-8')
        # CLI-compatible JSON retains all nonzero spectral bins and original LUFS bits.
        measured = E.references(args(B, root, '--ref-kb', str(snapshot_file)))[0]['spectrum']
        assert measured['power_density'] == E.spectrum(x, SR)['power_density']
        assert measured['lufs_i'] == E.RS._lufs(x, SR)


def test_reference_moves_validate_and_lowend_boost(material, tmp_path):
    root, x, ref = material
    reference = tmp_path/'lowboost.wav'
    audio_io.write(reference, shape(x, 40, 80, 6), SR, subtype='DOUBLE')
    low = L.run(args(L, root, '--ref-kb', str(reference)))
    assert any(m['params']['gain_db'] == 3 for m in low['candidates'])
    match = M.run(args(M, root, '--target', 'trk_bass', '--ref', str(ref)))
    for m in [*low['candidates'], match['chain_add']]:
        parsed = D.parse_document(T._doc(tmp_path/'refdoc', T._block([m])))
        result = D.validate(parsed, root)
        assert result['ok'], result['errors']


def test_fewer_than_three_references_and_nonfinite_json(material, tmp_path):
    root, x, _ = material
    refs = []
    for seed in range(3):
        p = tmp_path/f'ref{seed}.wav'
        audio_io.write(p, H.pink_noise(sr=SR, seconds=1, channels=2, seed=seed), SR, subtype='DOUBLE')
        refs.append(str(p))
    assert B.run(args(B, root, '--ref', *refs))['confidence'] == 'high'
    broken = tmp_path/'broken.json'
    spec = E.spectrum(x, SR)
    spec['power_density'][0] = float('nan')
    broken.write_text(json.dumps(spec), encoding='utf-8')
    with pytest.raises(InputError):
        E.references(args(B, root, '--ref-kb', str(broken)))


def test_cli_implicit_current_project(material, monkeypatch, capsys):
    root, _, ref = material
    monkeypatch.chdir(root)
    before = snapshot(root)
    assert main(['direction', 'ref', 'balance', '--ref', str(ref)]) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == 'direction_ref_balance'
    assert snapshot(root) == before


def test_explicit_master_requires_a_render_without_creating_one(material):
    root, _, ref = material
    before = snapshot(root)
    with pytest.raises(InputError, match='existing master render'):
        M.run(args(M, root, '--target', 'master', '--ref', str(ref)))
    assert snapshot(root) == before


def test_masking_band_edges_never_emit_unusable_eq(material, tmp_path):
    _, x, _ = material
    root = T._make(tmp_path/'band_edges', {'bass': x*.1, 'drums': x})
    ns = args(S, root, '--target', 'trk_bass', '--against', 'trk_drums')
    candidates, _ = S.masking(ns, 20, 20000)
    assert candidates
    assert all(20 <= c['freq_hz'] <= SR*.45 and .02 <= c['bw_oct'] <= 6 for c in candidates)
    # No measured ERB centre exists above the renderer's usable range.
    candidates, _ = S.masking(ns, 11000, 20000)
    assert candidates == []
