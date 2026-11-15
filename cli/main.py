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

# Later-milestone groups (SPEC 10.2 / 17). A group listed here is registered so that the
# command surface is stable, but exits with EXIT_INPUT_ERROR until it is implemented.
# Every group of SPEC 10.2 is implemented now; the mechanism stays for future groups.
STUB_GROUPS: dict[str, tuple[str, str]] = {}
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
    return api.profile_list(full=True) if a.detail else api.profile_list()


def cmd_profile_deliveries(a):
    return api.delivery_list()


def cmd_profile_show(a):
    return api.profile_show(a.id)


def cmd_objective_list(a):
    return api.objective_list(full=True) if a.detail else api.objective_list()


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


def _overrides(text):
    return json.loads(_read_arg_or_file(text)) if text else None


def cmd_plan_propose(a):
    return api.plan_propose(_project(a), a.stage, variant=a.variant, profile=a.profile, delivery=a.delivery,
                            objective=a.objective, max_iter=a.max_iter, targets=a.target,
                            overrides=_overrides(a.overrides), actor=a.actor)


def cmd_plan_apply(a):
    edits = _read_arg_or_file(a.edits) if a.edits else None
    return api.plan_apply(_project(a), _read_arg_or_file(a.proposal), edits=edits, actor=a.actor)


def cmd_plan_list(a):
    return api.proposal_list(_project(a), variant=a.variant, stage=a.stage, status=a.status)


def cmd_plan_show(a):
    return api.proposal_get(_project(a), a.proposal_id)


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
    if a.last:
        return api.verification_get(_project(a), a.variant)
    return api.verify(_project(a), a.variant, recheck_codecs=a.recheck_codecs, profiles=a.against_profile)


def cmd_variant_list(a):
    return api.variant_list(_project(a))


def cmd_listen(a):
    return api.audio_set(_project(a), a.variant)


def cmd_analysis(a):
    return api.analysis_view(_project(a), a.variant)


def _csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [x.strip() for x in value.split(",") if x.strip()]


def cmd_model_list(a):
    return api.model_list()


def cmd_model_show(a):
    return api.model_show(a.id)


def cmd_model_pull(a):
    return api.model_pull(a.id, allow_candidate=a.allow_candidate, force=a.force)


def cmd_model_register(a):
    runtime = None
    if a.runtime:
        try:
            runtime = json.loads(_read_arg_or_file(a.runtime))
        except ValueError:
            runtime = None
        if not isinstance(runtime, dict):
            raise InputError("--runtime must be a JSON object, '@file' or '-'")
    return api.model_register(a.path, id=a.id, license_weights=a.license_weights, license_code=a.license_code,
                              usage_restrictions=a.usage_restrictions, evidence_url=a.evidence_url, task=a.task,
                              architecture=a.architecture, stems=_csv(a.stems), runtime=runtime,
                              attribution=a.attribution, note=a.note, replace=a.replace)


def cmd_model_verify(a):
    return api.model_verify(a.id)


def cmd_model_remove(a):
    return api.model_remove(a.id)


def cmd_separate(a):
    if a.records:
        return api.separation_list(_project(a))
    return api.separate(_project(a), model=a.model, source=a.source, mode=a.mode, stems=_csv(a.stems),
                        device=a.device, allow_candidate=a.allow_candidate, add_tracks=a.add_tracks,
                        excerpt_s=a.excerpt_s, actor=a.actor)


# -- stages: cleanup and mix (SPEC 6.4, 6.5, 10.2) --

def cmd_clean_plan(a):
    return api.clean_plan(_project(a), targets=a.target, overrides=_overrides(a.overrides), apply=a.apply,
                          actor=a.actor)


def cmd_clean_apply(a):
    return api.clean_apply(_project(a), _read_arg_or_file(a.proposal), actor=a.actor)


def cmd_clean_delta(a):
    return api.clean_delta(_project(a), a.asset)


def cmd_mix_plan(a):
    return api.mix_plan(_project(a), variant=a.variant, objective=a.objective, max_iter=a.max_iter,
                        excerpt=not a.full_length, apply=a.apply, actor=a.actor)


def cmd_mix_apply(a):
    edits = _read_arg_or_file(a.edits) if a.edits else None
    return api.mix_apply(_project(a), _read_arg_or_file(a.proposal), edits=edits, actor=a.actor)


# -- remix operations (SPEC 9.3) --

def cmd_stem_list(a):
    return api.stem_list(_project(a))


def cmd_stem_add(a):
    return api.stem_add(_project(a), a.file, role=a.role, mode=a.mode, reason=a.reason or "", actor=a.actor)


def cmd_stem_replace(a):
    if (a.file is None) == (a.asset is None):
        raise InputError("give a FILE to import or --asset ID (exactly one)")
    return api.stem_replace(_project(a), a.track, a.file, asset=a.asset, keep_chain=not a.drop_chain,
                            mode=a.mode, reason=a.reason or "", actor=a.actor)


