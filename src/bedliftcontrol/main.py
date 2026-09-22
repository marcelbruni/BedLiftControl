"""Entry point: wire the config, controller and GUI together and run the app."""

import logging

from bedliftcontrol.config import Config
from bedliftcontrol.controller import BedController
from bedliftcontrol.gui import BedGui
from bedliftcontrol.history import History
from bedliftcontrol.inverter import Inverter
from bedliftcontrol.timesync import TimeSync
from bedliftcontrol.weather import WeatherService


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = Config.load()
    history = History()
    controller = BedController(config, history)
    inverter = Inverter()
    weather = WeatherService(selected=config.weather_location, history=history)
    timesync = TimeSync()
    gui = BedGui(controller, weather, timesync, history, inverter)
    weather.start()
    timesync.start()
    try:
        gui.display()
    finally:
        timesync.stop()
        weather.stop()
        controller.cleanup()


if __name__ == "__main__":
    main()
