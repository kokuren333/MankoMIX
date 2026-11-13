#!/usr/bin/env python3
"""Assemble the GUI icon set in gui/public/icons/ (D-067, SPEC section 11.5).

The set has two kinds of icons, both 16x16 PNG pixel art in the 11-colour
"ui-icons" palette of the product family theme "Circuit White / Solder Mask":

* reused  -- copied verbatim from the sibling project CyberSprite (same owner,
             Apache-2.0), file gui/public/icons/<name>.png of that project.
* new     -- MankoMIX-specific icons designed here (DESIGNS below). Their pixels
             are written by the CyberSprite CLI: one project per icon
             (`new --size 16x16 --palette ui-icons.gpl`), one `draw_rows` op,
             `validate`, then `export image` -- the same route CyberSprite uses
             for its own icons ("our own tool draws our own UI").

Usage (from the repository root):

    python -I tools/make_icons.py build [--cybersprite ../CyberSprite]
        Needs a CyberSprite checkout (default: sibling directory, or the
        environment variable CYBERSPRITE_ROOT) and `uv` on PATH. Writes the
        PNGs and manifest.json into gui/public/icons/. The CyberSprite projects
        for the new icons are made in _private/icon_work/ (git-ignored). The
        CyberSprite checkout is only read (the CLI runs with --no-sync).

    python -I tools/make_icons.py check
        Standard library only (CI). Decodes every PNG listed in the manifest
        and checks: 16x16, only palette colours, new icons equal their design
        pixel for pixel, reused icons match the recorded SHA-256, the manifest
        lists exactly the files in the folder, and it holds no absolute path.

Design characters (same alphabet as CyberSprite's icon designs):
    .  transparent      #  ink (1px outline)   k  ink-soft
    d  trace-deep       c  trace (cyan)        s  trace-soft
    w  white            g  warn gold           r  error red
    v  agent violet     p  agent-soft violet
Rules: 1px ink outline, content inside the 14x14 box (1..14), 45 degree or
2:1 steps, no anti-aliasing, status colours only on status icons, and the
meaning is carried by the shape, never by colour alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "gui" / "public" / "icons"
WORK_REL = "_private/icon_work"
MANIFEST = OUT / "manifest.json"

# ui-icons palette (index, name, colour). Identical to CyberSprite ui-icons.gpl.
PALETTE: list[tuple[str, str | None]] = [
    ("transparent", None),
    ("ink", "#0B2A3A"),
    ("trace-deep", "#0A86A8"),
    ("trace", "#19C3E6"),
    ("trace-soft", "#BFEFF9"),
    ("white", "#FFFFFF"),
    ("warn", "#E8A317"),
    ("error", "#E5484D"),
    ("agent", "#7C5CFF"),
    ("ink-soft", "#43606E"),
    ("agent-soft", "#D9D0FF"),
]
SYM = {".": 0, "#": 1, "d": 2, "c": 3, "s": 4, "w": 5, "g": 6, "r": 7, "v": 8, "k": 9, "p": 10}
SYM_DIGIT = ".123456789a"  # draw_rows "sym" format: one character per palette index ("." = transparent)

# Reused icons: MankoMIX name -> CyberSprite file name (gui/public/icons/).
REUSED: dict[str, str] = {
    "play": "play.png",
    "pause": "pause.png",
    "first": "first.png",
    "folder": "folder.png",
    "add": "add.png",
    "remove": "remove.png",
    "lock": "lock.png",
    "link": "link.png",
    "info": "info.png",
    "error": "error.png",
    "warning": "warning.png",
    "validate-ok": "validate-ok.png",
    "agent": "agent.png",
    "human": "human.png",
    "grid": "grid.png",
    "undo": "undo.png",
    "settings": "settings.png",
    "sources": "sources.png",
}

W = H = 16


# ------------------------------------------------------------------ helpers


def _blank() -> list[list[str]]:
    return [["."] * W for _ in range(H)]


def _rows(g: list[list[str]]) -> list[str]:
    return ["".join(r) for r in g]


def _rect(g: list[list[str]], x0: int, y0: int, x1: int, y1: int, fill: str, line: str = "#") -> None:
    """Outlined rectangle, corners inclusive."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            edge = x in (x0, x1) or y in (y0, y1)
            g[y][x] = line if edge else fill


def _hline(g, x0: int, x1: int, y: int, ch: str = "#") -> None:
    for x in range(x0, x1 + 1):
        g[y][x] = ch


