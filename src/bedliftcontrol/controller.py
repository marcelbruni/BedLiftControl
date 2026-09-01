"""Hardware and motion logic for the bed lift. No GUI dependencies."""

from enum import Enum
from time import sleep
import threading

import RPi.GPIO as GPIO

from bedliftcontrol.config import Config


class Direction(Enum):
    UP = 0
    DOWN = 1


class Pins(Enum):
    FRONT_PUL = 27
    BACK_PUL = 24
    FRONT_DIR = 22
    BACK_DIR = 23


CORRECTION_STEPS = 100


class BedController:
    def __init__(self, config: Config):
        self.config = config
        self._move_thread = None
        self._setup_gpio()

    def _setup_gpio(self):
        GPIO.setmode(GPIO.BCM)                      # choose BCM for GPIO numbering
        GPIO.setup(Pins.FRONT_PUL.value, GPIO.OUT)
        GPIO.setup(Pins.FRONT_DIR.value, GPIO.OUT)
        GPIO.setup(Pins.BACK_PUL.value, GPIO.OUT)
        GPIO.setup(Pins.BACK_DIR.value, GPIO.OUT)

    @property
    def is_moving(self):
        return self._move_thread is not None and self._move_thread.is_alive()

    def run_async(self, action, on_complete=None):
        """Run a movement in a background thread so the UI stays responsive.

        Only one movement runs at a time; returns False if one is already active.
        """
        if self.is_moving:
            return False

        def worker():
            try:
                action()
            finally:
                if on_complete is not None:
                    on_complete()

        self._move_thread = threading.Thread(target=worker, daemon=True)
        self._move_thread.start()
        return True

    def wait_for_move(self, timeout=None):
        """Block until the current movement finishes (mainly used by tests)."""
        thread = self._move_thread
        if thread is not None:
            thread.join(timeout)

    @staticmethod
    def calculate_sleep_from_pps(pps):
        return (1 / pps) / 2

    def change_direction(self, direction):
        if direction > 0:
            GPIO.output(Pins.FRONT_DIR.value, Direction.DOWN.value)
            GPIO.output(Pins.BACK_DIR.value, Direction.DOWN.value)
        else:
            GPIO.output(Pins.FRONT_DIR.value, Direction.UP.value)
            GPIO.output(Pins.BACK_DIR.value, Direction.UP.value)

    def move_step(self, sleeptime):
        GPIO.output(Pins.FRONT_PUL.value, 1)
        GPIO.output(Pins.BACK_PUL.value, 1)
        sleep(sleeptime)
        GPIO.output(Pins.FRONT_PUL.value, 0)
        GPIO.output(Pins.BACK_PUL.value, 0)
        sleep(sleeptime)

    def move_step_single(self, pin, sleeptime):
        GPIO.output(pin, 1)
        sleep(sleeptime)
        GPIO.output(pin, 0)
        sleep(sleeptime)

    def move_steps(self, direction, steps):
        self.change_direction(direction)
        sleeptime = self.calculate_sleep_from_pps(self.config.speed_pps)
        for _ in range(steps):
            self.move_step(sleeptime)

    def move_steps_single(self, pin, direction, steps):
        self.change_direction(direction)
        sleeptime = self.calculate_sleep_from_pps(self.config.speed_pps)
        for _ in range(steps):
            self.move_step_single(pin, sleeptime)

    def move_up(self):
        self.move_steps(Direction.UP.value, self.config.total_steps)
        self.config.bed_up = True
        self.config.save()

    def move_down(self):
        self.move_steps(Direction.DOWN.value, self.config.total_steps)
        self.config.bed_up = False
        self.config.save()

    def correct_back_up(self):
        self.move_steps_single(Pins.BACK_PUL.value, Direction.UP.value, CORRECTION_STEPS)

    def correct_back_down(self):
        self.move_steps_single(Pins.BACK_PUL.value, Direction.DOWN.value, CORRECTION_STEPS)

    def correct_front_up(self):
        self.move_steps_single(Pins.FRONT_PUL.value, Direction.UP.value, CORRECTION_STEPS)

    def correct_front_down(self):
        self.move_steps_single(Pins.FRONT_PUL.value, Direction.DOWN.value, CORRECTION_STEPS)
