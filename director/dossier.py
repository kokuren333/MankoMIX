"""Song dossier (曲資料): a deterministic, read-only Markdown digest of a project.

The dossier lays out what the project files already know about a song so a
director can read the song without opening the raw files. It lists facts and
does not weight them (no scores are added, no ordering by importance except
where a source already orders them, which is stated).

Inputs (all read-only): ``project.json``, ``analysis/ast_*.json`` and
``analysis/stem_sum.json``, the applied mix proposal (``cache/proposals/mxp_*``)
and master proposal (``mpl_*``), ``reports/verify_<variant>.json``, the
knowledge and profile data of the repository, the processor registry of
``dsp/processors.py``, and the cleaned stem audio (``cache/clean``) for the
per-section table. Nothing is written into the project; no LLM is involved.

Paths in the output are project-relative; the project folder name, absolute
paths and lyrics are never printed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from mankomix import repo_data_root
from mankomix.core import audio_io
from mankomix.core.cleanstage import applied_entry, cache_rel
from mankomix.core.measure import loudness as L
from mankomix.dsp import processors as P

from . import kb as kbmod

DOSSIER_VERSION = 2
ABSENT_LUFS = -60.0           # a stem counts as absent in a section below this integrated loudness
MAX_KB_CARDS = 8               # §10.1 only; the theory shelf (§10.2) lists every active theory card
_WORK_ID_RE = re.compile(r"^work_[a-z0-9][a-z0-9_-]*$")

HEADINGS = (
    "1. 依頼・媒体・床の指定",
    "2. ステム目録",
    "3. セクション表",
    "4. 測定ベクトル",
    "5. ステム間の関係",
    "6. 制約までの余裕",
    "7. ジャンル prior",
    "8. 抽象プロセッサと宣言範囲",
    "9. 床ミックスの構成",
    "10. 過去知見（kb 抜粋）",
    "11. 床の結果（参考）",
    "付記: 載せていない項目",
)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _num(v: Any, d: int = 2, sign: bool = False) -> str:
    if v is None or isinstance(v, bool):
        return "—"
    if isinstance(v, (int, float)):
        f = float(v)
        if not math.isfinite(f):
            return "—"
        if abs(f) < 0.5 * 10.0 ** (-d):
            f = 0.0                      # no "-0.00"
        return f"{f:+.{d}f}" if sign else f"{f:.{d}f}"
    return str(v)


def _c(v: Any) -> str:
    """Compact number: up to 3 decimals, trailing zeros removed."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "—" if v is None else str(v)
    s = _num(v, 3)
    return s.rstrip("0").rstrip(".") if "." in s else s


def _cell(v: Any) -> str:
    s = "—" if v is None or v == "" else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _table(head: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        out.append("| " + " | ".join(_cell(c) for c in r) + " |")
    return out


def _param_text(params: dict | None) -> str:
    if not params:
        return ""
    parts = []
    for k in sorted(params):
        v = params[k]
        if isinstance(v, float):
            v = _num(v, 2).rstrip("0").rstrip(".") if abs(v) < 1e6 else v
        elif isinstance(v, list):
            v = "[" + ",".join(_num(x, 2).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v) + "]"
        parts.append(f"{k}={v}")
    return ", ".join(parts)


def _range_text(r: Any) -> str:
    if isinstance(r, list) and len(r) == 2:
        return f"[{_c(r[0]) if r[0] is not None else '−∞'}, {_c(r[1]) if r[1] is not None else '+∞'}]"
    if isinstance(r, dict):
        return "; ".join(f"{k} {_range_text(v)}" for k, v in sorted(r.items()) if k != "source") or "—"
    return "—"


def _edge_distance(value: Any, target: Any) -> str:
    """Signed distance to the nearest range end: negative = inside by that much, positive = outside."""
    if not isinstance(value, (int, float)) or not isinstance(target, list) or len(target) != 2:
        return "—"
    lo, hi = target
    v = float(value)
    ds = []
    if lo is not None:
        ds.append(lo - v)
    if hi is not None:
        ds.append(v - hi)
    if not ds:
        return "—"
    worst = max(ds)
    return ("外 " if worst > 0 else "内 ") + _num(abs(worst), 2)


def _short(track_id: str | None) -> str:
    return track_id or "—"


# ---------------------------------------------------------------------------
# project context
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, root: Path, variant: str | None, song: str | None, kb_root: Path | None,
                 section_audio: bool):
        self.root = root
        self.song = song
        self.kb_root = kb_root
        self.section_audio = section_audio
        self.omitted: list[str] = []
        self.refs: list[str] = []
        self.ref_kb_root: Path | None = None
        self.sources: dict[str, str] = {}
        pj = root / "project.json"
        self.project = _read_json(pj)
        if not isinstance(self.project, dict):
            raise FileNotFoundError("project.json not found or unreadable")
        self.sources["project.json"] = hashlib.sha256(pj.read_bytes()).hexdigest()[:16]
        vs = self.project.get("variants") or []
        if variant:
            self.variant = next((v for v in vs if v.get("id") == variant), None)
            if self.variant is None:
                raise KeyError(f"unknown variant: {variant}")
        else:
            self.variant = vs[0] if vs else None
        self.variant_id = (self.variant or {}).get("id")
        self.proposals = self._load_proposals()
        self.mxp = self._pick_mix()
        self.mpl = self._pick_master()
        self.verify = None
        if self.variant_id:
            vp = root / "reports" / f"verify_{self.variant_id}.json"
            self.verify = _read_json(vp)
            if self.verify is not None:
                self.sources[vp.relative_to(root).as_posix()] = hashlib.sha256(vp.read_bytes()).hexdigest()[:16]
        self.tracks = [t for t in self.project.get("tracks") or [] if t.get("kind", "audio") == "audio"]
        self.assets = {a["id"]: a for a in self.project.get("assets") or [] if a.get("id")}
        self.analysis = {}
        for aid, ent in sorted((self.project.get("analysis_index") or {}).items()):
            p = root / str(ent.get("path") or "")
            data = _read_json(p) if ent.get("path") else None
            if isinstance(data, dict):
                self.analysis[aid] = data.get("vector") or {}
                self.sources[p.relative_to(root).as_posix()] = str(ent.get("sha256") or "")[:16]
        data_root = repo_data_root()
        self.genre_priors = _read_json(data_root / "knowledge" / "genre_priors.json") or {}
        self.thresholds = _read_json(data_root / "knowledge" / "thresholds.json") or {}
        self.cleanup_policy = _read_json(data_root / "knowledge" / "cleanup_policy.json") or {}
        self.media_profiles = _read_json(data_root / "profiles" / "media_profiles.json") or {}

    def _load_proposals(self) -> list[dict]:
        d = self.root / "cache" / "proposals"
        out = []
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                data = _read_json(p)
                if isinstance(data, dict):
                    data = dict(data)
                    data["_file"] = p.relative_to(self.root).as_posix()
                    data["_sha"] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                    out.append(data)
        return out

    def _pick(self, stage: str, wanted: str | None) -> dict | None:
        cands = [p for p in self.proposals if p.get("stage") == stage]
        if wanted:
            for p in cands:
                if p.get("proposal_id") == wanted:
                    return p
        applied = [p for p in cands if p.get("status") == "applied"]
        applied.sort(key=lambda p: (str(p.get("proposed_at") or ""), str(p.get("proposal_id") or "")))
        return applied[-1] if applied else None

    def _pick_mix(self) -> dict | None:
        wanted = ((self.project.get("mix") or {}).get("applied") or {}).get("proposal_id")
        p = self._pick("mix", wanted)
        if p:
            self.sources[p["_file"]] = p["_sha"]
        else:
            self.omitted.append("適用済みのミックス提案（mxp_）がない: セクション、マスキング、帯域担当、床ミックスの決定は空欄")
        return p

    def _pick_master(self) -> dict | None:
        wanted = ((self.variant or {}).get("master") or {}).get("proposal_id")
        p = self._pick("master", wanted)
        if p and self.variant_id and p.get("variant") not in (None, self.variant_id):
            p = None
        if p:
            self.sources[p["_file"]] = p["_sha"]
        else:
            self.omitted.append("適用済みのマスター提案（mpl_）がない: 計画段の S-08・R-14 は空欄")
        return p

    def profile(self, pid: str | None) -> dict | None:
        for p in self.media_profiles.get("profiles") or []:
            if p.get("id") == pid:
                return p
        return None

    def threshold(self, group: str, key: str) -> Any:
        v = ((self.thresholds.get(group) or {}).get(key) or {})
        return v.get("value") if isinstance(v, dict) else v

    def track_asset(self, t: dict) -> str | None:
        clips = t.get("clips") or []
        return clips[0].get("asset") if clips else None

    def sections(self) -> list[dict]:
        return list((self.mxp or {}).get("sections") or [])


