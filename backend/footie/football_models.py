"""Small, explainable football models shared by the simulator and the analytics.

Every model here is a closed-form formula on purpose: the explain stage can say
exactly which inputs drove a number, and the simulator uses the same formulas so
the synthetic data and the analytics agree with each other.

Coordinates are metres on a 105 x 68 pitch, in the *attacking frame* of the team
in possession (they attack towards x = 105, goal centre at y = 34).
"""
from __future__ import annotations

import math

PITCH_L = 105.0
PITCH_W = 68.0
GOAL_Y = 34.0
GOAL_WIDTH = 7.32
SPRINT_MS = 7.0  # 25.2 km/h, the usual broadcast sprint threshold


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def shot_geometry(x: float, y: float) -> tuple[float, float]:
    """Distance to goal centre and the angle (radians) the goal mouth subtends."""
    dx = max(PITCH_L - x, 0.1)
    dy = abs(y - GOAL_Y)
    dist = math.hypot(dx, dy)
    half = GOAL_WIDTH / 2
    angle = math.atan2(GOAL_WIDTH * dx, dx * dx + dy * dy - half * half)
    if angle < 0:
        angle += math.pi
    return dist, angle


def expected_goals(x: float, y: float, header: bool = False) -> float:
    """Logistic xG on distance and goal angle. ~0.04 from 20 m, ~0.15 from the penalty spot."""
    dist, angle = shot_geometry(x, y)
    z = -1.75 - 0.10 * dist + 1.55 * angle
    if header:
        z -= 0.9
    return clamp(sigmoid(z), 0.01, 0.95)


PASS_TYPE_BONUS = {
    "ground": 0.0,
    "long": 0.4,
    "through": 0.9,
    "cross": 1.0,
    "corner": 1.1,
    "free_kick": 0.3,
    "throw_in": -0.4,
    "goal_kick": 0.2,
    "kick_off": -1.5,
}


def pass_difficulty(distance: float, pressure: float, progress: float, pass_type: str) -> float:
    """0..1 rating of how hard a pass is, before knowing if it worked.

    distance: metres. pressure: 0 (free) to 1 (defender on top of the passer).
    progress: metres gained towards the opponent goal (negative for back passes).
    """
    z = (
        -3.0
        + 0.055 * distance
        + 1.6 * pressure
        + 0.02 * max(0.0, progress)
        + PASS_TYPE_BONUS.get(pass_type, 0.0)
    )
    return clamp(sigmoid(z), 0.01, 0.99)


def pass_success_probability(difficulty: float, passer_skill: float, attack_mult: float = 1.0) -> float:
    fail = difficulty * (1.25 - 0.5 * passer_skill) / max(attack_mult, 0.2)
    return clamp(1.0 - fail, 0.02, 0.99)


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def win_probability(
    goals_home: int,
    goals_away: int,
    rate_home: float,
    rate_away: float,
    minutes_left: float,
) -> tuple[float, float, float]:
    """Home / draw / away probabilities from independent Poisson scoring.

    rate_* are expected goals per 90 minutes for the rest of the match.
    """
    minutes_left = max(minutes_left, 0.0)
    lh = rate_home * minutes_left / 90.0
    la = rate_away * minutes_left / 90.0
    ph = [_poisson(k, lh) for k in range(11)]
    pa = [_poisson(k, la) for k in range(11)]
    home = draw = away = 0.0
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            diff = goals_home + i - (goals_away + j)
            p = pi * pj
            if diff > 0:
                home += p
            elif diff == 0:
                draw += p
            else:
                away += p
    total = home + draw + away
    return home / total, draw / total, away / total
