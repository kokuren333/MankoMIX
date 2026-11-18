import { useEffect, useState, type ComponentType } from "react";
import { useApp } from "./AppContext";
import type { StringKey } from "./i18n/strings";
import type { Lang, VariantSummary } from "./types";
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
import { NotesScreen, SpectralScreen, MetersScreen } from "./screens/ObservationScreens";
import { Icon, type IconName } from "./components/Icon";

export const SCREENS: { id: string; label: StringKey; icon: IconName; component: ComponentType }[] = [
  { id: "project", label: "nav.project", icon: "folder", component: ProjectScreen },
  { id: "stems", label: "nav.stems", icon: "stem", component: StemsScreen },
  { id: "mixmap", label: "nav.mixmap", icon: "grid", component: MixMapScreen },
  { id: "analysis", label: "nav.analysis", icon: "meter", component: AnalysisScreen },
  { id: "intent", label: "nav.intent", icon: "settings", component: IntentScreen },
  { id: "plan", label: "nav.plan", icon: "chain", component: PlanScreen },
  { id: "listen", label: "nav.listen", icon: "headphones", component: ListenScreen },
  { id: "verify", label: "nav.verify", icon: "validate-ok", component: VerifyScreen },
  { id: "report", label: "nav.report", icon: "report", component: ReportScreen },
  { id: "models", label: "nav.models", icon: "model", component: ModelsScreen },
  { id: "history", label: "nav.history", icon: "undo", component: HistoryScreen },
];

SCREENS.push(
  { id: "notes", label: "nav.notes", icon: "stem", component: NotesScreen },
  { id: "spectral", label: "nav.spectral", icon: "grid", component: SpectralScreen },
  { id: "meters", label: "nav.meters", icon: "meter", component: MetersScreen },
);

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
      <strong className="with-icon">
        <Icon name="info" />
        {t("mock.title")}
      </strong>
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
        <Icon name="warning" />
        {t("app.liveLost")}
      </div>
    );
  if (!lastEvent || lastEvent.type !== "project_changed") return null;
  const who = lastEvent.actor ? t(`actor.${lastEvent.actor}` as StringKey) : "";
  return (
    <div className={"toast" + (lastEvent.actor === "agent" ? " agent" : "")} role="status">
      <Icon name={lastEvent.actor === "agent" ? "agent" : lastEvent.actor === "planner" ? "chain" : "human"} />
      {t("app.changedBy")} <strong>{who}</strong>
      {lastEvent.seq != null && ` (#${lastEvent.seq})`} {label(lastEvent.summary)}
      <button type="button" className="link" onClick={clearEvent}>
        {t("app.dismiss")}
      </button>
    </div>
  );
}

function VariantPicker() {
  const { variants, variantId, setVariantId, t, label, lang } = useApp();
  if (variants.length === 0) return null;
  const optionText = (v: VariantSummary) => {
    // A direction example is headed by its direction; the objective × profile
    // is the floor it was applied on top of, not the headline.
    const head = v.direction
      ? `${t("direction.short")}${v.direction.pattern ? ` ${v.direction.pattern}` : ""} ${lang === "ja" ? "「" : "\""}${label(v.direction.request ?? v.direction.title, v.direction.id)}${lang === "ja" ? "」" : "\""} × ${v.profile}`
      : `${v.objectives.join("+")} × ${v.profile}`;
    return `${v.n != null ? `#${v.n} ` : ""}${head}${v.available ? "" : " (—)"}`;
  };
  return (
    <label className="variant-picker">
      <span className="sr-only">{t("app.variant")}</span>
      <select value={variantId} onChange={(e) => setVariantId(e.target.value)} aria-label={t("app.variant")}>
        {variants.map((v) => (
          <option key={v.id} value={v.id}>
            {optionText(v)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function DirectionBanner() {
  const { variant, t, label } = useApp();
  const d = variant?.direction;
  if (!variant || !d) return null;
  return (
    <aside className="direction-banner" role="note" aria-label={t("direction.short")} data-testid="direction-banner">
      <strong className="with-icon">
        <Icon name="agent" />
        {t("direction.short")}
        {d.pattern ? ` ${d.pattern}` : ""}: {label(d.request ?? d.title, d.id)}
      </strong>
      <p>
        {t("direction.floorNote")} ({variant.objectives.join("+")} × {variant.profile})
      </p>
    </aside>
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
          <span className={`mode-badge mode-${caps.mode}`}>
            {caps.mode === "mock" && <Icon name="lock" />}
            {caps.mode === "mock" ? t("app.backend.mock") : t("app.backend.local")}
          </span>
          {caps.liveUpdates && connection === "open" && (
            <span className="live-dot">
              <Icon name="link" label={t("app.liveOn")} />
            </span>
          )}
        </div>
        <div className="topbar-controls">
          <VariantPicker />
          <LangToggle />
        </div>
      </header>
      <MockBanner />
      <DirectionBanner />
      <ChangeToast />
      <div className="body">
        <nav className="nav" aria-label={t("app.nav")}>
          {SCREENS.map((s) => (
            <a key={s.id} href={`#/${s.id}`} className={route === s.id ? "active" : undefined} aria-current={route === s.id ? "page" : undefined} onClick={(e) => {
              e.preventDefault();
              go(s.id);
            }}>
              <Icon name={s.icon} />
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
