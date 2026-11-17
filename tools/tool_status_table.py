"""Regenerate the public tool inventory from specs and runtime declarations."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BEGIN = "<!-- tool-status:begin -->"
END = "<!-- tool-status:end -->"
README = ROOT / "docs/tool_impl/README.md"

# Only the correspondence is curated. Processor flags come exclusively from describe.
SURFACES = {
    "T01-10": "type:band_automation type:gain_automation op:duck_curve",
    "T01-11": "op:ride",
    "T02-02": "type:eq field:channel",
    "T02-07": "cmd:suggest/eq",
    "T02-08": "type:fir_eq cmd:ref/matcheq",
    "T02-09": "cmd:suggest/lowend",
    "T02-10": "type:passive_eq type:inductor_eq type:proportional_eq type:baxandall_eq",
    "T03-11": "type:reverb_hall op:duck",
    "T04-08": "type:tape_delay op:duck",
    "T05-06": "type:ms_gain field:channel",
    "T05-07": "spatial:encode spatial:rotate spatial:decode spatial:convert spatial:info",
    "T07-13": "type:amp_sim type:amp_basic",
    "T08-02": "type:pitch_curve cmd:pitch/notes op:edit_pitch gui:音符表示",
    "T08-08": "type:vocoder type:band_envelope op:vocode",
    "T08-10": "op:edit_stretch",
    "T08-11": "op:edit_stretch_extreme",
    "T08-12": "type:halftime op:edit_varispeed",
    "T09-06": "type:reverse_chunks op:edit_reverse",
    "T09-09": "type:lofi type:noise_bed",
    "T10-03": "op:edit_isolate",
    "T10-10": "type:spectral_repair gui:領域選択",
    "T10-12": "op:breath cmd:query/breaths",
    "T10-14": "op:edit_debleed",
    "T10-15": "type:dewind type:denoise_ml pending:衣擦れ",
    "T10-17": "type:dewow type:azimuth_fix",
    "T10-18": "type:noise_bed cmd:suggest/ambience",
    "T11-01": "op:edit_align_time cmd:query/align_time",
    "T11-02": "op:edit_align_pitch",
    "T11-03": "type:time_align cmd:suggest/align",
    "T11-04": "type:drum_gate cmd:suggest/align",
    "T11-05": "op:drum_replace",
    "T11-06": "cmd:extract/midi",
    "T11-07": "op:edit_quantize",
    "T11-08": "primitive:onsets cmd:query/onsets",
    "T12-01": "type:adaptive_limiter",
    "T12-02": "primitive:mono_loss primitive:correlation_bands cmd:query/mono",
    "T12-04": "type:fade op:edit_fade",
    "T12-05": "op:edit_normalize",
    "T12-06": "op:level_phrases",
    "T12-07": "cmd:preview/codec",
    "T12-08": "cmd:query/meters gui:メータ画面",
    "T12-09": "cmd:ref/balance",
}
REASONS = {
    "linear_eq": "100 Hz・0.3 oct・±24 dB・mid の誤差 ≤0.1 dB が未達（D-9）",
    "ms_gain": "任意 float64 の M/S 往復のビット一致が未達（D-9、丸め）",
    "dereverb": "T20 の30 %短縮と DRR +3 dB の同時合格、乾いた打楽器の RP4 が未達",
    "denoise_ml": "代替実行の Mix Report 接続に core の追加が必要（OQ-4、D-30）",
    "amp_sim": "代替実行の Mix Report 接続に core の追加が必要（OQ-4、D-30）",
}
MISSING_REASONS = {name: "W4d はフェード形状・cross・group の共通口不足で停止、製品op未追加"
                   for name in ("edit_stretch", "edit_stretch_extreme", "edit_varispeed",
                                "edit_reverse", "edit_fade", "edit_normalize")}


def inventory():
    rows = {}
    for path in sorted((ROOT / "docs/tool_impl/spec").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^## (T\d{2}-\d{2}[^\n]*)\n([^\n]*\n){0,3}", text, re.M):
            heading = match[1]
            header = next(line for line in match[0].splitlines()[1:] if "｜" in line)
            for part in re.split(r"\s*／\s*(?=T\d{2}-\d{2})", heading):
                tid, name = part.split(" ", 1)
                surface = SURFACES.get(tid)
                if surface is None:
                    surface = "type:" + re.search(r"`([a-z][a-z0-9_]*)`", header)[1]
                if tid in rows:
                    raise ValueError(f"duplicate tool: {tid}")
                rows[tid] = (name, surface.split())
    if len(rows) != 143:
        raise ValueError(f"expected 143 tools, got {len(rows)}")
    return dict(sorted(rows.items()))


def registry():
    from mankomix.director import commands, direction, query, xops
    from mankomix.cli.main import build_parser

    parser = build_parser()
    def children(p):
        return next(a.choices for a in p._actions if a.__class__.__name__ == "_SubParsersAction")
    spatial = children(children(children(parser)["spatial"])["ambi"])
    return (set(direction.OPS) | set(xops.specs(direction.OPS)),
            {"/".join(c["path"]) for c in commands.declarations()},
            set(query.PRIMITIVES), set(spatial))


def render():
    from mankomix.dsp import processors as P

    ops, commands, primitives, spatial = registry()
    lines = [BEGIN, "## 実装状況（143 件）", "",
             "型の `implemented` は実行時の `describe()` から取得する。op・コマンド・観察量には同名のフラグがないため、登録の有無を表示する。登録は実録音での品質の保証ではない。", "",
             "再生成: `python -X utf8 tools/tool_status_table.py`。検査だけなら `--check`。対応表は同スクリプト、名前と ID は各 spec、型の真偽と表面の在否は実装の宣言を正とする。", "",
             "T12-01 は T01-13 の重複で、同じ `adaptive_limiter` により充足する（件数は143のまま）。GUI の3部分は OQ-3（D-28）で保留。T10-15 の衣擦れ側は再配布可能な OSS 重みが見つからず未実装（D-29）。", "",
             "| ツール ID | 名前 | 実装した表面／予定の表面 | implemented／登録 | 未実装・保留の理由／注記 |",
             "|---|---|---|---|---|"]
    for tid, (name, surfaces) in inventory().items():
        labels, states, reasons = [], [], []
        for item in surfaces:
            kind, value = item.split(":", 1)
            label = {"type": "型", "op": "op", "cmd": "コマンド", "primitive": "観察量", "field": "欄", "gui": "GUI", "pending": "未実装部分", "spatial": "コマンド"}[kind]
            display = "direction " + value.replace("/", " ") if kind == "cmd" else "spatial ambi " + value if kind == "spatial" else value
            labels.append(f"{label} `{display}`")
            if kind == "type":
                flag = P.describe(value)["implemented"]
                states.append(f"`{value}`: `{str(flag).lower()}`")
                if not flag:
                    reasons.append(REASONS[value])
            elif kind in ("op", "cmd", "primitive", "spatial"):
                present = value in {"op": ops, "cmd": commands, "primitive": primitives, "spatial": spatial}[kind]
                states.append(f"`{display}`: {'登録済み' if present else '未登録'}")
                if not present:
                    reasons.append(f"`{display}` は宣言未登録（{MISSING_REASONS.get(value, '該当単位の受入待ち')}）")
            elif kind == "gui":
                states.append("GUI: 保留")
                reasons.append("GUI API の追加が core 差分0と両立しない（OQ-3、D-28）")
            elif kind == "pending":
                reasons.append("衣擦れ側は再配布可能な OSS 重みが見つからず未実装（D-29）")
        if tid == "T12-01":
            reasons.append("T01-13 と同一（重複）")
        lines.append("| " + " | ".join((tid, name, "、".join(labels), "、".join(states) or "—（型なし）", "。".join(dict.fromkeys(reasons)) or "—")) + " |")
    return "\n".join([*lines, END]) + "\n"


def updated(text):
    section = render()
    if BEGIN in text:
        return text[:text.index(BEGIN)] + section + text[text.index(END) + len(END):].lstrip("\n")
    return text.rstrip() + "\n\n" + section


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    old = README.read_text(encoding="utf-8")
    new = updated(old)
    if args.check:
        if old != new:
            print("tool status: stale; regenerate status_table.py")
            return 1
        print("tool status: OK (143 rows)")
    else:
        README.write_text(new, encoding="utf-8", newline="\n")
        print("tool status: regenerated (143 rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
