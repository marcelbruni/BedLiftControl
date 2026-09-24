"""Entry point: wire the config, controller and GUI together and run the app."""

import logging

from bedliftcontrol.config import Config
from bedliftcontrol.controller import BedController
from bedliftcontrol.gui import BedGui
from bedliftcontrol.history import History
from bedliftcontrol.inverter import Inverter
from bedliftcontrol.timesync import TimeSync
from bedliftcontrol.update import UpdateChecker
from bedliftcontrol.weather import WeatherService


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = Config.load()
    history = History()
    controller = BedController(config, history)
    inverter = Inverter(startup_seconds=config.inverter_startup_seconds)
    weather = WeatherService(selected=config.weather_location, history=history)
    timesync = TimeSync()
    updater = UpdateChecker()
    gui = BedGui(controller, weather, timesync, history, inverter, updater)
    weather.start()
    timesync.start()
    updater.start()
    try:
        gui.display()
    finally:
        updater.stop()
        timesync.stop()
        weather.stop()
        # releasing the pins would drop the relay anyway; doing it by name keeps the
        # switch-off in the log next to everything else the inverter did
        inverter.turn_off()
        controller.cleanup()


if __name__ == "__main__":
    main()
