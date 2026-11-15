"""Comparison sheet (対照表, refsheet): a reference work next to this project, same definitions.

``direction ref compare --project <p> --work <slug> [--variant <v>] --out <md>``
puts the measurements of a refstudy (``<kb>/references/works/<slug>/refstudy.md``)
next to the same measurements of this project:

- master vs master: the reference master against **this project's master**
  (the rendered variant), never against the mix bus or a middle stage;
- stems vs stems: only roles both sides have. This side is each track as it
  enters the bus stage, rendered by core's own mix renderer
  (``mixrender.render_mix(..., stems_out=...)``: cleaned clips -> track chain
  -> fader and gain automation -> pan and width), summed per role. Send
  returns, bus chains and the master stage are not in the stems (a bus mixes
  several tracks, so its output cannot be split per role); they show up only
  in the master vs master table;
- relations vs relations (lead vs the rest, low end of drums and bass, band
  owners);
- roles only one side has go to a separate table ("移せない特徴");
- one row compares the HF noisiness (spectral flatness).

Columns are only: reference value / this value / difference / comparison
conditions. There is no "target" or "recommended" column: a difference is a
question, not a target (U-5). This side is measured by the same functions as
the refstudy and passed through the same rendering and parsing, so both sides
share definitions and rounding by construction.

Read-only: nothing in the project is written (the output must be outside the
project folder), and nothing is written in the kb either.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np


from . import refstudy as RS

DIFF_NOTE = "差 = こちら − 参照"

# (key, label, decimals, group)  group: level | spectral | space | hf | dyn
MASTER_ROWS = (
    ("lufs_i", "積分ラウドネス LUFS-I", 2, "level"),
    ("true_peak_dbtp", "トゥルーピーク dBTP", 2, "level"),
    ("short_p95", "短期ラウドネス p95 LUFS", 2, "level"),
    ("plr_db", "PLR dB", 2, "dyn"),
    ("lra_lu", "LRA LU", 2, "dyn:lra"),
    ("short_range_lu", "短期ラウドネスの幅 p95−p10 LU", 2, "dyn:range"),
    ("crest_db", "広帯域クレスト dB", 2, "dyn"),
    ("near_peak_fraction", "ピーク −1 dB 以内の割合", 5, "dyn"),
    ("tilt_db_per_oct", "LTAS の傾き dB/oct", 2, "ltas"),
    *[(f"band_db:{b}", f"帯域比 dB `{b}`", 1, "hf" if b == "air" else "spectral") for b in RS.BAND_IDS],
    ("side_ratio_db", "全帯域 S/M dB", 2, "space"),
    ("correlation", "全帯域 相関", 3, "space"),
    *[(f"side_db:{b}", f"帯域 S/M dB `{b}`", 1, "space") for b in RS.BAND_IDS],
    ("mono_boundary_hz", "低域のモノ化の境界 Hz", 0, "space"),
    ("air_fraction", "エア帯（6–20 kHz）の比", 4, "hf"),
    ("rolloff_hz", "ロールオフ Hz（— = 全帯域）", 0, "hf"),
)
STEM_ROWS = (     # (key, label, decimals, group, note)
    ("rel_lu", "和との差 LU", 1, "level", "各側のステム和に対する相対値"),
    ("lr_diff_db", "L/R 差 dB（正 = 左）", 1, "space", "こちらはパン・幅の後（センド戻りを除く）"),
    ("side_ratio_db", "S/M dB", 1, "space", "こちらはパン・幅の後（センド戻りを除く）"),
    ("correlation", "相関", 3, "space", "こちらはパン・幅の後（センド戻りを除く）"),
    ("crest_db", "クレスト dB", 1, "dyn", "ステム単体"),
    ("present_fraction", "在区間の割合", 2, "level", "各側の区間で数える（区分が違う）"),
)
GROUP_NOTE = {
    "level": "絶対値（レベル合わせなし）",
    "dyn": "マスターどうし（段を揃える）",
    # LRA and p95-p10 differ only by the gate; both are on the 3 s short-term loudness (P-03)
    "dyn:lra": "マスターどうし（段を揃える）。EBU R128 の LRA: 短期ラウドネスに絶対ゲート −70 LUFS と"
               "相対ゲート −20 LU を掛けた後の p95 − p10",
    "dyn:range": "マスターどうし（段を揃える）。短期ラウドネスに絶対ゲート −70 LUFS だけを掛けた p95 − p10"
                 "（相対ゲートなし。−20 LU より静かな短期区間が無ければ LRA と同じ値）",
    "ltas": "−23 LUFS にレベル合わせ（R-01）",
    "spectral": "エネルギー比（レベルに依らない）",
    "space": "マスターどうし",
    "hf": "エネルギー比・高域",
}


class RefSheetError(ValueError):
    pass


def _sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# this project's side (read the project like the dossier does)
# ---------------------------------------------------------------------------

def project_side(project: str | Path, variant: str | None, kb_section_audio: bool = True) -> dict:
    """Measure this project's master render and stems with the refstudy functions; return parsed values."""
    from . import direction as D
    from . import dossier as DS
    root = Path(project)
    if not (root / "project.json").is_file():
        raise RefSheetError("no project.json in the project folder")
    try:
        ctx = DS._Ctx(root, variant, None, None, False)
    except KeyError as e:
        raise RefSheetError(str(e).strip("'\"")) from None
    vid = ctx.variant_id
    info: dict[str, Any] = {"variant": vid, "project_sha16": ctx.sources.get("project.json"), "notes": []}
    secs = [{"id": str(s.get("id")), "start_s": float(s["start_s"]), "end_s": float(s["end_s"]), "label": s.get("label")}
            for s in ctx.sections() if s.get("start_s") is not None and s.get("end_s") is not None]
    study: dict[str, Any] = {"work": "this", "origin": "measured", "lossy": False, "materials": [],
                             "sections_source": "project" if secs else "auto", "section_list": secs}
    mfile = D._render_file(root, vid) if vid else None
    if mfile is not None:
        x, sr = RS.read_audio(mfile)
        info["master_sha256"] = _sha_file(mfile)
        if not secs:
            secs = RS.auto_sections(x, sr)
            study["section_list"] = secs
        mm = RS.master_measure(x, sr, secs)
        summ = RS.section_summary(mm["sections"])
        study.update(master=mm, summary=summ, signs=RS.apply_caps(RS.signs(mm, summ), lossy=False, separated=False))
        del x
    else:
        info["master_sha256"] = None
        info["notes"].append("こちらのマスター（renders/<変種>/ の hires_native）が無い: マスターどうしの列は空欄"
                             "（先に render する）")
    by_role, sr0, facts = _project_stems(root, vid)
    if by_role:
        stem_secs = secs if secs else RS.auto_sections(RS._sum(list(by_role.values())), sr0)
        study["stems"] = {"assignment": [{"role": r, "count": facts["counts"][r], "sources": ["project"],
                                          "sha16": []} for r in sorted(by_role)],
                          "excluded": [], "measure": RS.stems_measure(by_role, sr0, stem_secs)}
        if not secs:
            study["section_list"] = stem_secs
        info["stems"] = facts
    else:
        info["notes"].append(f"こちらのステムを描画できない（{facts.get('error')}）: ステムどうしの列は空欄")
    del by_role
    md = RS.render(study)
    info["master_contrast_lu"] = _sign_contrast(md) if mfile is not None else None
    return {"info": info, "values": RS.study_values(md)}


