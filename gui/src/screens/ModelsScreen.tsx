import { useState } from "react";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, CapButton } from "../components/ui";

export function ModelsScreen() {
  const { backend, revision, t, caps } = useApp();
  const state = useAsync(() => backend.listModels(), [backend, revision]);
  const [msg, setMsg] = useState<string>();
  const pull = async (id: string) => {
    setMsg(undefined);
    try {
      const job = await backend.pullModel(id);
      setMsg(`${id}: ${job.state}`);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <div className="stack">
      {caps.mode === "mock" && <p className="notice small">{t("models.readOnly")}</p>}
      {msg && <p role="status">{msg}</p>}
      <Async state={state}>
        {(reg) => (
          <>
            {reg.note && <p className="muted small">{reg.note}</p>}
            <div className="screen-grid">
              {reg.models.map((m) => (
                <Card
                  key={m.id}
                  title={<code>{m.id}</code>}
                  actions={
                    <CapButton allowed={caps.modelDownload && !!m.weights?.source_url} icon="download" onClick={() => pull(m.id)} className="btn secondary">
                      {t("models.pull")}
                    </CapButton>
                  }
                >
                  <dl className="kv">
                    <dt>{t("models.task")}</dt>
                    <dd>
                      {m.task}
                      {m.stems ? ` (${m.stems.join(", ")})` : ""}
                    </dd>
                    <dt>{t("models.tier")}</dt>
                    <dd>{m.tier}</dd>
                    <dt>{t("models.status")}</dt>
                    <dd>
                      <span className="tag">{m.status}</span>
                    </dd>
                    <dt>{t("models.code")}</dt>
                    <dd>{m.license.code ?? "—"}</dd>
                    <dt>{t("models.weights")}</dt>
                    <dd>{m.license.weights ?? "—"}</dd>
                    <dt>{t("models.usage")}</dt>
                    <dd>{m.license.usage_restrictions ?? "—"}</dd>
                  </dl>
                  {m.license.evidence && m.license.evidence.length > 0 && (
                    <details>
                      <summary>{t("models.evidence")}</summary>
                      <ul className="plain-list small">
                        {m.license.evidence.map((e, i) => (
                          <li key={i}>
                            {/* Shown as text, not a link: the GUI never navigates to third-party hosts on its own. */}
                            <code className="break">{e.url}</code> {e.checked_on && `(${e.checked_on})`} {e.note}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {m.license.caveats && m.license.caveats.length > 0 && (
                    <p className="muted small">
                      {t("models.caveats")}: {m.license.caveats.join(" ")}
                    </p>
                  )}
                </Card>
              ))}
            </div>
            {reg.excluded_from_standard_route && reg.excluded_from_standard_route.length > 0 && (
              <Card title={t("models.excluded")}>
                <ul className="plain-list">
                  {reg.excluded_from_standard_route.map((x) => (
                    <li key={x.name}>
                      <strong>{x.name}</strong>: {x.reason}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </>
        )}
      </Async>
    </div>
  );
}
