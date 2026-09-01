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


class BedController:
    def __init__(self, config: Config):
        self.config = config
        self._move_thread: Optional[threading.Thread] = None
        self._steps_total = 0
        self._steps_done = 0
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
        self.change_direction(direction)
        target_sleep = self.calculate_sleep_from_pps(self.config.speed_pps)
        ramp = min(RAMP_STEPS, steps // 2)
        self._steps_total = steps
        self._steps_done = 0
        for i in range(steps):
            self.move_step(self._ramped_sleeptime(i, steps, ramp, target_sleep))
            self._steps_done = i + 1
        self._steps_total = 0
        self._steps_done = 0

    def move_steps_single(self, pin: int, direction: int, steps: int) -> None:
        self.change_direction(direction)
        sleeptime = self.calculate_sleep_from_pps(self.config.speed_pps)
        for _ in range(steps):
            self.move_step_single(pin, sleeptime)

    def move_up(self) -> None:
        self.move_steps(Direction.UP.value, self.config.total_steps)
        self.config.bed_up = True
        self.config.save()

    def move_down(self) -> None:
        self.move_steps(Direction.DOWN.value, self.config.total_steps)
        self.config.bed_up = False
        self.config.save()

    def correct_back_up(self) -> None:
        self.move_steps_single(Pins.BACK_PUL.value, Direction.UP.value, CORRECTION_STEPS)

    def correct_back_down(self) -> None:
        self.move_steps_single(Pins.BACK_PUL.value, Direction.DOWN.value, CORRECTION_STEPS)

    def correct_front_up(self) -> None:
        self.move_steps_single(Pins.FRONT_PUL.value, Direction.UP.value, CORRECTION_STEPS)

    def correct_front_down(self) -> None:
        self.move_steps_single(Pins.FRONT_PUL.value, Direction.DOWN.value, CORRECTION_STEPS)