def _vline(g, x: int, y0: int, y1: int, ch: str = "#") -> None:
    for y in range(y0, y1 + 1):
        g[y][x] = ch


def _node(g, x0: int, y0: int, fill: str = "c") -> None:
    """4x4 node with cut corners."""
    for dy, row in enumerate([".##.", "#" + fill * 2 + "#", "#" + fill * 2 + "#", ".##."]):
        for dx, ch in enumerate(row):
            if ch != ".":
                g[y0 + dy][x0 + dx] = ch


def _from_rows(rows: list[str]) -> list[str]:
    assert len(rows) == H, len(rows)
    for r in rows:
        assert len(r) == W and set(r) <= set(SYM), r
    return rows


# ------------------------------------------------------------------ designs


def waveform() -> list[str]:
    """Audio waveform: ink bars of varying amplitude around a cyan axis."""
    g = _blank()
    amp = {1: 2, 3: 4, 5: 6, 7: 3, 9: 5, 11: 2, 13: 4}
    for x in range(1, 15):
        if x in amp:
            _vline(g, x, 8 - amp[x], 7 + amp[x])
        else:
            g[7][x] = g[8][x] = "c"
    return _rows(g)


def stem() -> list[str]:
    """Stems: three track lanes, each with a header block and a body."""
    g = _blank()
    for y0 in (1, 6, 11):
        _rect(g, 1, y0, 14, y0 + 3, "c")
        for y in (y0 + 1, y0 + 2):
            g[y][2] = g[y][3] = "w"
            g[y][4] = "#"
    return _rows(g)


def separate() -> list[str]:
    """Stem separation: one block forks into three lanes."""
    g = _blank()
    _rect(g, 1, 3, 5, 12, "c")
    g[7][6] = g[8][6] = "#"
    _vline(g, 7, 2, 13)
    for y in (2, 7, 8, 13):
        g[y][8] = g[y][9] = "#"
    _rect(g, 10, 1, 14, 3, "c")
    _rect(g, 10, 6, 14, 9, "c")
    _rect(g, 10, 12, 14, 14, "c")
    return _rows(g)


def _tray(g) -> None:
    _vline(g, 1, 9, 14)
    _vline(g, 14, 9, 14)
    _hline(g, 1, 14, 14)
    _hline(g, 2, 13, 12, "s")
    _hline(g, 2, 13, 13, "s")


def export() -> list[str]:
    """Export / bounce: an arrow leaving a tray."""
    g = _blank()
    _tray(g)
    rows = {
        1: [(7, 8, "#")],
        2: [(6, 6, "#"), (7, 8, "c"), (9, 9, "#")],
        3: [(5, 5, "#"), (6, 9, "c"), (10, 10, "#")],
        4: [(4, 4, "#"), (5, 10, "c"), (11, 11, "#")],
        5: [(4, 6, "#"), (7, 8, "c"), (9, 11, "#")],
    }
    for y in range(6, 11):
        rows[y] = [(6, 6, "#"), (7, 8, "c"), (9, 9, "#")]
    rows[11] = [(6, 9, "#")]
    for y, runs in rows.items():
        for x0, x1, ch in runs:
            _hline(g, x0, x1, y, ch)
    return _rows(g)


def download() -> list[str]:
    """Download / fetch: an arrow entering a tray."""
    g = _blank()
    _tray(g)
    rows = {1: [(6, 9, "#")]}
    for y in range(2, 6):
        rows[y] = [(6, 6, "#"), (7, 8, "c"), (9, 9, "#")]
    rows[6] = [(4, 6, "#"), (7, 8, "c"), (9, 11, "#")]
    rows[7] = [(4, 4, "#"), (5, 10, "c"), (11, 11, "#")]
    rows[8] = [(5, 5, "#"), (6, 9, "c"), (10, 10, "#")]
    rows[9] = [(6, 6, "#"), (7, 8, "c"), (9, 9, "#")]
    rows[10] = [(7, 8, "#")]
    for y, runs in rows.items():
        for x0, x1, ch in runs:
            _hline(g, x0, x1, y, ch)
    return _rows(g)


