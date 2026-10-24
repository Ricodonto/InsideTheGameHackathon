import type { Club, MatchState, Overlay, PlayerStats, Side } from "../types";
import { METRICS } from "../types";

const minuteOf = (label: string) => label.replace("'", "").split("+").reduce((a, b) => a + Number(b), 0);

export function WinProbChart({ state, home, away, goals }: { state: MatchState; home: Club; away: Club; goals: Overlay[] }) {
  const W = 300;
  const H = 110;
  const pts = state.series;
  if (pts.length < 2)
    return (
      <div className="card">
        <div className="card-head">
          <span>Win probability</span>
        </div>
        <div className="panel-empty">The chart starts after kick-off.</div>
      </div>
    );
  const x = (m: number) => (Math.min(m, 96) / 96) * W;
  const top = pts.map((p) => [x(p.minute), p.wp[0] * H] as const);
  const mid = pts.map((p) => [x(p.minute), (p.wp[0] + p.wp[1]) * H] as const);
  const line = (arr: readonly (readonly [number, number])[]) => arr.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" L");
  const last = pts[pts.length - 1];
  const homeArea = `M${x(pts[0].minute)},0 L${line(top)} L${x(last.minute)},0 Z`;
  const drawArea = `M${line(top)} L${[...mid].reverse().map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" L")} Z`;
  const awayArea = `M${line(mid)} L${x(last.minute)},${H} L${x(pts[0].minute)},${H} Z`;
  const wp = state.win_probability;
  return (
    <div className="card">
      <div className="card-head">
        <span>Win probability</span>
        <span className="legend">
          <i style={{ background: home.primary }} /> {home.short} {Math.round(wp.home * 100)}%
          <i style={{ background: "var(--draw)" }} /> Draw {Math.round(wp.draw * 100)}%
          <i style={{ background: away.primary }} /> {away.short} {Math.round(wp.away * 100)}%
        </span>
      </div>
      <svg viewBox={`0 -4 ${W} ${H + 18}`} className="wp-chart" role="img" aria-label="Win probability over time">
        <path d={homeArea} fill={home.primary} opacity={0.9} />
        <path d={drawArea} fill="var(--draw)" opacity={0.7} />
        <path d={awayArea} fill={away.primary} opacity={0.9} />
        {[0, 45, 90].map((m) => (
          <g key={m}>
            <line x1={x(m)} x2={x(m)} y1={0} y2={H} stroke="var(--grid)" strokeDasharray="2 3" />
            <text x={x(m)} y={H + 12} className="axis" textAnchor={m === 0 ? "start" : m === 90 ? "end" : "middle"}>
              {m}'
            </text>
          </g>
        ))}
        {goals.map((g) => (
          <g key={g.id}>
            <line x1={x(minuteOf(g.minute))} x2={x(minuteOf(g.minute))} y1={0} y2={H} stroke="#fff" strokeWidth={1.2} />
            <circle cx={x(minuteOf(g.minute))} cy={g.side === "home" ? 4 : H - 4} r={3.2} fill="#fff" />
          </g>
        ))}
      </svg>
    </div>
  );
}

function Meter({ label, value, left, right, color }: { label: string; value: number; left: string; right: string; color?: string }) {
  return (
    <div className="meter">
      <div className="meter-label">
        <span>{label}</span>
        <span className="num">{value}</span>
      </div>
      <div className="meter-track">
        <div className="meter-fill" style={{ width: `${value}%`, background: color }} />
      </div>
      <div className="meter-ends">
        <span>{left}</span>
        <span>{right}</span>
      </div>
    </div>
  );
}

export function Indices({ state, home, away }: { state: MatchState; home: Club; away: Club }) {
  const ix = state.indices;
  const mom = ix.momentum;
  return (
    <div className="card">
      <div className="card-head">
        <span>Story indices</span>
        <span className="hint">last 5 minutes</span>
      </div>
      <Meter label="Control vs chaos" value={ix.control} left="Chaos" right="Control" color="var(--accent)" />
      <Meter label="Rhythm" value={ix.tempo} left="Stop-start" right="Frantic" color="#7cc4ff" />
      <Meter label={`${home.short} pressure`} value={ix.pressure.home} left="Passive" right="Suffocating" color={home.primary} />
      <Meter label={`${away.short} pressure`} value={ix.pressure.away} left="Passive" right="Suffocating" color={away.primary} />
      <Momentum value={mom} home={home} away={away} />
    </div>
  );
}

