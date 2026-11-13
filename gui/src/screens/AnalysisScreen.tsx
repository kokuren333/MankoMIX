import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, CapButton, StatusBadge, SyntheticFlag, fmtHz, fmtNum, fmtTime } from "../components/ui";
import { GroupedBars, LineChart, type Series } from "../components/charts";
import type { Analysis } from "../types";

export function AnalysisScreen() {
  const { backend, revision, variantId } = useApp();
  const state = useAsync(() => backend.getAnalysis(variantId), [backend, revision, variantId]);
  return <Async state={state}>{(a) => <AnalysisView a={a} />}</Async>;
}

function AnalysisView({ a }: { a: Analysis }) {
  const { t, label, caps, backend, bump } = useApp();
  const L = a.loudness;
  const times = L.before.map((_, i) => i * L.hop_s);
  const loudSeries: Series[] = [{ id: "before", name: t("analysis.before"), values: L.before, cls: "s2" }];
  if (L.after) loudSeries.push({ id: "after", name: t("analysis.after"), values: L.after, cls: "s1" });

  const ltasSeries: Series[] = [{ id: "before", name: t("analysis.before"), values: a.ltas.before, cls: "s2" }];
  if (a.ltas.after) ltasSeries.push({ id: "after", name: t("analysis.after"), values: a.ltas.after, cls: "s1" });
  const ref = a.ltas.reference;

  const bands = a.band_correlation.bands;
  const corrSeries: Series[] = [
    { id: "before", name: t("analysis.before"), values: bands.map((b) => b.before), cls: "s2" },
    { id: "after", name: t("analysis.after"), values: bands.map((b) => b.after), cls: "s1" },
  ];

  return (
    <div className="screen-grid">
      <Card
        title={t("analysis.loudness")}
        className="span-2"
        actions={
          caps.mode === "local" ? (
            <CapButton allowed={caps.runAnalysis} icon="meter" onClick={() => void backend.analyze().then(bump)}>
              {t("analysis.run")}
            </CapButton>
          ) : undefined
        }
      >
        <SyntheticFlag synthetic={a.synthetic} />
        <dl className="kv kv-inline">
          <dt>{t("analysis.integrated")}</dt>
          <dd>
            {fmtNum(L.integrated_lufs?.before, 1)} → {fmtNum(L.integrated_lufs?.after, 1)} LUFS
          </dd>
          <dt>{t("analysis.truePeak")}</dt>
          <dd>
            {fmtNum(L.true_peak_dbtp?.before, 1)} → {fmtNum(L.true_peak_dbtp?.after, 1)} dBTP
          </dd>
          {L.lra_lu && (
            <>
              <dt>{t("analysis.lra")}</dt>
              <dd>
                {fmtNum(L.lra_lu.before, 1)} → {fmtNum(L.lra_lu.after, 1)} LU
              </dd>
            </>
          )}
        </dl>
        <LineChart title={t("analysis.loudness")} xs={times} series={loudSeries} xFormat={(x) => fmtTime(x)} yUnit="LUFS" />
      </Card>

      <Card title={t("analysis.ltas")}>
        {!ref && <p className="muted small">{t("analysis.noReference")}</p>}
        <LineChart
          title={t("analysis.ltas")}
          xs={a.ltas.freqs_hz}
          series={ltasSeries}
          band={ref ? { name: label(ref.label, t("analysis.reference")), low: ref.low, high: ref.high } : null}
          logX
          xTicks={[50, 100, 200, 500, 1000, 2000, 5000, 10000].filter((f) => f >= a.ltas.freqs_hz[0] && f <= a.ltas.freqs_hz[a.ltas.freqs_hz.length - 1])}
          xFormat={(x) => fmtHz(x)}
          yUnit="dB"
        />
      </Card>

      <Card title={t("analysis.correlation")}>
        <GroupedBars title={t("analysis.correlation")} categories={bands.map((b) => `${fmtHz(b.lo_hz)}–${fmtHz(b.hi_hz)}`)} series={corrSeries} domain={[-1, 1]} />
      </Card>

      <Card title={t("analysis.diagnostics")} className="span-2">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("analysis.metric")}</th>
                <th>{t("analysis.value")}</th>
                <th>{t("analysis.threshold")}</th>
                <th>{t("analysis.status")}</th>
              </tr>
            </thead>
            <tbody>
              {a.diagnostics.map((d) => (
                <tr key={d.id}>
                  <td>
                    {label(d.label, d.id)} {d.metric && <code className="small">{d.metric}</code>}
                    {d.note && <div className="muted small">{label(d.note)}</div>}
                  </td>
                  <td className="num">{typeof d.value === "number" ? fmtNum(d.value, 1, d.unit) : (d.value ?? "—")}</td>
                  <td className="num">{d.threshold == null ? "—" : typeof d.threshold === "number" ? fmtNum(d.threshold, 1, d.unit) : d.threshold}</td>
                  <td>
                    <StatusBadge status={d.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {a.metrics && a.metrics.length > 0 && (
        <Card title={t("analysis.metrics")} className="span-2">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t("analysis.metric")}</th>
                  <th>{t("analysis.before")}</th>
                  <th>{t("analysis.after")}</th>
                </tr>
              </thead>
              <tbody>
                {a.metrics.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <code>{m.id}</code> {label(m.label)}
                    </td>
                    <td className="num">{fmtNum(m.before, 2, m.unit)}</td>
                    <td className="num">{fmtNum(m.after, 2, m.unit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
