"""Stage 5, Personalise: the same intelligence as genuinely different experiences.

A viewer profile decides which overlays reach the screen, how urgent they are,
and how they are worded (persona + language + favourite club framing).

Modes:
    analyst  dense: every card, index alerts, stat panels, technical wording
    casual   only the big moments, plain-language "why it mattered"
    player   follow one player: their sprints, passes, shots, distance
    metric   one number the viewer cares about (speed, pass_difficulty,
             pressure, xg, distance) plus the goals
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .explain import NameContext, compose, compose_recap, stat_rows

MODES = ("analyst", "casual", "player", "metric")
METRICS = ("speed", "pass_difficulty", "pressure", "xg", "distance")
ALWAYS_TICKER = {"tk_goal", "tk_red", "tk_half_time", "tk_full_time", "tk_kickoff", "tk_second_half"}


@dataclass
class Profile:
    mode: str = "casual"
    language: str = "en"
    club: str | None = None      # club short code, e.g. "NBR"
    player: str | None = None    # player id, e.g. "NBR-9"
    metric: str | None = "speed"
    label: str | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> "Profile":
        d = d or {}
        p = cls(**{k: d.get(k) for k in ("mode", "language", "club", "player", "metric", "label") if d.get(k) is not None})
        if p.mode not in MODES:
            p.mode = "casual"
        if p.metric not in METRICS:
            p.metric = "speed"
        return p

    def to_dict(self) -> dict:
        return asdict(self)


def select(ov: dict, profile: Profile) -> int | None:
    """Return the overlay's priority for this viewer, or None to drop it."""
    kind, otype = ov["kind"], ov["type"]
    m = ov["metrics"]
    fav = profile.club and ov["team"] == profile.club
    mine = profile.player and profile.player in ov["players"]
    code = None
    if otype == "ticker":
        code = ov.get("code")
    prio = ov["priority"]

    if profile.mode == "analyst":
        keep = kind not in ("sprint", "distance") or (kind == "distance" and m.get("km", 0) >= 10)
    elif profile.mode == "casual":
        keep = (
            otype in ("key_moment", "recap")
            or (otype == "index_alert" and profile.club and ov["team"] is not None)
            or kind == "top_speed"
            or (kind == "difficult_pass" and m.get("difficulty", 0) >= 0.7)
            or (kind == "shot" and (m.get("outcome") in ("saved", "post") and (fav or m.get("speed_kmh", 0) >= 100)))
            or (otype == "ticker" and (code in ALWAYS_TICKER or (fav and code in ("tk_sub", "tk_yellow", "tk_saved", "tk_post"))))
        )
    elif profile.mode == "player":
        keep = (
            mine
            or kind in ("goal", "red_card", "recap")
            or (otype == "ticker" and code in ALWAYS_TICKER)
        )
        if kind == "sprint" and not mine:
            keep = False
    else:  # metric
        keep = (
            profile.metric in ov["metric_tags"]
            or kind in ("goal", "recap")
            or (otype == "ticker" and code in ALWAYS_TICKER)
        )
        if kind == "sprint":
            keep = profile.metric == "speed" and m.get("speed_kmh", 0) >= 31
        if kind == "distance":
            keep = profile.metric == "distance" and m.get("km", 0) >= 9
        if kind == "shot" and profile.metric == "speed":
            keep = m.get("speed_kmh", 0) >= 90
    if not keep:
        return None
    if fav:
        prio += 1
    if mine:
        prio += 2
    return min(prio, 5)


def personalize(ov: dict, ins: dict, profile: Profile, ctx: NameContext, insight_lookup=None) -> dict | None:
    if ov["type"] == "ticker":
        ov = {**ov, "code": ins["facts"].get("code")}
    prio = select(ov, profile)
    if prio is None:
        return None
    if ins["kind"] == "recap":
        turning = None
        tid = ins["facts"].get("turning_point")
        if tid and insight_lookup and tid in insight_lookup:
            ti = insight_lookup[tid]
            tt = compose(ti, profile, ctx)
            turning = f"{tt['headline']} ({ti['minute']})."
        text = compose_recap(ins, profile, ctx, profile.language, turning)
    else:
        text = compose(ins, profile, ctx)
    out = {**ov, "priority": prio, "text": text}
    if ins["kind"] == "stat_panel":
        out["rows"] = stat_rows(ins["facts"]["stats"], profile.language)
    if ins["kind"] == "recap":
        out["rows"] = stat_rows(ins["facts"]["stats"], profile.language)
    return out