def cmd_stem_remove(a):
    return api.stem_remove(_project(a), a.track, reason=a.reason or "", actor=a.actor)


def cmd_stem_move(a):
    return api.stem_move(_project(a), a.clip, a.position, reason=a.reason or "", actor=a.actor)


def cmd_stem_mute(a):
    return api.stem_mute(_project(a), a.track, a.start, a.end, reason=a.reason or "", actor=a.actor)


def cmd_stem_split(a):
    return api.stem_split(_project(a), a.clip, a.at, reason=a.reason or "", actor=a.actor)


def cmd_stem_range_replace(a):
    return api.stem_range_replace(_project(a), a.track, a.start, a.end, a.asset, source_start=a.source_start,
                                  reason=a.reason or "", actor=a.actor)


def cmd_stem_role(a):
    return api.stem_role(_project(a), a.track, a.role, is_lead=a.lead, reason=a.reason or "", actor=a.actor)


def cmd_stem_export(a):
    return api.stem_export(_project(a), a.track, processed=not a.raw, out_dir=a.out_dir, subtype=a.subtype,
                           variant=a.variant)


# -- one-shot pipeline (SPEC 7.1, 10.2) --

def cmd_run(a):
    variants = None
    if a.variants:
        try:
            variants = json.loads(_read_arg_or_file(a.variants))
        except ValueError:
            raise InputError("--variants must be a JSON list of {objective, profile, delivery}, "
                             "'@file' or '-'") from None
    # the planner performs the run unless another actor is named explicitly
    actor = a.actor if a.actor != "human" else "planner"
    profiles = a.profile or ["streaming_universal"]
    return api.run(a.sources, objective=a.objective, profile=profiles[0] if len(profiles) == 1 else profiles,
                   delivery=a.delivery, variants=variants, out=a.out, project=a.project, genre=a.genre,
                   title=a.title, separate=a.separate, mode=a.mode, variant_mix=a.variant_mix,
                   mix_max_iter=a.mix_max_iter, master_max_iter=a.max_iter, excerpt=not a.full_length,
                   actor=actor)


def cmd_report(a):
    return api.report(_project(a), a.variant, lang=a.lang, write=not a.no_write)


# -- direction layer (outside the core; the core never imports it) --

def _shown_path(p: Path) -> str:
    """A path for the JSON output: as given when relative, else only the file name (no absolute paths)."""
    return p.as_posix() if not p.is_absolute() else p.name


def cmd_direction_dossier(a):
    from mankomix.director import dossier
    root = _project(a)
    if not (Path(root) / "project.json").is_file():
        raise InputError("no project.json in the project folder")
    try:
        res = dossier.build_dossier(root, variant=a.variant, song=a.song, kb_root=a.kb_root,
                                    section_audio=not a.no_section_audio, refs=a.refs or None,
                                    ref_kb_root=a.ref_kb)
    except KeyError as e:
        raise InputError(str(e).strip("'\"")) from None
    except ValueError as e:
        raise InputError(str(e)) from None
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(res["markdown"].encode("utf-8"))
        res = {k: v for k, v in res.items() if k != "markdown"}
        res["out"] = _shown_path(out)
    return res


def _direction_errors(fn, *args, **kw):
    from mankomix.director import direction as D
    from mankomix.director import query as Q
    try:
        return fn(*args, **kw)
    except (D.DirectionError, Q.QueryError) as e:
        raise InputError(str(e)) from None


def cmd_direction_validate(a):
    from mankomix.director import direction as D
    doc = _direction_errors(D.parse_document, a.file)
    res = D.validate(doc, a.project if a.project else None)
    res["exit_code"] = 0 if res["ok"] else 1
    return res


def cmd_direction_apply(a):
    from mankomix.director import direction as D
    res = _direction_errors(D.apply, _project(a), a.file, calibrate=bool(getattr(a, "calibrate", False)))
    if not res.get("applied"):
        res["exit_code"] = 1
    return res


def cmd_direction_check(a):
    from mankomix.director import direction as D
    return _direction_errors(D.check, _project(a), a.floor, a.file, variant=a.variant, delivery=a.delivery,
                             translation=bool(getattr(a, "translation", False)))


def cmd_direction_query(a):
    from mankomix.director import query as Q
    from mankomix.core import audio_io
    obs = json.loads(Path(a.spec[1:]).read_text(encoding="utf-8")) if a.spec.startswith("@") else json.loads(a.spec)
    sections = None
    if a.project:
        from mankomix.director import direction as D
        sections = D._Project(_project(a)).sections()
    x, sr = audio_io.read(a.audio)
    items = obs if isinstance(obs, list) else [obs]
    out = []
    for o in items:
        out.append({"id": o.get("id"), **_direction_errors(Q.observe, x, sr, o, sections=sections)})
    return {"kind": "observations", "file": Path(a.audio).name, "observations": out}


