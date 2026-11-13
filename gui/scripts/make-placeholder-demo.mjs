// Generate the SYNTHETIC placeholder demo dataset in public/demo/.
//
// Every number written here is invented so the GUI can be developed and
// tested before the core can produce real results. Every file carries
// "synthetic": true and the UI shows a banner for it. The real dataset is
// produced by a Python build step from the core (SPEC 11.4) using the same
// layout (see gui/DEMO_DATA.md) and replaces these files. No audio is written.
//
// Usage: npm run demo:placeholder
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const out = resolve(here, "..", "public", "demo");

const sampleSet = JSON.parse(readFileSync(join(repo, "samples/sample_set.json"), "utf8"));
const profiles = JSON.parse(readFileSync(join(repo, "profiles/media_profiles.json"), "utf8")).profiles;

// Variants with placeholder data; the rest are listed as not generated.
const AVAILABLE = new Set([1, 2, 10]);
const HOP_S = 2;
const LENGTH_S = 99;
const SR = 48000;

const r1 = (x) => Math.round(x * 10) / 10;
const r2 = (x) => Math.round(x * 100) / 100;
const fakeSha = (i) => (i + 1).toString(16).padStart(64, "0");
const write = (rel, obj) => {
  const p = join(out, rel);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, JSON.stringify(obj, null, 1) + "\n");
};
const L = (en, ja) => ({ en, ja });
const SYN = L("(synthetic placeholder)", "（合成のプレースホルダー）");

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

// --------------------------------------------------------------------------
// Project
// --------------------------------------------------------------------------
const TRACKS = [
  { id: "trk_vocals", role: "vocals", name: "Vocals", pan: 0, gain: -1.5, lead: true, imp: 1.0, centroid: 1900, depth: 0.92 },
  { id: "trk_backing", role: "backing_vocals", name: "Backing vocals", pan: -0.35, gain: -6, imp: 0.6, centroid: 2300, depth: 0.45 },
  { id: "trk_drums", role: "drums", name: "Drums", pan: 0, gain: -3, imp: 0.9, centroid: 2600, depth: 0.7 },
  { id: "trk_bass", role: "bass", name: "Bass", pan: 0, gain: -4, imp: 0.85, centroid: 140, depth: 0.65 },
  { id: "trk_synth", role: "synth", name: "Synth", pan: 0.3, gain: -7, imp: 0.5, centroid: 1500, depth: 0.4 },
  { id: "trk_fx", role: "fx", name: "FX", pan: 0.6, gain: -12, imp: 0.2, centroid: 5200, depth: 0.2 },
];

