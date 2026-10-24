"""Command-line tools for the synthetic dataset and for reviewing narration.

    python cli.py scenarios
    python cli.py export --scenario all --out ../data [--tracking]
    python cli.py generate --home NBR --away KSU --seed 7 --out ../data
    python cli.py report --scenario comeback --mode casual --lang es [--club RVA] [--player RVA-10]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from footie.pipeline.personalize import Profile
from footie.pipeline.runner import MatchSession
from footie.sim.scenarios import SCENARIOS, load_match
from footie.sim.simulator import MatchEngine, SimulatedMatch
from footie.sim.teams import CLUBS
from footie.sim.tracking import build_tracking


def export_match(m: SimulatedMatch, out: Path, tracking: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "metadata.json").write_text(json.dumps(m.metadata(), indent=2), encoding="utf-8")
    with (out / "events.jsonl").open("w", encoding="utf-8") as fh:
        for e in m.events:
            fh.write(json.dumps(e) + "\n")
    session = MatchSession(m)
    session.run_to_end()
    with (out / "insights.jsonl").open("w", encoding="utf-8") as fh:
        for ins in session.insights.values():
            fh.write(json.dumps(ins) + "\n")
    with (out / "overlays.jsonl").open("w", encoding="utf-8") as fh:
        for ov in session.overlays:
            fh.write(json.dumps(ov) + "\n")
    if tracking and m.tracking is not None:
        tr = m.tracking
        with (out / "tracking.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["t", "entity", "x", "y"])
            for i in range(tr.n):
                f = tr.frame(i)
                w.writerow([f"{f['t']:.1f}", "ball", f"{f['ball'][0]:.2f}", f"{f['ball'][1]:.2f}"])
                for pid, x, y in f["players"]:
                    w.writerow([f"{f['t']:.1f}", pid, f"{x:.2f}", f"{y:.2f}"])
    h, a = m.final_score()
    print(f"{m.match_id}: {m.home.name} {h}-{a} {m.away.name} -> {out}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scenarios")
    ex = sub.add_parser("export")
    ex.add_argument("--scenario", default="all")
    ex.add_argument("--out", default="../data")
    ex.add_argument("--tracking", action="store_true", help="also write 5 Hz tracking.csv (~20 MB per match)")
    gen = sub.add_parser("generate")
    gen.add_argument("--home", required=True, choices=sorted(CLUBS))
    gen.add_argument("--away", required=True, choices=sorted(CLUBS))
    gen.add_argument("--seed", type=int, default=1)
    gen.add_argument("--out", default="../data")
    gen.add_argument("--tracking", action="store_true")
    rp = sub.add_parser("report")
    rp.add_argument("--scenario", default="comeback")
    rp.add_argument("--mode", default="analyst")
    rp.add_argument("--lang", default="en")
    rp.add_argument("--club")
    rp.add_argument("--player")
    rp.add_argument("--metric", default="speed")
    rp.add_argument("--all", action="store_true", help="include non-key overlays")
    args = ap.parse_args(argv)

    if args.cmd == "scenarios":
        for s in SCENARIOS.values():
            print(f"{s.id:10} {s.title:14} {s.description}")
    elif args.cmd == "export":
        ids = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
        for sid in ids:
            export_match(load_match(sid), Path(args.out) / sid, args.tracking)
    elif args.cmd == "generate":
        if args.home == args.away:
            sys.exit("home and away must differ")
        m = MatchEngine(f"{args.home}-{args.away}-{args.seed}", CLUBS[args.home], CLUBS[args.away], args.seed).run()
        m.tracking = build_tracking(m)
        export_match(m, Path(args.out) / m.match_id, args.tracking)
    elif args.cmd == "report":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        m = load_match(args.scenario)
        session = MatchSession(m)
        session.run_to_end()
        prof = Profile(mode=args.mode, language=args.lang, club=args.club, player=args.player, metric=args.metric)
        print(f"# {m.home.name} v {m.away.name} · mode={prof.mode} lang={prof.language} club={prof.club} player={prof.player}\n")
        for ov in session.overlays:
            ins = session.insights[ov["insight_id"]]
            if not args.all and not ins["key"] and ov["type"] not in ("ticker",):
                continue
            p = session.personalize(ov, prof)
            if not p:
                continue
            t = p["text"]
            if p["type"] == "ticker":
                print(f"{p['minute']:>7}  {t['headline']}")
                continue
            print(f"\n{p['minute']:>7}  [{p['type']}] {t['headline']}  {t.get('sub', '')}")
            if t.get("body"):
                print(f"         {t['body']}")
            for w in t.get("why", []):
                print(f"         · {w}")


if __name__ == "__main__":
    main()
