"""The 230V inverter, switched through its potential-free remote contact.

The GPIO pin drives a relay that closes the inverter's remote terminal. Closing it only
starts the inverter - its output needs a few seconds to come up, so anything that draws
mains power has to wait for `ready`, not merely for the pin to go high.

Deliberately not persisted: after a power cut or a restart the relay is open and the
inverter stays off until someone asks for it. Restoring "on" at boot would switch mains
power on in an unattended vehicle.
"""

import logging
import time

import RPi.GPIO as GPIO

logger = logging.getLogger(__name__)

INVERTER_PIN = 17
# The inverter reports its output as stable well before the load side has settled; ten
# seconds is the upper end of what the manual's start-up takes, and waiting a moment too
# long costs nothing next to a movement that starts without power.
STARTUP_SECONDS = 10.0


class Inverter:
    def __init__(self, pin: int = INVERTER_PIN, startup_seconds: float = STARTUP_SECONDS,
                 clock=time.monotonic):
        self.pin = pin
        self.startup_seconds = startup_seconds
        self._clock = clock
        self._on = False
        self._switched_on_at = None
        self._setup_gpio()

    def _setup_gpio(self) -> None:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)

    @property
    def on(self) -> bool:
        return self._on

    @property
    def ready(self) -> bool:
        """On long enough to carry a load."""
        return self.seconds_until_ready == 0.0

    @property
    def seconds_until_ready(self) -> float:
        if not self._on:
            return self.startup_seconds
        elapsed = self._clock() - self._switched_on_at
        return max(0.0, self.startup_seconds - elapsed)

    def turn_on(self) -> bool:
        """True when this call actually started it; False when it was already running."""
        if self._on:
            return False
        GPIO.output(self.pin, GPIO.HIGH)
        self._on = True
        self._switched_on_at = self._clock()
        logger.info("Inverter switched on, ready in %.0fs", self.startup_seconds)
        return True

    def turn_off(self) -> bool:
        if not self._on:
            return False
        GPIO.output(self.pin, GPIO.LOW)
        self._on = False
        self._switched_on_at = None
        logger.info("Inverter switched off")
        return True

    def toggle(self) -> bool:
        """Returns the state it is in afterwards."""
        self.turn_off() if self._on else self.turn_on()
        return self._on
