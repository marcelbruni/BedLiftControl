"""Hardware and motion logic for the bed lift. No GUI dependencies."""

import logging
import threading
from enum import Enum
from time import sleep
from typing import Callable, Optional

import RPi.GPIO as GPIO

from bedliftcontrol.config import Config

logger = logging.getLogger(__name__)


class Direction(Enum):
    UP = 0
    DOWN = 1


class Pins(Enum):
    FRONT_PUL = 27
    BACK_PUL = 24
    FRONT_DIR = 22
    BACK_DIR = 23


CORRECTION_STEPS = 100
RAMP_STEPS = 500          # steps spent accelerating (and decelerating)
RAMP_START_FACTOR = 3.0   # first step runs at 1/RAMP_START_FACTOR of target speed
# A stop request decelerates over this many steps instead of cutting the pulses dead.
# Steppers can lose sync on an abrupt stop, and a lost step means the saved position
# no longer matches the bed - which is the one thing the stored position must not do.
STOP_RAMP_STEPS = 200


class BedController:
    def __init__(self, config: Config):
        self.config = config
        self._move_thread: Optional[threading.Thread] = None
        self._steps_total = 0
        self._steps_done = 0
        self._stop_requested = threading.Event()
        self._setup_gpio()

    def _setup_gpio(self) -> None:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)                      # choose BCM for GPIO numbering
        GPIO.setup(Pins.FRONT_PUL.value, GPIO.OUT)
        GPIO.setup(Pins.FRONT_DIR.value, GPIO.OUT)
        GPIO.setup(Pins.BACK_PUL.value, GPIO.OUT)
        GPIO.setup(Pins.BACK_DIR.value, GPIO.OUT)

    def cleanup(self) -> None:
        """Release the GPIO pins. Call once on application shutdown."""
        GPIO.cleanup()

    @property
    def is_moving(self) -> bool:
        return self._move_thread is not None and self._move_thread.is_alive()

    @property
    def progress(self) -> float:
        """Fraction (0.0-1.0) of the current move, or 0.0 when idle."""
        total = self._steps_total
        if total <= 0:
            return 0.0
        return self._steps_done / total

    @property
    def position(self) -> int:
        """Absolute position in steps: 0 is fully down, total_steps is fully up."""
        return self.config.position_steps

    @property
    def position_fraction(self) -> float:
        """Absolute position as 0.0 (fully down) to 1.0 (fully up)."""
        total = self.config.total_steps
        if total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.config.position_steps / total))

    @property
    def at_top(self) -> bool:
        return self.config.position_steps >= self.config.total_steps

    @property
    def at_bottom(self) -> bool:
        return self.config.position_steps <= 0

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def stop(self) -> None:
        """Ask the running movement to decelerate and end early.

        Safe to call when nothing is moving; the flag is cleared before the next move.
        """
        if self.is_moving:
            logger.info("Stop requested at step %s of %s", self._steps_done, self._steps_total)
        self._stop_requested.set()

    def run_async(self, action: Callable[[], None], on_complete: Optional[Callable[[], None]] = None) -> bool:
        """Run a movement in a background thread so the UI stays responsive.

        Only one movement runs at a time; returns False if one is already active.
        """
        if self.is_moving:
            return False

        def worker() -> None:
            try:
                action()
            except Exception:  # worker-thread boundary: never swallow silently
                logger.exception("Movement failed")
            finally:
                if on_complete is not None:
                    on_complete()

        self._move_thread = threading.Thread(target=worker, daemon=True)
        self._move_thread.start()
        return True

    def wait_for_move(self, timeout: Optional[float] = None) -> None:
        """Block until the current movement finishes (mainly used by tests)."""
        thread = self._move_thread
        if thread is not None:
            thread.join(timeout)

    @staticmethod
    def calculate_sleep_from_pps(pps: float) -> float:
        if pps <= 0:
            raise ValueError("pps must be positive")
        return (1 / pps) / 2

    @staticmethod
    def _ramped_sleeptime(index: int, steps: int, ramp: int, target: float) -> float:
        if ramp <= 0:
            return target
        if index < ramp:
            progress = index / ramp
        elif index >= steps - ramp:
            progress = (steps - 1 - index) / ramp
        else:
            return target
        factor = RAMP_START_FACTOR - (RAMP_START_FACTOR - 1.0) * progress
        return target * factor

    def change_direction(self, direction: int) -> None:
        if direction > 0:
            GPIO.output(Pins.FRONT_DIR.value, Direction.DOWN.value)
            GPIO.output(Pins.BACK_DIR.value, Direction.DOWN.value)
        else:
            GPIO.output(Pins.FRONT_DIR.value, Direction.UP.value)
            GPIO.output(Pins.BACK_DIR.value, Direction.UP.value)

    def move_step(self, sleeptime: float) -> None:
        GPIO.output(Pins.FRONT_PUL.value, 1)
        GPIO.output(Pins.BACK_PUL.value, 1)
        sleep(sleeptime)
        GPIO.output(Pins.FRONT_PUL.value, 0)
        GPIO.output(Pins.BACK_PUL.value, 0)
        sleep(sleeptime)

    def move_step_single(self, pin: int, sleeptime: float) -> None:
        GPIO.output(pin, 1)
        sleep(sleeptime)
        GPIO.output(pin, 0)
        sleep(sleeptime)

    def move_steps(self, direction: int, steps: int) -> None:
        """Drive `steps` pulses, tracking the absolute position as it goes.

        A stop request ends the move early: it decelerates over up to STOP_RAMP_STEPS
        further steps, which are counted like any other, so the position stays true.
        """
        self._stop_requested.clear()
        self.change_direction(direction)
        target_sleep = self.calculate_sleep_from_pps(self.config.speed_pps)
        ramp = min(RAMP_STEPS, steps // 2)
        step_delta = -1 if direction == Direction.DOWN.value else 1
        self._steps_total = steps
        self._steps_done = 0
        stopping_at: Optional[int] = None
        for i in range(steps):
            if stopping_at is None and self._stop_requested.is_set():
                stopping_at = i
            if stopping_at is None:
                sleeptime = self._ramped_sleeptime(i, steps, ramp, target_sleep)
            else:
                sleeptime = self._stopping_sleeptime(i - stopping_at, steps - stopping_at, target_sleep)
                if sleeptime is None:
                    break
            self.move_step(sleeptime)
            self._steps_done = i + 1
            self._advance_position(step_delta)
        self._steps_total = 0
        self._steps_done = 0

    @staticmethod
    def _stopping_sleeptime(done: int, remaining: int, target: float) -> Optional[float]:
        """Deceleration curve after a stop request, or None once it has come to rest."""
        ramp = min(STOP_RAMP_STEPS, remaining)
        if done >= ramp:
            return None
        progress = done / ramp if ramp else 1.0
        return target * (1.0 + (RAMP_START_FACTOR - 1.0) * progress)

    def _advance_position(self, delta: int) -> None:
        position = self.config.position_steps + delta
        # clamped, so a miscounted step can never push the stored position out of range
        self.config.position_steps = max(0, min(self.config.total_steps, position))

    def move_steps_single(self, pin: int, direction: int, steps: int) -> None:
        self.change_direction(direction)
        sleeptime = self.calculate_sleep_from_pps(self.config.speed_pps)
        for _ in range(steps):
            self.move_step_single(pin, sleeptime)

    def move_up(self) -> None:
        """Travel the remaining way up from wherever the bed currently stands."""
        self.move_steps(Direction.UP.value, self.config.total_steps - self.config.position_steps)
        self._store_position()

    def move_down(self) -> None:
        """Travel back down from wherever the bed currently stands."""
        self.move_steps(Direction.DOWN.value, self.config.position_steps)
        self._store_position()

    def _store_position(self) -> None:
        """Persist where the bed ended up - a completed move or a stop in between."""
        self.config.bed_up = self.at_top
        self.config.save()
        logger.info("Bed at %s of %s steps", self.config.position_steps, self.config.total_steps)

    def correct_back_up(self) -> None:
        self.move_steps_single(Pins.BACK_PUL.value, Direction.UP.value, CORRECTION_STEPS)

    def correct_back_down(self) -> None:
        self.move_steps_single(Pins.BACK_PUL.value, Direction.DOWN.value, CORRECTION_STEPS)

    def correct_front_up(self) -> None:
        self.move_steps_single(Pins.FRONT_PUL.value, Direction.UP.value, CORRECTION_STEPS)

    def correct_front_down(self) -> None:
        self.move_steps_single(Pins.FRONT_PUL.value, Direction.DOWN.value, CORRECTION_STEPS)
