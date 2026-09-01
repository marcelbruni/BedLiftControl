"""Characterization / behaviour tests for the logic and config layers.

guizero and RPi.GPIO are mocked in conftest.py, so these run on any machine.
"""

from unittest.mock import MagicMock, call

import pytest

from bedliftcontrol import controller as controller_module
from bedliftcontrol.config import Config
from bedliftcontrol.controller import BedController, Direction, Pins


@pytest.fixture
def gpio(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(controller_module, "GPIO", fake)
    monkeypatch.setattr(controller_module, "sleep", lambda *_: None)
    return fake


@pytest.fixture
def controller(gpio, tmp_path):
    config = Config(total_steps=10, speed_pps=800.0, bed_up=False, path=str(tmp_path / "config.json"))
    return BedController(config)


class TestConfig:
    def test_load_missing_returns_defaults(self, tmp_path):
        config = Config.load(str(tmp_path / "does_not_exist.json"))
        assert config.total_steps == 28000
        assert config.speed_pps == 800.0
        assert config.bed_up is False

    def test_save_then_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "config.json")
        Config(total_steps=29000, speed_pps=1200.0, bed_up=True, path=path).save()
        loaded = Config.load(path)
        assert loaded.total_steps == 29000
        assert loaded.speed_pps == 1200.0
        assert loaded.bed_up is True


class TestCalculateSleepFromPps:
    @pytest.mark.parametrize(
        "pps, expected",
        [
            (800, (1 / 800) / 2),
            (200, (1 / 200) / 2),
            (1400, (1 / 1400) / 2),
        ],
    )
    def test_returns_half_pulse_period(self, pps, expected):
        assert BedController.calculate_sleep_from_pps(pps) == expected


class TestEnums:
    def test_direction_values(self):
        assert Direction.UP.value == 0
        assert Direction.DOWN.value == 1

    def test_pin_values(self):
        assert Pins.FRONT_PUL.value == 27
        assert Pins.BACK_PUL.value == 24
        assert Pins.FRONT_DIR.value == 22
        assert Pins.BACK_DIR.value == 23


class TestChangeDirection:
    def test_down_sets_both_dir_pins_to_down(self, controller, gpio):
        controller.change_direction(1)
        gpio.output.assert_any_call(Pins.FRONT_DIR.value, Direction.DOWN.value)
        gpio.output.assert_any_call(Pins.BACK_DIR.value, Direction.DOWN.value)

    def test_up_sets_both_dir_pins_to_up(self, controller, gpio):
        controller.change_direction(0)
        gpio.output.assert_any_call(Pins.FRONT_DIR.value, Direction.UP.value)
        gpio.output.assert_any_call(Pins.BACK_DIR.value, Direction.UP.value)


class TestMoveStepSingle:
    def test_pulses_the_given_pin_high_then_low(self, controller, gpio):
        gpio.reset_mock()
        controller.move_step_single(Pins.BACK_PUL.value, 0.01)
        assert gpio.output.call_args_list == [
            call(Pins.BACK_PUL.value, 1),
            call(Pins.BACK_PUL.value, 0),
        ]

    def test_uses_exactly_the_pin_it_is_given(self, controller, gpio):
        gpio.reset_mock()
        controller.move_step_single(Pins.FRONT_PUL.value, 0.01)
        assert gpio.output.call_args_list == [
            call(Pins.FRONT_PUL.value, 1),
            call(Pins.FRONT_PUL.value, 0),
        ]

    def test_sleeps_twice_per_step(self, controller, monkeypatch):
        recorded = []
        monkeypatch.setattr(controller_module, "sleep", recorded.append)
        controller.move_step_single(Pins.BACK_PUL.value, 0.01)
        assert recorded == [0.01, 0.01]


class TestMoveStep:
    def test_pulses_both_pins_high_then_low(self, controller, gpio):
        gpio.reset_mock()
        controller.move_step(0.01)
        assert gpio.output.call_args_list == [
            call(Pins.FRONT_PUL.value, 1),
            call(Pins.BACK_PUL.value, 1),
            call(Pins.FRONT_PUL.value, 0),
            call(Pins.BACK_PUL.value, 0),
        ]


class TestMoveSteps:
    def test_calls_move_step_once_per_step(self, controller, monkeypatch):
        count = {"n": 0}
        monkeypatch.setattr(controller, "move_step", lambda _: count.__setitem__("n", count["n"] + 1))
        controller.move_steps(Direction.UP.value, 7)
        assert count["n"] == 7


class TestMoveUpDown:
    def test_move_up_sets_bed_up_and_persists(self, controller, monkeypatch):
        monkeypatch.setattr(controller, "move_steps", lambda *_: None)
        controller.move_up()
        assert controller.config.bed_up is True
        assert Config.load(controller.config.path).bed_up is True

    def test_move_down_clears_bed_up_and_persists(self, controller, monkeypatch):
        monkeypatch.setattr(controller, "move_steps", lambda *_: None)
        controller.config.bed_up = True
        controller.move_down()
        assert controller.config.bed_up is False
        assert Config.load(controller.config.path).bed_up is False
