import { useState, type ReactNode } from "react";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, StatusBadge, SyntheticFlag, fmtTime } from "../components/ui";
import type { Decision, Lang, Report } from "../types";
import type { StringKey } from "../i18n/strings";

export function ReportScreen() {
  const { backend, revision, variantId, lang } = useApp();
  const [reportLang, setReportLang] = useState<Lang>(lang);
  const state = useAsync(() => backend.getReport(variantId, reportLang), [backend, revision, variantId, reportLang]);
  return (
    <div className="stack">
      <Async state={state}>{(r) => <ReportView report={r} reportLang={reportLang} onLang={setReportLang} variantId={variantId} />}</Async>
    </div>
  );
}

/** Section keys of report.json in SPEC 6.8 order, with their heading string keys. */
export const REPORT_SECTIONS: { key: keyof Report; heading: StringKey }[] = [
  { key: "summary", heading: "report.s1" },
  { key: "inputs", heading: "report.s2" },
  { key: "measurements", heading: "report.s3" },
  { key: "decisions", heading: "report.s4" },
  { key: "objective_breakdown", heading: "report.s5" },
  { key: "constraints", heading: "report.s6" },
  { key: "cleanup", heading: "report.s7" },
  { key: "tradeoffs", heading: "report.s8" },
  { key: "listening_checks", heading: "report.s9" },
  { key: "reproducibility", heading: "report.s10" },
];

const ELEMENTS = ["balance", "panning", "frequency", "depth", "dynamics", "interest"] as const;

/** Generic renderer for report values of any JSON shape. */
export function Value({ v, depth = 0 }: { v: unknown; depth?: number }): ReactNode {
  const { label } = useApp();
  if (v === null || v === undefined || v === "") return <span className="muted">—</span>;
  if (typeof v === "number") return <span className="num">{Number.isInteger(v) ? v : v.toFixed(2).replace(/^-/, "−")}</span>;
  if (typeof v === "boolean") return <span>{v ? "✓" : "✕"}</span>;
  if (typeof v === "string") {
    if (["pass", "fail", "warning", "not_run", "incomplete"].includes(v)) return <StatusBadge status={v} />;
    return <span>{v}</span>;
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="muted">—</span>;
    const allObjects = v.every((x) => x && typeof x === "object" && !Array.isArray(x) && !("ja" in x || "en" in x));
    if (allObjects && depth < 3) {
      const cols = [...new Set(v.flatMap((x) => Object.keys(x as object)))];
      return (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {v.map((row, i) => (
                <tr key={i}>
                  {cols.map((c) => (
                    <td key={c}>
                      <Value v={(row as Record<string, unknown>)[c]} depth={depth + 1} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return (
      <ul className="plain-list">
        {v.map((x, i) => (
          <li key={i}>
            <Value v={x} depth={depth + 1} />
          </li>
        ))}
      </ul>
    );
  }
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (("ja" in o || "en" in o) && Object.values(o).every((x) => typeof x === "string")) return <span>{label(o as Record<string, string>)}</span>;
    return (
      <dl className="kv">
        {Object.entries(o).map(([k, x]) => (
          <div key={k} className="kv-row">
            <dt>{k}</dt>
            <dd>
              <Value v={x} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span>{String(v)}</span>;
}

function DecisionList({ items }: { items: Decision[] }) {
  const { t } = useApp();
  return (
    <ol className="decisions">
      {items.map((d, i) => (
        <li key={i} className="decision">
          {d.rule && <span className="chip rule">{d.rule}</span>}
          <dl className="kv">
            <dt>{t("report.measured")}</dt>
            <dd>
              <Value v={d.measured} />
            </dd>
            <dt>{t("report.action")}</dt>
            <dd>
              <Value v={d.action} />
            </dd>
            {d.alternatives && d.alternatives.length > 0 && (
              <>
                <dt>{t("report.alternatives")}</dt>
                <dd>
                  <Value v={d.alternatives} />
                </dd>
              </>
            )}
            <dt>{t("report.result")}</dt>
            <dd>
              <Value v={d.result} />
            </dd>
          </dl>
        </li>
      ))}
    </ol>
  );
}

function SectionBody({ k, report }: { k: keyof Report; report: Report }) {
  const { t } = useApp();
  const v = report[k];
  if (v === undefined || v === null || (Array.isArray(v) && v.length === 0)) return <p className="muted">{t("report.empty")}</p>;
  if (k === "decisions") {
    const d = v as Record<string, Decision[]>;
    const extra = Object.keys(d).filter((x) => !(ELEMENTS as readonly string[]).includes(x));
    return (
      <>
        {[...ELEMENTS, ...extra].map((el) => (
          <section key={el} className="subsection">
            <h3>{(ELEMENTS as readonly string[]).includes(el) ? t(`report.el.${el}` as StringKey) : el}</h3>
            {el === "interest" && <p className="muted small">{t("report.interestNote")}</p>}
            {d[el]?.length ? <DecisionList items={d[el]} /> : <p className="muted small">—</p>}
          </section>
        ))}
      </>
    );
  }
  if (k === "listening_checks") {
    const items = v as NonNullable<Report["listening_checks"]>;
    return (
      <ol className="checks">
        {items.map((c, i) => (
          <li key={i}>
            <span className="num time">{c.time_s == null ? "—" : fmtTime(c.time_s)}</span>{" "}
            <strong>
              <Value v={c.point} />
            </strong>
            {c.conditions != null && (
              <div className="muted small">
                {t("report.conditions")}: <Value v={c.conditions} />
              </div>
            )}
          </li>
        ))}
      </ol>
    );
  }
  if (k === "measurements") {
    const m = v as NonNullable<Report["measurements"]>;
    return (
      <>
        <p className={m.level_matched ? "small" : "notice small"}>{m.level_matched ? t("report.levelMatched") : t("report.notLevelMatched")}</p>
        <Value v={Object.fromEntries(Object.entries(m).filter(([x]) => x !== "level_matched"))} />
      </>
    );
  }
  return <Value v={v} />;
}

export function ReportView({ report, reportLang, onLang, variantId }: { report: Report; reportLang: Lang; onLang: (l: Lang) => void; variantId: string }) {
  const { t } = useApp();
  const download = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `report.${variantId}.${reportLang}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <article className="report">
      <Card
        title={
          <>
            {t("nav.report")} {report.summary?.result && <StatusBadge status={report.summary.result} />}
          </>
        }
        actions={
          <span className="row">
            <span className="seg" role="radiogroup" aria-label={t("report.lang")}>
              {(["ja", "en"] as Lang[]).map((l) => (
                <button key={l} type="button" role="radio" aria-checked={reportLang === l} className={"seg-btn" + (reportLang === l ? " active" : "")} onClick={() => onLang(l)}>
                  {l === "ja" ? "日本語" : "English"}
                </button>
              ))}
            </span>
            <button type="button" className="btn secondary" onClick={download}>
              {t("report.download")}
            </button>
          </span>
        }
      >
        <SyntheticFlag synthetic={report.synthetic} />
        <p className="notice small">{t("report.earFirst")}</p>
      </Card>
      {REPORT_SECTIONS.map((s) => (
        <Card key={String(s.key)} title={t(s.heading)} id={`report-${String(s.key)}`}>
          <SectionBody k={s.key} report={report} />
        </Card>
      ))}
    </article>
  );
}
