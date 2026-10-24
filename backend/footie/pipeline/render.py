"""Stage 4, Render: turn insights into a timed, machine-readable overlay feed.

An overlay says *what graphic to show, where, from when, and for how long*.
It deliberately carries no styling: any graphics engine (our web renderer, or
a broadcast partner's) can draw it in sync with the match clock.

Overlay contract (see docs/overlay-contract.md):
    id, insight_id   stable ids
    t                match time in seconds (sync key with the video feed)
    minute           display label, e.g. "67'" or "45+2'"
    type             key_moment | index_alert | player_tag | pass_card |
                     shot_card | stat_panel | recap | ticker
    anchor           {"kind": "lower_third" | "lower_third_small" | "top_right" |
                      "player" | "side_panel" | "fullscreen" | "ticker",
                      "player_id": "<id>" (player anchors only)}
    ttl              seconds on screen (0 = log line, no graphic)
    priority         1 (low) .. 5 (must show); personalisation adjusts it
    side, team, players, metric_tags, metrics, importance, key
    text             filled per viewer by the personalise stage
"""
from __future__ import annotations

# kind -> (overlay type, anchor kind, ttl seconds, base priority, metric tags)
OVERLAY_SPEC: dict[str, tuple[str, str, float, int, list[str]]] = {
    "goal": ("key_moment", "lower_third", 12, 5, ["xg", "speed"]),
    "big_chance": ("key_moment", "lower_third", 9, 4, ["xg"]),
    "red_card": ("key_moment", "lower_third", 10, 4, []),
    "control_shift": ("index_alert", "top_right", 10, 3, ["control", "pressure"]),
    "pressure_surge": ("index_alert", "top_right", 10, 3, ["pressure"]),
    "top_speed": ("player_tag", "player", 5, 3, ["speed"]),
    "sprint": ("player_tag", "player", 3, 1, ["speed"]),
    "distance": ("player_tag", "player", 4, 1, ["distance"]),
    "difficult_pass": ("pass_card", "lower_third_small", 5, 2, ["pass_difficulty"]),
    "shot": ("shot_card", "lower_third_small", 6, 2, ["speed", "xg"]),
    "stat_panel": ("stat_panel", "side_panel", 10, 2, []),
    "recap": ("recap", "fullscreen", 25, 5, []),
    "ticker": ("ticker", "ticker", 0, 1, []),
}

METRIC_FIELDS = (
    "xg", "speed_kmh", "distance_m", "difficulty", "ball_speed_kmh", "km", "index_before", "index_after",
    "pressures_pm", "high_regains", "wp_before", "wp_after", "outcome", "turnovers_pm", "completion_pct",
)


def to_overlay(ins: dict) -> dict:
    otype, anchor, ttl, priority, tags = OVERLAY_SPEC[ins["kind"]]
    anchor_obj = {"kind": anchor}
    if anchor == "player" and ins["players"]:
        anchor_obj["player_id"] = ins["players"][0]
    f = ins["facts"]
    return {
        "id": f"ov-{ins['id']}",
        "insight_id": ins["id"],
        "t": ins["t"],
        "minute": ins["minute"],
        "type": otype,
        "kind": ins["kind"],
        "anchor": anchor_obj,
        "ttl": ttl,
        "priority": priority,
        "side": ins["side"],
        "team": ins["team"],
        "players": ins["players"],
        "metric_tags": tags,
        "metrics": {k: f[k] for k in METRIC_FIELDS if k in f},
        "importance": ins["importance"],
        "key": ins["key"],
        "evidence": ins["evidence"],
    }
