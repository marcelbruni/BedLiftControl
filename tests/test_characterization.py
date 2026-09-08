"""Characterization / behaviour tests for the logic and config layers.

guizero and RPi.GPIO are mocked in conftest.py, so these run on any machine.
"""

import threading
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
        assert config.bed_up is True

    def test_save_then_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "config.json")
        Config(total_steps=29000, speed_pps=1200.0, bed_up=True, path=path).save()
        loaded = Config.load(path)
        assert loaded.total_steps == 29000
        assert loaded.speed_pps == 1200.0
        assert loaded.bed_up is True

    def test_load_corrupt_file_returns_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{ not valid json")
        config = Config.load(str(path))
        assert config.total_steps == 28000

    def test_load_missing_keys_returns_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"total_steps": 5}')
        config = Config.load(str(path))
        assert config.total_steps == 28000

    def test_load_invalid_values_are_clamped(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"total_steps": 0, "speed_pps": -5, "bed_up": true}')
        config = Config.load(str(path))
        assert config.total_steps == 28000
        assert config.speed_pps == 800.0
        assert config.bed_up is True

    def test_save_is_atomic_and_leaves_no_temp_file(self, tmp_path):
        path = tmp_path / "config.json"
        Config(total_steps=1, speed_pps=2.0, bed_up=False, path=str(path)).save()
        assert path.exists()
        assert not (tmp_path / "config.json.tmp").exists()


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

    @pytest.mark.parametrize("pps", [0, -1, -100])
    def test_rejects_non_positive(self, pps):
        with pytest.raises(ValueError):
            BedController.calculate_sleep_from_pps(pps)


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

    def test_reports_progress_and_resets_when_done(self, controller, monkeypatch):
        seen = []
        monkeypatch.setattr(controller, "move_step", lambda _: seen.append(controller.progress))
        controller.move_steps(Direction.UP.value, 4)
        assert seen == [0.0, 0.25, 0.5, 0.75]
        assert controller.progress == 0.0

    def test_ramps_speed_at_start_and_end(self, controller, monkeypatch):
        sleeps = []
        monkeypatch.setattr(controller, "move_step", lambda s: sleeps.append(s))
        controller.move_steps(Direction.UP.value, 2000)
        target = BedController.calculate_sleep_from_pps(controller.config.speed_pps)
        assert sleeps[0] > target                     # starts slower (accelerates)
        assert sleeps[-1] > target                    # ends slower (decelerates)
        assert min(sleeps) == pytest.approx(target)   # reaches full speed in the middle


class TestMoveUpDown:
    """bed_up is now derived from the absolute position rather than set blindly, so the
    stubbed move has to move the position for the flag to follow."""

    @staticmethod
    def _stub_travel(controller, monkeypatch):
        """Stand in for move_steps: apply the requested travel to the position."""
        from bedliftcontrol.controller import Direction

        def travel(direction, steps):
            delta = -steps if direction == Direction.DOWN.value else steps
            controller.config.position_steps = max(
                0, min(controller.config.total_steps, controller.config.position_steps + delta)
            )

        monkeypatch.setattr(controller, "move_steps", travel)

    def test_move_up_sets_bed_up_and_persists(self, controller, monkeypatch):
        self._stub_travel(controller, monkeypatch)
        controller.move_up()
        assert controller.config.bed_up is True
        assert Config.load(controller.config.path).bed_up is True

    def test_move_down_clears_bed_up_and_persists(self, controller, monkeypatch):
        self._stub_travel(controller, monkeypatch)
        controller.config.position_steps = controller.config.total_steps
        controller.config.bed_up = True
        controller.move_down()
        assert controller.config.bed_up is False
        assert Config.load(controller.config.path).bed_up is False

    def test_a_stopped_move_does_not_claim_the_bed_is_up(self, controller, monkeypatch):
        """The 'attach the safety ropes' state must not be recorded for a partial move."""
        monkeypatch.setattr(controller, "move_steps", lambda *_: None)  # nothing moved
        controller.move_up()
        assert controller.config.bed_up is False


class TestCleanup:
    def test_cleanup_releases_gpio(self, controller, gpio):
        controller.cleanup()
        gpio.cleanup.assert_called_once()


