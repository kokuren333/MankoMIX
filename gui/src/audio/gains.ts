// Pure gain logic for the A/B player. The match gain itself always comes from
// the backend data (AudioSet.level_match_gains_db or match_gain_db);
// the GUI never computes loudness.

export type SourceId = "before" | "floor" | "after" | "delta";

/** Floor is optional for compatibility with two-way engine clients. */
export type SourceGains = Record<Exclude<SourceId, "floor">, number> & { floor?: number };

export interface MonitorSettings {
  mono: boolean;
  /** Small-speaker preview: band-limited playback. */
  bandLimit: boolean;
  /** Low-level preview: plays LOW_LEVEL_DB quieter. */
  lowLevel: boolean;
}

/** Monitoring preview constants (playback aids only, not processing). */
export const BAND_LIMIT_HP_HZ = 200;
export const BAND_LIMIT_LP_HZ = 8000;
export const LOW_LEVEL_DB = -20;

export function dbToGain(db: number): number {
  return Math.pow(10, db / 20);
}

export interface GainInput {
  active: SourceId;
  levelMatch: boolean;
  matchGainDb: number;
  matchTarget: "before" | "floor" | "after";
  levelMatchGainsDb?: { before: number; floor: number; after: number };
}

/**
 * Linear gain per source. Only the active source is audible (all sources run
 * in sync so switching keeps the position). With level match on, the match
 * table is used when present, otherwise the pair gain is applied to match_target.
 */
export function sourceGains({ active, levelMatch, matchGainDb, matchTarget, levelMatchGainsDb }: GainInput): SourceGains {
  const g: SourceGains = { before: 0, after: 0, delta: 0 };
  if (levelMatchGainsDb || active === "floor") g.floor = 0;
  let v = 1;
  const db = levelMatchGainsDb
    ? active === "delta" ? 0 : levelMatchGainsDb[active]
    : active === matchTarget ? matchGainDb : 0;
  if (levelMatch && Number.isFinite(db)) v = dbToGain(db);
  g[active] = v;
  return g;
}

/** Master output gain for the monitor chain. */
export function monitorGain(m: MonitorSettings): number {
  return m.lowLevel ? dbToGain(LOW_LEVEL_DB) : 1;
}
