import { useEffect, useState } from "react";
import { useApp } from "../AppContext";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, fmtNum } from "../components/ui";
import { Icon } from "../components/Icon";
import { ROLES, type PatchOp, type Project, type Track } from "../types";

export function StemsScreen() {
  const { backend, revision } = useApp();
  const state = useAsync(() => backend.getProject(), [backend, revision]);
  return <Async state={state}>{(p) => <StemsView project={p} />}</Async>;
}

function panLabel(p: number): string {
  if (Math.abs(p) < 0.005) return "C";
  return `${p < 0 ? "L" : "R"}${Math.round(Math.abs(p) * 100)}`;
}

function StemsView({ project }: { project: Project }) {
  const { t, caps, backend, bump, layout } = useApp();
  const editable = caps.editProject;
  const [tracks, setTracks] = useState<Track[]>(project.tracks);
  const [error, setError] = useState<string>();
  useEffect(() => setTracks(project.tracks), [project]);

  const send = async (ops: PatchOp[], reason: string) => {
    setError(undefined);
    try {
      await backend.patchProject(ops, reason);
      bump();
    } catch (e) {
      setError((e as Error).message);
      setTracks(project.tracks);
    }
  };

  const local = (i: number, patch: Partial<Track>) => setTracks((ts) => ts.map((tr, j) => (j === i ? { ...tr, ...patch } : tr)));

  const commit = (i: number, field: string, value: unknown) =>
    send([{ op: "add", path: `/tracks/${i}/${field}`, value }], `gui: ${tracks[i].id} ${field}`);

  const setLead = (i: number) => {
    const ops: PatchOp[] = tracks.map((_, j) => ({ op: "add", path: `/tracks/${j}/is_lead`, value: j === i }));
    ops.push({ op: "add", path: "/objective/lead_stem", value: tracks[i].id });
    setTracks((ts) => ts.map((tr, j) => ({ ...tr, is_lead: j === i })));
    void send(ops, `gui: lead = ${tracks[i].id}`);
  };

  const controls = (tr: Track, i: number) => {
    const gain = tr.gain_db ?? 0;
    const pan = tr.pan?.position ?? 0;
    return {
      role: (
        <select
          aria-label={`${t("stems.role")} ${tr.id}`}
          value={tr.role}
          disabled={!editable}
          onChange={(e) => {
            local(i, { role: e.target.value as Track["role"] });
            void commit(i, "role", e.target.value);
          }}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      ),
      lead: (
        <input
          type="radio"
          name="lead"
          aria-label={`${t("stems.lead")} ${tr.id}`}
          checked={!!tr.is_lead}
          disabled={!editable}
          onChange={() => setLead(i)}
        />
      ),
      level: (
        <span className="slider-row">
          <input
            type="range"
            min={-24}
            max={12}
            step={0.5}
            value={gain}
            disabled={!editable}
            aria-label={`${t("stems.level")} ${tr.id}`}
            onChange={(e) => local(i, { gain_db: +e.target.value })}
            onPointerUp={() => void commit(i, "gain_db", tracks[i].gain_db ?? 0)}
            onKeyUp={() => void commit(i, "gain_db", tracks[i].gain_db ?? 0)}
          />
          <output className="num">{fmtNum(gain, 1)}</output>
        </span>
      ),
      pan: (
        <span className="slider-row">
          <input
            type="range"
            min={-1}
            max={1}
            step={0.01}
            value={pan}
            disabled={!editable}
            aria-label={`${t("stems.pan")} ${tr.id}`}
            onChange={(e) => local(i, { pan: { ...tr.pan, position: +e.target.value } })}
            onPointerUp={() => void commit(i, "pan", { ...tracks[i].pan, position: tracks[i].pan?.position ?? 0 })}
            onKeyUp={() => void commit(i, "pan", { ...tracks[i].pan, position: tracks[i].pan?.position ?? 0 })}
          />
          <output className="num">{panLabel(pan)}</output>
        </span>
      ),
      mute: (
        <input
          type="checkbox"
          aria-label={`${t("stems.mute")} ${tr.id}`}
          checked={!!tr.muted}
          disabled={!editable}
          onChange={(e) => {
            local(i, { muted: e.target.checked });
            void commit(i, "muted", e.target.checked);
          }}
        />
      ),
      solo: (
        <input
          type="checkbox"
          aria-label={`${t("stems.solo")} ${tr.id}`}
          checked={!!tr.solo}
          disabled={!editable}
          onChange={(e) => {
            local(i, { solo: e.target.checked });
            void commit(i, "solo", e.target.checked);
          }}
        />
      ),
    };
  };

  const name = (tr: Track) => tr.name ?? tr.id;
  // Origin shown by shape: delivered stem vs. stem separated from a mix (labelled for screen readers).
  const originOf = (tr: Track) => project.assets.find((a) => a.id === tr.clips?.[0]?.asset)?.origin;
  const origin = (tr: Track) =>
    originOf(tr) === "separated" ? (
      <Icon name="separate" label={t("stems.origin.separated")} />
    ) : originOf(tr) === "native_stem" ? (
      <Icon name="stem" label={t("stems.origin.native_stem")} />
    ) : null;
  const chainText = (tr: Track) => (tr.chain ?? []).map((p) => `${p.type} (${p.reason})`).join(" → ") || "—";

  return (
    <Card title={`${t("nav.stems")} (${tracks.length})`}>
      {!editable && <p className="muted small">{t("stems.readOnly")}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {layout === "narrow" ? (
        <div className="stem-cards" data-testid="stem-cards">
          {tracks.map((tr, i) => {
            const c = controls(tr, i);
            return (
              <article key={tr.id} className={"stem-card" + (tr.is_lead ? " is-lead" : "")}>
                <header>
                  <strong className="with-icon">
                    {origin(tr)}
                    {name(tr)}
                  </strong>
                  <label className="inline">
                    {c.lead} {t("stems.lead")}
                  </label>
                </header>
                <label>
                  {t("stems.role")} {c.role}
                </label>
                <label>
                  {t("stems.level")} {c.level}
                </label>
                <label>
                  {t("stems.pan")} {c.pan}
                </label>
                <div className="row">
                  <label className="inline">
                    {c.mute} {t("stems.mute")}
                  </label>
                  <label className="inline">
                    {c.solo} {t("stems.solo")}
                  </label>
                  <span className="muted small">
                    {t("stems.importance")}: {fmtNum(tr.importance?.value, 2)}
                  </span>
                </div>
                <p className="muted small">
                  {t("stems.chain")}: {chainText(tr)}
                </p>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="table-scroll">
          <table className="stems-table" data-testid="stem-table">
            <thead>
              <tr>
                <th>{t("stems.track")}</th>
                <th>{t("stems.role")}</th>
                <th>{t("stems.lead")}</th>
                <th>{t("stems.level")}</th>
                <th>{t("stems.pan")}</th>
                <th>{t("stems.mute")}</th>
                <th>{t("stems.solo")}</th>
                <th>{t("stems.importance")}</th>
                <th>{t("stems.chain")}</th>
              </tr>
            </thead>
            <tbody>
              {tracks.map((tr, i) => {
                const c = controls(tr, i);
                return (
                  <tr key={tr.id} className={tr.is_lead ? "is-lead" : undefined}>
                    <td>
                      <strong className="with-icon">
                        {origin(tr)}
                        {name(tr)}
                      </strong>
                      <div className="muted small">{(tr.clips ?? []).length} {t("stems.clips")}</div>
                    </td>
                    <td>{c.role}</td>
                    <td>{c.lead}</td>
                    <td>{c.level}</td>
                    <td>{c.pan}</td>
                    <td>{c.mute}</td>
                    <td>{c.solo}</td>
                    <td className="num">{fmtNum(tr.importance?.value, 2)}</td>
                    <td className="small">{chainText(tr)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