const project = {
  schema_version: 1,
  id: "prj_demo_placeholder",
  title: "Synthetic placeholder project",
  genre: sampleSet.genre ?? null,
  timebase: {
    sample_rate: SR,
    bpm: 92.0,
    key: null,
    length_samples: LENGTH_S * SR,
    conform_policy: { sample_rate: "majority", alignment: "head", short_assets: "pad_silence_at_render" },
  },
  provenance: {
    source: "ai_generated",
    service: "suno",
    input_kind: "suno_studio_multitrack_export",
    detected_by: "filename_pattern",
    declared_by_user: false,
    notes: "synthetic placeholder; not the real sample",
  },
  assets: TRACKS.map((t, i) => ({
    id: t.id.replace("trk_", "ast_"),
    path: `assets/${String(i + 1).padStart(2, "0")} ${t.name}.wav`,
    original_name: `${String(i + 1).padStart(2, "0")} ${t.name}.wav`,
    sha256: fakeSha(i),
    format: "wav_f32",
    channels: 2,
    sample_rate: SR,
    length_samples: LENGTH_S * SR,
    duration_s: LENGTH_S,
    role: t.role,
    role_source: "filename_pattern",
    origin: "native_stem",
  })),
  fullmix_asset: null,
  ingest: {
    adapter: "files",
    input_kind: "suno_studio_multitrack_export",
    detected_by: "filename_pattern",
    checks: [
      { check: "input_kind", level: "info", asset: null, message: "Suno Studio multitrack export detected (synthetic)" },
      { check: "sample_rate", level: "info", asset: null, message: "All assets at 48000 Hz (synthetic)" },
      { check: "hf_cutoff", level: "warning", asset: "ast_fx", message: "High-frequency cutoff near 16 kHz (synthetic)", values: { cutoff_hz: 16000 } },
      { check: "stem_sum", level: "info", asset: null, message: "Stem sum consistent with the reference mix (synthetic)" },
    ],
  },
  tracks: TRACKS.map((t) => ({
    id: t.id,
    kind: "audio",
    name: t.name,
    role: t.role,
    is_lead: !!t.lead,
    importance: { value: t.imp, source: "genre_prior", by_section: {} },
    clips: [{ id: `clp_${t.id.slice(4)}`, asset: t.id.replace("trk_", "ast_"), source_start: 0, length: LENGTH_S * SR, timeline_start: 0, gain_db: 0, fade_in: 0, fade_out: 0, muted: false }],
    cleanup: { enabled: true, plan: "auto", overrides: {} },
    chain: [{ id: `prc_${t.id.slice(4)}_hpf`, type: "filter", params: { mode: "hpf", cutoff_hz: t.role === "bass" ? 30 : 90, slope_db_oct: 12 }, reason: "R-07" }],
    gain_db: t.gain,
    pan: { position: t.pan, width: 1.0 },
    muted: false,
    solo: false,
    sends: [],
    output: "bus_mix",
  })),
  buses: [{ id: "bus_mix", kind: "mix", chain: [] }],
  mix: { pan_law_center_db: -3.0, declared_depth_order: ["trk_vocals", "trk_drums", "trk_bass"] },
  objective: { blend: [{ id: "comfort", weight: 1.0 }], intensity: sampleSet.intensity ?? 0.5, lead_stem: "trk_vocals" },
  references: [],
  listening_assumption: { system: "speakers_60deg", level: "moderate" },
  variants: [],
  engine: { min_version: "0.1.0" },
  notes: "SYNTHETIC PLACEHOLDER generated by gui/scripts/make-placeholder-demo.mjs",
};

// --------------------------------------------------------------------------
// Variants
// --------------------------------------------------------------------------
const variants = sampleSet.variants.map((v) => ({
  id: `v${String(v.n).padStart(2, "0")}`,
  n: v.n,
  objective: v.objective,
  profile: v.profile,
  role: v.role,
  deliveries: v.deliveries ?? [profiles.find((p) => p.id === v.profile)?.default_delivery ?? "hires_native"],
  intensity: sampleSet.intensity ?? 0.5,
  available: AVAILABLE.has(v.n),
  dir: `variants/v${String(v.n).padStart(2, "0")}/`,
}));

project.variants = variants
  .filter((v) => v.available)
  .map((v) => ({
    id: v.id,
    label: `${v.objective} x ${v.profile}`,
    objective: { blend: [{ id: v.objective, weight: 1.0 }], intensity: v.intensity },
    master: { route: "stem_mix", chain: [] },
    outputs: v.deliveries.map((d) => ({ profile: v.profile, delivery: d })),
  }));

write("index.json", {
  schema_version: 1,
  synthetic: true,
  generator: { name: "gui/scripts/make-placeholder-demo.mjs", version: "0", note: "Synthetic placeholder. Replace with the dataset built from the core." },
  title: L("Synthetic placeholder dataset", "合成のプレースホルダーデータ"),
  notice: L("All values are invented for GUI development. No audio is included.", "全ての値は GUI 開発用に作った架空の値です。音声は含みません。"),
  project: "project.json",
  history: "history.json",
  definitions: {
    objectives: "definitions/objectives.json",
    profiles: "definitions/media_profiles.json",
    deliveries: "definitions/delivery_formats.json",
    models: "definitions/models.json",
  },
  intensity: sampleSet.intensity ?? 0.5,
  variants,
  verification_only_profiles: sampleSet.verification_only_profiles ?? [],
});
write("project.json", project);

