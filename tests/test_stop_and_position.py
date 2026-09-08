"""Tests for the stop button's logic: the absolute position and interrupted moves.

GPIO and sleep are mocked, so the moves run instantly. total_steps is kept small in
most tests so a full travel is cheap to count.
"""

from unittest.mock import MagicMock

import pytest

from bedliftcontrol import controller as controller_module
from bedliftcontrol.config import Config
from bedliftcontrol.controller import STOP_RAMP_STEPS, BedController, Direction


@pytest.fixture
def gpio(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(controller_module, "GPIO", fake)
    monkeypatch.setattr(controller_module, "sleep", lambda *_: None)
    return fake


def make_controller(tmp_path, total_steps=1000, position=0):
    config = Config(
        total_steps=total_steps,
        speed_pps=800.0,
        bed_up=False,
        position_steps=position,
        path=str(tmp_path / "config.json"),
    )
    return BedController(config)


class TestPosition:
    def test_starts_at_the_bottom(self, gpio, tmp_path):
        controller = make_controller(tmp_path)
        assert controller.position == 0
        assert controller.at_bottom is True
        assert controller.at_top is False
        assert controller.position_fraction == 0.0

    def test_a_full_move_up_reaches_the_top(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=50)
        controller.move_up()
        assert controller.position == 50
        assert controller.at_top is True
        assert controller.position_fraction == 1.0

    def test_a_full_move_down_reaches_the_bottom(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=50, position=50)
        controller.move_down()
        assert controller.position == 0
        assert controller.at_bottom is True

    def test_fraction_is_the_way_up(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=100, position=25)
        assert controller.position_fraction == 0.25

    def test_fraction_survives_a_zero_total(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=100)
        controller.config.total_steps = 0  # would divide by zero
        assert controller.position_fraction == 0.0


class TestRemainingTravel:
    def test_moving_up_from_half_way_only_travels_the_rest(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=100, position=60)
        steps = []
        controller.move_steps = lambda direction, count: steps.append((direction, count))
        controller.move_up()
        assert steps == [(Direction.UP.value, 40)]

    def test_moving_down_from_half_way_only_travels_back(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=100, position=60)
        steps = []
        controller.move_steps = lambda direction, count: steps.append((direction, count))
        controller.move_down()
        assert steps == [(Direction.DOWN.value, 60)]

    def test_moving_up_at_the_top_travels_nothing(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=100, position=100)
        steps = []
        controller.move_steps = lambda direction, count: steps.append((direction, count))
        controller.move_up()
        assert steps == [(Direction.UP.value, 0)]


class TestStop:
    @staticmethod
    def stop_after(controller, n):
        """Request a stop once n pulses have been sent."""
        real = controller.move_step
        state = {"count": 0}

        def counting(sleeptime):
            real(sleeptime)
            state["count"] += 1
            if state["count"] == n:
                controller._stop_requested.set()

        controller.move_step = counting
        return state

    def test_stop_ends_the_move_early(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=5000)
        self.stop_after(controller, 100)
        controller.move_up()
        assert controller.position < 5000, "the move should not have completed"
        assert controller.position >= 100, "the pulses already sent must be counted"

    def test_stop_decelerates_instead_of_cutting_the_pulses(self, gpio, tmp_path):
        """An abrupt stop can make the steppers lose sync, which would falsify the
        stored position - so a few more steps are expected, but not many."""
        controller = make_controller(tmp_path, total_steps=5000)
        self.stop_after(controller, 100)
        controller.move_up()
        assert 100 < controller.position <= 100 + STOP_RAMP_STEPS

    def test_the_stopped_position_is_persisted(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=5000)
        self.stop_after(controller, 100)
        controller.move_up()
        assert Config.load(controller.config.path).position_steps == controller.position

    def test_a_stopped_move_up_does_not_record_the_bed_as_up(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=5000)
        self.stop_after(controller, 100)
        controller.move_up()
        assert controller.config.bed_up is False
        assert controller.at_top is False

    def test_both_ends_are_reachable_again_after_a_stop(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=5000)
        self.stop_after(controller, 100)
        controller.move_up()
        assert controller.at_top is False and controller.at_bottom is False

    def test_carrying_on_upwards_finishes_the_travel(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=2000)
        self.stop_after(controller, 100)
        controller.move_up()
        stopped_at = controller.position
        controller.move_up()  # same direction again
        assert controller.position == 2000
        assert stopped_at < 2000

    def test_turning_back_returns_to_the_start(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=2000)
        self.stop_after(controller, 100)
        controller.move_up()
        controller.move_down()  # the other way
        assert controller.position == 0
        assert controller.at_bottom is True

    def test_the_stop_flag_is_cleared_for_the_next_move(self, gpio, tmp_path):
        """Otherwise the next move would stop on its very first step."""
        controller = make_controller(tmp_path, total_steps=500)
        self.stop_after(controller, 50)
        controller.move_up()
        assert controller.stop_requested is True
        controller.move_up()
        assert controller.stop_requested is False
        assert controller.position == 500

    def test_stop_while_idle_is_harmless(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=100)
        controller.stop()  # nothing is running
        controller.move_up()
        assert controller.position == 100, "an idle stop must not block the next move"


class TestPositionBounds:
    def test_position_never_goes_below_zero(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=50, position=10)
        controller.move_steps(Direction.DOWN.value, 999)
        assert controller.position == 0

    def test_position_never_goes_above_total(self, gpio, tmp_path):
        controller = make_controller(tmp_path, total_steps=50, position=40)
        controller.move_steps(Direction.UP.value, 999)
        assert controller.position == 50


class TestStoppingSleeptime:
    def test_slows_down_step_by_step(self, gpio, tmp_path):
        controller = make_controller(tmp_path)
        first = controller._stopping_sleeptime(0, 1000, 0.001)
        middle = controller._stopping_sleeptime(STOP_RAMP_STEPS // 2, 1000, 0.001)
        assert middle > first, "a longer sleep means a slower step"

    def test_reports_the_end_of_the_ramp(self, gpio, tmp_path):
        controller = make_controller(tmp_path)
        assert controller._stopping_sleeptime(STOP_RAMP_STEPS, 1000, 0.001) is None

    def test_a_short_remaining_travel_shortens_the_ramp(self, gpio, tmp_path):
        controller = make_controller(tmp_path)
        assert controller._stopping_sleeptime(5, 5, 0.001) is None
