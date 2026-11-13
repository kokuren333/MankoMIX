import type { ReactNode } from "react";
import { useApp } from "../AppContext";
import type { AsyncState } from "../hooks/useAsync";
import { BackendError } from "../backend/Backend";
import type { StringKey } from "../i18n/strings";

export function Card({ title, children, actions, id, className }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; id?: string; className?: string }) {
  return (
    <section className={"card" + (className ? " " + className : "")} id={id}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

type AnyStatus = "pass" | "fail" | "warning" | "not_run" | "ok" | "incomplete" | "info" | "reject" | "critical";

const ICON: Record<AnyStatus, string> = {
  pass: "✓",
  ok: "✓",
  fail: "✕",
  reject: "✕",
  critical: "✕",
  warning: "!",
  incomplete: "…",
  not_run: "–",
  info: "i",
};

const TONE: Record<AnyStatus, string> = {
  pass: "good",
  ok: "good",
  fail: "critical",
  reject: "critical",
  critical: "critical",
  warning: "warning",
  incomplete: "muted",
  not_run: "muted",
  info: "muted",
};

/** Status shown as icon + text, never color alone. */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  const { t } = useApp();
  const s = (status ?? "not_run") as AnyStatus;
  const key = `status.${s}` as StringKey;
  return (
    <span className={`badge tone-${TONE[s] ?? "muted"}`} data-status={s}>
      <span aria-hidden="true" className="badge-icon">
        {ICON[s] ?? "?"}
      </span>
      {t(key) === key ? s : t(key)}
    </span>
  );
}

/** Loading / error wrapper for useAsync results. */
export function Async<T>({ state, children }: { state: AsyncState<T>; children: (data: T) => ReactNode }) {
  const { t } = useApp();
  if (state.error) {
    const notGen = state.error instanceof BackendError && state.error.code === "not_generated";
    return (
      <div className={notGen ? "notice" : "error"} role={notGen ? "status" : "alert"}>
        {notGen ? t("app.notGenerated") : `${t("app.error")}: ${state.error.message}`}{" "}
        {!notGen && (
          <button type="button" className="link" onClick={state.reload}>
            {t("app.retry")}
          </button>
        )}
      </div>
    );
  }
  if (state.data === undefined) return <div className="loading">{t("app.loading")}</div>;
  return <>{children(state.data)}</>;
}

/**
 * Button bound to a capability. When the capability is missing it is
 * disabled and explains why (demo vs. backend limitation).
 */
export function CapButton({
  allowed,
  onClick,
  children,
  className,
  busy,
  ...rest
}: {
  allowed: boolean;
  onClick: () => void;
  children: ReactNode;
  className?: string;
  busy?: boolean;
  "data-testid"?: string;
}) {
  const { caps, t } = useApp();
  const why = caps.mode === "mock" ? t("app.disabledInDemo") : t("app.disabledNoCap");
  return (
    <span className="cap-button">
      <button
        type="button"
        className={className ?? "btn"}
        disabled={!allowed || busy}
        aria-disabled={!allowed || busy}
        title={allowed ? undefined : why}
        onClick={onClick}
        data-testid={rest["data-testid"]}
      >
        {children}
      </button>
      {!allowed && <span className="cap-why">{why}</span>}
    </span>
  );
}

export function SyntheticFlag({ synthetic }: { synthetic?: boolean }) {
  const { t } = useApp();
  if (!synthetic) return null;
  return (
    <p className="synthetic" role="note">
      {t("app.synthetic")}
    </p>
  );
}

export function fmtNum(v: unknown, digits = 1, unit = ""): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return v == null ? "—" : String(v);
  const s = v.toFixed(digits).replace(/^-/, "−");
  return unit ? `${s} ${unit}` : s;
}

export function fmtTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function shortHash(h: string | null | undefined): string {
  return h ? `${h.slice(0, 8)}…${h.slice(-4)}` : "—";
}

export function fmtHz(hz: number): string {
  return hz >= 1000 ? `${+(hz / 1000).toFixed(hz >= 10000 ? 0 : 1)}k` : `${Math.round(hz)}`;
}
