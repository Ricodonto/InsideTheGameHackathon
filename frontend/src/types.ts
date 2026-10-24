// Shapes of the messages streamed by the backend (see backend/server.py and docs/overlay-contract.md).

export type Mode = "analyst" | "casual" | "player" | "metric";
export type Side = "home" | "away";

export interface Profile {
  mode: Mode;
  language: string;
  club: string | null;
  player: string | null;
  metric: string;
}

export interface Player {
  id: string;
  name: string;
  short: string;
  number: number;
  position: string;
  star: boolean;
}

export interface Club {
  id: string;
  name: string;
  short: string;
  primary: string;
  secondary: string;
  formation: string;
  players: Player[];
}

export interface Meta {
  scenario: { id: string; title: string; description: string; home: string; away: string };
  match: {
    match_id: string;
    home: Club;
    away: Club;
    duration: number;
    period_starts: number[];
    period_ends: number[];
  };
  llm: boolean;
  llm_provider: string | null; // "Foundry" or "GitHub Models"
  fabric: boolean;
}

export interface Frame {
  t: number;
  ball: [number, number];
  players: [string, number, number][];
}

export interface OverlayText {
  headline: string;
  sub?: string;
  body?: string;
  why?: string[];
  source: "template" | "llm";
}

export interface Overlay {
  id: string;
  insight_id: string;
  t: number;
  minute: string;
  type: "key_moment" | "index_alert" | "player_tag" | "pass_card" | "shot_card" | "stat_panel" | "recap" | "ticker";
  kind: string;
  anchor: { kind: string; player_id?: string };
  ttl: number;
  priority: number;
  side: Side | null;
  team: string | null;
  players: string[];
  metric_tags: string[];
  metrics: Record<string, number | string | boolean>;
  importance: number;
  key: boolean;
  text: OverlayText;
  rows?: (string | number)[][];
  code?: string;
  receivedAt?: number; // client time the overlay arrived (live overlays only)
}

export interface TeamStats {
  goals: number;
  shots: number;
  on_target: number;
  xg: number;
  possession_pct: number;
  pass_completion_pct: number;
  passes: number;
  pressures: number;
  high_regains: number;
  tackles: number;
  interceptions: number;
  corners: number;
  fouls: number;
  yellow: number;
  red: number;
  final_third_entries: number;
  distance_km: number;
}

export interface PlayerStats {
  id: string;
  name: string;
  side: Side;
  on_pitch: boolean;
  minutes: number;
  touches: number;
  passes: number;
  passes_completed: number;
  pass_accuracy_pct: number | null;
  avg_pass_difficulty: number | null;
  difficult_completed: number;
  progressive_passes: number;
  shots: number;
  on_target: number;
  goals: number;
  assists: number;
  xg: number;
  tackles: number;
  interceptions: number;
  pressures: number;
  distance_km: number;
  top_speed_kmh: number;
  sprints: number;
  yellow: number;
  red: number;
  rating: number;
}

export interface SeriesPoint {
  minute: number;
  t: number;
  wp: [number, number, number];
  control: number;
  tempo: number;
  pressure_home: number;
  pressure_away: number;
  momentum: number;
}

export interface MatchState {
  t: number;
  period: number;
  clock: number;
  minute: string;
  finished: boolean;
  score: Record<Side, number>;
  stats: Record<Side, TeamStats>;
  indices: { control: number; tempo: number; pressure: Record<Side, number>; momentum: number };
  win_probability: { home: number; draw: number; away: number };
  series: SeriesPoint[];
  players: Record<string, PlayerStats>;
  on_pitch: Record<Side, string[]>;
}

export interface Answer {
  question: string;
  answer: string;
  cites: string[];
  source: string;
}

export interface Status {
  playing: boolean;
  speed: number;
  t: number;
  duration: number;
}

export interface ViewerData {
  overlays: Overlay[];
  answers: Answer[];
}

export const LANGUAGES: Record<string, string> = {
  en: "English",
  es: "Español",
  fr: "Français",
  sw: "Kiswahili",
};

export const LLM_LANGUAGES: Record<string, string> = {
  pt: "Português",
  ar: "العربية",
  hi: "हिन्दी",
};

export const METRICS: Record<string, string> = {
  speed: "Speed",
  pass_difficulty: "Pass difficulty",
  pressure: "Pressure",
  xg: "Expected goals",
  distance: "Distance",
};

export const MODES: Record<Mode, string> = {
  analyst: "Analyst",
  casual: "Casual fan",
  player: "Player focus",
  metric: "Single metric",
};
