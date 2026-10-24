# Overlay contract

The render stage emits a stream of **overlay messages**. Each one tells a graphics engine *what* to show, *where*, *from when* and *for how long*. It carries no styling, so a broadcast graphics partner can draw the same feed our React app draws.

Overlays are delivered over the WebSocket as:

```json
{ "type": "overlay", "viewer": 0, "overlay": { ... } }
```

Raw (unpersonalised) overlays for a whole match are in `data/<scenario>/overlays.jsonl`. Ids are assigned per session, so they differ between runs.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable id, `ov-<insight id>` |
| `insight_id` | string | The interpreted fact this overlay comes from |
| `t` | number | Match time in seconds since kick-off (continuous across halves). **The sync key** with the video feed. |
| `minute` | string | Display label: `"67'"`, `"45+2'"` |
| `type` | enum | `key_moment`, `index_alert`, `player_tag`, `pass_card`, `shot_card`, `stat_panel`, `recap`, `ticker` |
| `kind` | string | The insight kind: `goal`, `big_chance`, `red_card`, `control_shift`, `pressure_surge`, `top_speed`, `sprint`, `distance`, `difficult_pass`, `shot`, `stat_panel`, `recap`, `ticker` |
| `anchor.kind` | enum | `lower_third`, `lower_third_small`, `top_right`, `player`, `side_panel`, `fullscreen`, `ticker` |
| `anchor.player_id` | string | For `player` anchors: track this player's position |
| `ttl` | number | Seconds on screen. `0` means a log line with no graphic. |
| `priority` | 1–5 | 5 = must show. Personalisation raises it for the viewer's club (+1) and focus player (+2). |
| `side`, `team` | string | `home`/`away` and club code, or null |
| `players` | string[] | Player ids involved, main player first |
| `metric_tags` | string[] | `xg`, `speed`, `pass_difficulty`, `pressure`, `control`, `distance`. Used by single-metric mode. |
| `metrics` | object | The numbers behind the graphic: e.g. `xg`, `speed_kmh`, `distance_m`, `difficulty`, `ball_speed_kmh`, `wp_before`, `wp_after`, `index_before`, `index_after` |
| `importance` | 0–1 | Editorial weight |
| `key` | bool | A key moment (goes in the story feed and recaps) |
| `evidence` | int[] | Event ids that back the claim, for audit and replay |
| `text` | object | Added per viewer: `headline`, `sub`, `body`, `why[]`, `source` (`template` or `llm`) |
| `rows` | array | `stat_panel` and `recap` only: localised `[label, home, away]` rows |

## Example

```json
{
  "id": "ov-i483",
  "insight_id": "i483",
  "t": 4118.37,
  "minute": "67'",
  "type": "key_moment",
  "kind": "goal",
  "anchor": { "kind": "lower_third" },
  "ttl": 12,
  "priority": 5,
  "side": "away",
  "team": "RVA",
  "players": ["RVA-11"],
  "metric_tags": ["xg", "speed"],
  "metrics": { "xg": 0.13, "speed_kmh": 92.3, "distance_m": 11.1, "wp_before": 23, "wp_after": 75, "outcome": "goal" },
  "importance": 1.0,
  "key": true,
  "evidence": [1910],
  "text": {
    "headline": "GOAL! P. Dembe",
    "sub": "Northbridge FC 2–3 Riverside Athletic · 67'",
    "body": "xG 0.13 · 92 km/h · 11 m out · 5-pass move",
    "why": ["It puts Riverside Athletic ahead.", "Riverside Athletic's chance of winning moved from 23% to 75%.", "It's P. Dembe's second goal of the match."],
    "source": "template"
  }
}
```

## Rendering rules our app follows

- At most one `lower_third` at a time (highest priority, then newest). Small cards only show when no lower third is up.
- `player` anchors follow the tracked player position every frame.
- `ttl` counts screen time, so overlays stay readable when playback runs faster than real time.
- When the LLM upgrades the text, an `overlay_text` message with the same `id` replaces `text` in place.
