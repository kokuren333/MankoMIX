import { useState } from "react";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, CapButton, StatusBadge, SyntheticFlag, fmtNum } from "../components/ui";
import type { MediaProfile, Verification } from "../types";

export function VerifyScreen() {
  const { backend, revision, variantId } = useApp();
  const state = useAsync(() => Promise.all([backend.getVerification(variantId), backend.listProfiles()]), [backend, revision, variantId]);
  return <Async state={state} variantDependent>{([v, p]) => <VerifyView v={v} profiles={p} />}</Async>;
}

function fmtVal(v: unknown): string {
  return typeof v === "number" ? fmtNum(v, 1) : v == null ? "—" : String(v);
}

function VerifyView({ v, profiles }: { v: Verification; profiles: MediaProfile[] }) {
  const { t, label, caps, backend, bump, variantId } = useApp();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const run = async () => {
    setBusy(true);
    setErr(undefined);
    try {
      await backend.verify(variantId);
      bump();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const profLabel = (id: string) => label(profiles.find((p) => p.id === id)?.label, id);

  return (
    <div className="screen-grid">
      <Card
        title={
          <>
            {t("verify.overall")} <StatusBadge status={v.overall} />
          </>
        }
        className="span-2"
        actions={
          caps.mode === "local" ? (
            <CapButton allowed={caps.runVerify} busy={busy} icon="validate-ok" onClick={run}>
              {t("verify.run")}
            </CapButton>
          ) : undefined
        }
      >
        <SyntheticFlag synthetic={v.synthetic} />
        {err && (
          <p className="error" role="alert">
            {err}
          </p>
        )}
      </Card>

      <Card title={t("verify.constraints")}>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>{t("analysis.status")}</th>
                <th>{t("verify.value")}</th>
                <th>{t("verify.limit")}</th>
              </tr>
            </thead>
            <tbody>
              {v.constraints.map((c) => (
                <tr key={c.id}>
                  <td>
                    <code>{c.id}</code>
                    {c.note && <div className="muted small">{label(c.note)}</div>}
                  </td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="num">{fmtVal(c.value)}</td>
                  <td className="num">{fmtVal(c.limit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title={
          <>
            {t("verify.gate")} <StatusBadge status={v.gate.status} />
          </>
        }
      >
        <ul className="plain-list">
          {v.gate.checks.map((c) => (
            <li key={c.id}>
              <StatusBadge status={c.status} /> {label(c.label, c.id)}
              {c.note && <div className="muted small">{label(c.note)}</div>}
            </li>
          ))}
        </ul>
      </Card>

      <Card title={t("verify.profiles")}>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("verify.profile")}</th>
                <th>{t("verify.delivery")}</th>
                <th>{t("analysis.status")}</th>
                <th>LUFS-I</th>
                <th>dBTP</th>
              </tr>
            </thead>
            <tbody>
              {v.profiles.map((p, i) => (
                <tr key={i}>
                  <td>
                    {profLabel(p.profile)}
                    {p.note && <div className="muted small">{label(p.note)}</div>}
                  </td>
                  <td>{p.delivery ?? "—"}</td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="num">{fmtNum(p.lufs_i, 1)}</td>
                  <td className="num">{fmtNum(p.true_peak_dbtp, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title={
          <>
            {t("verify.noise")} <StatusBadge status={v.noise_return.status} />
          </>
        }
      >
        <dl className="kv">
          <dt>{t("verify.delta")}</dt>
          <dd>{fmtNum(v.noise_return.delta_db, 1, "dB")}</dd>
          <dt>{t("verify.tolerance")}</dt>
          <dd>{fmtNum(v.noise_return.tolerance_db, 1, "dB")}</dd>
        </dl>
        {v.noise_return.note && <p className="muted small">{label(v.noise_return.note)}</p>}
      </Card>

      <Card title={t("verify.codec")} className="span-2">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("verify.codecName")}</th>
                <th>{t("analysis.status")}</th>
                <th>dBTP</th>
                <th>{t("intent.ceiling")}</th>
                <th>{t("verify.note")}</th>
              </tr>
            </thead>
            <tbody>
              {v.codec.map((c) => (
                <tr key={c.codec}>
                  <td>{c.codec}</td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="num">{fmtNum(c.true_peak_dbtp, 1)}</td>
                  <td className="num">{fmtNum(c.ceiling_dbtp, 1)}</td>
                  <td className="small">{label(c.note)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
