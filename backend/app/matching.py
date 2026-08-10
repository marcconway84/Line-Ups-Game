"""Fuzzy matching of a typed guess against the players in a starting XI.

Football names are awkward to type: they carry diacritics (Piqué, Baroš), apostrophes
(N'Golo Kanté, Eto'o), nobiliary particles (van der Sar, De Bruyne) and plenty of players
go by a single name (Xavi, Cafu). Players also expect a surname on its own to be enough.

The rules applied here, in order:

1. Every candidate player is reduced to a set of accepted keys - the full name, the
   surname (including any leading particles) and any hand-curated aliases.
2. A guess is normalised the same way and compared for an exact key hit.
3. If nothing hits exactly, a bounded edit distance pass forgives small typos.
4. If more than one player in the same XI is matched (e.g. "Charlton" in England 1966),
   the result is reported as ambiguous rather than being resolved arbitrarily.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Sequence

#: Tokens that belong to the surname rather than acting as a separator, so that
#: "Edwin van der Sar" can be answered with "van der Sar".
PARTICLES = frozenset(
    {
        "van", "von", "de", "der", "den", "di", "da", "das", "dos", "del",
        "della", "la", "le", "el", "mac", "mc", "ten", "ter", "bin", "al", "st",
    }
)

#: Characters that survive Unicode decomposition and so need spelling out by hand.
_TRANSLITERATIONS = {
    "ø": "o", "đ": "d", "ð": "d", "ß": "ss", "æ": "ae",
    "œ": "oe", "ł": "l", "þ": "th", "ı": "i",
}

MIN_GUESS_LENGTH = 3


def normalize(text: str | None) -> str:
    """Fold a name down to lowercase ASCII words, e.g. "N'Golo Kanté" -> "ngolo kante"."""
    if not text:
        return ""
    folded = "".join(_TRANSLITERATIONS.get(ch, ch) for ch in str(text).lower())
    # Apostrophes join rather than separate: "Eto'o" is typed "etoo", not "eto o".
    for apostrophe in ("'", "’", "ʼ", "`"):
        folded = folded.replace(apostrophe, "")
    decomposed = unicodedata.normalize("NFD", folded)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    kept = "".join(ch if (ch.isalnum() and ch.isascii()) else " " for ch in stripped)
    return " ".join(kept.split())


def surname_of(name: str) -> str:
    """Return the surname of a name, keeping any nobiliary particles attached."""
    tokens = normalize(name).split()
    if not tokens:
        return ""
    start = len(tokens) - 1
    while start > 0 and tokens[start - 1] in PARTICLES:
        start -= 1
    return " ".join(tokens[start:])


def alias_keys(name: str, accepts: Iterable[str] = ()) -> set[str]:
    """Every normalised string that should be accepted as this player's name."""
    tokens = normalize(name).split()
    keys: set[str] = set()
    if tokens:
        keys.add(" ".join(tokens))  # the full name
        keys.add(surname_of(name))  # surname, particles included
        keys.add(tokens[-1])  # the bare final token ("sar" for van der Sar)
        # Double-barrelled surnames: "Alexander-Arnold" is how people write it, but
        # normalising splits it in two, leaving only "arnold" above.
        last_raw = str(name).split()[-1] if str(name).split() else ""
        if "-" in last_raw:
            keys.add(normalize(last_raw))
    for alias in accepts or ():
        normalized = normalize(alias)
        if normalized:
            keys.add(normalized)
    return {key for key in keys if key}


def edit_distance(a: str, b: str, max_distance: int) -> int:
    """Levenshtein distance, giving up early once it exceeds ``max_distance``."""
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ch_a != ch_b),  # substitution
                )
            )
        if min(current) > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def typo_allowance(key: str) -> int:
    """How many characters of a key a player may get wrong and still be credited."""
    if len(key) >= 10:
        return 2
    if len(key) >= 6:
        return 1
    return 0  # short names such as "Xavi" or "Pelé" must be exact


@dataclass(frozen=True)
class Candidate:
    """A player a guess may be resolved to."""

    slot: int
    name: str
    keys: frozenset[str]

    @classmethod
    def build(cls, slot: int, name: str, accepts: Iterable[str] = ()) -> "Candidate":
        return cls(slot=slot, name=name, keys=frozenset(alias_keys(name, accepts)))


@dataclass(frozen=True)
class MatchResult:
    """Outcome of resolving one typed guess."""

    #: "match", "ambiguous", "no_match", "too_short" or "empty".
    status: str
    slots: tuple[int, ...] = field(default=())
    fuzzy: bool = False

    @property
    def slot(self) -> int | None:
        """The single matched slot, or None when the guess did not resolve to exactly one."""
        return self.slots[0] if self.status == "match" else None


def match_guess(guess: str, candidates: Sequence[Candidate]) -> MatchResult:
    """Resolve ``guess`` against ``candidates`` (normally the still-hidden players)."""
    needle = normalize(guess)
    if not needle:
        return MatchResult("empty")

    # Exact hits are checked before the length guard, so short curated aliases such as
    # "R9" or "CR7" still work while a stray two-letter guess does not.
    exact = [c.slot for c in candidates if needle in c.keys]
    if exact:
        return MatchResult("match" if len(exact) == 1 else "ambiguous", tuple(sorted(exact)))

    if len(needle.replace(" ", "")) < MIN_GUESS_LENGTH:
        return MatchResult("too_short")

    # Nothing exact - allow a small number of typos, preferring the closest players.
    best_distance: int | None = None
    near: list[int] = []
    for candidate in candidates:
        # Score each candidate by its closest key so the result does not depend on
        # set iteration order.
        distances = []
        for key in sorted(candidate.keys):
            allowance = typo_allowance(key)
            if allowance == 0:
                continue
            distance = edit_distance(needle, key, allowance)
            if distance <= allowance:
                distances.append(distance)
        if not distances:
            continue
        closest = min(distances)
        if best_distance is None or closest < best_distance:
            best_distance, near = closest, [candidate.slot]
        elif closest == best_distance:
            near.append(candidate.slot)
    if near:
        return MatchResult(
            "match" if len(near) == 1 else "ambiguous", tuple(sorted(near)), fuzzy=True
        )
    return MatchResult("no_match")