# ---------------------------------------------------------------------------
# sections from audio (read-only)
# ---------------------------------------------------------------------------

def _clean_audio_path(ctx: _Ctx, asset_id: str) -> tuple[Path | None, str]:
    entry = applied_entry(ctx.project, asset_id)
    asha = (ctx.assets.get(asset_id) or {}).get("sha256") or ""
    if entry is not None and entry.get("plan_hash") and asha:
        p = ctx.root / cache_rel(asha, entry["plan_hash"])
        if p.is_file():
            return p, "cleaned"
    a = ctx.assets.get(asset_id) or {}
    if a.get("path") and not a.get("linked"):
        p = ctx.root / a["path"]
        if p.is_file():
            return p, "asset"
    return None, "missing"


def _lufs(x: np.ndarray, sr: int) -> float | None:
    if x.shape[0] < int(0.4 * sr):
        return None
    v = L.integrated(x, sr)
    return float(v) if v is not None and math.isfinite(v) else None


def _section_audio(ctx: _Ctx) -> dict | None:
    secs = ctx.sections()
    if not secs or not ctx.section_audio:
        if not ctx.section_audio:
            ctx.omitted.append("セクション別の音声測定（--no-section-audio 指定）")
        return None
    per_track: dict[str, list[float | None]] = {}
    kinds: dict[str, str] = {}
    total = None
    sr0 = None
    for t in ctx.tracks:
        aid = ctx.track_asset(t)
        if not aid:
            continue
        p, kind = _clean_audio_path(ctx, aid)
        if p is None:
            kinds[t["id"]] = "missing"
            continue
        x, sr = audio_io.read(p, dtype="float32")
        x = np.asarray(x, dtype=np.float64)
        if x.ndim == 1:
            x = x[:, None]
        if sr0 is None:
            sr0 = sr
        elif sr != sr0:
            kinds[t["id"]] = "rate_mismatch"
            continue
        kinds[t["id"]] = kind
        vals = []
        for s in secs:
            a, b = int(round(float(s["start_s"]) * sr)), int(round(float(s["end_s"]) * sr))
            vals.append(_lufs(x[a:b], sr))
        per_track[t["id"]] = vals
        g = 10.0 ** (float(t.get("gain_db") or 0.0) / 20.0)
        y = x if x.shape[1] == 2 else np.repeat(x[:, :1], 2, axis=1)
        if total is None:
            total = np.zeros_like(y)
        n = min(total.shape[0], y.shape[0])
        total[:n] += y[:n] * g
        del x, y
    if total is None or sr0 is None:
        ctx.omitted.append("セクション別の音声測定（整音済みステムも素材も読めない）")
        return None
    sums = []
    for s in secs:
        a, b = int(round(float(s["start_s"]) * sr0)), int(round(float(s["end_s"]) * sr0))
        seg = total[a:b]
        st = L.short_term(seg, sr0) if seg.shape[0] >= 3 * sr0 else np.array([])
        st = st[np.isfinite(st)] if st.size else st
        sums.append({"lufs": _lufs(seg, sr0), "st_max": float(st.max()) if st.size else None})
    return {"per_track": per_track, "kinds": kinds, "sums": sums}


# ---------------------------------------------------------------------------
# sections of the document
# ---------------------------------------------------------------------------

def _s1(ctx: _Ctx) -> list[str]:
    v = ctx.variant or {}
    master = v.get("master") or {}
    prof = ctx.profile(master.get("profile"))
    obj = ctx.project.get("objective") or {}
    blend = "+".join(f"{b.get('id')}:{_num(b.get('weight'), 2)}" for b in obj.get("blend") or []) or "—"
    out = []
    if ctx.song:
        out.append(f"- 曲: `{ctx.song}`（スラグで指す）")
    out += [
        f"- ジャンル宣言: `{ctx.project.get('genre') or '—'}`",
        "- 依頼の原文: 曲資料には載せない（依頼ごとに指揮書の `request.utterance` に記す。この曲資料は依頼をまたいで共通）",
        f"- 変種: `{ctx.variant_id or '—'}` / プロファイル `{master.get('profile') or '—'}` / 経路 `{master.get('route') or '—'}`",
    ]
    outs = v.get("outputs") or []
    if outs:
        out.append("- 納品形式: " + ", ".join(f"`{o.get('delivery')}`（目標 {_num(o.get('target_lufs_i'), 1)} LUFS）" for o in outs))
    if prof:
        lo = prof.get("loudness") or {}
        tp = prof.get("true_peak") or {}
        out.append(f"- プロファイルの値（変更不可）: 目標 {_num(lo.get('target_lufs_i'), 1)} LUFS、窓 {_range_text(lo.get('window_lufs_i'))}、"
                   f"天井 {_num(tp.get('ceiling_dbtp'), 1)} dBTP、方針 `{lo.get('policy')}`、コーデック検査 {', '.join(prof.get('codec_checks') or []) or '—'}")
    out.append(f"- テンプレ（床）の目的関数: `{blend}`、強度 {_num(obj.get('intensity'), 2)}（床 = この目的関数で適用済みのミックスとマスター）")
    tb = ctx.project.get("timebase") or {}
    tempo = (ctx.mxp or {}).get("tempo") or {}
    out.append(f"- 長さ {_num((tb.get('length_samples') or 0) / (tb.get('sample_rate') or 1), 2)} s、{tb.get('sample_rate')} Hz、"
               f"テンポ {_num(tempo.get('bpm'), 1)} BPM（{tempo.get('source') or '—'}）")
    prov = ctx.project.get("provenance") or {}
    out.append(f"- 取り込み: `{prov.get('input_kind') or '—'}`、生成サービス {prov.get('service') or '未申告'}"
               "（生成時のスタイル指定・構成タグはプロジェクトに無い）")
    return out