write("history.json", {
  synthetic: true,
  entries: [
    { seq: 1, ts: "2026-11-13T09:00:00Z", actor: "human", op: "init", reason: "create project", summary: L("Project created", "プロジェクトを作成") },
    { seq: 2, ts: "2026-11-13T09:01:00Z", actor: "human", op: "import", reason: "import stems", summary: L("Imported 6 stems (synthetic)", "ステム 6 本を取り込み（合成）") },
    { seq: 3, ts: "2026-11-13T09:02:00Z", actor: "planner", op: "plan_apply", reason: "cleanup plan", summary: L("Cleanup plan applied", "整音の計画を適用") },
    { seq: 4, ts: "2026-11-13T09:03:00Z", actor: "planner", op: "plan_apply", reason: "mix plan", summary: L("Mix plan applied", "ミックスの計画を適用") },
    { seq: 5, ts: "2026-11-13T09:05:00Z", actor: "agent", op: "patch", reason: "lower synth 1 dB to unmask the vocal", summary: L("Synth level -1 dB", "シンセのレベル -1 dB") },
    { seq: 6, ts: "2026-11-13T09:06:00Z", actor: "human", op: "set", reason: "lead stem confirmed", summary: L("Lead stem = Vocals", "主役 = ボーカル") },
  ],
});

// --------------------------------------------------------------------------
// Per-variant synthetic results
// --------------------------------------------------------------------------
const FREQS = Array.from({ length: 24 }, (_, i) => Math.round(30 * Math.pow(16000 / 30, i / 23)));
const BANDS = [
  ["sub", 20, 60],
  ["bass", 60, 250],
  ["low_mid", 250, 500],
  ["mid", 500, 2000],
  ["high_mid", 2000, 6000],
  ["air", 6000, 20000],
];
const shape = (i) => {
  const t = i * HOP_S;
  if (t < 10) return -6 + t * 0.3;
  if (t < 40) return -2 + Math.sin(t / 3) * 0.8;
  if (t < 60) return 1.5 + Math.sin(t / 2) * 0.5;
  if (t < 80) return -1.5 + Math.sin(t / 4) * 0.6;
  return 1.8 - Math.max(0, t - 92) * 0.8;
};

function ltasBase(f) {
  const oct = Math.log2(f / 1000);
  return -24 - 3.2 * oct + (f < 80 ? -4 * Math.log2(80 / f) : 0) + (f > 12000 ? -8 * Math.log2(f / 12000) : 0);
}