def _edit_errors(fn, *args, **kw):
    from mankomix.director import edit as E
    try:
        return _direction_errors(fn, *args, **kw)
    except E.EditError as e:
        raise InputError(str(e)) from None


def _json_arg(text: str | None):
    if text is None:
        return None
    s = text.strip()
    if s.startswith("@"):
        return json.loads(Path(s[1:]).read_text(encoding="utf-8"))
    if s[:1] in "{[\"" or s in ("null", "true", "false"):
        return json.loads(s)
    return s


class _StemInputError(InputError):
    """The read-only stems commands use exit code 1 for invalid measurement inputs."""

    exit_code = 1


def _stem_errors(fn, *args, **kw):
    from mankomix.director.purity import PurityInputError
    from mankomix.director.stemobs import StemObsError
    try:
        return fn(*args, **kw)
    except (StemObsError, PurityInputError) as e:
        raise _StemInputError(str(e)) from None


def cmd_direction_stems_observe(a):
    from mankomix.director import relate as R
    specs = json.loads(_read_arg_or_file(a.spec))
    return _stem_errors(R.observe_specs, _project(a), specs, variant=a.variant)


def cmd_direction_stems_relate(a):
    from mankomix.director import relate as R
    return _stem_errors(R.stem_relate, _project(a), variant=a.variant, section=_json_arg(a.section), top=a.top)


def cmd_direction_stems_purity(a):
    from mankomix.director import purity as P
    return _stem_errors(P.stem_purity, _project(a), tracks=a.track)


def cmd_direction_edit_scan(a):
    from mankomix.director import edit as E
    params = _json_arg(a.params) if a.params else {}
    return _edit_errors(E.scan, _project(a), a.track, a.op, params, _json_arg(a.section))


def cmd_direction_edit_revert(a):
    from mankomix.director import edit as E
    return _edit_errors(E.revert, _project(a), a.direction, a.move, actor=a.actor)


def _ref_errors(fn, *args, **kw):
    from mankomix.core.errors import EnvironmentProblem
    from mankomix.director import refsheet as RSH
    from mankomix.director import refstudy as RS
    try:
        return fn(*args, **kw)
    except RS.SeparationUnavailable as e:
        raise EnvironmentProblem(f"--separate: {e}") from None
    except (RS.RefStudyError, RSH.RefSheetError) as e:
        raise InputError(str(e)) from None


def cmd_direction_ref_study(a):
    from mankomix.director import refstudy as RS
    res = _ref_errors(RS.study_command, a.work, master=a.master, stems=a.stems, sections=a.sections,
                      roles=a.roles, separate=a.separate, kb_root=a.kb, add=a.add)
    res["kb"] = _shown_path(Path(a.kb))
    return res


def cmd_direction_ref_compare(a):
    from mankomix.director import refsheet as RSH
    res = _ref_errors(RSH.compare_command, _project(a), a.work, a.out, variant=a.variant, kb_root=a.kb,
                      add=a.add)
    res["out"] = _shown_path(Path(a.out))
    return res


def cmd_direction_ref_credit(a):
    from mankomix.director import refstudy as RS
    res = _ref_errors(RS.credit_command, a.person, kb_root=a.kb)
    res["kb"] = _shown_path(Path(a.kb))
    return res


def cmd_direction_ref_list(a):
    from mankomix.director import refstudy as RS
    res = RS.list_command(a.kb)
    res["kb"] = _shown_path(Path(a.kb))
    return res


def cmd_kb_index(a):
    from mankomix.director import kb
    root = Path(a.root)
    if not root.is_dir():
        raise InputError(f"kb root not found: {_shown_path(root)}")
    res = kb.write_index(root)
    res["root"] = _shown_path(root)
    return res


def cmd_kb_lint(a):
    from mankomix.director import kb
    res = kb.lint(Path(a.root))
    res["root"] = _shown_path(Path(a.root))
    res["exit_code"] = 0 if res["ok"] else 1
    return res


def cmd_kb_search(a):
    from mankomix.director import kb
    root = Path(a.root)
    if not root.is_dir():
        raise InputError(f"kb root not found: {_shown_path(root)}")
    res = kb.search(root, kind=a.kind, genre=a.genre, text=a.text, source_type=a.source_type,
                    curriculum=a.curriculum)
    res["root"] = _shown_path(root)
    return res


def cmd_kb_show(a):
    from mankomix.director import kb
    root = Path(a.root)
    if not root.is_dir():
        raise InputError(f"kb root not found: {_shown_path(root)}")
    res = kb.show(root, a.id)
    if res is None:
        raise InputError(f"no kb card with id {a.id}", details={"id": a.id, "root": _shown_path(root)})
    res["root"] = _shown_path(root)
    return res