export function Momentum({ value, home, away, big }: { value: number; home: Club; away: Club; big?: boolean }) {
  const pct = Math.abs(value) / 2;
  return (
    <div className={`momentum ${big ? "momentum-big" : ""}`}>
      <div className="meter-label">
        <span>{big ? "Who's on top?" : "Momentum (10 min)"}</span>
        <span className="num">{value === 0 ? "Even" : `${value > 0 ? home.short : away.short} +${Math.abs(value)}`}</span>
      </div>
      <div className="mom-track">
        <div className="mom-mid" />
        <div
          className="mom-fill"
          style={{
            width: `${pct}%`,
            left: value >= 0 ? `${50 - pct}%` : "50%",
            background: value >= 0 ? home.primary : away.primary,
          }}
        />
      </div>
      <div className="meter-ends">
        <span>{home.name}</span>
        <span>{away.name}</span>
      </div>
    </div>
  );
}

export function WinChance({ state, home, away }: { state: MatchState; home: Club; away: Club }) {
  const wp = state.win_probability;
  const seg = (v: number, bg: string, fg: string, label: string) =>
    v > 0.02 ? (
      <div style={{ flex: v, background: bg, color: fg }} className="wc-seg">
        {v > 0.12 && `${label} ${Math.round(v * 100)}%`}
      </div>
    ) : null;
  return (
    <div className="card">
      <div className="card-head">
        <span>Chance of winning</span>
      </div>
      <div className="wc-bar">
        {seg(wp.home, home.primary, home.secondary, home.short)}
        {seg(wp.draw, "var(--draw)", "#111", "Draw")}
        {seg(wp.away, away.primary, away.secondary, away.short)}
      </div>
    </div>
  );
}

