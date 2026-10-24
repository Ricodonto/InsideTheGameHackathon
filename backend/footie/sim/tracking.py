"""Light tracking data: positions of the ball and every player at 5 Hz.

Generated after the event stream. The ball follows the event geometry exactly.
Players move towards a target (their shape position, the ball if they carry or
press it, the pass destination if they are receiving) with realistic top-speed
and acceleration limits, so speeds and distances computed downstream are
physically plausible rather than invented.
"""
from __future__ import annotations

import math
import random
from array import array
from dataclasses import dataclass

from ..football_models import clamp
from .simulator import SimulatedMatch, shape_position, to_frame

HZ = 5
DT = 1.0 / HZ
AMAX_STEP = 4.5 * DT  # max change in velocity per step (4.5 m/s^2)
NAN = float("nan")


@dataclass
class Tracking:
    hz: int
    n: int
    ball_x: array
    ball_y: array
    px: dict[str, array]
    py: dict[str, array]

    def index(self, t: float) -> int:
        return max(0, min(self.n - 1, int(round(t * self.hz))))

    def frame(self, i: int) -> dict:
        players = []
        for pid, xs in self.px.items():
            x = xs[i]
            if x == x:  # not NaN
                players.append((pid, x, self.py[pid][i]))
        return {"t": i / self.hz, "ball": (self.ball_x[i], self.ball_y[i]), "players": players}


def _ball_keyframes(events: list[dict]) -> list[tuple[float, float, float]]:
    pts: list[tuple[float, float, float]] = [(0.0, 52.5, 34.0)]
    for e in events:
        if "x" not in e or e.get("x") is None:
            continue
        if e.get("end_x") is not None and e.get("duration"):
            pts.append((e["t"], e["x"], e["y"]))
            pts.append((e["t"] + e["duration"], e["end_x"], e["end_y"]))
        else:
            pts.append((e["t"], e["x"], e["y"]))
    pts.sort(key=lambda p: p[0])
    return pts


