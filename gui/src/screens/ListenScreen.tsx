import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, SyntheticFlag, fmtNum, fmtTime } from "../components/ui";
import { Icon } from "../components/Icon";
import { sourceGains, type MonitorSettings, type SourceId } from "../audio/gains";
import type { LoadStatus } from "../audio/engine";
import type { AudioSet } from "../types";

export function ListenScreen() {
  const { backend, variantId } = useApp();
  const state = useAsync(() => backend.listAudio(variantId), [backend, variantId]);
  return <Async state={state}>{(set) => <Player set={set} />}</Async>;
}

function Toggle({ on, onChange, children, hint, testId }: { on: boolean; onChange: (v: boolean) => void; children: React.ReactNode; hint?: string; testId?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} className={"toggle" + (on ? " on" : "")} onClick={() => onChange(!on)} title={hint} data-testid={testId}>
      <span className="toggle-knob" aria-hidden="true" />
      {children}
    </button>
  );
}

export function Player({ set }: { set: AudioSet }) {
  const { t, label, engineFactory } = useApp();
  const engine = useMemo(() => engineFactory(), [engineFactory]);
  const [active, setActive] = useState<SourceId>("before");
  // SPEC 1.3 / 15.2: level-matched A/B is the default.
  const [levelMatch, setLevelMatch] = useState(true);
  const [monitor, setMonitor] = useState<MonitorSettings>({ mono: false, bandLimit: false, lowLevel: false });
  const [status, setStatus] = useState<Record<SourceId, LoadStatus> | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [dur, setDur] = useState(0);
  const raf = useRef<number | undefined>(undefined);

  const urls = useMemo(() => ({ before: set.files.before, after: set.files.after, delta: set.files.delta ?? null }), [set]);
  const hasAnyUrl = !!(urls.before || urls.after || urls.delta);

  useEffect(() => () => engine.dispose(), [engine]);

  useEffect(() => {
    let alive = true;
    setStatus(null);
    setPlaying(false);
    setPos(0);
    if (!hasAnyUrl || !engine.supported) return;
    setLoading(true);
    engine.load(urls).then((s) => {
      if (!alive) return;
      setStatus(s);
      setDur(engine.duration());
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [engine, urls, hasAnyUrl]);

  // Gains always follow state; the match gain value comes from the data.
  useEffect(() => {
    engine.setSourceGains(sourceGains({ active, levelMatch, matchGainDb: set.match_gain_db, matchTarget: set.match_target }));
  }, [engine, active, levelMatch, set.match_gain_db, set.match_target]);

  useEffect(() => {
    engine.setMonitor(monitor);
  }, [engine, monitor]);

  useEffect(() => {
    if (!playing) return;
    const tick = () => {
      setPos(engine.currentTime());
      if (!engine.isPlaying()) {
        setPlaying(false);
        return;
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current !== undefined) cancelAnimationFrame(raf.current);
    };
  }, [engine, playing]);

  const playable = engine.supported && !!status && Object.values(status).some((s) => s === "ok");
  const togglePlay = async () => {
    if (playing) {
      engine.pause();
      setPlaying(false);
      setPos(engine.currentTime());
    } else {
      await engine.play();
      setPlaying(engine.isPlaying());
    }
  };

  const sourceLabel = (s: SourceId) => (s === "before" ? t("listen.before") : s === "after" ? t("listen.after") : t("listen.delta"));
  const sources: SourceId[] = urls.delta ? ["before", "after", "delta"] : ["before", "after"];
  const m = set.measurements;

  return (
    <div className="listen">
      <Card title={t("nav.listen")}>
        <SyntheticFlag synthetic={(set as { synthetic?: boolean }).synthetic} />
        <p className="muted small">{t("listen.hint")}</p>
        {!hasAnyUrl && (
          <p className="notice" role="status" data-testid="no-audio">
            {t("listen.noAudio")}
          </p>
        )}
        {hasAnyUrl && !engine.supported && <p className="notice">{t("listen.unsupported")}</p>}
        {loading && <p className="muted">{t("listen.loadingAudio")}</p>}
        {status &&
          (Object.entries(status) as [SourceId, LoadStatus][])
            .filter(([, s]) => s === "missing" || s === "error")
            .map(([id]) => (
              <p key={id} className="notice small" role="status">
                {t("listen.missing")}: {sourceLabel(id)}
              </p>
            ))}
        {set.note && <p className="muted small">{label(set.note)}</p>}
        <dl className="kv">
          <dt>{t("listen.matchGain")}</dt>
          <dd data-testid="match-readout">
            {levelMatch
              ? `${fmtNum(set.match_gain_db, 1, "dB")} ${t("listen.appliedTo")} ${sourceLabel(set.match_target)}`
              : t("listen.levelMatchOff")}
          </dd>
          {m && (
            <>
              <dt>{t("listen.measurements")}</dt>
              <dd>
                {t("listen.before")}: {fmtNum(m.before?.lufs_i, 1, "LUFS")} / {fmtNum(m.before?.true_peak_dbtp, 1, "dBTP")}
                <br />
                {t("listen.after")}: {fmtNum(m.after?.lufs_i, 1, "LUFS")} / {fmtNum(m.after?.true_peak_dbtp, 1, "dBTP")}
              </dd>
            </>
          )}
        </dl>
      </Card>

      <div className="transport" role="group" aria-label={t("listen.ab")}>
        <div className="transport-row">
          <button
            type="button"
            className="btn secondary to-start"
            onClick={() => {
              engine.seek(0);
              setPos(0);
            }}
            disabled={!playable}
            aria-label={t("listen.toStart")}
            title={t("listen.toStart")}
            data-testid="to-start"
          >
            <Icon name="first" />
          </button>
          <button type="button" className="btn play" onClick={togglePlay} disabled={!playable} aria-label={playing ? t("listen.pause") : t("listen.play")}>
            <Icon name={playing ? "pause" : "play"} scale={2} />
          </button>
          <div className="ab" role="radiogroup" aria-label={t("listen.ab")}>
            {sources.map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={active === s}
                className={"ab-btn" + (active === s ? " active" : "")}
                onClick={() => setActive(s)}
                data-testid={`ab-${s}`}
              >
                {sourceLabel(s)}
              </button>
            ))}
          </div>
        </div>
        <label className="position">
          <span className="sr-only">{t("listen.position")}</span>
          <Icon name="waveform" />
          <span className="num small">{fmtTime(pos)}</span>
          <input
            type="range"
            min={0}
            max={dur || 0}
            step={0.1}
            value={Math.min(pos, dur || 0)}
            disabled={!playable}
            onChange={(e) => {
              engine.seek(+e.target.value);
              setPos(+e.target.value);
            }}
            aria-label={t("listen.position")}
          />
          <span className="num small">{fmtTime(dur)}</span>
        </label>
        <div className="transport-row toggles">
          <Toggle on={levelMatch} onChange={setLevelMatch} testId="level-match">
            {levelMatch ? t("listen.levelMatchOn") : t("listen.levelMatch")}
          </Toggle>
          <Toggle on={monitor.mono} onChange={(v) => setMonitor({ ...monitor, mono: v })} testId="mono">
            {t("listen.mono")}
          </Toggle>
          <Toggle on={monitor.bandLimit} onChange={(v) => setMonitor({ ...monitor, bandLimit: v })} hint={t("listen.bandLimitHint")} testId="band-limit">
            {t("listen.bandLimit")}
          </Toggle>
          <Toggle on={monitor.lowLevel} onChange={(v) => setMonitor({ ...monitor, lowLevel: v })} hint={t("listen.lowLevelHint")} testId="low-level">
            {t("listen.lowLevel")}
          </Toggle>
        </div>
        {(monitor.bandLimit || monitor.lowLevel) && (
          <p className="muted small transport-note">
            {monitor.bandLimit && t("listen.bandLimitHint")}
            {monitor.bandLimit && monitor.lowLevel && " · "}
            {monitor.lowLevel && t("listen.lowLevelHint")}
          </p>
        )}
      </div>
    </div>
  );
}
