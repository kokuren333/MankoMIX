"""W4c MIDI quality, read-only output contracts and independent SMF decoding."""
import json
import struct
import numpy as np
import pytest
from scipy import signal
from mankomix.cli.main import main
from mankomix.core.errors import InputError
from mankomix.director import commands as C
from mankomix.director.commands import extract_midi as M
from tests import test_upgrade2_duck as T
from tests.test_tk_w4c import args, train, home, SR


def read_smf(data):
    """Independent decoder for the explicit-status subset emitted here."""
    assert data[:4] == b'MThd' and struct.unpack('>IHHH', data[4:14]) == (6, 0, 1, 480)
    assert data[14:18] == b'MTrk'
    assert struct.unpack('>I', data[18:22])[0] == len(data)-22
    i, tick, active, notes, bends = 22, 0, {}, [], []
    while i < len(data):
        delta = 0
        while True:
            v = data[i]
            i += 1
            delta = delta*128+(v & 127)
            if v < 128:
                break
        tick += delta
        status = data[i]
        i += 1
        if status == 255:
            kind, length = data[i:i+2]
            i += 2+length
            if kind == 47:
                break
            continue
        a, b = data[i:i+2]
        i += 2
        if status & 240 == 144:
            active[(status & 15, a)] = (tick, b)
        elif status & 240 == 128:
            start, velocity = active.pop((status & 15, a))
            notes.append((start, tick, a, velocity))
        elif status & 240 == 224:
            bends.append((tick, a+128*b))
    assert not active
    return sorted(notes), bends



def test_midi_60_hits_velocity_roundtrip_readonly_and_cli(tmp_path, capsys):
    x, positions = train(60, kind='snare', levels=[.2, .4, .7, 1], interval=.3)
    root = T._make(tmp_path/'song', {'drums': x})
    flags = ['--target', 'trk_drums', '--kind', 'drums', '--threshold-db', '-40', '--min-interval-ms', '30']
    before = C._snapshot(root)
    out = C.execute(M.COMMANDS[0], args(M, root, *flags), root)
    rows = out['notes']
    assert len(rows) == 60
    errors = np.asarray([r['source_time_s']*SR for r in rows])-positions
    assert np.max(abs(errors)) <= .01*SR and np.median(abs(errors)) <= .003*SR
    v = np.array([r['velocity'] for r in rows]).reshape(-1, 4).mean(axis=0)
    assert np.all(np.diff(v) > 0)
    assert out == C.execute(M.COMMANDS[0], args(M, root, *flags), root)
    assert C._snapshot(root) == before
    assert main(['direction', 'extract', 'midi', *flags, '--project', str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == out
    assert C._snapshot(root) == before
    for dest in (tmp_path/'external'/'out.mid', root/'exports'/'out.mid'):
        written = C.execute(M.COMMANDS[0], args(M, root, *flags, '--out', str(dest)), root)
        notes, _ = read_smf(dest.read_bytes())
        assert notes == sorted((r['tick'], r['end_tick'], r['note'], r['velocity']) for r in written['notes'])
        written['written'] = False
        assert written == out
    print('midi_drum_count_median_max_ms', len(rows), np.median(abs(errors))/SR*1000, np.max(abs(errors))/SR*1000)



def test_midi_map_three_bands_and_quantize(tmp_path):
    x = np.zeros((4*SR, 1))
    labels = []
    rng = np.random.Generator(np.random.PCG64(4))
    for i in range(12):
        frequency, note = [(90, 36), (700, 38), (5000, 42)][i % 3]
        t = np.arange(round(.1*SR))/SR
        carrier = (rng.normal(size=len(t)) if frequency == 5000 else np.sin(2*np.pi*frequency*t))
        if frequency == 5000:
            carrier = signal.sosfilt(signal.butter(3, 3000, btype='highpass', fs=SR, output='sos'), carrier)
        wave = .5*carrier*np.exp(-t/.015)
        wave[:12] *= np.linspace(0, 1, 12)
        pos = round((.1+i*.3)*SR)
        x[pos:pos+len(wave), 0] += wave
        labels.append(note)
    root = T._make(tmp_path/'song', {'drums': x})
    out = M.run(args(M, root, '--target', 'trk_drums', '--kind', 'drums', '--map', '20:200:36,200:2500:38,2500:11000:42',
                     '--quantize', '1/16', '--bpm', '120'))
    assert len(out['notes']) == len(labels)
    assert np.mean([r['note'] == note for r, note in zip(out['notes'], labels)]) >= .9
    assert all(r['tick'] % 120 == 0 for r in out['notes'])



def test_midi_mono_16_notes_bends_and_smf(tmp_path):
    wanted = [60, 62, 64, 65, 67, 69, 71, 72]*2
    x = np.zeros((round((.12+16*.32)*SR), 1))
    for i, note in enumerate(wanted):
        t = np.arange(round(.24*SR))/SR
        hz = 440*2**((note-69)/12)
        wave = .4*np.sin(2*np.pi*hz*t)
        wave[:120] *= np.linspace(0, 1, 120)
        wave[-120:] *= np.linspace(1, 0, 120)
        pos = round((.1+i*.32)*SR)
        x[pos:pos+len(t), 0] = wave
    root = T._make(tmp_path/'song', {'vocals': x})
    out = M.run(args(M, root, '--target', 'trk_vocals', '--kind', 'mono', '--bend', '--out', str(tmp_path/'melody.mid')))
    rows = out['notes']
    assert [r['note'] for r in rows] == wanted
    error = [abs(r['time_s']-(.1+i*.32)) for i, r in enumerate(rows)]
    length_error = [abs(r['duration_s']-.24) for r in rows]
    assert max(error) <= .020 and max(length_error) <= .040
    notes, bends = read_smf((tmp_path/'melody.mid').read_bytes())
    assert notes == sorted((r['tick'], r['end_tick'], r['note'], r['velocity']) for r in rows)
    assert all((p['tick'], p['value']) in bends for r in rows for p in r['bends'])
    print('midi_mono_max_head_length_ms', max(error)*1000, max(length_error)*1000)



@pytest.mark.parametrize('flags', [['--velocity-range', '127', '1'], ['--threshold-db', 'nan'],
    ['--map', '20:200:128'], ['--bpm', '401'], ['--a4', '0']])
def test_midi_bad_input_readonly(tmp_path, flags):
    x, _ = train(2)
    root = T._make(tmp_path/'song', {'drums': x})
    before = C._snapshot(root)
    with pytest.raises(InputError):
        C.execute(M.COMMANDS[0], args(M, root, '--target', 'trk_drums', '--kind', 'drums', *flags), root)
    assert C._snapshot(root) == before



def test_midi_protected_outputs_and_section_ids(tmp_path):
    x, _ = train(4, kind='snare', interval=.3)
    root = T._make(tmp_path/'song', {'drums': x})
    flags = ['--target', 'trk_drums', '--kind', 'drums']
    before = C._snapshot(root)
    for path in (root/'project.json', root/'journal.jsonl', root/'directions'/'notes.mid'):
        with pytest.raises(InputError):
            C.execute(M.COMMANDS[0], args(M, root, *flags, '--out', str(path)), root)
    assert C._snapshot(root) == before
    full = M.run(args(M, root, *flags))
    part = M.run(args(M, root, *flags, '--section', '.4,1.2'))
    assert [r['id'] for r in part['notes']] == [r['id'] for r in full['notes'] if .4 <= r['time_s'] < 1.2]
    assert C._snapshot(root) == before

