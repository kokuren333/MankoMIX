"""Mix Report (SPEC 6.8, R-24, R-25, D-044).

``report.json`` is canonical; Markdown is rendered from it in Japanese and
English. Text fields are bilingual objects ``{"ja": ..., "en": ...}`` in the
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
from .mastering import find_variant, objective_ids
from .measure import loudness as ld
from .render import ARCHIVE_DELIVERY, load_manifest, output_ext, variant_dir, variant_route
from .routes import load_master_input

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


def _decisions(plan: dict) -> dict:
    out = {k: [] for k in ("balance", "panning", "frequency", "depth", "dynamics", "interest")}
    for r in plan.get("rationale", []) or []:
        el = _STAGE_ELEMENT.get(r.get("stage"), "dynamics")
        d = {"stage": r.get("stage"), "measured": r.get("measured"), "rule": r.get("rule"),
             "action": r.get("action"), "alternatives": r.get("alternatives", []), "result": r.get("expected")}
        if r.get("moves"):
            words = []
            for m in r["moves"]:
                vb = _vocab_band(m.get("band", ""))
                direction = "too_much" if m.get("gain_db", 0) < 0 else "too_little"
                ja = (vb or {}).get(direction, {}).get("ja") if vb else None
                words.append({"band": m.get("band"), "gain_db": m.get("gain_db"),
                              "vocabulary": T(ja or m.get("band", ""), _BAND_WORDS_EN.get(m.get("band"), m.get("band", "")))})
            d["vocabulary"] = words
        out[el].append(d)
    na_mix = T("フルミックス経路のマスタリングでは扱わない（ミックス段は M4）",
               "Not handled by full-mix mastering (the mix stage arrives in M4)")
    for el in ("balance", "depth"):
        if not out[el]:
            out[el].append({"measured": None, "rule": None, "action": na_mix, "alternatives": [], "result": None,
                            "status": "not_evaluated"})
    out["interest"].append({"measured": None, "rule": "R-26",
                            "action": T("「仕掛け」は自動化が最も難しい軸で、人間の指示とリファレンスに依存する。このマイルストーンでは評価しない",
                                        "Interest is the hardest axis to automate and depends on human direction and references; not evaluated in this milestone"),
                            "alternatives": [], "result": None, "status": "not_evaluated"})
    if not out["panning"]:
        out["panning"].append({"measured": None, "rule": "R-09", "action": T("ステレオ処理なし", "No stereo processing"),
                               "alternatives": [], "result": None})
    return out


def _measurements(project, variant, x_in, sr_in, archive_path: Path | None) -> dict:
    before = ld.loudness_summary(x_in, sr_in)
    res = {"level_matched": False, "before": {k: ma.finite_or_none(v) for k, v in before.items()},
           "after": None, "comparison": None,
           "assumed_playback": T("比較はレベルマッチ後の信号で行う（R-01）。幅と定位の値はスピーカー（±30°）とモノ合算を前提にする",
                                 "Comparisons use level-matched signals (R-01). Width/localisation values assume speakers (+/-30 deg) and a mono fold")}
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


def _listening_checks(x, sr, plan: dict, verify: dict) -> list[dict]:
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
    for o in verify.get("outputs", []) or []:
        s02 = (o.get("checks") or {}).get("S-02") or {}
        if (s02.get("render_iterations") or 0) > 1:
            out.append({"time_s": times.get("loudest_start_s"), "duration_s": 3.0,
                        "point": T(f"{o['profile']}: コーデック通過後の天井を守るため天井を {s02.get('final_limiter_ceiling_dbtp')} dBTP まで下げた。大きい区間で歪みや詰まりがないか",
                                   f"{o['profile']}: ceiling lowered to {s02.get('final_limiter_ceiling_dbtp')} dBTP for the codec-after ceiling; check the loud section for distortion or congestion"),
                        "conditions": cond})
    return out


def _constraints(verify: dict) -> list[dict]:
    out = []
    for o in verify.get("outputs", []) or []:
        out.append({"profile": o.get("profile"), "delivery": o.get("delivery"), "overall": o.get("overall"),
                    "checks": o.get("checks")})
    if verify.get("archive"):
        out.append({"profile": None, "delivery": ARCHIVE_DELIVERY, "overall": verify["archive"].get("overall"),
                    "checks": verify["archive"].get("checks")})
    return out


def _notes(project, obj: dict) -> list[dict]:
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
                      "text": T(f"ジャンル「{label.get('ja', genre)}」の prior は初期値にだけ使う（[慣行]）。M2 のマスタリング計画は帯域の判定に汎用 prior だけを使っている",
                                f"The genre prior '{label.get('en', genre)}' only sets initial values (practice level). The M2 mastering planner uses only the generic prior for band checks")})
    if not data.get("references"):
        notes.append({"code": "generic_prior", "rule": "R-17",
                      "text": T("リファレンスが登録されていないため、汎用の目安に対する評価であり、ジャンルに合わせた評価ではない",
                                "No references are registered: this is an evaluation against a generic prior, not a genre-specific one")})
    else:
        notes.append({"code": "references_unused", "rule": "R-17",
                      "text": T("登録済みのリファレンスは、このマイルストーンのマスタリング計画ではまだ使っていない",
                                "Registered references are not yet used by the mastering planner in this milestone")})
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


def _tradeoffs(plan: dict, verify: dict, notes: list[dict]) -> list[dict]:
    out = []
    sb = plan.get("send_back")
    if sb:
        out.append({"kind": "send_back", "rule": sb.get("rule"), "text": sb.get("reason"), "measured": sb.get("measured")})
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
    for n in notes:
        if n["code"] in ("generic_prior", "normalization_tradeoff"):
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
    x, sr = load_master_input(project, route)
    ad = config.get_delivery(ARCHIVE_DELIVERY)
    apath = variant_dir(project, variant_id) / f"master__{ARCHIVE_DELIVERY}.{output_ext(ad)}"
    outputs = variant.get("outputs") or []
    notes = _notes(project, obj)

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
        "measurements": _measurements(project, variant, x, sr, apath),
        "decisions": _decisions(plan),
        "objective_breakdown": {
            "status": "not_evaluated", "milestone": "M3",
            "terms": [{"objective": oid, "status": "not_evaluated"} for oid in objective_ids(obj)],
            "note": T("目的関数の指標別スコアは M3 で実装する。合計 score は出さない",
                      "Per-metric objective scores arrive in M3; no total score is shown"),
        },
        "constraints": _constraints(verify),
        "cleanup": {"status": "not_evaluated", "milestone": "M5",
                    "note": T("整音は M5 で実装する。このマスターには整音を適用していない",
                              "Cleanup arrives in M5; no cleanup was applied to this master")},
        "tradeoffs": _tradeoffs(plan, verify, notes),
        "listening_checks": _listening_checks(x, sr, plan, verify),
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
    if s.get("send_back"):
        L.append(f"- **{t(T('差し戻し', 'Send back'))} ({s['send_back'].get('rule')})**: {t(s['send_back'].get('reason'))}")
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
    L.append("")

    L.append("## " + t(_SEC[4]))
    for el, items in (r.get("decisions") or {}).items():
        L.append(f"### {t(_EL.get(el, T(el, el)))}")
        for d in items:
            L.append(f"- {t(T('行動', 'Action'))}: {t(d.get('action'))}" + (f" [{d.get('rule')}]" if d.get("rule") else ""))
            if d.get("measured"):
                L.append(f"  - {t(T('測定', 'Measured'))}: `{_j(d.get('measured'))}`")
            for v in d.get("vocabulary", []) or []:
                L.append(f"  - {v.get('band')}: {v.get('gain_db'):+.1f} dB — {t(v.get('vocabulary'))}")
            if d.get("alternatives"):
                L.append(f"  - {t(T('代替案', 'Alternatives'))}: " + "; ".join(t(x) for x in d["alternatives"]))
            if d.get("result"):
                L.append(f"  - {t(T('結果（予測）', 'Result (expected)'))}: `{_j(d.get('result'))}`")
    L.append("")

    L.append("## " + t(_SEC[5]))
    ob = r.get("objective_breakdown") or {}
    L.append(f"- {t(ob.get('note'))} ({ob.get('status')}, {ob.get('milestone')})")
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
    L.append("")

    L.append("## " + t(_SEC[7]))
    L.append(f"- {t((r.get('cleanup') or {}).get('note'))}")
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
    for e in rep.get("outputs", []):
        L.append(f"- `{e.get('file')}`: seed {e.get('dither_seed')}, ceiling {e.get('limiter_ceiling_dbtp')} dBTP, "
                 f"iterations {e.get('iterations')}, sha256 `{(e.get('file_sha256') or '')[:16]}…`")
    L.append(f"- {t(rep.get('promise'))}")
    L.append("")
    return "\n".join(L)


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