def _s2(ctx: _Ctx, sa: dict | None) -> list[str]:
    secs = ctx.sections()
    rows = []
    for t in ctx.tracks:
        aid = ctx.track_asset(t)
        a = ctx.assets.get(aid) or {}
        vec = ctx.analysis.get(aid) or {}
        p03 = vec.get("P-03") or {}
        tp = p03.get("true_peak_dbtp")
        presence = "—"
        if sa and t["id"] in sa["per_track"]:
            vals = sa["per_track"][t["id"]]
            presence = "".join("●" if (x is not None and x >= ABSENT_LUFS) else "·" for x in vals)
        rows.append([t["id"], t.get("role"), "主役" if t.get("is_lead") else "", a.get("origin"),
                     _num((t.get("importance") or {}).get("value"), 2), _num(p03.get("integrated_lufs"), 1),
                     _num(tp, 2), _num(-tp if isinstance(tp, (int, float)) else None, 2), presence])
    out = _table(["トラック", "役割", "主役", "origin", "重要度", "LUFS-I（素材）", "TP dBTP", "ヘッドルーム dB", "在・不在（区間順）"], rows)
    out.append("")
    out.append(f"- origin: `native_stem` = 生成元のステム、`separated` = 分離由来（R-22）、`reference_fullmix` = 参照用の 2 ミックス")
    if secs:
        out.append(f"- 在・不在: 区間 {', '.join(s['id'] for s in secs)} の順。● = 区間の積分ラウドネス ≥ {ABSENT_LUFS:.0f} LUFS、· = 未満（整音後の素材、フェーダー前）")
    fm = ctx.project.get("fullmix_asset")
    if fm:
        out.append(f"- 参照 2 ミックス: `{fm}`（ミックスには入らない）")
    return out


def _s3(ctx: _Ctx, sa: dict | None) -> list[str]:
    secs = ctx.sections()
    if not secs:
        return ["- セクションはミックス提案にしかなく、適用済みのミックス提案がないため空欄"]
    out = ["区間はミックス提案（`sections`）の推定。ラベル quiet/mid/loud はその推定の分類。", ""]
    rows = []
    for i, s in enumerate(secs):
        row = [s.get("id"), f"{_num(s.get('start_s'), 1)}–{_num(s.get('end_s'), 1)}",
               _num(float(s.get("end_s", 0)) - float(s.get("start_s", 0)), 1), s.get("label")]
        if sa:
            sm = sa["sums"][i]
            present = [tid for tid, v in sa["per_track"].items() if v[i] is not None and v[i] >= ABSENT_LUFS]
            gains = {t["id"]: float(t.get("gain_db") or 0.0) for t in ctx.tracks}
            post = sorted(((v[i] + gains.get(tid, 0.0), tid) for tid, v in sa["per_track"].items() if v[i] is not None),
                          key=lambda z: (-z[0], z[1]))
            top = ", ".join(f"{tid}（{_num(val, 1)}）" for val, tid in post[:2])
            row += [_num(sm["lufs"], 1), _num(sm["st_max"], 1), len(present), top]
        rows.append(row)
    head = ["区間", "秒", "長さ s", "ラベル"]
    if sa:
        head += ["和 LUFS-I", "和 短期最大", "在ステム数", "大きい順 2 本（フェーダー込み LUFS）"]
    out += _table(head, rows)
    if sa:
        out.append("")
        out.append("- 「和」= 整音後のステムに床のフェーダーだけを掛けた静的和（パン・処理・バスなし）。描画済みミックスではない")
        out.append("- 密度は在ステム数で示す。帯域ごとの主役数（P-22）は代表区間だけ測られている（§5）")
        out.append("")
        out.append("トラック別の区間ラウドネス（LUFS-I、整音後、フェーダー前。— は無音または 0.4 s 未満）")
        out.append("")
        rows2 = [[tid] + [_num(v, 1) for v in vals] for tid, vals in sa["per_track"].items()]
        out += _table(["トラック"] + [s["id"] for s in secs], rows2)
        src = sorted(set(sa["kinds"].values()))
        out.append("")
        out.append(f"- 音声の出どころ: {', '.join(src)}（cleaned = cache/clean の整音済み、asset = 素材そのまま）")
    exc = (ctx.mxp or {}).get("excerpts") or []
    if exc:
        out.append("- 代表区間（ミックス評価に使った抜粋）: " + ", ".join(
            f"{e.get('label')} {_num(e.get('start_s'), 2)}–{_num(e.get('end_s'), 2)} s" for e in exc))
    return out


def _vec_row(name: str, vec: dict) -> list[Any]:
    p03 = vec.get("P-03") or {}
    p05 = ((vec.get("P-05") or {}).get("full_band") or {})
    p06 = vec.get("P-06") or {}
    p04 = ((vec.get("P-04") or {}).get("full_band") or {})
    worst = p06.get("worst_band")
    wl = ((p06.get("bands") or {}).get(worst) or {}).get("mono_loss_db") if worst else None
    bands = (vec.get("P-07") or {}).get("bands") or {}
    frac = "/".join(_num((bands.get(b) or {}).get("fraction"), 2) for b in ("sub", "bass", "lowmid", "mid", "highmid", "air"))
    return [name, _num(p03.get("integrated_lufs"), 1), _num(p03.get("short_term_p95"), 1), _num(p03.get("lra_lu"), 1),
            _num(p03.get("plr_db"), 1), _num(p03.get("psr_db"), 1), _num(p04.get("crest_db"), 1),
            _num(p05.get("correlation"), 3), _num(p05.get("side_ratio"), 3), f"{worst or '—'} {_num(wl, 2)}", frac]


