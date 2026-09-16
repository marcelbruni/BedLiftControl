"""Memory: find the pairs, using the drawn weather icons as card faces.

Pure logic, no Tk, so the rules can be tested without a window. Tapping is the only
input the 7" panel offers, which is exactly what this game needs.
"""

import random
from dataclasses import dataclass, field

CARD_ICONS = (
    "sun",
    "sun-cloud",
    "cloud",
    "fog",
    "rain-3",
    "snow-3",
    "grains",
    "thunder",
)
PAIR_COUNT = len(CARD_ICONS)

IGNORED = "ignored"
REVEALED = "revealed"
MATCH = "match"
MISMATCH = "mismatch"


@dataclass
class Card:
    icon: str
    face_up: bool = False
    matched: bool = False


@dataclass
class MemoryGame:
    """`shuffle` is injectable so a test can lay the deck out in a known order."""

    icons: tuple = CARD_ICONS
    shuffle: object = field(default=random.shuffle)
    cards: list = field(default_factory=list)
    moves: int = 0

    def __post_init__(self) -> None:
        self.deal()

    def deal(self) -> None:
        self.cards = [Card(icon) for icon in self.icons for _ in range(2)]
        self.shuffle(self.cards)
        self.moves = 0

    @property
    def face_up_unmatched(self) -> list:
        return [card for card in self.cards if card.face_up and not card.matched]

    @property
    def waiting(self) -> bool:
        """Two cards are up and did not match; nothing may be tapped until resolved."""
        return len(self.face_up_unmatched) == 2

    @property
    def won(self) -> bool:
        return all(card.matched for card in self.cards)

    @property
    def pairs_found(self) -> int:
        return sum(card.matched for card in self.cards) // 2

    def reveal(self, index: int) -> str:
        if self.waiting or not 0 <= index < len(self.cards):
            return IGNORED
        card = self.cards[index]
        if card.matched or card.face_up:
            return IGNORED
        card.face_up = True
        open_cards = self.face_up_unmatched
        if len(open_cards) < 2:
            return REVEALED
        self.moves += 1
        first, second = open_cards
        if first.icon != second.icon:
            return MISMATCH
        first.matched = second.matched = True
        return MATCH

    def resolve(self) -> None:
        """Turn the mismatched pair back over."""
        for card in self.face_up_unmatched:
            card.face_up = False
