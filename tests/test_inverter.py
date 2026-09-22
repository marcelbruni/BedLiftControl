"""Tests for the inverter switch.

RPi.GPIO is mocked (conftest.py), so the pin writes can be asserted without hardware.
The clock is injected, so the start-up delay needs no waiting.
"""

import pytest
import RPi.GPIO as GPIO

from bedliftcontrol.inverter import INVERTER_PIN, STARTUP_SECONDS, Inverter


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def inverter(clock):
    GPIO.reset_mock()
    return Inverter(clock=clock)


def outputs():
    return [call.args for call in GPIO.output.call_args_list]


class TestWiring:
    def test_the_pin_is_an_output(self, inverter):
        assert GPIO.setup.call_args.args[0] == INVERTER_PIN
        assert GPIO.setup.call_args.args[1] == GPIO.OUT

    def test_it_starts_low(self, inverter):
        """A relay that closes on its own at start-up would switch mains power on in a
        parked vehicle."""
        assert GPIO.setup.call_args.kwargs["initial"] == GPIO.LOW

    def test_off_after_construction(self, inverter):
        assert inverter.on is False

    def test_a_second_instance_can_use_another_pin(self, clock):
        assert Inverter(pin=5, clock=clock).pin == 5


class TestSwitching:
    def test_turning_on_drives_the_pin_high(self, inverter):
        assert inverter.turn_on() is True
        assert (INVERTER_PIN, GPIO.HIGH) in outputs()
        assert inverter.on is True

    def test_turning_on_twice_changes_nothing(self, inverter):
        inverter.turn_on()
        assert inverter.turn_on() is False

    def test_turning_off_drives_the_pin_low(self, inverter):
        inverter.turn_on()
        assert inverter.turn_off() is True
        assert (INVERTER_PIN, GPIO.LOW) in outputs()
        assert inverter.on is False

    def test_turning_off_when_it_is_off_changes_nothing(self, inverter):
        assert inverter.turn_off() is False

    def test_toggle_reports_the_new_state(self, inverter):
        assert inverter.toggle() is True
        assert inverter.toggle() is False


class TestStartup:
    def test_not_ready_while_off(self, inverter):
        assert inverter.ready is False

    def test_not_ready_the_moment_it_is_switched_on(self, inverter):
        inverter.turn_on()
        assert inverter.ready is False

    def test_ready_once_the_start_up_has_passed(self, inverter, clock):
        inverter.turn_on()
        clock.advance(STARTUP_SECONDS)
        assert inverter.ready is True

    def test_still_not_ready_just_before(self, inverter, clock):
        inverter.turn_on()
        clock.advance(STARTUP_SECONDS - 0.1)
        assert inverter.ready is False

    def test_the_countdown_runs_down(self, inverter, clock):
        inverter.turn_on()
        clock.advance(4.0)
        assert inverter.seconds_until_ready == pytest.approx(STARTUP_SECONDS - 4.0)

    def test_the_countdown_stops_at_zero(self, inverter, clock):
        inverter.turn_on()
        clock.advance(STARTUP_SECONDS * 3)
        assert inverter.seconds_until_ready == 0.0

    def test_an_already_running_inverter_keeps_its_readiness(self, inverter, clock):
        """A second turn_on must not restart the countdown - the thing is up."""
        inverter.turn_on()
        clock.advance(STARTUP_SECONDS)
        inverter.turn_on()
        assert inverter.ready is True

    def test_switching_off_and_on_again_starts_the_countdown_over(self, inverter, clock):
        inverter.turn_on()
        clock.advance(STARTUP_SECONDS)
        inverter.turn_off()
        inverter.turn_on()
        assert inverter.ready is False

    def test_an_inverter_that_is_off_reports_the_full_wait(self, inverter):
        assert inverter.seconds_until_ready == STARTUP_SECONDS