def _project_stems(root: Path, vid: str | None) -> tuple[dict[str, np.ndarray] | None, int | None, dict]:
    """Per-role signals of this project as they enter the bus stage, rendered by core (read-only).

    ``mixrender.render_mix(stems_out=...)`` yields every audible track after its
    cleaned clips, track chain, fader / gain automation and pan / width, i.e.
    the signal the track adds to its output bus. Tracks are summed per role.
    The cleanup caches must already be valid: core would regenerate a missing
    cache inside the project, and this sheet never writes into the project.
    """
    from mankomix.core import cleanstage
    from mankomix.core import mixrender as MR
    from mankomix.core.errors import MankoError
    from mankomix.core.project import Project
    try:
        pobj = Project.open(root)
        data, _ = MR.effective_data(pobj, variant_id=vid)
        tracks = MR.stem_tracks(data)
        for t in tracks:
            for c in t.get("clips") or []:
                aid = c.get("asset")
                e = cleanstage.track_cleanup_entry(t, aid)
                if e is None:
                    continue
                asha = pobj.asset(aid).get("sha256") or ""
                if e.get("asset_sha256") not in (None, asha) or \
                        cleanstage._cache_valid(pobj, asha, str(e.get("plan_hash"))) is None:
                    return None, None, {"error": "整音の cache が無いか古い。先に clean apply／render する"}
        stems: dict[str, np.ndarray] = {}
        _, sr, rec = MR.render_mix(pobj, variant_id=vid, stems_out=stems, measure=False)
    except MankoError as e:
        return None, None, {"error": str(e)}
    role = {t["id"]: str(t.get("role") or "other") for t in tracks}
    groups: dict[str, list[np.ndarray]] = {}
    for tid in sorted(stems):
        groups.setdefault(role.get(tid, "other"), []).append(stems.pop(tid))
    if not groups:
        return None, None, {"error": "聞こえるトラックが無い"}
    mix_id = MR._mix_bus_id(data)
    heard = [t for t in rec["tracks"] if t.get("audible")]
    facts = {
        "counts": {r: len(v) for r, v in groups.items()},
        "tracks": len(heard),
        "muted": sorted(t["id"] for t in rec["tracks"] if not t.get("audible")),
        "chains": sum(1 for t in heard if t.get("chain")),
        "panned": sum(1 for t in heard if (t.get("pan") or {}).get("position")
                      or (t.get("pan") or {}).get("width") != 1.0),
        "automation": sum(1 for t in heard if t.get("automation")),
        "send_buses": sorted({s["bus"] for t in heard for s in t.get("sends") or []}),
        "sub_bus_tracks": sum(1 for t in heard if t.get("output") != mix_id),
    }
    by_role = {r: RS._sum(v) for r, v in sorted(groups.items())}
    return by_role, int(sr), facts


