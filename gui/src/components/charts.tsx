import { useMemo, useRef, useState, type PointerEvent } from "react";
import { useApp } from "../AppContext";

// Small dependency-free SVG charts. Colors come from CSS custom properties
// (--series-1 = After, --series-2 = Before, neutral gray = reference band).

export interface Series {
  id: string;
  name: string;
  values: (number | null)[];
  /** CSS class selecting the series color: "s1" | "s2" | ... */
  cls: string;
}

const W = 640;
const PAD = { l: 44, r: 12, t: 12, b: 28 };

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function Legend({ items }: { items: { name: string; cls: string; kind?: "line" | "band" }[] }) {
  if (items.length < 2) return null;
  return (
    <ul className="legend">
      {items.map((i) => (
        <li key={i.name}>
          <span className={`swatch ${i.kind === "band" ? "swatch-band" : i.cls}`} aria-hidden="true" />
          {i.name}
        </li>
      ))}
    </ul>
  );
}

export interface LineChartProps {
  title: string;
  xs: number[];
  series: Series[];
  band?: { name: string; low: number[]; high: number[] } | null;
  logX?: boolean;
  xFormat?: (x: number) => string;
  yFormat?: (y: number) => string;
  xTicks?: number[];
  yUnit?: string;
  height?: number;
}

