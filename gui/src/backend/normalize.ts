// Shape adapters: accept both the raw data files (objectives/catalog.json,
// profiles/*.json) and list-style API responses. Pure data reshaping only.
import type { DeliveryFormat, MediaProfile, ObjectiveCatalog, ObjectiveDef, Project, VariantSummary } from "../types";

export function normalizeCatalog(raw: unknown): ObjectiveCatalog {
  if (Array.isArray(raw)) return { default: (raw[0] as ObjectiveDef)?.id ?? "comfort", objectives: raw as ObjectiveDef[] };
  const r = raw as Partial<ObjectiveCatalog> & { items?: ObjectiveDef[] };
  const objectives = r.objectives ?? r.items ?? [];
  return { default: r.default ?? objectives[0]?.id ?? "comfort", objectives, note: r.note };
}

export function normalizeProfiles(raw: unknown): MediaProfile[] {
  if (Array.isArray(raw)) return raw as MediaProfile[];
  const r = raw as { profiles?: MediaProfile[]; items?: MediaProfile[] };
  return r.profiles ?? r.items ?? [];
}

export function normalizeDeliveries(raw: unknown): DeliveryFormat[] {
  if (Array.isArray(raw)) return raw as DeliveryFormat[];
  const r = raw as { formats?: DeliveryFormat[]; deliveries?: DeliveryFormat[]; items?: DeliveryFormat[] };
  return r.formats ?? r.deliveries ?? r.items ?? [];
}

/** Derive variant summaries from project.variants (used when the server has no /variants). */
export function variantsFromProject(project: Project): VariantSummary[] {
  return (project.variants ?? []).map((v) => {
    const obj = v.objective ?? project.objective;
    const blend = [...(obj?.blend ?? [])].sort((a, b) => b.weight - a.weight);
    return {
      id: v.id,
      label: v.label,
      objectives: blend.map((b) => b.id),
      objective: obj,
      profile: v.outputs[0]?.profile ?? "",
      deliveries: v.outputs.map((o) => o.delivery),
      intensity: obj?.intensity,
      available: true,
    };
  });
}