def _stem_condition(info: dict) -> str:
    """Comparison condition of the stems tables: what this side's stems contain."""
    f = info.get("stems") or {}
    s = (f"参照 = 配布ステム（処理済みの書き出し）／こちら = 変種 `{info.get('variant') or '—'}` の各トラックが"
         "バスに入る直前の信号を役割ごとに合算（コアの描画 `mixrender.render_mix` のトラック出力: 整音後 → "
         "トラックの処理チェーン → フェーダー・オートメーション → パン・幅。"
         f"聞こえるトラック {f.get('tracks', 0)} 本、うち処理チェーンあり {f.get('chains', 0)}・"
         f"パン／幅が中央・1 以外 {f.get('panned', 0)}・オートメーションあり {f.get('automation', 0)}）")
    excl = "バスの処理・マスター段は含まない"
    if f.get("send_buses"):
        excl = ("センド戻り（" + ", ".join(f"`{b}`" for b in f["send_buses"]) + "）・" + excl
                + "（バスは複数トラックを混ぜるので役割に分けられない。これらはマスターどうしの列にだけ現れる）")
    if f.get("sub_bus_tracks"):
        excl += f"。サブバス経由のトラック {f['sub_bus_tracks']} 本はサブバスの処理の前"
    if f.get("muted"):
        excl += f"。ミュート中のトラック {len(f['muted'])} 本は含まない"
    return s + "; " + excl


def _sign_contrast(md: str) -> float | None:
    """Loudest minus quietest section loudness, as the RS-CONTRAST sign states it (refstudy §5).

    Read from the evidence of the sign (rounded once, from the unrounded section
    loudness), not recomputed from the §4 table whose LUFS-I are rounded to 0.1.
    """
    for r in RS.parse_tables(md).get("5", []):
        if r.get("規則") == "`RS-CONTRAST`":
            for part in str(r.get("根拠の測定値") or "").split(";"):
                k, _, v = part.partition("=")
                if k.strip() == "ラウドネス差 LU":
                    return RS.cell_num(v)
    return None


# ---------------------------------------------------------------------------
# the sheet
# ---------------------------------------------------------------------------

def _diff(a: Any, b: Any, d: int) -> str:
    fa, fb = RS._f(a), RS._f(b)
    if fa is None or fb is None:
        return "—"
    return RS._num(fb - fa, d, sign=True)


def _caps(group: str, ref: dict, stems: str | None = None) -> list[str]:
    out = []
    if ref.get("lossy") and group == "hf":
        out.append("参照は非可逆: 確度上限 low")
    if ref.get("origin") == "separated":
        out.append("参照は分離由来: 確度上限 medium")
    if stems:
        out.append(stems)
    return out


