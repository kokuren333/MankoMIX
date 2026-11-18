import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { useApp } from "../AppContext";
import { LineChart } from "../components/charts";
import type { MeterObservation, NoteObservation, SpectralParams, SpectralPreview } from "../backend/observations";
import "./observations.css";

function useWords() {
  const { lang } = useApp();
  return (ja: string, en: string) => lang === "ja" ? ja : en;
}

function Json({ value }: { value: unknown }) {
  return <details><summary>JSON</summary><pre className="oq-json">{JSON.stringify(value, null, 2)}</pre></details>;
}

function useSource() {
  const { backend, revision } = useApp();
  const [target, setTarget] = useState("");
  const [section, setSection] = useState("");
  const [tracks, setTracks] = useState<string[]>([]);
  const [sourceError, setSourceError] = useState("");
  useEffect(() => {
    let alive = true;
    backend.getProject().then(p => {
      if (!alive) return;
      const ids = (p.tracks ?? []).map(t => t.id);
      setTracks(ids);
      setTarget(old => old || ids[0] || "master");
      setSourceError("");
    }).catch(e => alive && setSourceError(String(e)));
    return () => { alive = false; };
  }, [backend, revision]);
  return { target, setTarget, section, setSection, tracks, sourceError, revision };
}

function Source({ source, trackOnly = false }: { source: ReturnType<typeof useSource>; trackOnly?: boolean }) {
  const w = useWords();
  return <div className="oq-controls">
    <label>{w("対象 ID", "Target ID")}<input aria-label="target" list="oq-targets" value={source.target} onChange={e => source.setTarget(e.target.value)} /></label>
    <datalist id="oq-targets">{[...source.tracks, ...(trackOnly ? [] : ["mix", "master"])].map(id => <option key={id} value={id} />)}</datalist>
    <label>{w("区間（空欄＝全体）", "Section (empty = full)")}<input aria-label="section" value={source.section} onChange={e => source.setSection(e.target.value)} /></label>
    {source.sourceError && <p role="alert">{source.sourceError}</p>}
  </div>;
}

function useObservation<T>(key: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    generation.current++;
    setData(undefined); setError(""); setPending(false);
    return () => { generation.current++; };
  }, [key]);
  async function run(fn: () => Promise<T>) {
    const id = ++generation.current;
    setPending(true); setError(""); setData(undefined);
    try { const result = await fn(); if (id === generation.current) setData(result); }
    catch (e) { if (id === generation.current) setError(String(e)); }
    finally { if (id === generation.current) setPending(false); }
  }
  return { data, error, pending, run };
}

function Frame({ available, pending, error, children }: { available: boolean; pending: boolean; error: string; children: ReactNode }) {
  const w = useWords();
  return <section className="oq-observation">
    <p>{w("CLI と同じ観察値を表示します。合否・音質の判定は行いません。", "Shows CLI observations without pass/fail or quality judgments.")}</p>
    {!available && <p role="note">{w("ローカルサーバーで利用できます。デモにはこの観察データがありません。", "Available on the local server. The demo has no observation data.")}</p>}
    {pending && <p role="status">{w("読み込み中…", "Loading…")}</p>}
    {error && <p role="alert">{error}</p>}
    {children}
  </section>;
}

