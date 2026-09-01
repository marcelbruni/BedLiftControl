"""Entry point: wire the config, controller and GUI together and run the app."""

import logging

from bedliftcontrol.config import Config
from bedliftcontrol.controller import BedController
from bedliftcontrol.gui import BedGui


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = Config.load()
    controller = BedController(config)
    try:
        gui = BedGui(controller)
        gui.display()
    finally:
        controller.cleanup()


if __name__ == "__main__":
    main()
