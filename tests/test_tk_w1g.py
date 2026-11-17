"""W1g: item-bound extension seeds and bandlimited random modulation."""
import copy
import hashlib
import json

import numpy as np
import pytest

from mankomix.dsp import engine as E, processors as P, reference
from mankomix.dspx import chain as X, registry
from mankomix.dspx.bb import curves as Q
from mankomix.dspx.procs import tremolo as TR


def test_item_seed_unsigned_sha256_and_legacy_identity():
    for project_seed in (0, 12, 2**64-1):
        for sid in ('a', 'a.1', '項目.2'):
            data = json.dumps({'project_seed': project_seed, 'item_id': sid},
                              sort_keys=True, separators=(',', ':'), ensure_ascii=False)
            expected = int.from_bytes(hashlib.sha256(data.encode('utf-8')).digest()[:8], 'big')
            assert X.item_seed(project_seed, sid) == expected
    assert any(X.item_seed(12, str(i)) >= 2**63 for i in range(10))
    for spec in P._PROCESSORS:
        fn = reference.IMPLEMENTATIONS.get(spec['type'], object())
        assert X.seed_implementation(fn, spec['type'], 'a') is fn


def test_seed_wrapper_preserves_call_and_result():
    calls = []
    result = (np.ones((2, 1)), 48000, {'test': True})
    x, params = np.zeros((2, 1)), {'seed': 37}

    def fn(audio, sr, p, *, seed):
        calls.append((audio, sr, p, seed))
        return result

    wrapped = X.seed_implementation(fn, 'tremolo', 'parent.2')
    assert wrapped(x, 48000, params, seed=91) is result
    assert calls[0][0] is x and calls[0][2] is params
    assert calls[0][1::2] == (48000, X.item_seed(91, 'parent.2'))


def test_engine_random_repeat_each_seed_component_and_channel():
    x = np.full((12000, 2), .1)
    p = dict(lfo_shape='random', rate_hz=7, seed=3)
    chain = [dict(id='a', type='tremolo', channel='left', params=dict(p)),
             dict(id='b', type='tremolo', channel='right', params=dict(p))]
    a = E.render_chain(x, 16000, chain, stage='track', seed=12)
    repeat = E.render_chain(x, 16000, chain, stage='track', seed=12)
    assert a.audio.tobytes() == repeat.audio.tobytes()
    assert a.steps == repeat.steps
    assert a.audio[:, 0].tobytes() != a.audio[:, 1].tobytes()
    for i, step in enumerate(chain):
        validated = P.validate_params('tremolo', p)
        expected = TR.tremolo(x[:, i:i+1], 16000, validated,
                             seed=X.item_seed(12, step['id']))[0]
        assert a.audio[:, i:i+1].tobytes() == expected.tobytes()
    for component in ('id', 'parameter', 'project'):
        changed = copy.deepcopy(chain)
        if component == 'id':
            changed[0]['id'] = 'different'
        elif component == 'parameter':
            changed[0]['params']['seed'] = 4
        b = E.render_chain(x, 16000, changed, stage='track', seed=13 if component == 'project' else 12)
        assert a.audio[:, 0].tobytes() != b.audio[:, 0].tobytes()
        if component != 'project':
            assert a.audio[:, 1].tobytes() == b.audio[:, 1].tobytes()


def test_expanded_composite_ids_bind_random_seed(monkeypatch):
    kind = 'w1g_composite'
    spec = P.describe('gain')
    spec.update(type=kind, composite=True, params=[])
    monkeypatch.setitem(P.PROCESSORS, kind, spec)
    children = [dict(type='tremolo', channel=channel, params={'lfo_shape': 'random', 'seed': 5})
                for channel in ('left', 'right')]
    table = registry.composites()
    table[kind] = lambda p: copy.deepcopy(children)
    monkeypatch.setattr(registry, 'composites', lambda: table)
    x = np.full((8000, 2), .1)
    expanded = [dict(child, id=f'parent.{i}') for i, child in enumerate(children, 1)]
    a = E.render_chain(x, 16000, [dict(type=kind, id='parent')], stage='track', seed=7)
    b = E.render_chain(x, 16000, expanded, stage='track', seed=7)
    assert a.audio.tobytes() == b.audio.tobytes()
    assert [s['id'] for s in a.steps] == ['parent.1', 'parent.2']
    assert a.audio[:, 0].tobytes() != a.audio[:, 1].tobytes()


@pytest.mark.parametrize('seed', [0, 12, 91])
def test_bandlimited_random_spectrum_and_clock(seed):
    opts = dict(rate_hz=1, seed=seed, item_id='a')
    a = Q.bandlimited_random(100000, 1000, **opts)
    assert np.isfinite(a).all() and np.max(np.abs(a)) <= 1
    spectrum = np.abs(np.fft.rfft((a-a.mean())*np.hanning(len(a))))**2
    frequencies = np.fft.rfftfreq(len(a), .001)
    leakage = 10*np.log10(spectrum[frequencies > 1].sum()/spectrum.sum())
    assert leakage <= -100
    print('bandlimited_random_above_rate_db', seed, leakage)
    for size in (64, 1024):
        blocks = [Q.bandlimited_random(min(size, 7000-i), 1000, start_sample=i, **opts)
                  for i in range(0, 7000, size)]
        assert np.concatenate(blocks).tobytes() == a[:7000].tobytes()
    assert Q.bandlimited_random(123, 1000, start_sample=1733, **opts).tobytes() == a[1733:1856].tobytes()
    inverse = Q.bandlimited_random(100000, 1000, phase=.5, **opts)
    np.testing.assert_allclose(inverse, -a, atol=1e-14, rtol=0)


def test_bandlimited_random_tempo_origin_and_empty():
    opts = dict(seed=14, parameter_seed=3, phase=.2, origin_s=.031)
    a = Q.bandlimited_random(3000, 1000, rate_hz=2, **opts)
    b = Q.bandlimited_random(3000, 1000, rate_hz=17, note='1/4', bpm=120, **opts)
    assert a.tobytes() == b.tobytes()
    assert Q.bandlimited_random(0, 1000, **opts).shape == (0,)
    assert Q.bandlimited_random(567, 1000, start_sample=123, **opts).tobytes() == Q.bandlimited_random(690, 1000, **opts)[123:].tobytes()