export function NotesScreen() {
  const { backend, caps } = useApp();
  const w = useWords(), source = useSource();
  const available = caps.mode === "local" && !!backend.getPitchNotes;
  const [lo, setLo] = useState(70), [hi, setHi] = useState(1000), [a4, setA4] = useState(440);
  const key = JSON.stringify([source.target, source.section, source.revision, lo, hi, a4]);
  const obs = useObservation<NoteObservation>(key);
  const [before, setBefore] = useState<NoteObservation>();
  useEffect(() => { setBefore(undefined); }, [source.target, source.section, lo, hi, a4]);
  const rows = obs.data?.notes ?? [];
  const all = [...rows, ...(before?.notes ?? [])];
  const duration = Math.max(1, ...all.map(n => n.t1));
  const low = Math.min(48, ...all.map(n => n.pitch_midi)) - 1;
  const high = Math.max(84, ...all.map(n => n.pitch_midi)) + 1;
  const y = (pitch: number) => 190 - (pitch - low) / (high - low) * 170;
  return <Frame available={available} pending={obs.pending} error={obs.error}>
    <Source source={source} trackOnly />
    <div className="oq-controls">{[["lo_hz", lo, setLo], ["hi_hz", hi, setHi], ["a4", a4, setA4]].map(([name, value, setter]) =>
      <label key={String(name)}>{String(name)}<input type="number" aria-label={String(name)} value={value as number} onChange={e => (setter as (v: number) => void)(Number(e.target.value))} /></label>)}
      <button disabled={!available || obs.pending || !source.target} onClick={() => obs.run(() => backend.getPitchNotes!({ target: source.target, section: source.section || undefined, lo_hz: lo, hi_hz: hi, a4 }))}>{w("音符を取得", "Load notes")}</button>
      <button disabled={!obs.data} onClick={() => setBefore(obs.data)}>{w("比較用に保持", "Keep for comparison")}</button>
    </div>
    <p>{w("CLI で edit_pitch を適用後、再取得すると保持した音符と比較できます。線は CLI の pitch_midi（音符の中央値）です。", "After applying edit_pitch via CLI, reload to compare with the kept notes. Lines show CLI pitch_midi (note medians).")}</p>
    {(obs.data || before) && <>
      <figure className="chart"><figcaption>{w("音符帯と音程（MIDI）・時間（秒）。保持＝破線、現在＝実線", "Note bands and pitch (MIDI), time (s). Kept = dashed, current = solid")}</figcaption>
        <svg viewBox="0 0 640 230" role="img" aria-label="Note bands">
          {[before, obs.data].map((data, group) => <g key={group} className={group ? "oq-current" : "oq-before"}>
            {data?.notes.map(n => <g key={n.id}><rect x={40 + n.t0 / duration * 580} y={y(n.pitch_midi) - 4} width={(n.t1 - n.t0) / duration * 580} height={8} />
              <line x1={40 + n.t0 / duration * 580} x2={40 + n.t1 / duration * 580} y1={y(n.pitch_midi)} y2={y(n.pitch_midi)} /><title>{`${n.id}: ${n.t0}–${n.t1} s, ${n.pitch_midi} MIDI`}</title></g>)}
          </g>)}
          <text x={40} y={220}>0 s</text><text x={570} y={220}>{duration} s</text>
          <text x={0} y={25}>{high}</text><text x={0} y={190}>{low}</text>
        </svg>
      </figure>
      {[before, obs.data].map((data, i) => data && <div key={i} className="table-scroll"><h2>{i ? w("現在", "Current") : w("保持した比較値", "Kept comparison")}</h2>
        <table><thead><tr>{["id", "t0 (s)", "t1 (s)", "pitch_midi", "cents_off", "drift_cents", "vibrato.hz", "vibrato.width_cents", "confidence", "level_db"].map(k => <th key={k}>{k}</th>)}</tr></thead>
          <tbody>{data.notes.map(n => <tr key={n.id}>{[n.id, n.t0, n.t1, n.pitch_midi, n.cents_off, n.drift_cents, n.vibrato.hz, n.vibrato.width_cents, n.confidence, n.level_db].map((v, j) => <td key={j}>{v}</td>)}</tr>)}</tbody></table>
        {data.caveats.map(c => <p key={c}>{c}</p>)}<Json value={data} />
      </div>)}
    </>}
  </Frame>;
}

type Rectangle = [number, number, number, number];

/** Geometry snaps to CLI time-bin and frequency-band boundaries. */
export function Spectrogram({ data, onSelect, selection }: { data: MeterObservation; onSelect?: (r: Rectangle) => void; selection?: Rectangle }) {
  const sp = data.spectrogram;
  const [anchor, setAnchor] = useState<[number, number]>();
  if (!sp || !data.times_s.length) return null;
  const count = data.times_s.length, bands = sp.edges_hz.length - 1;
  const cell = (e: PointerEvent<SVGSVGElement>): [number, number] => {
    const box = e.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(count - 1, Math.floor((e.clientX - box.left) / (box.width || 1) * count))),
      Math.max(0, Math.min(bands - 1, Math.floor((1 - (e.clientY - box.top) / (box.height || 1)) * bands)))];
  };
  const t0 = data.range_s[0], t1 = data.range_s[1];
  const sx = (t: number) => (t - t0) / (t1 - t0) * 640;
  const sy = (hz: number) => 240 * (1 - Math.log(Math.max(hz, sp.edges_hz[0]) / sp.edges_hz[0]) / Math.log(sp.edges_hz[bands] / sp.edges_hz[0]));
  return <figure className="chart"><figcaption>{`${t0}–${t1} s × ${sp.edges_hz[0]}–${sp.edges_hz[bands]} Hz (log), dBFS`}</figcaption>
    <svg className={onSelect ? "oq-selectable" : ""} viewBox="0 0 640 240" role="img" aria-label="Spectrogram"
      onPointerDown={e => { if (onSelect) { setAnchor(cell(e)); e.currentTarget.setPointerCapture?.(e.pointerId); } }}
      onPointerCancel={() => setAnchor(undefined)}
      onPointerUp={e => {
        if (!onSelect || !anchor) return;
        const end = cell(e), a = Math.min(anchor[0], end[0]), b = Math.max(anchor[0], end[0]);
        const lo = Math.min(anchor[1], end[1]), hi = Math.max(anchor[1], end[1]);
        onSelect([data.times_s[a], data.end_times_s[b], sp.edges_hz[lo], sp.edges_hz[hi + 1]]);
        setAnchor(undefined);
      }}>
      {sp.levels_dbfs.map((row, i) => row.map((v, j) => <rect key={`${i}-${j}`} className="oq-bin"
        x={sx(data.times_s[i])} y={(bands - j - 1) / bands * 240} width={sx(data.end_times_s[i]) - sx(data.times_s[i])} height={240 / bands + .1}
        opacity={Math.max(.05, Math.min(1, (v + 100) / 100))}><title>{`${data.times_s[i]}–${data.end_times_s[i]} s, ${sp.edges_hz[j]}–${sp.edges_hz[j + 1]} Hz: ${v} dBFS`}</title></rect>))}
      {selection && <rect className="oq-selection" x={sx(selection[0])} y={sy(selection[3])} width={sx(selection[1]) - sx(selection[0])} height={sy(selection[2]) - sy(selection[3])} />}
    </svg>
  </figure>;
}

