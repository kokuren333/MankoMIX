import { useEffect, useState } from "react";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, CapButton } from "../components/ui";
import type { ParamEdits, Proposal, Stage } from "../types";
import type { StringKey } from "../i18n/strings";

const STAGES: Stage[] = ["cleanup", "mix", "master"];

export function PlanScreen() {
  const { backend, revision, variantId, caps, t, bump } = useApp();
  const state = useAsync(() => backend.listProposals(variantId), [backend, revision, variantId]);
  const [busy, setBusy] = useState<Stage | null>(null);
  const [err, setErr] = useState<string>();

  const propose = async (stage: Stage) => {
    setBusy(stage);
    setErr(undefined);
    try {
      await backend.proposePlan(stage, variantId);
      bump();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="stack">
      {caps.mode === "local" && (
        <Card title={t("plan.propose")}>
          <div className="row">
            {STAGES.map((s) => (
              <CapButton key={s} allowed={caps.runPlanner} busy={busy === s} onClick={() => propose(s)} className="btn secondary">
                {t(`plan.stage.${s}` as StringKey)}
              </CapButton>
            ))}
          </div>
          {err && (
            <p className="error" role="alert">
              {err}
            </p>
          )}
        </Card>
      )}
      <Async state={state}>
        {(proposals) =>
          proposals.length === 0 ? (
            <p className="muted">{t("plan.none")}</p>
          ) : (
            <>
              {proposals.map((p) => (
                <ProposalCard key={p.id} proposal={p} />
              ))}
            </>
          )
        }
      </Async>
    </div>
  );
}

function paramValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function parseParam(text: string, original: unknown): unknown {
  if (typeof original === "number") {
    const n = Number(text);
    return Number.isFinite(n) ? n : original;
  }
  if (typeof original === "boolean") return text === "true";
  if (typeof original === "object" && original !== null) {
    try {
      return JSON.parse(text);
    } catch {
      return original;
    }
  }
  return text;
}

function ProposalCard({ proposal: p }: { proposal: Proposal }) {
  const { t, label, caps, backend, bump, layout } = useApp();
  const [edits, setEdits] = useState<ParamEdits>({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  useEffect(() => setEdits({}), [p.id]);

  const isAgent = p.author === "agent";
  const canDecide = p.status === "pending" && caps.applyPlan && (!isAgent || caps.agentLink);
  const canEdit = canDecide && caps.editProject;

  const edit = (procId: string, key: string, value: unknown) => setEdits((e) => ({ ...e, [procId]: { ...e[procId], [key]: value } }));

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(undefined);
    try {
      await fn();
      bump();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title={
        <>
          {t(`plan.stage.${p.stage}` as StringKey)} <code className="small">{p.id}</code>
        </>
      }
      actions={
        <span className="row">
          <span className={`actor actor-${p.author}`}>
            {t("plan.author")}: {t(`actor.${p.author}` as StringKey)}
          </span>
          <span className="tag">{t(`plan.status.${p.status}` as StringKey)}</span>
        </span>
      }
    >
      {p.summary && <p>{label(p.summary)}</p>}
      <ol className="chain">
        {p.steps.map((s) => {
          const params = { ...s.processor.params, ...edits[s.processor.id] };
          const editableKeys = s.editable ?? Object.keys(s.processor.params);
          return (
            <li key={s.processor.id} className="chain-step">
              <div className="chain-head">
                <span>
                  <strong>{s.processor.type}</strong> <span className="muted">→ {s.target}</span>
                </span>
                <span className="rule-chips">
                  {s.processor.reason.split(/[,\s]+/).filter(Boolean).map((r) => (
                    <span key={r} className={/^R-\d+/.test(r) ? "chip rule" : "chip"} title={t("plan.reason")}>
                      {r}
                    </span>
                  ))}
                </span>
              </div>
              <dl className={"params" + (layout === "narrow" ? " params-narrow" : "")}>
                {Object.entries(params).map(([k, v]) => (
                  <div key={k} className="param">
                    <dt>{k}</dt>
                    <dd>
                      {canEdit && editableKeys.includes(k) && (layout !== "narrow" || typeof v !== "object") ? (
                        <input
                          aria-label={`${s.processor.id} ${k}`}
                          type={typeof s.processor.params[k] === "number" ? "number" : "text"}
                          step="any"
                          value={paramValue(v)}
                          onChange={(e) => edit(s.processor.id, k, parseParam(e.target.value, s.processor.params[k]))}
                        />
                      ) : (
                        <span className="num">{paramValue(v)}</span>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
              {s.note && <p className="muted small">{label(s.note)}</p>}
              {s.alternatives && s.alternatives.length > 0 && (
                <p className="muted small">
                  {t("report.alternatives")}: {s.alternatives.map((a) => label(a)).join(" / ")}
                </p>
              )}
            </li>
          );
        })}
      </ol>
      {p.status === "rejected" && p.reject_reason && (
        <p className="muted">
          {t("plan.reject")}: {p.reject_reason}
        </p>
      )}
      {p.status === "pending" && (
        <div className="decide">
          {isAgent && !caps.agentLink && <p className="notice small">{t("plan.agentNeedsLink")}</p>}
          <div className="row">
            <CapButton allowed={canDecide} busy={busy} onClick={() => run(() => backend.applyPlan(p.id, edits))} data-testid="plan-approve">
              {t("plan.approve")}
            </CapButton>
            <input
              className="reason"
              placeholder={t("plan.rejectReason")}
              aria-label={t("plan.rejectReason")}
              value={reason}
              disabled={!canDecide}
              onChange={(e) => setReason(e.target.value)}
            />
            <CapButton allowed={canDecide} busy={busy} className="btn danger" onClick={() => run(() => backend.rejectPlan(p.id, reason))} data-testid="plan-reject">
              {t("plan.reject")}
            </CapButton>
          </div>
          {err && (
            <p className="error" role="alert">
              {err}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
