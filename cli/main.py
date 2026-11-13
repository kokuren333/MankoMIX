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
    "master": ("M2", "mastering plan/apply"),
    "render": ("M2", "preview rendering"),
    "export": ("M2", "final export per output"),
    "verify": ("M2", "verification"),
    "report": ("M2", "Mix Report"),
    "run": ("M4", "one-shot pipeline with the planner"),
    "model": ("M6", "model registry"),
    "reference": ("M3", "reference tracks"),
    "serve": ("M8", "local GUI server"),
    "mcp": ("M7", "MCP server (stdio)"),
}
OBJECTIVE_STUBS = {"set": "M3", "validate": "M3"}


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
    return api.init_project(path, title=title, genre=a.genre)


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
    for name, ms in OBJECTIVE_STUBS.items():
        add(name, _stub("objective", ms, name), f"(not implemented yet, {ms})", gsub) \
            .add_argument("args", nargs=argparse.REMAINDER)

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
