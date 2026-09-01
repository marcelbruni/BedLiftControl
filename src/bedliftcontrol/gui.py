"""guizero user interface for the bed lift. Delegates all motion to BedController."""

import logging
from enum import Enum

from guizero import App, Box, Text, PushButton, info, Slider, Window

from bedliftcontrol.controller import BedController

logger = logging.getLogger(__name__)

BACKGROUND_COLOR = "dim grey"
TEXT_COLOR = "white"
PROGRESS_LABEL = "moving: "

POLL_INTERVAL_MS = 100
STEPS_MIN = 27000
STEPS_MAX = 30000
SPEED_MIN = 200
SPEED_MAX = 1400


class MoveContext(Enum):
    UP = "up"
    DOWN = "down"


class BedGui:
    def __init__(self, controller: BedController):
        self.controller = controller
        self._move_context: MoveContext | None = None
        self._open_windows: dict[str, object] = {}
        self._build()

    def _build(self) -> None:
        self.app = App(title="Steuerung Bettmotoren", width=800, height=420, bg=BACKGROUND_COLOR)
        self.app.font = "Piboto Bold"
        self.app.text_color = TEXT_COLOR

        # up/down control buttons
        updown_box = Box(self.app, height="fill", align="right", border=True)
        updown_box.text_color = TEXT_COLOR
        self.up_button = PushButton(updown_box, align="top", width=1, height=1, command=self._on_up, text="↑")
        self.up_button.text_size = 118
        self.down_button = PushButton(updown_box, align="bottom", width=1, height=1, command=self._on_down, text="↓")
        self.down_button.text_size = 118

        # content box (progress only)
        main_box = Box(self.app, layout="grid", align="top", width="fill", height="370", border=True)
        main_box.bg = BACKGROUND_COLOR
        main_box.text_color = TEXT_COLOR
        content_box = Box(main_box, grid=[0, 0], layout="grid", align="top", width="fill", height="370", border=False)
        self.progress_text = Text(content_box, grid=[0, 0], align="left", text="", font="Piboto")

        # bottom button bar
        button_box = Box(self.app, width="fill", height=50, align="bottom", border=True)
        button_box.bg = BACKGROUND_COLOR
        button_box.text_color = TEXT_COLOR
        PushButton(button_box, align="left", width=2, command=self._settings_window, text="⚙")
        PushButton(button_box, align="left", width=2, command=self._corrections_window, text="↑↓")
        PushButton(button_box, align="left", width=10, command=self._not_implemented_window, text="230V on/off")

        # initial enabled state reflects the stored position
        if self.controller.config.bed_up:
            self.up_button.enabled = False
        else:
            self.down_button.enabled = False

    def _start_move(self, context: MoveContext, action) -> None:
        self.up_button.enabled = False
        self.down_button.enabled = False
        self._move_context = context
        self.controller.run_async(action)
        self.app.repeat(POLL_INTERVAL_MS, self._poll_movement)

    def _on_up(self) -> None:
        if self.controller.is_moving:
            return
        self._start_move(MoveContext.UP, self.controller.move_up)

    def _on_down(self) -> None:
        if self.controller.is_moving:
            return
        info("Bett herunterfahren", "Motoren einschalten und Sicherungsseile lösen!")
        self._start_move(MoveContext.DOWN, self.controller.move_down)

    def _poll_movement(self) -> None:
        # runs on the main thread; update progress until the background move finishes
        if self.controller.is_moving:
            self.progress_text.value = PROGRESS_LABEL + str(round(self.controller.progress * 100)) + "%"
            return
        self.app.cancel(self._poll_movement)
        self.progress_text.value = ""
        if self._move_context == MoveContext.UP:
            self.up_button.enabled = False
            self.down_button.enabled = True
            info("Bett oben", "Sicherungsseile anbringen und Motoren ausschalten!")
        else:
            self.up_button.enabled = True
            self.down_button.enabled = False
        self._move_context = None

    def _correct(self, action) -> None:
        if self.controller.is_moving:
            return
        self.controller.run_async(action)

    def _toggle_window(self, name: str, builder) -> None:
        window = self._open_windows.get(name)
        if window is not None:
            self._open_windows.pop(name, None)
            window.destroy()
            return
        window = builder()
        window.when_closed = lambda: self._on_window_closed(name)
        self._open_windows[name] = window

    def _on_window_closed(self, name: str) -> None:
        window = self._open_windows.pop(name, None)
        if window is not None:
            window.destroy()

    def _settings_window(self) -> None:
        self._toggle_window("settings", self._build_settings_window)

    def _build_settings_window(self):
        window = Window(self.app, layout="grid", width="575", height="150", bg=BACKGROUND_COLOR, title="Settings")
        Text(window, grid=[0, 0], align="right", text="total steps", font="Piboto")
        Text(window, grid=[0, 1], align="right", text="speed pps", font="Piboto")
        steps_slider = Slider(window, grid=[1, 0], align="left", height="40", width="488", start=STEPS_MIN, end=STEPS_MAX, command=self._on_steps_change)
        steps_slider.value = self.controller.config.total_steps
        steps_slider.text_size = 12
        speed_slider = Slider(window, grid=[1, 1], align="left", height="40", width="488", start=SPEED_MIN, end=SPEED_MAX, command=self._on_speed_change)
        speed_slider.value = self.controller.config.speed_pps
        speed_slider.text_size = 12
        return window

    def _on_steps_change(self, value) -> None:
        self.controller.config.total_steps = int(value)
        self.controller.config.save()

    def _on_speed_change(self, value) -> None:
        self.controller.config.speed_pps = float(value)
        self.controller.config.save()

    def _corrections_window(self) -> None:
        self._toggle_window("corrections", self._build_corrections_window)

    def _build_corrections_window(self):
        text_size = 28
        button_width = 10
        button_height = 3
        window = Window(self.app, layout="grid", width="590", height="350", bg=BACKGROUND_COLOR, title="Corrections")
        Text(window, grid=[0, 0], text="  ")
        Text(window, grid=[1, 0], text="back correction")
        Text(window, grid=[2, 0], text="     ")
        Text(window, grid=[3, 0], text="front correction")
        Text(window, grid=[0, 1], text="  ")
        back_up_button = PushButton(window, grid=[1, 1], width=button_width, height=button_height, command=lambda: self._correct(self.controller.correct_back_up), text="↑")
        back_up_button.text_size = text_size
        Text(window, grid=[2, 1], text="     ")
        front_up_button = PushButton(window, grid=[3, 1], width=button_width, height=button_height, command=lambda: self._correct(self.controller.correct_front_up), text="↑")
        front_up_button.text_size = text_size
        Text(window, grid=[0, 2], text="  ")
        back_down_button = PushButton(window, grid=[1, 2], width=button_width, height=button_height, command=lambda: self._correct(self.controller.correct_back_down), text="↓")
        back_down_button.text_size = text_size
        Text(window, grid=[2, 2], text="     ")
        front_down_button = PushButton(window, grid=[3, 2], width=button_width, height=button_height, command=lambda: self._correct(self.controller.correct_front_down), text="↓")
        front_down_button.text_size = text_size
        return window

    def _not_implemented_window(self) -> None:
        self._toggle_window("not_implemented", self._build_not_implemented_window)

    def _build_not_implemented_window(self):
        window = Window(self.app, width="200", height="40", bg=BACKGROUND_COLOR, title="Not Implemented!")
        Text(window, text="not implemented!")
        return window

    def display(self) -> None:
        self.app.display()