def headphones() -> list[str]:
    """Listening: a headband and two ear cups."""
    return _from_rows([
        "................",
        ".....######.....",
        "...##cccccc##...",
        "..#cc######cc#..",
        ".#c##......##c#.",
        ".#c#........#c#.",
        ".#c#........#c#.",
        ".####......####.",
        ".#cc#......#cc#.",
        ".#cc#......#cc#.",
        ".#cc#......#cc#.",
        ".#cc#......#cc#.",
        ".#cc#......#cc#.",
        ".#cc#......#cc#.",
        ".####......####.",
        "................",
    ])


def meter() -> list[str]:
    """Analysis / measurement: three level bars on a base line."""
    g = _blank()
    for x0, top in ((1, 7), (6, 2), (11, 5)):
        _rect(g, x0, top, x0 + 3, 14, "c")
    return _rows(g)


def report() -> list[str]:
    """Mix Report: a page with a folded corner, a title and text lines."""
    g = _blank()
    _hline(g, 2, 10, 1)
    for y in range(2, 14):
        g[y][2] = "#"
    for y in range(5, 14):
        g[y][13] = "#"
    _hline(g, 2, 13, 14)
    for y in (2, 3):
        _hline(g, 3, 9, y, "w")
    g[2][10] = g[2][11] = "#"
    g[3][10] = "#"
    g[3][11] = "s"
    g[3][12] = "#"
    _hline(g, 10, 13, 4)
    _hline(g, 3, 9, 4, "w")
    for y in range(5, 14):
        _hline(g, 3, 12, y, "w")
    _hline(g, 4, 8, 3, "d")
    for y in (6, 8, 10):
        _hline(g, 4, 11, y, "k")
    _hline(g, 4, 8, 12, "k")
    return _rows(g)


def model() -> list[str]:
    """Model (neural network): three nodes joined by edges."""
    g = _blank()
    _node(g, 6, 1)
    _node(g, 1, 11)
    _node(g, 11, 11)
    for x, y in ((6, 5), (5, 6), (5, 7), (4, 8), (4, 9), (3, 10)):
        g[y][x] = "d"
        g[y][15 - x] = "d"
    _hline(g, 5, 10, 12, "d")
    return _rows(g)


def chain() -> list[str]:
    """Processing chain (plan): three processor blocks in series."""
    g = _blank()
    for x0 in (1, 6, 11):
        _rect(g, x0, 5, x0 + 3, 10, "c")
    for x in (5, 10):
        g[7][x] = g[8][x] = "#"
    return _rows(g)


DESIGNS = {
    "waveform": waveform,
    "stem": stem,
    "separate": separate,
    "export": export,
    "download": download,
    "headphones": headphones,
    "meter": meter,
    "report": report,
    "model": model,
    "chain": chain,
}

MEANING = {
    "waveform": "audio waveform (audio material, A/B position)",
    "stem": "stems / multitrack lanes",
    "separate": "stem separation (one source forks into lanes)",
    "export": "export / bounce (arrow out of a tray)",
    "download": "download / fetch a model (arrow into a tray)",
    "headphones": "listening (A/B)",
    "meter": "analysis / measurement bars",
    "report": "Mix Report (page with text lines)",
    "model": "model registry (neural network nodes)",
    "chain": "processing chain / plan",
}


def design_rows(name: str) -> list[str]:
    rows = DESIGNS[name]()
    _from_rows(rows)
    return rows


# ------------------------------------------------------------------ PNG (stdlib)