def _s4(ctx: _Ctx) -> list[str]:
    out = ["### 4.1 全体とステム別（analysis の要約値。LTAS の全ビンなど生の配列は載せない）", ""]
    rows = []
    if "stem_sum" in ctx.analysis:
        rows.append(_vec_row("静的ステム和", ctx.analysis["stem_sum"]))
    fm = ctx.project.get("fullmix_asset")
    if fm and fm in ctx.analysis:
        rows.append(_vec_row(f"参照 2 ミックス", ctx.analysis[fm]))
    for t in ctx.tracks:
        aid = ctx.track_asset(t)
        if aid in ctx.analysis:
            rows.append(_vec_row(t["id"], ctx.analysis[aid]))
    out += _table(["対象", "LUFS-I", "短期 p95", "LRA", "PLR", "PSR", "クレスト", "相関", "S/M 比", "モノ損失 最悪帯域 dB",
                   "P-07 帯域比 sub/bass/lowmid/mid/highmid/air"], rows)
    out.append("")
    out.append("- 素材（整音前・フェーダー前）の測定。P-07 の帯域: sub 20–60、bass 60–250、lowmid 200–800、mid 800–2k、highmid 2k–6k、air 6k–20k Hz")
    out.append("")
    out.append("### 4.2 目的関数の項と範囲端までの距離")
    out.append("")
    rows = []
    for stage, prop in (("mix", ctx.mxp), ("master", ctx.mpl)):
        if not prop:
            continue
        terms = (prop.get("objective_evaluation") or {}).get("terms") or []
        resolved = {(t.get("objective"), t.get("key")): t for t in (prop.get("objective_resolved") or {}).get("terms") or []}
        for t in terms:
            rt = resolved.get((t.get("objective"), t.get("key"))) or {}
            val = t.get("value")
            target = t.get("target")
            src = t.get("target_source") or rt.get("target_source") or (target.get("source") if isinstance(target, dict) else None)
            if isinstance(val, dict):
                vtxt = "; ".join(f"{k} {_num(v, 2)}" for k, v in sorted(val.items()))
                dist = "; ".join(f"{k} {_edge_distance(val.get(k), target.get(k) if isinstance(target, dict) else None)}"
                                 for k in sorted(val))
            else:
                vtxt, dist = _num(val, 3), _edge_distance(val, target)
            rows.append([stage, t.get("key"), t.get("status"), vtxt, _range_text(target), dist, src or "—",
                         _num(t.get("penalty"), 3)])
    if rows:
        out += _table(["段", "指標", "状態", "値", "範囲", "範囲端まで", "範囲の出どころ", "罰"], rows)
        out.append("")
        out.append("- 範囲端まで: 内 x = 範囲の内側に x の余裕、外 x = x はみ出し。罰は目的関数の値（重みは掛けていない）")
    meas = (ctx.mxp or {}).get("measurements") or {}
    if meas:
        out.append("")
        out.append("### 4.3 ミックス段の測定（ミックス提案 `measurements`、開始 → 最終）")
        out.append("")
        st, fi = meas.get("start") or {}, meas.get("final") or {}
        keys = [k for k in ("P-10", "P-10_verdict", "P-02_vs_lead_db", "P-02_overall_db", "P-22_max_owners",
                            "P-09_penalty", "low_ratio_db", "gate") if k in st or k in fi]
        rows = [[k, _num(st.get(k), 3) if not isinstance(st.get(k), str) else st.get(k),
                 _num(fi.get(k), 3) if not isinstance(fi.get(k), str) else fi.get(k)] for k in keys]
        out += _table(["量", "開始", "最終（床）"], rows)
        p10 = next((u for u in (ctx.mxp or {}).get("unresolved") or [] if u.get("code") == "p10_off_target"), None)
        if p10:
            out.append("")
            out.append(f"- P-10 の目標 {_range_text(p10.get('target'))} dB（ジャンル prior。§7）に対し最終 {_num(p10.get('value'), 2)} dB: "
                       f"範囲端まで {_edge_distance(p10.get('value'), p10.get('target'))}")
    return out


def _s5(ctx: _Ctx) -> list[str]:
    out = []
    mx = ctx.mxp or {}
    # masking vs lead (candidate maskers recorded by the planner)
    rows = []
    for m in mx.get("moves") or []:
        me = m.get("measured") or {}
        if "buried_db" in me:
            rows.append([m.get("id"), m.get("track"), me.get("region"), _range_text(me.get("band_hz")),
                         _num(me.get("lead_peak_hz"), 0), _num(me.get("buried_db"), 3), _num(me.get("masker_importance"), 2),
                         m.get("status"), (m.get("result") or {}).get("verdict")])
    out.append("### 5.1 主役に対するマスキング（P-02。ミックス提案が候補に挙げた対）")
    out.append("")
    if rows:
        out += _table(["手", "覆う側", "領域", "帯域 Hz", "主役のピーク Hz", "埋もれ dB", "覆う側の重要度", "採否", "結果"], rows)
    else:
        out.append("- 記録なし")
    fi = (mx.get("measurements") or {}).get("final") or {}
    out.append("")
    out.append(f"- 床の P-02: 対主役 {_num(fi.get('P-02_vs_lead_db'), 3)} dB、全体 {_num(fi.get('P-02_overall_db'), 3)} dB。"
               "区間別・対ごとの全表はプロジェクトに保存されていない（§付記）")
    # lowest octaves
    out.append("")
    out.append("### 5.2 最低オクターブの占有（素材の P-07 帯域レベル dB、フェーダー込みは床の gain_db を加算）")
    out.append("")
    rows = []
    for t in ctx.tracks:
        vec = ctx.analysis.get(ctx.track_asset(t)) or {}
        bands = (vec.get("P-07") or {}).get("bands") or {}
        g = float(t.get("gain_db") or 0.0)
        sub, bass = (bands.get("sub") or {}).get("level_db"), (bands.get("bass") or {}).get("level_db")
        if sub is None and bass is None:
            continue
        rows.append((-(sub + g) if sub is not None else 999.0, t["id"], sub, bass, g))
    rows.sort(key=lambda r: (r[0], r[1]))
    out += _table(["トラック", "sub 20–60", "bass 60–250", "フェーダー", "sub（込み）", "bass（込み）"],
                  [[tid, _num(s, 1), _num(b, 1), _num(g, 1, sign=True), _num(s + g if s is not None else None, 1),
                    _num(b + g if b is not None else None, 1)] for _, tid, s, b, g in rows[:6]])
    out.append("")
    out.append("- sub（込み）の大きい順に上位 6 本。キックはドラムのステムに含まれる（キック単独のステムはない）")
    # band owners
    out.append("")
    out.append("### 5.3 帯域担当（P-22、R-28。ミックス提案 `arrangement`、代表区間ごと）")
    out.append("")
    arr = mx.get("arrangement") or []
    if arr:
        rows = []
        for a in arr:
            me = a.get("measured") or {}
            rows.append([a.get("id"), a.get("section"), f"{_num(me.get('start_s'), 2)}–{_num(me.get('end_s'), 2)}",
                         a.get("band"), me.get("owners"), ", ".join(a.get("keep") or []), ", ".join(a.get("yield") or []),
                         a.get("status")])
        out += _table(["ID", "代表区間", "秒", "帯域", "主役数", "残す", "譲る", "状態"], rows)
        out.append("")
        out.append("- 提案のみ（自動適用されない）。区間ミュート・オクターブ変更はリミックス操作")
    else:
        out.append("- 記録なし")
    # stereo
    out.append("")
    out.append("### 5.4 相関・幅（素材の P-05 全帯域）")
    out.append("")
    items = []
    for t in ctx.tracks:
        vec = ctx.analysis.get(ctx.track_asset(t)) or {}
        fb = (vec.get("P-05") or {}).get("full_band") or {}
        if fb:
            items.append(f"{t['id']} {_num(fb.get('correlation'), 3)}/{_num(fb.get('side_ratio'), 3)}")
    out.append("- 相関/S/M 比: " + ("、".join(items) if items else "—"))
    return out


