"""Synthetic match engine: produces a football-realistic event stream.

The engine walks through a match as a chain of on-ball actions (pass, carry,
shot, tackle, ...). Each choice is driven by pitch zone, player attributes,
team style and a per-scenario "script" of multipliers, which is how we get
storylines such as a comeback on cue.

Coordinates in emitted events are absolute: home attacks towards x = 105 for
the whole match (we do not swap ends at half-time, to keep consumers simple).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..football_models import (
    PITCH_L,
    PITCH_W,
    clamp,
    expected_goals,
    pass_difficulty,
    pass_success_probability,
)
from .teams import FORMATIONS, Club, Player

HALF = 2700.0  # seconds in a regulation half


def other(side: str) -> str:
    return "away" if side == "home" else "home"


def to_frame(side: str, x: float, y: float) -> tuple[float, float]:
    """Absolute <-> team attacking frame (the transform is its own inverse)."""
    if side == "home":
        return x, y
    return PITCH_L - x, PITCH_W - y


def shape_position(
    position: str, anchor: tuple[float, float], ball_frame: tuple[float, float], in_possession: bool
) -> tuple[float, float]:
    """Where a player stands given the ball, in the team's attacking frame."""
    ax, ay = anchor
    bx, by = ball_frame
    if position == "GK":
        x = clamp(5 + max(0.0, bx - 35) * 0.12, 2, 18)
        y = 34 + (by - 34) * 0.15
        return x, y
    if in_possession:
        line = clamp(28 + (bx - 52.5) * 0.5, 14, 55)
        x = line + (ax - 22) * 0.85
        y = 34 + (ay - 34) * 1.05 + (by - 34) * 0.15
    else:
        line = clamp(18 + (bx - 52.5) * 0.45, 8, 40)
        x = line + (ax - 22) * 0.65
        y = 34 + (ay - 34) * 0.7 + (by - 34) * 0.35
    return clamp(x, 1, 104), clamp(y, 1, 67)


@dataclass
class ScriptPhase:
    start_min: float
    end_min: float
    mult: dict[str, float]  # keys like "home_attack", "away_press"


@dataclass
class ForcedRedCard:
    side: str
    minute: float
    position: str


@dataclass
class SimulatedMatch:
    """Raw output of the engine: metadata plus the ordered event list."""

    match_id: str
    home: Club
    away: Club
    seed: int
    events: list[dict]
    possession_log: list[tuple[float, str, str]]  # (t, side, carrier id)
    lineup_log: list[tuple[float, str, str, str]]  # (t, side, "on"/"off", player id)
    period_starts: list[float]
    period_ends: list[float]
    anchors: dict[str, tuple[float, float]]
    duration: float = 0.0
    tracking: object | None = None  # filled by tracking.build_tracking

    def club(self, side: str) -> Club:
        return self.home if side == "home" else self.away

    def player(self, pid: str) -> Player:
        for c in (self.home, self.away):
            for p in c.players:
                if p.id == pid:
                    return p
        raise KeyError(pid)

    def side_of(self, pid: str) -> str:
        return "home" if any(p.id == pid for p in self.home.players) else "away"

    def clock(self, t: float) -> tuple[int, float]:
        """(period, display seconds) for a global match time t."""
        if len(self.period_starts) > 1 and t >= self.period_starts[1]:
            return 2, HALF + (t - self.period_starts[1])
        return 1, t

    def final_score(self) -> tuple[int, int]:
        h = sum(1 for e in self.events if e["type"] == "shot" and e["outcome"] == "goal" and e["side"] == "home")
        a = sum(1 for e in self.events if e["type"] == "shot" and e["outcome"] == "goal" and e["side"] == "away")
        return h, a

    def score_at(self, t: float) -> tuple[int, int]:
        h = a = 0
        for e in self.events:
            if e["t"] > t:
                break
            if e["type"] == "shot" and e["outcome"] == "goal":
                if e["side"] == "home":
                    h += 1
                else:
                    a += 1
        return h, a

    def metadata(self) -> dict:
        return {
            "match_id": self.match_id,
            "seed": self.seed,
            "pitch": {"length": PITCH_L, "width": PITCH_W},
            "home": self.home.to_dict(),
            "away": self.away.to_dict(),
            "period_starts": self.period_starts,
            "period_ends": self.period_ends,
            "duration": self.duration,
            "anchors": {k: list(v) for k, v in self.anchors.items()},
        }


