"""Sanity tests: the synthetic data looks like football, and every stage produces output."""
import math

import pytest

from footie.football_models import expected_goals, pass_difficulty, win_probability
from footie.pipeline.personalize import Profile
from footie.pipeline.runner import MatchSession
from footie.sim.scenarios import SCENARIOS, load_match, simulate


def test_models_are_sane():
    assert expected_goals(99, 34) > expected_goals(85, 34) > expected_goals(80, 10)
    assert pass_difficulty(40, 0.9, 30, "through") > pass_difficulty(8, 0.0, 0, "ground")
    h, d, a = win_probability(1, 0, 1.4, 1.4, 5)
    assert h > 0.8 and math.isclose(h + d + a, 1.0, abs_tol=1e-9)


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_engine_produces_realistic_volumes(seed):
    m = simulate("derby", seed)
    passes = [e for e in m.events if e["type"] == "pass"]
    shots = [e for e in m.events if e["type"] == "shot"]
    completion = sum(e["outcome"] == "complete" for e in passes) / len(passes)
    assert 900 < len(passes) < 1800
    assert 0.7 < completion < 0.9
    assert 12 < len(shots) < 50
    assert sum(m.final_score()) <= 9
    assert [e["t"] for e in m.events] == sorted(e["t"] for e in m.events)


def test_engine_is_deterministic():
    a, b = simulate("comeback", 5), simulate("comeback", 5)
    assert a.events == b.events


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_scenarios_tell_their_story(sid):
    assert SCENARIOS[sid].predicate(load_match(sid))


@pytest.fixture(scope="module")
def session():
    s = MatchSession(load_match("comeback"))
    s.run_to_end()
    return s


def test_tracking_is_physically_plausible(session):
    players = session.state()["players"]
    starters = [p for p in players.values() if p["minutes"] >= 85 and p["id"].split("-")[1] != "1"]
    assert starters
    for p in starters:
        assert 6.0 < p["distance_km"] < 15.0, p
        assert 20.0 < p["top_speed_kmh"] < 37.0, p


def test_pipeline_emits_every_stage(session):
    kinds = {i["kind"] for i in session.insights.values()}
    assert {"goal", "shot", "recap", "ticker", "difficult_pass"} <= kinds
    goals = [i for i in session.insights.values() if i["kind"] == "goal"]
    assert len(goals) == sum(session.match.final_score())
    for ov in session.overlays:
        assert ov["t"] >= 0 and ov["type"] and ov["anchor"]["kind"]


def test_personalisation_differs(session):
    analyst = Profile(mode="analyst")
    casual = Profile(mode="casual", language="es", club="RVA")
    a = [session.personalize(o, analyst) for o in session.overlays]
    c = [session.personalize(o, casual) for o in session.overlays]
    a, c = [x for x in a if x], [x for x in c if x]
    assert len(a) > 2 * len(c) > 0
    goal = next(x for x in c if x["kind"] == "goal")
    assert goal["text"]["headline"].startswith("¡GOL!")


def test_player_focus_follows_player(session):
    pid = "RVA-10"
    prof = Profile(mode="player", player=pid)
    mine = [session.personalize(o, prof) for o in session.overlays]
    mine = [x for x in mine if x and x["kind"] in ("sprint", "distance", "shot", "difficult_pass")]
    assert mine and all(pid in x["players"] for x in mine)


@pytest.mark.parametrize("lang", ["en", "es", "fr", "sw"])
def test_every_language_renders(session, lang):
    prof = Profile(mode="analyst", language=lang)
    for ov in session.overlays:
        p = session.personalize(ov, prof)
        if p:
            assert "{" not in p["text"]["headline"], p["text"]
            assert "{" not in p["text"].get("body", ""), p["text"]
