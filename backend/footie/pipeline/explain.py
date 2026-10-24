"""Stage 3, Explain: say why a moment matters, not only that it happened.

Two layers:
1. `reasons()` turns an insight's facts into language-neutral reason codes
   (e.g. "came against the run of play", "started with a high regain").
   These are deterministic and auditable: every reason is backed by numbers.
2. `compose()` renders headline / body / reasons for a viewer profile with the
   multilingual templates. `Narrator` optionally upgrades key moments and
   recaps with an LLM (Azure OpenAI in Microsoft Foundry) that is only given
   the facts and reasons, never raw freedom to invent.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ..i18n import LANGUAGES, LLM_ONLY_LANGUAGES, tr
from ..llm import LLMClient

log = logging.getLogger(__name__)

Reason = tuple[str, dict]


@dataclass
class NameContext:
    names: dict[str, str]        # player id -> short name
    full_names: dict[str, str]   # player id -> full name
    clubs: dict[str, str]        # "home"/"away" -> club name
    club_by_short: dict[str, str]
    side_by_short: dict[str, str]

    def player(self, pid: str | None) -> str:
        return self.names.get(pid or "", pid or "?")

    def team(self, side: str | None) -> str:
        return self.clubs.get(side or "", "")

    @classmethod
    def from_match(cls, match) -> "NameContext":
        names, full = {}, {}
        for c in (match.home, match.away):
            for p in c.players:
                names[p.id], full[p.id] = p.short, p.name
        return cls(
            names, full,
            {"home": match.home.name, "away": match.away.name},
            {match.home.short: match.home.name, match.away.short: match.away.name},
            {match.home.short: "home", match.away.short: "away"},
        )


def _opp(side: str) -> str:
    return "away" if side == "home" else "home"


def reasons(ins: dict, ctx: NameContext) -> list[Reason]:
    f, kind, side = ins["facts"], ins["kind"], ins["side"]
    team = ctx.team(side)
    out: list[Reason] = []
    if kind == "goal":
        h0, a0 = f["score_before"]
        hs, as_ = f["score_after"]
        lead = f["lead_before"]
        if h0 == 0 and a0 == 0:
            out.append(("r_opener", {}))
        elif lead == -1:
            out.append(("r_equaliser", {"hs": hs, "as": as_}))
        elif lead == 0:
            out.append(("r_lead", {"team": team}))
        elif lead >= 1:
            out.append(("r_extends", {"team": team, "lead": lead + 1}))
        else:
            out.append(("r_pulls_back", {"team": team}))
        if f.get("opp_momentum", 0) >= 30:
            out.append(("r_against_run", {"opp": ctx.team(_opp(side))}))
        if f.get("high_regain") and f.get("seq_seconds", 99) <= 20:
            out.append(("r_pressure_led", {"secs": f["seq_seconds"]}))
        elif f.get("seq_seconds", 99) <= 15 and f.get("seq_travel_m", 0) >= 40:
            out.append(("r_counter", {"dist": f["seq_travel_m"], "secs": f["seq_seconds"]}))
        if f.get("seq_passes", 0) >= 8:
            out.append(("r_long_seq", {"n": f["seq_passes"]}))
        if f["xg"] < 0.08:
            out.append(("r_low_xg", {"xg": f"{f['xg']:.2f}"}))
        if abs(f["wp_after"] - f["wp_before"]) >= 8:
            out.append(("r_wp", {"team": team, "a": f["wp_before"], "b": f["wp_after"]}))
        if f.get("scorer_goals") == 2:
            out.append(("r_brace", {"player": ctx.player(f["scorer"])}))
        elif f.get("scorer_goals") == 3:
            out.append(("r_hattrick", {"player": ctx.player(f["scorer"])}))
        if f.get("speed_kmh", 0) >= 100:
            out.append(("r_fast_shot", {"speed": round(f["speed_kmh"])}))
        if f.get("minutes_left", 99) <= 10:
            out.append(("r_late", {"left": max(1, f["minutes_left"])}))
    elif kind == "big_chance":
        out.append(("r_high_xg", {"xg": f"{f['xg']:.2f}", "pct": round(100 * f["xg"])}))
        if f.get("minutes_left", 99) <= 10:
            out.append(("r_late", {"left": max(1, f["minutes_left"])}))
    elif kind == "red_card":
        out.append(("r_numbers", {"team": team, "left": f["minutes_left"], "n": f["men_left"]}))
        if abs(f["wp_after"] - f["wp_before"]) >= 3:
            out.append(("r_wp", {"team": team, "a": f["wp_before"], "b": f["wp_after"]}))
    elif kind == "control_shift":
        if f["state"] == "chaos":
            out.append(("r_turnovers", {"to": f["turnovers_pm"]}))
            out.append(("r_completion_down", {"comp": f["completion_pct"]}))
        else:
            out.append(("r_completion_up", {"comp": f["completion_pct"]}))
    elif kind == "pressure_surge":
        out.append(("r_regains", {"hr": f["high_regains"]}))
        if f.get("chasing"):
            out.append(("r_chasing", {"team": team}))
    return out


def _outcome(lang: str, outcome: str) -> str:
    return tr(lang, f"out_{outcome}")


def _fan_prefix(ins: dict, profile, ctx: NameContext) -> str:
    """'Great news for X fans' style framing for the viewer's favourite club."""
    if not profile.club or ins["kind"] not in ("goal", "red_card", "big_chance"):
        return ""
    fav_side = ctx.side_by_short.get(profile.club)
    if not fav_side:
        return ""
    good = (ins["side"] == fav_side) == (ins["kind"] == "goal")
    if ins["kind"] == "big_chance":
        good = ins["side"] != fav_side  # an opponent's miss is good news
    return tr(profile.language, "fan_good" if good else "fan_bad", team=ctx.club_by_short[profile.club])


