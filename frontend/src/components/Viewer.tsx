import { useState } from "react";
import type { FrameBuffer } from "../useMatchStream";
import type { Answer, Frame, MatchState, Meta, Mode, Overlay, Profile } from "../types";
import { LANGUAGES, LLM_LANGUAGES, METRICS, MODES } from "../types";
import { Feed, Indices, MetricTracker, Momentum, PlayerCard, StatsTable, WinChance, WinProbChart } from "./Panels";
import { Stage } from "./Stage";

interface Props {
  index: number;
  label: string;
  meta: Meta;
  state: MatchState | null;
  frame: Frame | null;
  frames: React.MutableRefObject<FrameBuffer>;
  overlays: Overlay[];
  answers: Answer[];
  profile: Profile;
  onProfile: (p: Profile) => void;
  onReplay: (t: number) => void;
  onAsk: (q: string) => void;
}

const SUGGESTIONS: Record<Mode, string[]> = {
  analyst: ["Why did the momentum shift?", "Who leads on pressures?", "What's the xG?"],
  casual: ["What's the score?", "Who's been the best player?", "Why did that goal matter?"],
  player: ["How is my player doing?", "Who has run the furthest?", "Who is the fastest?"],
  metric: ["Who is the fastest?", "Who has run the furthest?", "What's the xG?"],
};

export function Viewer(props: Props) {
  const { meta, state, profile, onProfile, overlays } = props;
  const { home, away } = meta.match;
  const set = (patch: Partial<Profile>) => onProfile({ ...profile, ...patch });
  const goals = overlays.filter((o) => o.kind === "goal");
  const focusClub = profile.player?.startsWith(home.short + "-") ? home : away;
  const languages = meta.llm ? { ...LANGUAGES, ...LLM_LANGUAGES } : LANGUAGES;

  return (
    <section className="viewer" aria-label={props.label}>
      <div className="profile-bar">
        <span className="viewer-label">{props.label}</span>
        <label>
          Mode
          <select value={profile.mode} onChange={(e) => set({ mode: e.target.value as Mode })}>
            {Object.entries(MODES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Language
          <select value={profile.language} onChange={(e) => set({ language: e.target.value })}>
            {Object.entries(languages).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Club
          <select value={profile.club ?? ""} onChange={(e) => set({ club: e.target.value || null })}>
            <option value="">Neutral</option>
            <option value={home.short}>{home.name}</option>
            <option value={away.short}>{away.name}</option>
          </select>
        </label>
        {profile.mode === "player" && (
          <label>
            Player
            <select value={profile.player ?? ""} onChange={(e) => set({ player: e.target.value || null })}>
              <option value="">Choose…</option>
              {[home, away].map((c) => (
                <optgroup key={c.short} label={c.name}>
                  {c.players.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.number} {p.name} ({p.position}){p.star ? " ★" : ""}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
        )}
        {profile.mode === "metric" && (
          <label>
            Metric
            <select value={profile.metric} onChange={(e) => set({ metric: e.target.value })}>
              {Object.entries(METRICS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <Stage meta={meta} state={state} frame={props.frame} frames={props.frames} overlays={overlays} profile={profile} />

      {state && (
        <div className={`panels panels-${profile.mode}`}>
          {profile.mode === "analyst" && (
            <>
              <WinProbChart state={state} home={home} away={away} goals={goals} />
              <Indices state={state} home={home} away={away} />
              <StatsTable state={state} home={home} away={away} />
              <Feed overlays={overlays} onReplay={props.onReplay} title="Commentary & key moments" />
            </>
          )}
          {profile.mode === "casual" && (
            <>
              <div className="stack">
                <WinChance state={state} home={home} away={away} />
                <div className="card">
                  <Momentum value={state.indices.momentum} home={home} away={away} big />
                </div>
              </div>
              <Feed overlays={overlays.filter((o) => o.key || o.type === "ticker")} onReplay={props.onReplay} title="The story so far" />
            </>
          )}
          {profile.mode === "player" && (
            <>
              <PlayerCard p={profile.player ? state.players[profile.player] : undefined} club={focusClub} />
              <Feed
                overlays={overlays.filter((o) => (profile.player && o.players.includes(profile.player)) || o.kind === "goal" || o.type === "ticker")}
                onReplay={props.onReplay}
                title="Their match"
              />
            </>
          )}
          {profile.mode === "metric" && (
            <>
              <MetricTracker metric={profile.metric} state={state} home={home} away={away} />
              <Feed overlays={overlays} onReplay={props.onReplay} title="Moments" />
            </>
          )}
          <AskBox answers={props.answers} onAsk={props.onAsk} suggestions={SUGGESTIONS[profile.mode]} provider={meta.llm ? meta.llm_provider : null} />
        </div>
      )}
    </section>
  );
}

function AskBox({ answers, onAsk, suggestions, provider }: { answers: Answer[]; onAsk: (q: string) => void; suggestions: string[]; provider: string | null }) {
  const [q, setQ] = useState("");
  const submit = (text: string) => {
    if (!text.trim()) return;
    onAsk(text.trim());
    setQ("");
  };
  return (
    <div className="card ask">
      <div className="card-head">
        <span>Ask the match</span>
        <span className="hint">{provider ? `answered by AI (${provider}) from live data` : "rule-based answers (add AI keys in .env)"}</span>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(q);
        }}
      >
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Why did they concede?" aria-label="Question" />
        <button type="submit">Ask</button>
      </form>
      <div className="chips">
        {suggestions.map((s) => (
          <button key={s} className="chip" onClick={() => submit(s)}>
            {s}
          </button>
        ))}
      </div>
      <ol className="answers">
        {[...answers].reverse().map((a, i) => (
          <li key={i}>
            <div className="q">{a.question}</div>
            <div className="a">
              {a.answer}
              {a.source === "llm" && <span className="ai-badge">AI</span>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