export function SpectralScreen() {
  const { backend, caps } = useApp();
  const w = useWords(), source = useSource();
  const available = caps.mode === "local" && !!backend.getMeters && !!backend.previewSpectralRepair;
  const key = JSON.stringify([source.target, source.section, source.revision]);
  const obs = useObservation<MeterObservation>(key);
  const [rectangle, setRectangle] = useState<Rectangle>([0, .2, 200, 2000]);
  const [append, setAppend] = useState(false);
  const [params, setParams] = useState(JSON.stringify({ t0_s: [], t1_s: [], lo_hz: [], hi_hz: [], mode: "replace_time", attenuate_db: 12, context_ms: 200, feather_ms: 10, feather_oct: .05, window: 2048, delta: false }, null, 2));
  const preview = useObservation<SpectralPreview>(JSON.stringify([key, params]));
  const [editError, setEditError] = useState("");
  function select(r: Rectangle) {
    setRectangle(r);
    try {
      const p = JSON.parse(params) as SpectralParams;
      (["t0_s", "t1_s", "lo_hz", "hi_hz"] as const).forEach((k, i) => { p[k] = append ? [...p[k], r[i]] : [r[i]]; });
      setParams(JSON.stringify(p, null, 2)); setEditError("");
    } catch (e) { setEditError(String(e)); }
  }
  return <Frame available={available} pending={obs.pending || preview.pending} error={obs.error || preview.error || editError}>
    <Source source={source} />
    <button disabled={!available || obs.pending || !source.target} onClick={() => obs.run(() => backend.getMeters!({ target: source.target, section: source.section || undefined, what: "spectrogram", max_points: 200 }))}>{w("スペクトログラムを取得", "Load spectrogram")}</button>
    <p>{w("図をドラッグして矩形を選択します。時刻と周波数は API のビン境界を使います（1 領域 2 秒以内、最大 64 個）。", "Drag a rectangle using API bin boundaries (at most 2 s per region, 64 regions).")}</p>
    {obs.data && <Spectrogram data={obs.data} onSelect={select} selection={rectangle} />}
    <div className="oq-controls">{["t0_s", "t1_s", "lo_hz", "hi_hz"].map((name, i) => <label key={name}>{name} ({i < 2 ? "s" : "Hz"})<input type="number" step="any" aria-label={name} value={rectangle[i]} onChange={e => setRectangle(old => old.map((v, j) => i === j ? Number(e.target.value) : v) as Rectangle)} /></label>)}</div>
    <label><input type="checkbox" checked={append} onChange={e => setAppend(e.target.checked)} />{w("既存の配列に追加", "Append to arrays")}</label>
    <button onClick={() => select(rectangle)}>{w("数値を配列へ反映", "Use numeric rectangle")}</button>
    <label className="oq-params">spectral_repair params<textarea aria-label="spectral_repair params" rows={16} value={params} onChange={e => setParams(e.target.value)} /></label>
    <button disabled={!available || preview.pending || !source.target} onClick={() => preview.run(() => backend.previewSpectralRepair!({ target: source.target, section: source.section || undefined, max_points: 200, params: JSON.parse(params) }))}>{w("検証・下見", "Validate / preview")}</button>
    <p>{w("読み取り専用です。適用はこの params を spectral_repair プロセッサとして CLI の指揮書 op に指定してください。", "Read-only. Apply these params as a spectral_repair processor through a CLI direction op.")}</p>
    {preview.data && <><p role="status">{w("検証済み（未適用）", "Validated (not applied)")}</p><Json value={preview.data} /></>}
  </Frame>;
}