def build_tracking(match: SimulatedMatch, seed: int | None = None) -> Tracking:
    rng = random.Random(seed if seed is not None else match.seed + 7)
    n = int(match.duration * HZ) + 1
    events = match.events

    # --- ball
    keys = _ball_keyframes(events)
    ball_x, ball_y = array("f", [0.0]) * n, array("f", [0.0]) * n
    k = 0
    for i in range(n):
        t = i * DT
        while k + 1 < len(keys) and keys[k + 1][0] <= t:
            k += 1
        t0, x0, y0 = keys[k]
        if k + 1 < len(keys):
            t1, x1, y1 = keys[k + 1]
            f = 0.0 if t1 <= t0 else clamp((t - t0) / (t1 - t0), 0, 1)
            ball_x[i] = x0 + (x1 - x0) * f
            ball_y[i] = y0 + (y1 - y0) * f
        else:
            ball_x[i], ball_y[i] = x0, y0

    # --- context timelines
    poss_log = match.possession_log
    flights = [
        (e["t"], e["t"] + e["duration"], e["recipient"], e["end_x"], e["end_y"])
        for e in events
        if e["type"] == "pass" and e.get("recipient")
    ]
    pressures = [(e["t"], e["player"]) for e in events if e["type"] == "pressure"]
    lineup_changes = sorted(match.lineup_log)

    side_of: dict[str, str] = {}
    position_of: dict[str, str] = {}
    pace_of: dict[str, float] = {}
    stamina_of: dict[str, float] = {}
    for side, club in (("home", match.home), ("away", match.away)):
        for p in club.players:
            side_of[p.id] = side
            position_of[p.id] = p.position
            pace_of[p.id] = p.pace
            stamina_of[p.id] = p.stamina

    on_pitch = {p.id for p in match.home.starters} | {p.id for p in match.away.starters}
    entered = {pid: 0.0 for pid in on_pitch}
    ever = set(on_pitch) | {pid for _, _, kind, pid in lineup_changes if kind == "on"}

    px = {pid: array("f", [NAN]) * n for pid in ever}
    py = {pid: array("f", [NAN]) * n for pid in ever}
    wob = {pid: (rng.uniform(1.0, 2.0), rng.uniform(10, 18), rng.uniform(0, 6.3), rng.uniform(11, 19), rng.uniform(0, 6.3)) for pid in ever}

    pos: dict[str, list[float]] = {}
    vel: dict[str, list[float]] = {}
    # Before every kick-off (start of each half, after goals) players retreat into their own half.
    kickoffs = [e["t"] for e in events if e["type"] == "pass" and e.get("pass_type") == "kick_off"]

    def own_half(side: str, x: float) -> float:
        return min(x, 51.0) if side == "home" else max(x, 54.0)

    def init_player(pid: str, t: float, smooth_ball: tuple[float, float], poss_side: str) -> None:
        side = side_of[pid]
        bf = to_frame(side, *smooth_ball)
        fx, fy = shape_position(position_of[pid], match.anchors.get(pid, (40, 34)), bf, poss_side == side)
        x, y = to_frame(side, fx, fy)
        if t > 0:  # substitutes walk on from the touchline
            y = 0.0 if y < 34 else 68.0
        else:
            x = own_half(side, x)
        pos[pid] = [x, y]
        vel[pid] = [0.0, 0.0]

    sbx, sby = 52.5, 34.0
    pi = fi = pri = li = ki = 0
    poss_side, carrier = "home", None
    active_flight = None
    for pid in on_pitch:
        init_player(pid, 0.0, (sbx, sby), "home")

    alpha = DT / 1.2
    anchors = match.anchors
    vmax_of = {pid: 7.3 + 2.1 * pace_of[pid] for pid in ever}
    for i in range(n):
        t = i * DT
        bx, by = ball_x[i], ball_y[i]
        sbx += (bx - sbx) * alpha
        sby += (by - sby) * alpha

        while li < len(lineup_changes) and lineup_changes[li][0] <= t:
            _, _, kind, pid = lineup_changes[li]
            if kind == "off":
                on_pitch.discard(pid)
            else:
                on_pitch.add(pid)
                entered[pid] = t
                init_player(pid, t, (sbx, sby), poss_side)
            li += 1
        while pi < len(poss_log) and poss_log[pi][0] <= t:
            _, poss_side, carrier = poss_log[pi]
            pi += 1
        while fi < len(flights) and flights[fi][0] <= t:
            active_flight = flights[fi]
            fi += 1
        if active_flight and t > active_flight[1] + 0.3:
            active_flight = None
        while pri < len(pressures) and pressures[pri][0] < t - 0.5:
            pri += 1
        pressers = {p for (pt, p) in pressures[pri:pri + 3] if pt - 1.5 <= t <= pt + 0.5}
        while ki < len(kickoffs) and kickoffs[ki] < t:
            ki += 1
        before_kickoff = ki < len(kickoffs) and kickoffs[ki] - t <= 40

        frames_for = {"home": (sbx, sby), "away": (105.0 - sbx, 68.0 - sby)}
        for pid in on_pitch:
            side = side_of[pid]
            p, v = pos[pid], vel[pid]
            urgent = False
            if pid == carrier and not active_flight:
                tx, ty, urgent = bx, by, True
            elif active_flight and pid == active_flight[2]:
                tx, ty, urgent = active_flight[3], active_flight[4], True
            elif pid in pressers:
                tx, ty, urgent = bx, by, True
            else:
                fx, fy = shape_position(position_of[pid], anchors.get(pid, (40, 34)), frames_for[side], poss_side == side)
                if side == "away":
                    fx, fy = 105.0 - fx, 68.0 - fy
                tx, ty = fx, fy
                if before_kickoff:
                    tx = own_half(side, tx)
                if position_of[pid] != "GK":
                    a, p1, f1, p2, f2 = wob[pid]
                    tx += a * math.sin(6.283 * t / p1 + f1)
                    ty += a * math.cos(6.283 * t / p2 + f2)
            ex, ey = tx - p[0], ty - p[1]
            gap = math.hypot(ex, ey)
            if urgent and gap > 6:
                minutes = (t - entered.get(pid, 0.0)) / 60.0
                cap = vmax_of[pid] * (1 - 0.09 * min(minutes / 90, 1.2) * (1 - stamina_of[pid]))
                tau = 0.45
            else:
                cap, tau = 5.2, 1.0
            want = gap / tau
            if want > cap:
                want = cap
            if gap > 1e-6:
                dvx, dvy = ex / gap * want, ey / gap * want
            else:
                dvx = dvy = 0.0
            ax, ay = (dvx - v[0]), (dvy - v[1])
            dv = math.hypot(ax, ay)
            if dv > AMAX_STEP:
                ax, ay = ax * AMAX_STEP / dv, ay * AMAX_STEP / dv
            v[0] += ax
            v[1] += ay
            nx, ny = p[0] + v[0] * DT, p[1] + v[1] * DT
            p[0] = -2.0 if nx < -2 else 107.0 if nx > 107 else nx
            p[1] = -2.0 if ny < -2 else 70.0 if ny > 70 else ny
            px[pid][i] = p[0]
            py[pid][i] = p[1]

    return Tracking(HZ, n, ball_x, ball_y, px, py)