def _s6(ctx: _Ctx) -> list[str]:
    out = []
    v = ctx.verify
    if v:
        out.append(f"### 6.1 verify（`reports/verify_{ctx.variant_id}.json`。overall: {v.get('overall')}）")
        out.append("")
        for i, o in enumerate(v.get("outputs") or []):
            me = o.get("measured") or {}
            out.append(f"**{o.get('profile')} / {o.get('delivery')}**: overall {o.get('overall')}、LUFS-I {_num(me.get('lufs_i'), 3)}、"
                       f"TP {_num(me.get('true_peak_dbtp'), 2)} dBTP、{me.get('sample_rate')} Hz {me.get('subtype')}")
            out.append("")
            ch = o.get("checks") or {}
            if i == 0:
                rows = [[cid, ch[cid].get("status"), _check_values(cid, ch[cid])] for cid in sorted(ch)]
                out += _table(["検査", "状態", "値と許容"], rows)
            else:
                # later outputs: statuses, plus the values that carry a margin (S-01, S-02, S-08)
                out.append("- 状態: " + ", ".join(f"{cid} {ch[cid].get('status')}" for cid in sorted(ch)))
                for cid in ("S-01", "S-02", "S-08"):
                    if cid in ch:
                        out.append(f"- {cid}: {_check_values(cid, ch[cid])}")
            out.append("")
    else:
        out.append("- verify の記録がない（未描画）")
        out.append("")
    if ctx.mpl:
        ex = ctx.mpl.get("expected") or {}
        gr = ex.get("limiter_gr") or {}
        warn = ctx.threshold("p18_limiter_dependency", "gr_p95_warn_db")
        sb = ctx.threshold("p18_limiter_dependency", "gr_p95_send_back_db")
        out.append("### 6.2 マスター計画段（`" + str(ctx.mpl.get("proposal_id")) + "`）")
        out.append("")
        out.append(f"- R-14 リミッター GR: p95 {_num(gr.get('gr_p95_db'), 2)} dB（警告 {_num(warn, 1)}、差し戻し {_num(sb, 1)}）、"
                   f"中央値 {_num(gr.get('gr_median_db'), 2)}、最大 {_num(gr.get('gr_max_db'), 2)}、1 dB 超の割合 {_num(gr.get('gr_fraction_gt_1db'), 3)}")
        s08 = ex.get("s08") or {}
        if s08:
            out.append(f"- 計画段 S-08: {s08.get('status')}（verify 許容での判定 {s08.get('verify_tolerance_status')}）、"
                       f"最悪の超過 {_num(s08.get('worst_excess_db'), 2)} dB（負 = 許容の内側）、計画余裕 {_num(s08.get('margin_db'), 2)} dB")
            rows = [[k, _num(d.get("delta_db"), 2), _num(d.get("tolerance_db"), 2),
                     _num((d.get("tolerance_db") or 0) - (s08.get("margin_db") or 0), 2) if d.get("tolerance_db") is not None else "—",
                     _num((d.get("tolerance_db") - (s08.get("margin_db") or 0)) - d["delta_db"], 2)
                     if d.get("tolerance_db") is not None and d.get("delta_db") is not None else "—"]
                    for k, d in sorted((s08.get("deltas") or {}).items())]
            out.append("")
            out += _table(["S-08 指標", "模擬の差 dB", "verify 許容", "計画上限（許容 − 余裕）", "計画上限までの余裕"], rows)
            out.append("")
        out.append(f"- 期待値: LUFS-I {_num(ex.get('lufs_i'), 2)}、TP {_num(ex.get('true_peak'), 2)} dBTP（天井 {_num(ex.get('ceiling_dbtp'), 1)}、"
                   f"コーデック後の天井 {_num(ex.get('codec_after_ceiling_dbtp'), 1)}）")
        inp = ctx.mpl.get("input") or {}
        out.append(f"- マスター入力: {_num(inp.get('lufs_i'), 2)} LUFS、TP {_num(inp.get('true_peak'), 2)} dBTP")
    ev = (ctx.variant or {}).get("evaluation") or {}
    gate = ev.get("gate") or {}
    if gate:
        out.append("")
        out.append(f"### 6.3 OF-5（トランスレーション・ゲート、計画時）: {gate.get('status')}")
        out.append("")
        for c in gate.get("checks") or []:
            out.append(f"- {c.get('id')}: {c.get('status')}" + (f"（{c.get('reason')}）" if c.get("reason") else ""))
        for n in gate.get("notes") or []:
            out.append(f"- 注: {n}")
    tol = ctx.cleanup_policy.get("s08") or {}
    if tol:
        out.append("")
        out.append("- S-08 の許容（knowledge/cleanup_policy.json、変更不可）: " + "、".join(
            f"{k} {_num((v or {}).get('value'), 1)}" for k, v in sorted(tol.items()) if isinstance(v, dict)))
    return out


def _check_values(cid: str, c: dict) -> str:
    parts = []
    if cid == "S-08":
        for k, d in sorted((c.get("deltas") or {}).items()):
            if d.get("delta_db") is None:
                continue
            parts.append(f"{k} Δ{_num(d.get('delta_db'), 3)} / 許容 {_num(d.get('tolerance_db'), 1)}")
        return "; ".join(parts)
    if cid == "S-07":
        worst = None
        for aid, a in sorted((c.get("assets") or {}).items()):
            r = a.get("residual_stored_dbfs")
            if r is not None and (worst is None or r > worst[1]):
                worst = (aid, r, a.get("limit_dbfs"))
        return f"最大残差 {worst[0]} {_num(worst[1], 1)} dBFS / 上限 {_num(worst[2], 1)}" if worst else ""
    if cid == "S-02":
        cods = c.get("codecs") or {}
        parts = [f"{k} {_num(v.get('true_peak_dbtp'), 2)}" for k, v in sorted(cods.items())]
        return f"コーデック後 TP {', '.join(parts)} dBTP / 天井 {_num(c.get('codec_after_ceiling_dbtp'), 1)}"
    if cid == "S-09":
        me = c.get("measured") or {}
        return (f"nan {me.get('nan')}, inf {me.get('inf')}, clipped {me.get('clipped_samples')}, "
                f"frames {me.get('frames')}/{me.get('expected_frames')}")
    flat: list[str] = []
    skip = {"status", "rule", "note", "reason", "expected", "method", "milestone", "facts", "problems", "issues",
            "suggestions", "baseline", "conditional_applied"}

    def walk(prefix: str, o: Any, depth: int) -> None:
        if isinstance(o, dict):
            if depth >= 3:
                return
            for k in sorted(o):
                if k not in skip:
                    walk(f"{prefix}.{k}" if prefix else k, o[k], depth + 1)
        elif isinstance(o, bool):
            flat.append(f"{prefix} {o}")
        elif isinstance(o, (int, float)):
            flat.append(f"{prefix} {_num(o, 3)}")
        elif isinstance(o, list) and o and len(o) <= 3 and all(
                isinstance(x, (int, float)) and not isinstance(x, bool) for x in o):
            flat.append(f"{prefix} [{', '.join(_num(x, 2) for x in o)}]")
        elif isinstance(o, str) and len(o) <= 24:
            flat.append(f"{prefix} {o}")
    walk("", c, 0)
    flat = [x.replace("measured.", "").replace("limits.", "上限 ") for x in flat]
    if cid == "S-05":
        f = c.get("facts") or {}
        flat.append(f"dither {f.get('quantization')} ×{f.get('dither_count')}")
    if c.get("reason"):
        flat.append(str(c.get("reason"))[:60])
    return "; ".join(x.strip() for x in flat)


