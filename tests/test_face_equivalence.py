"""Face equivalence (SPEC 16.1, 10.1): the CLI and the MCP server wrap the same
core API, so the same operation sequence must produce the same project.

The sequence runs once through the CLI (in-process ``cli.main.main``) and
once through MCP tools (the JSON-RPC handler of ``mcp.server.Server``). The
resulting project.json files are compared after normalising the randomly
generated project id; journals must contain the same operations, differing
only in the recorded actor (CLI: human, MCP: agent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mankomix.cli import main as cli_main
from mankomix.mcp.server import Server

from tests.test_mcp import write_stem_folder

TITLE = "Equivalence Song"
GENRE = "jpop"


def _project_json(root: Path) -> dict:
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert data["id"].startswith("prj_")
    data["id"] = "prj_normalised"
    return data


def _journal(root: Path) -> list[dict]:
    lines = (root / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines if x.strip()]


def _analysis_files(root: Path) -> dict[str, dict]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "analysis").glob("*.json"))}


class Cli:
    def __init__(self, capsys, project: Path):
        self.capsys = capsys
        self.project = project

    def __call__(self, *argv: str, expect: int = 0) -> dict:
        code = cli_main.main([*argv[:1], "--project", str(self.project), *argv[1:]])
        out = self.capsys.readouterr().out
        assert code == expect, out
        return json.loads(out)


class Mcp:
    def __init__(self, root: Path):
        self.server = Server(root)
        self.n = 0
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        assert r["result"]["serverInfo"]["name"] == "mankomix"

    def rpc(self, method: str, params: dict) -> dict:
        self.n += 1
        line = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        return json.loads(self.server.handle_line(line))

    def __call__(self, name: str, expect_error: bool = False, **arguments) -> dict:
        res = self.rpc("tools/call", {"name": name, "arguments": arguments})["result"]
        assert res["isError"] is expect_error, res["structuredContent"]
        return res["structuredContent"]


@pytest.fixture
def faces(tmp_path, capsys):
    write_stem_folder(tmp_path / "export")
    cli_proj, mcp_proj = tmp_path / "via_cli", tmp_path / "via_mcp"
    return Cli(capsys, cli_proj), Mcp(tmp_path), cli_proj, mcp_proj, tmp_path


def test_same_operations_same_project(faces):
    cli, mcp, cli_proj, mcp_proj, root = faces
    patch_ops = [{"op": "replace", "path": "/tracks/1/gain_db", "value": -2.5},
                 {"op": "replace", "path": "/objective/intensity", "value": 0.7}]

    # --- via CLI ---------------------------------------------------------------
    cli("init", str(cli_proj), "--title", TITLE, "--genre", GENRE)
    cli("import", str(root / "export"))
    cli("set", "/tracks/0/gain_db", "-1.5", "--reason", "balance")
    cli("set", "/title", json.dumps("Renamed"), "--reason", "rename")
    cli("patch", json.dumps(patch_ops), "--reason", "tweak")
    cli("analyze")
    cli("undo")
    cli("checkout", "4")
    cli("set", "/tracks/0/gain_db", "\"not a number\"", expect=2)
    cli_valid = cli("validate")
    cli_hist = cli("history", "--limit", "50")

    # --- via MCP ---------------------------------------------------------------
    mcp("project_init", project="via_mcp", title=TITLE, genre=GENRE)
    mcp("import_files", project="via_mcp", sources=["export"])
    mcp("project_set", project="via_mcp", pointer="/tracks/0/gain_db", value=-1.5, reason="balance")
    mcp("project_set", project="via_mcp", pointer="/title", value="Renamed", reason="rename")
    mcp("project_patch", project="via_mcp", ops=patch_ops, reason="tweak")
    mcp("analyze_run", project="via_mcp")
    mcp("history_undo", project="via_mcp")
    mcp("history_checkout", project="via_mcp", seq=4)
    err = mcp("project_set", expect_error=True, project="via_mcp", pointer="/tracks/0/gain_db",
              value="not a number")
    mcp_valid = mcp("project_validate", project="via_mcp", detail="full")
    mcp_hist = mcp("history_list", project="via_mcp", limit=50)

    # --- same project.json ------------------------------------------------------
    a, b = _project_json(cli_proj), _project_json(mcp_proj)
    assert a == b
    assert a["title"] == "Renamed" and a["tracks"][0]["gain_db"] == -1.5

    # same derived files
    assert sorted(p.name for p in (cli_proj / "assets").iterdir()) == \
        sorted(p.name for p in (mcp_proj / "assets").iterdir())
    assert _analysis_files(cli_proj) == _analysis_files(mcp_proj)

    # same journal operations; only the actor differs
    ja, jb = _journal(cli_proj), _journal(mcp_proj)
    strip = ("ts", "actor", "before_hash", "after_hash", "before")
    assert [{k: v for k, v in e.items() if k not in strip} for e in ja] == \
           [{k: v for k, v in e.items() if k not in strip} for e in jb]
    assert [e["op"] for e in ja] == ["create", "import", "set", "set", "patch", "analyze", "undo", "checkout"]
    assert {e["actor"] for e in ja[1:]} == {"human"}
    assert {e["actor"] for e in jb[1:]} == {"agent"}

    # same answers and the same error for the same requests
    assert cli_valid == mcp_valid
    assert [(e["seq"], e["op"], e.get("reason")) for e in cli_hist["entries"]] == \
           [(e["seq"], e["op"], e.get("reason")) for e in mcp_hist["entries"]]
    cli_err = cli("set", "/tracks/0/gain_db", "\"not a number\"", expect=2)
    assert cli_err["error"] == err["error"]


def test_same_read_results(faces):
    cli, mcp, cli_proj, mcp_proj, root = faces
    cli("init", str(cli_proj), "--title", TITLE)
    cli("import", str(root / "export"))
    mcp("project_init", project="via_mcp", title=TITLE)
    mcp("import_files", project="via_mcp", sources=["export"])

    def norm_status(s: dict) -> dict:
        s = dict(s, id=None, project=None)
        s["last_journal"] = [{k: v for k, v in e.items() if k not in ("ts", "actor", "after_hash")}
                             for e in s["last_journal"]]
        return s

    assert norm_status(cli("status")) == norm_status(mcp("project_open", project="via_mcp", detail="full"))
    assert cli("profile", "list") == mcp("profile_list", detail="full")
    assert cli("objective", "show", "comfort") == mcp("objective_get", id="comfort", detail="full")
    m_cli = cli("measure", str(root / "export" / "1 Drums.wav"))
    m_mcp = mcp("measure_audio", path="export/1 Drums.wav", detail="full")
    assert m_cli == m_mcp


@pytest.fixture(scope="module")
def direction_mcp(tmp_path_factory):
    mcp = Mcp(tmp_path_factory.mktemp("direction_faces"))
    listed = {tool["name"] for tool in mcp.rpc("tools/list", {})["result"]["tools"]}
    return mcp, listed


@pytest.mark.parametrize("command, tool", [
    ("direction stems observe", "direction_stems_observe"),
    ("direction stems relate", "direction_stems_relate"),
    ("direction stems purity", "direction_stems_purity"),
    ("direction listen pack", "direction_listen_pack"),
    ("direction listen record", "direction_listen_record"),
    ("direction stems stages", "direction_stems_stages"),
    ("direction stems placement", "direction_stems_placement"),
    ("direction stems phrases", "direction_stems_phrases"),
    ("direction wiring", "direction_wiring"),
    ("direction check", "direction_check"),
])
def test_direction_commands_remain_documented_cli_only(direction_mcp, command, tool):
    """New direction commands follow the three original previews' CLI-only policy."""
    from tests.test_mcp_e2e import CLI_TO_MCP, KNOWN_CLI_ONLY

    assert CLI_TO_MCP[command] == tool
    reason = KNOWN_CLI_ONLY[command]
    assert reason.strip() and "MCP" in reason
    mcp, listed = direction_mcp
    assert tool not in listed, reason
    assert mcp(tool, expect_error=True)["error"] == "unknown_tool"


@pytest.mark.parametrize("command, required, flag", [
    ("direction stems relate", [], "--axes"),
    ("direction check", ["direction.md", "--floor", "floor"], "--edit-list"),
    ("direction check", ["direction.md", "--floor", "floor"], "--contour"),
])
def test_direction_flags_belong_to_cli_only_commands(command, required, flag):
    """Optional direction flags retain their parent command's MCP registration."""
    from tests.test_mcp_e2e import CLI_TO_MCP, KNOWN_CLI_ONLY

    args = cli_main.build_parser().parse_args([*command.split(), *required, flag])
    assert getattr(args, flag.removeprefix("--").replace("-", "_")) is True
    assert command in KNOWN_CLI_ONLY
    assert CLI_TO_MCP[command].startswith("direction_")
    assert f"{command} {flag}" not in CLI_TO_MCP
