"""BB-00 registration and contracts, using only temporary test processors."""
import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from mankomix.dsp import engine as E, processors as P, reference
from mankomix.dsp.errors import ChainError, NumericError, ParamError
from mankomix.dspx import assets, registry
from mankomix.dspx import params as XP
from mankomix.director import calibrate, direction as D


def _spec(kind, params=(), **extra):
    spec = P.describe("gain")
    spec.update(type=kind, params=list(params), **extra)
    return spec


def _curve(**extra):
    return {"id": "points", "type": "curve", "x_unit": "s", "x_min": 0, "x_max": 10,
            "y_min": -60, "y_max": 12, "max_points": 3, "default": [],
            "description": "Test curve.", **extra}


def _asset(**extra):
    return {"id": "asset_id", "type": "asset", "registry": "w0a_assets", "default": "known",
            "description": "Test asset.", **extra}


@pytest.fixture
def register(monkeypatch):
    def add(spec, fn=None):
        monkeypatch.setitem(P.PROCESSORS, spec["type"], spec)
        if fn is not None:
            monkeypatch.setitem(reference.IMPLEMENTATIONS, spec["type"], fn)
        return spec["type"]
    return add


def _render(chain, audio=None):
    if audio is None:
        audio = np.tile([.375, .125], (32, 1))
    return E.render_chain(audio, 48000, chain, stage="track")