def _s7(ctx: _Ctx) -> list[str]:
    g = ctx.project.get("genre")
    ent = next((x for x in ctx.genre_priors.get("genres") or [] if x.get("id") == g), None)
    out = []
    if ent:
        p10 = ent.get("p10_target_db") or {}
        out.append(f"- `{g}`（knowledge/genre_priors.json、状態 {ctx.genre_priors.get('status')}、等級 {ent.get('evidence')}）: "
                   f"P-10 目標 {_range_text(p10.get('range'))} dB{'（暫定）' if p10.get('provisional') else ''}、低域の主役 `{ent.get('low_end_lead')}`、"
                   f"重視 {', '.join(ent.get('emphasis') or []) or '—'}、重要度の順 {' > '.join(ent.get('stem_importance_order') or ctx.genre_priors.get('default_stem_importance_order') or [])}")
        for n in ent.get("notes") or []:
            out.append(f"  - 注記: {n}")
    else:
        out.append(f"- ジャンル `{g}` の prior はない（汎用 prior）")
    out.append("")
    out.append("**この曲資料で prior 由来の数値**（実測ではない。範囲・重み・目標だけ）")
    out.append("")
    srcs = set()
    for prop in (ctx.mxp, ctx.mpl):
        for t in (prop or {}).get("objective_resolved", {}).get("terms") or []:
            srcs.add((t.get("key"), t.get("target_source")))
    for key, src in sorted(srcs, key=lambda z: (str(z[0]), str(z[1]))):
        if src in ("genre_prior", "generic_prior", "masking_model", "thresholds_m3"):
            out.append(f"- {key} の範囲: `{src}`")
    out.append("- P-10 の目標（§4.3）: `genre_prior`")
    out.append("- §2 の重要度: `default`（ジャンルの重要度の順から）" if any(
        (t.get("importance") or {}).get("source") == "default" for t in ctx.tracks) else "- §2 の重要度: 指定あり")
    if ctx.mpl:
        for r in ctx.mpl.get("rationale") or []:
            if (r.get("measured") or {}).get("band_ratios_vs_generic_prior"):
                out.append("- マスター段の帯域比の範囲（`generic_prior`）: " + "、".join(
                    f"{b} {_range_text(v.get('prior_range'))}（実測 {_num(v.get('ratio'), 3)}）"
                    for b, v in r["measured"]["band_ratios_vs_generic_prior"].items()))
    return out


def _s8(ctx: _Ctx) -> list[str]:
    out = ["`dsp/processors.py` の登録から機械的に列挙。範囲外の値は validate が拒否する。", ""]
    rows = []
    for t in P.processor_types():
        d = P.describe(t)
        ps = []
        for prm in d.get("params") or []:
            if prm["type"] in ("float", "int"):
                ps.append(f"{prm['id']} {_num(prm['min'], 2 if prm['type'] == 'float' else 0)}..{_num(prm['max'], 2 if prm['type'] == 'float' else 0)}{(' ' + prm['unit']) if prm.get('unit') and prm['unit'] not in ('-1..1',) else ''}")
            elif prm["type"] == "enum":
                ps.append(f"{prm['id']} {{{'/'.join(str(c) for c in prm['choices'])}}}")
            elif prm["type"] == "bool":
                ps.append(f"{prm['id']} bool")
            elif prm["type"] == "float_array":
                ps.append(f"{prm['id']} [{_num(prm['min'], 1)}..{_num(prm['max'], 1)}]×≤{prm['max_len']}")
        rows.append([t, "/".join(d.get("stages") or []), "" if d.get("implemented") else "未実装", "; ".join(ps)])
    out += _table(["処理", "段", "", "パラメーターと宣言範囲"], rows)
    out.append("")
    out.append("- `limiter`・`loudness_gain` はマスター段の固定順（S-06）、`resample`・`dither` は書き出し段。指揮書の不変領域")
    out.append("- `aw.*` はネイティブ実装（Airwindows 移植）。ネイティブが無い環境では参照実装の代替が走る")
    out.append("- 区間ごとの処理切替・パンのオートメーションはない（オートメーションはゲインだけ）")
    return out


def _chain_text(chain: list[dict] | None) -> str:
    if not chain:
        return "—"
    return "<br>".join(f"`{c.get('id')}` {c.get('type')}({_param_text(c.get('params'))})"
                       + (f" [{c.get('owner')}]" if c.get("owner") and c.get("owner") != "mixplan" else "")
                       for c in chain)


def _s9(ctx: _Ctx) -> list[str]:
    out = ["床（現在の project.json）のトラック。処理 ID は `chain_param`／`chain_remove` の `replaces` に使う。"
           "owner が mixplan 以外の処理には [owner] を付けた。", ""]
    rows = []
    for t in ctx.tracks:
        pan = t.get("pan") or {}
        sends = "; ".join(f"{s.get('bus')} {_num(s.get('level_db'), 1)} dB{' pre' if s.get('pre_fader') else ''}"
                          for s in t.get("sends") or []) or "—"
        rows.append([t["id"], _num(t.get("gain_db"), 1, sign=True), f"{_num(pan.get('position'), 2)} / {_num(pan.get('width'), 2)}",
                     sends, t.get("output"), _chain_text(t.get("chain"))])
    out += _table(["トラック", "フェーダー dB", "パン位置 / 幅", "センド", "出力", "チェーン"], rows)
    out.append("")
    out.append("**バス**")
    out.append("")
    rows = []
    for b in ctx.project.get("buses") or []:
        rows.append([b.get("id"), b.get("kind"), b.get("output") or "—", _chain_text(b.get("chain"))])
    out += _table(["バス", "種別", "出力", "チェーン"], rows)
    mix = ctx.project.get("mix") or {}
    out.append("")
    out.append(f"- パン則: 中央 {_num(mix.get('pan_law_center_db'), 1)} dB。奥行きの宣言順: {mix.get('declared_depth_order') or 'なし'}")
    v = ctx.variant or {}
    if v.get("track_overrides") or v.get("bus_overrides"):
        out.append(f"- 変種 `{ctx.variant_id}` の上書き: " + json.dumps(
            {k: v.get(k) for k in ("track_overrides", "bus_overrides") if v.get(k)}, ensure_ascii=False, sort_keys=True)[:600])
    return out


_EVIDENCE_RANK = {e: i for i, e in enumerate(kbmod.EVIDENCE)}