def compose(ins: dict, profile, ctx: NameContext) -> dict:
    """Template text for one insight and one viewer profile."""
    lang = profile.language if profile.language in LANGUAGES else "en"
    analyst = profile.mode == "analyst"
    f, kind = ins["facts"], ins["kind"]
    team = ctx.team(ins["side"])
    rs = [tr(lang, code, **params) for code, params in reasons(ins, ctx)]
    headline = body = ""
    sub = ""

    if kind == "goal":
        hs, as_ = f["score_after"]
        headline = tr(lang, "goal_h", player=ctx.player(f["scorer"]))
        sub = f"{ctx.team('home')} {hs}–{as_} {ctx.team('away')} · {ins['minute']}"
        body = tr(lang, "goal_b_analyst", xg=f"{f['xg']:.2f}", speed=round(f["speed_kmh"]),
                  dist=round(f["distance_m"]), passes=f["seq_passes"]) if analyst else ""
    elif kind == "big_chance":
        headline = tr(lang, "bigchance_h", player=ctx.player(f["shooter"]))
        sub = f"{team} · {ins['minute']}"
        body = tr(lang, "shot_b_analyst", speed=round(f["speed_kmh"]), xg=f"{f['xg']:.2f}",
                  outcome=_outcome(lang, f["outcome"])) if analyst else ""
    elif kind == "red_card":
        headline = tr(lang, "red_h", player=ctx.player(f["player"]))
        sub = f"{team} · {ins['minute']}"
    elif kind == "control_shift":
        if f["state"] == "chaos":
            headline = tr(lang, "ctrl_chaos_h")
            body = tr(lang, "ctrl_b_chaos_casual")
        else:
            headline = tr(lang, "ctrl_control_h", team=team)
            body = tr(lang, "ctrl_b_control_casual", team=team)
        if analyst:
            body = tr(lang, "ctrl_b_analyst", a=f["index_before"], b=f["index_after"],
                      to=f["turnovers_pm"], comp=f["completion_pct"])
        sub = ins["minute"]
    elif kind == "pressure_surge":
        headline = tr(lang, "press_h", team=team)
        body = (tr(lang, "press_b_analyst", a=f["index_before"], b=f["index_after"], ppm=f["pressures_pm"],
                   hr=f["high_regains"]) if analyst else tr(lang, "press_b_casual", team=team))
        sub = ins["minute"]
    elif kind == "top_speed":
        headline = ctx.player(f["player"])
        body = tr(lang, "speed_record_b", speed=f"{f['speed_kmh']:.1f}")
    elif kind == "sprint":
        headline = ctx.player(f["player"])
        body = tr(lang, "sprint_b", speed=f"{f['speed_kmh']:.1f}")
    elif kind == "distance":
        headline = ctx.player(f["player"])
        body = tr(lang, "distance_b", km=f["km"])
    elif kind == "difficult_pass":
        headline = tr(lang, "pass_h", player=ctx.player(f["passer"]), recipient=ctx.player(f["recipient"]))
        if analyst or profile.mode == "metric":
            body = tr(lang, "pass_b_analyst", dist=round(f["distance_m"]), diff=round(100 * f["difficulty"]),
                      speed=round(f["ball_speed_kmh"]))
        else:
            key = "pass_b_casual_pressed" if f["under_pressure"] else "pass_b_casual"
            body = tr(lang, key, dist=round(f["distance_m"]), recipient=ctx.player(f["recipient"]))
    elif kind == "shot":
        headline = tr(lang, "shot_h", player=ctx.player(f["shooter"]))
        if analyst or profile.mode == "metric":
            body = tr(lang, "shot_b_analyst", speed=round(f["speed_kmh"]), xg=f"{f['xg']:.2f}",
                      outcome=_outcome(lang, f["outcome"]))
        else:
            body = tr(lang, "shot_b_casual", speed=round(f["speed_kmh"]), outcome=_outcome(lang, f["outcome"]))
    elif kind == "ticker":
        params = {k: v for k, v in f.items() if k != "code"}
        if "as_" in params:
            params["as"] = params.pop("as_")
        params.setdefault("hs", "")
        params.setdefault("as", "")
        for k in ("player_in", "player_out"):
            if k in params:
                params[k] = ctx.player(params[k])
        headline = tr(lang, f["code"], player=ctx.player(ins["players"][0] if ins["players"] else None),
                      team=team, home=ctx.team("home"), away=ctx.team("away"), **params)
    elif kind == "stat_panel":
        headline = tr(lang, "stat_h", minute=ins["minute"])
    elif kind == "recap":
        return compose_recap(ins, profile, ctx, lang)

    prefix = _fan_prefix(ins, profile, ctx)
    why = rs if analyst else rs[:2]
    if prefix and profile.mode != "analyst":
        why = [prefix] + why
    return {"headline": headline, "sub": sub, "body": body, "why": why, "source": "template"}


