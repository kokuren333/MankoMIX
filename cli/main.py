"""`mankomix` / `mmx` command line (SPEC 10.1, 10.2).

A thin face over ``mankomix.core.api``: every command maps 1:1 to one API
function, prints its JSON result to stdout and exits with the shared exit
codes (0 ok, 1 verify failed, 2 input error, 3 environment error).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from mankomix import ENGINE_VERSION
from mankomix.core import api
from mankomix.core.errors import EXIT_ENV_ERROR, EXIT_INPUT_ERROR, EXIT_OK, InputError, MankoError

from .format import render_text

ACTORS = ("human", "agent", "planner")

# Later-milestone groups (SPEC 10.2 / 17). They are registered so that the
# command surface is stable, but exit with EXIT_INPUT_ERROR for now.
STUB_GROUPS = {
    "stem": ("M4", "remix operations: list/add/replace/remove/move/mute/role/export"),
    "separate": ("M6", "stem separation"),
    "clean": ("M5", "cleanup plan/apply/delta"),
    "mix": ("M4", "mix plan/apply"),
    "run": ("M4", "one-shot pipeline with the planner"),
    "model": ("M6", "model registry"),
    "serve": ("M8", "local GUI server"),
}
OBJECTIVE_STUBS: dict[str, str] = {}


class CliParser(argparse.ArgumentParser):
    """Argument errors become InputError so they are reported as JSON with exit code 2."""

    def error(self, message: str):  # type: ignore[override]
        raise InputError(message, details={"usage": self.format_usage().strip()})


class NotImplementedYet(InputError):
    code = "not_implemented"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _project(args) -> str:
    if args.project:
        return args.project
    if Path("project.json").is_file():
        return "."
    raise InputError("no project: pass --project PATH or run inside a project folder")


def _read_arg_or_file(text: str) -> str:
    """Accept inline JSON, '@file' or '-' (stdin)."""
    if text == "-":
        return sys.stdin.read()
    if text.startswith("@"):
        p = Path(text[1:])
        if not p.is_file():
            raise InputError(f"file not found: {p.name}")
        return p.read_text(encoding="utf-8")
    return text


def _stub(group: str, milestone: str, sub: str | None = None) -> Callable[[Any], dict]:
    def run(args) -> dict:
        name = f"{group} {sub}" if sub else group
        raise NotImplementedYet(f"not implemented yet (milestone {milestone})",
                                details={"command": name, "milestone": milestone})
    return run


# ---------------------------------------------------------------------------
# command handlers (1:1 with core.api)
# ---------------------------------------------------------------------------

def cmd_doctor(a):
    return api.doctor(strict_lgpl=a.strict_lgpl)


def cmd_init(a):
    path = a.path or a.project or "."
    title = a.title or Path(os.path.abspath(path)).name.removesuffix(".mmx") or "Untitled"
    return api.init_project(path, title=title, genre=a.genre, project_id=a.project_id, actor=a.actor)


def cmd_import(a):
    prov = None
    if a.provenance:
        try:
            prov = json.loads(_read_arg_or_file(a.provenance))
        except ValueError:
            prov = None
        if not isinstance(prov, dict):
            raise InputError("--provenance must be a JSON object, '@file' or '-'")
    return api.import_files(_project(a), a.sources, mode=a.mode, provenance=prov, actor=a.actor)


def cmd_status(a):
    return api.status(_project(a))


def cmd_validate(a):
    return api.validate_project(_project(a))


def cmd_analyze(a):
    return api.analyze(_project(a), force=a.force, actor=a.actor)


def cmd_measure(a):
    return api.measure_audio(a.file)


def cmd_compare(a):
    return api.compare_audio(a.file_a, a.file_b)


def cmd_set(a):
    return api.set_value(_project(a), a.pointer, a.value, a.actor, reason=a.reason)


def cmd_patch(a):
    return api.patch(_project(a), _read_arg_or_file(a.ops), a.actor, reason=a.reason)


def cmd_history(a):
    return api.history(_project(a), limit=a.limit, detail=a.detail)


def cmd_undo(a):
    return api.undo(_project(a), a.actor)


def cmd_checkout(a):
    return api.checkout(_project(a), a.seq, a.actor)


def cmd_profile_list(a):
    return api.profile_list()


def cmd_profile_show(a):
    return api.profile_show(a.id)


def cmd_objective_list(a):
    return api.objective_list()


def cmd_objective_show(a):
    return api.objective_show(a.id)


def cmd_objective_set(a):
    return api.objective_set(_project(a), _read_arg_or_file(a.spec), variant=a.variant, actor=a.actor)


def cmd_objective_validate(a):
    src = a.definition
    # '@file' / '-' are read here; a plain .json path is read by the core
    return api.objective_validate(_read_arg_or_file(src) if src == "-" or src.startswith("@") else src)


def cmd_reference_add(a):
    return api.reference_add(_project(a), a.file, label=a.label, actor=a.actor)


def cmd_reference_list(a):
    return api.reference_list(_project(a))


def cmd_reference_remove(a):
    return api.reference_remove(_project(a), a.id, actor=a.actor)


def cmd_plan_propose(a):
    return api.plan_propose(_project(a), a.stage, variant=a.variant, profile=a.profile, delivery=a.delivery,
                            objective=a.objective, max_iter=a.max_iter)


def cmd_plan_apply(a):
    return api.plan_apply(_project(a), _read_arg_or_file(a.proposal), actor=a.actor)


def cmd_plan_reject(a):
    return api.plan_reject(_project(a), a.proposal_id, a.reason, actor=a.actor)


def cmd_plan_run(a):
    # the planner performs this operation unless another actor is named explicitly
    actor = a.actor if a.actor != "human" else "planner"
    return api.planner_run(_project(a), variant=a.variant, profile=a.profile, delivery=a.delivery,
                           objective=a.objective, max_iter=a.max_iter, apply=a.apply, actor=actor)


def cmd_gate(a):
    return api.gate_check(_project(a), a.variant)


def cmd_get(a):
    return api.project_get(_project(a), a.pointer)


def cmd_knowledge(a):
    query = " ".join(a.query) if a.query else None
    return api.knowledge_lookup(query, id=a.id, kind=a.kind, source=a.source, limit=a.limit, detail=a.detail)


def cmd_route(a):
    return api.route(_project(a))


def cmd_master_plan(a):
    return api.master_plan(_project(a), profile=a.profile, delivery=a.delivery, objective=a.objective,
                           variant=a.variant, target_lufs=a.target_lufs, apply=a.apply, actor=a.actor)


def cmd_master_apply(a):
    return api.master_apply(_project(a), _read_arg_or_file(a.proposal), actor=a.actor)


def _outputs(values):
    return list(values) if values else None


def cmd_render(a):
    return api.render(_project(a), a.variant, outputs=_outputs(a.output))


def cmd_export(a):
    return api.export(_project(a), a.variant)


def cmd_verify(a):
    return api.verify(_project(a), a.variant, recheck_codecs=a.recheck_codecs)


def cmd_report(a):
    return api.report(_project(a), a.variant, lang=a.lang, write=not a.no_write)


def cmd_mcp(a):
    # Serves JSON-RPC on stdin/stdout until stdin closes; nothing else may reach stdout,
    # so leave through SystemExit instead of returning a result for _emit.
    from mankomix.mcp.server import run_stdio
    raise SystemExit(run_stdio(a.root or a.project or "."))


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def _common() -> argparse.ArgumentParser:
    """Global options, accepted before or after the command name."""
    p = CliParser(add_help=False, argument_default=argparse.SUPPRESS)
    p.add_argument("--project", "-p", metavar="PATH",
                   help="project folder (default: current folder if it holds project.json)")
    p.add_argument("--actor", choices=ACTORS, help="who performs the operation (default: human)")
    p.add_argument("--format", choices=("json", "text"), help="output format (default: json)")
    p.add_argument("--debug", action="store_true", help="show tracebacks for unexpected errors")
    return p


GLOBAL_DEFAULTS = {"project": None, "actor": "human", "format": "json", "debug": False}


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = CliParser(prog="mankomix", parents=[common],
                       description="MankoMIX: agent-first, deterministic mixing and mastering. "
                                   "Every command prints JSON (use --format text for a summary).")
    parser.add_argument("--version", action="version", version=f"mankomix {ENGINE_VERSION}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def add(name: str, func, help_: str, parent=sub):
        sp = parent.add_parser(name, parents=[common], help=help_, description=help_)
        if func is not None:
            sp.set_defaults(func=func)
        return sp

    sp = add("doctor", cmd_doctor, "check dependencies, ffmpeg build, encoders, GPU, models")
    sp.add_argument("--strict-lgpl", dest="strict_lgpl", action="store_true", default=None,
                    help="treat a non-LGPL ffmpeg build as an error")
    sp.add_argument("--no-strict-lgpl", dest="strict_lgpl", action="store_false",
                    help="disable strict LGPL mode even if configured")

    sp = add("init", cmd_init, "create a project folder")
    sp.add_argument("path", nargs="?", help="project folder (default: --project or current folder)")
    sp.add_argument("--title", help="song title (default: folder name)")
    sp.add_argument("--genre", help="genre id for priors (e.g. jpop)")
    sp.add_argument("--project-id", dest="project_id", help="fixed project id (prj_ is prefixed when missing)")

    sp = add("import", cmd_import, "import files/folders as-is with the file adapter")
    sp.add_argument("sources", nargs="+", help="files or folders (stems, fullmix, Suno export set)")
    sp.add_argument("--mode", choices=("copy", "link"), default="copy",
                    help="copy byte-identical into assets/ (default) or reference in place")
    sp.add_argument("--provenance", help="declared provenance as a JSON object, '@file' or '-'")

    add("status", cmd_status, "project summary")
    add("validate", cmd_validate, "validate project.json (schema and invariants)")

    sp = add("analyze", cmd_analyze, "measure all assets and the static stem sum (cached)")
    sp.add_argument("--force", action="store_true", help="ignore the analysis cache")

    sp = add("measure", cmd_measure, "measure any audio file")
    sp.add_argument("file")

    sp = add("compare", cmd_compare, "level-matched comparison of two audio files")
    sp.add_argument("file_a")
    sp.add_argument("file_b")

    sp = add("set", cmd_set, "set one value by JSON pointer (validated)")
    sp.add_argument("pointer", help="JSON pointer, e.g. /tracks/0/gain_db")
    sp.add_argument("value", help="JSON value, e.g. -1.5 or '\"text\"'")
    sp.add_argument("--reason", help="why (recorded in the journal)")

    sp = add("patch", cmd_patch, "apply an RFC 6902 JSON patch (validated)")
    sp.add_argument("ops", help="JSON array inline, '@file' or '-' for stdin")
    sp.add_argument("--reason", help="why (recorded in the journal)")

    sp = add("history", cmd_history, "list journal entries")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--detail", action="store_true", help="include the JSON patch of each entry")

    add("undo", cmd_undo, "undo the last operation")

    sp = add("checkout", cmd_checkout, "restore the project to a journal sequence number")
    sp.add_argument("seq", type=int)

    grp = add("profile", None, "media profiles and delivery formats")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    add("list", cmd_profile_list, "list media profiles and delivery formats", gsub)
    add("show", cmd_profile_show, "show one profile or delivery format", gsub).add_argument("id")

    grp = add("objective", None, "objective functions")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    add("list", cmd_objective_list, "list objectives", gsub)
    add("show", cmd_objective_show, "show one objective", gsub).add_argument("id")
    sp = add("set", cmd_objective_set, "set the project objective (blend, intensity, overrides, lead)", gsub)
    sp.add_argument("spec", help="'comfort', 'bass_heavy:0.7', 'comfort:0.6+bass_heavy:0.4', JSON inline, "
                                 "'@file' or '-'")
    sp.add_argument("--variant", help="set a variant's objective override instead of the project objective")
    sp = add("validate", cmd_objective_validate,
             "validate an objective definition (.json file, inline JSON, '@file', '-') or an objective spec", gsub)
    sp.add_argument("definition")
    for name, ms in OBJECTIVE_STUBS.items():
        add(name, _stub("objective", ms, name), f"(not implemented yet, {ms})", gsub) \
            .add_argument("args", nargs=argparse.REMAINDER)

    grp = add("reference", None, "reference tracks (only measurement vectors are stored, never audio)")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    sp = add("add", cmd_reference_add, "measure a reference file and register its vector", gsub)
    sp.add_argument("file")
    sp.add_argument("--label", help="display label (default: file name)")
    add("list", cmd_reference_list, "list registered references", gsub)
    add("remove", cmd_reference_remove, "remove a reference and its vector", gsub).add_argument("id")

    grp = add("plan", None, "stage plans: propose, approve and apply, reject (R-31); planner loop")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True

    def plan_opts(sp):
        sp.add_argument("--variant", help="variant id (default: var_<profile>)")
        sp.add_argument("--profile", help="media profile id (default: the variant's, else streaming_universal)")
        sp.add_argument("--delivery", help="delivery format id (default: the profile's default)")
        sp.add_argument("--objective", help="objective for this plan, e.g. comfort:0.6+bass_heavy:0.4 "
                                            "(default: the project's)")

    sp = add("propose", cmd_plan_propose,
             "propose a stage plan refined by the planner (saved under cache/proposals/)", gsub)
    sp.add_argument("--stage", choices=("master", "mix", "clean"), default="master")
    plan_opts(sp)
    sp.add_argument("--max-iter", dest="max_iter", type=int, help="planner iteration cap (default 6)")
    sp = add("apply", cmd_plan_apply, "approve and apply a proposal", gsub)
    sp.add_argument("proposal", help="proposal id, JSON inline, '@file' or '-'")
    sp = add("reject", cmd_plan_reject, "reject a proposal and ask for an alternative (journaled)", gsub)
    sp.add_argument("proposal_id")
    sp.add_argument("--reason", required=True, help="why the proposal is rejected")
    sp = add("run", cmd_plan_run,
             "run the planner loop (measure, preview, evaluate, iterate) for the master stage", gsub)
    plan_opts(sp)
    sp.add_argument("--max-iter", dest="max_iter", type=int, default=6, help="iteration cap (default 6)")
    sp.add_argument("--apply", action="store_true", help="apply the resulting proposal")

    sp = add("gate", cmd_gate, "translation gate OF-5 on a variant's master (exit 1 unless pass)")
    sp.add_argument("variant", nargs="?")

    sp = add("get", cmd_get, "read project.json or the value at a JSON pointer")
    sp.add_argument("pointer", nargs="?", help="JSON pointer, e.g. /variants/0/evaluation (default: whole document)")

    sp = add("knowledge", cmd_knowledge, "look up rules (R-nn), vocabulary, bands, genre priors and thresholds")
    sp.add_argument("query", nargs="*", help="free text; every word must match")
    sp.add_argument("--id", help="exact entry id, e.g. R-14 or komori")
    sp.add_argument("--kind", help="rule, term, band, genre, section, table, ...")
    sp.add_argument("--source", help="knowledge file name without .json, e.g. rules")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--detail", action="store_true", help="include each entry's data")

    add("route", cmd_route, "mastering route selection (R-21)")

    grp = add("master", None, "mastering stage (full-mix route in M2)")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    sp = add("plan", cmd_master_plan, "propose a mastering chain for a profile (R-31 proposal)", gsub)
    sp.add_argument("--profile", required=True, help="media profile id, e.g. spotify, club")
    sp.add_argument("--delivery", help="delivery format id (default: the profile's default)")
    sp.add_argument("--objective", help="objective id or id:intensity, e.g. bass_heavy:0.7")
    sp.add_argument("--variant", help="variant id (default: var_<profile>)")
    sp.add_argument("--target-lufs", dest="target_lufs", type=float, help="loudness target within the profile window")
    sp.add_argument("--apply", action="store_true", help="apply the proposal right away")
    sp = add("apply", cmd_master_apply, "apply a mastering proposal", gsub)
    sp.add_argument("proposal", help="proposal id, JSON inline, '@file' or '-'")

    sp = add("render", cmd_render, "render a variant's outputs (masters + manifests)")
    sp.add_argument("variant", nargs="?", help="variant id (optional if the project has one variant)")
    sp.add_argument("--output", action="append", help="profile:delivery to render (repeatable)")

    sp = add("export", cmd_export, "final export of every output of a variant")
    sp.add_argument("variant", nargs="?")

    sp = add("verify", cmd_verify, "verify rendered outputs (S-01, S-02, S-05, S-06, S-09, ...)")
    sp.add_argument("variant", nargs="?")
    sp.add_argument("--recheck-codecs", dest="recheck_codecs", action="store_true",
                    help="re-run codec round trips even if the render-time results are still valid")

    sp = add("report", cmd_report, "build the Mix Report (JSON + Markdown, ja/en)")
    sp.add_argument("variant", nargs="?")
    sp.add_argument("--lang", choices=("ja", "en", "both"), default="both")
    sp.add_argument("--no-write", dest="no_write", action="store_true", help="do not write files under reports/")

    sp = add("mcp", cmd_mcp, "MCP server over stdio (JSON-RPC 2.0) for AI agents")
    sp.add_argument("--root", help="workspace folder the server may access (default: --project or current folder)")

    for name, (ms, desc) in STUB_GROUPS.items():
        add(name, _stub(name, ms), f"{desc} (not implemented yet, {ms})") \
            .add_argument("args", nargs=argparse.REMAINDER)
    return parser


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf is not None:
            try:
                reconf(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _emit(obj: dict, fmt: str, command: str | None) -> None:
    if fmt == "text":
        text = render_text(command, obj)
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _wants(argv: list[str], flag: str) -> bool:
    return flag in argv


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    fmt = "text" if any(x in ("--format=text",) for x in argv) or \
        any(argv[i] == "--format" and i + 1 < len(argv) and argv[i + 1] == "text" for i in range(len(argv))) \
        else "json"
    debug = _wants(argv, "--debug")
    command = None
    try:
        parser = build_parser()
        try:
            args = parser.parse_args(argv)
        except SystemExit as e:          # --help / --version
            return int(e.code or 0)
        for k, v in GLOBAL_DEFAULTS.items():
            if not hasattr(args, k):
                setattr(args, k, v)
        fmt, debug = args.format, args.debug
        command = " ".join(x for x in (getattr(args, "command", None), getattr(args, "subcommand", None)) if x)
        result = args.func(args)
        _emit(result, fmt, command)
        if command == "doctor" and result.get("status") == "error":
            return EXIT_ENV_ERROR
        if command in ("verify", "gate") and isinstance(result, dict) and result.get("exit_code"):
            return int(result["exit_code"])
        return EXIT_OK
    except MankoError as e:
        _emit(e.to_dict(), fmt, "error")
        return e.exit_code
    except json.JSONDecodeError as e:
        _emit(InputError(f"invalid JSON: {e.msg}").to_dict(), fmt, "error")
        return EXIT_INPUT_ERROR
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # Output consumer went away (e.g. `| head`); silence the final flush.
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass
        return EXIT_OK
    except Exception as e:  # unexpected: environment / internal problem
        msg = api._scrub_str(f"{type(e).__name__}: {e}", api._known_roots(None))
        payload = {"error": "internal_error", "message": msg, "details": {}}
        if debug:
            payload["details"]["traceback"] = api._scrub_str(traceback.format_exc(), api._known_roots(None))
        _emit(payload, fmt, "error")
        return EXIT_ENV_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