def _s10_experience(ctx: _Ctx, cards: list[dict]) -> list[str]:
    """10.1: lesson / move / research cards and the song's own cards (unchanged from v1)."""
    picked = []
    for c in cards:
        m = c["meta"]
        kind = m.get("kind")
        same = bool(ctx.song) and (c["path"].startswith(f"songs/{ctx.song}/") or any(
            f"songs/{ctx.song}/" in str(b) for b in (m.get("backing") or [])))
        if kind in ("lesson", "move", "research") or (kind == "song" and same):
            stale = m.get("status") == "stale"
            picked.append((stale, 0 if same else 1, 0 if kind == "song" else 1,
                           _EVIDENCE_RANK.get(m.get("evidence"), len(_EVIDENCE_RANK)), str(m.get("id")), c, same))
    picked.sort(key=lambda z: z[:5])
    if not picked:
        return ["- 該当するカードなし"]
    out = [f"並び順は kb 規約（同じ曲の実測 > replicated > measured > literature > practice > tip > hunch、stale は末尾）。最大 {MAX_KB_CARDS} 枚。", ""]
    for z in picked[:MAX_KB_CARDS]:
        c, same = z[5], z[6]
        m = c["meta"]
        claim = kbmod.section_text(c["body"], "主張") or c["summary"]
        cond = kbmod.section_text(c["body"], "適用条件")
        out.append(f"- **{m.get('id')}**（{m.get('kind')}、等級 {m.get('evidence') or '—'}、状態 {m.get('status')}"
                   f"{'、同じ曲' if same else ''}）{m.get('title')}")
        out.append(f"  - 適用条件（front matter）: {kbmod.format_applies(m.get('applies_to'))}")
        out.append("  - 主張: " + " ".join(claim.split())[:400])
        if cond:
            out.append("  - 適用条件（本文）: " + " ".join(cond.split())[:300])
    if len(picked) > MAX_KB_CARDS:
        ctx.omitted.append(f"kb の抜粋: {len(picked) - MAX_KB_CARDS} 枚は上限 {MAX_KB_CARDS} 枚を超えたため省略")
    return out


def _s10_theory(cards: list[dict]) -> list[str]:
    """10.2: every active theory card, id and title only (no body; not counted in MAX_KB_CARDS)."""
    shelf = sorted((str(c["meta"].get("id")), str(c["meta"].get("title") or "")) for c in cards
                   if c["meta"].get("kind") == "theory" and c["meta"].get("status") == "active")
    if not shelf:
        out = ["- 理論カードなし"]
    else:
        out = [f"active な理論カード（kind: theory）の ID と題だけを全件、ID 順に載せる（{len(shelf)} 枚。本文は載せない。"
               "10.1 の上限とは別枠）。引くときは `mankomix kb show <ID>`。使うかどうかは指揮者の裁量で、使わなくてよい。", ""]
        out += [f"- {cid} {' '.join(title.split())}" for cid, title in shelf]
    # active curriculum bundles (upgrade 2, proposal 6): one line each, only when present, so a kb without
    # bundles gives the same section as before
    bundles = sorted((str(c["meta"].get("id")), str(c["meta"].get("title") or ""),
                      len(c["meta"]["items"]) if isinstance(c["meta"].get("items"), list) else 0) for c in cards
                     if c["meta"].get("kind") == "curriculum" and c["meta"].get("status") == "active")
    out += [f"- カリキュラム: {cid} {' '.join(title.split())}（{n} 項）" for cid, title, n in bundles]
    return out


def _s10_references(ctx: _Ctx) -> list[str]:
    """10.3: the work cards named for this job: id, title and the refstudy hash only (no numbers)."""
    if not ctx.refs:
        return ["- 指定なし"]
    roots = []
    for label, r in (("kb", ctx.kb_root), ("非公開 kb", ctx.ref_kb_root)):
        if r is not None and Path(r).is_dir() and all(Path(r).resolve() != Path(x).resolve() for _, x in roots):
            roots.append((label, Path(r)))
    found: dict[str, tuple[str, dict, Path]] = {}
    for label, r in roots:
        for c in kbmod.load_cards(r):
            cid = c["meta"].get("id")
            if c["meta"].get("kind") == "work" and cid in ctx.refs and cid not in found:
                found[cid] = (label, c, r)
    out = ["案件で指定された作品（work カード）の ID・題・測定資料 refstudy の sha256（先頭 16 桁）だけを載せる。"
           "数値の対照は曲資料に入れない（`direction ref compare` の対照表 refsheet）。", ""]
    for wid in ctx.refs:
        if wid not in found:
            out.append(f"- {wid}: kb にカードが無い（音源の持ち込みを利用者に求める。U-2）")
            continue
        label, c, r = found[wid]
        study = (r / c["path"]).parent / "refstudy.md"
        sha = hashlib.sha256(study.read_bytes()).hexdigest()[:16] if study.is_file() else None
        title = " ".join(str(c["meta"].get("title") or "").split())
        out.append(f"- {wid} {title}（{label}）: refstudy " + (f"`{sha}`" if sha else "なし（`direction ref study` で作る）"))
    return out


def _s10(ctx: _Ctx) -> list[str]:
    have_kb = ctx.kb_root is not None and Path(ctx.kb_root).is_dir()
    if not have_kb:
        ctx.omitted.append("kb の抜粋（kb が見つからない）")
    cards = kbmod.load_cards(ctx.kb_root) if have_kb else []
    out = ["### 10.1 経験", ""]
    out += _s10_experience(ctx, cards) if have_kb else ["- kb が見つからない"]
    out += ["", "### 10.2 理論の棚", ""]
    out += _s10_theory(cards) if have_kb else ["- kb が見つからない"]
    out += ["", "### 10.3 リファレンス", ""]
    out += _s10_references(ctx)
    return out


