"""Entry point: wire the config, controller and GUI together and run the app."""

from bedliftcontrol.config import Config
from bedliftcontrol.controller import BedController
from bedliftcontrol.gui import BedGui


def main():
    config = Config.load()
    controller = BedController(config)
    gui = BedGui(controller)
    gui.display()


if __name__ == "__main__":
    main()