def _bytes(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@pytest.mark.parametrize("helper,args", [
    ("_f", ("x", "dB", -10, 10, 0, "x")),
    ("_i", ("x", "n", 0, 10, 1, "x")),
    ("_e", ("x", ["a", "b"], "a", "x")),
    ("_b", ("x", False, "x")),
    ("_a", ("x", "Hz", 0, 10, 5, [], "x")),
])
def test_parameter_helpers_match_existing(helper, args):
    assert getattr(XP, helper)(*args) == getattr(P, helper)(*args)


def test_curve_defaults_schema_and_boundaries(register):
    kind = register(_spec("w0a_curve", [_curve()]))
    assert P.validate_params(kind, {}) == {"points": []}
    value = [[0, -60], [5, 0], [10, 12]]
    result = P.validate_params(kind, {"points": value})
    assert result == {"points": value} and result["points"] is not value
    assert all(isinstance(n, float) for pair in result["points"] for n in pair)
    schema = P._param_schema(_curve())
    Draft202012Validator(schema).validate(value)
    assert schema["items"]["minItems"] == schema["items"]["maxItems"] == 2
    default = [[1, -6]]
    P.PROCESSORS[kind]["params"][0]["default"] = default
    out = P.validate_params(kind, {})
    out["points"][0][1] = 0
    assert default == [[1, -6]]


@pytest.mark.parametrize("value", [None, "bad", [1, 2], [[0]], [[0, 1, 2]],
    [[0, 0], [0, 1]], [[2, 0], [1, 0]], [[-1, 0]], [[11, 0]], [[0, -61]],
    [[0, 13]], [[True, 0]], [[0, "x"]], [[float("nan"), 0]], [[0, float("inf")]],
    [[0, 0], [1, 0], [2, 0], [3, 0]], [[], []]])
def test_curve_rejects_invalid_values(register, value):
    kind = register(_spec("w0a_curve", [_curve()]))
    with pytest.raises(ParamError):
        P.validate_params(kind, {"points": value})


@pytest.mark.parametrize("limit", [65537, -1, True, 1.5])
def test_curve_rejects_invalid_point_limit(register, limit):
    kind = register(_spec("w0a_curve", [_curve(max_points=limit)]))
    with pytest.raises(ParamError):
        P.validate_params(kind, {})


def test_curve_maximum_point_count(register):
    kind = register(_spec("w0a_curve", [_curve(max_points=65536, x_max=65535)]))
    assert len(P.validate_params(kind, {"points": [[i, 0] for i in range(65536)]})["points"]) == 65536


def test_asset_registration_resolution_and_schema(register, monkeypatch):
    monkeypatch.setattr(assets, "RESOLVERS", {})
    assets.register("w0a_assets", {"known": {"sha256": "abc"}}.__getitem__)
    kind = register(_spec("w0a_asset", [_asset()]))
    assert assets.resolve("w0a_assets", "known") == {"sha256": "abc"}
    assert P.validate_params(kind, {}) == {"asset_id": "known"}
    assert P._param_schema(_asset())["type"] == "string"
    with pytest.raises(ValueError):
        assets.register("w0a_assets", lambda _: {})
    for value in ("missing", 1, None, ["known"]):
        with pytest.raises(ParamError):
            P.validate_params(kind, {"asset_id": value})
    monkeypatch.setitem(assets.RESOLVERS, "w0a_assets", lambda _: None)
    with pytest.raises(ParamError):
        P.validate_params(kind, {})
    monkeypatch.delitem(assets.RESOLVERS, "w0a_assets")
    with pytest.raises(ParamError, match="unknown asset registry"):
        P.validate_params(kind, {})


def test_channel_omission_and_explicit_stereo_use_original_path(monkeypatch):
    rng = np.random.default_rng(71)
    x = rng.normal(0, .1, (1024, 2))
    chain = [{"type": "gain", "params": {"gain_db": -6}},
             {"type": "compressor", "params": {"threshold_db": -20}}]
    assert _bytes(E.validate_chain(chain, "track")) == _bytes(E._validate_chain_base(chain, "track"))
    before = _render(chain, x)
    with monkeypatch.context() as patch:
        patch.setattr(E, "validate_chain", E._validate_chain_base)
        patch.setattr(P, "validate_params", P._validate_params_base)
        original = _render(chain, x)
    assert before.audio.tobytes() == original.audio.tobytes()
    assert _bytes(before.to_dict()) == _bytes(original.to_dict())
    explicit = _render([{**s, "channel": "stereo"} for s in chain], x)
    assert explicit.audio.tobytes() == before.audio.tobytes()
    assert all(s["channel"] == "stereo" for s in explicit.steps)
    assert all("channel" not in s for s in before.steps)


@pytest.mark.parametrize("channel", ["mid", "side", "left", "right"])
def test_channel_targets_only_selected_mono_component(channel, register):
    inputs = []
    def gain(x, sr, p, *, seed):
        inputs.append(x.copy())
        assert x.shape == (32, 1)
        return reference.basic.gain(x, sr, p, seed=seed)
    kind = register(_spec("w0a_gain", [XP._f("gain_db", "dB", -60, 24, 0, "Gain.")]), gain)
    x = np.tile([.375, .125], (32, 1))
    result = _render([{"type": kind, "channel": channel, "params": {"gain_db": -6}}], x)
    y = result.audio
    factor = 10 ** (-6 / 20)
    mid, side = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2
    if channel in ("mid", "side"):
        m, s = (y[:, 0] + y[:, 1]) / 2, (y[:, 0] - y[:, 1]) / 2
        untouched, expected = (s, side) if channel == "mid" else (m, mid)
        assert untouched.tobytes() == expected.tobytes()
        np.testing.assert_allclose(m if channel == "mid" else s,
                                   (mid if channel == "mid" else side) * factor, atol=1e-16, rtol=0)
    else:
        index = 0 if channel == "left" else 1
        assert y[:, 1-index].tobytes() == x[:, 1-index].tobytes()
        np.testing.assert_array_equal(y[:, index], x[:, index] * factor)
    assert result.steps[0]["channel"] == channel
    assert len(inputs) == 1


@pytest.mark.parametrize("channel", ["mid", "side", "left", "right"])
@pytest.mark.parametrize("bypass", [False, True])
def test_channel_rejects_mono_input(channel, bypass):
    with pytest.raises(ParamError, match="stereo input"):
        _render([{"type": "gain", "channel": channel, "bypass": bypass}], np.zeros(16))


@pytest.mark.parametrize("kind,stage", [("pan", "track"), ("stereo", "track"), ("limiter", "master"),
    ("loudness_gain", "export"), ("resample", "export"), ("dither", "export")])
def test_channel_rejected_type_list(kind, stage):
    with pytest.raises(ParamError, match="channel targeting"):
        E.validate_chain([{"type": kind, "channel": "mid"}], stage)


def test_channel_custom_restrictions_invalid_values_and_bypass(register):
    for definition, stage in ((_spec("w0a_nochannel", channel_ok=False), "track"),
                              (_spec("w0a_export", stages=["export"]), "export")):
        kind = register(definition)
        with pytest.raises(ParamError):
            E.validate_chain([{"type": kind, "channel": "left"}], stage)
    for channel in ("bogus", None, [], 1):
        with pytest.raises(ParamError):
            E.validate_chain([{"type": "gain", "channel": channel}], "track")
    result = _render([{"type": "gain", "channel": "left", "bypass": True}])
    assert result.steps[0]["channel"] == "left" and result.steps[0]["bypass"]


def test_channel_validates_fallback_and_output_shape(register):
    spec = _spec("w0a_unavailable", backends=["missing"])
    kind = register(spec)
    with pytest.raises(ParamError):
        E.validate_chain([{"type": kind, "channel": "left", "fallback": {"type": "pan", "params": {}}}], "track")
    for fn in (lambda x, sr, p, **kw: (np.repeat(x, 2, axis=1), sr, {}),
               lambda x, sr, p, **kw: (x, sr * 2, {})):
        kind = register(_spec("w0a_bad_output"), fn)
        with pytest.raises(NumericError):
            _render([{"type": kind, "channel": "side"}])


@pytest.fixture
def composite(register, monkeypatch):
    kind = register(_spec("w0a_composite", [XP._f("gain_db", "dB", -60, 24, -6, "Gain.")], composite=True))
    table = {kind: lambda p: [{"type": "gain", "params": p}, {"type": "gain", "params": {"gain_db": -3}}]}
    monkeypatch.setattr(registry, "composites", lambda: table)
    return kind, table


def test_composite_expansion_records_ids_source_and_channel(composite):
    kind, _ = composite
    source = {"id": "source", "type": kind, "params": {"gain_db": -6}, "channel": "left"}
    original = copy.deepcopy(source)
    steps = E.validate_chain([source], "track")
    assert [s["id"] for s in steps] == ["source.1", "source.2"]
    assert all(s["type"] == "gain" and s["composite_of"] == source for s in steps)
    result = _render([source])
    direct = _render([{k: v for k, v in s.items() if k != "composite_of"} for s in steps])
    assert result.audio.tobytes() == direct.audio.tobytes()
    assert all(s["composite_of"] == source and s["channel"] == "left" for s in result.steps)
    assert source == original
    bypass = _render([{**source, "bypass": True}])
    assert all(s["bypass"] and "composite_of" in s for s in bypass.steps)


@pytest.mark.parametrize("children", [None, [], [None], [{"type": "missing"}],
    [{"type": "gain", "params": {"gain_db": 100}}], [{"type": "gain", "params": {"unknown": 1}}],
    [{"type": "w0a_composite"}], [{"type": "gain", "channel": "bad"}],
    [{"type": "dither"}, {"type": "gain"}]])
def test_composite_rejects_invalid_expansions(composite, children):
    kind, table = composite
    table[kind] = lambda p: children
    with pytest.raises((ParamError, ChainError)):
        E.validate_chain([{"type": kind}], "track")


def test_composite_checks_source_ranges_and_final_chain_constraints(composite):
    kind, table = composite
    for raw in ({"type": kind, "params": {"gain_db": -61}}, {"type": kind, "unknown": True}):
        with pytest.raises((ParamError, ChainError)):
            E.validate_chain([raw], "track")
    with pytest.raises(ChainError, match="duplicate"):
        E.validate_chain([{"id": "x", "type": kind}, {"id": "x.1", "type": "gain"}], "track")
    table[kind] = lambda p: [{"type": "limiter"}, {"type": "gain"}]
    with pytest.raises(ChainError, match="final mastering"):
        E.validate_chain([{"type": kind}], "master")


def test_composite_can_expand_to_an_extension_processor(composite, register):
    kind, table = composite
    child = register(_spec("w0a_child", [XP._f("gain_db", "dB", -60, 24, 0, "Gain.")]),
                     reference.basic.gain)
    table[kind] = lambda p: [{"type": child, "params": p}]
    result = _render([{"type": kind}])
    assert result.steps[0]["type"] == child
    assert result.steps[0]["id"] == "00_w0a_composite.1"
    assert result.audio.tobytes() == _render([{"type": "gain", "params": {"gain_db": -6}}]).audio.tobytes()


def test_describe_and_existing_schema_unchanged_when_extensions_removed(register, monkeypatch):
    original = {s["type"]: copy.deepcopy(s) for s in P._PROCESSORS}
    register(_spec("w0a_extra", channel_ok=False))
    current = {t: _bytes(P.describe(t)) for t in original}
    stripped = {t: s for t, s in P.PROCESSORS.items() if t in original}
    with monkeypatch.context() as patch:
        patch.setattr(P, "PROCESSORS", stripped)
        assert current == {t: _bytes(P.describe(t)) for t in original}
    assert current == {t: _bytes(s) for t, s in original.items()}
    base = P._graph_schema_base()
    schema = P.graph_schema()
    assert schema["x-schema-version"] == P.SCHEMA_VERSION == 1
    for variant in schema["items"]["oneOf"]:
        assert "channel" in variant["properties"]
        variant["properties"].pop("channel")
    assert _bytes(schema) == _bytes(base)


def test_director_array_ids_are_per_type_and_curve_is_not_range(register):
    kind = register(_spec("w0a_array", [XP._a("threshold_db", "dB", -60, 0, 5, [], "Thresholds."), _curve()]))
    move = {"id": "m", "op": "chain_add", "processor": "compressor"}
    assert D.resolve_params(move, {"threshold_db": [-20, -10]}) == ({"threshold_db": -15}, [])
    assert D._ends({"threshold_db": [-20, -10]}, "compressor") == [{"threshold_db": -20}, {"threshold_db": -10}]
    for value in ([-20, -10], []):
        params = {"threshold_db": value, "points": [[0, 0], [1, 1]]}
        move = {"id": "m", "op": "chain_add", "processor": kind, "params": params}
        assert D.resolve_params(move, params)[0] == params
        assert D._ends(params, kind) == [params]
        assert calibrate.knobs({"block": {"moves": [move]}}) == []
    bad_curve = {"points": [0, 1]}
    assert D.resolve_params(move, bad_curve)[0] == bad_curve
    errors = []
    assert D._check_proc_params(kind, bad_curve, "track", "test", errors) is None
    assert errors[0]["code"] == "param_range"
    assert set(("compressor", "dynamic_eq", "deesser", "aw.pressure4")) | registry.time_varying_types() == D.TIME_VARYING


def test_existing_direction_validation_proposal_and_calibration_bytes(tmp_path, register, monkeypatch):
    from tests import test_director as TD, test_direction_update as TU
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    root = TU._project(tmp_path / "song", low_amp=.1)
    proj = D._Project(root)
    block = TD._block()
    block["moves"][0].update(processor="compressor", params={"threshold_db": [-20, -10]})
    doc = D.parse_document(TD._doc(tmp_path, block))
    legacy_ids = frozenset(p["id"] for spec in P._PROCESSORS for p in spec["params"] if p["type"] == "float_array")
    with monkeypatch.context() as patch:
        patch.setattr(D, "_array_param_ids", lambda _: legacy_ids)
        before = _bytes((D.validate(doc, root), D.build_proposal(proj, doc), calibrate.knobs(doc, proj)))
    register(_spec("w0a_array", [XP._a("threshold_db", "dB", -60, 0, 5, [], "Thresholds.")]))
    after = _bytes((D.validate(doc, root), D.build_proposal(proj, doc), calibrate.knobs(doc, proj)))
    assert before == after
    assert calibrate.knobs(doc, proj)[0]["start"] == -15


def test_director_bus_and_chain_param_use_the_child_type(register):
    kind = register(_spec("w0a_array", [XP._a("threshold_db", "dB", -60, 0, 5, [], "Thresholds."), _curve()]))
    array = {"threshold_db": [-20, -10], "points": [[0, 0], [1, 1]]}
    scalar = {"threshold_db": [-20, -10]}
    move = {"id": "bus", "op": "bus_add", "params": {"chain": [
        {"type": kind, "params": array}, {"type": "compressor", "params": scalar}]}}
    assert D.resolve_params(move, array)[0] == array
    assert D.resolve_params(move, scalar)[0] == {"threshold_db": -15}
    assert [k["id"] for k in calibrate.knobs({"block": {"moves": [move]}})] == ["bus.chain1.threshold_db"]
    change = {"id": "change", "op": "chain_param", "target": "trk_a", "replaces": "item", "params": array}
    proj = SimpleNamespace(tracks=lambda: {"trk_a": {"chain": [{"id": "item", "type": kind}]}},
                           buses=lambda: {}, floor_items=lambda: {"item": ("track", "trk_a")})
    assert D._move_processor(change, proj) == kind
    assert D.resolve_params(change, array, ptype=D._move_processor(change, proj))[0] == array
    assert calibrate.knobs({"block": {"moves": [change]}}, proj) == []


def _mock_modules(tmp_path, monkeypatch, modules):
    directory = tmp_path / "procs"
    directory.mkdir()
    for name in reversed(list(modules)):
        (directory / f"{name}.py").touch()
    monkeypatch.setattr(registry, "__file__", str(tmp_path / "registry.py"))
    monkeypatch.setattr(registry, "_TABLES", None)
    calls = []
    def load(name):
        calls.append(name.rsplit(".", 1)[1])
        return modules[calls[-1]]
    monkeypatch.setattr(registry.importlib, "import_module", load)
    return calls


def test_registry_filename_order_metadata_and_copy_isolation(tmp_path, monkeypatch):
    fn = lambda *a, **kw: None
    modules = {"a": SimpleNamespace(SPECS=[_spec("w0a_a")], IMPLS={"w0a_a": fn}, TIME_VARYING={"w0a_a"}),
               "z": SimpleNamespace(SPECS=[_spec("w0a_z", composite=True)], IMPLS={}, COMPOSITES={"w0a_z": fn})}
    calls = _mock_modules(tmp_path, monkeypatch, modules)
    result = registry.specs()
    assert calls == ["a", "z"] and [s["type"] for s in result] == ["w0a_a", "w0a_z"]
    assert registry.implementations() == {"w0a_a": fn}
    assert registry.time_varying_types() == frozenset({"w0a_a"})
    assert registry.composites() == {"w0a_z": fn}
    result[0]["params"].append({})
    assert registry.specs()[0]["params"] == []


@pytest.mark.parametrize("case", ["existing", "duplicate", "duplicate_impl", "missing_spec", "missing_expander"])
def test_registry_rejects_collisions_and_invalid_metadata(tmp_path, monkeypatch, case):
    fn = lambda *a, **kw: None
    a = SimpleNamespace(SPECS=[_spec("w0a_a")], IMPLS={"w0a_a": fn})
    b = SimpleNamespace(SPECS=[_spec("w0a_b")], IMPLS={"w0a_b": fn})
    if case == "existing":
        a.SPECS = [_spec("gain")]
        a.IMPLS = {"gain": fn}
    elif case == "duplicate":
        b.SPECS = a.SPECS
    elif case == "duplicate_impl":
        b.IMPLS = a.IMPLS
    elif case == "missing_spec":
        b.IMPLS = {"unknown": fn}
    else:
        a.SPECS[0]["composite"] = True
    _mock_modules(tmp_path, monkeypatch, {"a": a, "b": b})
    with pytest.raises(ImportError):
        registry.specs()