class TestAsyncMovement:
    def test_run_async_runs_action_and_completes(self, controller):
        ran = threading.Event()
        assert controller.run_async(ran.set) is True
        controller.wait_for_move(timeout=1)
        assert ran.is_set()
        assert controller.is_moving is False

    def test_is_moving_true_while_action_runs(self, controller):
        started = threading.Event()
        release = threading.Event()

        def action():
            started.set()
            release.wait(1)

        controller.run_async(action)
        assert started.wait(1)
        assert controller.is_moving is True
        release.set()
        controller.wait_for_move(timeout=1)
        assert controller.is_moving is False

    def test_second_move_is_rejected_while_moving(self, controller):
        started = threading.Event()
        release = threading.Event()

        def action():
            started.set()
            release.wait(1)

        assert controller.run_async(action) is True
        assert started.wait(1)
        assert controller.run_async(lambda: None) is False
        release.set()
        controller.wait_for_move(timeout=1)

    def test_on_complete_runs_after_action(self, controller):
        order = []
        controller.run_async(lambda: order.append("action"), on_complete=lambda: order.append("done"))
        controller.wait_for_move(timeout=1)
        assert order == ["action", "done"]

    def test_exception_in_action_still_runs_on_complete(self, controller):
        completed = threading.Event()

        def boom():
            raise RuntimeError("motor jammed")

        controller.run_async(boom, on_complete=completed.set)
        controller.wait_for_move(timeout=1)
        assert completed.is_set()
        assert controller.is_moving is False


class TestConfigKiosk:
    def test_kiosk_defaults_to_off(self, tmp_path):
        assert Config.load(str(tmp_path / "missing.json")).kiosk is False

    def test_kiosk_survives_a_save_and_load(self, tmp_path):
        path = str(tmp_path / "config.json")
        Config(total_steps=29000, speed_pps=1200.0, bed_up=True, kiosk=True, path=path).save()
        assert Config.load(path).kiosk is True

    def test_a_config_written_before_kiosk_existed_keeps_its_values(self, tmp_path):
        """The other keys are read with [], so a missing key must not land in the
        except branch - that would silently reset steps, speed and bed position."""
        import json

        path = tmp_path / "config.json"
        path.write_text(json.dumps({"total_steps": 29500, "speed_pps": 1200.0, "bed_up": False}))
        config = Config.load(str(path))
        assert config.total_steps == 29500
        assert config.speed_pps == 1200.0
        assert config.bed_up is False
        assert config.kiosk is False


class TestCorrections:
    """Which pin gets pulsed, in which direction, how many times. Swapping two pins
    here would tilt the bed the wrong way and no other test would notice."""

    # Direction.DOWN.value is 1, so a downward move writes a 1 to the DIR pins too -
    # only the PUL pins count as pulses.
    PUL_PINS = (Pins.FRONT_PUL.value, Pins.BACK_PUL.value)

    @classmethod
    def _pulses(cls, gpio):
        return [c for c in gpio.output.call_args_list
                if c.args[0] in cls.PUL_PINS and c.args[1] == 1]

    @classmethod
    def _pulsed_pins(cls, gpio):
        """Motor pins that were pulsed at least once."""
        return {c.args[0] for c in cls._pulses(gpio)}

    @pytest.mark.parametrize(
        "method, pin, direction",
        [
            ("correct_back_up", Pins.BACK_PUL, Direction.UP),
            ("correct_back_down", Pins.BACK_PUL, Direction.DOWN),
            ("correct_front_up", Pins.FRONT_PUL, Direction.UP),
            ("correct_front_down", Pins.FRONT_PUL, Direction.DOWN),
        ],
    )
    def test_pulses_only_its_own_motor(self, controller, gpio, method, pin, direction):
        getattr(controller, method)()
        assert self._pulsed_pins(gpio) == {pin.value}

    @pytest.mark.parametrize(
        "method, direction",
        [
            ("correct_back_up", Direction.UP),
            ("correct_front_up", Direction.UP),
            ("correct_back_down", Direction.DOWN),
            ("correct_front_down", Direction.DOWN),
        ],
    )
    def test_sets_both_direction_pins(self, controller, gpio, method, direction):
        getattr(controller, method)()
        assert call(Pins.FRONT_DIR.value, direction.value) in gpio.output.call_args_list
        assert call(Pins.BACK_DIR.value, direction.value) in gpio.output.call_args_list

    @pytest.mark.parametrize(
        "method",
        ["correct_back_up", "correct_back_down", "correct_front_up", "correct_front_down"],
    )
    def test_moves_exactly_the_correction_step_count(self, controller, gpio, method):
        from bedliftcontrol.controller import CORRECTION_STEPS

        getattr(controller, method)()
        assert len(self._pulses(gpio)) == CORRECTION_STEPS

    @pytest.mark.parametrize(
        "method",
        ["correct_back_up", "correct_back_down", "correct_front_up", "correct_front_down"],
    )
    def test_does_not_touch_the_stored_position(self, controller, monkeypatch, method):
        """A correction re-zeroes one side against its end stop. The common travel is
        unchanged, and the offset lives in the mechanism, not in the config."""
        controller.config.position_steps = 7
        getattr(controller, method)()
        assert controller.config.position_steps == 7

    def test_up_and_down_are_opposite(self, controller, gpio):
        controller.correct_front_up()
        up_directions = [c for c in gpio.output.call_args_list
                         if c.args[0] == Pins.FRONT_DIR.value]
        gpio.reset_mock()
        controller.correct_front_down()
        down_directions = [c for c in gpio.output.call_args_list
                           if c.args[0] == Pins.FRONT_DIR.value]
        assert up_directions[0].args[1] != down_directions[0].args[1]


