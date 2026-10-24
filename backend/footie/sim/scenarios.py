"""Scripted demo scenarios.

A scenario pairs two clubs with a script of strength multipliers and a story
predicate. We search seeds until the stochastic engine produces a match that
tells the intended story, so the demo always has drama in the right place.
Seed search is deterministic, so a scenario always yields the same match.
"""
from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .simulator import ForcedRedCard, MatchEngine, ScriptPhase, SimulatedMatch
from .teams import CLUBS
from .tracking import build_tracking


def _goals(m: SimulatedMatch) -> list[dict]:
    return [e for e in m.events if e["type"] == "shot" and e["outcome"] == "goal"]


def _comeback(m: SimulatedMatch) -> bool:
    h = a = 0
    led_by_two = False
    for g in _goals(m):
        if g["side"] == "home":
            h += 1
        else:
            a += 1
        if h - a >= 2 and g["clock"] < 60 * 50:
            led_by_two = True
    return led_by_two and a > h and a + h <= 6


def _red_card(m: SimulatedMatch) -> bool:
    red = next((e for e in m.events if e["type"] == "card" and e.get("card") == "red"), None)
    if not red:
        return False
    h0, a0 = m.score_at(red["t"])
    h, a = m.final_score()
    return h0 >= a0 and (a - a0) >= 2 and a > h


def _derby(m: SimulatedMatch) -> bool:
    h, a = m.final_score()
    goals = _goals(m)
    late = any(g["clock"] > 80 * 60 for g in goals)
    return h >= 1 and a >= 1 and 3 <= h + a <= 5 and late and abs(h - a) <= 1


@dataclass
class Scenario:
    id: str
    title: str
    description: str
    home: str
    away: str
    script: list[ScriptPhase] = field(default_factory=list)
    forced_red: ForcedRedCard | None = None
    predicate: Callable[[SimulatedMatch], bool] = lambda m: True
    seed: int | None = None  # pinned story seed; re-run find_seed() and update after changing the engine

    def summary(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "home": CLUBS[self.home].name,
            "away": CLUBS[self.away].name,
        }


SCENARIOS: dict[str, Scenario] = {
    s.id: s
    for s in [
        Scenario(
            id="comeback",
            title="The Comeback",
            description="Northbridge storm into a two-goal lead, then Riverside's second-half press turns the game.",
            home="NBR",
            away="RVA",
            script=[
                ScriptPhase(0, 42, {"home_attack": 1.5, "away_attack": 0.75, "home_press": 1.2}),
                ScriptPhase(52, 100, {"home_attack": 0.75, "away_attack": 1.55, "away_press": 1.45, "home_press": 0.8}),
            ],
            predicate=_comeback,
            seed=29,
        ),
        Scenario(
            id="red_card",
            title="Ten Men",
            description="Kingsport are holding their own until a red card just before the hour changes everything.",
            home="KSU",
            away="ASH",
            script=[ScriptPhase(60, 100, {"away_attack": 1.3, "away_press": 1.2})],
            forced_red=ForcedRedCard(side="home", minute=57, position="CB"),
            predicate=_red_card,
            seed=1,
        ),
        Scenario(
            id="derby",
            title="Late Drama",
            description="An end-to-end derby between Northbridge and Ashford, settled in the final ten minutes.",
            home="NBR",
            away="ASH",
            script=[ScriptPhase(75, 100, {"home_attack": 1.25, "away_attack": 1.25, "home_press": 1.2, "away_press": 1.2})],
            predicate=_derby,
            seed=12,
        ),
    ]
}


def simulate(scenario_id: str, seed: int) -> SimulatedMatch:
    sc = SCENARIOS[scenario_id]
    engine = MatchEngine(
        match_id=f"{scenario_id}-{seed}",
        home=CLUBS[sc.home],
        away=CLUBS[sc.away],
        seed=seed,
        script=sc.script,
        forced_red=ForcedRedCard(**vars(sc.forced_red)) if sc.forced_red else None,
    )
    return engine.run()


def find_seed(scenario_id: str, max_tries: int = 400) -> int:
    sc = SCENARIOS[scenario_id]
    for seed in range(1, max_tries + 1):
        if sc.predicate(simulate(scenario_id, seed)):
            return seed
    return 1


CACHE_DIR = Path(os.getenv("FOOTIE_CACHE_DIR", Path(__file__).resolve().parents[2] / ".cache"))
CACHE_VERSION = 2  # bump when the engine changes so stale matches are rebuilt


def story_seed(scenario_id: str) -> int:
    sc = SCENARIOS[scenario_id]
    if sc.seed is not None:
        return sc.seed
    marker = CACHE_DIR / f"seed-{scenario_id}-v{CACHE_VERSION}.txt"
    if marker.exists():
        return int(marker.read_text())
    seed = find_seed(scenario_id)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(seed))
    return seed


@lru_cache(maxsize=8)
def load_match(scenario_id: str, seed: int | None = None) -> SimulatedMatch:
    """Simulate a scenario (with its story seed unless given) plus tracking.

    Cached in memory and on disk, since tracking takes a few seconds to build.
    """
    if seed is None:
        seed = story_seed(scenario_id)
    path = CACHE_DIR / f"match-{scenario_id}-{seed}-v{CACHE_VERSION}.pkl"
    if path.exists():
        try:
            with path.open("rb") as fh:
                return pickle.load(fh)
        except Exception:
            path.unlink(missing_ok=True)
    m = simulate(scenario_id, seed)
    m.tracking = build_tracking(m)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump(m, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return m
