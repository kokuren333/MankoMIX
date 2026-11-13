import { useEffect, useState } from "react";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, CapButton, fmtNum } from "../components/ui";
import type { DeliveryFormat, MediaProfile, ObjectiveCatalog, ObjectiveSpec, OutputSpec, PatchOp, Project, VariantSummary } from "../types";

export function IntentScreen() {
  const { backend, revision } = useApp();
  const state = useAsync(
    () => Promise.all([backend.getProject(), backend.listObjectives(), backend.listProfiles(), backend.listDeliveries()]),
    [backend, revision],
  );
  return <Async state={state}>{([p, o, pr, d]) => <IntentView project={p} catalog={o} profiles={pr} deliveries={d} />}</Async>;
}

/** Objective × profile matrix of available variants (the demo's switch). */
export function VariantMatrix({ catalog, profiles }: { catalog: ObjectiveCatalog; profiles: MediaProfile[] }) {
  const { variants, variantId, setVariantId, label } = useApp();
  const objIds = [...new Set(variants.map((v) => v.objectives[0]))];
  const profIds = [...new Set(variants.map((v) => v.profile))];
  const objLabel = (id: string) => label(catalog.objectives.find((o) => o.id === id)?.label, id);
  const profLabel = (id: string) => label(profiles.find((p) => p.id === id)?.label, id);
  const cell = (o: string, p: string): VariantSummary | undefined => variants.find((v) => v.objectives[0] === o && v.profile === p);
  return (
    <div className="table-scroll">
      <table className="matrix">
        <thead>
          <tr>
            <th />
            {profIds.map((p) => (
              <th key={p} scope="col">
                {profLabel(p)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {objIds.map((o) => (
            <tr key={o}>
              <th scope="row">{objLabel(o)}</th>
              {profIds.map((p) => {
                const v = cell(o, p);
                if (!v) return <td key={p} className="muted">·</td>;
                return (
                  <td key={p}>
                    <button
                      type="button"
                      className={"chip" + (v.id === variantId ? " active" : "") + (v.available ? "" : " unavailable")}
                      aria-pressed={v.id === variantId}
                      onClick={() => setVariantId(v.id)}
                      title={v.available ? undefined : "not generated"}
                    >
                      {v.n != null ? `#${v.n}` : v.id}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IntentView({ project, catalog, profiles, deliveries }: { project: Project; catalog: ObjectiveCatalog; profiles: MediaProfile[]; deliveries: DeliveryFormat[] }) {
  const { t, label, caps, variant, backend, bump } = useApp();
  const editable = caps.editProject;
  const projVariantIdx = (project.variants ?? []).findIndex((v) => v.id === variant?.id);
  const baseObjective: ObjectiveSpec =
    caps.mode === "mock" && variant?.objective ? variant.objective : (project.variants?.[projVariantIdx]?.objective ?? project.objective);
  const baseOutputs: OutputSpec[] =
    caps.mode === "mock" && variant
      ? (variant.deliveries.length ? variant.deliveries : [""]).map((d) => ({ profile: variant.profile, delivery: d }))
      : (project.variants?.[projVariantIdx]?.outputs ?? []);

  const [obj, setObj] = useState<ObjectiveSpec>(baseObjective);
  const [outputs, setOutputs] = useState<OutputSpec[]>(baseOutputs);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string }>();
  const baseKey = JSON.stringify([baseObjective, baseOutputs]);
  useEffect(() => {
    setObj(baseObjective);
    setOutputs(baseOutputs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseKey]);

  const weightOf = (id: string) => obj.blend.find((b) => b.id === id)?.weight ?? 0;
  const setWeight = (id: string, w: number) => {
    const rest = obj.blend.filter((b) => b.id !== id);
    setObj({ ...obj, blend: w > 0 ? [...rest, { id, weight: w }] : rest });
  };
  const total = obj.blend.reduce((s, b) => s + b.weight, 0);

  const apply = async () => {
    setBusy(true);
    setMsg(undefined);
    const ops: PatchOp[] = [];
    // A variant-level objective override is edited in place; otherwise the project objective.
    const objPath = projVariantIdx >= 0 && project.variants?.[projVariantIdx]?.objective ? `/variants/${projVariantIdx}/objective` : "/objective";
    ops.push({ op: "replace", path: objPath, value: obj });
    if (projVariantIdx >= 0) ops.push({ op: "replace", path: `/variants/${projVariantIdx}/outputs`, value: outputs });
    try {
      await backend.patchProject(ops, "gui: intent & output");
      setMsg({ kind: "ok", text: t("app.saved") });
      bump();
    } catch (e) {
      setMsg({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const profileOf = (id: string) => profiles.find((p) => p.id === id);

  return (
    <div className="screen-grid">
      <Card title={t("app.variant")} className="span-2">
        {caps.mode === "mock" && <p className="notice small">{t("intent.mockHint")}</p>}
        <VariantMatrix catalog={catalog} profiles={profiles} />
      </Card>

      <Card title={t("intent.objective")}>
        <p className="muted small">{t("intent.weightsNote")}</p>
        <div className="sliders">
          {catalog.objectives.map((o) => {
            if (o.kind === "gate") {
              return (
                <div key={o.id} className="slider-line gate">
                  <span className="slider-name">
                    {label(o.label, o.id)} <code className="small">{o.spec_id}</code>
                  </span>
                  <span className="muted small">{t("intent.gate")}</span>
                </div>
              );
            }
            const w = weightOf(o.id);
            return (
              <label key={o.id} className="slider-line">
                <span className="slider-name">
                  {label(o.label, o.id)} <code className="small">{o.spec_id}</code>
                  {o.provisional ? <span className="tag">{t("intent.provisional")}</span> : null}
                  {o.summary && <span className="muted small block">{label(o.summary)}</span>}
                </span>
                <input type="range" min={0} max={1} step={0.05} value={w} disabled={!editable} onChange={(e) => setWeight(o.id, +e.target.value)} aria-label={label(o.label, o.id)} />
                <output className="num">{total > 0 ? `${Math.round((w / total) * 100)}%` : "0%"}</output>
              </label>
            );
          })}
        </div>
        <label className="slider-line">
          <span className="slider-name">{t("intent.intensity")}</span>
          <input type="range" min={0} max={1} step={0.05} value={obj.intensity} disabled={!editable} onChange={(e) => setObj({ ...obj, intensity: +e.target.value })} aria-label={t("intent.intensity")} />
          <output className="num">{fmtNum(obj.intensity, 2)}</output>
        </label>
        <label className="field">
          {t("intent.lead")}
          <select value={obj.lead_stem ?? ""} disabled={!editable} onChange={(e) => setObj({ ...obj, lead_stem: e.target.value || null })}>
            <option value="">—</option>
            {project.tracks.map((tr) => (
              <option key={tr.id} value={tr.id}>
                {tr.name ?? tr.id}
              </option>
            ))}
          </select>
        </label>
      </Card>

      <Card title={t("intent.outputs")}>
        {outputs.map((o, i) => {
          const prof = profileOf(o.profile);
          return (
            <div key={i} className="output-row">
              <label className="field">
                {t("intent.profile")}
                <select
                  value={o.profile}
                  disabled={!editable}
                  onChange={(e) => setOutputs(outputs.map((x, j) => (j === i ? { ...x, profile: e.target.value } : x)))}
                >
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {label(p.label, p.id)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                {t("intent.delivery")}
                <select
                  value={o.delivery}
                  disabled={!editable}
                  onChange={(e) => setOutputs(outputs.map((x, j) => (j === i ? { ...x, delivery: e.target.value } : x)))}
                >
                  {!o.delivery && <option value="">{prof?.default_delivery ?? "—"}</option>}
                  {deliveries.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.id}
                    </option>
                  ))}
                </select>
              </label>
              {prof && (
                <p className="muted small">
                  {t("intent.target")}: {prof.loudness.target_lufs_i == null ? "—" : fmtNum(prof.loudness.target_lufs_i, 1, "LUFS")} · {t("intent.ceiling")}:{" "}
                  {fmtNum(prof.true_peak.ceiling_dbtp, 1, "dBTP")}
                </p>
              )}
              {editable && outputs.length > 1 && (
                <button type="button" className="link" onClick={() => setOutputs(outputs.filter((_, j) => j !== i))}>
                  {t("intent.remove")}
                </button>
              )}
            </div>
          );
        })}
        {editable && projVariantIdx >= 0 && (
          <button
            type="button"
            className="btn secondary"
            onClick={() => setOutputs([...outputs, { profile: profiles[0]?.id ?? "", delivery: profiles[0]?.default_delivery ?? deliveries[0]?.id ?? "" }])}
          >
            {t("intent.addOutput")}
          </button>
        )}
      </Card>

      <Card title={t("intent.references")} className="span-2">
        {project.references?.length ? (
          <ul className="plain-list">
            {project.references.map((r) => (
              <li key={r.id}>
                <code>{r.id}</code> {r.label ?? ""}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">{t("intent.noReferences")}</p>
        )}
      </Card>

      <div className="span-2 apply-bar">
        <CapButton allowed={editable} busy={busy} onClick={apply} data-testid="intent-apply">
          {busy ? t("app.saving") : t("app.save")}
        </CapButton>
        {msg && (
          <span className={msg.kind === "ok" ? "ok-text" : "error"} role="status">
            {msg.text}
          </span>
        )}
      </div>
    </div>
  );
}