class MatchEngine:
    def __init__(
        self,
        match_id: str,
        home: Club,
        away: Club,
        seed: int,
        script: list[ScriptPhase] | None = None,
        forced_red: ForcedRedCard | None = None,
    ):
        self.match_id = match_id
        self.home, self.away = home, away
        self.seed = seed
        self.rng = random.Random(seed)
        self.script = script or []
        self.forced_red = forced_red
        self.events: list[dict] = []
        self.possession_log: list[tuple[float, str, str]] = []
        self.lineup_log: list[tuple[float, str, str, str]] = []
        self.on_pitch: dict[str, list[Player]] = {"home": list(home.starters), "away": list(away.starters)}
        self.bench: dict[str, list[Player]] = {"home": list(home.bench), "away": list(away.bench)}
        self.anchors: dict[str, tuple[float, float]] = {}
        for club in (home, away):
            for p, (_, ax, ay) in zip(club.starters, FORMATIONS[club.formation]):
                self.anchors[p.id] = (ax, ay)
        self.yellows: set[str] = set()
        self.subs_made = {"home": 0, "away": 0}
        self.sub_minutes = {
            s: sorted(self.rng.uniform(56, 84) for _ in range(3)) for s in ("home", "away")
        }
        self.t = 0.0
        self.period = 1
        self.period_starts: list[float] = []
        self.period_ends: list[float] = []
        self.poss = "home"
        self.carrier: Player = home.starters[0]
        self.ball = (52.5, 34.0)
        self._id = 0

    # ------------------------------------------------------------------ helpers
    def club(self, side: str) -> Club:
        return self.home if side == "home" else self.away

    def clock(self) -> float:
        return self.t - self.period_starts[-1] + (HALF if self.period == 2 else 0.0)

    def minute(self) -> float:
        return self.clock() / 60.0

    def mult(self, side: str, key: str) -> float:
        m = 1.0
        minute = self.minute()
        for ph in self.script:
            if ph.start_min <= minute < ph.end_min:
                m *= ph.mult.get(f"{side}_{key}", 1.0)
        # playing with fewer men hurts
        missing = 11 - len(self.on_pitch[side])
        if key == "attack":
            m *= 0.85**missing * 1.08 ** (11 - len(self.on_pitch[other(side)]))
        if key == "press":
            m *= 0.85**missing
        return m

    def emit(self, etype: str, side: str, player: Player | None, **kw) -> dict:
        self._id += 1
        period, clock = self.period, self.clock()
        ev = {
            "id": self._id,
            "match_id": self.match_id,
            "t": round(self.t, 2),
            "period": period,
            "clock": round(clock, 2),
            "type": etype,
            "side": side,
            "team": self.club(side).short,
            "player": player.id if player else None,
        }
        for k, v in kw.items():
            ev[k] = round(v, 2) if isinstance(v, float) else v
        self.events.append(ev)
        return ev

    def set_possession(self, side: str, carrier: Player) -> None:
        self.poss, self.carrier = side, carrier
        self.possession_log.append((round(self.t, 2), side, carrier.id))

    def positions(self, side: str, in_possession: bool) -> dict[str, tuple[float, float]]:
        """Approximate absolute positions of a side's players from team shape."""
        bf = to_frame(side, *self.ball)
        out = {}
        for p in self.on_pitch[side]:
            fx, fy = shape_position(p.position, self.anchors[p.id], bf, in_possession)
            out[p.id] = to_frame(side, fx, fy)
        return out

    def nearest(self, side: str, point: tuple[float, float], exclude_gk: bool = True) -> tuple[Player, float]:
        pos = self.positions(side, side == self.poss)
        best, best_d = None, 1e9
        for p in self.on_pitch[side]:
            if exclude_gk and p.position == "GK":
                continue
            x, y = pos[p.id]
            d = math.hypot(x - point[0], y - point[1])
            if d < best_d:
                best, best_d = p, d
        return best, best_d

    def keeper(self, side: str) -> Player:
        for p in self.on_pitch[side]:
            if p.position == "GK":
                return p
        return self.on_pitch[side][0]

    # ------------------------------------------------------------------ match flow
    def run(self) -> SimulatedMatch:
        for period in (1, 2):
            self.period = period
            self.period_starts.append(self.t)
            stoppage = self.rng.uniform(60, 180) if period == 1 else self.rng.uniform(180, 330)
            length = HALF + stoppage
            self.emit("period_start", "home", None)
            self.kickoff("home" if period == 1 else "away")
            while self.t - self.period_starts[-1] < length:
                self.maybe_substitute()
                self.maybe_forced_red()
                self.step()
            self.emit("period_end", "home", None)
            self.period_ends.append(self.t)
            self.ball = (52.5, 34.0)
        return SimulatedMatch(
            match_id=self.match_id,
            home=self.home,
            away=self.away,
            seed=self.seed,
            events=self.events,
            possession_log=self.possession_log,
            lineup_log=self.lineup_log,
            period_starts=self.period_starts,
            period_ends=self.period_ends,
            anchors=self.anchors,
            duration=self.t,
        )

    def kickoff(self, side: str) -> None:
        self.ball = (52.5, 34.0)
        st = next((p for p in self.on_pitch[side] if p.position in ("ST", "AM")), self.on_pitch[side][-1])
        self.set_possession(side, st)
        mid = next((p for p in self.on_pitch[side] if p.position in ("DM", "CM")), self.on_pitch[side][5])
        target = to_frame(side, 44, 34 + self.rng.uniform(-8, 8))
        self.do_pass_to(mid, target, "kick_off", pressure=0.0, force_success=True)

    def stoppage(self, lo: float, hi: float) -> None:
        self.t += self.rng.uniform(lo, hi)

    def maybe_substitute(self) -> None:
        if self.period != 2:
            return
        for side in ("home", "away"):
            n = self.subs_made[side]
            if n >= 3 or not self.bench[side] or self.minute() < self.sub_minutes[side][n]:
                continue
            outfield = [p for p in self.on_pitch[side] if p.position != "GK"]
            if not outfield:
                continue
            off = min(outfield, key=lambda p: p.stamina + self.rng.uniform(0, 0.2))
            group = {"CB": "CB", "RB": "CB", "LB": "CB", "DM": "CM", "CM": "CM", "AM": "CM",
                     "RW": "RW", "LW": "RW", "RM": "RW", "LM": "RW", "ST": "ST"}
            pick = next((b for b in self.bench[side] if b.position == group.get(off.position)), None)
            pick = pick or next((b for b in self.bench[side] if b.position != "GK"), None)
            if pick is None:
                continue
            self.bench[side].remove(pick)
            self.on_pitch[side][self.on_pitch[side].index(off)] = pick
            self.anchors[pick.id] = self.anchors[off.id]
            self.subs_made[side] += 1
            self.stoppage(20, 35)
            self.emit("substitution", side, pick, player_off=off.id)
            self.lineup_log.append((round(self.t, 2), side, "off", off.id))
            self.lineup_log.append((round(self.t, 2), side, "on", pick.id))
            if self.carrier.id == off.id:
                self.carrier = pick

    def maybe_forced_red(self) -> None:
        fr = self.forced_red
        if not fr or self.minute() < fr.minute or self.poss == fr.side:
            return
        offender = next((p for p in self.on_pitch[fr.side] if p.position == fr.position), None)
        self.forced_red = None
        if offender is None:
            return
        x, y = self.ball
        self.emit("foul", fr.side, offender, x=x, y=y, fouled=self.carrier.id)
        self.send_off(fr.side, offender, second_yellow=False)
        self.stoppage(40, 70)

    def send_off(self, side: str, p: Player, second_yellow: bool) -> None:
        self.emit("card", side, p, card="red", second_yellow=second_yellow)
        self.on_pitch[side].remove(p)
        self.lineup_log.append((round(self.t, 2), side, "off", p.id))

    # ------------------------------------------------------------------ on-ball step
    def step(self) -> None:
        side, car = self.poss, self.carrier
        if car not in self.on_pitch[side]:  # carrier was subbed or sent off
            self.carrier = car = self.nearest(side, self.ball)[0]
        opp = other(side)
        bx, by = to_frame(side, *self.ball)
        rng = self.rng

        # 1. pressure from the defending side
        press = self.club(opp).press * self.mult(opp, "press")
        p_press = 0.06 + 0.32 * press * (0.55 + 0.45 * (1 - bx / PITCH_L))
        if bx > 88.5 and abs(by - 34) < 20.16:
            p_press += 0.25  # defenders swarm in their own box
        defender, d = self.nearest(opp, self.ball)
        if car.position == "GK":
            p_press *= 0.3
        if rng.random() < p_press:
            pressure = rng.uniform(0.5, 1.0)
            self.t += rng.uniform(0.3, 0.9)
            self.emit("pressure", opp, defender, x=self.ball[0], y=self.ball[1], on_player=car.id)
            # 2. duel: defender may win the ball or foul
            p_win = (0.09 + 0.16 * defender.defending - 0.07 * car.pace) * min(press / 0.6, 1.4)
            if rng.random() < p_win:
                if rng.random() < 0.33:
                    self.foul(opp, defender, car)
                else:
                    self.emit("tackle", opp, defender, x=self.ball[0], y=self.ball[1], outcome="won", on_player=car.id)
                    self.t += rng.uniform(0.6, 1.5)
                    self.set_possession(opp, defender)
                return
        else:
            pressure = rng.uniform(0.0, 0.3)

        # 3. choose an action
        in_box = bx > 88.5 and abs(by - 34) < 20.16
        dist_goal = math.hypot(PITCH_L - bx, 34 - by)
        attack = self.mult(side, "attack")
        p_shot = 0.0
        if in_box:
            p_shot = 0.11 * attack
        elif dist_goal < 30 and abs(by - 34) < 18:
            p_shot = 0.055 * car.shooting * attack
        p_carry = 0.02 if car.position == "GK" else 0.14 + 0.16 * car.pace
        r = rng.random()
        if r < p_shot:
            self.shot(side, car, pressure)
        elif r < p_shot + p_carry:
            self.carry(side, car)
        else:
            self.choose_pass(side, car, pressure)

    def foul(self, side: str, offender: Player, victim: Player) -> None:
        x, y = self.ball
        self.emit("foul", side, offender, x=x, y=y, fouled=victim.id)
        if self.rng.random() < 0.13:
            if offender.id in self.yellows:
                self.send_off(side, offender, second_yellow=True)
            else:
                self.yellows.add(offender.id)
                self.emit("card", side, offender, card="yellow")
        self.stoppage(18, 40)
        # free kick: direct shot if close and central, otherwise a pass
        fside = other(side)
        bx, by = to_frame(fside, x, y)
        taker = max(self.on_pitch[fside], key=lambda p: p.passing)
        self.set_possession(fside, taker)
        if math.hypot(PITCH_L - bx, 34 - by) < 30 and abs(by - 34) < 14 and self.rng.random() < 0.5:
            self.shot(fside, taker, 0.0, set_piece="free_kick")
        else:
            self.choose_pass(fside, taker, 0.0, pass_type="free_kick")

    def carry(self, side: str, car: Player) -> None:
        bx, by = to_frame(side, *self.ball)
        length = self.rng.uniform(4, 14) * (0.7 + 0.6 * car.pace)
        gx, gy = PITCH_L - bx, 34 - by
        n = math.hypot(gx, gy) or 1
        dx = 0.65 * gx / n + 0.35 + self.rng.gauss(0, 0.25)
        dy = 0.65 * gy / n + self.rng.gauss(0, 0.35)
        m = math.hypot(dx, dy) or 1
        ex = clamp(bx + length * dx / m, 1, 104)
        ey = clamp(by + length * dy / m, 1, 67)
        if ex > 92:  # the box is crowded: carries get squeezed out short of goal
            ex = 92 + (ex - 92) * 0.35
        speed = 3.6 + 3.4 * car.pace
        dur = math.hypot(ex - bx, ey - by) / speed
        start = self.ball
        end = to_frame(side, ex, ey)
        self.emit("carry", side, car, x=start[0], y=start[1], end_x=end[0], end_y=end[1], duration=dur)
        self.t += dur
        self.ball = end

    def choose_pass(self, side: str, car: Player, pressure: float, pass_type: str | None = None) -> None:
        rng = self.rng
        club = self.club(side)
        bx, by = to_frame(side, *self.ball)
        pos = self.positions(side, True)
        wide_final_third = bx > 75 and abs(by - 34) > 16
        mates = [p for p in self.on_pitch[side] if p.id != car.id]
        weights = []
        for p in mates:
            mx, my = to_frame(side, *pos[p.id])
            dist = math.hypot(mx - bx, my - by)
            fwd = mx - bx
            w = math.exp(-(((dist - 15) / 13) ** 2)) * (1 + club.directness * max(0.0, fwd) / 15)
            if p.position == "GK":
                w *= 0.25 if bx < 35 else 0.0
            if wide_final_third and mx > 88:
                w *= 3.0
            weights.append(max(w, 1e-4))
        target = rng.choices(mates, weights=weights)[0]
        tx, ty = to_frame(side, *pos[target.id])
        ptype = pass_type or "ground"
        if pass_type is None:
            dist = math.hypot(tx - bx, ty - by)
            if wide_final_third and tx > 88 and rng.random() < 0.6:
                ptype = "cross"
                tx, ty = rng.uniform(92, 100), rng.uniform(26, 42)
            elif bx > 50 and target.position in ("ST", "RW", "LW", "AM") and tx > bx + 8 and rng.random() < 0.18:
                ptype = "through"
                tx = min(tx + rng.uniform(6, 12), 101)
            elif dist > 32:
                ptype = "long"
        tx += rng.gauss(0, 1.5)
        ty += rng.gauss(0, 1.5)
        self.do_pass_to(target, to_frame(side, tx, ty), ptype, pressure)

    def do_pass_to(
        self,
        target: Player,
        end_abs: tuple[float, float],
        ptype: str,
        pressure: float,
        force_success: bool = False,
    ) -> None:
        rng = self.rng
        side, car = self.poss, self.carrier
        start = self.ball
        bx, by = to_frame(side, *start)
        ex, ey = to_frame(side, *end_abs)
        ex, ey = clamp(ex, -2, 107), clamp(ey, -2, 70)
        dist = math.hypot(ex - bx, ey - by)
        diff = pass_difficulty(dist, pressure, ex - bx, ptype)
        ok = force_success or rng.random() < pass_success_probability(diff, car.passing, self.mult(side, "attack"))
        if ptype in ("long", "goal_kick"):
            speed = rng.uniform(17, 22)
        elif ptype in ("cross", "corner"):
            speed = rng.uniform(18, 24)
        elif ptype == "throw_in":
            speed = rng.uniform(8, 11)
        else:
            speed = 8.5 + 0.28 * dist + rng.uniform(-1, 1.5)
        if ok:
            ex, ey = clamp(ex, 1, 104), clamp(ey, 1, 67)
            end = to_frame(side, ex, ey)
            dur = dist / speed
            self.emit("pass", side, car, x=start[0], y=start[1], end_x=end[0], end_y=end[1],
                      duration=dur, outcome="complete", recipient=target.id, pass_type=ptype)
            self.t += dur
            self.ball = end
            self.set_possession(side, target)
            self.t += rng.uniform(0.5, 1.3)
            if ptype in ("cross", "corner") and rng.random() < 0.22:
                self.shot(side, target, rng.uniform(0.4, 0.9), header=True)
            return

        opp = other(side)
        out_of_play = ey < 0 or ey > 68 or ex > 105 or (ptype in ("cross", "long") and rng.random() < 0.25)
        if out_of_play:
            ex2, ey2 = ex, ey
            if 0 <= ey <= 68 and ex <= 105:  # overhit: push it out over the nearest line
                if ex > 90:
                    ex2 = 106
                else:
                    ey2 = -1 if ey < 34 else 69
            end = to_frame(side, ex2, ey2)
            dur = math.hypot(ex2 - bx, ey2 - by) / speed
            self.emit("pass", side, car, x=start[0], y=start[1], end_x=end[0], end_y=end[1],
                      duration=dur, outcome="out", recipient=target.id, pass_type=ptype)
            self.t += dur
            self.ball = end
            if ex2 > 105:
                self.goal_kick(opp)
            else:
                self.throw_in(opp, end)
            return
        frac = rng.uniform(0.55, 0.95)
        ix, iy = bx + (ex - bx) * frac, by + (ey - by) * frac
        point = to_frame(side, clamp(ix, 1, 104), clamp(iy, 1, 67))
        interceptor, _ = self.nearest(opp, point, exclude_gk=False)
        dur = math.hypot(ix - bx, iy - by) / speed
        self.emit("pass", side, car, x=start[0], y=start[1], end_x=point[0], end_y=point[1],
                  duration=dur, outcome="incomplete", recipient=target.id, pass_type=ptype)
        self.t += dur
        self.ball = point
        self.emit("interception", opp, interceptor, x=point[0], y=point[1])
        self.set_possession(opp, interceptor)
        self.t += rng.uniform(0.5, 1.2)

    def throw_in(self, side: str, where: tuple[float, float]) -> None:
        self.stoppage(10, 22)
        x = clamp(where[0], 1, 104)
        y = 0.5 if where[1] < 34 else 67.5
        self.ball = (x, y)
        taker = self.nearest(side, self.ball)[0]
        self.set_possession(side, taker)
        self.emit("throw_in", side, taker, x=x, y=y)
        mates = [p for p in self.on_pitch[side] if p.id != taker.id and p.position != "GK"]
        pos = self.positions(side, True)
        target = min(mates, key=lambda p: math.hypot(pos[p.id][0] - x, pos[p.id][1] - y) + self.rng.uniform(0, 8))
        self.do_pass_to(target, pos[target.id], "throw_in", 0.2)

    def goal_kick(self, side: str) -> None:
        self.stoppage(15, 28)
        gk = self.keeper(side)
        self.ball = to_frame(side, 5.5, 34 + self.rng.uniform(-6, 6))
        self.set_possession(side, gk)
        self.emit("goal_kick", side, gk, x=self.ball[0], y=self.ball[1])
        self.choose_pass(side, gk, 0.0, pass_type="goal_kick" if self.rng.random() < 0.5 else None)

    def corner(self, side: str) -> None:
        self.stoppage(18, 32)
        cy = 0.5 if self.rng.random() < 0.5 else 67.5
        self.ball = to_frame(side, 104.5, cy)
        taker = max((p for p in self.on_pitch[side] if p.position != "GK"), key=lambda p: p.passing)
        self.set_possession(side, taker)
        self.emit("corner", side, taker, x=self.ball[0], y=self.ball[1])
        mates = [p for p in self.on_pitch[side] if p.position in ("CB", "ST", "AM", "CM", "DM") and p.id != taker.id]
        target = self.rng.choice(mates or [p for p in self.on_pitch[side] if p.id != taker.id])
        spot = to_frame(side, self.rng.uniform(93, 101), self.rng.uniform(28, 40))
        self.do_pass_to(target, spot, "corner", 0.6)

    def shot(self, side: str, shooter: Player, pressure: float, header: bool = False, set_piece: str | None = None) -> None:
        rng = self.rng
        bx, by = to_frame(side, *self.ball)
        xg = expected_goals(bx, by, header=header)
        dist = math.hypot(PITCH_L - bx, 34 - by)
        if header:
            speed_kmh = clamp(rng.gauss(55, 8), 35, 75)
        else:
            speed_kmh = clamp(rng.gauss(68 + 42 * shooter.shooting - 0.3 * dist, 9), 45, 128)
        attack = self.mult(side, "attack")
        p_goal = xg * (0.75 + 0.45 * shooter.shooting) * attack * (1 - 0.3 * pressure)
        p_block = 0.0 if set_piece else 0.22
        r = rng.random()
        opp = other(side)
        if r < p_goal:
            outcome = "goal"
            end = (PITCH_L, clamp(34 + rng.gauss(0, 2.2), 30.5, 37.5))
        elif r < p_goal + p_block:
            outcome = "blocked"
            end = (bx + rng.uniform(1.5, 4), by + rng.uniform(-2, 2))
        elif r < p_goal + p_block + 0.34:
            outcome = "saved"
            end = (PITCH_L - 0.5, clamp(34 + rng.gauss(0, 2.5), 31, 37))
        elif r < p_goal + p_block + 0.37:
            outcome = "post"
            end = (PITCH_L, 34 + rng.choice([-3.66, 3.66]))
        else:
            outcome = "off_target"
            end = (PITCH_L + 1, 34 + rng.choice([-1, 1]) * rng.uniform(4.5, 12))
        start = self.ball
        end_abs = to_frame(side, *end)
        travel = math.hypot(end[0] - bx, end[1] - by)
        dur = travel / (speed_kmh / 3.6)
        self.emit("shot", side, shooter, x=start[0], y=start[1], end_x=end_abs[0], end_y=end_abs[1],
                  duration=dur, outcome=outcome, body_part="head" if header else "foot",
                  set_piece=set_piece)
        self.t += dur
        self.ball = end_abs
        if outcome == "goal":
            self.stoppage(45, 75)
            self.kickoff(opp)
        elif outcome == "saved":
            gk = self.keeper(opp)
            r2 = rng.random()
            if r2 < 0.5:
                self.ball = to_frame(opp, 4, 34)
                self.emit("save", opp, gk, x=self.ball[0], y=self.ball[1], outcome="caught", shot_by=shooter.id)
                self.set_possession(opp, gk)
                self.t += rng.uniform(4, 9)
            elif r2 < 0.85:
                self.emit("save", opp, gk, x=self.ball[0], y=self.ball[1], outcome="parried_out", shot_by=shooter.id)
                self.corner(side)
            else:
                self.emit("save", opp, gk, x=self.ball[0], y=self.ball[1], outcome="parried", shot_by=shooter.id)
                self.loose_ball(side)
        elif outcome == "blocked":
            if rng.random() < 0.35:
                self.corner(side)
            else:
                self.loose_ball(side)
        elif outcome == "post":
            self.loose_ball(side)
        else:
            self.goal_kick(opp)

    def loose_ball(self, attacking_side: str) -> None:
        bx, by = to_frame(attacking_side, *self.ball)
        spot = to_frame(attacking_side, clamp(bx - self.rng.uniform(4, 12), 60, 100), clamp(by + self.rng.gauss(0, 6), 10, 58))
        self.ball = spot
        self.t += self.rng.uniform(1.0, 2.0)
        winner_side = attacking_side if self.rng.random() < 0.45 else other(attacking_side)
        p, _ = self.nearest(winner_side, spot)
        self.emit("recovery", winner_side, p, x=spot[0], y=spot[1])
        self.set_possession(winner_side, p)
