import { useEffect, useState } from "react";

export type Layout = "narrow" | "medium" | "wide";

/** Width thresholds in CSS pixels (SPEC 11.3: phone width up to desktop width). */
export const NARROW_MAX = 719;
export const MEDIUM_MAX = 1099;

/** Pure classification so the responsive logic is testable without pixels. */
export function classifyWidth(width: number): Layout {
  if (width <= NARROW_MAX) return "narrow";
  if (width <= MEDIUM_MAX) return "medium";
  return "wide";
}

function currentWidth(): number {
  return typeof window === "undefined" ? 1280 : window.innerWidth;
}

/** Current layout class, updated on resize / orientation change. */
export function useBreakpoint(): Layout {
  const [layout, setLayout] = useState<Layout>(() => classifyWidth(currentWidth()));
  useEffect(() => {
    const onResize = () => setLayout(classifyWidth(currentWidth()));
    window.addEventListener("resize", onResize);
    window.addEventListener("orientationchange", onResize);
    onResize();
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("orientationchange", onResize);
    };
  }, []);
  return layout;
}
