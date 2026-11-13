import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Backend, Capabilities } from "./backend/Backend";
import { defaultEngineFactory, type EngineFactory } from "./audio/engine";
import { STRINGS, type StringKey } from "./i18n/strings";
import { pickLabel } from "./i18n/label";
import type { ChangeEvent, Label, Lang, VariantSummary } from "./types";
import { useBreakpoint, type Layout } from "./hooks/useBreakpoint";

export interface AppState {
  backend: Backend;
  caps: Capabilities;
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: StringKey) => string;
  label: (l: Label | null | undefined, fallback?: string) => string;
  variants: VariantSummary[];
  variantId: string;
  setVariantId: (id: string) => void;
  variant?: VariantSummary;
  /** Incremented whenever the project changes (own edits or pushed events). */
  revision: number;
  bump: () => void;
  lastEvent?: ChangeEvent;
  clearEvent: () => void;
  connection: "open" | "lost" | "none";
  engineFactory: EngineFactory;
  layout: Layout;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}

function initialLang(): Lang {
  const q = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("lang") : null;
  if (q === "ja" || q === "en") return q;
  try {
    const saved = localStorage.getItem("mankomix.lang");
    if (saved === "ja" || saved === "en") return saved;
  } catch {
    // storage unavailable
  }
  return typeof navigator !== "undefined" && navigator.language?.startsWith("ja") ? "ja" : "en";
}

export interface AppProviderProps {
  backend: Backend;
  lang?: Lang;
  engineFactory?: EngineFactory;
  children: ReactNode;
}

export function AppProvider({ backend, lang: langProp, engineFactory, children }: AppProviderProps) {
  const [lang, setLangState] = useState<Lang>(langProp ?? initialLang);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [variants, setVariants] = useState<VariantSummary[]>([]);
  const [variantId, setVariantId] = useState("");
  const [revision, setRevision] = useState(0);
  const [lastEvent, setLastEvent] = useState<ChangeEvent>();
  const [connection, setConnection] = useState<"open" | "lost" | "none">("none");
  const [bootError, setBootError] = useState<Error | null>(null);
  const layout = useBreakpoint();

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("mankomix.lang", l);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    let alive = true;
    Promise.all([backend.capabilities(), backend.listVariants()])
      .then(([c, vs]) => {
        if (!alive) return;
        setCaps(c);
        setVariants(vs);
        setVariantId((cur) => cur || vs.find((v) => v.available)?.id || vs[0]?.id || "");
      })
      .catch((e: Error) => alive && setBootError(e));
    return () => {
      alive = false;
    };
  }, [backend]);

  useEffect(() => {
    if (!caps?.liveUpdates) return;
    return backend.subscribe((ev) => {
      if (ev.type === "connection") {
        setConnection(ev.state);
        return;
      }
      setLastEvent(ev);
      if (ev.type === "project_changed" || ev.type === "proposal") setRevision((n) => n + 1);
      if (ev.type === "project_changed") {
        backend
          .listVariants()
          .then(setVariants)
          .catch(() => {});
      }
    });
  }, [backend, caps]);

  const value = useMemo<AppState | null>(() => {
    if (!caps) return null;
    const dict = STRINGS[lang];
    return {
      backend,
      caps,
      lang,
      setLang,
      t: (key) => dict[key] ?? key,
      label: (l, fallback) => pickLabel(l, lang, fallback),
      variants,
      variantId,
      setVariantId,
      variant: variants.find((v) => v.id === variantId),
      revision,
      bump: () => setRevision((n) => n + 1),
      lastEvent,
      clearEvent: () => setLastEvent(undefined),
      connection,
      engineFactory: engineFactory ?? defaultEngineFactory,
      layout,
    };
  }, [backend, caps, lang, setLang, variants, variantId, revision, lastEvent, connection, engineFactory, layout]);

  if (bootError) {
    const dict = STRINGS[lang];
    return (
      <div className="boot-error" role="alert">
        <h1>MankoMIX</h1>
        <p>
          {dict["app.error"]}: {bootError.message}
        </p>
        <p className="muted">{backend.kind === "local" ? "mankomix serve" : "demo/index.json"}</p>
      </div>
    );
  }
  if (!value) return <div className="boot">{STRINGS[lang]["app.loading"]}</div>;
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