def stat_rows(stats: dict, lang: str) -> list[list]:
    h, a = stats["home"], stats["away"]
    return [
        [tr(lang, "st_poss"), f"{h['possession_pct']}%", f"{a['possession_pct']}%"],
        [tr(lang, "st_shots"), h["shots"], a["shots"]],
        [tr(lang, "st_on_target"), h["on_target"], a["on_target"]],
        [tr(lang, "st_xg"), f"{h['xg']:.2f}", f"{a['xg']:.2f}"],
        [tr(lang, "st_passes"), f"{h['pass_completion_pct']}%", f"{a['pass_completion_pct']}%"],
        [tr(lang, "st_pressures"), h["pressures"], a["pressures"]],
        [tr(lang, "st_distance"), h["distance_km"], a["distance_km"]],
    ]


def compose_recap(ins: dict, profile, ctx: NameContext, lang: str, turning_text: str | None = None) -> dict:
    f = ins["facts"]
    analyst = profile.mode == "analyst"
    hs, as_ = f["score"]
    st = f["stats"]
    home, away = ctx.team("home"), ctx.team("away")
    lines = [tr(lang, "rc_score", home=home, away=away, hs=hs, **{"as": as_})]
    if f["goals"]:
        goals = ", ".join(f"{ctx.player(g['player'])} {g['minute']}" for g in f["goals"])
        lines.append(tr(lang, "rc_goals", list=goals))
    else:
        lines.append(tr(lang, "rc_none"))
    if analyst:
        lines.append(tr(lang, "rc_xg", home=home, away=away, xgh=f"{st['home']['xg']:.2f}", sh=st["home"]["shots"],
                        xga=f"{st['away']['xg']:.2f}", sa=st["away"]["shots"]))
    poss_side = "home" if st["home"]["possession_pct"] >= st["away"]["possession_pct"] else "away"
    lines.append(tr(lang, "rc_poss", team=ctx.team(poss_side), pct=st[poss_side]["possession_pct"]))
    if turning_text:
        lines.append(tr(lang, "rc_turning", text=turning_text))
    star = f["star"]
    detail = []
    if star["goals"]:
        detail.append(tr(lang, "d_goals", n=star["goals"]))
    if star["assists"]:
        detail.append(tr(lang, "d_assists", n=star["assists"]))
    if star.get("pass_accuracy_pct") and not star["goals"]:
        detail.append(tr(lang, "d_passes", pct=star["pass_accuracy_pct"]))
    detail.append(tr(lang, "d_km", km=f"{star['distance_km']:.1f}"))
    lines.append(tr(lang, "rc_star", player=ctx.player(star["id"]), detail=", ".join(detail)))
    if analyst or profile.metric == "speed":
        lines.append(tr(lang, "rc_speed", player=ctx.player(f["fastest"]["player"]), speed=f"{f['fastest']['speed_kmh']:.1f}"))
    if analyst or profile.metric == "distance":
        lines.append(tr(lang, "rc_distance", player=ctx.player(f["most_distance"]["player"]), km=f["most_distance"]["km"]))
    return {
        "headline": tr(lang, "recap_ft_h" if f["final"] else "recap_ht_h"),
        "sub": f"{home} {hs}–{as_} {away}",
        "body": " ".join(lines),
        "why": [],
        "source": "template",
    }


