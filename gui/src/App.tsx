import { useEffect, useState, type ComponentType } from "react";
import { useApp } from "./AppContext";
import type { StringKey } from "./i18n/strings";
import type { Lang } from "./types";
import { ProjectScreen } from "./screens/ProjectScreen";
import { StemsScreen } from "./screens/StemsScreen";
import { MixMapScreen } from "./screens/MixMapScreen";
import { AnalysisScreen } from "./screens/AnalysisScreen";
import { IntentScreen } from "./screens/IntentScreen";
import { PlanScreen } from "./screens/PlanScreen";
import { ListenScreen } from "./screens/ListenScreen";
import { VerifyScreen } from "./screens/VerifyScreen";
import { ReportScreen } from "./screens/ReportScreen";
import { ModelsScreen } from "./screens/ModelsScreen";
import { HistoryScreen } from "./screens/HistoryScreen";

export const SCREENS: { id: string; label: StringKey; component: ComponentType }[] = [
  { id: "project", label: "nav.project", component: ProjectScreen },
  { id: "stems", label: "nav.stems", component: StemsScreen },
  { id: "mixmap", label: "nav.mixmap", component: MixMapScreen },
  { id: "analysis", label: "nav.analysis", component: AnalysisScreen },
  { id: "intent", label: "nav.intent", component: IntentScreen },
  { id: "plan", label: "nav.plan", component: PlanScreen },
  { id: "listen", label: "nav.listen", component: ListenScreen },
  { id: "verify", label: "nav.verify", component: VerifyScreen },
  { id: "report", label: "nav.report", component: ReportScreen },
  { id: "models", label: "nav.models", component: ModelsScreen },
  { id: "history", label: "nav.history", component: HistoryScreen },
];

function readHash(): string {
  const h = typeof window !== "undefined" ? window.location.hash.replace(/^#\/?/, "") : "";
  return SCREENS.some((s) => s.id === h) ? h : "listen";
}

/** Hash routing keeps the static build working under any sub-path. */
function useRoute(): [string, (id: string) => void] {
  const [route, setRoute] = useState(readHash);
  useEffect(() => {
    const on = () => setRoute(readHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [route, (id) => (window.location.hash = `#/${id}`)];
}

export function MockBanner() {
  const { caps, t } = useApp();
  if (caps.mode !== "mock") return null;
  return (
    <aside className="mock-banner" role="note" aria-label={t("mock.title")} data-testid="mock-banner">
      <strong>{t("mock.title")}</strong>
      <p>{t("mock.body")}</p>
      <details>
        <summary>{t("mock.cannot")}</summary>
        <ul>
          <li>{t("mock.cannot.upload")}</li>
          <li>{t("mock.cannot.dsp")}</li>
          <li>{t("mock.cannot.agent")}</li>
          <li>{t("mock.cannot.models")}</li>
        </ul>
        <p className="small">{t("mock.switchHint")}</p>
      </details>
    </aside>
  );
}

function ChangeToast() {
  const { lastEvent, clearEvent, t, label, connection } = useApp();
  if (connection === "lost")
    return (
      <div className="toast warn" role="status">
        {t("app.liveLost")}
      </div>
    );
  if (!lastEvent || lastEvent.type !== "project_changed") return null;
  const who = lastEvent.actor ? t(`actor.${lastEvent.actor}` as StringKey) : "";
  return (
    <div className={"toast" + (lastEvent.actor === "agent" ? " agent" : "")} role="status">
      {t("app.changedBy")} <strong>{who}</strong>
      {lastEvent.seq != null && ` (#${lastEvent.seq})`} {label(lastEvent.summary)}
      <button type="button" className="link" onClick={clearEvent}>
        {t("app.dismiss")}
      </button>
    </div>
  );
}

function VariantPicker() {
  const { variants, variantId, setVariantId, t } = useApp();
  if (variants.length === 0) return null;
  return (
    <label className="variant-picker">
      <span className="sr-only">{t("app.variant")}</span>
      <select value={variantId} onChange={(e) => setVariantId(e.target.value)} aria-label={t("app.variant")}>
        {variants.map((v) => (
          <option key={v.id} value={v.id}>
            {v.n != null ? `#${v.n} ` : ""}
            {v.objectives.join("+")} × {v.profile}
            {v.available ? "" : " (—)"}
          </option>
        ))}
      </select>
    </label>
  );
}

function LangToggle() {
  const { lang, setLang, t } = useApp();
  return (
    <span className="seg" role="radiogroup" aria-label={t("app.lang")}>
      {(["ja", "en"] as Lang[]).map((l) => (
        <button key={l} type="button" role="radio" aria-checked={lang === l} className={"seg-btn" + (lang === l ? " active" : "")} onClick={() => setLang(l)}>
          {l.toUpperCase()}
        </button>
      ))}
    </span>
  );
}

export function App() {
  const { t, caps, layout, connection } = useApp();
  const [route, go] = useRoute();
  const Screen = SCREENS.find((s) => s.id === route)?.component ?? ListenScreen;
  return (
    <div className={`app layout-${layout} mode-${caps.mode} route-${route}`} data-testid="app-root">
      <header className="topbar">
        <div className="brand">
          <span className="logo">{t("app.title")}</span>
          <span className={`mode-badge mode-${caps.mode}`}>{caps.mode === "mock" ? t("app.backend.mock") : t("app.backend.local")}</span>
          {caps.liveUpdates && connection === "open" && <span className="live-dot" title={t("app.liveOn")} aria-label={t("app.liveOn")} />}
        </div>
        <div className="topbar-controls">
          <VariantPicker />
          <LangToggle />
        </div>
      </header>
      <MockBanner />
      <ChangeToast />
      <div className="body">
        <nav className="nav" aria-label={t("app.nav")}>
          {SCREENS.map((s) => (
            <a key={s.id} href={`#/${s.id}`} className={route === s.id ? "active" : undefined} aria-current={route === s.id ? "page" : undefined} onClick={(e) => {
              e.preventDefault();
              go(s.id);
            }}>
              {t(s.label)}
            </a>
          ))}
        </nav>
        <main className="main">
          <h1 className="screen-title">{t(SCREENS.find((s) => s.id === route)!.label)}</h1>
          <Screen />
        </main>
      </div>
    </div>
  );
}