def build_sheet(project: str | Path, work: str, *, variant: str | None = None,
                kb_root: str | Path = RS.DEFAULT_KB) -> dict:
    RS.check_slug(work)
    rs_path = RS.work_dir(Path(kb_root), work) / "refstudy.md"
    if not rs_path.is_file():
        raise RefSheetError(f"no refstudy for work_{work} in the kb (run: mankomix direction ref study --work {work} ...)")
    ref_md = rs_path.read_text(encoding="utf-8")
    ref = RS.study_values(ref_md)
    ref_sha = hashlib.sha256(rs_path.read_bytes()).hexdigest()
    ours = project_side(project, variant)
    me, info = ours["values"], ours["info"]
    has_ref_master = "## 3. マスター: 全体" in ref_md
    has_our_master = info.get("master_sha256") is not None
    lines = [f"# 対照表（refsheet）: work_{work} × こちら（変種 `{info['variant'] or '—'}`）", "",
             "<!-- 機械生成（mankomix direction ref compare）。手で編集しない。 -->", "",
             f"- 参照: `work_{work}` の refstudy（SHA-256 `{ref_sha}`）、origin `{ref.get('origin') or '—'}`"
             f"{'、非可逆音源' if ref.get('lossy') else ''}",
             f"- こちら: project.json `{info.get('project_sha16') or '—'}`、マスター "
             + (f"`{info['master_sha256']}`" if has_our_master else "なし"),
             f"- 列は 参照の値／こちらの値／差／比較条件 だけ（{DIFF_NOTE}）。目標・推奨の列は作らない。"
             "差は埋めるべき目標ではなく問い（U-5）。一度に比べる問いは 1 つ（SPEC §4.6）",
             "- 採る特徴はこの曲の素材での手に翻訳し、主張は床に対して立てる（U-6）。参照との距離は参考値（U-7）",
             ""]
    for n in info.get("notes") or []:
        lines.append(f"- 注: {n}")
    if info.get("notes"):
        lines.append("")
    # 1. master vs master
    lines += ["## 1. マスターどうし", ""]
    if not has_ref_master:
        lines += ["- 参照にマスターがない（refstudy にマスターの測定がない）", ""]
    else:
        rows = []
        for key, label, d, group in MASTER_ROWS:
            a, b = ref.get(key), me.get(key) if has_our_master else None
            cond = "; ".join([GROUP_NOTE[group], *_caps(group, ref)])
            rows.append([f"`{key}` {label}", RS._num(a, d), RS._num(b, d), _diff(a, b, d), cond])
        rc, oc = _sign_contrast(ref_md), info.get("master_contrast_lu")
        rows.append(["`contrast_lu` 区間コントラスト（最大 − 最小区間の LUFS-I）LU", RS._num(rc, 2), RS._num(oc, 2),
                     _diff(rc, oc, 2), "両側とも兆候 `RS-CONTRAST` の根拠値（丸め前の区間ラウドネスの差）。"
                     "区間の区分が両者で違う（参照: refstudy §4、こちら: ミックス提案の区間）"])
        lines += RS._table(["量", "参照", "こちら", "差", "比較条件"], rows)
        lines += [""]
    # 2. stems vs stems
    rs_, ms_ = ref.get("stems") or {}, me.get("stems") or {}
    both = sorted(set(rs_) & set(ms_))
    lines += ["## 2. ステムどうし（役割が両方にあるものだけ）", ""]
    if both:
        lines += ["- 比較条件（全行共通）: " + "; ".join(_caps("level", ref, stems=_stem_condition(info))),
                  "- 和との差: 各側のステム和に対する役割の LU 差。在区間の割合は各側の区間で数える（区分は両者で違う）", ""]
        for r in both:
            rows = []
            for key, label, d, group, note in STEM_ROWS:
                a, b = rs_[r].get(key), ms_[r].get(key)
                rows.append([f"`{key}` {label}", RS._num(a, d), RS._num(b, d), _diff(a, b, d),
                             "; ".join([note, *_caps(group, ref)])])
            for bid in RS.BAND_IDS:
                key = f"band_db:{bid}"
                a, b = rs_[r].get(key), ms_[r].get(key)
                if a is None and b is None:
                    continue
                g = "hf" if bid == "air" else "spectral"
                rows.append([f"`{key}` 帯域比 dB", RS._num(a, 1), RS._num(b, 1), _diff(a, b, 1),
                             "; ".join([GROUP_NOTE[g], *_caps(g, ref)])])
            lines += [f"### 2.{both.index(r) + 1} `{r}`", ""]
            lines += RS._table(["量", "参照", "こちら", "差", "比較条件"], rows)
            lines += [""]
    else:
        lines += ["- 両方にある役割がない（どちらかにステムがない）", ""]
    # 3. relations
    lines += ["## 3. ステム間の関係どうし", ""]
    rows = []
    a, b = ref.get("lead_vs_rest_lu"), me.get("lead_vs_rest_lu")
    if a is not None or b is not None:
        rows.append(["`lead_vs_rest_lu` 主役対伴奏 LU（全体）", RS._num(a, 2), RS._num(b, 2), _diff(a, b, 2),
                     "; ".join(["各側のステムで計算（曲資料 §5 と同じ定義）", *_caps("level", ref)])])
    for bid in sorted(set(ref.get("low_share") or {}) | set(me.get("low_share") or {})):
        a, b = (ref.get("low_share") or {}).get(bid), (me.get("low_share") or {}).get(bid)
        rows.append([f"`low_share:{bid}` drums の取り分（drums と bass）", RS._num(a, 3), RS._num(b, 3), _diff(a, b, 3),
                     "; ".join(["キック単独のステムがなければドラムに含まれる", *_caps("level", ref)])])
    for bid in RS.BAND_IDS:
        a, b = ref.get(f"owners:{bid}"), me.get(f"owners:{bid}")
        if a is None and b is None:
            continue
        rows.append([f"`owners:{bid}` 帯域担当数", RS._num(a, 0), RS._num(b, 0), _diff(a, b, 0),
                     "; ".join(["P-22 規則（`knowledge/masking_model.json`）。編成の違いを含む", *_caps("level", ref)])])
    if rows:
        lines += RS._table(["量", "参照", "こちら", "差", "比較条件"], rows)
    else:
        lines.append("- 比べられる関係がない")
    lines += [""]
    # 4. untransferable
    only_ref, only_me = sorted(set(rs_) - set(ms_)), sorted(set(ms_) - set(rs_))
    lines += ["## 4. 移せない特徴（役割が片方にしかない）", ""]
    if (only_ref or only_me) and rs_ and ms_:
        rows = [[f"`{r}`", "あり", "なし", RS._num(rs_[r].get("rel_lu"), 1), "編成差: こちらに無い役割（参照の和との差 LU）"]
                for r in only_ref]
        rows += [[f"`{r}`", "なし", "あり", RS._num(ms_[r].get("rel_lu"), 1), "編成差: 参照に無い役割（こちらの和との差 LU）"]
                 for r in only_me]
        lines += RS._table(["役割", "参照", "こちら", "和との差 LU", "注記"], rows)
    elif not (rs_ and ms_):
        lines.append("- ステムが片方にしかないため判定しない")
    else:
        lines.append("- なし（役割の構成が一致）")
    lines += [""]
    # 5. HF noisiness
    lines += ["## 5. 高域の雑音性", ""]
    a, b = ref.get("flatness"), me.get("flatness") if has_our_master else None
    cond = "; ".join(["マスターどうし。生成物特有の劣化が残っているかを、きれいな実物と比べて見る。"
                      "対処は既存の整音段（`cleanup_override`）の仕事", *_caps("hf", ref)])
    lines += RS._table(["量", "参照", "こちら", "差", "比較条件"],
                       [["`flatness` 高域（10–14 kHz）の平坦度", RS._num(a, 4), RS._num(b, 4), _diff(a, b, 4), cond]])
    lines += ["", "## 付記", "",
              "- 参照の値は refstudy の表からの読み取り（書き写し）。こちらの値は同じ関数・同じ丸めで測った",
              "- この表は読み取りのみで作る。プロジェクトも kb も書き換えない", ""]
    md = "\n".join(lines)
    return {"markdown": md, "sha256": hashlib.sha256(md.encode("utf-8")).hexdigest(), "refstudy_sha256": ref_sha,
            "variant": info["variant"], "roles_both": both, "roles_ref_only": only_ref, "roles_this_only": only_me,
            "master_compared": bool(has_ref_master and has_our_master)}


def compare_command(project: str | Path, work: str, out: str | Path, *, variant: str | None = None,
                    kb_root: str | Path = RS.DEFAULT_KB) -> dict:
    outp = Path(out)
    if _within(outp, Path(project)):
        raise RefSheetError("--out must be outside the project folder (ref compare never writes into the project)")
    res = build_sheet(project, work, variant=variant, kb_root=kb_root)
    outp.parent.mkdir(parents=True, exist_ok=True)
    data = res["markdown"].encode("utf-8")
    old = outp.read_bytes() if outp.is_file() else None
    if old != data:
        outp.write_bytes(data)
    return {"kind": "refsheet", "work": f"work_{work}", "variant": res["variant"], "refsheet_sha256": res["sha256"],
            "refstudy_sha256": res["refstudy_sha256"], "master_compared": res["master_compared"],
            "roles_both": res["roles_both"], "roles_ref_only": res["roles_ref_only"],
            "roles_this_only": res["roles_this_only"], "changed": old != data}
