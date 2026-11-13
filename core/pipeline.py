"""One-shot pipeline with the planner only (docs/SPEC.md 6, 7.1, 7.2, 9.4, 10.2 ``run``, 15.2).

    input -> [separation] -> analysis -> cleanup -> mix -> mastering -> verify + Mix Report

Every stage goes through the core API facade (``core.api``), the same calls an agent
makes through MCP or a person through the CLI, so ``run`` has no logic of its own
beyond sequencing and the stage gates (SPEC 6: "measure -> plan -> run -> measure ->
stage gate"; a failed gate stops the run with the stage and the reason).

Stages and gates
----------------
project   create ``<name>.mmx`` (next to ``out``, else in the current folder) or open
          ``project``; an existing project is reused (identical files are not imported
          twice).
import    file adapter, as-is (A-12). Gate: at least one usable asset.
separate  only with ``separate=True`` and a 2-mix without stems (registered model, full mode).
analyze   measurement vectors (cached).
clean     plan for every stem (or the 2-mix on the full-mix route); applied when something
          was detected, skipped otherwise. Gate: S-07 (null-test residual) of every
          cleaned asset.
mix       when stems exist (not for separated-only stems next to a 2-mix, R-21): mix plan
          with the primary objective, applied. Gate: no S-03 / S-04 failure. A 2-mix
          alone takes the full-mix route (stage skipped).
master    per variant (objective x profile): planner loop, applied; further deliveries of
          the same variant reuse the approved chain. Gate: S-01 / S-03 / S-04 / S-06 / S-09
          failures of the planner's preview are reported and deferred to verify, which
          measures them again on the rendered files (SPEC 6.7) and is the binding gate.
          A failed translation gate (OF-5) after the planner's iterations does not stop the
          run (SPEC 4.1: a correction target, not a rejection; 7.2: report the best candidate
          and the unresolved issues): the gate reads "warning" and the summary lists it
          under ``unresolved``.
render    every output (masters + manifests).
          A send-back of the master plan (e.g. S-08: the noise floor would return inside the
          profile window) is recorded on the stage and under ``unresolved``; S-08 is a hard
          verify check, so such a master may legitimately fail verification.
verify    every variant; a failed verification gives exit code 1 (the run still writes
          the reports so the failure is explained, but no master of a failed variant is
          delivered).
report    Mix Report per variant, ja + en (JSON + Markdown).
deliver   copies to ``out``: ``<variant>/`` masters, their manifests, the report (json, ja.md,
          en.md) and the verification, plus ``run_summary.json``. Only project-relative or
          out-relative paths are written.

Variants (SPEC 9.4, 15.2): ``profile`` and ``delivery`` may be lists (every profile gets every
delivery), or ``variants`` = [{objective, profile, delivery}] lists them explicitly. Variants
with the primary (first) objective are ``var_<profile>``; others are
``var_<objective>_<profile>``. With ``variant_mix=True`` a variant whose objective differs from
the primary one also gets its own mix plan, stored as the variant's track overrides.

Determinism: the same inputs, options and engine give the same project, masters and reports;
``run_summary.json`` carries no timings (they are only in the returned result).
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .errors import EXIT_INPUT_ERROR, EXIT_OK, EXIT_VERIFY_FAILED, InputError, MankoError

STAGES = ("project", "import", "separate", "analyze", "clean", "mix", "master", "render", "verify", "report",
          "deliver")
SUMMARY_FILE = "run_summary.json"
MIX_GATE_CONSTRAINTS = ("S-03", "S-04")
MASTER_GATE_CONSTRAINTS = ("S-01", "S-03", "S-04", "S-06", "S-09")


class _Stop(Exception):
    """A stage gate failed: stop the run (not an error of the run itself)."""

    def __init__(self, stage: str, reason: dict, exit_code: int = EXIT_VERIFY_FAILED):
        super().__init__(reason.get("en") if isinstance(reason, dict) else str(reason))
        self.stage = stage
        self.reason = reason
        self.exit_code = exit_code


def _api():
    from . import api
    return api


def _T(ja: str, en: str) -> dict:
    return {"ja": ja, "en": en}


# --------------------------------------------------------------------------
# arguments


def _as_list(value: Any, what: str) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    raise InputError(f"{what} must be a string or a list of strings")


def _objective_spec(objective: Any) -> dict:
    """Normalised, validated objective spec {blend, intensity, overrides, lead_stem}."""
    from . import objectives as O
    arg = _api()._objective_arg(objective)
    spec = O.normalize_spec(arg)
    errs = [i for i in O.validate_objective_spec(spec) if i.get("level") == "error"]
    if errs:
        raise InputError(f"invalid objective {objective!r}", details={"issues": errs})
    return {"blend": [{"id": b["id"], "weight": float(b["weight"])} for b in spec["blend"]],
            "intensity": float(spec["intensity"]), "overrides": spec.get("overrides") or {},
            "lead_stem": spec.get("lead_stem")}


def _objective_label(objective: Any, spec: dict) -> str:
    if isinstance(objective, str) and objective.strip()[:1] not in "{[":
        return objective.strip().replace(" ", "")
    blend = spec["blend"]
    if len(blend) == 1:
        return blend[0]["id"] + ("" if spec["intensity"] == 0.5 else f":{spec['intensity']:g}")
    return "+".join(f"{b['id']}:{b['weight']:g}" for b in blend)


def _objective_slug(spec: dict) -> str:
    slug = "_".join(b["id"] for b in spec["blend"])
    if spec["intensity"] != 0.5:
        slug += f"_i{int(round(spec['intensity'] * 100))}"
    return slug


def plan_variants(objective: Any = "comfort", profile: Any = "streaming_universal", delivery: Any = None,
                  variants: Any = None) -> list[dict]:
    """The variants a run produces: [{id, objective (spec), objective_label, primary, profile, deliveries}]."""
    from . import config
    if variants is not None:
        if isinstance(variants, str):
            variants = _api()._parse_json_value(variants, "variants")
        if isinstance(variants, dict):
            variants = [variants]
        if not isinstance(variants, list) or not variants or not all(isinstance(v, dict) for v in variants):
            raise InputError("variants must be a non-empty list of {objective, profile, delivery} objects")
        raw = []
        for v in variants:
            unknown = sorted(set(v) - {"objective", "profile", "delivery", "deliveries"})
            if unknown:
                raise InputError(f"unknown variant keys: {', '.join(unknown)}",
                                 details={"valid": ["objective", "profile", "delivery"]})
            if not v.get("profile"):
                raise InputError("every variant needs a profile")
            raw.append((v.get("objective", objective), v["profile"],
                        _as_list(v.get("delivery", v.get("deliveries")), "delivery")))
    else:
        profiles = _as_list(profile, "profile") or ["streaming_universal"]
        deliveries = _as_list(delivery, "delivery")
        raw = [(objective, p, list(deliveries)) for p in profiles]

    groups: list[dict] = []
    primary_key = None
    for obj, prof, dels in raw:
        if obj is None:
            obj = objective
        spec = _objective_spec(obj)
        key = json.dumps(spec, sort_keys=True)
        if primary_key is None:
            primary_key = key
        p = config.get_profile(prof)
        pid = p["id"]
        if not dels:
            dels = [p.get("default_delivery") or "hires_native"]
        for d in dels:
            config.get_delivery(d)
        g = next((g for g in groups if g["_key"] == key and g["profile"] == pid), None)
        if g is None:
            g = {"_key": key, "objective": spec, "objective_label": _objective_label(obj, spec),
                 "primary": key == primary_key, "profile": pid, "deliveries": []}
            groups.append(g)
        for d in dels:
            if d not in g["deliveries"]:
                g["deliveries"].append(d)
    taken: set[str] = set()
    for g in groups:
        base = f"var_{g['profile']}" if g["primary"] else f"var_{_objective_slug(g['objective'])}_{g['profile']}"
        base = re.sub(r"[^A-Za-z0-9_.-]+", "_", base)
        vid, i = base, 2
        while vid in taken:
            vid, i = f"{base}_{i}", i + 1
        taken.add(vid)
        g["id"] = vid
        g.pop("_key")
    return groups


def _slug(text: str) -> str:
    from .adapters.file import slugify
    return slugify(text) or "song"


def default_project_path(sources: list[str], out: str | Path | None) -> Path:
    first = Path(sources[0])
    name = first.name if first.is_dir() else first.stem
    base = Path(out).resolve().parent if out is not None else Path.cwd()
    return base / f"{_slug(name)}.mmx"


# --------------------------------------------------------------------------
# stage helpers


def _stage(summary: dict, name: str, status: str, t0: float, **kw) -> dict:
    rec = {"stage": name, "status": status, **kw}
    summary["stages"].append(rec)
    summary["timings"][name] = round(summary["timings"].get(name, 0.0) + (time.perf_counter() - t0), 3)
    return rec


def _stem_route(data: dict) -> tuple[bool, str]:
    """(mix stage applies, reason) following R-21."""
    from . import mixrender as mr
    stems = mr.stem_tracks(data)
    fid = mr.fullmix_asset_id(data)
    if not stems:
        return False, "full_mix"
    assets = {a.get("id"): a for a in data.get("assets") or []}
    origins = {(assets.get(c.get("asset")) or {}).get("origin") for t in stems for c in t.get("clips") or []}
    origins.discard(None)
    if fid is not None and origins and origins <= {"separated"}:
        return False, "separated_only"
    return True, "stems"


def _constraint_fails(constraints: Any, ids: tuple[str, ...]) -> list[str]:
    if not isinstance(constraints, dict):
        return []
    out = []
    for k in ids:
        v = constraints.get(k)
        if (v.get("status") if isinstance(v, dict) else v) == "fail":
            out.append(k)
    return out


def _gate_status(gate: Any) -> str | None:
    return gate.get("status") if isinstance(gate, dict) else None


def _gate(constraints_failed: list[str], of5: dict | None, *, defer: bool = False) -> dict:
    """Stage gate (SPEC 4.1, 6, 7.2): a failed safety constraint S-nn rejects the candidate and stops
    the run; a failed translation gate OF-5 makes it a correction target. The planner has already
    iterated up to its cap, so OF-5 failures are reported as unresolved ("warning") instead.
    ``defer``: the constraints are measured again on the rendered files by verify (SPEC 6.7), which
    is then the binding gate; a preview failure is reported ("warning", ``deferred_to_verify``)."""
    of5 = of5 or {}
    if constraints_failed and not defer:
        status = "fail"
    elif constraints_failed or of5.get("status") == "fail":
        status = "warning"
    else:
        status = "pass"
    out = {"status": status, "constraints_failed": list(constraints_failed),
           "of5": {"status": of5.get("status"), "failed": list(of5.get("failed") or [])}}
    if defer and constraints_failed:
        out["deferred_to_verify"] = list(constraints_failed)
    return out


def _unresolved(summary: dict, stage: str, variant: str | None, gate: dict, codes: Any) -> None:
    items = summary.setdefault("unresolved", [])
    if gate.get("of5", {}).get("status") == "fail":
        items.append({"stage": stage, "variant": variant, "code": "of5_fail", "rule": "OF-5",
                      "failed": gate["of5"]["failed"],
                      "note": _T("トランスレーション・ゲート不合格: 反復上限までに是正できなかった（人の判断に委ねる）",
                                 "translation gate failed: not corrected within the iteration cap (left to a human)")})
    for c in sorted({c for c in codes or [] if isinstance(c, str)} - {"gate_fail", "send_back"}):
        items.append({"stage": stage, "variant": variant, "code": c})


def send_back_brief(sb: Any) -> dict | None:
    """{rules, reason} of a master plan's send-back to the mix / cleanup stage (R-14 .. S-08)."""
    if not isinstance(sb, dict) or not sb:
        return None
    rules = sb.get("rules") or [r for r in [sb.get("rule")] + [a.get("rule") for a in sb.get("also") or []
                                                              if isinstance(a, dict)] if r]
    return {"rules": list(rules), "reason": sb.get("reason")}


