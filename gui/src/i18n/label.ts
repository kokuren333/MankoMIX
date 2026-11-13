import type { Label, Lang } from "../types";

/** Pick a display string from a plain or per-language label. */
export function pickLabel(label: Label | null | undefined, lang: Lang, fallback = ""): string {
  if (label == null) return fallback;
  if (typeof label === "string") return label;
  return label[lang] ?? label.en ?? label.ja ?? Object.values(label).find((v) => !!v) ?? fallback;
}