function variantData(v) {
  const prof = profiles.find((p) => p.id === v.profile);
  const target = prof?.loudness?.target_lufs_i ?? -14;
  const ceiling = prof?.true_peak?.ceiling_dbtp ?? -1;
  const beforeI = -11.5;
  const afterI = target;
  const matchTarget = beforeI > afterI ? "before" : "after";
  const matchGain = -Math.abs(beforeI - afterI);
  const tilt = (f) =>
    (v.objective === "bass_heavy" ? (f < 120 ? 3 : f < 250 ? 1.5 : 0) : 0) +
    (v.objective === "club_impact" ? (f < 100 ? 2.5 : f > 6000 ? 0.8 : 0) : 0) +
    (f > 2000 && f < 5000 ? -1.2 : 0) +
    (f > 250 && f < 500 ? -0.8 : 0);
  const n = Math.round(LENGTH_S / HOP_S);
  const beforeL = Array.from({ length: n }, (_, i) => r1(beforeI + shape(i)));
  const afterL = Array.from({ length: n }, (_, i) => r1(afterI + shape(i) * 0.75));

  const analysis = {
    schema_version: 1,
    synthetic: true,
    variant: v.id,
    loudness: {
      hop_s: HOP_S,
      before: beforeL,
      after: afterL,
      integrated_lufs: { before: beforeI, after: afterI },
      true_peak_dbtp: { before: 0.8, after: r1(ceiling - 0.2) },
      lra_lu: { before: 7.2, after: 5.9 },
    },
    ltas: {
      freqs_hz: FREQS,
      before: FREQS.map((f) => r1(ltasBase(f) + (f > 2500 && f < 4500 ? 2.5 : 0) + (f > 250 && f < 450 ? 1.5 : 0))),
      after: FREQS.map((f) => r1(ltasBase(f) + tilt(f) + (f > 2500 && f < 4500 ? 1.2 : 0) + (f > 250 && f < 450 ? 0.6 : 0))),
      reference: {
        label: L("Genre prior band (synthetic)", "ジャンル prior の帯（合成）"),
        low: FREQS.map((f) => r1(ltasBase(f) - 3)),
        high: FREQS.map((f) => r1(ltasBase(f) + 3)),
      },
    },
    band_correlation: {
      bands: BANDS.map(([id, lo, hi], i) => ({ id, lo_hz: lo, hi_hz: hi, before: r2([0.98, 0.93, 0.8, 0.62, 0.48, 0.35][i]), after: r2([0.99, 0.96, 0.82, 0.6, 0.5, 0.4][i]) })),
    },
    stems: TRACKS.map((t) => ({
      track: t.id,
      centroid_hz: t.centroid * (v.objective === "bass_heavy" && t.role === "bass" ? 0.85 : 1),
      depth: r2(Math.min(1, t.depth + (v.objective === "club_impact" && t.role === "drums" ? 0.15 : 0))),
      level_db: t.gain,
      pan: t.pan,
    })),
    masking: [
      { a: "trk_vocals", b: "trk_synth", band_hz: [1000, 4000], amount_db: 3.1, severity: "warning" },
      { a: "trk_bass", b: "trk_drums", band_hz: [60, 120], amount_db: v.objective === "bass_heavy" ? 4.2 : 2.2, severity: v.objective === "bass_heavy" ? "warning" : "info" },
    ],
    diagnostics: [
      { id: "shimmer", metric: "P-16", label: L("High-band shimmer index (10-14 kHz)", "高域シマー指標（10〜14 kHz）"), value: 0.31, unit: "", threshold: 0.4, status: "ok", note: SYN },
      { id: "hf_cutoff", metric: "P-16", label: L("High-frequency cutoff", "高域の頭打ち周波数"), value: 16000, unit: "Hz", threshold: null, status: "warning", note: L("Typical of generated audio (synthetic)", "生成音源に典型的（合成）") },
      { id: "noise_floor", metric: "P-16", label: L("Noise floor in quiet passages", "静音区間のノイズ床"), value: -72.5, unit: "dBFS", threshold: -60, status: "ok" },
      { id: "spectral_flatness", metric: "P-16", label: L("Spectral flatness (air band)", "帯域別スペクトル平坦度（エア帯域）"), value: 0.22, unit: "", threshold: 0.3, status: "ok" },
    ],
    metrics: [
      { id: "P-01", label: L("LTAS band deviation", "LTAS 帯域偏差"), before: 2.8, after: 1.4, unit: "dB" },
      { id: "P-02", label: L("Masking risk (vs lead)", "マスキング・リスク（対主役）"), before: 3.4, after: 1.9, unit: "dB" },
      { id: "P-07", label: L("Sub+bass energy ratio", "サブ+バスのエネルギー比"), before: 0.31, after: v.objective === "bass_heavy" ? 0.38 : 0.32, unit: "" },
      { id: "P-10", label: L("Lead band level difference", "主役帯域レベル差"), before: 1.2, after: 2.6, unit: "dB" },
      { id: "P-11", label: L("Harshness", "ハーシュネス"), before: 2.1, after: 1.0, unit: "dB" },
    ],
  };

  const proc = (id, type, params, reason) => ({ id, type, params, reason });
  const plan = {
    synthetic: true,
    proposals: [
      {
        id: `prop_${v.id}_cleanup`, stage: "cleanup", variant: v.id, author: "planner", status: "applied", created_at: "2026-11-13T09:02:00Z",
        summary: L("Gentle high-band cleanup on vocals (synthetic)", "ボーカルの高域を軽く整音（合成）"),
        steps: [{ target: "trk_vocals", processor: proc("prc_cl_1", "cleanup.hf_denoise", { band_hz: [10000, 14000], amount_db: 3.0 }, "R-20") }],
      },
      {
        id: `prop_${v.id}_mix`, stage: "mix", variant: v.id, author: "planner", status: "applied", created_at: "2026-11-13T09:03:00Z",
        summary: L("Unmask the vocal and tidy the low end (synthetic)", "ボーカルのマスキングを解き、低域を整理（合成）"),
        steps: [
          { target: "trk_synth", processor: proc("prc_mx_1", "eq.bell", { freq_hz: 2200, gain_db: -1.5, q: 1.2 }, "R-03"), alternatives: [L("Lower the synth fader 1 dB", "シンセのフェーダーを 1 dB 下げる")] },
          { target: "trk_bass", processor: proc("prc_mx_2", "eq.bell", { freq_hz: 300, gain_db: -2.0, q: 1.0 }, "R-07 R-28") },
          { target: "trk_vocals", processor: proc("prc_mx_3", "dynamics.compressor", { threshold_db: -18, ratio: 2.5, attack_ms: 10, release_ms: 120 }, "R-11") },
        ],
      },
      {
        id: `prop_${v.id}_master`, stage: "master", variant: v.id, author: "planner", status: "pending", created_at: "2026-11-13T09:04:00Z",
        summary: L(`Master to ${target} LUFS, ceiling ${ceiling} dBTP (synthetic)`, `${target} LUFS、天井 ${ceiling} dBTP へマスタリング（合成）`),
        steps: [
          { target: "master", processor: proc("prc_ms_1", "eq.tilt", { pivot_hz: 1000, tilt_db: v.objective === "bass_heavy" ? 0.8 : 0.3 }, "R-17") },
          { target: "master", processor: proc("prc_ms_2", "limiter.true_peak", { ceiling_dbtp: ceiling, target_lufs_i: target, oversampling: 4 }, "S-01 S-06") },
        ],
      },
      {
        id: `prop_${v.id}_agent`, stage: "mix", variant: v.id, author: "agent", status: "pending", created_at: "2026-11-13T09:07:00Z",
        summary: L("Agent suggestion: de-ess the vocal (synthetic)", "エージェントの提案: ボーカルにディエッサー（合成）"),
        steps: [{ target: "trk_vocals", processor: proc("prc_ag_1", "dynamics.deesser", { freq_hz: 6500, range_db: 3 }, "R-14"), note: L("Proposed through MCP (synthetic)", "MCP 経由の提案（合成）") }],
      },
    ],
  };

  const pass = (id, value, limit, note) => ({ id, status: "pass", value, limit, ...(note ? { note } : {}) });
  const codecs = prof?.codec_checks ?? ["aac"];
  const verify = {
    schema_version: 1,
    synthetic: true,
    variant: v.id,
    overall: "warning",
    constraints: [
      pass("S-01", r1(ceiling - 0.2), ceiling),
      { id: "S-02", status: "not_run", value: null, limit: -0.1, note: L("Opus encoder not available (synthetic)", "Opus 符号化器が使えない（合成）") },
      pass("S-03", 0.62, 0),
      pass("S-04", 0.8, 1.5),
      pass("S-05", "f32", "f32"),
      pass("S-06", "fixed", "fixed"),
      pass("S-07", -86, -80),
      pass("S-08", 0.4, 1.0),
      pass("S-09", "ok", "ok"),
      pass("S-10", "ok", "ok"),
      pass("S-11", "ok", "ok"),
    ],
    gate: {
      status: "pass",
      checks: [
        { id: "band_limited_lead_preserved", label: L("Lead preserved in band-limited preview", "帯域制限で主役が保存"), status: "pass" },
        { id: "mono_fold_loss_within_limit", label: L("Mono fold loss within limit", "モノ合算の損失が閾値内"), status: "pass" },
        { id: "low_level_balance_preserved", label: L("Balance preserved at low level", "小音量で関係が保存"), status: "pass" },
        { id: "pitch_preserved_without_fundamental", label: L("Bass pitch preserved without fundamental", "基音なしで低音の音高が保存"), status: v.objective === "bass_heavy" ? "warning" : "pass" },
      ],
    },
    profiles: [
      { profile: v.profile, delivery: v.deliveries[0], status: "pass", lufs_i: afterI, true_peak_dbtp: r1(ceiling - 0.2) },
      ...(v.n === 1
        ? (sampleSet.verification_only_profiles ?? []).map((p) => {
            const pp = profiles.find((x) => x.id === p);
            const c = pp?.true_peak?.ceiling_dbtp ?? -1;
            return { profile: p, delivery: null, status: r1(ceiling - 0.2) <= c ? "pass" : "fail", lufs_i: afterI, true_peak_dbtp: r1(ceiling - 0.2) };
          })
        : []),
    ],
    noise_return: { status: "pass", delta_db: 0.4, tolerance_db: 1.0, note: SYN },
    codec: codecs.map((c) => (c === "opus" ? { codec: c, status: "not_run", note: L("encoder not available (synthetic)", "符号化器なし（合成）") } : { codec: c, status: "pass", true_peak_dbtp: r1(ceiling + 0.6), ceiling_dbtp: -0.1 })),
  };

  const audio = {
    variant: v.id,
    synthetic: true,
    files: { before: null, after: null, delta: null, before_level_matched: null, fullmix_reference: null },
    match_gain_db: r1(matchGain),
    match_target: matchTarget,
    measurements: { before: { lufs_i: beforeI, true_peak_dbtp: 0.8 }, after: { lufs_i: afterI, true_peak_dbtp: r1(ceiling - 0.2) } },
    note: L("Placeholder dataset: no audio files.", "プレースホルダーのため音声はありません。"),
  };

  const report = (lang) => {
    const tr = (en, ja) => (lang === "ja" ? ja : en);
    return {
      schema_version: 1,
      language: lang,
      synthetic: true,
      summary: {
        project: project.title,
        objective: { blend: [{ id: v.objective, weight: 1 }], intensity: v.intensity },
        profiles: [v.profile],
        outputs: v.deliveries.map((d) => ({ profile: v.profile, delivery: d })),
        result: "warning",
        note: tr("Synthetic placeholder report.", "合成のプレースホルダーのレポートです。"),
      },
      inputs: {
        assets: project.assets.map((a) => ({ id: a.id, role: a.role, sha256: a.sha256.slice(-8) })),
        provenance: project.provenance,
        ingest_checks: project.ingest.checks.map((c) => ({ check: c.check, level: c.level, message: c.message })),
        stem_sum_consistency: { status: "pass", residual_db: -48.2 },
      },
      measurements: {
        level_matched: true,
        before: { lufs_i: beforeI, true_peak_dbtp: 0.8, "P-01_db": 2.8, "P-02_db": 3.4 },
        after: { lufs_i: afterI, true_peak_dbtp: r1(ceiling - 0.2), "P-01_db": 1.4, "P-02_db": 1.9 },
      },
      decisions: {
        balance: [{ measured: tr("Vocal 1.2 dB above accompaniment in 300 Hz-5 kHz", "300 Hz〜5 kHz でボーカルが伴奏より 1.2 dB 上"), rule: "R-03", action: tr("Synth -1.5 dB at 2.2 kHz", "シンセの 2.2 kHz を -1.5 dB"), alternatives: [tr("Raise vocal 1 dB", "ボーカルを 1 dB 上げる")], result: tr("2.6 dB (about 1.2x perceived)", "2.6 dB（知覚でおよそ 1.2 倍）") }],
        panning: [{ measured: tr("Backing vocals and synth overlap at center-left", "コーラスとシンセが中央やや左で重なる"), rule: "R-09", action: tr("No change (assumed speakers at 60 degrees)", "変更なし（スピーカー 60 度を前提）"), result: tr("kept", "維持") }],
        frequency: [{ measured: tr("Low-mid occupancy 31%", "低中域の占有率 31%"), rule: "R-07", action: tr("Bass -2 dB at 300 Hz", "ベースの 300 Hz を -2 dB"), result: tr("26%", "26%") }],
        depth: [{ measured: tr("Depth order matches the declaration", "奥行き順序は宣言と一致"), rule: "R-12", action: tr("No change", "変更なし"), result: tr("kept", "維持") }],
        dynamics: [{ measured: tr("Vocal crest 14 dB", "ボーカルのクレスト 14 dB"), rule: "R-11", action: tr("Compressor 2.5:1, -18 dB", "コンプレッサー 2.5:1、-18 dB"), result: tr("crest 11 dB", "クレスト 11 dB") }],
        interest: [],
      },
      objective_breakdown: [
        { metric: "P-01", weight: 0.25, before: 2.8, after: 1.4 },
        { metric: "P-02", weight: 0.2, before: 3.4, after: 1.9 },
        { metric: "P-11", weight: 0.15, before: 2.1, after: 1.0 },
      ],
      constraints: verify.constraints.map((c) => ({ id: c.id, status: c.status })),
      cleanup: [{ step: "hf_denoise", target: "trk_vocals", action: tr("executed", "実行"), removed_db: 3.0, side_effect: tr("none measured", "測定上なし") }],
      tradeoffs: [
        tr("Codec round-trip for Opus not run: encoder unavailable (synthetic).", "Opus のコーデック往復は未実施: 符号化器なし（合成）。"),
        ...(v.objective === "bass_heavy" ? [tr("More sub energy lowers the whole track after normalization; the mid band becomes relatively quieter.", "サブを上げると正規化で全体が下がり、中域が相対的に下がる。")] : []),
      ],
      listening_checks: [
        { time_s: 42, point: tr("Chorus entry: is the vocal sibilance too strong?", "サビ頭: ボーカルの歯擦音が強すぎないか"), conditions: tr("Fixed volume, level-matched A/B", "音量固定、レベルマッチの A/B") },
        { time_s: 12, point: tr("Does the bass thin out in mono?", "モノで低音が痩せていないか"), conditions: tr("Mono toggle, headphones and phone speaker", "モノ切り替え、ヘッドホンとスマートフォン") },
        { time_s: null, point: tr("Does the removed part (delta) contain breath or consonants?", "除去分に息や子音が含まれていないか"), conditions: tr("Delta playback, rested ears", "除去分の再生、耳を休めてから") },
      ],
      reproducibility: {
        project_hash: fakeSha(99),
        engine_version: "0.0.0-placeholder",
        backends: [{ name: "placeholder", version: "0" }],
        definitions: { objectives: "catalog.json", profiles: "media_profiles.json" },
        models: [],
      },
    };
  };

  return { analysis, plan, verify, audio, reportEn: report("en"), reportJa: report("ja") };
}

for (const v of variants.filter((x) => x.available)) {
  const d = variantData(v);
  write(`${v.dir}analysis.json`, d.analysis);
  write(`${v.dir}plan.json`, d.plan);
  write(`${v.dir}verify.json`, d.verify);
  write(`${v.dir}audio.json`, d.audio);
  write(`${v.dir}report.en.json`, d.reportEn);
  write(`${v.dir}report.ja.json`, d.reportJa);
}

// Definitions are copied verbatim from the canonical data files.
execFileSync(process.execPath, [join(here, "sync-definitions.mjs"), out], { stdio: "inherit" });
console.log(`placeholder demo written: ${variants.filter((v) => v.available).length} variants with data`);
