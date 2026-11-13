import { useRef, useState } from "react";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, CapButton, StatusBadge, fmtNum, shortHash } from "../components/ui";
import type { Project } from "../types";

export function ProjectScreen() {
  const { backend, revision } = useApp();
  const state = useAsync(() => backend.getProject(), [backend, revision]);
  return <Async state={state}>{(p) => <ProjectView project={p} />}</Async>;
}

function ProjectView({ project: p }: { project: Project }) {
  const { t, caps, backend, bump } = useApp();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>();
  const rate = p.timebase.sample_rate;
  const len = p.timebase.length_samples;

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setMsg(undefined);
    try {
      await backend.importFiles(Array.from(files));
      bump();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="screen-grid">
      <Card
        title={t("project.overview")}
        actions={
          <>
            <input ref={fileRef} type="file" accept="audio/*,.wav,.flac,.aiff,.aif" multiple hidden onChange={(e) => onFiles(e.target.files)} />
            <CapButton allowed={caps.importAudio} busy={busy} onClick={() => fileRef.current?.click()} data-testid="import-button">
              {busy ? t("project.importing") : t("project.import")}
            </CapButton>
          </>
        }
      >
        <dl className="kv">
          <dt>{t("project.title")}</dt>
          <dd>{p.title}</dd>
          <dt>{t("project.genre")}</dt>
          <dd>{p.genre ?? "—"}</dd>
          <dt>{t("project.sampleRate")}</dt>
          <dd>{rate ? `${rate} Hz` : "—"}</dd>
          <dt>{t("project.bpm")}</dt>
          <dd>{p.timebase.bpm ?? "—"}</dd>
          <dt>{t("project.key")}</dt>
          <dd>{p.timebase.key ?? "—"}</dd>
          <dt>{t("project.length")}</dt>
          <dd>{rate && len ? `${fmtNum(len / rate, 1)} s` : "—"}</dd>
        </dl>
        {caps.importAudio && <p className="muted small">{t("project.importHint")}</p>}
        {msg && (
          <p className="error" role="alert">
            {msg}
          </p>
        )}
      </Card>

      <Card title={t("project.provenance")}>
        {p.provenance ? (
          <dl className="kv">
            {Object.entries(p.provenance).map(([k, v]) => (
              <div key={k} className="kv-row">
                <dt>{k}</dt>
                <dd>{v === null || v === "" ? "—" : String(v)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="muted">—</p>
        )}
      </Card>

      <Card title={t("project.checks")} className="span-2">
        {p.ingest?.checks?.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t("check.level")}</th>
                  <th>{t("check.check")}</th>
                  <th>{t("check.asset")}</th>
                  <th>{t("check.message")}</th>
                </tr>
              </thead>
              <tbody>
                {p.ingest.checks.map((c, i) => (
                  <tr key={i}>
                    <td>
                      <StatusBadge status={c.level} />
                    </td>
                    <td>
                      <code>{c.check}</code>
                    </td>
                    <td>{c.asset ?? "—"}</td>
                    <td>{c.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">{t("project.noChecks")}</p>
        )}
      </Card>

      <Card title={`${t("project.assets")} (${p.assets.length})`} className="span-2">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("asset.id")}</th>
                <th>{t("asset.name")}</th>
                <th>{t("asset.role")}</th>
                <th>{t("asset.origin")}</th>
                <th>{t("asset.format")}</th>
                <th>{t("asset.hash")}</th>
              </tr>
            </thead>
            <tbody>
              {p.assets.map((a) => (
                <tr key={a.id}>
                  <td>
                    <code>{a.id}</code>
                  </td>
                  <td>{a.original_name ?? a.path}</td>
                  <td>{a.role}</td>
                  <td>{a.origin}</td>
                  <td>
                    {a.format ?? "—"}
                    {a.sample_rate ? ` · ${a.sample_rate} Hz` : ""}
                    {a.channels ? ` · ${a.channels}ch` : ""}
                  </td>
                  <td>
                    <code title={a.sha256}>{shortHash(a.sha256)}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