# ---------------------------------------------------------------------- LLM layer
PERSONAS = {
    "analyst": "a data-hungry analyst. Be precise and technical, cite the key numbers (xG, km/h, index values). Up to 45 words in the body.",
    "casual": "a casual fan. Be warm and vivid, use plain words, avoid jargon and acronyms such as xG. Up to 30 words in the body.",
    "player": "a fan following one player ({player}) all match. Centre the text on that player where the facts allow. Up to 35 words.",
    "metric": "a viewer who only cares about one metric ({metric}). Lead with that number. Up to 25 words.",
}

SYSTEM_PROMPT = """You write on-screen graphics text for a live football broadcast.
Rules:
- Use ONLY the facts and reasons provided. Never invent players, numbers, events or history.
- Copy every number exactly as given. Do not round or change it.
- The match is still in progress unless the facts say it has finished. Never say a team has won.
- Explain why the moment matters, not only what happened.
- Write in {language}.
- Audience: {persona}
- {fan}
Return only a JSON object: {{"headline": "<max 8 words>", "body": "<the explanation>"}}"""


def _language_name(code: str) -> str:
    return LANGUAGES.get(code) or LLM_ONLY_LANGUAGES.get(code) or "English"


class Narrator:
    """Optional LLM upgrade for key moments, recaps and Q&A, with caching."""

    LLM_KINDS = {"goal", "big_chance", "red_card", "control_shift", "pressure_surge", "recap"}

    def __init__(self, llm: "LLMClient | bool | None" = None):
        """llm=None reads Foundry settings from the environment; llm=False forces template-only."""
        if llm is None:
            llm = LLMClient.from_env()
        self.llm = llm or None
        self.cache: dict[tuple, dict] = {}

    @property
    def enabled(self) -> bool:
        return self.llm is not None

    def wants(self, ins: dict) -> bool:
        return self.enabled and ins["kind"] in self.LLM_KINDS

    def _system(self, profile, ctx: NameContext) -> str:
        persona = PERSONAS.get(profile.mode, PERSONAS["casual"]).format(
            player=ctx.player(profile.player), metric=profile.metric or "speed")
        club = ctx.club_by_short.get(profile.club, profile.club)
        fan = (f"The viewer is a {club} fan. Say plainly whether this moment is good or bad news for {club}: "
               f"pleased if it helps {club}, sympathetic if it hurts them. Never confuse {club} with the other team."
               if profile.club else "Stay neutral between the two clubs.")
        return SYSTEM_PROMPT.format(language=_language_name(profile.language), persona=persona, fan=fan)

    async def rewrite(self, ins: dict, profile, ctx: NameContext, draft: dict) -> dict | None:
        key = (ins["id"], profile.mode, profile.language, profile.club, profile.player, profile.metric)
        if key in self.cache:
            return self.cache[key]
        en_reasons = [tr("en", c, **p) for c, p in reasons(ins, ctx)]
        payload = {
            "moment": ins["kind"],
            "minute": ins["minute"],
            "home": ctx.team("home"),
            "away": ctx.team("away"),
            "team": ctx.team(ins["side"]) if ins["side"] else None,
            "facts": _readable_facts(ins["facts"], ctx),
            "why_it_matters": en_reasons,
            "draft_in_english": draft if profile.language == "en" else None,
        }
        try:
            out = await self.llm.complete_json(self._system(profile, ctx), json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            log.warning("LLM narration failed for %s: %s", ins["id"], exc)
            return None
        if not out or not out.get("headline"):
            return None
        result = {**draft, "headline": out["headline"], "body": out.get("body", ""), "why": [], "source": "llm"}
        self.cache[key] = result
        return result

    async def answer(self, question: str, context: dict, profile, ctx: NameContext) -> dict:
        if not self.enabled:
            return {"answer": fallback_answer(question, context, ctx), "source": "rules", "cites": []}
        system = (
            "You answer questions about a football match that is in progress, for a broadcast companion app. "
            "Use only the match data provided. If the data does not answer the question, say so. "
            "When you use a key moment, cite its id in square brackets, e.g. [i42]. "
            f"Answer in {_language_name(profile.language)} for {PERSONAS.get(profile.mode, PERSONAS['casual']).format(player=ctx.player(profile.player), metric=profile.metric or 'speed')} "
            'Return JSON: {"answer": "<text>", "cites": ["<insight id>", ...]}'
        )
        user = json.dumps({"question": question, "match": context}, ensure_ascii=False)
        try:
            out = await self.llm.complete_json(system, user, max_tokens=350)
            return {"answer": out.get("answer", ""), "cites": out.get("cites", []), "source": "llm"}
        except Exception as exc:
            log.warning("LLM answer failed: %s", exc)
            return {"answer": fallback_answer(question, context, ctx), "source": "rules", "cites": []}


def _readable_facts(facts: dict, ctx: NameContext) -> dict:
    out = {}
    for k, v in facts.items():
        if k in ("scorer", "shooter", "assist", "player", "passer", "recipient") and isinstance(v, str):
            out[k] = ctx.full_names.get(v, v)
        elif k in ("stats", "star", "key_moments", "opp_momentum", "seq_start", "high_regain", "lead_before"):
            continue
        else:
            out[k] = v
    return out


def fallback_answer(question: str, context: dict, ctx: NameContext) -> str:
    """Rule-based answers so 'Ask the match' works without an LLM."""
    q = question.lower()
    st = context["state"]
    home, away = ctx.team("home"), ctx.team("away")
    score = f"{home} {st['score']['home']}–{st['score']['away']} {away} ({st['minute']})"
    players = context.get("players", {})
    for pid, p in players.items():
        last = ctx.names[pid].split(". ")[-1].lower()
        if last in q:
            return (f"{ctx.full_names[pid]}: {p['goals']} goals, {p['shots']} shots, "
                    f"{p['pass_accuracy_pct'] or 0}% passing, {p['distance_km']} km, top speed {p['top_speed_kmh']} km/h.")
    if "score" in q or "winning" in q:
        return score
    if "possession" in q or "ball" in q:
        s = st["stats"]
        return f"Possession: {home} {s['home']['possession_pct']}%, {away} {s['away']['possession_pct']}%."
    if "fast" in q or "speed" in q:
        top = max(players.values(), key=lambda p: p["top_speed_kmh"])
        return f"Fastest so far: {top['name']} at {top['top_speed_kmh']} km/h."
    if "distance" in q or "run" in q:
        top = max(players.values(), key=lambda p: p["distance_km"])
        return f"Most distance: {top['name']} with {top['distance_km']} km."
    if "xg" in q or "chance" in q:
        s = st["stats"]
        return f"xG: {home} {s['home']['xg']:.2f}, {away} {s['away']['xg']:.2f}."
    if "why" in q and context.get("key_moments"):
        m = context["key_moments"][-1]
        return f"{m['minute']} {m['kind'].replace('_', ' ')}: " + " ".join(m.get("why", []))
    return f"{score}. Ask about the score, possession, xG, speed, distance or a player by name."