def decode_png(data: bytes) -> list[list[tuple[int, int, int, int]]]:
    """Decode an 8-bit indexed / RGB / RGBA, non-interlaced PNG into RGBA rows."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    i, idat, plte, trns, ihdr = 8, b"", b"", b"", None
    while i < len(data):
        (n,) = struct.unpack(">I", data[i : i + 4])
        kind, body = data[i + 4 : i + 8], data[i + 8 : i + 8 + n]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
        i += 12 + n
    if ihdr is None:
        raise ValueError("no IHDR")
    w, h, depth, ctype, _c, _f, interlace = ihdr
    if depth != 8 or interlace != 0 or ctype not in (2, 3, 6):
        raise ValueError(f"unsupported PNG format depth={depth} type={ctype} interlace={interlace}")
    bpp = {2: 3, 3: 1, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = w * bpp
    prev = bytearray(stride)
    out = []
    pos = 0
    for _ in range(h):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ftype == 1:
                line[x] = (line[x] + a) & 255
            elif ftype == 2:
                line[x] = (line[x] + b) & 255
            elif ftype == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        row = []
        for x in range(w):
            if ctype == 3:
                k = line[x]
                r, g_, b_ = plte[3 * k : 3 * k + 3]
                alpha = trns[k] if k < len(trns) else 255
                row.append((r, g_, b_, alpha))
            elif ctype == 2:
                row.append((*line[3 * x : 3 * x + 3], 255))
            else:
                row.append(tuple(line[4 * x : 4 * x + 4]))
        out.append(row)
    return out


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def pixel_symbol(px: tuple[int, int, int, int]) -> str:
    """Map an RGBA pixel back to its design character; raises on a foreign colour."""
    r, g_, b_, a = px
    if a == 0:
        return "."
    if a != 255:
        raise ValueError(f"semi-transparent pixel {px}")
    for ch, idx in SYM.items():
        colour = PALETTE[idx][1]
        if colour and _hex_to_rgb(colour) == (r, g_, b_):
            return ch
    raise ValueError(f"colour outside the ui-icons palette: {px}")


def png_symbols(path: Path) -> list[str]:
    px = decode_png(path.read_bytes())
    if len(px) != H or any(len(r) != W for r in px):
        raise ValueError(f"{path.name}: not 16x16")
    return ["".join(pixel_symbol(p) for p in row) for row in px]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ build


def _cs_root(arg: str | None) -> Path:
    root = Path(arg or os.environ.get("CYBERSPRITE_ROOT") or (REPO.parent / "CyberSprite"))
    if not (root / "pyproject.toml").is_file():
        raise SystemExit(f"CyberSprite checkout not found: {root.name or root} (use --cybersprite)")
    return root.resolve()


def _csp(cs: Path, *args: str, stdin: str | None = None) -> dict:
    """Run the CyberSprite CLI with the MankoMIX repository as working directory."""
    cmd = ["uv", "run", "--project", str(cs), "--no-sync", "cybersprite", "--quiet", *args]
    p = subprocess.run(cmd, cwd=REPO, input=stdin, capture_output=True, text=True, encoding="utf-8")
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"cybersprite {' '.join(args)} -> exit {p.returncode}\n{p.stdout}\n{p.stderr}") from None
    if not out.get("ok"):
        raise RuntimeError(f"cybersprite {' '.join(args)} failed: {json.dumps(out)[:2000]}")
    return out


def _write_gpl(path: Path) -> None:
    lines = ["GIMP Palette", "Name: ui-icons (Circuit White / Solder Mask)", "Columns: 8", "#"]
    for name, colour in PALETTE:
        r, g_, b_ = _hex_to_rgb(colour) if colour else (0, 0, 0)
        lines.append(f"{r:3d} {g_:3d} {b_:3d}\t{name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def build_new(cs: Path, name: str, rows: list[str]) -> dict:
    work = REPO / WORK_REL
    proj = work / f"{name}.csprite"
    proj_rel = f"{WORK_REL}/{name}.csprite"
    if proj.exists():
        shutil.rmtree(proj)
    _csp(cs, "new", proj_rel, "--size", "16x16", "--palette", f"{WORK_REL}/ui-icons.gpl", "--name", name, "--layer-name", "icon")
    tx = {
        "label": f"draw icon {name}",
        "ops": [
            {
                "op": "set_palette",
                "args": {"colors": [c or "#000000" for _, c in PALETTE], "names": {str(i): n for i, (n, _) in enumerate(PALETTE)}},
            },
            {
                "op": "draw_rows",
                "args": {
                    "layer": "icon",
                    "frame": 0,
                    "x": 0,
                    "y": 0,
                    "format": "sym",
                    "rows": ["".join(SYM_DIGIT[SYM[c]] for c in r) for r in rows],
                },
            },
        ],
    }
    _csp(cs, "-p", proj_rel, "apply", "-", "--preview", "none", stdin=json.dumps(tx))
    v = _csp(cs, "-p", proj_rel, "validate")["result"]
    out_rel = f"gui/public/icons/{name}.png"
    e = _csp(cs, "-p", proj_rel, "export", "image", "--out", out_rel)["result"]
    f = (e.get("files") or [{}])[0]
    if not (e.get("validation_ok") and e.get("verified") and f.get("width") == 16 and f.get("height") == 16):
        raise RuntimeError(f"{name}: export not verified: {json.dumps(e)[:1000]}")
    return {"validate_ok": v.get("ok"), "errors": v.get("counts", {}).get("error")}


def cmd_build(args: argparse.Namespace) -> int:
    cs = _cs_root(args.cybersprite)
    src_dir = cs / "gui" / "public" / "icons"
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    (REPO / WORK_REL).mkdir(parents=True, exist_ok=True)
    _write_gpl(REPO / WORK_REL / "ui-icons.gpl")

    entries = []
    for name, src in sorted(REUSED.items()):
        s = src_dir / src
        if not s.is_file():
            raise SystemExit(f"CyberSprite icon missing: gui/public/icons/{src} (run `npm run icons` in CyberSprite/gui)")
        shutil.copyfile(s, OUT / f"{name}.png")
        png_symbols(OUT / f"{name}.png")  # palette / size check
        entries.append({
            "name": name,
            "file": f"{name}.png",
            "origin": "reused",
            "source_project": "CyberSprite",
            "source_file": f"gui/public/icons/{src}",
            "source_original": f"assets/ui/icons/{src[:-4]}.csprite",
            "author": "kokuren333 (same owner as MankoMIX)",
            "license": "Apache-2.0",
            "sha256": sha256(OUT / f"{name}.png"),
        })
    for name in sorted(DESIGNS):
        rows = design_rows(name)
        log = build_new(cs, name, rows)
        got = png_symbols(OUT / f"{name}.png")
        if got != rows:
            raise RuntimeError(f"{name}: exported pixels differ from the design")
        entries.append({
            "name": name,
            "file": f"{name}.png",
            "origin": "new",
            "meaning": MEANING[name],
            "drawn_by": "tools/make_icons.py design data, written with the CyberSprite CLI (draw_rows, validate, export image)",
            "author": "kokuren333",
            "license": "Apache-2.0",
            "sha256": sha256(OUT / f"{name}.png"),
        })
        print(json.dumps({"name": name, **log}))
    entries.sort(key=lambda e: e["name"])
    manifest = {
        "schema_version": 1,
        "size": [16, 16],
        "palette": {"name": "ui-icons", "colors": [{"index": i, "name": n, "color": c} for i, (n, c) in enumerate(PALETTE)]},
        "theme": "Circuit White / Solder Mask (CyberSprite SPEC 14.3; MankoMIX D-067)",
        "icons": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"icons: {len(REUSED)} reused + {len(DESIGNS)} new -> gui/public/icons/")
    return 0


# ------------------------------------------------------------------ check


def cmd_check(_args: argparse.Namespace) -> int:
    problems: list[str] = []
    if not MANIFEST.is_file():
        print("gui/public/icons/manifest.json missing", file=sys.stderr)
        return 1
    text = MANIFEST.read_text(encoding="utf-8")
    if ":\\" in text or ":/" in text.replace("://", "") or "/Users/" in text or "/home/" in text:
        problems.append("manifest.json contains an absolute path")
    man = json.loads(text)
    names = [e["name"] for e in man["icons"]]
    want = sorted(set(REUSED) | set(DESIGNS))
    if sorted(names) != want:
        problems.append(f"manifest icons {sorted(names)} != expected {want}")
    files = sorted(p.name for p in OUT.glob("*.png"))
    if files != sorted(f"{n}.png" for n in names):
        problems.append(f"png files {files} do not match the manifest")
    for e in man["icons"]:
        p = OUT / e["file"]
        if not p.is_file():
            continue
        try:
            got = png_symbols(p)
        except ValueError as exc:
            problems.append(f"{e['file']}: {exc}")
            continue
        if sha256(p) != e["sha256"]:
            problems.append(f"{e['file']}: sha256 differs from the manifest")
        if e["origin"] == "new" and got != design_rows(e["name"]):
            problems.append(f"{e['file']}: pixels differ from the design in tools/make_icons.py")
        if e["origin"] == "reused" and e.get("source_project") != "CyberSprite":
            problems.append(f"{e['file']}: reused icon without provenance")
    for p in problems:
        print(p, file=sys.stderr)
    print(f"icons: {len(names)} checked, {len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="copy reused icons and draw the new ones with the CyberSprite CLI")
    b.add_argument("--cybersprite", help="CyberSprite checkout (default: ../CyberSprite or CYBERSPRITE_ROOT)")
    sub.add_parser("check", help="verify gui/public/icons/ against the manifest and the designs (stdlib only)")
    a = ap.parse_args(argv)
    return cmd_build(a) if a.cmd == "build" else cmd_check(a)


if __name__ == "__main__":
    raise SystemExit(main())