def cmd_serve(a):
    # Serves HTTP until interrupted; prints one JSON line with the address first. Nothing
    # else is printed to stdout, so leave through SystemExit like `mcp`.
    from mankomix.core.server import run_server
    raise SystemExit(run_server(root=a.root, project=a.project, host=a.host, port=a.port, static=a.static,
                                allow_remote=a.allow_remote))


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
    add("list", cmd_profile_list, "list media profiles and delivery formats", gsub) \
        .add_argument("--detail", action="store_true", help="full definitions instead of ids and labels")
    add("show", cmd_profile_show, "show one profile or delivery format", gsub).add_argument("id")
    add("deliveries", cmd_profile_deliveries, "list delivery formats (container, rate, bit depth, dither)", gsub)

    grp = add("objective", None, "objective functions")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    add("list", cmd_objective_list, "list objectives", gsub) \
        .add_argument("--detail", action="store_true", help="full definitions (terms, constraint emphasis)")
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
    sp.add_argument("--stage", choices=("master", "mix", "clean", "cleanup"), default="master")
    plan_opts(sp)
    sp.add_argument("--max-iter", dest="max_iter", type=int,
                    help="planner iteration cap (default: master 6, mix 4)")
    sp.add_argument("--target", action="append",
                    help="clean stage: asset id, track id or 'fullmix' (repeatable; default: every stem)")
    sp.add_argument("--overrides", help="clean stage: step overrides as JSON inline, '@file' or '-'")
    sp = add("apply", cmd_plan_apply, "approve and apply a proposal", gsub)
    sp.add_argument("proposal", help="proposal id, JSON inline, '@file' or '-'")
    sp.add_argument("--edits", help="parameter edits applied first: {\"<processor id>\": {\"<param>\": value}} "
                                    "inline, '@file' or '-'")
    sp = add("list", cmd_plan_list, "list saved proposals (planner and agent, any status), newest first", gsub)
    sp.add_argument("--variant")
    sp.add_argument("--stage", choices=("master", "mix", "clean", "cleanup"))
    sp.add_argument("--status", choices=("pending", "applied", "rejected"))
    sp = add("show", cmd_plan_show, "show one saved proposal (reviewable steps and the full proposal)", gsub)
    sp.add_argument("proposal_id")
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
    sp.add_argument("--last", action="store_true", help="show the last verification without running it again")
    sp.add_argument("--against-profile", dest="against_profile", action="append",
                    help="verification-only profile (repeatable): judge the existing rendered master against "
                         "its P-03 / S-01 / S-02 without re-rendering (SPEC 15.2)")

    grp = add("variant", None, "variants (objective x media profile)")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    add("list", cmd_variant_list, "list variants with objective blend, outputs and render state", gsub)

    sp = add("listen", cmd_listen, "listening set: before / after / delta files and the level-match gain")
    sp.add_argument("variant", nargs="?")

    sp = add("analysis", cmd_analysis, "analysis view: loudness over time, LTAS, band correlation, stems, metrics")
    sp.add_argument("variant", nargs="?")

    grp = add("model", None, "model registry: official catalogue and BYOW (SPEC 12)")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    add("list", cmd_model_list, "list models with license, status and local state", gsub)
    add("show", cmd_model_show, "show one model (license evidence, attribution, files)", gsub).add_argument("id")
    sp = add("pull", cmd_model_pull, "download a catalogue model from its pinned source (sha256 verified)", gsub)
    sp.add_argument("id")
    sp.add_argument("--allow-candidate", dest="allow_candidate", action="store_true",
                    help="also pull a candidate entry whose license evidence is not fully verified")
    sp.add_argument("--force", action="store_true", help="download again even if the files are present")
    sp = add("register", cmd_model_register, "register your own weights (BYOW; hashed in place, never copied)",
             gsub)
    sp.add_argument("path", help="weights file")
    sp.add_argument("--id", required=True, help="model id ([a-z0-9][a-z0-9_.-]*)")
    sp.add_argument("--license-weights", dest="license_weights", required=True,
                    help="license of the weights (use 'unknown' if you do not know it)")
    sp.add_argument("--license-code", dest="license_code", help="license of the inference code")
    sp.add_argument("--usage-restrictions", dest="usage_restrictions", default="unknown",
                    help="none, non_commercial, research_only, unknown, ... (default unknown)")
    sp.add_argument("--evidence-url", dest="evidence_url", help="where the license is stated (http(s) URL)")
    sp.add_argument("--task", default="separation")
    sp.add_argument("--architecture")
    sp.add_argument("--stems", help="comma-separated stem names, e.g. vocals,drums,bass,other")
    sp.add_argument("--runtime", help="runtime JSON (backend, cpu_ok, light, sample_rate, config), '@file' or '-'")
    sp.add_argument("--attribution", default="")
    sp.add_argument("--note", default="")
    sp.add_argument("--replace", action="store_true", help="overwrite an existing BYOW registration")
    add("verify", cmd_model_verify, "re-hash local weight files against the pinned sha256", gsub).add_argument("id")
    add("remove", cmd_model_remove, "delete downloaded weights (official) or forget a BYOW registration", gsub) \
        .add_argument("id")

    sp = add("separate", cmd_separate, "separate a project asset into stems with a registered model (SPEC 6.2)")
    sp.add_argument("--model", help="model id (default: the registry default for the mode)")
    sp.add_argument("--source", help="asset id to separate (default: the full mix)")
    sp.add_argument("--mode", choices=("preview", "full"), default="preview",
                    help="preview: loudest excerpt, assets only (default); full: whole file, adds tracks")
    sp.add_argument("--stems", help="comma-separated subset of the model's stems")
    sp.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    sp.add_argument("--allow-candidate", dest="allow_candidate", action="store_true")
    sp.add_argument("--add-tracks", dest="add_tracks", action="store_true", default=None,
                    help="add tracks for the stems (default: only in full mode)")
    sp.add_argument("--no-add-tracks", dest="add_tracks", action="store_false")
    sp.add_argument("--excerpt-s", dest="excerpt_s", type=float,
                    help="preview excerpt length in seconds (default 30)")
    sp.add_argument("--records", action="store_true", help="list the project's separation records instead")

    grp = add("clean", None, "cleanup stage (SPEC 6.4): plan, apply, delta")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    sp = add("plan", cmd_clean_plan, "propose a cleanup plan per stem (or the 2-mix on the full-mix route)", gsub)
    sp.add_argument("--target", action="append",
                    help="asset id, track id or 'fullmix' (repeatable; default: every stem)")
    sp.add_argument("--overrides", help="step overrides, e.g. '{\"spectral_reduction\": \"light\"}', "
                                        "inline, '@file' or '-'")
    sp.add_argument("--apply", action="store_true", help="apply the proposal right away")
    sp = add("apply", cmd_clean_apply, "approve and apply a cleanup proposal", gsub)
    sp.add_argument("proposal", help="proposal id, JSON inline, '@file' or '-'")
    sp = add("delta", cmd_clean_delta, "write the removed component of an applied cleanup (for listening)", gsub)
    sp.add_argument("asset", help="asset id, track id or 'fullmix'")

    grp = add("mix", None, "mix stage (SPEC 6.5): plan, apply")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    sp = add("plan", cmd_mix_plan, "propose a mix in the fixed order (balance .. mix bus), measured per step", gsub)
    sp.add_argument("--variant", help="plan a variant's mix (stored as its track overrides)")
    sp.add_argument("--objective", help="objective for this plan, e.g. vocal_forward:0.7 (default: the project's)")
    sp.add_argument("--max-iter", dest="max_iter", type=int, default=4, help="iteration cap (default 4)")
    sp.add_argument("--full-length", dest="full_length", action="store_true",
                    help="evaluate on the full length instead of representative excerpts")
    sp.add_argument("--apply", action="store_true", help="apply the proposal right away")
    sp = add("apply", cmd_mix_apply, "approve and apply a mix proposal", gsub)
    sp.add_argument("proposal", help="proposal id, JSON inline, '@file' or '-'")
    sp.add_argument("--edits", help="parameter edits applied first: {\"<processor id>\": {\"<param>\": value}} "
                                    "inline, '@file' or '-'")

    grp = add("stem", None, "remix operations on stems (SPEC 9.3); times in samples or seconds ('1.5s')")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True

    def reason(sp):
        sp.add_argument("--reason", help="why (recorded in the journal)")
        return sp

    add("list", cmd_stem_list, "list tracks, clips, unused assets and R-22 notes", gsub)
    sp = reason(add("add", cmd_stem_add, "import a file as a new stem track (checks + tempo/key report)", gsub))
    sp.add_argument("file")
    sp.add_argument("--role", help="role, e.g. guitar (default: estimated from the file name)")
    sp.add_argument("--mode", choices=("copy", "link"), default="copy")
    sp = reason(add("replace", cmd_stem_replace, "point a track at another file or asset", gsub))
    sp.add_argument("track")
    sp.add_argument("file", nargs="?", help="audio file to import")
    sp.add_argument("--asset", help="use an existing asset id instead of a file")
    sp.add_argument("--drop-chain", dest="drop_chain", action="store_true",
                    help="clear the track chain (default: keep it)")
    sp.add_argument("--mode", choices=("copy", "link"), default="copy")
    sp = reason(add("remove", cmd_stem_remove, "remove a track (its assets stay, flagged unused)", gsub))
    sp.add_argument("track")
    sp = reason(add("move", cmd_stem_move, "move a clip on the timeline", gsub))
    sp.add_argument("clip")
    sp.add_argument("position", help="new timeline start (samples or '1.5s')")
    sp = reason(add("mute", cmd_stem_mute, "mute a range of a track", gsub))
    sp.add_argument("track")
    sp.add_argument("start")
    sp.add_argument("end")
    sp = reason(add("split", cmd_stem_split, "split a clip at a timeline position", gsub))
    sp.add_argument("clip")
    sp.add_argument("at")
    sp = reason(add("range-replace", cmd_stem_range_replace,
                    "mute a range of a track and place a clip of another asset there", gsub))
    sp.add_argument("track")
    sp.add_argument("start")
    sp.add_argument("end")
    sp.add_argument("asset", help="asset id to place")
    sp.add_argument("--source-start", dest="source_start", default="0", help="offset in the asset (default 0)")
    sp = reason(add("role", cmd_stem_role, "change a track's role and lead flag", gsub))
    sp.add_argument("track")
    sp.add_argument("role")
    sp.add_argument("--lead", dest="lead", action="store_true", default=None, help="make it the single lead")
    sp.add_argument("--no-lead", dest="lead", action="store_false", help="stop it being the lead")
    sp = add("export", cmd_stem_export, "write processed (or raw) stems as WAV files plus a manifest", gsub)
    sp.add_argument("--track", action="append", help="track id (repeatable; default: every stem track)")
    sp.add_argument("--raw", action="store_true", help="edited clip layout only (no chain, fader or pan)")
    sp.add_argument("--out-dir", dest="out_dir", default="renders/stems", help="project-relative folder")
    sp.add_argument("--subtype", choices=("FLOAT", "PCM_24", "PCM_16"), default="FLOAT")
    sp.add_argument("--variant", help="render with a variant's track overrides")

    sp = add("run", cmd_run, "one-shot pipeline with the planner: import, analyze, clean, mix, master, render, "
                             "verify, report; deliverables to --out (exit 1 if a gate or verification fails)")
    sp.add_argument("sources", nargs="+", help="stem folder, files or a single 2-mix")
    sp.add_argument("--objective", default="comfort",
                    help="'comfort', 'bass_heavy:0.7' or a blend 'comfort:0.6+bass_heavy:0.4' (default comfort)")
    sp.add_argument("--profile", action="append", help="media profile (repeatable; default streaming_universal)")
    sp.add_argument("--delivery", action="append",
                    help="delivery format for every profile (repeatable; default: the profile's)")
    sp.add_argument("--variants", help="JSON list of {objective, profile, delivery} instead of the options "
                                       "above, inline, '@file' or '-'")
    sp.add_argument("--out", help="folder for the deliverables (masters, manifests, reports, run_summary.json)")
    sp.add_argument("--genre", help="genre id for priors (e.g. jpop)")
    sp.add_argument("--title", help="song title for a new project (default: the source name)")
    sp.add_argument("--separate", action="store_true", help="separate a 2-mix into stems first (registered model)")
    sp.add_argument("--mode", choices=("copy", "link"), default="copy", help="import mode (default copy)")
    sp.add_argument("--variant-mix", dest="variant_mix", action="store_true",
                    help="plan a separate mix for every variant whose objective differs from the first")
    sp.add_argument("--mix-max-iter", dest="mix_max_iter", type=int, default=4, help="mix iteration cap (default 4)")
    sp.add_argument("--max-iter", dest="max_iter", type=int, default=6, help="master iteration cap (default 6)")
    sp.add_argument("--full-length", dest="full_length", action="store_true",
                    help="evaluate mix candidates on the full length instead of excerpts")

    sp = add("report", cmd_report, "build the Mix Report (JSON + Markdown, ja/en)")
    sp.add_argument("variant", nargs="?")
    sp.add_argument("--lang", choices=("ja", "en", "both"), default="both")
    sp.add_argument("--no-write", dest="no_write", action="store_true", help="do not write files under reports/")

    grp = add("direction", None, "direction layer: song dossier, direction validate / apply / check, observation query")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    sp = add("dossier", cmd_direction_dossier,
             "write the song dossier (Markdown) from the project files: stems, sections, measurements, "
             "constraint margins, processors, the floor mix and its result", gsub)
    sp.add_argument("--variant", help="variant id (default: the project's first variant)")
    sp.add_argument("--out", help="write the Markdown to this file (default: return it in the JSON 'markdown')")
    sp.add_argument("--song", help="song slug used to name the song (the title is then not printed) and to pick "
                                   "the song's kb cards")
    sp.add_argument("--kb-root", dest="kb_root", help="kb folder for the excerpt (default: kb/ of the repository)")
    sp.add_argument("--no-section-audio", dest="no_section_audio", action="store_true",
                    help="skip the per-section loudness table (it reads the cleaned stem audio)")
    sp.add_argument("--ref", dest="refs", action="append", metavar="WORK_ID",
                    help="a work card named for this job (work_<slug>; repeatable): section 10.3 lists its id, "
                         "title and refstudy hash only")
    sp.add_argument("--ref-kb", dest="ref_kb",
                    help="second kb folder searched for the --ref work cards (default: _private/kb of the repository)")
    sp = add("validate", cmd_direction_validate,
             "check a direction document: block shape, ops, processor ranges, the invariant area, quantity "
             "references and the review tier E1-E3 (exit 1 on any error); --project also checks targets", gsub)
    sp.add_argument("file", help="direction Markdown file")
    sp = add("apply", cmd_direction_apply,
             "apply a direction's moves on top of the floor mix of --project (a copy): cleanup overrides via clean "
             "plan, the mix moves as one mxp_ proposal via plan apply; prints the master target to use", gsub)
    sp.add_argument("file", help="direction Markdown file")
    sp.add_argument("--calibrate", action="store_true",
                    help="choose range values inside the declared ranges by predicting the claims at the mix stage "
                         "(renders the mix in memory; the choice is kept in the apply record)")
    sp = add("check", cmd_direction_check,
             "compare the rendered result of --project with the floor (level matched): claims, expectations, "
             "safeguards, move_ref coverage, gate definition hash, convergence -> directions/dir_*.outcome.json", gsub)
    sp.add_argument("file", help="direction Markdown file")
    sp.add_argument("--floor", required=True, help="the floor project folder (rendered)")
    sp.add_argument("--variant", help="variant id (default: the project's first variant)")
    sp.add_argument("--delivery", default="hires_native", help="delivery file to compare (default hires_native)")
    sp.add_argument("--translation", action="store_true",
                    help="add the translation block (mono / small-speaker view; reference only, in no verdict)")
    sp = add("query", cmd_direction_query,
             "observation quantities on an audio file (band_energy, band_ratio, crest, loudness, side_ratio, "
             "correlation); --project resolves section ids", gsub)
    sp.add_argument("audio", help="audio file")
    sp.add_argument("spec", help="observation JSON (object or list) or @file")

    grp_stems = add("stems", None, "read-only stem observations, cross-track relations and contents", gsub)
    ssub = grp_stems.add_subparsers(dest="refcommand", metavar="SUBCOMMAND")
    ssub.required = True
    sp = add("observe", cmd_direction_stems_observe,
             "measure track observation specs on --project; writes nothing; requires valid cleanup caches", ssub)
    sp.add_argument("spec", help="observation JSON (object or list) or @file")
    sp.add_argument("--variant", help="variant id (default: the project's first variant)")
    sp = add("relate", cmd_direction_stems_relate,
             "cross-track masking and band owners on --project; writes nothing; requires valid cleanup caches", ssub)
    sp.add_argument("--variant", help="variant id (default: the project's first variant)")
    sp.add_argument("--section", help="section id or JSON {\"t0_s\", \"t1_s\"}")
    sp.add_argument("--top", type=int, default=3, help="number of top maskers per track (1 to 8; default: 3)")
    sp = add("purity", cmd_direction_stems_purity,
             "post-clean, pre-chain stem contents on --project; writes nothing; requires valid cleanup caches", ssub)
    sp.add_argument("--track", action="append", help="track id (repeatable; default: all audible stems)")

    # the edit (declutter) stage: read-only scan and revert from the ledger (an optional move, UPGRADE2 §1)
    grp_edit = add("edit", None, "edit stage of a direction (edit_trim / edit_gate): scan a track read-only, "
                                 "revert the cut regions from the ledger", gsub)
    esub = grp_edit.add_subparsers(dest="refcommand", metavar="SUBCOMMAND")   # third word of the command name
    esub.required = True
    sp = add("scan", cmd_direction_edit_scan,
             "what an edit move would cut and refuse on --project (raw asset before cleanup, safeguards EG-1 to "
             "EG-5, removed energy); writes nothing", esub)
    sp.add_argument("--track", required=True, help="track id")
    sp.add_argument("--op", required=True, choices=("edit_trim", "edit_gate"), help="edit op")
    sp.add_argument("--params", help="params JSON (as in a direction move) or @file")
    sp.add_argument("--section", help="section id or JSON {\"t0_s\", \"t1_s\"} (detection range)")
    sp = add("revert", cmd_direction_edit_revert,
             "unmute the regions a direction cut and restore the fades (one journal entry), from "
             "directions/dir_<id>.edits.json", esub)
    sp.add_argument("--direction", required=True, help="direction id dir_<12 hex>")
    sp.add_argument("--move", help="only this edit move (default: every applied edit move)")

    # raw-reference path (原液): measures user-supplied references for the director; never the core yardstick
    grp_ref = add("ref", None, "raw references (原液): refstudy of a work, refsheet against this project, engineer "
                               "credit aggregate, list; the core yardstick 'reference add' is separate", gsub)
    rsub = grp_ref.add_subparsers(dest="refcommand", metavar="SUBCOMMAND")
    rsub.required = True
    kb_help = "kb folder (default: _private/kb; third-party works stay private, UD-1)"
    sp = add("study", cmd_direction_ref_study,
             "measure a reference master and/or stems in memory (no audio kept) and write "
             "<kb>/references/works/<slug>/refstudy.md (and a work card template when absent)", rsub)
    sp.add_argument("--work", required=True, help="work slug (the card id is work_<slug>)")
    sp.add_argument("--master", help="reference master (2-mix) audio file")
    sp.add_argument("--stems", help="folder of reference stems (roles from the file names)")
    sp.add_argument("--sections", help="sections JSON [{id, start_s, end_s}], inline or a file "
                                       "(default: the loudest / quietest regions)")
    sp.add_argument("--roles", help="role overrides JSON {file name: role}, inline or a file")
    sp.add_argument("--separate", action="store_true",
                    help="pseudo stems from --master with the registered separation model (origin: separated, "
                         "confidence at most medium); error when no model is usable here")
    sp.add_argument("--add", action="append", choices=("transient",),
                    help="optional section (repeatable; off by default): transient = per-section band crest, "
                         "attack density and their signs (master only)")
    sp.add_argument("--kb", default="_private/kb", help=kb_help)
    sp = add("compare", cmd_direction_ref_compare,
             "write the refsheet: the work's refstudy next to this project's master and stems with the same "
             "definitions (reference / this / difference / conditions; read-only)", rsub)
    sp.add_argument("--work", required=True, help="work slug")
    sp.add_argument("--variant", help="variant id (default: the project's first variant)")
    sp.add_argument("--out", required=True, help="Markdown file to write (outside the project folder)")
    sp.add_argument("--add", action="append", choices=("transient", "guide"),
                    help="optional section (repeatable; off by default): transient = both transient profiles; "
                         "guide = shape deviation from the generic guide (and the project's yardstick)")
    sp.add_argument("--kb", default="_private/kb", help=kb_help)
    sp = add("credit", cmd_direction_ref_credit,
             "regenerate the aggregate part of an engineer card from the credited works' refstudies "
             "(median, IQR, n; n < 3 is shown as cases, not a trend)", rsub)
    sp.add_argument("--person", required=True, help="engineer slug (the card id is eng_<slug>)")
    sp.add_argument("--kb", default="_private/kb", help=kb_help)
    add("list", cmd_direction_ref_list, "works and engineers of the kb with refstudy freshness", rsub)         .add_argument("--kb", default="_private/kb", help=kb_help)

    grp = add("kb", None, "experience store kb/: index, lint, search and show")
    gsub = grp.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    gsub.required = True
    add("index", cmd_kb_index, "regenerate kb/INDEX.md from the front matter of every card", gsub) \
        .add_argument("--root", default="kb", help="kb folder (default: kb)")
    add("lint", cmd_kb_lint, "check front matter, backing links, forbidden content, broken links and index "
                             "freshness (exit 1 on any violation)", gsub) \
        .add_argument("--root", default="kb", help="kb folder (default: kb)")
    sp = add("search", cmd_kb_search, "find cards by kind, genre and text (index order; read-only)", gsub)
    sp.add_argument("--kind", action="append", help="card kind (repeatable), e.g. theory, work, lesson")
    sp.add_argument("--genre", action="append", help="genre in the card's genre list or applies_to (repeatable)")
    sp.add_argument("--text", help="case-insensitive text in the id, title or body")
    sp.add_argument("--source-type", dest="source_type", action="append",
                    help="the card's optional source_type (repeatable), e.g. curriculum")
    sp.add_argument("--curriculum", help="bundle id cur_<slug>: its cards, by the bundle's order of learning, then id")
    sp.add_argument("--root", default="kb", help="kb folder (default: kb)")
    sp = add("show", cmd_kb_show, "front matter and body of one card by id (read-only)", gsub)
    sp.add_argument("id", help="card id, e.g. KT-0001, work_<slug>, KL-0001")
    sp.add_argument("--root", default="kb", help="kb folder (default: kb)")

    sp = add("serve", cmd_serve, "local server for the GUI (HTTP + Server-Sent Events, loopback only by default)")
    sp.add_argument("--root", help="workspace folder the server may access (default: --project or current folder)")
    sp.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    sp.add_argument("--port", type=int, default=8765, help="port (default 8765; 0 = any free port)")
    sp.add_argument("--static", help="built GUI folder to serve at / (default: gui/dist when present)")
    sp.add_argument("--allow-remote", dest="allow_remote", action="store_true",
                    help="allow a non-loopback bind address (exposes the project to the network)")

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
        command = " ".join(x for x in (getattr(args, "command", None), getattr(args, "subcommand", None),
                                       getattr(args, "refcommand", None)) if x)
        result = args.func(args)
        _emit(result, fmt, command)
        if command == "doctor" and result.get("status") == "error":
            return EXIT_ENV_ERROR
        if command in ("verify", "gate", "run", "kb lint", "direction validate", "direction apply") and isinstance(result, dict) and result.get("exit_code"):
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
