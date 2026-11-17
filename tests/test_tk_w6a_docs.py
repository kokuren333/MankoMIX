"""Keep the public implementation supplement aligned with runtime declarations."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

from mankomix.director import commands, direction, xops
from mankomix.director._observations_w4b import PRIMITIVES
from mankomix.dsp import processors as P

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools/tool_status_table.py"


def section(path, marker):
    text = (ROOT / path).read_text(encoding="utf-8")
    return text.split(f"<!-- {marker}:begin -->", 1)[1].split(f"<!-- {marker}:end -->", 1)[0]


def rows(text):
    # Inline alternatives in CLI syntax escape pipes; those are not cell borders.
    return [re.split(r"(?<!\\)\|", line)[1:-1]
            for line in text.splitlines() if line.startswith("| `")]


def test_status_regeneration_is_byte_identical():
    readme = ROOT / "docs/tool_impl/README.md"
    before = readme.read_bytes()
    for extra in (["--check"], []):
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(GENERATOR), *extra],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert readme.read_bytes() == before, "status table needs regeneration"


def test_all_143_tools_have_exact_describe_flags():
    spec = importlib.util.spec_from_file_location("w6a_status", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inventory = module.inventory()
    text = section("docs/tool_impl/README.md", "tool-status")
    actual = {cells[0].strip(): cells for line in text.splitlines() if line.startswith("| T")
              for cells in [line.split("|")[1:-1]]}
    assert len(actual) == 143
    assert set(actual) == set(inventory)
    found = {}
    for tid, (_, surfaces) in inventory.items():
        cell = actual[tid][3]
        expected = {value: str(P.describe(value)["implemented"]).lower()
                    for item in surfaces for kind, value in [item.split(":", 1)] if kind == "type"}
        flags = dict(re.findall(r"`([a-z0-9_]+)`: `(true|false)`", cell))
        assert flags == expected, tid
        for ptype, flag in flags.items():
            found[ptype] = flag
            if flag == "false":
                assert actual[tid][4].strip() != "—", tid
    # All newly registered types must be assigned to at least one catalog item.
    from mankomix.dspx.registry import specs
    assert {row["type"] for row in specs()} <= set(found)
    assert "重複" in actual["T12-01"][4]
    assert "衣擦れ" in actual["T10-15"][4]
    for tid in ("T08-02", "T10-10", "T12-08"):
        assert "OQ-3" in actual[tid][4]


def test_documented_ops_match_registration_and_required_fields():
    declared = {"duck_curve": direction.OPS["duck_curve"]}
    declared.update({name: (s.stage, s.required) for name, s in xops.specs(direction.OPS).items()})
    table = rows(section("docs/DIRECTION_FORMAT.md", "tool-ops"))
    registered = {}
    for cells in table:
        name = re.search(r"`([^`]+)`", cells[0])[1]
        if cells[3].strip() == "登録済み":
            assert name not in registered
            registered[name] = (cells[1].strip(), tuple(cells[2].strip().split(", ")))
        else:
            assert cells[3].strip() == "未登録"
            assert name not in declared, f"{name}: update pending documentation"
    assert registered == declared


def test_documented_commands_match_registry_and_cli_flags():
    declared = {"direction " + " ".join(c["path"]): c for c in commands.declarations()}
    table = rows(section("docs/DIRECTION_FORMAT.md", "tool-commands"))
    registered = {}
    for cells in table:
        name = re.search(r"`([^`]+)`", cells[0])[1]
        if cells[3].strip() == "登録済み":
            assert name not in registered
            registered[name] = cells[2].strip()
        else:
            assert cells[3].strip() == "未登録"
            assert name not in declared
    assert registered == {name: str(c["writes"]) for name, c in declared.items()}
    cli_rows = rows(section("cli/README.md", "tool-cli"))
    seen = set()
    for cells in cli_rows:
        usage = re.search(r"`([^`]+)`", cells[0])[1]
        name = next((name for name in declared if usage == name or usage.startswith(name + " ")), None)
        assert name is not None, usage
        assert name not in seen
        seen.add(name)
        parser = argparse.ArgumentParser(add_help=False)
        declared[name]["add_args"](parser)
        valid = {flag for action in parser._actions for flag in action.option_strings}
        assert set(re.findall(r"--[a-z][a-z0-9-]*", usage)) <= valid, usage
    assert seen == set(declared)


def test_documented_primitives_and_spatial_commands_match_registry():
    names = {re.search(r"`([^`]+)`", cells[0])[1]
             for cells in rows(section("docs/DIRECTION_FORMAT.md", "tool-primitives"))}
    assert names == set(PRIMITIVES)
    from mankomix.cli.main import build_parser
    def children(parser):
        return next(a.choices for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    spatial = children(children(children(build_parser())["spatial"])["ambi"])
    table = rows(section("cli/README.md", "tool-spatial"))
    names = set()
    for cells in table:
        usage = re.search(r"`([^`]+)`", cells[0])[1]
        name = usage.split()[2]
        names.add(name)
        valid = {flag for a in spatial[name]._actions for flag in a.option_strings}
        assert set(re.findall(r"--[a-z][a-z0-9-]*", usage)) <= valid
    assert names == set(spatial)
