"""Fictional clubs and squads. No real clubs or players are represented."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

# Formation anchors in the team's attacking frame (own goal at x=0, attacking x=105).
# Facing +x, the left flank is high y.
FORMATIONS: dict[str, list[tuple[str, float, float]]] = {
    "4-3-3": [
        ("GK", 5, 34), ("RB", 30, 8), ("CB", 22, 24), ("CB", 22, 44), ("LB", 30, 60),
        ("DM", 40, 34), ("CM", 50, 20), ("CM", 50, 48),
        ("RW", 70, 9), ("ST", 76, 34), ("LW", 70, 59),
    ],
    "4-2-3-1": [
        ("GK", 5, 34), ("RB", 30, 8), ("CB", 22, 24), ("CB", 22, 44), ("LB", 30, 60),
        ("DM", 40, 26), ("DM", 40, 42),
        ("RW", 63, 10), ("AM", 60, 34), ("LW", 63, 58), ("ST", 76, 34),
    ],
    "4-4-2": [
        ("GK", 5, 34), ("RB", 30, 8), ("CB", 22, 24), ("CB", 22, 44), ("LB", 30, 60),
        ("RM", 55, 10), ("CM", 46, 26), ("CM", 46, 42), ("LM", 55, 58),
        ("ST", 73, 28), ("ST", 73, 40),
    ],
}

BENCH_POSITIONS = ["GK", "CB", "CM", "RW", "ST"]

FIRST_NAMES = [
    "Tomas", "Kwame", "Luca", "Mateo", "Idris", "Ollie", "Rafael", "Jonah", "Sami", "Theo",
    "Kofi", "Andre", "Emil", "Yusuf", "Callum", "Dani", "Marek", "Nico", "Ezra", "Felix",
    "Joel", "Amadou", "Kai", "Bruno", "Leon", "Ciaran", "Hugo", "Tariq", "Elias", "Malik",
    "Arlo", "Diego", "Femi", "Jakub", "Rory", "Silas", "Wilf", "Zane", "Oskar", "Ruben",
    "Ibrahim", "Kenji", "Moses", "Pavel", "Reece", "Stefan", "Tobi", "Viktor", "Wes", "Ade",
]
LAST_NAMES = [
    "Okafor", "Brennan", "Delacroix", "Varga", "Mensah", "Whitlock", "Santoro", "Haldane",
    "Kowal", "Achterberg", "Osei", "Lindqvist", "Marchetti", "Doherty", "Ferreira", "Nakamura",
    "Abara", "Castell", "Holloway", "Petrov", "Quaye", "Rinaldi", "Strand", "Tembo", "Ulrich",
    "Vance", "Wren", "Yildiz", "Zubiri", "Ashworth", "Bakari", "Corrigan", "Duval", "Eze",
    "Fontaine", "Gallo", "Hartley", "Ibsen", "Juma", "Kariuki", "Lowry", "Mwangi", "Navarro",
    "Ogunleye", "Pellegrini", "Rasmussen", "Sterling-Hope", "Thorne", "Valdez", "Whitfield",
    "Achebe", "Barros", "Coulter", "Dembe", "Esposito", "Fairbairn", "Garnier", "Hakimi-Roe",
]


@dataclass
class Player:
    id: str
    name: str
    short: str
    number: int
    position: str
    pace: float
    passing: float
    shooting: float
    defending: float
    stamina: float
    star: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Club:
    id: str
    name: str
    short: str
    primary: str
    secondary: str
    formation: str
    press: float       # 0..1 how aggressively they press
    directness: float  # 0..1 preference for forward / long passing
    strength: float    # 0..1 overall quality, drives pre-match win probability
    players: list[Player] = field(default_factory=list)

    @property
    def starters(self) -> list[Player]:
        return self.players[:11]

    @property
    def bench(self) -> list[Player]:
        return self.players[11:]

    def player(self, pid: str) -> Player:
        for p in self.players:
            if p.id == pid:
                return p
        raise KeyError(pid)

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k != "players"}
        d["players"] = [p.to_dict() for p in self.players]
        return d


POSITION_PROFILE = {
    # pace, passing, shooting, defending
    "GK": (0.35, 0.55, 0.10, 0.80),
    "CB": (0.55, 0.60, 0.25, 0.85),
    "RB": (0.80, 0.65, 0.35, 0.70),
    "LB": (0.80, 0.65, 0.35, 0.70),
    "DM": (0.60, 0.80, 0.45, 0.75),
    "CM": (0.65, 0.82, 0.55, 0.60),
    "AM": (0.72, 0.85, 0.72, 0.40),
    "RM": (0.80, 0.72, 0.60, 0.50),
    "LM": (0.80, 0.72, 0.60, 0.50),
    "RW": (0.88, 0.74, 0.70, 0.35),
    "LW": (0.88, 0.74, 0.70, 0.35),
    "ST": (0.80, 0.68, 0.85, 0.30),
}


def _build_squad(club: Club, star_position: str) -> None:
    rng = random.Random(club.id)
    used: set[str] = set()
    positions = [p for p, _, _ in FORMATIONS[club.formation]] + BENCH_POSITIONS
    numbers = iter([1, 2, 5, 6, 3, 4, 8, 10, 7, 9, 11, 13, 15, 16, 17, 19])
    star_done = False
    for pos in positions:
        while True:
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            if last not in used:
                used.add(last)
                break
        base = POSITION_PROFILE[pos]
        q = club.strength

        def attr(b: float) -> float:
            return round(max(0.2, min(0.98, b * (0.8 + 0.35 * q) + rng.gauss(0, 0.05))), 2)

        num = next(numbers)
        star = not star_done and pos == star_position
        p = Player(
            id=f"{club.short}-{num}",
            name=f"{first} {last}",
            short=f"{first[0]}. {last}",
            number=num,
            position=pos,
            pace=attr(base[0]),
            passing=attr(base[1]),
            shooting=attr(base[2]),
            defending=attr(base[3]),
            stamina=round(rng.uniform(0.55, 0.95), 2),
            star=star,
        )
        if star:
            star_done = True
            p.pace = min(0.98, p.pace + 0.08)
            p.shooting = min(0.98, p.shooting + 0.1)
            p.passing = min(0.98, p.passing + 0.06)
        club.players.append(p)


def _club(cid, name, short, primary, secondary, formation, press, directness, strength, star):
    c = Club(cid, name, short, primary, secondary, formation, press, directness, strength)
    _build_squad(c, star)
    return c


CLUBS: dict[str, Club] = {
    c.short: c
    for c in [
        _club("northbridge", "Northbridge FC", "NBR", "#1b3a8f", "#8fd3ff", "4-3-3", 0.78, 0.35, 0.64, "ST"),
        _club("riverside", "Riverside Athletic", "RVA", "#c8202f", "#ffffff", "4-2-3-1", 0.55, 0.50, 0.60, "AM"),
        _club("kingsport", "Kingsport United", "KSU", "#f2a900", "#1a1a1a", "4-4-2", 0.42, 0.72, 0.52, "ST"),
        _club("ashford", "Ashford Rovers", "ASH", "#127a4a", "#f4f4f4", "4-3-3", 0.62, 0.45, 0.57, "LW"),
    ]
}
