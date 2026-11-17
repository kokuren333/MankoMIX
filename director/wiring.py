"""Read-only wiring derived from project metadata and unapplied direction moves."""
from __future__ import annotations

import json
from pathlib import Path

from mankomix.core import mixrender as MR
from . import direction as D
from . import duck as K

NOTE = ("プロジェクトから導出した配線であり、宣言ではない。"
        "帯域を限ったダッキングとバスを相手にしたダッキングは未対応。")
RELIABILITY = {"routing": "high", "duck": "project_provenance", "planned": "not_applied"}


def _rounded(value):
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return value


def _chain(chain, *, planned=False, move=None):
    rows = []
    for item in chain or []:
        kind = item.get("type") or item.get("processor")
        params = item.get("params") or {}
        row = {"type": kind, "planned": planned}
        if move is not None:
            row["move"] = move
        if kind == "reverb":
            # Include the processor defaults, just as the renderer does.
            from mankomix.dsp.processors import validate_params
            full = validate_params(kind, params)
            row.update({k: full[k] for k in ("lowcut_hz", "highcut_hz")})
        elif kind == "filter":
            from mankomix.dsp.processors import validate_params
            full = validate_params(kind, params)
            row.update({k: full[k] for k in ("kind", "freq_hz")})
        rows.append(row)
    return rows


def _duck(record, *, planned, move, direction):
    release = record.get("release") or {}
    return {"type": "duck", "source": record.get("key"), "target": record.get("track"),
            "depth_db": record.get("depth_db"), "attack_ms": record.get("attack_ms"),
            "release_ms": release.get("ms"), "release_note": release.get("note"),
            "band": "full_band", "key_band_hz": record.get("key_band_hz"),
            "planned": planned, "move": move, "direction": direction}


