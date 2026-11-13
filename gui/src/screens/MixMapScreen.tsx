import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, StatusBadge, SyntheticFlag, fmtHz, fmtNum } from "../components/ui";
import type { Analysis, Project } from "../types";

const W = 640;
const H = 400;
const PAD = 40;
const F_MIN = 40;
const F_MAX = 12000;

export interface MapPoint {
  id: string;
  name: string;
  x: number;
  y: number;
  r: number;
  opacity: number;
  pan: number;
  centroid: number;
  depth: number;
  lead: boolean;
}

/** Map coordinates for a stem (presentation only: pan, log centroid, depth). */
export function placeStem(pan: number, centroidHz: number, depth: number): { x: number; y: number; r: number; opacity: number } {
  const p = Math.max(-1, Math.min(1, pan));
  const f = Math.max(F_MIN, Math.min(F_MAX, centroidHz || F_MIN));
  const d = Math.max(0, Math.min(1, depth));
  const x = PAD + ((p + 1) / 2) * (W - 2 * PAD);
  const ly = (Math.log10(f) - Math.log10(F_MIN)) / (Math.log10(F_MAX) - Math.log10(F_MIN));
  const y = H - PAD - ly * (H - 2 * PAD);
  return { x, y, r: 12 + d * 24, opacity: 0.3 + d * 0.6 };
}

export function overlaps(a: MapPoint, b: MapPoint): boolean {
  return Math.hypot(a.x - b.x, a.y - b.y) < (a.r + b.r) * 0.8;
}

export function MixMapScreen() {
  const { backend, revision, variantId } = useApp();
  const state = useAsync(() => Promise.all([backend.getProject(), backend.getAnalysis(variantId)]), [backend, revision, variantId]);
  return <Async state={state}>{([p, a]) => <MixMap project={p} analysis={a} />}</Async>;
}

function MixMap({ project, analysis }: { project: Project; analysis: Analysis }) {
  const { t } = useApp();
  const byId = new Map(project.tracks.map((tr) => [tr.id, tr]));
  const points: MapPoint[] = analysis.stems.map((s) => {
    const tr = byId.get(s.track);
    const pan = tr?.pan?.position ?? s.pan ?? 0;
    const g = placeStem(pan, s.centroid_hz, s.depth);
    return { id: s.track, name: tr?.name ?? s.track, pan, centroid: s.centroid_hz, depth: s.depth, lead: !!tr?.is_lead, ...g };
  });
  const pointById = new Map(points.map((p) => [p.id, p]));
  const warnings = analysis.masking.filter((m) => m.severity !== "info");
  const overlapPairs: [MapPoint, MapPoint][] = [];
  for (let i = 0; i < points.length; i++) for (let j = i + 1; j < points.length; j++) if (overlaps(points[i], points[j])) overlapPairs.push([points[i], points[j]]);
  const flagged = new Set(warnings.flatMap((w) => [w.a, w.b]));
  const freqTicks = [50, 100, 200, 500, 1000, 2000, 5000, 10000];

  return (
    <div className="screen-grid">
      <Card title={t("nav.mixmap")} className="span-2">
        <SyntheticFlag synthetic={analysis.synthetic} />
        <p className="muted small">{t("mixmap.desc")}</p>
        <div className="chart-wrap mixmap">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("nav.mixmap")}>
            {freqTicks.map((f) => {
              const y = placeStem(0, f, 0).y;
              return (
                <g key={f}>
                  <line className="grid" x1={PAD} x2={W - PAD} y1={y} y2={y} />
                  <text className="tick" x={PAD - 6} y={y + 4} textAnchor="end">
                    {fmtHz(f)}
                  </text>
                </g>
              );
            })}
            <line className="axis" x1={W / 2} x2={W / 2} y1={PAD - 10} y2={H - PAD} />
            <text className="tick" x={PAD} y={H - 12} textAnchor="start">
              {t("mixmap.left")}
            </text>
            <text className="tick" x={W / 2} y={H - 12} textAnchor="middle">
              C
            </text>
            <text className="tick" x={W - PAD} y={H - 12} textAnchor="end">
              {t("mixmap.right")}
            </text>
            {warnings.map((w, i) => {
              const a = pointById.get(w.a);
              const b = pointById.get(w.b);
              if (!a || !b) return null;
              return <line key={i} className={`mask-link sev-${w.severity}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
            })}
            {[...points]
              .sort((a, b) => a.depth - b.depth)
              .map((p) => (
                <g key={p.id} className={"stem-dot" + (flagged.has(p.id) ? " flagged" : "") + (p.lead ? " lead" : "")}>
                  <circle cx={p.x} cy={p.y} r={p.r} style={{ fillOpacity: p.opacity }}>
                    <title>{`${p.name}: pan ${fmtNum(p.pan, 2)}, ${fmtHz(p.centroid)}Hz, ${t("mixmap.depth")} ${fmtNum(p.depth, 2)}`}</title>
                  </circle>
                  <text className="dot-label" x={p.x} y={p.y + p.r + 12} textAnchor="middle">
                    {p.name}
                  </text>
                </g>
              ))}
          </svg>
        </div>
      </Card>
      <Card title={t("mixmap.masking")} className="span-2">
        {warnings.length === 0 && overlapPairs.length === 0 ? (
          <p className="muted">{t("mixmap.noMasking")}</p>
        ) : (
          <ul className="plain-list">
            {warnings.map((w, i) => (
              <li key={i}>
                <StatusBadge status={w.severity === "critical" ? "critical" : "warning"} /> {pointById.get(w.a)?.name ?? w.a} ↔ {pointById.get(w.b)?.name ?? w.b}:{" "}
                {fmtHz(w.band_hz[0])}–{fmtHz(w.band_hz[1])} Hz, {fmtNum(w.amount_db, 1, "dB")}
              </li>
            ))}
            {overlapPairs
              .filter(([a, b]) => !warnings.some((w) => (w.a === a.id && w.b === b.id) || (w.a === b.id && w.b === a.id)))
              .map(([a, b]) => (
                <li key={a.id + b.id}>
                  <StatusBadge status="info" /> {a.name} ↔ {b.name}: {t("mixmap.overlap")}
                </li>
              ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
