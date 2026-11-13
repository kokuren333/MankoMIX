"""Short human-readable summaries for `--format text`.

JSON stays the machine contract; this is only a convenience view.
"""

from __future__ import annotations

import json
from typing import Any


def _scalar(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _generic(obj: dict, indent: str = "") -> list[str]:
    lines = []
    for k, v in obj.items():
        if isinstance(v, dict):
            if len(json.dumps(v, ensure_ascii=False)) <= 80:
                lines.append(f"{indent}{k}: {_scalar(v)}")
            else:
                lines.append(f"{indent}{k}:")
                lines += _generic(v, indent + "  ")
        elif isinstance(v, list):
            lines.append(f"{indent}{k}: {len(v)} item(s)")
            for item in v[:20]:
                if isinstance(item, dict):
                    head = item.get("id") or item.get("asset") or item.get("code") or item.get("seq")
                    rest = item.get("message") or item.get("label") or item.get("role") or item.get("op") or ""
                    lines.append(f"{indent}  - {head if head is not None else _scalar(item)} {rest}".rstrip())
                else:
                    lines.append(f"{indent}  - {_scalar(item)}")
        else:
            lines.append(f"{indent}{k}: {_scalar(v)}")
    return lines


def _doctor(r: dict) -> list[str]:
    ff = r.get("ffmpeg") or {}
    enc = ff.get("encoders") or {}
    lines = [
        f"status: {r.get('status')}",
        f"python: {r.get('python', {}).get('version')}",
        "packages: " + ", ".join(f"{k} {v.get('version') or 'missing'}" for k, v in (r.get("packages") or {}).items()),
        f"ffmpeg: {ff.get('version') + ' (' + str(ff.get('build')) + ')' if ff.get('found') and ff.get('version') else ('found' if ff.get('found') else 'not found')}",
        "round-trip encoders: " + (", ".join(f"{c}={e.get('encoder') or '-'}" for c, e in enc.items()) or "-"),
        f"ffprobe: {'found' if (r.get('ffprobe') or {}).get('found') else 'not found'}",
        f"strict LGPL: {(r.get('strict_lgpl') or {}).get('enabled')} ({(r.get('strict_lgpl') or {}).get('source')})",
        "gpu: " + (", ".join(f"{d['name']} {d.get('memory_total') or ''}".strip() for d in (r.get('gpu') or {}).get("devices", [])) or "none"),
        f"models: {(r.get('models') or {}).get('status')}",
    ]
    for i in r.get("issues") or []:
        lines.append(f"[{i.get('level')}] {i.get('message')}")
    return lines


def _status(r: dict) -> list[str]:
    tb = r.get("timebase") or {}
    lines = [f"{r.get('title')} ({r.get('project')}, genre={r.get('genre')})",
             f"timebase: {tb.get('sample_rate')} Hz, {tb.get('length_samples')} samples"]
    lines.append(f"assets: {len(r.get('assets') or [])}")
    for a in r.get("assets") or []:
        lines.append(f"  - {a.get('id')} [{a.get('role')}] {a.get('path')} analysis={a.get('analysis')}")
    lines.append(f"tracks: {len(r.get('tracks') or [])}, fullmix: {r.get('fullmix')}")
    lines.append(f"checks: {_scalar(r.get('check_counts') or {})}")
    lines.append(f"analysis: {_scalar((r.get('analysis') or {}).get('states') or {})}")
    return lines


def _fmt_num(v: Any, unit: str = "") -> str:
    if isinstance(v, (int, float)):
        return f"{v:.2f}{(' ' + unit) if unit else ''}"
    return "n/a"


def _measure(r: dict) -> list[str]:
    inf = r.get("info") or {}
    p03 = (r.get("vector") or {}).get("P-03") or {}
    return [
        f"file: {r.get('file')}",
        f"format: {inf.get('container')} {inf.get('subtype')}, {inf.get('sample_rate')} Hz, "
        f"{inf.get('channels')} ch, {_fmt_num(inf.get('duration_s'), 's')}",
        f"integrated: {_fmt_num(p03.get('integrated_lufs'), 'LUFS')}",
        f"true peak: {_fmt_num(p03.get('true_peak_dbtp'), 'dBTP')}",
        f"LRA: {_fmt_num(p03.get('lra_lu'), 'LU')}, PLR: {_fmt_num(p03.get('plr_db'), 'dB')}, "
        f"PSR: {_fmt_num(p03.get('psr_db'), 'dB')}",
        f"analyzer: {(r.get('vector') or {}).get('analyzer_version')}",
    ]


def _compare(r: dict) -> list[str]:
    c = r.get("comparison") or {}
    lines = [f"a: {r.get('a')}", f"b: {r.get('b')}"]
    if r.get("resampled"):
        rs = r["resampled"]
        lines.append(f"resampled in memory: {rs.get('file')} {rs.get('from_hz')} -> {rs.get('to_hz')} Hz")
    lines.append(f"level match: {c.get('matched_side')} {_fmt_num(c.get('match_gain_db'), 'dB')}")
    for key, d in (c.get("deltas") or {}).items():
        if key.startswith("P-03/") and isinstance(d, dict):
            lines.append(f"  {key}: b - a = {_fmt_num(d.get('delta'), d.get('unit') or '')}")
    lines.append(f"({len(c.get('deltas') or {})} deltas in JSON output)")
    return lines


def _import(r: dict) -> list[str]:
    lines = []
    for rec in r.get("imported") or []:
        lines.append(f"source: {rec.get('input_kind') or rec.get('kind')} ({rec.get('mode')}), "
                     f"added {len(rec.get('assets_added') or [])} asset(s), skipped {len(rec.get('skipped') or [])}")
        for w in rec.get("warnings") or []:
            lines.append(f"  [warning] {w}")
    lines.append(f"assets in project: {r.get('assets')}")
    lines.append(f"checks: {_scalar(r.get('check_counts') or {})}")
    for c in r.get("checks") or []:
        if isinstance(c, dict) and c.get("level") in ("warning", "reject", "error"):
            lines.append(f"  [{c.get('level')}] {c.get('asset') or '-'}: {c.get('message')}")
    return lines


def _analyze(r: dict) -> list[str]:
    lines = [f"analyzer: {r.get('analyzer_version')}",
             f"measured: {r.get('measured')}, cached: {r.get('cached')}, saved: {r.get('saved')}"]
    for a in r.get("assets") or []:
        lines.append(f"  - {a.get('asset')}: {'cached' if a.get('cached') else 'measured'} -> {a.get('path')}")
    ss = r.get("stem_sum")
    if ss:
        lines.append(f"  - stem_sum ({ss.get('stems')} stems): {'cached' if ss.get('cached') else 'measured'}"
                     f" -> {ss.get('path')}")
    for w in r.get("warnings") or []:
        lines.append(f"[{w.get('level')}] {w.get('asset')}: {w.get('message')}")
    return lines


def _error(r: dict) -> list[str]:
    lines = [f"error ({r.get('error')}): {r.get('message')}"]
    for k, v in (r.get("details") or {}).items():
        if k != "traceback":
            lines.append(f"  {k}: {_scalar(v)}")
    if "traceback" in (r.get("details") or {}):
        lines.append(r["details"]["traceback"])
    return lines


def render_text(command: str | None, result: dict) -> str:
    if command == "doctor":
        lines = _doctor(result)
    elif command == "status":
        lines = _status(result)
    elif command == "import":
        lines = _import(result)
    elif command == "analyze":
        lines = _analyze(result)
    elif command == "measure":
        lines = _measure(result)
    elif command == "compare":
        lines = _compare(result)
    elif command == "error":
        lines = _error(result)
    else:
        lines = _generic(result)
    return "\n".join(lines)