class TestCorrectionRamp:
    """A click still moves exactly CORRECTION_STEPS, but eased in and out."""

    @staticmethod
    def _sleeptimes(controller):
        times = []
        controller.move_step_single = lambda pin, sleeptime: times.append(sleeptime)
        return times

    def test_step_count_is_unchanged(self, controller, gpio):
        from bedliftcontrol.controller import CORRECTION_STEPS

        times = self._sleeptimes(controller)
        controller.correct_front_up()
        assert len(times) == CORRECTION_STEPS

    def test_starts_slower_than_it_runs(self, controller, gpio):
        times = self._sleeptimes(controller)
        controller.correct_front_up()
        assert times[0] > times[len(times) // 2], "a longer sleep means a slower step"

    def test_ends_slower_than_it_runs(self, controller, gpio):
        times = self._sleeptimes(controller)
        controller.correct_front_up()
        assert times[-1] > times[len(times) // 2]

    def test_reaches_the_target_speed_in_the_middle(self, controller, gpio):
        times = self._sleeptimes(controller)
        controller.correct_front_up()
        target = controller.calculate_sleep_from_pps(controller.config.speed_pps)
        assert times[len(times) // 2] == pytest.approx(target)

    def test_the_ramp_is_symmetric(self, controller, gpio):
        times = self._sleeptimes(controller)
        controller.correct_front_up()
        assert times[0] == pytest.approx(times[-1])


class TestCorrectionHold:
    """Holding a correction button keeps one motor turning until it is let go."""

    @staticmethod
    def _stop_after(controller, count):
        times = []

        def counting(pin, sleeptime):
            times.append(sleeptime)
            if len(times) == count:
                controller._stop_requested.set()

        controller.move_step_single = counting
        return times

    def test_runs_until_stopped(self, controller, gpio):
        times = self._stop_after(controller, 60)
        controller.hold_front_up()
        assert len(times) >= 60

    def test_decelerates_after_release(self, controller, gpio):
        from bedliftcontrol.controller import CORRECTION_RAMP_STEPS

        times = self._stop_after(controller, 60)
        controller.hold_front_up()
        assert 60 < len(times) <= 60 + CORRECTION_RAMP_STEPS
        assert times[-1] > times[59], "the last steps must be the slow ones"

    def test_ramps_in(self, controller, gpio):
        times = self._stop_after(controller, 60)
        controller.hold_front_up()
        assert times[0] > times[30]

    def test_reaches_target_speed_while_held(self, controller, gpio):
        times = self._stop_after(controller, 60)
        controller.hold_front_up()
        target = controller.calculate_sleep_from_pps(controller.config.speed_pps)
        assert times[40] == pytest.approx(target)

    def test_capped_so_a_lost_release_cannot_run_away(self, controller, gpio):
        from bedliftcontrol.controller import CORRECTION_HOLD_MAX_STEPS, CORRECTION_RAMP_STEPS

        times = []
        controller.move_step_single = lambda pin, sleeptime: times.append(sleeptime)
        controller.hold_front_up()  # nothing ever asks it to stop
        assert len(times) <= CORRECTION_HOLD_MAX_STEPS + CORRECTION_RAMP_STEPS

    def test_a_previous_stop_does_not_block_the_next_hold(self, controller, gpio):
        controller._stop_requested.set()
        times = self._stop_after(controller, 30)
        controller.hold_front_up()
        assert len(times) >= 30, "the flag must be cleared when the hold starts"

    @pytest.mark.parametrize(
        "method, pin, direction",
        [
            ("hold_back_up", Pins.BACK_PUL, Direction.UP),
            ("hold_back_down", Pins.BACK_PUL, Direction.DOWN),
            ("hold_front_up", Pins.FRONT_PUL, Direction.UP),
            ("hold_front_down", Pins.FRONT_PUL, Direction.DOWN),
        ],
    )
    def test_pulses_only_its_own_motor(self, controller, gpio, method, pin, direction):
        pulsed = []

        def once(p, _sleeptime):
            pulsed.append(p)
            controller._stop_requested.set()

        controller.move_step_single = once
        getattr(controller, method)()
        assert set(pulsed) == {pin.value}
        assert call(Pins.FRONT_DIR.value, direction.value) in gpio.output.call_args_list
        assert call(Pins.BACK_DIR.value, direction.value) in gpio.output.call_args_list

    def test_does_not_touch_the_stored_position(self, controller, gpio):
        controller.config.position_steps = 7
        self._stop_after(controller, 30)
        controller.hold_front_up()
        assert controller.config.position_steps == 7
