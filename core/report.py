"""Mix Report (SPEC 6.8, R-24, R-25, D-044).

``report.json`` is canonical; Markdown is rendered from it in Japanese and
English. Section 5 is the per-metric objective breakdown (never only a total
score): taken from the evaluation stored with the applied proposal, or
computed on the rendered master; section 6 adds the S-nn statuses of that
evaluation and the translation gate (OF-5). Text fields are bilingual objects ``{"ja": ..., "en": ...}`` in the
canonical file; ``build_report(..., lang="ja"|"en")`` resolves them to one
language. Nothing is fabricated: sections a route or milestone cannot fill
say so explicitly.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import mankomix

from . import audio_io, config
from . import master_analysis as ma
from .errors import InputError
from .hashing import canonical_hash
from .mastering import find_variant, limiter_ceiling, objective_ids
from .measure import loudness as ld
from .render import ARCHIVE_DELIVERY, load_manifest, output_ext, variant_dir, variant_route
from .routes import load_master_input, resample

LANGS = ("ja", "en")


def T(ja: str, en: str) -> dict:
    return {"ja": ja, "en": en}


def _resolve(obj, lang: str):
    if isinstance(obj, dict):
        if set(obj.keys()) == {"ja", "en"} and all(isinstance(v, str) for v in obj.values()):
            return obj[lang] if lang in obj else obj["en"]
        return {k: _resolve(v, lang) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v, lang) for v in obj]
    return obj


def resolve_language(report: dict, lang: str) -> dict:
    """Resolve a bilingual report ("both") to one language; "both" returns it unchanged."""
    return report if lang == "both" else _resolve(report, lang)


def _txt(obj, lang: str) -> str:
    if isinstance(obj, dict):
        if lang in obj:
            return str(obj[lang])
        if "en" in obj:
            return str(obj["en"])
        return json.dumps(obj, ensure_ascii=False)
    return "" if obj is None else str(obj)


def _sone(db: float | None) -> dict | None:
    if db is None or not math.isfinite(db):
        return None
    return {"delta_db": round(db, 2), "sone_ratio": round(ma.sone_ratio(db), 3)}


def _fmt_db(db: float | None, lang: str) -> str:
    if db is None:
        return "-"
    r = ma.sone_ratio(db)
    if lang == "ja":
        return f"{db:+.1f} dB（知覚上の大きさ 約 {r:.2f} 倍）"
    return f"{db:+.1f} dB (about {r:.2f}x perceived loudness)"


def _load_verify(project, variant_id: str) -> dict:
    p = Path(project.root) / "reports" / f"verify_{variant_id}.json"
    if p.is_file():
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    from .verify import verify_variant
    return verify_variant(project, variant_id)


# --------------------------------------------------------------------------
# section builders


_STAGE_ELEMENT = {"corrective_eq": "frequency", "enhance": "frequency", "dynamics": "dynamics",
                  "loudness": "dynamics", "true_peak_limiter": "dynamics", "stereo": "panning"}

_BAND_WORDS_EN = {"sub": "pressure / weight", "bass": "body / foundation (too much: boomy)",
                  "low_mid": "warmth (too much: muddy, boxy)", "mid": "core / forwardness",
                  "high_mid": "presence / edge (too much: harsh)", "air": "air / sparkle (too much: hiss)"}


def _vocab_band(band_id: str) -> dict | None:
    try:
        voc = config.load_vocabulary()
    except Exception:
        return None
    alias = {"low_mid": "low_mid", "high_mid": "presence", "sub": "sub_bass"}.get(band_id, band_id)
    for b in voc.get("bands", []):
        if b.get("id") == alias:
            return b
    return None


ELEMENTS = ("balance", "panning", "frequency", "depth", "dynamics", "interest")
_STAGE_ELEMENT["planner_loop"] = "frequency"
_STAGE_ELEMENT["noise_return_guard"] = "dynamics"


def _move_words(moves: list) -> list[dict]:
    """Perceptual vocabulary for EQ moves (plan_master moves carry gain_db, planner moves delta_db)."""
    words = []
    for m in moves or []:
        if not isinstance(m, dict) or not m.get("band"):
            continue
        if m.get("kind") not in (None, "eq"):
            continue
        g = m.get("gain_db", m.get("delta_db"))
        if not isinstance(g, (int, float)):
            continue
        vb = _vocab_band(m["band"])
        direction = "too_much" if g < 0 else "too_little"
        ja = (vb or {}).get(direction, {}).get("ja") if vb else None
        words.append({"band": m["band"], "gain_db": float(g),
                      "vocabulary": T(ja or m["band"], _BAND_WORDS_EN.get(m["band"], m["band"]))})
    return words


def _decisions(plan: dict, stored: dict | None = None, n_refs: int = 0) -> dict:
    """Decision log by the six elements (SPEC 6.8 section 4).

    ``plan.rationale`` gives the stage decisions of the chain; ``stored`` (the
    applied proposal's planner decisions, ``variants[].decisions``) adds the
    planner's moves and its notes for balance / depth / interest.
    """
    out = {k: [] for k in ELEMENTS}
    for r in plan.get("rationale", []) or []:
        el = _STAGE_ELEMENT.get(r.get("stage"), "dynamics")
        d = {"stage": r.get("stage"), "measured": r.get("measured"), "rule": r.get("rule"),
             "action": r.get("action"), "alternatives": r.get("alternatives", []), "result": r.get("expected")}
        words = _move_words(r.get("moves"))
        if words:
            d["vocabulary"] = words
        if r.get("steps"):
            # corrective steps (e.g. the S-08 guard): measured -> rule -> action -> alternatives -> result
            d["steps"] = r["steps"]
        out[el].append(d)
    for el in ELEMENTS:
        for d in (stored or {}).get(el) or []:
            if isinstance(d, dict):
                out[el].append(d)
    na_mix = T("フルミックス経路のマスタリングでは扱わない（ミックス段は M4）",
               "Not handled by full-mix mastering (the mix stage arrives in M4)")
    for el in ("balance", "depth"):
        if not out[el]:
            out[el].append({"measured": None, "rule": None, "action": na_mix, "alternatives": [], "result": None,
                            "status": "not_evaluated"})
    refs = (T(f"登録済みのリファレンス {n_refs} 曲は目標範囲の物差しとして使った（スペクトルの写し取りはしない）",
              f"The {n_refs} registered reference(s) were used as a yardstick for target ranges (no spectrum copying)")
            if n_refs else
            T("リファレンスは登録されていない", "No references are registered"))
    if not any(d.get("status") == "depends_on_humans_and_references" for d in out["interest"]):
        out["interest"].append({"measured": None, "rule": "R-26",
                                "action": T("「仕掛け」は自動化が最も難しい軸で、人間の指示とリファレンスに依存する。プランナーは展開のコントラストを平坦にしないことだけを監視する",
                                            "Interest is the hardest axis to automate and depends on human direction and references; the planner only watches that section contrast is not flattened"),
                                "alternatives": [], "result": None, "status": "depends_on_humans_and_references"})
    for d in out["interest"]:
        if d.get("status") == "depends_on_humans_and_references":
            d["references"] = refs
    if not out["panning"]:
        out["panning"].append({"measured": None, "rule": "R-09", "action": T("ステレオ処理なし", "No stereo processing"),
                               "alternatives": [], "result": None})
    return out


# --------------------------------------------------------------------------
# objective evaluation (sections 3, 5, 6)


_ROW_KEYS = ("objective", "metric", "variant", "key", "sense", "weight", "effective_weight", "value", "target",
             "target_source", "penalty", "contribution", "status", "reason", "unit")


def _rows(terms: list) -> list[dict]:
    return [{k: t.get(k) for k in _ROW_KEYS if k in t} for t in terms or [] if isinstance(t, dict)]


def _by_objective(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        if r.get("status") == "measured" and isinstance(r.get("contribution"), (int, float)):
            out[r["objective"]] = out.get(r["objective"], 0.0) + float(r["contribution"])
    return out


def _evaluate_signal(O, x, sr, resolved, *, before=None, profile=None, ceiling=None, limiter=None,
                     chain=None, gate=False) -> dict:
    meas = O.measure_for_objective(x, sr, resolved, before=before, profile=profile, ceiling_dbtp=ceiling,
                                   limiter=limiter, chain=chain, gate=gate)
    return O.evaluate(meas, resolved)


def _objective_evaluation(project, variant: dict, x_in, sr_in, archive_path: Path | None) -> dict:
    """Before / after objective evaluation of a variant (level matched, R-01).

    "after" is the evaluation stored with the applied proposal when it belongs to
    the current chain (``variants[].evaluation``), else it is computed on the
    rendered archive master. "before" is the unprocessed master input against the
    same resolved objective (preservation metrics compare the input with itself).
    """
    from . import objectives as O
    vid = variant.get("id")
    master = variant.get("master") or {}
    chain = master.get("chain") or []
    plan = master.get("plan") or {}
    try:
        resolved = O.resolve_objective(project, variant=vid)
    except Exception as exc:  # an invalid stored objective must not break the report
        return {"status": "not_evaluated", "reason": f"objective could not be resolved: {exc}"}
    outputs = variant.get("outputs") or []
    profile = None
    if outputs and outputs[0].get("profile"):
        try:
            profile = config.get_profile(outputs[0]["profile"])
        except Exception:
            profile = None
    out: dict = {"status": "not_evaluated", "resolved": O.summarize_resolved(resolved),
                 "resolved_notes": resolved.get("notes") or [], "before": None, "after": None, "source": None}
    stored = variant.get("evaluation")
    if isinstance(stored, dict) and stored.get("chain_hash") == canonical_hash(chain):
        out["after"] = {"score": stored.get("score"), "terms": _rows(stored.get("terms")),
                        "constraints": stored.get("constraints") or {}, "constraint_details": None,
                        "gate": stored.get("gate"), "redistribution": stored.get("redistribution") or [],
                        "scope": stored.get("scope"), "proposal_id": stored.get("proposal_id")}
        out["source"] = "stored_proposal"
        if (stored.get("objective") or {}).get("reference"):
            out["resolved"]["reference"] = stored["objective"]["reference"]
    elif isinstance(stored, dict):
        out["stale_stored"] = True
    try:
        if out["after"] is None and archive_path is not None and archive_path.is_file():
            y, sr = audio_io.read(archive_path)
            if int(sr) != int(sr_in):
                y, sr = resample(y, sr, sr_in), sr_in
            n = min(y.shape[0], x_in.shape[0])
            ev = _evaluate_signal(O, y, sr, resolved, before=x_in[:n] if n else None, profile=profile,
                                  ceiling=limiter_ceiling(chain) if chain else None,
                                  limiter=(plan.get("expected") or {}).get("limiter_gr"), chain=chain or None,
                                  gate=True)
            out["after"] = {"score": ev.get("score"), "score_unconstrained": ev.get("score_unconstrained"),
                            "terms": _rows(ev.get("terms")), "constraints": ev.get("constraints") or {},
                            "constraint_details": ev.get("constraint_details"), "gate": ev.get("gate"),
                            "redistribution": ev.get("redistribution") or [], "scope": "full_length",
                            "notes": ev.get("notes") or []}
            out["source"] = "rendered_master"
        evb = _evaluate_signal(O, x_in, sr_in, resolved, before=x_in, profile=profile)
        out["before"] = {"score": evb.get("score_unconstrained"), "terms": _rows(evb.get("terms")),
                         "scope": "full_length", "note": T(
                             "処理前（マスター入力）。保存系の指標（トランジェント、展開のコントラスト）は入力どうしの比較なので理想値になる",
                             "Before = the unprocessed master input; preservation metrics (transients, section contrast) compare the input with itself and are ideal")}
    except Exception as exc:  # informative section: report the reason instead of failing
        out["error"] = str(exc)
    if out["after"] is not None:
        out["status"] = "evaluated"
    elif "error" not in out:
        out["reason"] = "render the variant (or apply a planner proposal) to evaluate the objective"
    return out


def _fmt_num(v, nd: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{v:.{nd}f}" if math.isfinite(float(v)) else "-"
    if isinstance(v, list) and len(v) == 2 and all(isinstance(a, (int, float)) or a is None for a in v):
        return f"[{_fmt_num(v[0], nd)}, {_fmt_num(v[1], nd)}]"
    text = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 60 else text[:59] + "…"


def _breakdown(oe: dict, obj: dict) -> dict:
    """Section 5: per-metric achievement (never only a total score)."""
    after = oe.get("after")
    if after is None:
        return {"status": oe.get("status", "not_evaluated"), "reason": oe.get("reason") or oe.get("error"),
                "terms": [{"objective": oid, "status": "not_evaluated"} for oid in objective_ids(obj)],
                "note": T("目的関数の達成度は、レンダリング後（またはプランナーの提案を適用した後）に指標別に評価する。合計 score だけは出さない",
                          "The objective is evaluated per metric after rendering (or after applying a planner proposal); a total score alone is never shown")}
    before = {t.get("key") + "|" + str(t.get("objective")): t for t in (oe.get("before") or {}).get("terms") or []}
    rows = []
    for t in after.get("terms") or []:
        b = before.get(str(t.get("key")) + "|" + str(t.get("objective"))) or {}
        rows.append({**t, "value_before": b.get("value"), "penalty_before": b.get("penalty"),
                     "status_before": b.get("status")})
    res = oe.get("resolved") or {}
    provisional = [b for b in (res.get("blend") or []) if b.get("id") in _provisional_ids()]
    out = {
        "status": "evaluated",
        "source": oe.get("source"),
        "source_label": {"stored_proposal": T("適用した提案の評価（プランナーの全尺評価）", "evaluation stored with the applied proposal (planner, full length)"),
                         "rendered_master": T("レンダリングしたマスターを評価", "evaluated on the rendered master")}.get(oe.get("source")),
        "proposal_id": after.get("proposal_id"),
        "scope": after.get("scope"),
        "objective": {"blend": res.get("blend"), "intensity": res.get("intensity"), "lead": res.get("lead"),
                      "genre": res.get("genre"), "reference": res.get("reference")},
        "score": after.get("score"),
        "score_before": (oe.get("before") or {}).get("score"),
        "score_by_objective": _by_objective(after.get("terms") or []),
        "terms": rows,
        "redistribution": after.get("redistribution") or [],
        "level_matched": True,
        "rule": "R-01",
        "note": T("各項の penalty は目標範囲内なら 0、外れるほど 1 に近づく。score は実効重み × penalty の合計で、0 が理想。測定できない項の重みは同じ目的関数の測定できた項へ比例配分し、記録する",
                  "Each penalty is 0 inside the target range and approaches 1 the further it is outside. The score is the sum of effective weight x penalty; 0 is ideal. Weights of terms that cannot be measured are redistributed proportionally to the measured terms of the same objective and recorded"),
    }
    if provisional:
        out["weak_evidence"] = [{"objective": b.get("id"), "text": T(
            f"「{b.get('id')}」は暫定の目的関数。聴覚疲労を定量した査読研究は弱く、この評価は弱証拠に基づく（SPEC 4.4）",
            f"'{b.get('id')}' is a provisional objective: peer-reviewed evidence quantifying listening fatigue is weak, so this evaluation rests on weak evidence (SPEC 4.4)")}
            for b in provisional]
    if oe.get("stale_stored"):
        out["stale_note"] = T("保存されていた評価は現在のチェーンと一致しないため使わず、レンダリング結果で評価し直した",
                              "The stored evaluation does not match the current chain; re-evaluated on the render")
    return out


def _provisional_ids() -> set:
    try:
        return {o["id"] for o in config.load_objectives()["objectives"] if o.get("provisional")}
    except Exception:
        return set()


_GATE_MEANING = {
    "pass": T("必須の検査がすべて合格した", "Every required check passed"),
    "fail": T("必須の検査に落第がある。score の良し悪しに関わらず是正の対象（SPEC 4.1）",
              "A required check failed: the master is a correction target regardless of its score (SPEC 4.1)"),
    "incomplete": T("評価できなかった必須の検査がある（各検査の理由を参照）。incomplete は合格扱いにしない。2mix だけの場合、主役に関する検査（帯域制限、小音量）はステムがないと評価できない",
                    "Some required checks could not be evaluated (see each reason); incomplete is never a pass. With a 2mix only, the lead checks (band-limited, low level) cannot be evaluated without stems"),
    "not_evaluated": T("ゲートは評価されていない（レンダリング後に評価する）", "The gate was not evaluated (it is evaluated after rendering)"),
}


def _gate_section(oe: dict) -> dict:
    after = oe.get("after") or {}
    g = after.get("gate") or {}
    status = g.get("status") or "not_evaluated"
    return {"spec_id": "OF-5", "status": status, "pass": bool(g.get("pass")), "meaning": _GATE_MEANING.get(status),
            "profile": g.get("profile"),
            "checks": [{k: c.get(k) for k in ("id", "status", "required", "reason", "values") if k in c}
                       for c in g.get("checks") or []],
            "corrective_suggestions": g.get("corrective_suggestions") or [],
            "notes": g.get("notes") or []}


def _objective_constraints(oe: dict) -> dict:
    after = oe.get("after") or {}
    st = after.get("constraints") or {}
    det = after.get("constraint_details") or {}
    return {"statuses": st, "details": {k: v for k, v in det.items() if st.get(k) != "not_evaluated"},
            "rejected": any(v == "fail" for v in st.values()),
            "note": T("目的関数の評価時の安全不変条件。混合や強度で緩和されない（SPEC 4.3）。出口ごとの最終判定は上の検証結果",
                      "Safety invariants at objective evaluation; never relaxed by blend or intensity (SPEC 4.3). The per-output verdicts above are final")}


def _objective_metrics(oe: dict) -> list[dict]:
    before = {(t.get("objective"), t.get("key")): t for t in (oe.get("before") or {}).get("terms") or []}
    out = []
    for t in (oe.get("after") or {}).get("terms") or []:
        b = before.get((t.get("objective"), t.get("key"))) or {}
        out.append({"objective": t.get("objective"), "metric": t.get("key"), "unit": t.get("unit"),
                    "before": b.get("value"), "after": t.get("value"), "status": t.get("status")})
    return out


def _measurements(project, variant, x_in, sr_in, archive_path: Path | None, oe: dict | None = None) -> dict:
    before = ld.loudness_summary(x_in, sr_in)
    res = {"level_matched": False, "before": {k: ma.finite_or_none(v) for k, v in before.items()},
           "after": None, "comparison": None,
           "assumed_playback": T("比較はレベルマッチ後の信号で行う（R-01）。幅と定位の値はスピーカー（±30°）とモノ合算を前提にする",
                                 "Comparisons use level-matched signals (R-01). Width/localisation values assume speakers (+/-30 deg) and a mono fold")}
    if oe and oe.get("after"):
        res["objective_metrics"] = _objective_metrics(oe)
        res["objective_metrics_note"] = T("目的関数の代理指標の処理前後。レベルマッチ後に測定した値（R-01）",
                                          "Objective proxy metrics before and after, measured on level-matched signals (R-01)")
    if archive_path is None or not archive_path.is_file():
        return res
    y, sr = audio_io.read(archive_path)
    after = ld.loudness_summary(y, sr)
    res["after"] = {k: ma.finite_or_none(v) for k, v in after.items()}
    gain = None
    if math.isfinite(after["integrated_lufs"]) and math.isfinite(before["integrated_lufs"]):
        gain = after["integrated_lufs"] - before["integrated_lufs"]
    res["loudness_change"] = _sone(gain)
    try:
        from .measure.compare import compare
        if int(sr) == int(sr_in):
            c = compare(x_in, sr_in, y, sr)
            keep = {}
            for k, v in (c.get("deltas") or {}).items():
                if k.startswith(("P-03/lra", "P-03/plr", "P-03/psr", "P-03/true_peak", "P-07/partition_bands",
                                 "P-06/bands", "P-04/bands")):
                    d = dict(v)
                    if d.get("delta") is not None:
                        d["delta"] = round(d["delta"], 3)
                    if d.get("perceived_ratio") is not None:
                        d["perceived_ratio"] = round(d["perceived_ratio"], 3)
                    keep[k] = d
            res["comparison"] = {"match_gain_db": round(c.get("match_gain_db", 0.0), 3),
                                 "matched_side": c.get("matched_side"), "rule": "R-01", "deltas": keep}
            res["level_matched"] = True
    except Exception as exc:  # comparison is informative; report the reason instead of failing
        res["comparison"] = {"error": str(exc)}
    return res


_S08_KEYS = ("shimmer_index_db", "side_shimmer_index_db", "noise_floor_dbfs", "noise_floor_hf_dbfs",
             "above_ceiling_level_db")
_S08_NAMES = {"shimmer_index_db": T("シマー指数", "shimmer index"),
              "side_shimmer_index_db": T("サイドのシマー指数", "side shimmer index"),
              "noise_floor_dbfs": T("ノイズ床", "noise floor"),
              "noise_floor_hf_dbfs": T("高域のノイズ床", "HF noise floor"),
              "above_ceiling_level_db": T("天井より上の成分", "above-ceiling level")}
_STEP_NAMES = {"click_repair": T("クリック修復", "click repair"),
               "spectral_reduction": T("スペクトル低減", "spectral reduction"),
               "protection": T("保護", "protection"), "completion": T("高域補完", "HF completion")}


def _s08_output(o: dict) -> dict | None:
    c = (o.get("checks") or {}).get("S-08")
    if not isinstance(c, dict):
        return None
    deltas = {}
    for k in _S08_KEYS:
        d = (c.get("deltas") or {}).get(k)
        if isinstance(d, dict) and d.get("delta_db") is not None:
            deltas[k] = {"before": d.get("before"), "after": d.get("after"), "delta_db": d.get("delta_db"),
                         "tolerance_db": d.get("tolerance_db"), "pass": d.get("pass"),
                         "gain_compensated": d.get("gain_compensated")}
    return {"profile": o.get("profile"), "delivery": o.get("delivery"), "status": c.get("status"),
            "baseline": c.get("baseline"), "gain_db": c.get("gain_db"), "gain_source": c.get("gain_source"),
            "frame_selection": c.get("frame_selection"), "conformed": c.get("conformed"),
            "deltas": deltas, "suggestions": c.get("suggestions") or [],
            "plan_send_back": c.get("plan_send_back")}


def _cleanup_section(project, route: str, verify: dict, plan: dict) -> dict:
    """Section 7 (SPEC 6.8): cleanup steps run / light / skip per asset, removed energy per band,
    P-21 side effects, S-07 residual, the delta file for listening, the noise baseline and the S-08
    result of every output (with the planner's S-08 steps)."""
    from .cleanstage import BASELINE_FILE, cleanup_summary
    try:
        summ = cleanup_summary(project, route)
    except Exception as exc:  # informative section: report the reason instead of failing
        summ = {"status": "error", "assets": [], "error": str(exc)}
    assets = []
    for a in summ.get("assets") or []:
        removed = {}
        for band, r in (a.get("removed_energy") or {}).items():
            rel = (r or {}).get("removed_rel_db")
            removed[band] = {"range_hz": (r or {}).get("range_hz"), "removed_rel_db": rel,
                             "removed_dbfs": (r or {}).get("removed_dbfs"),
                             "sone_ratio": None if rel is None else round(ma.sone_ratio(float(rel)), 4)}
        p21 = a.get("p21") or {}
        width = {b: (w or {}).get("change_db") for b, w in (p21.get("width_change") or {}).items()}
        over = a.get("oversuppression") or {}
        steps = {k: v for k, v in (a.get("steps") or {}).items()}
        assets.append({
            "asset": a.get("asset"), "skipped": bool(a.get("skipped")), "plan_hash": a.get("plan_hash"),
            "steps": steps,
            "steps_by_action": {act: sorted(k for k, v in steps.items() if v == act) for act in ("run", "light", "skip")},
            "reasons": a.get("reasons"),
            "removed_energy": removed,
            "side_effects": {"rule": "P-21", "pass": p21.get("pass"),
                             "lowmid_250_500_change": _sone(p21.get("lowmid_250_500_change_db")),
                             "lowmid_tolerance_db": p21.get("lowmid_tolerance_db"),
                             "width_change_db": width, "width_tolerance_db": p21.get("width_tolerance_db")}
            if p21 else None,
            "s07": a.get("s07"),
            "oversuppression": {"flagged": over.get("flagged"), "rerun": over.get("rerun")} if over else None,
            "delta_file": a.get("delta"),
            "record": a.get("record"),
        })
    s08 = [x for x in (_s08_output(o) for o in verify.get("outputs", []) or []) if x is not None]
    guard = next((r for r in plan.get("rationale") or [] if r.get("stage") == "noise_return_guard"), None)
    s08_plan = None
    if guard:
        s08_plan = {"status": ((guard.get("expected") or {}).get("s08") or {}).get("status"),
                    "first": ((guard.get("measured") or {}).get("s08") or {}).get("status"),
                    "action": guard.get("action"),
                    "steps": [{"step": st.get("step"), "kind": st.get("kind"), "action": st.get("action"),
                               "result_s08": ((st.get("result") or {}).get("s08") or {}).get("status")}
                              for st in guard.get("steps") or []]}
    baseline_src = next((x["baseline"].get("source") for x in s08 if isinstance(x.get("baseline"), dict)), None)
    applied = summ.get("status") == "applied"
    return {
        "status": summ.get("status", "not_applied"),
        "error": summ.get("error"),
        "assets": assets,
        "noise_baseline": {"file": summ.get("noise_baseline") or (BASELINE_FILE if applied else None),
                           "source": baseline_src},
        "neural_completion_used": bool(summ.get("neural_completion_used", False)),
        "s08": s08,
        "s08_plan": s08_plan,
        "note": (T("整音は M5 の工程（ミックスとマスタリングの前。R-20）。除去分の音声（delta）を聴いて、息や子音が含まれていないかを確認する",
                   "Cleanup runs before mixing and mastering (R-20). Listen to the removed component (delta) for breaths or consonants")
                 if applied else
                 T("このマスターの入力には整音を適用していない。ノイズ戻り監視（S-08）の基準は、入力そのもの（未整音）である",
                   "No cleanup was applied to this master's input; the noise-return guard (S-08) uses the input as is (not cleaned) as its baseline")),
    }


def _listening_checks(x, sr, plan: dict, verify: dict, cleanup: dict | None = None) -> list[dict]:
    times = ma.section_times(x, sr)
    lim = ((plan.get("expected") or {}).get("limiter_gr")) or {}
    cond = T("音量を固定して聴く／処理前後はレベルマッチ版で比べる／複数の再生環境（モニター、ヘッドホン、スマートフォン）で聴く／耳を休めてから最終判断する（長時間の大音量の後は高域の判断が甘くなる）",
             "Listen at a fixed volume / compare before and after only level-matched / use several playback systems (monitors, headphones, smartphone) / decide with rested ears (after long loud listening, high-frequency judgement gets lenient)")
    out = [{"time_s": 0.0, "duration_s": min(10.0, times["duration_s"]),
            "point": T("最初の 10 秒: 処理前とのレベルマッチ比較で、音色（低域の量、高域の明るさ）が意図どおりか",
                       "First 10 s: in a level-matched comparison with the input, is the tone (low-end amount, top-end brightness) as intended?"),
            "conditions": cond}]
    if times.get("loudest_start_s") is not None:
        out.append({"time_s": times["loudest_start_s"], "duration_s": 3.0,
                    "point": T(f"最も大きい区間: リミッターでアタックが潰れていないか、ポンピングがないか（ゲインリダクション 95 パーセンタイル {lim.get('gr_p95_db', 0):.1f} dB、最大 {lim.get('gr_max_db', 0):.1f} dB）",
                               f"Loudest section: are attacks flattened or is there pumping from the limiter? (GR p95 {lim.get('gr_p95_db', 0):.1f} dB, max {lim.get('gr_max_db', 0):.1f} dB)"),
                    "conditions": cond})
        out.append({"time_s": times["loudest_start_s"], "duration_s": 3.0,
                    "point": T("最も大きい区間をモノで: 低音が痩せたり消えたりしないか、主役が引っ込まないか",
                               "Loudest section in mono: does the bass thin out or vanish, does the lead step back?"),
                    "conditions": cond})
    if times.get("quietest_start_s") is not None:
        out.append({"time_s": times["quietest_start_s"], "duration_s": 3.0,
                    "point": T("最も静かな区間: ノイズやヒスが目立っていないか、静と動のコントラストが残っているか（R-26）",
                               "Quietest section: is noise or hiss exposed, is the quiet/loud contrast preserved? (R-26)"),
                    "conditions": cond})
    for a in (cleanup or {}).get("assets") or []:
        if a.get("skipped") or not a.get("delta_file"):
            continue
        out.append({"time_s": 0.0, "duration_s": times["duration_s"], "file": a["delta_file"],
                    "point": T(f"除去分の音声（`{a['delta_file']}`、{a['asset']}）を聴く: 除去分の音声に息や子音が含まれていないか（含まれていれば整音が強すぎる）",
                               f"Listen to the removed component (`{a['delta_file']}`, {a['asset']}): does it contain breaths or consonants? (if so, the cleanup is too strong)"),
                    "conditions": cond})
    s08_fail = [x for x in (cleanup or {}).get("s08") or [] if x.get("status") == "fail"]
    s08_plan = (cleanup or {}).get("s08_plan") or {}
    corrected = any(st.get("result_s08") for st in s08_plan.get("steps") or [])
    if s08_fail or corrected:
        qt = times.get("quietest_start_s")
        worst = []
        for x_ in s08_fail:
            for k, d in (x_.get("deltas") or {}).items():
                if d.get("pass") is False:
                    worst.append((x_["profile"], k, d["delta_db"], d["tolerance_db"]))
        if s08_fail:
            det_ja = "、".join(f"{pr}: {_S08_NAMES[k]['ja']} {dd:+.1f} dB（許容 {tl:.1f} dB）" for pr, k, dd, tl in worst[:4])
            det_en = ", ".join(f"{pr}: {_S08_NAMES[k]['en']} {dd:+.1f} dB (tolerance {tl:.1f} dB)" for pr, k, dd, tl in worst[:4])
            point = T(f"最も静かな区間と 10 kHz 以上: マスター後にノイズやシマー（高域のチリチリしたゆらぎ）が戻っていないか、処理前とレベルマッチで比べる。S-08 は不合格（{det_ja}）",
                      f"Quietest section and above 10 kHz: has noise or shimmer (flickering HF grit) come back after mastering? Compare level-matched with the input. S-08 failed ({det_en})")
        else:
            point = T("最も静かな区間と 10 kHz 以上: ノイズ戻り監視（S-08）のためにリミッターの駆動を変えた（4 章の手順）。ノイズやシマーが戻っていないか、低域の歪みやアタックの変化がないか",
                      "Quietest section and above 10 kHz: the limiter drive was changed for the noise-return guard (S-08; steps in section 4). Has noise or shimmer come back, and are low-end distortion or attacks affected?")
        out.append({"time_s": qt if qt is not None else 0.0, "duration_s": 5.0, "point": point,
                    "conditions": cond, "rule": "S-08"})
    for o in verify.get("outputs", []) or []:
        s02 = (o.get("checks") or {}).get("S-02") or {}
        if (s02.get("render_iterations") or 0) > 1:
            out.append({"time_s": times.get("loudest_start_s"), "duration_s": 3.0,
                        "point": T(f"{o['profile']}: コーデック通過後の天井を守るため天井を {s02.get('final_limiter_ceiling_dbtp')} dBTP まで下げた。大きい区間で歪みや詰まりがないか",
                                   f"{o['profile']}: ceiling lowered to {s02.get('final_limiter_ceiling_dbtp')} dBTP for the codec-after ceiling; check the loud section for distortion or congestion"),
                        "conditions": cond})
    return out


def _constraints(verify: dict, gate: dict | None = None) -> list[dict]:
    out = []
    for o in verify.get("outputs", []) or []:
        checks = dict(o.get("checks") or {})
        of5 = checks.get("OF-5")
        if gate and gate.get("status") not in (None, "not_evaluated") and isinstance(of5, dict)                 and of5.get("status") == "not_evaluated":
            # verify does not run the gate; show the objective evaluation's result instead of a stale note
            checks["OF-5"] = {"status": gate["status"], "rule": "OF-5",
                              "reason": "see 'translation_gate' (objective evaluation of this master)"}
        out.append({"profile": o.get("profile"), "delivery": o.get("delivery"), "overall": o.get("overall"),
                    "checks": checks})
    if verify.get("archive"):
        out.append({"profile": None, "delivery": ARCHIVE_DELIVERY, "overall": verify["archive"].get("overall"),
                    "checks": verify["archive"].get("checks")})
    return out


def _notes(project, obj: dict, oe: dict | None = None) -> list[dict]:
    data = project.data
    notes = []
    genre = data.get("genre")
    if not genre:
        notes.append({"code": "genre_unset", "rule": "D-053",
                      "text": T("ジャンル未指定のため汎用の初期値で評価した（ジャンルは音から自動推定しない）",
                                "No genre declared, so generic initial values were used (genre is never inferred from audio)")})
    else:
        try:
            label = config.get_genre_prior(genre).get("label", {})
        except Exception:
            label = {"ja": genre, "en": genre}
        notes.append({"code": "genre_prior", "rule": "R-33",
                      "text": T(f"ジャンル「{label.get('ja', genre)}」の prior は、目的関数の重みと目標範囲の初期値にだけ使う（[慣行]）。リファレンスの実測とユーザーの指定が常に優先する",
                                f"The genre prior '{label.get('en', genre)}' only sets the initial weights and target ranges of the objective (practice level); measured references and user settings always take precedence")})
    refs = [r for r in data.get("references") or [] if isinstance(r, dict)]
    used = ((oe or {}).get("resolved") or {}).get("reference") or {}
    if not refs:
        notes.append({"code": "generic_prior", "rule": "R-17",
                      "text": T("リファレンスが登録されていないため、汎用の目安に対する評価であり、ジャンルに合わせた評価ではない。v1 は市販曲から得た統計を同梱しない（D-039）。手元の曲を reference add で登録すると、その測定ベクトルの分布が目標範囲になる",
                                "No references are registered: this is an evaluation against a generic prior, not a genre-specific one. v1 ships no statistics taken from commercial tracks (D-039); registering your own tracks with reference add makes their measured distribution the target ranges")})
    elif used.get("source") == "generic_prior":
        notes.append({"code": "references_not_in_evaluation", "rule": "R-17",
                      "text": T(f"リファレンスは {len(refs)} 曲登録されているが、この評価はその登録より前の提案で行われ、汎用の目安に対する評価になっている。plan propose で提案し直すと反映される",
                                f"{len(refs)} reference(s) are registered, but this evaluation comes from a proposal made before they were registered and uses the generic prior; propose again with plan propose to use them")})
    else:
        notes.append({"code": "references_used", "rule": "R-17",
                      "text": T(f"目標範囲は、ユーザーが登録したリファレンス {len(refs)} 曲の実測分布（中央値と四分位範囲、レベルマッチ後）から取った。リファレンスの音声はプロジェクトに含めず、測定ベクトルだけを保存している（SPEC 4.6、D-039）。スペクトルをそのまま写す EQ マッチはしない",
                                f"Target ranges come from the measured distribution (median and IQR, level matched) of the {len(refs)} reference(s) registered by the user. Reference audio is never stored in the project, only measurement vectors (SPEC 4.6, D-039). No spectrum-copying EQ match is done")})
    for oid in objective_ids(obj):
        if oid in _provisional_ids():
            notes.append({"code": "weak_evidence_objective", "objective": oid, "rule": "SPEC 4.4",
                          "text": T(f"「{oid}」は暫定の目的関数で、聴覚疲労を定量した査読研究は弱い。Mix Report の評価は弱証拠に基づく",
                                    f"'{oid}' is a provisional objective; peer-reviewed evidence quantifying listening fatigue is weak, so its evaluation rests on weak evidence")})
    for oid in objective_ids(obj):
        try:
            od = config.get_objective(oid)
        except Exception:
            continue
        if "normalization_tradeoff" in (od.get("report_notes") or []):
            notes.append({"code": "normalization_tradeoff", "objective": oid,
                          "text": T("低域（サブ）を上げると、再生側のラウドネス正規化で曲全体が下げられ、中域が相対的に下がる。重低音の強化はこのトレードオフと引き換えになる",
                                    "Raising the sub band makes playback loudness normalization turn the whole track down, so the midrange drops relatively. Bass emphasis comes at this trade-off")})
    return notes


def _tradeoffs(plan: dict, verify: dict, notes: list[dict], breakdown: dict | None = None,
               gate: dict | None = None) -> list[dict]:
    out = []
    sb = plan.get("send_back")
    if sb:
        out.append({"kind": "send_back", "rule": sb.get("rule"), "text": sb.get("reason"), "measured": sb.get("measured"),
                    **({"suggestions": sb["suggestions"]} if sb.get("suggestions") else {})})
        for a in sb.get("also") or []:
            out.append({"kind": "send_back", "rule": a.get("rule"), "text": a.get("reason"), "measured": a.get("measured"),
                        **({"suggestions": a["suggestions"]} if a.get("suggestions") else {})})
    for w in plan.get("warnings", []) or []:
        out.append({"kind": "warning", "rule": w.get("rule"), "text": w.get("message"), "code": w.get("code")})
    for o in verify.get("outputs", []) or []:
        for k, c in (o.get("checks") or {}).items():
            if c.get("status") in ("fail", "not_run"):
                out.append({"kind": "unresolved", "rule": k,
                            "text": T(f"{o['profile']} / {o['delivery']}: {k} は {c['status']}",
                                      f"{o['profile']} / {o['delivery']}: {k} is {c['status']}")})
    out.append({"kind": "weak_evidence", "rule": None,
                "text": T("閾値（リミッター依存度、モノ損失、低域の逆相の持続）は [慣行] の初期値で、較正の対象である",
                          "Thresholds (limiter dependency, mono loss, low-band anti-phase persistence) are practice-level initial values subject to calibration")})
    for t in (breakdown or {}).get("terms") or []:
        if t.get("status") == "measured" and (t.get("penalty") or 0.0) > 0.25:
            out.append({"kind": "off_target", "rule": t.get("metric"), "text": T(
                f"{t.get('objective')} / {t.get('key')}: 目標 {_fmt_num(t.get('target'))} に対して {_fmt_num(t.get('value'))}（penalty {_fmt_num(t.get('penalty'))}）。達成できていない",
                f"{t.get('objective')} / {t.get('key')}: {_fmt_num(t.get('value'))} against the target {_fmt_num(t.get('target'))} (penalty {_fmt_num(t.get('penalty'))}); not achieved")})
    nm = [t for t in (breakdown or {}).get("terms") or [] if t.get("status") not in (None, "measured")]
    if nm:
        keys = ", ".join(sorted({str(t.get("key")) for t in nm}))
        out.append({"kind": "not_measured", "rule": None, "text": T(
            f"測定できなかった項（{keys}）の重みは、同じ目的関数の測定できた項へ比例配分した。ステムや整音段がないと測れない指標がある",
            f"Terms that could not be measured ({keys}) had their weight redistributed to the measured terms of the same objective; some metrics need stems or the cleanup stage")})
    if gate and gate.get("status") in ("fail", "incomplete"):
        out.append({"kind": "gate_" + gate["status"], "rule": "OF-5", "text": gate.get("meaning")})
    for w in (breakdown or {}).get("weak_evidence") or []:
        out.append({"kind": "weak_evidence", "rule": "SPEC 4.4", "text": w.get("text")})
    for n in notes:
        if n["code"] in ("generic_prior", "normalization_tradeoff", "references_not_in_evaluation"):
            out.append({"kind": "note", "rule": n.get("rule"), "text": n["text"]})
    return out


def _reproducibility(project, variant_id: str, outputs: list[dict]) -> dict:
    mans = []
    a = load_manifest(project, variant_id, None, ARCHIVE_DELIVERY)
    if a:
        mans.append(a)
    for o in outputs:
        m = load_manifest(project, variant_id, o["profile"], o["delivery"])
        if m:
            mans.append(m)
    ff = None
    entries = []
    for m in mans:
        f = (m.get("backends") or {}).get("ffmpeg") or {}
        if f.get("used"):
            ff = {"version": f.get("version"), "configuration": f.get("configuration"), "build": f.get("build")}
        entries.append({"file": m.get("file"), "file_sha256": m.get("file_sha256"),
                        "dither_seed": (m.get("dither") or {}).get("seed"),
                        "limiter_ceiling_dbtp": m.get("final_limiter_ceiling_dbtp"),
                        "iterations": (m.get("s02") or {}).get("iteration_count"),
                        "definitions": m.get("definitions")})
    first = mans[0] if mans else {}
    from mankomix.dspx.bb.ml import report_records
    model_records, fallback_steps, render_warnings = [], [], []
    for manifest, entry in zip(mans, entries):
        records = report_records(manifest.get("steps") or [])
        fallbacks = [s for s in manifest.get("steps") or [] if s.get("fallback")]
        warnings = list(manifest.get("render_warnings") or [])
        if not records and not fallbacks and not any("rendered with fallback" in w for w in warnings):
            warnings = []
        if records or fallbacks or warnings:
            entry["render_warnings"] = warnings
            entry["steps"] = manifest.get("steps") or []
        for collection, values in ((model_records, records), (fallback_steps, fallbacks),
                                   (render_warnings, warnings)):
            for value in values:
                if value not in collection:
                    collection.append(value)
    if model_records or fallback_steps or render_warnings:
        return {"project_hash": first.get("project_hash"),
                "engine_version": first.get("engine_version", mankomix.__version__),
                "assets": first.get("assets", []),
                "backends": {"engine": "mankomix.dsp (reference backend)", "ffmpeg": ff,
                             "ffmpeg_note": T("FFmpeg は同梱せず、ユーザー環境のものを外部プロセスとして呼ぶ。ビルド構成を記録する",
                                              "FFmpeg is not bundled; the user's build is called as an external process and its build configuration is recorded")},
                "models": [r for r in model_records if not r.get("fallback_used") and not r.get("inference_skipped")],
                "models_note": T("モデル推論・代替処理の実行記録を参照", "See the executed model and fallback records"),
                "outputs": entries,
                "promise": T("同じ正本・素材・エンジンの版・バックエンドの版なら同じ出力になる（同一環境ではビット一致）",
                             "Same project, assets, engine and backend versions give the same output (bit-identical in the same environment)"),
                "model_records": model_records, "fallback_steps": fallback_steps,
                "render_warnings": render_warnings}
    return {"project_hash": first.get("project_hash"), "engine_version": first.get("engine_version", mankomix.__version__),
            "assets": first.get("assets", []),
            "backends": {"engine": "mankomix.dsp (reference backend)", "ffmpeg": ff,
                         "ffmpeg_note": T("FFmpeg は同梱せず、ユーザー環境のものを外部プロセスとして呼ぶ。ビルド構成を記録する",
                                          "FFmpeg is not bundled; the user's build is called as an external process and its build configuration is recorded")},
            "models": [], "models_note": T("このレンダリングはモデルを使っていない", "No models were used in this render"),
            "outputs": entries,
            "promise": T("同じ正本・素材・エンジンの版・バックエンドの版なら同じ出力になる（同一環境ではビット一致）",
                         "Same project, assets, engine and backend versions give the same output (bit-identical in the same environment)")}


# --------------------------------------------------------------------------
# public API


def build_report(project, variant_id: str, *, lang: str = "ja") -> dict:
    """Build the Mix Report dict. lang: "ja", "en", or "both" (bilingual text objects)."""
    if lang not in ("ja", "en", "both"):
        raise InputError(f"unsupported report language '{lang}'", details={"valid": ["ja", "en", "both"]})
    data = project.data
    variant = find_variant(data, variant_id)
    if variant is None:
        raise InputError(f"unknown variant '{variant_id}'")
    master = variant.get("master") or {}
    plan = master.get("plan") or {}
    obj = variant.get("objective") or data.get("objective") or {}
    verify = _load_verify(project, variant_id)
    route = variant_route(project, variant)
    x, sr = load_master_input(project, route, variant_id=variant_id)
    ad = config.get_delivery(ARCHIVE_DELIVERY)
    apath = variant_dir(project, variant_id) / f"master__{ARCHIVE_DELIVERY}.{output_ext(ad)}"
    outputs = variant.get("outputs") or []
    oe = _objective_evaluation(project, variant, x, sr, apath)
    cleanup = _cleanup_section(project, route, verify, plan)
    notes = _notes(project, obj, oe)
    breakdown = _breakdown(oe, obj)
    gate = _gate_section(oe)

    result = verify.get("overall", "incomplete")
    if result == "pass" and (plan.get("send_back") or plan.get("warnings")):
        result = "warning"

    report = {
        "schema_version": 1,
        "language": lang,
        "variant": variant_id,
        "summary": {
            "project": data.get("title"),
            "project_id": data.get("id"),
            "objective": obj,
            "profiles": sorted({o.get("profile") for o in outputs}),
            "outputs": [{"profile": o.get("profile"), "delivery": o.get("delivery"),
                         "result": next((v.get("overall") for v in verify.get("outputs", [])
                                         if v.get("profile") == o.get("profile") and v.get("delivery") == o.get("delivery")), None),
                         "file": next((v.get("file") for v in verify.get("outputs", [])
                                       if v.get("profile") == o.get("profile") and v.get("delivery") == o.get("delivery")), None)}
                        for o in outputs],
            "route": {"route": route, "reason": plan.get("route_reason"), "rule": "R-21"},
            "result": result,
            "send_back": plan.get("send_back"),
            "objective_score": breakdown.get("score"),
            "objective_score_before": breakdown.get("score_before"),
            "translation_gate": gate.get("status"),
        },
        "inputs": {
            "assets": [{k: a.get(k) for k in ("id", "path", "sha256", "role", "origin", "sample_rate", "channels",
                                               "length_samples")} for a in data.get("assets", []) or []],
            "provenance": data.get("provenance"),
            "ingest_checks": (data.get("ingest") or {}).get("checks", []),
            "stem_sum_consistency": None,
            "stem_sum_note": T("ステム合算の整合は解析段（analyze）の結果を参照。このレポートでは再評価しない",
                               "Stem-sum consistency comes from the analysis stage; not re-evaluated in this report"),
        },
        "measurements": _measurements(project, variant, x, sr, apath, oe),
        "decisions": _decisions(plan, variant.get("decisions") if oe.get("source") == "stored_proposal" else None,
                                len(data.get("references") or [])),
        "objective_breakdown": breakdown,
        "constraints": _constraints(verify, gate),
        "objective_constraints": _objective_constraints(oe),
        "translation_gate": gate,
        "cleanup": cleanup,
        "tradeoffs": _tradeoffs(plan, verify, notes, breakdown, gate),
        "listening_checks": _listening_checks(x, sr, plan, verify, cleanup),
        "reproducibility": _reproducibility(project, variant_id, outputs),
        "notes": notes,
        "chain": master.get("chain", []),
    }
    report = json.loads(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return report if lang == "both" else _resolve(report, lang)


_SEC = {
    1: T("1. 概要", "1. Summary"),
    2: T("2. 入力と出所", "2. Inputs and provenance"),
    3: T("3. 測定（前後比較）", "3. Measurements (before / after)"),
    4: T("4. 判断の記録", "4. Decision log"),
    5: T("5. 目的関数の達成度", "5. Objective achievement"),
    6: T("6. 制約とゲート", "6. Constraints and gates"),
    7: T("7. 整音の記録", "7. Cleanup record"),
    8: T("8. トレードオフと未解決事項", "8. Trade-offs and open issues"),
    9: T("9. 人の耳で確認すべき点", "9. Listening checks (human ears decide)"),
    10: T("10. 再現情報", "10. Reproducibility"),
}
_EL = {"balance": T("バランス", "Balance"), "panning": T("定位", "Panning"), "frequency": T("周波数", "Frequency"),
       "depth": T("奥行き", "Depth"), "dynamics": T("ダイナミクス", "Dynamics"), "interest": T("仕掛け", "Interest")}


def _mmss(t) -> str:
    if t is None:
        return "-"
    t = float(t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def render_markdown(report: dict, lang: str = "ja") -> str:
    """Render a report (bilingual or single-language) as Markdown."""
    if lang not in LANGS:
        raise InputError(f"unsupported report language '{lang}'")
    r = _resolve(report, lang) if report.get("language") in ("both", None) else report
    s = r.get("summary", {})
    L = []
    t = lambda o: _txt(o, lang)  # noqa: E731
    L.append(f"# Mix Report — {s.get('project') or s.get('project_id')} / {r.get('variant')}")
    L.append("")
    L.append("## " + t(_SEC[1]))
    L.append(f"- {t(T('総合結果', 'Overall result'))}: **{s.get('result')}**")
    route = s.get("route") or {}
    L.append(f"- {t(T('経路', 'Route'))}: {route.get('route')} ({route.get('rule')}) — {t(route.get('reason'))}")
    blend = ", ".join(f"{b.get('id')}×{b.get('weight')}" for b in (s.get("objective") or {}).get("blend", []))
    L.append(f"- {t(T('目的関数', 'Objective'))}: {blend} / intensity {(s.get('objective') or {}).get('intensity')}")
    for o in s.get("outputs", []):
        L.append(f"- {t(T('出口', 'Output'))}: {o.get('profile')} × {o.get('delivery')} → {o.get('result')} (`{o.get('file')}`)")
    if s.get("objective_score") is not None:
        L.append(f"- {t(T('目的関数の score（0 が理想、内訳は 5 章）', 'Objective score (0 is ideal; breakdown in section 5)'))}: "
                 f"{_fmt_num(s.get('objective_score_before'), 3)} → **{_fmt_num(s.get('objective_score'), 3)}**")
    if s.get("translation_gate"):
        L.append(f"- {t(T('トランスレーション・ゲート（OF-5）', 'Translation gate (OF-5)'))}: {s.get('translation_gate')}")
    if s.get("send_back"):
        L.append(f"- **{t(T('差し戻し', 'Send back'))} ({s['send_back'].get('rule')})**: {t(s['send_back'].get('reason'))}")
        for a in s["send_back"].get("also") or []:
            L.append(f"- **{t(T('差し戻し', 'Send back'))} ({a.get('rule')})**: {t(a.get('reason'))}")
    for n in r.get("notes", []):
        L.append(f"- {t(n.get('text'))}")
    L.append("")

    L.append("## " + t(_SEC[2]))
    for a in r.get("inputs", {}).get("assets", []):
        L.append(f"- `{a.get('path')}` ({a.get('role')}, {a.get('origin')}, {a.get('sample_rate')} Hz) sha256 `{(a.get('sha256') or '')[:16]}…`")
    checks = r.get("inputs", {}).get("ingest_checks") or []
    L.append(f"- {t(T('取り込み検査', 'Ingest checks'))}: {len(checks)}")
    for c in checks[:20]:
        L.append(f"  - [{c.get('level')}] {c.get('check')}: {c.get('message')}")
    L.append(f"- {t(r.get('inputs', {}).get('stem_sum_note'))}")
    L.append("")

    L.append("## " + t(_SEC[3]))
    m = r.get("measurements", {})
    L.append(f"_{t(m.get('assumed_playback'))}_")
    L.append("")
    b, a = m.get("before") or {}, m.get("after") or {}
    L.append(f"| {t(T('指標', 'Metric'))} | {t(T('処理前', 'Before'))} | {t(T('処理後', 'After'))} |")
    L.append("|---|---|---|")
    for k, lab in (("integrated_lufs", "LUFS-I"), ("short_term_max_lufs", "Short-term max"), ("lra_lu", "LRA"),
                   ("true_peak_dbtp", "True peak dBTP"), ("plr_db", "PLR"), ("psr_db", "PSR")):
        fb = "-" if b.get(k) is None else f"{b[k]:.2f}"
        fa = "-" if a.get(k) is None else f"{a[k]:.2f}"
        L.append(f"| {lab} | {fb} | {fa} |")
    lc = m.get("loudness_change")
    if lc:
        L.append("")
        L.append(f"- {t(T('ラウドネスの変化', 'Loudness change'))}: {_fmt_db(lc['delta_db'], lang)}")
    comp = m.get("comparison") or {}
    if comp.get("deltas"):
        L.append(f"- {t(T('レベルマッチ後の差（処理後 − 処理前）', 'Level-matched differences (after - before)'))}, "
                 f"match gain {comp.get('match_gain_db')} dB:")
        for k, d in comp["deltas"].items():
            if d.get("delta") is None:
                continue
            if d.get("perceived_ratio") is not None:
                L.append(f"  - {k}: {_fmt_db(d['delta'], lang)}")
            else:
                L.append(f"  - {k}: {d['delta']:+.2f} {d.get('unit', '')}")
    if m.get("objective_metrics"):
        L.append("")
        L.append(f"_{t(m.get('objective_metrics_note'))}_")
        L.append("")
        L.append(f"| {t(T('目的関数', 'Objective'))} | {t(T('指標', 'Metric'))} | {t(T('処理前', 'Before'))} | {t(T('処理後', 'After'))} | {t(T('単位', 'Unit'))} |")
        L.append("|---|---|---|---|---|")
        for om in m["objective_metrics"]:
            L.append(f"| {om.get('objective')} | {om.get('metric')} | {_fmt_num(om.get('before'))} | "
                     f"{_fmt_num(om.get('after'))} | {om.get('unit') or ''} |")
    L.append("")

    L.append("## " + t(_SEC[4]))
    for el, items in (r.get("decisions") or {}).items():
        L.append(f"### {t(_EL.get(el, T(el, el)))}")
        for d in items:
            L.append(f"- {t(T('行動', 'Action'))}: {t(d.get('action'))}" + (f" [{d.get('rule')}]" if d.get("rule") else "")
                     + (f" ({d.get('status')})" if d.get("status") else ""))
            if d.get("references"):
                L.append(f"  - {t(T('リファレンス', 'References'))}: {t(d.get('references'))}")
            if d.get("measured"):
                L.append(f"  - {t(T('測定', 'Measured'))}: `{_j(d.get('measured'))}`")
            for v in d.get("vocabulary", []) or []:
                g = v.get("gain_db")
                L.append(f"  - {v.get('band')}: {_fmt_db(g, lang) if isinstance(g, (int, float)) else '-'} — {t(v.get('vocabulary'))}")
            if d.get("alternatives"):
                L.append(f"  - {t(T('代替案', 'Alternatives'))}: " + "; ".join(t(x) for x in d["alternatives"]))
            if d.get("result"):
                L.append(f"  - {t(T('結果（予測）', 'Result (expected)'))}: `{_j(d.get('result'))}`")
            for st in d.get("steps") or []:
                L.append(f"  - {t(T('手順', 'Step'))} {st.get('step')} [{st.get('rule')}]: {t(st.get('action'))}")
                ms = ((st.get("measured") or {}).get("s08") or {})
                if ms:
                    L.append(f"    - {t(T('測定', 'Measured'))}: S-08 {ms.get('status')} `{_j(ms.get('deltas'))}`")
                if st.get("alternatives"):
                    L.append(f"    - {t(T('代替案', 'Alternatives'))}: " + "; ".join(t(x) for x in st["alternatives"]))
                if st.get("result"):
                    rs = st["result"]
                    L.append(f"    - {t(T('結果（シミュレーション）', 'Result (simulated)'))}: S-08 {(rs.get('s08') or {}).get('status')}, "
                             f"{rs.get('lufs_i')} LUFS, GR p95 {rs.get('limiter_gr_p95_db')} dB"
                             + (f", {_j(rs.get('limiter_style'))}" if rs.get("limiter_style") else "")
                             + f" `{_j((rs.get('s08') or {}).get('deltas'))}`")
    L.append("")

    L.append("## " + t(_SEC[5]))
    ob = r.get("objective_breakdown") or {}
    if ob.get("status") != "evaluated":
        L.append(f"- {t(ob.get('note'))} ({ob.get('status')})")
        if ob.get("reason"):
            L.append(f"- {ob.get('reason')}")
    else:
        o = ob.get("objective") or {}
        blend = ", ".join(f"{b.get('id')}×{_fmt_num(b.get('weight'), 2)}" for b in o.get("blend") or [])
        ref = o.get("reference") or {}
        ref_txt = (t(T(f"リファレンス {ref.get('n')} 曲の実測分布", f"measured distribution of {ref.get('n')} reference(s)"))
                   if ref.get("source") == "references" else t(T("汎用 prior（ジャンルに合わせた評価ではない）", "generic prior (not genre-specific)")))
        L.append(f"- {t(T('目的関数', 'Objective'))}: {blend} / intensity {o.get('intensity')} / "
                 f"{t(T('目標の出どころ', 'targets from'))}: {ref_txt}")
        lead = o.get("lead") or {}
        if lead.get("stem"):
            L.append(f"- {t(T('主役', 'Lead'))}: {lead.get('stem')}" + (f" ({t(T('推定', 'estimated'))})" if lead.get("estimated") else ""))
        L.append(f"- {t(T('評価の出どころ', 'Evaluated from'))}: {t(ob.get('source_label'))} ({ob.get('scope')})"
                 + (f", proposal `{ob.get('proposal_id')}`" if ob.get("proposal_id") else ""))
        L.append(f"- score: {t(T('処理前', 'before'))} {_fmt_num(ob.get('score_before'), 3)} → "
                 f"{t(T('処理後', 'after'))} **{_fmt_num(ob.get('score'), 3)}** "
                 + "(" + ", ".join(f"{k} {_fmt_num(v, 3)}" for k, v in (ob.get("score_by_objective") or {}).items()) + ")")
        L.append("")
        L.append(f"| {t(T('目的関数', 'Objective'))} | {t(T('指標', 'Metric'))} | {t(T('状態', 'Status'))} | "
                 f"{t(T('値（前 → 後）', 'Value (before → after)'))} | {t(T('目標', 'Target'))} | "
                 f"{t(T('penalty（前 → 後）', 'Penalty (before → after)'))} | {t(T('実効重み', 'Eff. weight'))} | {t(T('寄与', 'Contribution'))} |")
        L.append("|---|---|---|---|---|---|---|---|")
        for row in ob.get("terms") or []:
            st = row.get("status")
            if st != "measured" and row.get("reason"):
                st = f"{st}: {row.get('reason')}"
            L.append(f"| {row.get('objective')} | {row.get('key')} | {st} | "
                     f"{_fmt_num(row.get('value_before'))} → {_fmt_num(row.get('value'))} {row.get('unit') or ''} | "
                     f"{_fmt_num(row.get('target'))} | {_fmt_num(row.get('penalty_before'), 3)} → {_fmt_num(row.get('penalty'), 3)} | "
                     f"{_fmt_num(row.get('effective_weight'), 3)} | {_fmt_num(row.get('contribution'), 3)} |")
        for rd in ob.get("redistribution") or []:
            L.append(f"- {t(T('重みの再配分', 'Weight redistribution'))} ({rd.get('objective')}): "
                     f"{', '.join(rd.get('terms') or [])} → {_fmt_num(rd.get('moved_weight'), 3)}")
        for w in ob.get("weak_evidence") or []:
            L.append(f"- **{t(T('弱証拠', 'Weak evidence'))}**: {t(w.get('text'))}")
        if ob.get("stale_note"):
            L.append(f"- {t(ob.get('stale_note'))}")
        L.append(f"- {t(ob.get('note'))}")
    L.append("")

    L.append("## " + t(_SEC[6]))
    for c in r.get("constraints", []):
        L.append(f"### {c.get('profile') or 'archive'} × {c.get('delivery')} — {c.get('overall')}")
        L.append(f"| {t(T('検査', 'Check'))} | {t(T('結果', 'Status'))} | {t(T('値', 'Values'))} |")
        L.append("|---|---|---|")
        for k, v in (c.get("checks") or {}).items():
            vals = {kk: vv for kk, vv in v.items() if kk not in ("status", "rule", "codecs", "issues", "facts", "reason", "note")}
            if v.get("codecs"):
                vals["codecs"] = {cc: {"status": x.get("status"), "tp": x.get("true_peak_dbtp")} for cc, x in v["codecs"].items()}
            extra = v.get("reason") or ""
            L.append(f"| {k} | {v.get('status')} | `{_j(vals)}` {extra} |")
    oc = r.get("objective_constraints") or {}
    if oc.get("statuses"):
        L.append(f"### {t(T('安全不変条件（目的関数の評価時）', 'Safety invariants (at objective evaluation)'))}")
        L.append(f"_{t(oc.get('note'))}_")
        L.append("")
        L.append(" / ".join(f"{k}: {v}" for k, v in oc["statuses"].items()))
    g = r.get("translation_gate") or {}
    L.append(f"### {t(T('トランスレーション・ゲート（OF-5）', 'Translation gate (OF-5)'))} — {g.get('status')}")
    if g.get("meaning"):
        L.append(f"_{t(g.get('meaning'))}_")
    if g.get("checks"):
        L.append("")
        L.append(f"| {t(T('検査', 'Check'))} | {t(T('必須', 'Required'))} | {t(T('結果', 'Status'))} | {t(T('理由', 'Reason'))} |")
        L.append("|---|---|---|---|")
        for c in g["checks"]:
            L.append(f"| {c.get('id')} | {c.get('required')} | {c.get('status')} | {c.get('reason') or ''} |")
    for sug in g.get("corrective_suggestions") or []:
        L.append(f"- {t(T('是正案', 'Correction'))}: {t(sug.get('text') if isinstance(sug, dict) and sug.get('text') else sug)}")
    for n in g.get("notes") or []:
        L.append(f"- {t(n)}")
    L.append("")

    L.append("## " + t(_SEC[7]))
    _render_cleanup(L, r.get("cleanup") or {}, lang)
    L.append("")

    L.append("## " + t(_SEC[8]))
    for x in r.get("tradeoffs", []):
        L.append(f"- [{x.get('kind')}{(' ' + x['rule']) if x.get('rule') else ''}] {t(x.get('text'))}")
    L.append("")

    L.append("## " + t(_SEC[9]))
    checks = r.get("listening_checks", [])
    if checks:
        L.append(f"**{t(T('試聴の条件', 'Listening conditions'))}**: {t(checks[0].get('conditions'))}")
        L.append("")
    for c in checks:
        L.append(f"- [{_mmss(c.get('time_s'))}] {t(c.get('point'))}")
    L.append("")

    L.append("## " + t(_SEC[10]))
    rep = r.get("reproducibility") or {}
    L.append(f"- project hash: `{rep.get('project_hash')}`")
    L.append(f"- engine: mankomix {rep.get('engine_version')} — {(rep.get('backends') or {}).get('engine')}")
    ff = (rep.get("backends") or {}).get("ffmpeg")
    if ff:
        L.append(f"- ffmpeg: {ff.get('version')} (build: {ff.get('build')})")
        L.append(f"  - configuration: `{ff.get('configuration')}`")
    else:
        L.append(f"- ffmpeg: {t(T('使用せず', 'not used'))}")
    L.append(f"- {t((rep.get('backends') or {}).get('ffmpeg_note'))}")
    L.append(f"- {t(rep.get('models_note'))}")
    for warning in rep.get("render_warnings", []):
        L.append(f"- {t(T('描画警告', 'Render warning'))}: {warning}")
    for step in rep.get("fallback_steps", []):
        L.append(f"- {t(T('代替処理', 'Fallback'))}: `{_j(step)}`")
    for model in rep.get("model_records", []):
        L.append(f"- {t(T('モデル実行記録', 'Model execution record'))}: `{_j(model)}`")
    for e in rep.get("outputs", []):
        L.append(f"- `{e.get('file')}`: seed {e.get('dither_seed')}, ceiling {e.get('limiter_ceiling_dbtp')} dBTP, "
                 f"iterations {e.get('iterations')}, sha256 `{(e.get('file_sha256') or '')[:16]}…`")
    L.append(f"- {t(rep.get('promise'))}")
    L.append("")
    return "\n".join(L)


def _render_cleanup(L: list, c: dict, lang: str) -> None:
    """Markdown of section 7 (cleanup record and the noise-return guard)."""
    t = lambda o: _txt(o, lang)  # noqa: E731
    status = {"applied": T("適用済み", "applied"), "not_applied": T("未適用", "not applied")}.get(c.get("status"))
    L.append(f"- {t(T('整音', 'Cleanup'))}: {t(status) if status else c.get('status')}")
    if c.get("error"):
        L.append(f"- {t(T('記録を読めなかった', 'Records could not be read'))}: {c['error']}")
    L.append(f"- {t(c.get('note'))}")
    for a in c.get("assets") or []:
        L.append(f"### {a.get('asset')}" + (f" — {t(T('スキップ（検出なし）', 'skipped (nothing detected)'))}" if a.get("skipped") else ""))
        steps = a.get("steps") or {}
        if steps:
            L.append(f"- {t(T('工程', 'Steps'))}: " + ", ".join(f"{t(_STEP_NAMES.get(k, T(k, k)))} = {v}" for k, v in steps.items()))
        reasons = a.get("reasons") or {}
        if isinstance(reasons, dict):
            for k, rs in reasons.items():
                if rs:
                    L.append(f"  - {k}: " + "; ".join(str(x) for x in (rs if isinstance(rs, list) else [rs])))
        elif reasons:
            L.append("  - " + "; ".join(str(x) for x in reasons))
        rem = a.get("removed_energy") or {}
        if rem:
            L.append("")
            L.append(f"| {t(T('帯域', 'Band'))} | Hz | {t(T('除去量（入力比）', 'Removed (re input)'))} | {t(T('知覚上の大きさ（sone 比）', 'Perceived loudness (sone ratio)'))} | dBFS |")
            L.append("|---|---|---|---|---|")
            for band, r in rem.items():
                rng = r.get("range_hz") or [None, None]
                rel = r.get("removed_rel_db")
                L.append(f"| {band} | {_fmt_num(rng[0], 0)}–{_fmt_num(rng[1], 0)} | "
                         f"{'-' if rel is None else f'{rel:+.1f} dB'} | {_fmt_num(r.get('sone_ratio'), 3)} | {_fmt_num(r.get('removed_dbfs'), 1)} |")
            L.append("")
        se = a.get("side_effects")
        if se:
            lm = se.get("lowmid_250_500_change") or {}
            L.append(f"- {t(T('副作用（P-21）', 'Side effects (P-21)'))}: {se.get('pass')} — 250–500 Hz "
                     f"{_fmt_db(lm.get('delta_db'), lang) if lm else '-'} ({t(T('許容', 'tolerance'))} ±{se.get('lowmid_tolerance_db')} dB), "
                     f"{t(T('幅の変化', 'width change'))} `{_j(se.get('width_change_db'))}` ({t(T('許容', 'tolerance'))} -{se.get('width_tolerance_db')} dB)")
        s07 = a.get("s07") or {}
        if s07:
            L.append(f"- S-07 {t(T('低域保護帯の残差', 'low-band residual'))}: {_fmt_num(s07.get('residual_dbfs'), 1)} dBFS "
                     f"({t(T('上限', 'limit'))} {s07.get('limit_dbfs')} dBFS, {s07.get('crossover_hz')} Hz) → {s07.get('pass')}")
        ov = a.get("oversuppression") or {}
        if ov.get("rerun"):
            L.append(f"- {t(T('過剰除去の検出により弱めて再実行した', 'Over-suppression detected: re-run with less strength'))}")
        if a.get("delta_file"):
            L.append(f"- {t(T('除去分の音声（試聴用）', 'Removed component (for listening)'))}: `{a['delta_file']}`")
    nb = c.get("noise_baseline") or {}
    L.append(f"- {t(T('ノイズ戻り監視の基準', 'Noise-return baseline'))}: "
             + (f"`{nb['file']}` — " if nb.get("file") else "") + (nb.get("source") or "-"))
    sp = c.get("s08_plan")
    if sp:
        L.append(f"- {t(T('計画時の S-08（シミュレーション）', 'S-08 at planning (simulated)'))}: {sp.get('first')} → {sp.get('status')} — {t(sp.get('action'))}")
        for st in sp.get("steps") or []:
            L.append(f"  - {t(T('手順', 'step'))} {st.get('step')}: {t(st.get('action'))}" + (f" → {st['result_s08']}" if st.get("result_s08") else ""))
    rows = c.get("s08") or []
    if rows:
        L.append("")
        L.append(f"| {t(T('出口', 'Output'))} | S-08 | {t(T('ゲイン補正', 'Gain comp.'))} | "
                 + " | ".join(t(_S08_NAMES[k]) for k in _S08_KEYS[:4]) + " |")
        L.append("|---|---|---|" + "---|" * 4)
        for x in rows:
            cells = []
            for k in _S08_KEYS[:4]:
                d = (x.get("deltas") or {}).get(k)
                cells.append("-" if not d else f"{d['delta_db']:+.2f} / {d['tolerance_db']:.1f}" + ("" if d.get("pass") else " ✗"))
            L.append(f"| {x.get('profile')} × {x.get('delivery')} | {x.get('status')} | {_fmt_num(x.get('gain_db'))} dB | " + " | ".join(cells) + " |")
        L.append("")
        L.append(f"_{t(T('値は 増加量 / 許容幅（dB）。レベル系はマスターのゲイン変化（統合ラウドネスの差）を補正済み。マスターは基準と同じフレーム（時刻を揃えた静かな区間とオンセットのゲート）で測る', 'Values are rise / tolerance (dB). Level metrics are compensated by the master gain change (integrated loudness difference); the master is measured on the baseline frames (time-aligned quiet passages and onset gate)'))}_")
        for x in rows:
            for sg in x.get("suggestions") or []:
                L.append(f"- {t(T('是正案', 'Correction'))} ({x.get('profile')}): {t(sg.get('text'))}")
            psb = x.get("plan_send_back")
            if psb:
                for sg in psb.get("suggestions") or []:
                    L.append(f"  - {t(sg.get('text'))}")


def write_report(project, variant_id: str) -> dict:
    """Write reports/report_<variant>.json (bilingual) and .ja.md / .en.md. Returns relative paths."""
    rep = build_report(project, variant_id, lang="both")
    rdir = Path(project.root) / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    jp = rdir / f"report_{variant_id}.json"
    with open(jp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rep, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    paths = {"json": project.rel(jp)}
    for lang in LANGS:
        mp = rdir / f"report_{variant_id}.{lang}.md"
        with open(mp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_markdown(rep, lang))
        paths[f"md_{lang}"] = project.rel(mp)
    return paths
