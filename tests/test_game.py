"""Tests for the memory game rules.

The deck is laid out in a known order by injecting a shuffle that does nothing, so
"card 0 and card 1 are a pair" holds and the rules can be checked exactly.
"""

import pytest

from bedliftcontrol.game import (
    CARD_ICONS,
    IGNORED,
    MATCH,
    MISMATCH,
    PAIR_COUNT,
    REVEALED,
    MemoryGame,
)


def no_shuffle(cards):
    return None


@pytest.fixture
def game():
    """Ordered deck: pair n sits at index 2n and 2n+1."""
    return MemoryGame(shuffle=no_shuffle)


class TestDeck:
    def test_two_cards_per_icon(self, game):
        for icon in CARD_ICONS:
            assert [card.icon for card in game.cards].count(icon) == 2

    def test_deck_size(self, game):
        assert len(game.cards) == 2 * PAIR_COUNT

    def test_all_icons_are_drawable(self):
        from bedliftcontrol.icons import ICON_SPECS

        for icon in CARD_ICONS:
            assert icon in ICON_SPECS, f"{icon} has no drawing"

    def test_icons_are_distinct(self):
        assert len(set(CARD_ICONS)) == len(CARD_ICONS)

    def test_everything_starts_face_down(self, game):
        assert not any(card.face_up or card.matched for card in game.cards)

    def test_a_real_shuffle_is_used_by_default(self):
        """Two fresh decks in the same order would be a broken shuffle."""
        orders = {tuple(card.icon for card in MemoryGame().cards) for _ in range(20)}
        assert len(orders) > 1


class TestReveal:
    def test_the_first_card_turns_over(self, game):
        assert game.reveal(0) == REVEALED
        assert game.cards[0].face_up is True

    def test_a_matching_second_card_is_a_pair(self, game):
        game.reveal(0)
        assert game.reveal(1) == MATCH
        assert game.cards[0].matched and game.cards[1].matched

    def test_a_different_second_card_is_a_mismatch(self, game):
        game.reveal(0)
        assert game.reveal(2) == MISMATCH
        assert not game.cards[0].matched

    def test_tapping_the_same_card_twice_does_nothing(self, game):
        game.reveal(0)
        assert game.reveal(0) == IGNORED

    def test_tapping_a_matched_card_does_nothing(self, game):
        game.reveal(0)
        game.reveal(1)
        assert game.reveal(0) == IGNORED

    def test_a_third_card_is_ignored_while_two_are_open(self, game):
        game.reveal(0)
        game.reveal(2)
        assert game.reveal(4) == IGNORED
        assert game.cards[4].face_up is False

    @pytest.mark.parametrize("index", [-1, 99])
    def test_an_index_outside_the_deck_is_ignored(self, game, index):
        assert game.reveal(index) == IGNORED


class TestMoveCount:
    def test_starts_at_zero(self, game):
        assert game.moves == 0

    def test_the_first_card_is_not_a_move(self, game):
        game.reveal(0)
        assert game.moves == 0

    def test_a_pair_counts_as_one_move(self, game):
        game.reveal(0)
        game.reveal(1)
        assert game.moves == 1

    def test_a_mismatch_counts_as_one_move(self, game):
        game.reveal(0)
        game.reveal(2)
        assert game.moves == 1

    def test_ignored_taps_do_not_count(self, game):
        game.reveal(0)
        game.reveal(0)
        game.reveal(99)
        assert game.moves == 0


class TestResolve:
    def test_a_mismatched_pair_turns_back_over(self, game):
        game.reveal(0)
        game.reveal(2)
        game.resolve()
        assert not any(card.face_up for card in game.cards)

    def test_matched_cards_stay_up(self, game):
        game.reveal(0)
        game.reveal(1)
        game.resolve()
        assert game.cards[0].matched and game.cards[1].matched

    def test_play_continues_after_resolving(self, game):
        game.reveal(0)
        game.reveal(2)
        game.resolve()
        assert game.waiting is False
        assert game.reveal(4) == REVEALED


class TestWaiting:
    def test_not_waiting_at_the_start(self, game):
        assert game.waiting is False

    def test_not_waiting_after_one_card(self, game):
        game.reveal(0)
        assert game.waiting is False

    def test_waiting_after_a_mismatch(self, game):
        game.reveal(0)
        game.reveal(2)
        assert game.waiting is True

    def test_not_waiting_after_a_match(self, game):
        game.reveal(0)
        game.reveal(1)
        assert game.waiting is False, "a found pair must not block the next tap"


class TestWinning:
    @staticmethod
    def play_out(game):
        for pair in range(PAIR_COUNT):
            game.reveal(2 * pair)
            game.reveal(2 * pair + 1)

    def test_not_won_at_the_start(self, game):
        assert game.won is False

    def test_won_once_every_pair_is_found(self, game):
        self.play_out(game)
        assert game.won is True

    def test_pairs_found_counts_up(self, game):
        assert game.pairs_found == 0
        game.reveal(0)
        game.reveal(1)
        assert game.pairs_found == 1

    def test_a_perfect_game_takes_one_move_per_pair(self, game):
        self.play_out(game)
        assert game.moves == PAIR_COUNT


class TestDealAgain:
    def test_a_new_deal_clears_the_board(self, game):
        game.reveal(0)
        game.reveal(1)
        game.deal()
        assert not any(card.face_up or card.matched for card in game.cards)

    def test_a_new_deal_resets_the_moves(self, game):
        game.reveal(0)
        game.reveal(2)
        game.deal()
        assert game.moves == 0

    def test_a_new_deal_keeps_the_deck_complete(self, game):
        game.deal()
        assert len(game.cards) == 2 * PAIR_COUNT
