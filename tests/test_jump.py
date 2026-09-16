"""Tests for the jump game rules.

Obstacle sizes and gaps come from an injected random source that always answers the
same, so "the obstacle is 20 wide and 30 high, 1.5 seconds apart" holds and the
physics can be checked exactly.
"""

import pytest

from bedliftcontrol import jump
from bedliftcontrol.jump import (
    MAX_FRAME_SECONDS,
    MAX_SPEED,
    OVER,
    PLAYER_SIZE,
    PLAYER_X,
    READY,
    RESTART_LOCK_SECONDS,
    RUNNING,
    START_SPEED,
    WORLD_WIDTH,
    JumpGame,
    Obstacle,
)

FRAME = 1 / 30


class FixedRandom:
    def __init__(self, gap_seconds=1.5, width=20.0, height=30.0):
        self.gap_seconds = gap_seconds
        self.width = width
        self.height = height

    def uniform(self, low, high):
        if (low, high) == jump.OBSTACLE_WIDTH:
            return self.width
        if (low, high) == jump.OBSTACLE_HEIGHT:
            return self.height
        return self.gap_seconds


@pytest.fixture
def game():
    return JumpGame(rng=FixedRandom())


@pytest.fixture
def open_track():
    """Obstacles so far apart that none ever arrives: lets a run go on as long as needed."""
    return JumpGame(rng=FixedRandom(gap_seconds=10000))


def run_until_over(game):
    game.jump()
    while game.state != OVER:
        game.tick(FRAME)


def run(game, seconds, tap_at=()):
    """Tick for a while, tapping at the given elapsed times."""
    taps = sorted(tap_at, reverse=True)
    elapsed = 0.0
    while elapsed < seconds:
        while taps and taps[-1] <= elapsed:
            taps.pop()
            game.jump()
        game.tick(FRAME)
        elapsed += FRAME


class TestStart:
    def test_waits_for_the_first_tap(self, game):
        assert game.state == READY

    def test_ticking_changes_nothing_before_the_first_tap(self, game):
        run(game, 2.0)
        assert game.distance == 0 and game.obstacles == []

    def test_the_first_tap_starts_the_run(self, game):
        game.jump()
        assert game.state == RUNNING

    def test_the_first_tap_is_also_a_jump(self, game):
        game.jump()
        game.tick(FRAME)
        assert game.airborne is True

    def test_it_starts_slow(self, game):
        assert game.speed == START_SPEED


class TestJumping:
    def test_a_tap_lifts_the_player(self, game):
        game.jump()
        run(game, 0.2)
        assert game.height > 0

    def test_a_second_tap_in_the_air_is_ignored(self, game):
        game.jump()
        run(game, 0.2)
        assert game.jump() is False

    def test_the_player_comes_back_down(self, game):
        game.jump()
        run(game, 1.0)
        assert game.height == 0 and game.airborne is False

    def test_the_jump_clears_every_obstacle_height(self, game):
        game.jump()
        peak = 0.0
        for _ in range(30):
            game.tick(FRAME)
            peak = max(peak, game.height)
        assert peak > max(jump.OBSTACLE_HEIGHT)

    def test_it_can_jump_again_after_landing(self, game):
        game.jump()
        run(game, 1.0)
        assert game.jump() is True


class TestSpeed:
    def test_it_gets_faster(self, game):
        game.jump()
        run(game, 3.0)
        assert game.speed > START_SPEED

    def test_it_stops_getting_faster_at_the_top(self, open_track):
        open_track.jump()
        run(open_track, 120.0)
        assert open_track.speed == MAX_SPEED

    def test_a_stalled_frame_does_not_teleport_the_player(self, game):
        game.jump()
        game.tick(5.0)
        assert game.distance <= START_SPEED * MAX_FRAME_SECONDS + 1


class TestObstacles:
    def test_none_are_standing_at_the_start(self, game):
        assert game.obstacles == []

    def test_they_come_in(self, game):
        game.jump()
        run(game, 3.0)
        assert game.obstacles

    def test_they_enter_from_the_right(self, game):
        game.jump()
        run(game, 2.0)
        assert all(obstacle.x <= WORLD_WIDTH for obstacle in game.obstacles)

    def test_they_move_towards_the_player(self, game):
        game.jump()
        run(game, 2.0)
        first = game.obstacles[0]
        before = first.x
        run(game, 0.5)
        assert first.x < before

    def test_passed_ones_are_dropped(self, open_track):
        open_track.obstacles = [Obstacle(x=-30.0, width=20.0, height=30.0)]
        open_track.state = RUNNING
        run(open_track, 0.2)
        assert open_track.obstacles == []

    def test_the_gap_leaves_room_to_land(self, game):
        """Shorter than the time in the air and the game would be unwinnable."""
        game.jump()
        run(game, 60.0)
        assert game.gap_left >= 0
        assert jump.MIN_GAP_SECONDS > 2 * jump.JUMP_VELOCITY / jump.GRAVITY


class TestCollision:
    @staticmethod
    def place(game, distance_ahead, height=30.0):
        game.state = RUNNING
        game.obstacles = [Obstacle(x=PLAYER_X + PLAYER_SIZE + distance_ahead,
                                   width=20.0, height=height)]

    def test_running_into_one_ends_the_game(self, game):
        self.place(game, 40.0)
        run(game, 2.0)
        assert game.state == OVER

    def test_jumping_over_one_does_not(self, game):
        self.place(game, START_SPEED * 0.25)
        game.jump()
        run(game, 1.5)
        assert game.state == RUNNING

    def test_a_jump_that_is_too_early_still_ends_it(self, game):
        self.place(game, START_SPEED * 2)
        game.jump()
        run(game, 3.0)
        assert game.state == OVER

    def test_standing_on_the_ground_next_to_one_is_safe(self, game):
        game.state = RUNNING
        game.obstacles = [Obstacle(x=PLAYER_X + PLAYER_SIZE + 1, width=20.0, height=30.0)]
        game.tick(0.0)
        assert game.state == RUNNING


class TestGameOver:
    @pytest.fixture
    def crashed(self, game):
        run_until_over(game)
        return game

    def test_the_world_stands_still(self, crashed):
        distance = crashed.distance
        run(crashed, 1.0)
        assert crashed.distance == distance

    def test_a_tap_right_away_does_nothing(self, crashed):
        assert crashed.jump() is False
        assert crashed.state == OVER

    def test_a_tap_after_the_lock_restarts(self, crashed):
        run(crashed, RESTART_LOCK_SECONDS + 0.2)
        assert crashed.can_restart is True
        assert crashed.jump() is True
        assert crashed.state == READY

    def test_the_restart_clears_the_board(self, crashed):
        run(crashed, RESTART_LOCK_SECONDS + 0.2)
        crashed.jump()
        assert crashed.obstacles == []
        assert crashed.score == 0
        assert crashed.speed == START_SPEED


class TestScore:
    def test_starts_at_zero(self, game):
        assert game.score == 0

    def test_counts_up_while_running(self, game):
        game.jump()
        run(game, 2.0)
        assert game.score > 0

    def test_counts_faster_when_faster(self, open_track):
        open_track.jump()
        run(open_track, 2.0)
        first_stretch = open_track.score
        run(open_track, 2.0)
        second_stretch = open_track.score - first_stretch
        assert second_stretch > first_stretch