def wiring(project, *, variant=None, direction=None, format="json"):
    """Return metadata only; never render audio, regenerate caches or save files."""
    if format not in ("json", "mermaid"):
        raise D.DirectionError("bad_value: format must be json or mermaid")
    proj = D._Project(project)
    pv = proj.variant(variant)
    if variant is not None and pv is None:
        raise D.DirectionError(f"unknown variant '{variant}'")
    vid = (pv or {}).get("id")
    data, _ = MR.effective_data(proj, variant_id=vid)
    mix = MR._mix_bus_id(data)
    MR.bus_order(data)
    nodes, edges = [], []
    for kind, holders in (("track", data.get("tracks")), ("bus", data.get("buses"))):
        for holder in sorted(holders or [], key=lambda h: h["id"]):
            hid = holder["id"]
            nodes.append({"id": hid, "type": kind, "planned": False,
                          "chain": _chain(holder.get("chain")), "planned_moves": []})
            edges.append({"type": "route", "source": hid,
                          "target": "master" if hid == mix else holder.get("output") or mix,
                          "planned": False})
            if kind == "track":
                for send in holder.get("sends") or []:
                    edges.append({"type": "send", "source": hid, "target": send["bus"],
                                  "level_db": send.get("level_db", 0.0),
                                  "pre_fader": bool(send.get("pre_fader", False)), "planned": False})
    nodes.append({"id": "master", "type": "master", "planned": False,
                  "chain": _chain((pv or {}).get("master", {}).get("chain")), "planned_moves": []})
    by_id = {n["id"]: n for n in nodes}
    # Floor ducking has no direction move_ref. Its retained proposal identifies
    # the key and release; require the exact automation still to be in use.
    floor = proj.floor_mxp or {}
    axis = ((floor.get("measurements") or {}).get("final") or {}).get("time_axis") or {}
    for move in floor.get("moves") or []:
        if move.get("kind") != "automation" or move.get("status") != "kept" or "R-11" not in (move.get("rules") or []):
            continue
        tid = move.get("track")
        track = next((t for t in data.get("tracks") or [] if t["id"] == tid), {})
        auto = track.get("automation") or {}
        original = (((floor.get("changes") or {}).get("tracks") or {}).get(tid) or {}).get("automation")
        points = auto.get("gain_db") or []
        if auto != original or not points or axis.get("kick") not in by_id:
            continue
        # The floor stores triplets [pre-hit, hit, return] in sample positions.
        attack = max((points[i + 1][0] - points[i][0]) * 1000 / proj.rate
                     for i in range(0, len(points) - 2, 3))
        edges.append(_duck({"key": axis["kick"], "track": tid,
                            "depth_db": -min(p[1] for p in points), "attack_ms": attack,
                            "release": (move.get("measured") or {}).get("release"),
                            "key_band_hz": [40.0, 120.0]},
                           planned=False, move=move.get("id"), direction=None))
    # A summed automation cannot recover its key or timing parameters. Read its
    # provenance record, and require the move still to be present on the target.
    applied = {}
    for path in sorted((Path(project) / D.DIRECTIONS_DIR).glob("dir_*.apply.json")):
        record = D._read_json(path)
        did = record.get("id", path.name.removesuffix(".apply.json"))
        moves = (record.get("record") or {}).get("moves") or {}
        applied[did] = set(moves)
        for mid, move in sorted(moves.items()):
            if move.get("op") != "duck":
                continue
            target = next((t for t in data.get("tracks") or [] if t["id"] == move.get("track")), {})
            refs = (target.get("automation") or {}).get("move_ref") or []
            if isinstance(refs, str):
                refs = [refs]
            if D._ref(did, mid) in refs:
                edges.append(_duck(move, planned=False, move=mid, direction=did))
    if direction is not None:
        doc = D.parse_document(direction)
        moves = [m for m in doc["block"].get("moves") or []
                 if m["id"] not in applied.get(doc["id"], set())]
        # Buses must be present before sends and chain additions are overlaid.
        for m in moves:
            if m.get("op") == "bus_add":
                params, _ = D.resolve_params(m, m.get("params"))
                chain = []
                for c in params.get("chain") or []:
                    cp, _ = D.resolve_params(m, c.get("params"))
                    chain.extend(_chain([{**c, "params": cp}], planned=True, move=m["id"]))
                node = {"id": m["target"], "type": "bus", "planned": True,
                        "chain": chain, "planned_moves": []}
                nodes.append(node)
                by_id[node["id"]] = node
                edges.append({"type": "route", "source": node["id"],
                              "target": params.get("output", "bus_mix"), "planned": True, "move": m["id"]})
        for m in moves:
            op, mid, target = m.get("op"), m["id"], m.get("target")
            if op == "master_target":
                target = "master"
            params, _ = D.resolve_params(m, m.get("params"))
            if op == "bus_add":
                continue
            if target not in by_id:
                raise D.DirectionError(f"unknown_target: {target}")
            if op == "send":
                edges.append({"type": "send", "source": target, "target": params["bus"],
                              "level_db": params.get("level_db", -15.0),
                              "pre_fader": bool(params.get("pre_fader", False)), "planned": True, "move": mid})
            elif op == "duck":
                if target not in proj.tracks() or params.get("key") not in proj.tracks():
                    raise D.DirectionError("bad_target: duck requires a track key and target")
                def error(where, code, message):
                    raise D.DirectionError(f"{code}: {where}: {message}")
                K.check_params(params, target, mid, error, tracks=proj.tracks(), buses=proj.buses(),
                               bpm=K.floor_bpm(proj.floor_mxp), has_project=True)
                p = K.full_params(params)
                try:
                    _, release = K.release(params, K.floor_bpm(proj.floor_mxp))
                except ValueError as e:
                    raise D.DirectionError(str(e)) from None
                edges.append(_duck({**p, "track": target, "release": release,
                                    "key_band_hz": [p["key_lo_hz"], p["key_hi_hz"]]},
                                   planned=True, move=mid, direction=doc["id"]))
            elif op == "chain_add":
                by_id[target]["chain"].extend(_chain([{"type": m["processor"], "params": params}],
                                                     planned=True, move=mid))
            elif op == "place":
                derived = D.place_derive(params)
                by_id[target]["planned_moves"].append({"op": op, "move": mid, "params": params,
                                                       "planned": True, "derived": derived["derived"]})
                for subop, processor, subparams in derived["moves"]:
                    if subop == "send":
                        edges.append({"type": "send", "source": target, "target": subparams["bus"],
                                      "level_db": subparams["level_db"], "pre_fader": False,
                                      "planned": True, "move": mid})
                    elif subop == "chain_add":
                        by_id[target]["chain"].extend(_chain([{"type": processor, "params": subparams}],
                                                             planned=True, move=mid))
            else:
                by_id[target]["planned_moves"].append({"op": op, "move": mid, "params": params,
                                                       "planned": True,
                                                       **{k: m[k] for k in ("replaces", "section") if k in m}})
    for edge in edges:
        if edge["source"] not in by_id or edge["target"] not in by_id:
            raise D.DirectionError("unknown_target: wiring edge refers to an unknown node")
    result = _rounded({"kind": "direction_wiring", "variant": vid,
                       "nodes": sorted(nodes, key=lambda n: n["id"]),
                       "edges": sorted(edges, key=lambda e: (e["source"], e["target"], e["type"],
                                                            e["planned"], e.get("direction") or "", e.get("move") or "",
                                                            json.dumps(e, sort_keys=True))),
                       "note": NOTE, "reliability": RELIABILITY})
    return mermaid(result) if format == "mermaid" else result


def mermaid(graph):
    """Encode the same node/edge information with stable, safe Mermaid ids."""
    def label(value):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        # Mermaid entity escapes prevent metadata from becoming diagram syntax.
        return text.replace("&", "#38;").replace('"', "#quot;").replace("<", "#60;").replace(">", "#62;")

    ids = {n["id"]: f"n{i}" for i, n in enumerate(graph["nodes"])}
    lines = ["flowchart LR", "  %% " + json.dumps({k: v for k, v in graph.items()
                                                   if k not in ("nodes", "edges")}, ensure_ascii=False)]
    for node in graph["nodes"]:
        lines.append(f'  {ids[node["id"]]}["{label(node)}"]')
    for edge in graph["edges"]:
        arrow = "-.->" if edge["planned"] or edge["type"] == "duck" else "-->"
        lines.append(f'  {ids[edge["source"]]} {arrow}|"{label(edge)}"| {ids[edge["target"]]}')
    return "\n".join(lines) + "\n"