def _s11(ctx: _Ctx) -> list[str]:
    out = []
    mx = ctx.mxp
    if mx:
        oe = mx.get("objective_evaluation") or {}
        out.append(f"### 11.1 ミックス（`{mx.get('proposal_id')}`）")
        out.append("")
        out.append(f"- 目的関数の値（罰の合計。小さいほど範囲に近い）: {_num(oe.get('score'), 4)}、ガード込み {_num(oe.get('total_with_guard'), 4)}"
                   f"（ガード項 {', '.join(f'{k} {_num(v, 4)}' for k, v in sorted((oe.get('guard') or {}).items()))}）")
        cons = oe.get("constraints") or {}
        out.append("- 制約: " + ", ".join(f"{k} {v}" for k, v in sorted(cons.items())))
        moves = mx.get("moves") or []
        kept = [m for m in moves if m.get("status") == "kept"]
        rej = [m for m in moves if m.get("status") != "kept"]
        steps = {}
        for m in kept:
            steps.setdefault(m.get("step_id"), []).append(m.get("id"))
        out.append(f"- 適用された手 {len(kept)}: " + "; ".join(f"{k} {len(v)}" for k, v in steps.items()))
        out.append(f"- 棄却された手 {len(rej)}:")
        for m in rej:
            out.append(f"  - {m.get('id')} {m.get('track') or m.get('bus')}: {(m.get('action') or {}).get('ja', '')} → "
                       f"{(m.get('result') or {}).get('verdict')}")
        for u in mx.get("unresolved") or []:
            out.append(f"- 未解決: `{u.get('code')}` " + json.dumps({k: v for k, v in u.items() if k != "code"},
                                                                  ensure_ascii=False, sort_keys=True))
        gate = oe.get("gate") or {}
        if gate:
            out.append(f"- ミックス段の OF-5: {gate.get('status')}（" + ", ".join(
                f"{k} {v}" for k, v in sorted((gate.get("checks") or {}).items())) + "）")
    mp = ctx.mpl
    if mp:
        out.append("")
        out.append(f"### 11.2 マスター（`{mp.get('proposal_id')}`、{mp.get('profile')} / {mp.get('delivery')}）")
        out.append("")
        out.append("- チェーン: " + " → ".join(f"{c.get('type')}({_param_text(c.get('params'))})" for c in mp.get("chain") or []))
        oe = mp.get("objective_evaluation") or {}
        out.append(f"- 目的関数の値 {_num(oe.get('score'), 4)}（ステムを渡さないため未測定の項: "
                   + (", ".join(t.get("key") for t in oe.get("terms") or [] if t.get("status") == "not_measured") or "なし") + "）")
        for r in mp.get("rationale") or []:
            if r.get("stage") == "loudness":
                tried = (r.get("measured") or {}).get("tried") or []
                out.append("- ラウドネスの試行: " + "; ".join(f"目標 {_num(t.get('target'), 1)} → {_num(t.get('lufs_i'), 2)} LUFS、GR p95 {_num(t.get('gr_p95_db'), 2)}" for t in tried)
                           + f"（{(r.get('action') or {}).get('ja', '')}）")
        dominant = []
        ex = mp.get("expected") or {}
        if ex.get("target_lufs_i") is not None and ex.get("lufs_i") is not None:
            dominant.append(f"目標ラウドネス {_num(ex.get('target_lufs_i'), 1)} LUFS（プロファイル）")
        gr = (ex.get("limiter_gr") or {}).get("gr_p95_db")
        if gr is not None:
            dominant.append(f"R-14 GR p95 {_num(gr, 2)} dB")
        s08 = ex.get("s08") or {}
        if s08.get("worst_excess_db") is not None:
            dominant.append(f"計画段 S-08 最悪の超過 {_num(s08.get('worst_excess_db'), 2)} dB")
        out.append("- 支配した制約（値の並び。どれが効いたかの判定はしない）: " + "、".join(dominant))
        if mp.get("send_back"):
            out.append("- 差し戻し: " + json.dumps(mp.get("send_back"), ensure_ascii=False, sort_keys=True)[:400])
    if ctx.verify:
        out.append("")
        out.append("### 11.3 実測（verify）")
        out.append("")
        for o in ctx.verify.get("outputs") or []:
            me = o.get("measured") or {}
            out.append(f"- {o.get('delivery')}: LUFS-I {_num(me.get('lufs_i'), 3)}、TP {_num(me.get('true_peak_dbtp'), 2)} dBTP、overall {o.get('overall')}")
    if not out:
        out.append("- 床の記録がない")
    return out


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def build_dossier(project_path: str | Path, *, variant: str | None = None, song: str | None = None,
                  kb_root: str | Path | None = None, section_audio: bool = True,
                  refs: list[str] | None = None, ref_kb_root: str | Path | None = None) -> dict:
    """``refs``: work card ids named for this job (§10.3); looked up in ``kb_root`` and then in
    ``ref_kb_root`` (default: the private kb ``_private/kb`` of the repository, where third-party works
    live by default). Only the id, the title and the refstudy hash are printed."""
    root = Path(project_path)
    if kb_root is None:
        cand = repo_data_root() / "kb"
        kb_root = cand if cand.is_dir() else None
    wanted: list[str] = []
    for r in refs or []:
        if not isinstance(r, str) or not _WORK_ID_RE.match(r):
            raise ValueError(f"--ref needs a work card id work_<slug> (got {r!r})")
        if r not in wanted:
            wanted.append(r)
    if ref_kb_root is None:
        cand = repo_data_root() / "_private" / "kb"
        ref_kb_root = cand if cand.is_dir() else None
    ctx = _Ctx(root, variant, song, Path(kb_root) if kb_root is not None else None, section_audio)
    ctx.refs = wanted
    ctx.ref_kb_root = Path(ref_kb_root) if ref_kb_root is not None else None
    sa = _section_audio(ctx)
    body: list[str] = []
    builders = (lambda: _s1(ctx), lambda: _s2(ctx, sa), lambda: _s3(ctx, sa), lambda: _s4(ctx), lambda: _s5(ctx),
                lambda: _s6(ctx), lambda: _s7(ctx), lambda: _s8(ctx), lambda: _s9(ctx), lambda: _s10(ctx),
                lambda: _s11(ctx))
    for head, fn in zip(HEADINGS[:-1], builders):
        body.append(f"## {head}")
        body.append("")
        body += fn()
        body.append("")
    always = [
        "マスキングの区間別・対ごとの全表、相関の対ごとの表（プロジェクトに保存されていない。追加観察で取る）",
        "帯域担当（P-22）の全区間の表（代表区間 3 つだけ測られている）",
        "セクション別の P-01〜P-22（解析はステム単位の全長値だけ）",
        "描画済みミックス・マスターの区間別ラウドネス（写しに描画結果がない。§3 は静的和）",
        "生成時の情報（スタイル指定・歌詞の構成タグ）と利用者の感想（プロジェクトに無い）",
        "LTAS の全ビン、ラウドネスの時系列など生の配列（方針として載せない）",
    ]
    body.append(f"## {HEADINGS[-1]}")
    body.append("")
    for o in ctx.omitted + always:
        body.append(f"- {o}")
    body.append("")
    srcs = "、".join(f"`{k}` {v}" for k, v in sorted(ctx.sources.items()) if not k.startswith("analysis/"))
    n_an = sum(1 for k in ctx.sources if k.startswith("analysis/"))
    header = [
        f"# 曲資料（dossier）{('— ' + song) if song else ''}",
        "",
        f"<!-- 機械生成（mankomix direction dossier v{DOSSIER_VERSION}）。決定論・読み取りのみ。並べるだけで重みづけしない。 -->",
        "",
        f"- 入力（sha256 先頭 16 桁）: {srcs}、analysis {n_an} 件",
        "",
    ]
    md = "\n".join(header + body).rstrip() + "\n"
    return {
        "kind": "dossier",
        "version": DOSSIER_VERSION,
        "variant": ctx.variant_id,
        "song": song,
        "sha256": hashlib.sha256(md.encode("utf-8")).hexdigest(),
        "chars": len(md),
        "headings": list(HEADINGS),
        "omitted": ctx.omitted,
        "references": ctx.refs,
        "markdown": md,
    }