export function StatsTable({ state, home, away }: { state: MatchState; home: Club; away: Club }) {
  const h = state.stats.home;
  const a = state.stats.away;
  const rows: [string, string | number, string | number][] = [
    ["Possession", `${h.possession_pct}%`, `${a.possession_pct}%`],
    ["Shots (on target)", `${h.shots} (${h.on_target})`, `${a.shots} (${a.on_target})`],
    ["xG", h.xg.toFixed(2), a.xg.toFixed(2)],
    ["Pass completion", `${h.pass_completion_pct}%`, `${a.pass_completion_pct}%`],
    ["Final-third entries", h.final_third_entries, a.final_third_entries],
    ["Pressures", h.pressures, a.pressures],
    ["High regains", h.high_regains, a.high_regains],
    ["Ball wins (tackles, interceptions)", h.tackles + h.interceptions, a.tackles + a.interceptions],
    ["Corners", h.corners, a.corners],
    ["Distance (km)", h.distance_km, a.distance_km],
  ];
  return (
    <div className="card">
      <div className="card-head">
        <span>Match stats</span>
      </div>
      <table className="stats">
        <thead>
          <tr>
            <th style={{ color: home.primary === "#1a1a1a" ? home.secondary : undefined }}>{home.short}</th>
            <th />
            <th>{away.short}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, hv, av]) => (
            <tr key={k}>
              <td className="num">{hv}</td>
              <td className="stat-label">{k}</td>
              <td className="num">{av}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Feed({ overlays, onReplay, title = "Live feed", limit = 60 }: {
  overlays: Overlay[];
  onReplay: (t: number) => void;
  title?: string;
  limit?: number;
}) {
  const items = overlays.filter((o) => o.key || o.type === "ticker").slice(-limit).reverse();
  return (
    <div className="card feed">
      <div className="card-head">
        <span>{title}</span>
      </div>
      {items.length === 0 && <div className="panel-empty">Waiting for kick-off.</div>}
      <ol>
        {items.map((o) =>
          o.type === "ticker" ? (
            <li key={o.id} className="feed-line">
              <span className="feed-min">{o.minute}</span>
              {o.text.headline}
            </li>
          ) : o.type === "recap" ? null : (
            <li key={o.id} className={`feed-moment feed-${o.kind}`}>
              <div className="feed-moment-head">
                <span className="feed-min">{o.minute}</span>
                <strong>{o.text.headline}</strong>
                <button className="replay" onClick={() => onReplay(o.t)} title="Replay this moment">
                  Replay
                </button>
              </div>
              {o.text.body && <div className="feed-body">{o.text.body}</div>}
              {o.text.why?.map((w, i) => (
                <div key={i} className="feed-why">
                  {w}
                </div>
              ))}
            </li>
          ),
        )}
      </ol>
    </div>
  );
}

export function PlayerCard({ p, club }: { p: PlayerStats | undefined; club: Club }) {
  if (!p) return <div className="card panel-empty">Pick a player to follow.</div>;
  const info = club.players.find((x) => x.id === p.id);
  const cells: [string, string | number][] = [
    ["Minutes", p.minutes],
    ["Distance", `${p.distance_km.toFixed(2)} km`],
    ["Top speed", `${p.top_speed_kmh.toFixed(1)} km/h`],
    ["Sprints", p.sprints],
    ["Passes", `${p.passes_completed}/${p.passes}`],
    ["Pass accuracy", p.pass_accuracy_pct === null ? "–" : `${p.pass_accuracy_pct}%`],
    ["Avg pass difficulty", p.avg_pass_difficulty ?? "–"],
    ["Hard passes completed", p.difficult_completed],
    ["Shots (on target)", `${p.shots} (${p.on_target})`],
    ["xG", p.xg.toFixed(2)],
    ["Goals / assists", `${p.goals} / ${p.assists}`],
    ["Ball wins", p.tackles + p.interceptions],
  ];
  return (
    <div className="card player-card">
      <div className="pc-head" style={{ background: club.primary, color: club.secondary }}>
        <span className="pc-num">{info?.number}</span>
        <div>
          <div className="pc-name">{info?.name ?? p.name}</div>
          <div className="pc-sub">
            {info?.position} · {club.name} {p.on_pitch ? "" : "· off the pitch"}
          </div>
        </div>
      </div>
      <dl className="pc-grid">
        {cells.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className="num">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const METRIC_VALUE: Record<string, (p: PlayerStats) => number> = {
  speed: (p) => p.top_speed_kmh,
  distance: (p) => p.distance_km,
  pass_difficulty: (p) => p.difficult_completed,
  xg: (p) => p.xg,
  pressure: (p) => p.pressures,
};
const METRIC_FMT: Record<string, (v: number) => string> = {
  speed: (v) => `${v.toFixed(1)} km/h`,
  distance: (v) => `${v.toFixed(2)} km`,
  pass_difficulty: (v) => `${v} hard passes`,
  xg: (v) => `${v.toFixed(2)} xG`,
  pressure: (v) => `${v} pressures`,
};

export function MetricTracker({ metric, state, home, away }: { metric: string; state: MatchState; home: Club; away: Club }) {
  const val = METRIC_VALUE[metric] ?? METRIC_VALUE.speed;
  const fmt = METRIC_FMT[metric] ?? METRIC_FMT.speed;
  const ranked = Object.values(state.players).sort((a, b) => val(b) - val(a)).slice(0, 6);
  const clubOf = (s: Side) => (s === "home" ? home : away);
  const teamValue =
    metric === "pressure"
      ? [state.indices.pressure.home, state.indices.pressure.away].map((v) => `${v}`)
      : metric === "xg"
        ? [state.stats.home.xg.toFixed(2), state.stats.away.xg.toFixed(2)]
        : null;
  const leader = ranked[0];
  return (
    <div className="card metric">
      <div className="card-head">
        <span>{METRICS[metric] ?? metric}</span>
        <span className="hint">match leaders</span>
      </div>
      {leader && (
        <div className="metric-big">
          <span className="num">{fmt(val(leader))}</span>
          <span>{leader.name}</span>
        </div>
      )}
      {teamValue && (
        <div className="metric-teams">
          <span style={{ color: home.primary === "#1a1a1a" ? "#ddd" : undefined }}>
            {home.short} {teamValue[0]}
          </span>
          <span>
            {away.short} {teamValue[1]}
          </span>
        </div>
      )}
      <ol className="leaders">
        {ranked.map((p) => (
          <li key={p.id}>
            <i style={{ background: clubOf(p.side).primary }} />
            <span>{p.name}</span>
            <span className="num">{fmt(val(p))}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
