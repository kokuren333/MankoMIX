"""Export deterministic blind listening packs and record graded listening sessions.

Pack writes stay in the export folder; records append sessions in the project
without changing outcomes or the existing machine verification and gate results.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path

import numpy as np

from mankomix import repo_data_root
from mankomix.core import audio_io, mixrender
from mankomix.core.hashing import canonical_hash, sha256_file
from mankomix.core.project import Project

from . import direction as D
from . import edit as E
from . import query as Q

MEMBERS = ("result", "floor", "raw_gain_only")


def _output_path(out, project: Path, floor: Path, kb_roots) -> Path:
    dest = Path(out).resolve()
    repo = repo_data_root().resolve()
    for root in (project, floor, repo / "kb", repo / "_private" / "kb",
                 *(Path(p).resolve() for p in kb_roots)):
        root = root.resolve()
        if dest == root or dest.is_relative_to(root):
            raise D.DirectionError("out must be outside the project, floor and kb folders (G-5)")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise D.DirectionError("out must be absent or an empty directory; refusing to overwrite")
    return dest


def _ranges(sections, excerpts, floor: D._Project, sr: int, length: int) -> list[tuple[int, int]]:
    requested = []
    for section in sections:
        if isinstance(section, str) and section.lstrip().startswith("{"):
            try:
                section = json.loads(section)
            except ValueError as exc:
                raise D.DirectionError("section must be an id or a JSON time range") from exc
        if isinstance(section, str):
            found = next((s for s in floor.sections() if s.get("id") == section), None)
            if found is None:
                raise D.DirectionError(f"unknown floor section '{section}'")
            requested.append((found.get("start_s"), found.get("end_s")))
        elif isinstance(section, dict) and set(section) == {"t0_s", "t1_s"}:
            requested.append((section["t0_s"], section["t1_s"]))
        else:
            raise D.DirectionError("section must be an id or {t0_s, t1_s}")
    requested.extend(excerpts)
    if not requested:
        raise D.DirectionError("give at least one section or excerpt")
    ranges = set()
    for pair in requested:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise D.DirectionError("excerpt must be (t0, t1)")
        if not all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) for t in pair):
            raise D.DirectionError("excerpt times must be finite numbers")
        t0, t1 = pair
        if not 0 <= t0 < t1 <= length / sr:
            raise D.DirectionError("excerpt must lie inside all three members")
        a, b = int(round(t0 * sr)), int(round(t1 * sr))
        if b <= a:
            raise D.DirectionError("excerpt is empty at the native sample rate")
        ranges.add((a, b))
    return sorted(ranges)


def _identity(proj: D._Project) -> str:
    applied = (proj.floor_mxp or {}).get("direction") or {}
    if applied.get("id"):
        return applied["id"]
    # Edit-only / master-only directions need not have a mix proposal.
    records = []
    for path in sorted((proj.root / D.DIRECTIONS_DIR).glob("dir_*.apply.json")):
        rec = D._read_json(path)
        if rec.get("applied") is True and rec.get("id"):
            records.append(rec["id"])
    if len(set(records)) > 1:
        raise D.DirectionError("multiple applied directions; cannot determine the listening seed")
    return records[0] if records else proj.data["id"]


def _lead_activity(project, variant, sr: int, length: int) -> tuple[np.ndarray, dict]:
    from mankomix.core import objectives

    resolved = objectives.resolve_objective(project, variant=variant, references={})
    lead = (resolved.get("lead") or {}).get("stem")
    track = next((t for t in mixrender.stem_tracks(project.data) if t.get("id") == lead), None)
    if track is None:
        raise D.DirectionError("lead matching needs a lead stem")
    ids = list(dict.fromkeys(c["asset"] for c in track.get("clips") or []))
    if not ids:
        raise D.DirectionError("lead matching needs a lead stem asset")
    x, rate, _ = mixrender.static_sum(project, assets=ids)
    if rate != sr:
        raise D.DirectionError("lead stem and masters have different sample rates")
    levels, hop, win = E.frame_levels(E._power(x), sr)
    # Union of active analysis windows; overlap never counts a sample twice.
    edges = np.zeros(length + 1, dtype=np.int32)
    starts = np.flatnonzero(levels > E.ACTIVE_FLOOR_DBFS) * hop
    starts = starts[starts < length]
    np.add.at(edges, starts, 1)
    np.add.at(edges, np.minimum(starts + win, length), -1)
    mask = np.cumsum(edges[:-1]) > 0
    return mask, {"track": lead, "frame_ms": E.FRAME_MS, "hop_ms": E.HOP_MS,
                  "active_floor_dbfs": E.ACTIVE_FLOOR_DBFS,
                  "definition": "union of raw lead asset frames above the edit activity floor"}


def _levels(signals: dict, sr: int, a: int, b: int, mask=None) -> dict:
    levels = {}
    for name, x in signals.items():
        segment = x[a:b]
        if mask is not None:
            segment = segment[mask[a:b]]
        if not len(segment):
            raise D.DirectionError("no active lead samples in the excerpt")
        value = Q.integrated_lufs(segment, sr)
        if not math.isfinite(value):
            raise D.DirectionError("cannot level match a member with undefined loudness")
        levels[name] = value
    return levels


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def listen_pack(project, floor, *, out, variant=None, sections=(), excerpts=(),
                match="integrated", kb_roots=()) -> dict:
    """Export three anonymised WAVs per excerpt and a separate answer key.

    Ranges are a sorted union at sample precision. Lead matching measures the
    excerpt's samples in active raw lead windows, concatenated once in time order.
    All validation and level measurements precede the first output write.
    """
    root, froot = Path(project).resolve(), Path(floor).resolve()
    kb_roots = tuple(kb_roots)
    dest = _output_path(out, root, froot, kb_roots)
    if match not in ("integrated", "section", "lead"):
        raise D.DirectionError("match must be integrated, section or lead")
    proj, fproj = D._Project(root), D._Project(froot)
    v = proj.variant(variant)
    if v is None:
        raise D.DirectionError("result variant not found")
    vid = v["id"]
    fv = fproj.variant(vid) or fproj.variant()
    if fv is None:
        raise D.DirectionError("floor variant not found")
    result_file = D._render_file(root, vid)
    floor_file = D._render_file(froot, fv["id"])
    if result_file is None or floor_file is None:
        raise D.DirectionError("rendered masters missing; render the result and floor first")
    result, sr = audio_io.read(result_file)
    baseline, fsr = audio_io.read(floor_file)
    if sr != fsr:
        raise D.DirectionError("the result and the floor have different sample rates")
    pobj = Project.open(root)
    stems = mixrender.stem_tracks(pobj.data)
    if stems:
        raw, rsr, raw_record = mixrender.static_sum(pobj)
        raw_kind = "stem_sum"
    else:
        aid = mixrender.fullmix_asset_id(pobj.data)
        if not aid:
            raise D.DirectionError("no imported stems or original full mix")
        raw, rsr, raw_record = mixrender.static_sum(pobj, assets=[aid])
        raw_kind = "fullmix"
    if rsr != sr:
        raise D.DirectionError("raw material and masters have different sample rates")
    signals = dict(zip(MEMBERS, (result, baseline, raw)))
    if any(x.ndim != 2 or x.shape[1] not in (1, 2) or not np.isfinite(x).all() for x in signals.values()):
        raise D.DirectionError("members must be finite mono or stereo audio")
    # Give every member the same channel layout, as in the existing measurement path.
    signals = {name: np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x for name, x in signals.items()}
    length = min(len(x) for x in signals.values())
    ranges = _ranges(sections, excerpts, fproj, sr, length)
    identity = _identity(proj)
    mask, lead_info = _lead_activity(pobj, vid, sr, length) if match == "lead" else (None, None)
    integrated = {name: Q.integrated_lufs(x, sr) for name, x in signals.items()} if match == "integrated" else None
    inputs = {"project": sha256_file(root / "project.json"),
              "floor_project": sha256_file(froot / "project.json"),
              "result_master": sha256_file(result_file), "floor_master": sha256_file(floor_file),
              "raw_assets": {aid: sha256_file(pobj.asset_path(aid)) for aid in raw_record["summed_assets"]}}
    if fproj.floor_mxp is not None:
        inputs["floor_proposal"] = canonical_hash(fproj.floor_mxp)
    entries, jobs, groups = {}, [], []
    for index, (a, b) in enumerate(ranges, 1):
        levels = integrated if integrated is not None else _levels(signals, sr, a, b, mask)
        if not all(math.isfinite(x) for x in levels.values()):
            raise D.DirectionError("cannot level match a member with undefined loudness")
        target = min(levels.values())
        gains = {name: min(0.0, round(target - value, 3)) for name, value in levels.items()}
        seed = canonical_hash({"identity": identity, "excerpt_samples": [a, b], "sample_rate": sr})
        order = sorted(MEMBERS, key=lambda name: hashlib.sha256(f"{seed}:{name}".encode("utf-8")).digest())
        names = []
        for slot, name in enumerate(order):
            token = hashlib.sha256(f"{seed}:{slot}".encode("ascii")).hexdigest()[:6]
            filename = f"x{index:02d}_k{slot + 1}{token}.wav"
            gain = gains[name]
            segment = signals[name][a:b] * 10.0 ** (gain / 20.0)
            entries[filename] = {"member": name, "excerpt": {"t0_s": round(a / sr, 3), "t1_s": round(b / sr, 3),
                                                          "start_sample": a, "end_sample": b},
                                 "gain_db": gain, "match": match, "raw_source_kind": raw_kind,
                                 "source_kind": raw_kind if name == "raw_gain_only" else "rendered_master",
                                 "pcm_clipped_samples": int(np.count_nonzero((segment >= 1.0) | (segment < -1.0))),
                                 "loudness_lufs": round(levels[name], 3), "input_hashes": inputs}
            jobs.append((filename, name, a, b, gain))
            names.append(filename)
        groups.append(names)
    key = {"kind": "direction_listen_key", "schema_version": 1, "identity": identity,
           "variant": vid, "sample_rate": sr, "bit_depth": 24, "match": match,
           "raw_source_kind": raw_kind, "input_hashes": inputs, "files": entries}
    if lead_info is not None:
        key["lead_activity"] = lead_info
    conditions = {"level_match": match, "blind": True, "members": list(MEMBERS)}
    answers = {"date": "", "playback": "", "conditions": conditions,
               "judgments": [{"axis": axis, "pair": ["", ""], "answer": "", "note": ""}
                             for axis in ("audible", "preference", "fits_request")]}
    sheet = ["# 聴取シート", "", "聴いた日: __________", "再生環境: __________", ""]
    for i, names in enumerate(groups, 1):
        sheet += [f"## {i:02d}", "", *(f"- `{name}`" for name in names), "",
                  "違いが分かるか: __________", "どちらが好きか（記号で回答）: __________",
                  "依頼に合うか（記号で回答）: __________", "メモ: __________", ""]
    # Recheck immediately before writing, including resolved junction / symlink paths.
    dest = _output_path(dest, root, froot, kb_roots)
    dest.mkdir(parents=True, exist_ok=True)
    for filename, name, a, b, gain in jobs:
        segment = signals[name][a:b] * 10.0 ** (gain / 20.0)
        audio_io.write(dest / filename, segment, sr, subtype="PCM_24")
    (dest / "key").mkdir()
    (dest / "key" / "key.json").write_bytes(_json_bytes(key))
    (dest / "sheet.md").write_bytes(("\n".join(sheet) + "\n").encode("utf-8"))
    (dest / "answers.template.json").write_bytes(_json_bytes(answers))
    return {"kind": "direction_listen_pack", "files": sorted([*entries, "key/key.json", "sheet.md", "answers.template.json"]),
            "key": key}


def _answer_object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise D.DirectionError(f"{label} must contain exactly: {', '.join(fields)}; grade is machine assigned")


def _answer_text(value, label):
    if not isinstance(value, str) or len(value) > 400:
        raise D.DirectionError(f"{label} must be a string of at most 400 characters")


def _listening_session(answers) -> dict:
    """Validate one completed answer template, never accepting a supplied grade."""
    _answer_object(answers, ("date", "playback", "conditions", "judgments"), "answers")
    day = answers["date"]
    if not isinstance(day, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) is None:
        raise D.DirectionError("date must be YYYY-MM-DD")
    try:
        date.fromisoformat(day)
    except ValueError:
        raise D.DirectionError("date must be a valid calendar date") from None
    _answer_text(answers["playback"], "playback")
    cond = answers["conditions"]
    _answer_object(cond, ("level_match", "blind", "members"), "conditions")
    if cond["level_match"] not in ("integrated", "section", "lead", "none"):
        raise D.DirectionError("conditions.level_match must be integrated, section, lead or none")
    if not isinstance(cond["blind"], bool):
        raise D.DirectionError("conditions.blind must be a boolean")
    if not isinstance(cond["members"], list) or any(m not in MEMBERS for m in cond["members"]):
        raise D.DirectionError("conditions.members must be an array of member names")
    if not isinstance(answers["judgments"], list):
        raise D.DirectionError("judgments must be an array")
    for judgment in answers["judgments"]:
        _answer_object(judgment, ("axis", "pair", "answer", "note"), "judgment")
        if judgment["axis"] not in ("audible", "preference", "fits_request"):
            raise D.DirectionError("axis must be audible, preference or fits_request")
        pair = judgment["pair"]
        if not isinstance(pair, list) or len(pair) != 2 or any(m not in MEMBERS for m in pair):
            raise D.DirectionError("pair must be two member names")
        if judgment["answer"] not in (*pair, "none", "unsure"):
            raise D.DirectionError("answer must be a pair member, none or unsure")
        _answer_text(judgment["note"], "note")
    # Copy the caller's JSON data so the returned record never shares mutable answers.
    return json.loads(_json_bytes(answers))


def listening_grade(sessions) -> str:
    """Grade the recorded conditions only; judgments and conformance are separate."""
    qualified = all(s["conditions"]["level_match"] != "none"
                    and s["conditions"]["blind"] is True
                    and "raw_gain_only" in s["conditions"]["members"] for s in sessions)
    return "adoption" if qualified and len({s["date"] for s in sessions}) >= 2 else "trial"


def _record_json(path):
    try:
        return D._read_json(path)
    except (OSError, ValueError) as exc:
        raise D.DirectionError(f"cannot read valid JSON from {path.name}") from exc


def _record_numbers(value):
    if isinstance(value, float):
        if not math.isfinite(value):
            raise D.DirectionError("outcome results must contain finite numbers")
        return round(value, 3)
    if isinstance(value, dict):
        return {k: _record_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_record_numbers(v) for v in value]
    return value


def _record_conformance(root, source, outcome):
    """Copy saved verdicts for the checked variant; never run or infer a check."""
    result = {"source": source.name, "verify": None, "gate": None}
    for key in ("status", "summary"):
        if key in outcome:
            result[f"outcome_{key}"] = _record_numbers(outcome[key])
    vid = outcome.get("variant")
    if not isinstance(vid, str) or re.fullmatch(r"[A-Za-z0-9_-]+", vid) is None:
        return result
    verify_path = root / "reports" / f"verify_{vid}.json"
    if verify_path.is_file():
        verify = _record_json(verify_path)
        if not isinstance(verify, dict):
            raise D.DirectionError("verify report must be an object")
        if verify.get("variant") == vid:
            result["verify"] = _record_numbers(verify.get("overall"))
    # Mix Reports persist the gate, including evaluation of a rendered master.
    report_path = root / "reports" / f"report_{vid}.json"
    if report_path.is_file():
        report = _record_json(report_path)
        if not isinstance(report, dict):
            raise D.DirectionError("Mix Report must be an object")
        if report.get("variant") == vid:
            gate = report.get("translation_gate")
            if isinstance(gate, dict):
                result["gate"] = _record_numbers(gate.get("status"))
    # Applying a master plan also saves its gate in variants[].evaluation.
    if result["gate"] is None:
        project = _record_json(root / "project.json")
        for variant in project.get("variants") or []:
            if variant.get("id") != vid:
                continue
            evaluation = variant.get("evaluation") or {}
            chain = (variant.get("master") or {}).get("chain") or []
            if evaluation.get("chain_hash") == canonical_hash(chain):
                gate = evaluation.get("gate")
                if isinstance(gate, dict):
                    result["gate"] = _record_numbers(gate.get("status"))
            break
    return result


def listen_record(project, direction, answers) -> dict:
    """Append exactly one session, retaining duplicates and never changing the outcome."""
    session = _listening_session(answers)
    if not isinstance(direction, str) or re.fullmatch(r"dir_[0-9a-f]{12}", direction) is None:
        raise D.DirectionError("direction must be dir_<12 lowercase hex digits>")
    root = Path(project)
    if not (root / "project.json").is_file():
        raise D.DirectionError("no project.json in the project folder")
    folder = root / D.DIRECTIONS_DIR
    source = folder / f"{direction}.outcome.json"
    outcome = _record_json(source)
    if not isinstance(outcome, dict) or outcome.get("direction", direction) != direction:
        raise D.DirectionError("outcome must be an object for this direction")
    dest = folder / f"{direction}.listening.json"
    sessions = []
    if dest.exists():
        previous = _record_json(dest)
        if not isinstance(previous, dict) or previous.get("kind") != "direction_listening" \
                or previous.get("schema_version") != 1 or previous.get("direction") != direction \
                or not isinstance(previous.get("sessions"), list):
            raise D.DirectionError("invalid existing listening record")
        sessions = [_listening_session(s) for s in previous["sessions"]]
    sessions.append(session)
    record = {"kind": "direction_listening", "schema_version": 1, "direction": direction,
              "conformance": _record_conformance(root, source, outcome),
              "sessions": sessions, "grade": listening_grade(sessions)}
    dest.write_bytes(_json_bytes(record))
    return record
