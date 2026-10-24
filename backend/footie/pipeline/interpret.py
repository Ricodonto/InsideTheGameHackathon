"""Stage 2, Interpret: turn raw events and frames into football meaning.

`MatchAnalyzer` is incremental: it only knows what has been ingested so far.
It maintains team and player stats, pass quality, ball/shot/player speeds,
win probability and three story indices (Control vs Chaos, Pressure, Rhythm),
and emits *insights*: structured, language-neutral facts about moments worth
showing. Insights carry the evidence (event ids) and the context numbers the
explain stage needs to say *why* a moment matters.
"""
from __future__ import annotations

import math
from collections import deque

from ..football_models import (
    PITCH_L,
    SPRINT_MS,
    clamp,
    expected_goals,
    pass_difficulty,
    shot_geometry,
    win_probability,
)
from ..sim.simulator import HALF, SimulatedMatch, other, to_frame

WINDOW = 300.0      # 5 minutes of match time for the indices
LONG_WINDOW = 600.0  # 10 minutes for momentum
ON_BALL = {"pass", "carry", "shot"}
REGAINS = {"tackle", "interception", "recovery"}


def norm(v: float, lo: float, hi: float) -> float:
    return clamp((v - lo) / (hi - lo), 0.0, 1.0)


def minute_label(period: int, clock: float) -> str:
    m = int(clock // 60) + 1
    if period == 1 and clock >= HALF:
        return f"45+{m - 45}'"
    if period == 2 and clock >= 2 * HALF:
        return f"90+{m - 90}'"
    return f"{m}'"


def _team_stats() -> dict:
    return {
        "goals": 0, "shots": 0, "on_target": 0, "xg": 0.0, "passes": 0, "passes_completed": 0,
        "pressures": 0, "tackles": 0, "interceptions": 0, "fouls": 0, "yellow": 0, "red": 0,
        "corners": 0, "possession_s": 0.0, "final_third_entries": 0, "high_regains": 0,
    }


def _player_stats() -> dict:
    return {
        "touches": 0, "passes": 0, "passes_completed": 0, "difficulty_sum": 0.0, "difficult_completed": 0,
        "progressive_passes": 0, "shots": 0, "on_target": 0, "goals": 0, "assists": 0, "xg": 0.0,
        "tackles": 0, "interceptions": 0, "pressures": 0, "recoveries": 0, "fouls": 0,
        "distance_m": 0.0, "top_speed_kmh": 0.0, "sprints": 0, "minutes": 0.0,
        "yellow": 0, "red": 0,
    }


class MatchAnalyzer:
    def __init__(self, match: SimulatedMatch):
        self.m = match
        self.side_of = {p.id: "home" for p in match.home.players} | {p.id: "away" for p in match.away.players}
        self.name = {p.id: p.short for c in (match.home, match.away) for p in c.players}
        self.t = 0.0
        self.period = 1
        self.clock = 0.0
        self.finished = False
        self.score = {"home": 0, "away": 0}
        self.team = {"home": _team_stats(), "away": _team_stats()}
        self.players = {pid: _player_stats() for pid in self.side_of}
        self.on_pitch = {"home": {p.id for p in match.home.starters}, "away": {p.id for p in match.away.starters}}
        self.entered = {pid: 0.0 for s in self.on_pitch.values() for pid in s}
        self.left: dict[str, float] = {}

        self.win = deque()  # (t, kind, side, value) for rolling windows
        self.seq_hist = deque()  # (end_t, side, passes)
        self.poss_side: str | None = None
        self.last_ball_t: float | None = None
        self.seq: dict | None = None
        self.last_pressure_on: dict[str, float] = {}
        self.last_complete_pass: dict[str, dict] = {}
        self.goals_by: dict[str, int] = {}
        self.goal_list: list[dict] = []

        self.idx = {"control": 50.0, "tempo": 50.0, "pressure": {"home": 50.0, "away": 50.0}, "momentum": 0.0}
        self._win_detail = {"completion": 0.8, "turnovers_pm": 0.0, "seq_len": 0.0}
        self.wp = self._win_prob()
        self.idx_hist = deque()  # (t, control, p_home, p_away)
        self.series: list[dict] = []
        self._next_series_min = 0
        self._next_tick = 0.0
        self._next_panel_min = 15
        self.ctrl_state = "neutral"
        self.ctrl_last = -1e9
        self.press_last = {"home": -1e9, "away": -1e9}

        self.prev_pos: dict[str, tuple[float, float, float]] = {}
        self.prev_v: dict[str, float] = {}
        self.run: dict[str, int] = {}
        self.run_peak: dict[str, float] = {}
        self.km_marks: dict[str, int] = {}
        self.speed_record = 0.0
        self.speed_record_last = -1e9

        self._n = 0
        self.insights: list[dict] = []

    # ------------------------------------------------------------------ helpers
    def club(self, side: str):
        return self.m.home if side == "home" else self.m.away

    def label(self) -> str:
        return minute_label(self.period, self.clock)

    def insight(self, kind: str, side: str | None, players: list[str], importance: float,
                facts: dict, evidence: list[int] | None = None, key: bool = False) -> dict:
        self._n += 1
        ins = {
            "id": f"i{self._n}",
            "t": round(self.t, 2),
            "period": self.period,
            "clock": round(self.clock, 1),
            "minute": self.label(),
            "kind": kind,
            "side": side,
            "team": self.club(side).short if side else None,
            "players": [p for p in players if p],
            "importance": round(importance, 2),
            "key": key,
            "facts": facts,
            "evidence": evidence or [],
        }
        self.insights.append(ins)
        return ins

    def ticker(self, code: str, side: str | None, players: list[str], evidence: list[int] | None = None, **facts) -> dict:
        imp = {"tk_goal": 0.9, "tk_red": 0.8, "tk_half_time": 0.7, "tk_full_time": 0.9, "tk_kickoff": 0.6,
               "tk_second_half": 0.5, "tk_post": 0.5, "tk_saved": 0.4, "tk_sub": 0.3, "tk_yellow": 0.35}.get(code, 0.2)
        return self.insight("ticker", side, players, imp, {"code": code, **facts}, evidence)

    def frame_xy(self, side: str, x: float, y: float) -> tuple[float, float]:
        return to_frame(side, x, y)

    def _push(self, kind: str, side: str | None, value: float = 1.0) -> None:
        self.win.append((self.t, kind, side, value))

    def _window(self, span: float) -> list[tuple]:
        lo = self.t - span
        return [w for w in self.win if w[0] >= lo]

    def minutes_played(self) -> float:
        return self.clock / 60.0

    def _rates(self) -> tuple[float, float]:
        sh, sa = self.m.home.strength, self.m.away.strength
        rh = 1.35 * (1 + 1.6 * (sh - sa)) + 0.12
        ra = 1.35 * (1 + 1.6 * (sa - sh)) - 0.05
        mins = self.minutes_played()
        if mins > 8:
            w = min(0.45, mins / 90 * 0.6)
            rh = (1 - w) * rh + w * self.team["home"]["xg"] / mins * 90
            ra = (1 - w) * ra + w * self.team["away"]["xg"] / mins * 90
        mom = self.idx["momentum"] / 100.0
        rh *= 1 + 0.15 * mom
        ra *= 1 - 0.15 * mom
        mh, ma = 11 - len(self.on_pitch["home"]), 11 - len(self.on_pitch["away"])
        rh *= 0.78**mh * 1.15**ma
        ra *= 0.78**ma * 1.15**mh
        return clamp(rh, 0.2, 4.0), clamp(ra, 0.2, 4.0)

    def _win_prob(self) -> tuple[float, float, float]:
        h, a = self.score["home"], self.score["away"]
        if self.finished:
            return (1.0, 0.0, 0.0) if h > a else (0.0, 1.0, 0.0) if h == a else (0.0, 0.0, 1.0)
        rh, ra = self._rates()
        left = max(0.5, 95.0 - self.minutes_played())
        return win_probability(h, a, rh, ra, left)

    def wp_for(self, side: str, wp: tuple[float, float, float] | None = None) -> int:
        wp = wp or self.wp
        return round(100 * (wp[0] if side == "home" else wp[2]))

    # ------------------------------------------------------------------ events
    def ingest_event(self, e: dict) -> list[dict]:
        start = len(self.insights)
        self.t = e["t"]
        self.period = e["period"]
        self.clock = e["clock"]
        side = e["side"]
        etype = e["type"]
        pid = e.get("player")

        if etype in ON_BALL or etype in REGAINS or etype in ("throw_in", "goal_kick", "corner"):
            self._possession(side, e)

        handler = getattr(self, f"_on_{etype}", None)
        if handler:
            handler(e, side, pid)
        if pid and etype in ON_BALL:
            self.players[pid]["touches"] += 1
        self.tick(self.t)
        return self.insights[start:]

    def _possession(self, side: str, e: dict) -> None:
        if self.last_ball_t is not None and self.poss_side and self.t - self.last_ball_t < 10:
            self.team[self.poss_side]["possession_s"] += self.t - self.last_ball_t
            self._push("poss", self.poss_side, self.t - self.last_ball_t)
        elif self.last_ball_t is not None:
            self._push("stop", None, self.t - self.last_ball_t)
        self.last_ball_t = self.t
        if e["type"] in ON_BALL:
            self._push("event", side)
        if side != self.poss_side:
            if self.poss_side is not None:
                self._push("turnover", side)
            if self.seq:
                self.seq_hist.append((self.t, self.seq["side"], self.seq["passes"]))
            fx, _ = self.frame_xy(side, e.get("x", 52.5), e.get("y", 34))
            self.seq = {"side": side, "start_t": self.t, "start_x": fx, "start_kind": e["type"], "passes": 0}
            self.poss_side = side

    def _on_period_start(self, e, side, pid):
        if self.period == 1:
            self.ticker("tk_kickoff", None, [], [e["id"]])
        else:
            self.ticker("tk_second_half", None, [], [e["id"]])

    def _on_period_end(self, e, side, pid):
        if self.period == 2:
            self.finished = True
        self.wp = self._win_prob()
        code = "tk_full_time" if self.period == 2 else "tk_half_time"
        self.ticker(code, None, [], [e["id"]], hs=self.score["home"], as_=self.score["away"])
        self.recap(final=self.period == 2)

    def _on_pass(self, e, side, pid):
        ps, ts = self.players[pid], self.team[side]
        x0, y0 = self.frame_xy(side, e["x"], e["y"])
        x1, y1 = self.frame_xy(side, e["end_x"], e["end_y"])
        dist = math.hypot(x1 - x0, y1 - y0)
        progress = x1 - x0
        pressed = self.t - self.last_pressure_on.get(pid, -99) < 2.5
        diff = pass_difficulty(dist, 0.8 if pressed else 0.15, progress, e.get("pass_type", "ground"))
        speed = dist / e["duration"] * 3.6 if e.get("duration") else 0.0
        complete = e["outcome"] == "complete"
        ps["passes"] += 1
        ts["passes"] += 1
        ps["difficulty_sum"] += diff
        self._push("pass", side, 1.0 if complete else 0.0)
        e_metrics = {"distance_m": round(dist, 1), "difficulty": round(diff, 2), "ball_speed_kmh": round(speed, 1),
                     "progress_m": round(progress, 1), "under_pressure": pressed}
        if complete:
            ps["passes_completed"] += 1
            ts["passes_completed"] += 1
            if self.seq and self.seq["side"] == side:
                self.seq["passes"] += 1
            if progress >= 10 and x1 > 35:
                ps["progressive_passes"] += 1
            if x0 < 70 <= x1:
                ts["final_third_entries"] += 1
                self._push("fte", side)
            self.last_complete_pass[side] = {"event": e, "t": self.t, "recipient": e["recipient"], "passer": pid}
            if diff >= 0.5 and e.get("pass_type") not in ("corner", "kick_off"):
                ps["difficult_completed"] += 1
                self.insight("difficult_pass", side, [pid, e["recipient"]], 0.2 + 0.3 * diff,
                             {**e_metrics, "passer": pid, "recipient": e["recipient"], "pass_type": e.get("pass_type")},
                             [e["id"]])

    def _on_carry(self, e, side, pid):
        x0, _ = self.frame_xy(side, e["x"], e["y"])
        x1, _ = self.frame_xy(side, e["end_x"], e["end_y"])
        if x0 < 70 <= x1:
            self.team[side]["final_third_entries"] += 1
            self._push("fte", side)

    def _on_pressure(self, e, side, pid):
        self.players[pid]["pressures"] += 1
        self.team[side]["pressures"] += 1
        self.last_pressure_on[e.get("on_player")] = self.t
        self._push("pressure", side)

    def _regain(self, e, side, pid, stat: str):
        self.players[pid][stat] += 1
        fx, _ = self.frame_xy(side, e["x"], e["y"])
        if fx >= 60:
            self.team[side]["high_regains"] += 1
            self._push("high_regain", side)
            if self.seq and self.seq["side"] == side:
                self.seq["high_regain"] = True

    def _on_tackle(self, e, side, pid):
        self.team[side]["tackles"] += 1
        self._regain(e, side, pid, "tackles")

    def _on_interception(self, e, side, pid):
        self.team[side]["interceptions"] += 1
        self._regain(e, side, pid, "interceptions")

    def _on_recovery(self, e, side, pid):
        self._regain(e, side, pid, "recoveries")

    def _on_corner(self, e, side, pid):
        self.team[side]["corners"] += 1
        self.ticker("tk_corner", side, [pid], [e["id"]])

    def _on_foul(self, e, side, pid):
        self.team[side]["fouls"] += 1
        self.players[pid]["fouls"] += 1
        self.ticker("tk_foul", side, [pid], [e["id"]])

    def _on_substitution(self, e, side, pid):
        off = e["player_off"]
        self.on_pitch[side].discard(off)
        self.on_pitch[side].add(pid)
        self.entered[pid] = self.t
        self.left[off] = self.t
        self.ticker("tk_sub", side, [pid, off], [e["id"]], player_in=pid, player_out=off)

    def _on_card(self, e, side, pid):
        if e["card"] == "yellow":
            self.team[side]["yellow"] += 1
            self.players[pid]["yellow"] += 1
            self.ticker("tk_yellow", side, [pid], [e["id"]])
            return
        before = self.wp
        self.team[side]["red"] += 1
        self.players[pid]["red"] += 1
        self.on_pitch[side].discard(pid)
        self.left[pid] = self.t
        self.wp = self._win_prob()
        n = len(self.on_pitch[side])
        left = max(1, round(93 - self.minutes_played()))
        self.ticker("tk_red", side, [pid], [e["id"]], n=n)
        self.insight("red_card", side, [pid], 0.9, {
            "player": pid, "second_yellow": e.get("second_yellow", False), "men_left": n,
            "minutes_left": left, "wp_before": self.wp_for(side, before), "wp_after": self.wp_for(side),
            "score": [self.score["home"], self.score["away"]],
        }, [e["id"]], key=True)

    def _on_shot(self, e, side, pid):
        ps, ts = self.players[pid], self.team[side]
        x0, y0 = self.frame_xy(side, e["x"], e["y"])
        x1, y1 = self.frame_xy(side, e["end_x"], e["end_y"])
        header = e.get("body_part") == "head"
        xg = expected_goals(x0, y0, header=header)
        dist_goal, _ = shot_geometry(x0, y0)
        travel = math.hypot(x1 - x0, y1 - y0)
        speed = travel / e["duration"] * 3.6 if e.get("duration") else 0.0
        outcome = e["outcome"]
        on_target = outcome in ("goal", "saved")
        ps["shots"] += 1
        ts["shots"] += 1
        ps["xg"] += xg
        ts["xg"] += xg
        self._push("xg", side, xg)
        if on_target:
            ps["on_target"] += 1
            ts["on_target"] += 1
        assist = None
        lp = self.last_complete_pass.get(side)
        if lp and lp["recipient"] == pid and self.t - lp["t"] < 12:
            assist = lp["passer"]
        seq = self.seq if self.seq and self.seq["side"] == side else None
        seq_secs = round(self.t - seq["start_t"]) if seq else 0
        seq_travel = round(x0 - seq["start_x"]) if seq else 0
        metrics = {
            "shooter": pid, "xg": round(xg, 2), "speed_kmh": round(speed, 1), "distance_m": round(dist_goal, 1),
            "outcome": outcome, "body_part": e.get("body_part"), "set_piece": e.get("set_piece"), "assist": assist,
        }
        self.insight("shot", side, [pid], 0.3 + 0.4 * xg, metrics, [e["id"]])
        ctx = {
            "seq_passes": seq["passes"] if seq else 0,
            "seq_seconds": seq_secs,
            "seq_travel_m": seq_travel,
            "seq_start": seq["start_kind"] if seq else None,
            "high_regain": bool(seq and seq.get("high_regain")),
            "opp_momentum": self._momentum_for(other(side)),
            "minutes_left": max(0, round(93 - self.minutes_played())),
        }

        if outcome != "goal":
            code = {"saved": "tk_saved", "off_target": "tk_off_target", "blocked": "tk_blocked", "post": "tk_post"}[outcome]
            self.ticker(code, side, [pid], [e["id"]])
            if xg >= 0.25:
                self.insight("big_chance", side, [pid] + ([assist] if assist else []), 0.55 + 0.4 * xg,
                             {**metrics, **ctx, "wp": self.wp_for(side)}, [e["id"]], key=True)
            return

        before = self.wp
        h0, a0 = self.score["home"], self.score["away"]
        self.score[side] += 1
        ts["goals"] += 1
        ps["goals"] += 1
        if assist:
            self.players[assist]["assists"] += 1
        self.goals_by[pid] = self.goals_by.get(pid, 0) + 1
        self.goal_list.append({"minute": self.label(), "player": pid, "side": side})
        self.wp = self._win_prob()
        self.ticker("tk_goal", side, [pid], [e["id"]], hs=self.score["home"], as_=self.score["away"])
        lead_before = (h0 - a0) if side == "home" else (a0 - h0)
        evidence = [e["id"]] + ([lp["event"]["id"]] if assist else [])
        self.insight("goal", side, [pid] + ([assist] if assist else []), 1.0, {
            **metrics, **ctx,
            "scorer": pid,
            "score_before": [h0, a0],
            "score_after": [self.score["home"], self.score["away"]],
            "lead_before": lead_before,
            "scorer_goals": self.goals_by[pid],
            "wp_before": self.wp_for(side, before),
            "wp_after": self.wp_for(side),
        }, evidence, key=True)

    def _momentum_for(self, side: str) -> int:
        """Momentum share (-100..100) from `side`'s point of view over 10 minutes."""
        return round(self.idx["momentum"] if side == "home" else -self.idx["momentum"])

    # ------------------------------------------------------------------ frames
    def ingest_frame(self, f: dict) -> list[dict]:
        start = len(self.insights)
        t = f["t"]
        for pid, x, y in f["players"]:
            prev = self.prev_pos.get(pid)
            self.prev_pos[pid] = (t, x, y)
            if not prev or t - prev[0] > 0.5 or t <= prev[0]:
                continue
            d = math.hypot(x - prev[1], y - prev[2])
            v_raw = d / (t - prev[0])
            v = 0.5 * (v_raw + self.prev_v.get(pid, v_raw))
            self.prev_v[pid] = v_raw
            ps = self.players[pid]
            ps["distance_m"] += d
            kmh = v * 3.6
            if kmh > ps["top_speed_kmh"]:
                ps["top_speed_kmh"] = kmh
            km = int(ps["distance_m"] // 1000)
            if km > self.km_marks.get(pid, 0):
                self.km_marks[pid] = km
                self.t = max(self.t, t)
                self.insight("distance", self.side_of[pid], [pid], 0.3 if km >= 10 else 0.08,
                             {"player": pid, "km": km})
            if v > SPRINT_MS:
                self.run[pid] = self.run.get(pid, 0) + 1
                self.run_peak[pid] = max(self.run_peak.get(pid, 0.0), kmh)
            else:
                if self.run.get(pid, 0) >= 5:  # a sprint is >= 1 s above 25.2 km/h
                    ps["sprints"] += 1
                    peak = self.run_peak[pid]
                    self.t = max(self.t, t)
                    if peak > self.speed_record and peak >= 30 and t > 120 and t - self.speed_record_last > 90:
                        self.speed_record = peak
                        self.speed_record_last = t
                        self.insight("top_speed", self.side_of[pid], [pid], 0.4,
                                     {"player": pid, "speed_kmh": round(peak, 1), "record": True})
                    elif peak >= 27:
                        self.insight("sprint", self.side_of[pid], [pid], 0.08,
                                     {"player": pid, "speed_kmh": round(peak, 1)})
                    self.speed_record = max(self.speed_record, peak)
                self.run[pid] = 0
                self.run_peak[pid] = 0.0
        return self.insights[start:]

    # ------------------------------------------------------------------ periodic
    def tick(self, t: float) -> list[dict]:
        """Recompute indices and periodic insights. Safe to call often."""
        start = len(self.insights)
        if t < self._next_tick:
            return []
        self._next_tick = t + 5.0
        self.t = max(self.t, t)
        while self.win and self.win[0][0] < self.t - LONG_WINDOW:
            self.win.popleft()
        while self.seq_hist and self.seq_hist[0][0] < self.t - WINDOW:
            self.seq_hist.popleft()
        self._compute_indices()
        self.wp = self._win_prob()
        self.idx_hist.append((self.t, self.idx["control"], self.idx["pressure"]["home"], self.idx["pressure"]["away"]))
        while self.idx_hist and self.idx_hist[0][0] < self.t - WINDOW - 30:
            self.idx_hist.popleft()
        if self.clock / 60 >= self._next_series_min:
            self.series.append({
                "minute": round(self.clock / 60, 1),
                "t": round(self.t, 1),
                "wp": [round(v, 3) for v in self.wp],
                "control": round(self.idx["control"]),
                "tempo": round(self.idx["tempo"]),
                "pressure_home": round(self.idx["pressure"]["home"]),
                "pressure_away": round(self.idx["pressure"]["away"]),
                "momentum": round(self.idx["momentum"]),
            })
            self._next_series_min = int(self.clock / 60) + 1
        if self.clock > 8 * 60:
            self._detect_control_shift()
            self._detect_pressure_surge()
        if self.clock / 60 >= self._next_panel_min and self._next_panel_min not in (45, 90):
            self.insight("stat_panel", None, [], 0.35, {"stats": self.team_summary()})
            self._next_panel_min += 15
            if self._next_panel_min in (45, 90):
                self._next_panel_min += 15
        return self.insights[start:]

    def _compute_indices(self) -> None:
        w5 = self._window(WINDOW)
        span = max(60.0, min(WINDOW, self.t)) / 60.0
        passes = [v for (_, k, _, v) in w5 if k == "pass"]
        comp = sum(passes) / len(passes) if passes else 0.8
        turnovers = sum(1 for w in w5 if w[1] == "turnover") / span
        seqs = [n for (_, _, n) in self.seq_hist]
        seq_len = sum(seqs) / len(seqs) if seqs else 3.0
        control = 100 * (0.4 * norm(seq_len, 2.0, 6.5) + 0.35 * norm(comp, 0.68, 0.9) + 0.25 * (1 - norm(turnovers, 2.0, 4.2)))

        events = sum(1 for w in w5 if w[1] == "event") / span
        stop = sum(v for (_, k, _, v) in w5 if k == "stop") / (span * 60)
        tempo = 100 * (0.7 * norm(events, 9, 24) + 0.3 * (1 - clamp(stop, 0, 1)))

        pressure = {}
        for s in ("home", "away"):
            p = sum(1 for w in w5 if w[1] == "pressure" and w[2] == s) / span
            hr = sum(1 for w in w5 if w[1] == "high_regain" and w[2] == s)
            pressure[s] = 100 * (0.65 * norm(p, 1.0, 4.0) + 0.35 * norm(hr, 0, 4))

        w10 = self._window(LONG_WINDOW)
        xg = {s: sum(v for (_, k, sd, v) in w10 if k == "xg" and sd == s) for s in ("home", "away")}
        fte = {s: sum(1 for w in w10 if w[1] == "fte" and w[2] == s) for s in ("home", "away")}
        poss = {s: sum(v for (_, k, sd, v) in w10 if k == "poss" and sd == s) for s in ("home", "away")}
        tot = poss["home"] + poss["away"]
        share = poss["home"] / tot if tot else 0.5
        z = (xg["home"] - xg["away"]) * 1.2 + (fte["home"] - fte["away"]) / 14 + (share - 0.5) * 1.5
        momentum = 100 * math.tanh(z)

        # Smooth with a ~1 minute time constant so the story indices move like a narrative, not noise.
        a = 0.08 if self.clock > 120 else 0.5
        old = self.idx
        self.idx = {
            "control": old["control"] + a * (control - old["control"]),
            "tempo": old["tempo"] + a * (tempo - old["tempo"]),
            "pressure": {s: old["pressure"][s] + a * (pressure[s] - old["pressure"][s]) for s in pressure},
            "momentum": old["momentum"] + a * (momentum - old["momentum"]),
        }
        self._win_detail = {"completion": comp, "turnovers_pm": turnovers, "seq_len": seq_len}

    def _index_ago(self, field: int) -> float:
        for row in self.idx_hist:
            if row[0] >= self.t - WINDOW:
                return row[field]
        return self.idx_hist[0][field] if self.idx_hist else 50.0

    def _possession_share(self, span: float) -> dict[str, float]:
        w = self._window(span)
        poss = {s: sum(v for (_, k, sd, v) in w if k == "poss" and sd == s) for s in ("home", "away")}
        tot = poss["home"] + poss["away"]
        return {s: (poss[s] / tot if tot else 0.5) for s in poss}

    def _detect_control_shift(self) -> None:
        c = self.idx["control"]
        state = "control" if c >= 60 else "chaos" if c <= 38 else "neutral"
        if state == "neutral" or state == self.ctrl_state:
            if state != "neutral":
                self.ctrl_state = state
            return
        if self.t - self.ctrl_last < 600:
            return
        share = self._possession_share(WINDOW)
        dominant = max(share, key=share.get)
        if state == "control" and share[dominant] < 0.58:
            return
        self.ctrl_state = state
        self.ctrl_last = self.t
        d = self._win_detail
        self.insight("control_shift", dominant if state == "control" else None, [], 0.5, {
            "state": state,
            "index_before": round(self._index_ago(1)),
            "index_after": round(c),
            "turnovers_pm": round(d["turnovers_pm"], 1),
            "completion_pct": round(100 * d["completion"]),
            "possession_pct": round(100 * share[dominant]),
            "team_side": dominant if state == "control" else None,
        }, key=True)

    def _detect_pressure_surge(self) -> None:
        for s in ("home", "away"):
            now = self.idx["pressure"][s]
            ago = self._index_ago(2 if s == "home" else 3)
            if now >= 62 and now - ago >= 20 and self.t - self.press_last[s] >= 600:
                self.press_last[s] = self.t
                w5 = self._window(WINDOW)
                span = max(60.0, min(WINDOW, self.t)) / 60.0
                ppm = sum(1 for w in w5 if w[1] == "pressure" and w[2] == s) / span
                hr = sum(1 for w in w5 if w[1] == "high_regain" and w[2] == s)
                diff = self.score[s] - self.score[other(s)]
                self.insight("pressure_surge", s, [], 0.5, {
                    "index_before": round(ago), "index_after": round(now), "pressures_pm": round(ppm, 1),
                    "high_regains": hr, "chasing": diff < 0, "score_diff": diff,
                }, key=True)

    # ------------------------------------------------------------------ summaries
    def team_summary(self) -> dict:
        out = {}
        tot = self.team["home"]["possession_s"] + self.team["away"]["possession_s"]
        for s in ("home", "away"):
            ts = self.team[s]
            dist = sum(self.players[p]["distance_m"] for p in self.players if self.side_of[p] == s)
            out[s] = {
                "goals": ts["goals"],
                "shots": ts["shots"],
                "on_target": ts["on_target"],
                "xg": round(ts["xg"], 2),
                "possession_pct": round(100 * ts["possession_s"] / tot) if tot else 50,
                "pass_completion_pct": round(100 * ts["passes_completed"] / ts["passes"]) if ts["passes"] else 0,
                "passes": ts["passes"],
                "pressures": ts["pressures"],
                "high_regains": ts["high_regains"],
                "tackles": ts["tackles"],
                "interceptions": ts["interceptions"],
                "corners": ts["corners"],
                "fouls": ts["fouls"],
                "yellow": ts["yellow"],
                "red": ts["red"],
                "final_third_entries": ts["final_third_entries"],
                "distance_km": round(dist / 1000, 1),
            }
        return out

    def player_summary(self, pid: str) -> dict:
        ps = self.players[pid]
        mins_on = (self.left.get(pid, self.t) - self.entered[pid]) / 60 if pid in self.entered else 0.0
        rating = (
            ps["goals"] * 3 + ps["assists"] * 2 + ps["xg"] * 2 + ps["difficult_completed"] * 0.3
            + (ps["tackles"] + ps["interceptions"]) * 0.25 + ps["passes_completed"] / 20 + ps["on_target"] * 0.5
        )
        return {
            "id": pid,
            "name": self.name[pid],
            "side": self.side_of[pid],
            "on_pitch": pid in self.on_pitch[self.side_of[pid]],
            "minutes": round(max(0.0, mins_on)),
            "touches": ps["touches"],
            "passes": ps["passes"],
            "passes_completed": ps["passes_completed"],
            "pass_accuracy_pct": round(100 * ps["passes_completed"] / ps["passes"]) if ps["passes"] else None,
            "avg_pass_difficulty": round(100 * ps["difficulty_sum"] / ps["passes"]) if ps["passes"] else None,
            "difficult_completed": ps["difficult_completed"],
            "progressive_passes": ps["progressive_passes"],
            "shots": ps["shots"],
            "on_target": ps["on_target"],
            "goals": ps["goals"],
            "assists": ps["assists"],
            "xg": round(ps["xg"], 2),
            "tackles": ps["tackles"],
            "interceptions": ps["interceptions"],
            "pressures": ps["pressures"],
            "distance_km": round(ps["distance_m"] / 1000, 2),
            "top_speed_kmh": round(ps["top_speed_kmh"], 1),
            "sprints": ps["sprints"],
            "yellow": ps["yellow"],
            "red": ps["red"],
            "rating": round(rating, 2),
        }

    def recap(self, final: bool) -> dict:
        stats = self.team_summary()
        played = [pid for pid in self.players if pid in self.entered]
        summaries = [self.player_summary(p) for p in played]
        star = max(summaries, key=lambda s: s["rating"])
        fastest = max(summaries, key=lambda s: s["top_speed_kmh"])
        runner = max(summaries, key=lambda s: s["distance_km"])
        keys = [i for i in self.insights if i["key"]]

        def swing(i):
            f = i["facts"]
            return abs(f.get("wp_after", 0) - f.get("wp_before", 0)) + (20 if i["kind"] == "goal" else 0)

        turning = max(keys, key=swing) if keys else None
        return self.insight("recap", None, [star["id"]], 1.0 if final else 0.8, {
            "final": final,
            "score": [self.score["home"], self.score["away"]],
            "stats": stats,
            "goals": list(self.goal_list),
            "star": star,
            "fastest": {"player": fastest["id"], "speed_kmh": fastest["top_speed_kmh"]},
            "most_distance": {"player": runner["id"], "km": round(runner["distance_km"], 1)},
            "turning_point": turning["id"] if turning else None,
            "key_moments": [i["id"] for i in keys][-8:],
            "wp": [round(v, 3) for v in self.wp],
        }, key=True)

    def snapshot(self) -> dict:
        h, d, a = self.wp
        return {
            "t": round(self.t, 1),
            "period": self.period,
            "clock": round(self.clock, 1),
            "minute": self.label(),
            "finished": self.finished,
            "score": {"home": self.score["home"], "away": self.score["away"]},
            "stats": self.team_summary(),
            "indices": {
                "control": round(self.idx["control"]),
                "tempo": round(self.idx["tempo"]),
                "pressure": {s: round(v) for s, v in self.idx["pressure"].items()},
                "momentum": round(self.idx["momentum"]),
            },
            "win_probability": {"home": round(h, 3), "draw": round(d, 3), "away": round(a, 3)},
            "series": self.series,
            "players": {pid: self.player_summary(pid) for pid in self.players if pid in self.entered},
            "on_pitch": {s: sorted(v) for s, v in self.on_pitch.items()},
        }