export function LineChart({ title, xs, series, band, logX, xFormat = String, yFormat = (y) => y.toFixed(1), xTicks, yUnit = "", height = 220 }: LineChartProps) {
  const { t } = useApp();
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const H = height;

  const geom = useMemo(() => {
    const all: number[] = [];
    for (const s of series) for (const v of s.values) if (v != null && Number.isFinite(v)) all.push(v);
    if (band) all.push(...band.low, ...band.high);
    let yMin = Math.min(...all);
    let yMax = Math.max(...all);
    if (!Number.isFinite(yMin)) {
      yMin = 0;
      yMax = 1;
    }
    const padY = (yMax - yMin) * 0.08 || 1;
    yMin -= padY;
    yMax += padY;
    const fx = (x: number) => (logX ? Math.log10(Math.max(x, 1e-9)) : x);
    const x0 = fx(xs[0] ?? 0);
    const x1 = fx(xs[xs.length - 1] ?? 1);
    const sx = (x: number) => PAD.l + ((fx(x) - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
    const sy = (y: number) => PAD.t + (1 - (y - yMin) / (yMax - yMin || 1)) * (H - PAD.t - PAD.b);
    return { sx, sy, yTicks: niceTicks(yMin, yMax, 4), yMin, yMax };
  }, [xs, series, band, logX, H]);

  const path = (vals: (number | null)[]) => {
    let d = "";
    let pen = false;
    vals.forEach((v, i) => {
      if (v == null || !Number.isFinite(v) || xs[i] === undefined) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${geom.sx(xs[i]).toFixed(1)},${geom.sy(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  const bandPath = band
    ? `M${xs.map((x, i) => `${geom.sx(x).toFixed(1)},${geom.sy(band.high[i]).toFixed(1)}`).join("L")}L${xs
        .map((x, i) => `${geom.sx(x).toFixed(1)},${geom.sy(band.low[i]).toFixed(1)}`)
        .reverse()
        .join("L")}Z`
    : "";

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const svg = ref.current;
    if (!svg || xs.length === 0) return;
    const r = svg.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / (r.width || 1)) * W;
    let best = 0;
    let bd = Infinity;
    xs.forEach((x, i) => {
      const d = Math.abs(geom.sx(x) - vx);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    setHover(best);
  };

  const ticksX = xTicks ?? niceTicks(xs[0] ?? 0, xs[xs.length - 1] ?? 1, 6);
  const legendItems = [
    ...series.map((s) => ({ name: s.name, cls: s.cls })),
    ...(band ? [{ name: band.name, cls: "", kind: "band" as const }] : []),
  ];

  return (
    <figure className="chart">
      <figcaption className="sr-only">{title}</figcaption>
      <Legend items={legendItems} />
      <div className="chart-wrap">
        <svg
          ref={ref}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={title}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {geom.yTicks.map((y) => (
            <g key={y}>
              <line className="grid" x1={PAD.l} x2={W - PAD.r} y1={geom.sy(y)} y2={geom.sy(y)} />
              <text className="tick" x={PAD.l - 6} y={geom.sy(y) + 4} textAnchor="end">
                {yFormat(y)}
              </text>
            </g>
          ))}
          {ticksX.map((x) => (
            <text key={x} className="tick" x={geom.sx(x)} y={H - 8} textAnchor="middle">
              {xFormat(x)}
            </text>
          ))}
          <line className="axis" x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} />
          {band && <path className="band" d={bandPath} />}
          {series.map((s) => (
            <path key={s.id} className={`line ${s.cls}`} d={path(s.values)} />
          ))}
          {hover != null && xs[hover] !== undefined && (
            <g className="crosshair">
              <line x1={geom.sx(xs[hover])} x2={geom.sx(xs[hover])} y1={PAD.t} y2={H - PAD.b} />
              {series.map((s) => {
                const v = s.values[hover];
                return v == null ? null : <circle key={s.id} className={`dot ${s.cls}`} cx={geom.sx(xs[hover])} cy={geom.sy(v)} r={4} />;
              })}
            </g>
          )}
        </svg>
        {hover != null && xs[hover] !== undefined && (
          <div className="tooltip" style={{ left: `${(geom.sx(xs[hover]) / W) * 100}%` }} role="status">
            <strong>{xFormat(xs[hover])}</strong>
            {series.map((s) => (
              <div key={s.id}>
                <span className={`swatch ${s.cls}`} aria-hidden="true" /> {s.name}: {s.values[hover] == null ? "—" : `${yFormat(s.values[hover]!)} ${yUnit}`}
              </div>
            ))}
            {band && (
              <div>
                {band.name}: {yFormat(band.low[hover])}–{yFormat(band.high[hover])} {yUnit}
              </div>
            )}
          </div>
        )}
      </div>
      <details className="table-view">
        <summary>{t("analysis.showTable")}</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>x</th>
                {series.map((s) => (
                  <th key={s.id}>{s.name}</th>
                ))}
                {band && <th>{band.name}</th>}
              </tr>
            </thead>
            <tbody>
              {xs.map((x, i) => (
                <tr key={i}>
                  <td>{xFormat(x)}</td>
                  {series.map((s) => (
                    <td key={s.id} className="num">
                      {s.values[i] == null ? "—" : yFormat(s.values[i]!)}
                    </td>
                  ))}
                  {band && (
                    <td className="num">
                      {yFormat(band.low[i])}–{yFormat(band.high[i])}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

export interface GroupedBarsProps {
  title: string;
  categories: string[];
  series: Series[];
  domain: [number, number];
  yFormat?: (y: number) => string;
  height?: number;
}

/** Grouped vertical bars around a zero baseline (e.g. correlation -1..1). */
export function GroupedBars({ title, categories, series, domain, yFormat = (y) => y.toFixed(2), height = 200 }: GroupedBarsProps) {
  const { t } = useApp();
  const H = height;
  const [lo, hi] = domain;
  const sy = (y: number) => PAD.t + (1 - (y - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const groupW = (W - PAD.l - PAD.r) / Math.max(categories.length, 1);
  const barW = Math.max(4, Math.min(22, (groupW - 10) / Math.max(series.length, 1) - 2));
  const zero = sy(Math.max(lo, Math.min(hi, 0)));
  const ticks = niceTicks(lo, hi, 4);
  return (
    <figure className="chart">
      <figcaption className="sr-only">{title}</figcaption>
      <Legend items={series.map((s) => ({ name: s.name, cls: s.cls }))} />
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
          {ticks.map((y) => (
            <g key={y}>
              <line className="grid" x1={PAD.l} x2={W - PAD.r} y1={sy(y)} y2={sy(y)} />
              <text className="tick" x={PAD.l - 6} y={sy(y) + 4} textAnchor="end">
                {yFormat(y)}
              </text>
            </g>
          ))}
          <line className="axis" x1={PAD.l} x2={W - PAD.r} y1={zero} y2={zero} />
          {categories.map((c, ci) => {
            const gx = PAD.l + ci * groupW + (groupW - series.length * (barW + 2)) / 2;
            return (
              <g key={c}>
                {series.map((s, si) => {
                  const v = s.values[ci];
                  if (v == null) return null;
                  const y = sy(Math.max(lo, Math.min(hi, v)));
                  const top = Math.min(y, zero);
                  const h = Math.max(1, Math.abs(zero - y));
                  return (
                    <rect key={s.id} className={`bar ${s.cls}`} x={gx + si * (barW + 2)} y={top} width={barW} height={h} rx={2}>
                      <title>{`${c} — ${s.name}: ${yFormat(v)}`}</title>
                    </rect>
                  );
                })}
                <text className="tick" x={PAD.l + ci * groupW + groupW / 2} y={H - 8} textAnchor="middle">
                  {c}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <details className="table-view">
        <summary>{t("analysis.showTable")}</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("analysis.band")}</th>
                {series.map((s) => (
                  <th key={s.id}>{s.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {categories.map((c, ci) => (
                <tr key={c}>
                  <td>{c}</td>
                  {series.map((s) => (
                    <td key={s.id} className="num">
                      {s.values[ci] == null ? "—" : yFormat(s.values[ci]!)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
