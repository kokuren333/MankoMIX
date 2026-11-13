import { useState } from "react";
import { Icon, type IconName } from "../components/Icon";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, CapButton } from "../components/ui";
import type { StringKey } from "../i18n/strings";
import type { Actor } from "../types";

const ACTOR_ICON: Record<Actor, IconName> = { human: "human", agent: "agent", planner: "chain" };

export function HistoryScreen() {
  const { backend, revision, t, label, caps, bump, lang } = useApp();
  const state = useAsync(() => backend.history(100), [backend, revision]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const undo = async () => {
    setBusy(true);
    setErr(undefined);
    try {
      await backend.undo();
      bump();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const fmtWhen = (ts: string) => {
    const d = new Date(ts);
    return Number.isNaN(d.getTime()) ? ts : d.toLocaleString(lang === "ja" ? "ja-JP" : "en-GB");
  };
  return (
    <Card
      title={t("nav.history")}
      actions={
        <CapButton allowed={caps.undo} busy={busy} icon="undo" onClick={undo} data-testid="undo">
          {t("history.undo")}
        </CapButton>
      }
    >
      {err && (
        <p className="error" role="alert">
          {err}
        </p>
      )}
      <Async state={state}>
        {(entries) =>
          entries.length === 0 ? (
            <p className="muted">{t("history.empty")}</p>
          ) : (
            <ol className="history">
              {entries.map((e) => (
                <li key={e.seq} className={"history-item" + (e.undone ? " undone" : "")}>
                  <span className="num muted">#{e.seq}</span>
                  <span className={`actor actor-${e.actor}`}>
                    <Icon name={ACTOR_ICON[e.actor] ?? "human"} />
                    {t(`actor.${e.actor}` as StringKey)}
                  </span>
                  <span className="history-what">
                    <code>{e.op}</code> {label(e.summary)}
                    {e.reason && <span className="muted small block">{e.reason}</span>}
                  </span>
                  <time className="muted small" dateTime={e.ts}>
                    {fmtWhen(e.ts)}
                  </time>
                  {e.undone && <span className="tag">{t("history.undone")}</span>}
                </li>
              ))}
            </ol>
          )
        }
      </Async>
    </Card>
  );
}