export function MetersScreen() {
  const { backend, caps } = useApp();
  const w = useWords(), source = useSource();
  const available = caps.mode === "local" && !!backend.getMeters;
  const [step, setStep] = useState(100), [max, setMax] = useState(200);
  const obs = useObservation<MeterObservation>(JSON.stringify([source.target, source.section, source.revision, step, max]));
  const [index, setIndex] = useState(0);
  const d = obs.data, i = Math.min(index, Math.max(0, (d?.times_s.length ?? 1) - 1));
  const vector = d?.vectorscope?.windows[i];
  return <Frame available={available} pending={obs.pending} error={obs.error}>
    <Source source={source} />
    <div className="oq-controls"><label>step_ms<input type="number" min={10} max={1000} value={step} onChange={e => setStep(Number(e.target.value))} /></label>
      <label>max_points<input type="number" min={1} max={100000} value={max} onChange={e => setMax(Number(e.target.value))} /></label>
      <button disabled={!available || obs.pending || !source.target} onClick={() => obs.run(() => backend.getMeters!({ target: source.target, section: source.section || undefined, step_ms: step, max_points: max, points: 1000 }))}>{w("メータを取得", "Load meters")}</button></div>
    {d && <>
      <dl className="oq-summary">{Object.entries(d.summary).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v ?? "—"}</dd></div>)}</dl>
      <label>{w("観察位置", "Observation position")}<input aria-label="Observation position" type="range" min={0} max={Math.max(0, d.times_s.length - 1)} value={i} onChange={e => setIndex(Number(e.target.value))} />{d.times_s[i]}–{d.end_times_s[i]} s</label>
      <p>effective_step_ms: {d.effective_step_ms}</p>
      {d.peak && <LineChart title={w("ピーク", "Peak")} xs={d.times_s} series={[{ id: "sample", name: "sample_peak_dbfs", values: d.peak.sample_peak_dbfs, cls: "s1" }, { id: "true", name: "true_peak_dbtp", values: d.peak.true_peak_dbtp, cls: "s2" }]} />}
      {d.peak && <p>sample_peak_dbfs: {d.peak.sample_peak_dbfs[i]} / true_peak_dbtp: {d.peak.true_peak_dbtp[i]}</p>}
      {d.loudness && <LineChart title={w("ラウドネス履歴", "Loudness history")} xs={d.times_s} yUnit="LUFS" series={[{ id: "mom", name: "momentary.mean_lufs", values: d.loudness.momentary.mean_lufs, cls: "s1" }, { id: "short", name: "short_term.mean_lufs", values: d.loudness.short_term.mean_lufs, cls: "s2" }]} />}
      {d.spectrum && <LineChart title={w("スペクトラム", "Spectrum")} xs={d.spectrum.bands_hz.map(b => b[0])} logX yUnit="dBFS" series={[{ id: "now", name: `${d.times_s[i]} s`, values: d.spectrum.levels_dbfs[i] ?? [], cls: "s1" }, { id: "max", name: "max_hold_dbfs", values: d.spectrum.max_hold_dbfs, cls: "s2" }]} />}
      <Spectrogram data={d} />
      <p>correlation.full: {d.correlation?.full ?? "—"}</p>
      {vector && <p>tilt_degrees: {vector.tilt_degrees ?? "—"} / spread: {vector.spread ?? "—"} / mid_dbfs: {vector.mid_dbfs} / side_dbfs: {vector.side_dbfs}</p>}
      {d.vectorscope?.points_lr && <figure className="chart"><figcaption>{w("ベクトルスコープ（全区間の L/R 標本）", "Vectorscope (L/R samples over the full section)")}</figcaption>
        <svg viewBox="0 0 300 300" role="img" aria-label="Vectorscope"><path className="oq-axis" d="M150 0V300M0 150H300" />
          {d.vectorscope.points_lr.map(([left, right], n) => <circle className="oq-bin" key={n} cx={150 + (left - right) * 75} cy={150 - (left + right) * 75} r={1.5}><title>{`L: ${left}, R: ${right}`}</title></circle>)}</svg>
      </figure>}
      <Json value={d} />
    </>}
  </Frame>;
}