def _verify_output_brief(o: dict) -> dict:
    checks = o.get("checks") or {}
    failed = sorted(k for k, c in checks.items() if isinstance(c, dict) and c.get("status") == "fail")
    out = {"profile": (o.get("output") or {}).get("profile", o.get("profile")),
           "delivery": (o.get("output") or {}).get("delivery", o.get("delivery")),
           "overall": o.get("overall"), "failed": failed}
    sugg = []
    for k in failed:
        for sg in checks[k].get("suggestions") or []:
            if isinstance(sg, dict) and sg.get("action"):
                sugg.append({"check": k, "action": sg["action"]})
    if sugg:
        out["suggestions"] = sugg
    psb = (checks.get("S-08") or {}).get("plan_send_back") if isinstance(checks.get("S-08"), dict) else None
    if psb:
        out["plan_send_back"] = {"rule": psb.get("rule"), "reason": psb.get("reason")}
    return out


def _copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


# --------------------------------------------------------------------------
# the run


def run(sources: list[str], *, objective: Any = "comfort", profile: Any = "streaming_universal",
        delivery: Any = None, variants: Any = None, out: str | Path | None = None,
        project: str | Path | None = None, genre: str | None = None, title: str | None = None,
        separate: bool = False, mode: str = "copy", variant_mix: bool = False, mix_max_iter: int = 4,
        master_max_iter: int = 6, excerpt: bool = True, actor: str = "planner") -> dict:
    api = _api()
    t_start = time.perf_counter()
    # ---- arguments (errors here are input errors: nothing has been touched yet)
    if isinstance(sources, (str, Path)):
        sources = [str(sources)]
    if not sources:
        raise InputError("no sources given")
    sources = [str(s) for s in sources]
    for s in sources:
        if not Path(s).exists():
            raise InputError(f"source not found: {Path(s).name}")
    if mode not in ("copy", "link"):
        raise InputError(f"unknown import mode '{mode}' (use copy or link)")
    for name, v in (("mix_max_iter", mix_max_iter), ("master_max_iter", master_max_iter)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise InputError(f"{name} must be an integer >= 0")
    from . import journal
    journal.check_actor(actor)
    plan = plan_variants(objective, profile, delivery, variants)
    primary = next(g for g in plan if g["primary"])
    proj_path = Path(project) if project is not None else default_project_path(sources, out)
    out_path = Path(out) if out is not None else None
    if out_path is not None and out_path.exists() and not out_path.is_dir():
        raise InputError(f"--out must be a folder: {out_path.name}")

    summary: dict = {
        "kind": "run_summary", "status": "running", "exit_code": None,
        "project": proj_path.name, "created": False,
        "objective": primary["objective_label"],
        "variants": [{"id": g["id"], "objective": g["objective_label"], "primary": g["primary"],
                      "profile": g["profile"], "deliveries": list(g["deliveries"])} for g in plan],
        "route": None, "stages": [], "results": {}, "unresolved": [], "deliverables": None,
        "stopped_at": None, "reason": None, "error": None, "timings": {},
    }
    stage = "project"
    try:
        # ---- project
        t0 = time.perf_counter()
        if (proj_path / "project.json").is_file():
            proj = api._open(proj_path)
            if genre is not None and proj.data.get("genre") != genre:
                api.set_value(proj_path, "/genre", json.dumps(genre), actor, reason="run: genre")
            _stage(summary, "project", "ok", t0, created=False)
        else:
            name = title or (Path(sources[0]).name if Path(sources[0]).is_dir() else Path(sources[0]).stem)
            api.init_project(proj_path, title=name, genre=genre, actor="human" if actor == "human" else actor)
            summary["created"] = True
            _stage(summary, "project", "ok", t0, created=True)

        # ---- import
        stage = "import"
        t0 = time.perf_counter()
        imp = api.import_files(proj_path, sources, mode=mode, actor=actor)
        data = api._open(proj_path).data
        n_assets = len(api._asset_list(data))
        rejects = [r for rec in imp.get("imported") or [] if isinstance(rec, dict) for r in rec.get("rejects") or []]
        added = sum(len(rec.get("assets_added") or []) for rec in imp.get("imported") or [] if isinstance(rec, dict))
        gate = {"status": "pass" if n_assets else "fail", "assets": n_assets, "added": added,
                "rejects": len(rejects), "check_counts": imp.get("check_counts")}
        _stage(summary, "import", "ok" if n_assets else "failed", t0, gate=gate)
        if not n_assets:
            raise _Stop("import", _T("使える素材がない（取り込み検査ですべて除外された）",
                                     "no usable asset (every file was rejected by the import checks)"),
                        EXIT_INPUT_ERROR)

        # ---- separate (optional)
        stage = "separate"
        t0 = time.perf_counter()
        from . import mixrender as mr
        if separate and not mr.stem_tracks(data) and mr.fullmix_asset_id(data) is not None:
            sep = api.separate(proj_path, mode="full", actor=actor)
            _stage(summary, "separate", "ok", t0, model=sep.get("model_id"), stems=sep.get("stems"),
                   tracks_added=sep.get("tracks_added"))
            data = api._open(proj_path).data
        else:
            why = ("not requested" if not separate else "the project already has stems" if mr.stem_tracks(data)
                   else "no full mix to separate")
            _stage(summary, "separate", "skipped", t0, reason=why)

        # ---- analyze
        stage = "analyze"
        t0 = time.perf_counter()
        an = api.analyze(proj_path, actor=actor)
        _stage(summary, "analyze", "ok", t0, measured=an.get("measured"), cached=an.get("cached"))

        # ---- objective (primary) for the project
        api.objective_set(proj_path, primary["objective"], actor=actor)

        # ---- clean
        stage = "clean"
        t0 = time.perf_counter()
        cp = api.clean_plan(proj_path, actor=actor)
        cs = cp["summary"]
        if cs["items"]:
            ca = api.clean_apply(proj_path, cp["proposal_id"], actor=actor)
            failed = [a["asset"] for a in ca.get("assets") or [] if not (a.get("s07") or {}).get("pass", True)]
            gate = {"status": "fail" if failed else "pass", "check": "S-07", "failed": failed}
            _stage(summary, "clean", "failed" if failed else "applied", t0, proposal_id=cp["proposal_id"],
                   cleaned=[i["asset"] for i in cs["items"]],
                   skipped=[{"asset": s["asset"], "code": s.get("code")} for s in cs["skipped"]], gate=gate)
            if failed:
                raise _Stop("clean", _T(f"整音の null テスト残差が限度を超えた（S-07）: {', '.join(failed)}",
                                        f"cleanup null-test residual over the limit (S-07): {', '.join(failed)}"))
        else:
            _stage(summary, "clean", "skipped", t0, proposal_id=cp["proposal_id"],
                   reason="nothing detected" if cs["skipped"] else "no target",
                   skipped=[{"asset": s["asset"], "code": s.get("code")} for s in cs["skipped"]])

        # ---- mix
        stage = "mix"
        t0 = time.perf_counter()
        data = api._open(proj_path).data
        do_mix, why = _stem_route(data)
        if do_mix:
            mp = api.mix_plan(proj_path, objective=None, max_iter=mix_max_iter, excerpt=excerpt, apply=True,
                              actor=actor)
            ms = mp["summary"]
            fails = list(ms.get("failed_constraints") or [])
            fails = [c for c in fails if c in MIX_GATE_CONSTRAINTS]
            of5 = ms.get("gate") or {}
            gate = _gate(fails, of5)
            _stage(summary, "mix", "failed" if gate["status"] == "fail" else "applied", t0,
                   proposal_id=mp["proposal_id"], score_start=ms.get("score_start"), score=ms.get("score"),
                   moves=ms.get("moves"), unresolved=ms.get("unresolved"), gate=gate)
            _unresolved(summary, "mix", None, gate, ms.get("unresolved"))
            if gate["status"] == "fail":
                raise _Stop("mix", _T("ミックス段の安全条件に落ちた（" + ", ".join(fails) + "）",
                                      "the mix stage violates a safety constraint (" + ", ".join(fails) + ")"))
        else:
            reason = (_T("2mix のみ: フルミックス経路（R-21）", "2-mix only: full-mix route (R-21)") if why == "full_mix"
                      else _T("分離由来のステムのみ: フルミックス経路（R-21）",
                              "separated stems only: full-mix route (R-21)"))
            _stage(summary, "mix", "skipped", t0, reason=reason)
        summary["route"] = api.route(proj_path).get("route")

        # ---- per-variant mix (opt-in) and master
        stage = "master"
        for g in plan:
            t0 = time.perf_counter()
            vid = g["id"]
            obj = None if g["primary"] else g["objective"]
            vmix = None
            if variant_mix and do_mix and not g["primary"]:
                data = api._open(proj_path).data
                if not any(v.get("id") == vid for v in data.get("variants") or []):
                    api.patch(proj_path, [{"op": "add", "path": "/variants/-",
                                           "value": {"id": vid, "objective": g["objective"], "master": {},
                                                     "outputs": [{"profile": g["profile"],
                                                                  "delivery": g["deliveries"][0]}]}}],
                              actor, reason=f"run: variant {vid}")
                vm = api.mix_plan(proj_path, variant=vid, max_iter=mix_max_iter, excerpt=excerpt, apply=True,
                                  actor=actor)
                vmix = {"proposal_id": vm["proposal_id"], "score": vm["summary"].get("score"),
                        "gate": vm["summary"].get("gate")}
            pr = api.planner_run(proj_path, variant=vid, profile=g["profile"], delivery=g["deliveries"][0],
                                 objective=obj, max_iter=master_max_iter, apply=True, actor=actor)
            if len(g["deliveries"]) > 1:
                prop = api.proposal_get(proj_path, pr["proposal_id"])["proposal"]
                for d in g["deliveries"][1:]:
                    api.master_apply(proj_path, {**prop, "delivery": d}, actor=actor)
            s = pr.get("summary") or {}
            fails = _constraint_fails(s.get("constraints"), MASTER_GATE_CONSTRAINTS)
            gstat = _gate_status(s.get("gate"))
            of5_failed = sorted(c.get("id") for c in (s.get("gate") or {}).get("checks") or []
                                if isinstance(c, dict) and c.get("status") == "fail")
            gate = _gate(fails, {"status": gstat, "failed": of5_failed}, defer=True)
            rec = _stage(summary, "master", "failed" if gate["status"] == "fail" else "applied", t0, variant=vid,
                         proposal_id=pr["proposal_id"], score_start=pr.get("score_start"),
                         score=pr.get("score_final"), converged=pr.get("converged"), gate=gate)
            if vmix is not None:
                rec["variant_mix"] = vmix
            sb = send_back_brief(s.get("send_back"))
            if sb is not None:
                rec["send_back"] = sb
            summary["results"][vid] = {"master": {"proposal_id": pr["proposal_id"], "gate": gate, "send_back": sb}}
            _unresolved(summary, "master", vid, gate,
                        [u.get("code") for u in pr.get("unresolved") or [] if isinstance(u, dict)])
            if fails:
                summary["unresolved"].append({"stage": "master", "variant": vid, "code": "constraint_fail",
                                              "failed": fails, "deferred_to": "verify"})
            if sb is not None:
                # SPEC 6.6.3: the master plan sends the problem back to the mix / cleanup stage; the
                # planner-only run cannot act on it, so it is reported (verify decides the outcome)
                summary["unresolved"].append({"stage": "master", "variant": vid, "code": "send_back",
                                              "rules": sb["rules"], "reason": sb["reason"]})
            if gate["status"] == "fail":
                raise _Stop("master", _T(f"マスタリング段の安全条件に落ちた（{vid}: " + ", ".join(fails) + "）",
                                         f"the mastering stage violates a safety constraint ({vid}: "
                                         + ", ".join(fails) + ")"))

        # ---- render, verify, report
        verify_failed: list[str] = []
        for g in plan:
            vid = g["id"]
            stage = "render"
            t0 = time.perf_counter()
            rr = api.render(proj_path, vid)
            outs = [{k: o.get(k) for k in ("profile", "delivery", "file", "manifest", "status", "lufs_i",
                                           "true_peak_dbtp")} for o in rr.get("outputs") or []]
            _stage(summary, "render", "ok", t0, variant=vid, outputs=len(outs))
            stage = "verify"
            t0 = time.perf_counter()
            vr = api.verify(proj_path, vid)
            passed = bool(vr.get("passed"))
            if not passed:
                verify_failed.append(vid)
            per_output = [_verify_output_brief(o) for o in vr.get("outputs") or [] if isinstance(o, dict)]
            _stage(summary, "verify", "ok" if passed else "failed", t0, variant=vid,
                   gate={"status": "pass" if passed else "fail", "overall": vr.get("overall"),
                         "outputs": per_output})
            stage = "report"
            t0 = time.perf_counter()
            rp = api.report(proj_path, vid, lang="both", write=True)
            _stage(summary, "report", "ok", t0, variant=vid, paths=rp.get("paths"))
            res = summary["results"].setdefault(vid, {})
            res.update({"outputs": outs, "archive": (rr.get("archive") or {}).get("file"),
                        "verify": {"overall": vr.get("overall"), "passed": passed, "path": vr.get("path"),
                                   "outputs": per_output},
                        "report": rp.get("paths")})

        # ---- deliver
        stage = "deliver"
        t0 = time.perf_counter()
        if out_path is not None:
            root = Path(api._open(proj_path).root)
            files: list[str] = []
            for g in plan:
                vid = g["id"]
                res = summary["results"][vid]
                todo: list[str] = []
                if vid not in verify_failed:
                    for o in res.get("outputs") or []:
                        todo += [o["file"], o["manifest"]]
                else:
                    todo += [o["manifest"] for o in res.get("outputs") or []]
                todo += [p for p in (res.get("report") or {}).values() if isinstance(p, str)]
                if res.get("verify", {}).get("path"):
                    todo.append(res["verify"]["path"])
                for rel in todo:
                    src = root / rel
                    if src.is_file():
                        dest = out_path / vid / src.name
                        _copy(src, dest)
                        files.append(f"{vid}/{src.name}")
                res["delivered"] = vid not in verify_failed
            summary["deliverables"] = {"out": out_path.name, "files": files}
            _stage(summary, "deliver", "ok", t0, files=len(files),
                   withheld=[{"variant": v, "reason": "verification failed"} for v in verify_failed])
        else:
            _stage(summary, "deliver", "skipped", t0, reason="no --out given; the files stay in the project")
        if verify_failed:
            detail = "; ".join(f"{v}: " + ", ".join(sorted({c for o in summary["results"][v]["verify"]["outputs"]
                                                            for c in o["failed"]}) or ["incomplete"])
                               for v in verify_failed)
            summary["stopped_at"] = "verify"
            summary["reason"] = _T("検証に落ちたバリアントがある（" + detail + "）",
                                   "verification failed (" + detail + ")")
            summary["status"], summary["exit_code"] = "failed", EXIT_VERIFY_FAILED
        else:
            summary["status"], summary["exit_code"] = "ok", EXIT_OK
    except _Stop as stop:
        summary.update(status="stopped", exit_code=stop.exit_code, stopped_at=stop.stage, reason=stop.reason)
    except MankoError as e:
        summary.update(status="failed", exit_code=e.exit_code, stopped_at=stage, error=e.to_dict(),
                       reason=_T(f"{stage} 段でエラー: {e.message}", f"error in the {stage} stage: {e.message}"))
        if stage in ("project",) and not summary["stages"]:
            raise
    summary["timings"]["total"] = round(time.perf_counter() - t_start, 3)
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)
        stored = copy.deepcopy(summary)
        stored.pop("timings", None)
        (out_path / SUMMARY_FILE).write_text(json.dumps(stored, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                             encoding="utf-8")
        summary["summary_file"] = f"{out_path.name}/{SUMMARY_FILE}"
    return summary


__all__ = ["run", "plan_variants", "default_project_path", "STAGES", "SUMMARY_FILE"]
