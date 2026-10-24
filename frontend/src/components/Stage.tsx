import { useState } from "react";
import type { FrameBuffer } from "../useMatchStream";
import type { Frame, MatchState, Meta, Overlay, Profile } from "../types";
import { Pitch, toPct } from "./Pitch";

interface Props {
  meta: Meta;
  state: MatchState | null;
  frame: Frame | null;
  frames: React.MutableRefObject<FrameBuffer>;
  overlays: Overlay[];
  profile: Profile;
}

/** Overlays stay on screen for `ttl` seconds of wall time after they arrive, so they stay readable at 10x. */
function isActive(o: Overlay, now: number) {
  return o.receivedAt !== undefined && now - o.receivedAt < o.ttl * 1000;
}

export function Stage({ meta, state, frame, frames, overlays, profile }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const now = performance.now();
  const active = overlays.filter((o) => o.ttl > 0 && isActive(o, now) && !dismissed.has(o.id));
  const pick = (type: Overlay["type"], n: number) =>
    active
      .filter((o) => o.type === type)
      .sort((a, b) => b.priority - a.priority || b.t - a.t)
      .slice(0, n);

  const lower = pick("key_moment", 1)[0];
  const small = lower ? [] : [...pick("pass_card", 1), ...pick("shot_card", 1)].sort((a, b) => b.t - a.t).slice(0, 2);
  const alert = pick("index_alert", 1)[0];
  const tags = pick("player_tag", 4);
  const panel = pick("stat_panel", 1)[0];
  const recap = pick("recap", 1)[0];
  const { home, away } = meta.match;
  const positions = new Map(frame?.players.map((p) => [p[0], p]) ?? []);
  const dismiss = (id: string) => setDismissed((d) => new Set(d).add(id));

  return (
    <div className="stage">
      <Pitch frames={frames} home={home} away={away} focusPlayer={profile.player} favClub={profile.club} />

      {state && (
        <div className="scorebug" role="status">
          <span className="sb-team" style={{ background: home.primary, color: home.secondary }}>{home.short}</span>
          <span className="sb-score">
            {state.score.home}–{state.score.away}
          </span>
          <span className="sb-team" style={{ background: away.primary, color: away.secondary }}>{away.short}</span>
          <span className="sb-clock">{state.finished ? "FT" : state.minute}</span>
        </div>
      )}

      {tags.map((o) => {
        const pid = o.anchor.player_id;
        const p = pid ? positions.get(pid) : undefined;
        if (!p) return null;
        const pos = toPct(p[1], p[2]);
        return (
          <div key={o.id} className={`tag tag-${o.kind}`} style={{ left: `${pos.left}%`, top: `${pos.top}%` }}>
            <strong>{o.text.headline}</strong>
            <span>{o.text.body}</span>
          </div>
        );
      })}

      {alert && (
        <div className="alert" key={alert.id}>
          <div className="alert-kicker">{alert.minute}</div>
          <div className="alert-head">{alert.text.headline}</div>
          {alert.text.body && <div className="alert-body">{alert.text.body}</div>}
          <AiBadge o={alert} />
        </div>
      )}

      {panel && profile.mode === "analyst" && panel.rows && (
        <div className="panel" key={panel.id}>
          <div className="panel-head">{panel.text.headline}</div>
          <StatRows rows={panel.rows} home={home.short} away={away.short} />
        </div>
      )}

      {lower && (
        <div className={`lower lower-${lower.kind}`} key={lower.id}>
          <div className="lower-bar" style={{ background: lower.side ? meta.match[lower.side].primary : "#ffb547" }} />
          <div className="lower-main">
            <div className="lower-head">
              {lower.text.headline}
              {lower.text.sub && <span className="lower-sub">{lower.text.sub}</span>}
            </div>
            {lower.text.body && <div className="lower-body">{lower.text.body}</div>}
            {lower.text.why && lower.text.why.length > 0 && (
              <ul className="lower-why">
                {lower.text.why.slice(0, profile.mode === "analyst" ? 4 : 3).map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>
          <AiBadge o={lower} />
        </div>
      )}

      {small.length > 0 && (
        <div className="smalls">
          {small.map((o) => (
            <div className="small" key={o.id}>
              <div className="small-head">{o.text.headline}</div>
              <div className="small-body">{o.text.body}</div>
            </div>
          ))}
        </div>
      )}

      {recap && (
        <div className="recap" onClick={() => dismiss(recap.id)} title="Click to close">
          <div className="recap-card">
            <div className="recap-kicker">{recap.text.headline}</div>
            <div className="recap-score">{recap.text.sub}</div>
            <p>{recap.text.body}</p>
            {recap.rows && <StatRows rows={recap.rows} home={home.short} away={away.short} />}
            <AiBadge o={recap} />
          </div>
        </div>
      )}
    </div>
  );
}

function StatRows({ rows, home, away }: { rows: (string | number)[][]; home: string; away: string }) {
  return (
    <table className="stat-rows">
      <thead>
        <tr>
          <th />
          <th>{home}</th>
          <th>{away}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={String(r[0])}>
            <td>{r[0]}</td>
            <td>{r[1]}</td>
            <td>{r[2]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AiBadge({ o }: { o: Overlay }) {
  return o.text.source === "llm" ? <span className="ai-badge" title="Written by the AI model from the computed facts">AI</span> : null;
}
