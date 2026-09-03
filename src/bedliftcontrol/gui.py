"""CustomTkinter user interface for the bed lift. Delegates all motion to BedController."""

import logging
from enum import Enum
from tkinter import messagebox

import customtkinter as ctk

from bedliftcontrol.controller import BedController

logger = logging.getLogger(__name__)

APPEARANCE_MODE = "dark"
COLOR_THEME = "green"
PROGRESS_COLOR = "#43a047"
ARROW_FONT_SIZE = 96
BUTTON_COLOR = "#2fa572"
BUTTON_DISABLED_COLOR = "#333333"
CORRECTION_BUTTON_HEIGHT = 90

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
        self._steps_value_label = None
        self._speed_value_label = None
        self._build()

    def _build(self) -> None:
        ctk.set_appearance_mode(APPEARANCE_MODE)
        ctk.set_default_color_theme(COLOR_THEME)

        self.app = ctk.CTk()
        self.app.title("Steuerung Bettmotoren")
        self.app.geometry("800x420")

        # bottom action bar
        bottom = ctk.CTkFrame(self.app, corner_radius=0)
        bottom.pack(side="bottom", fill="x")
        ctk.CTkButton(bottom, text="⚙", width=50, command=self._settings_window).pack(side="left", padx=4, pady=6)
        ctk.CTkButton(bottom, text="↑↓", width=50, command=self._corrections_window).pack(side="left", padx=4, pady=6)
        ctk.CTkButton(bottom, text="230V on/off", width=120, command=self._not_implemented_window).pack(side="left", padx=4, pady=6)

        # left vertical progress bar (fills from the bottom as the bed rises)
        left = ctk.CTkFrame(self.app)
        left.pack(side="left", fill="y", padx=10, pady=10)
        self.progress_bar = ctk.CTkProgressBar(left, orientation="vertical", width=28, progress_color=PROGRESS_COLOR)
        self.progress_bar.pack(side="top", fill="y", expand=True, pady=(6, 4))
        self.progress_label = ctk.CTkLabel(left, text="", width=48)
        self.progress_label.pack(side="bottom", pady=4)

        # right up/down control buttons
        right = ctk.CTkFrame(self.app)
        right.pack(side="right", fill="y", padx=10, pady=10)
        arrow_font = ctk.CTkFont(size=ARROW_FONT_SIZE)
        self.up_button = ctk.CTkButton(right, text="↑", font=arrow_font, width=180, command=self._on_up)
        self.up_button.pack(side="top", fill="both", expand=True, pady=(0, 5))
        self.down_button = ctk.CTkButton(right, text="↓", font=arrow_font, width=180, command=self._on_down)
        self.down_button.pack(side="bottom", fill="both", expand=True)

        # initial state reflects the stored position
        if self.controller.config.bed_up:
            self._set_enabled(self.up_button, False)
        else:
            self._set_enabled(self.down_button, False)
        self._set_bar(1.0 if self.controller.config.bed_up else 0.0)

    @staticmethod
    def _set_enabled(widget, enabled: bool) -> None:
        widget.configure(
            state="normal" if enabled else "disabled",
            fg_color=BUTTON_COLOR if enabled else BUTTON_DISABLED_COLOR,
        )

    def _set_bar(self, fill_level: float) -> None:
        self.progress_bar.set(max(0.0, min(1.0, fill_level)))

    def _start_move(self, context: MoveContext, action) -> None:
        self._set_enabled(self.up_button, False)
        self._set_enabled(self.down_button, False)
        self._move_context = context
        self.controller.run_async(action)
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        self.app.after(POLL_INTERVAL_MS, self._poll_movement)

    def _on_up(self) -> None:
        if self.controller.is_moving:
            return
        self._start_move(MoveContext.UP, self.controller.move_up)

    def _on_down(self) -> None:
        if self.controller.is_moving:
            return
        messagebox.showinfo("Bett herunterfahren", "Motoren einschalten und Sicherungsseile lösen!")
        self._start_move(MoveContext.DOWN, self.controller.move_down)

    def _poll_movement(self) -> None:
        # runs on the main thread; update the bar until the background move finishes
        if self.controller.is_moving:
            progress = self.controller.progress
            fill = progress if self._move_context == MoveContext.UP else 1.0 - progress
            self._set_bar(fill)
            self.progress_label.configure(text=f"{round(progress * 100)}%")
            self._schedule_poll()
            return
        self.progress_label.configure(text="")
        self._set_bar(1.0 if self._move_context == MoveContext.UP else 0.0)
        if self._move_context == MoveContext.UP:
            self._set_enabled(self.up_button, False)
            self._set_enabled(self.down_button, True)
            messagebox.showinfo("Bett oben", "Sicherungsseile anbringen und Motoren ausschalten!")
        else:
            self._set_enabled(self.up_button, True)
            self._set_enabled(self.down_button, False)
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
        window.protocol("WM_DELETE_WINDOW", lambda: self._on_window_closed(name))
        self._open_windows[name] = window

    def _on_window_closed(self, name: str) -> None:
        window = self._open_windows.pop(name, None)
        if window is not None:
            window.destroy()

    def _settings_window(self) -> None:
        self._toggle_window("settings", self._build_settings_window)

    def _build_settings_window(self):
        window = ctk.CTkToplevel(self.app)
        window.title("Settings")
        window.geometry("560x160")
        content = ctk.CTkFrame(window, fg_color="transparent")
        content.pack(expand=True)
        ctk.CTkLabel(content, text="total steps").grid(row=0, column=0, padx=12, pady=12, sticky="e")
        steps_slider = ctk.CTkSlider(content, from_=STEPS_MIN, to=STEPS_MAX, width=300, command=self._on_steps_change)
        steps_slider.set(self.controller.config.total_steps)
        steps_slider.grid(row=0, column=1, padx=12, pady=12)
        self._steps_value_label = ctk.CTkLabel(content, text=str(self.controller.config.total_steps), width=60)
        self._steps_value_label.grid(row=0, column=2, padx=(4, 0))
        ctk.CTkLabel(content, text="speed pps").grid(row=1, column=0, padx=12, pady=12, sticky="e")
        speed_slider = ctk.CTkSlider(content, from_=SPEED_MIN, to=SPEED_MAX, width=300, command=self._on_speed_change)
        speed_slider.set(self.controller.config.speed_pps)
        speed_slider.grid(row=1, column=1, padx=12, pady=12)
        self._speed_value_label = ctk.CTkLabel(content, text=str(int(self.controller.config.speed_pps)), width=60)
        self._speed_value_label.grid(row=1, column=2, padx=(4, 0))
        return window

    def _on_steps_change(self, value) -> None:
        self.controller.config.total_steps = int(value)
        self.controller.config.save()
        if self._steps_value_label is not None:
            self._steps_value_label.configure(text=str(int(value)))

    def _on_speed_change(self, value) -> None:
        self.controller.config.speed_pps = float(value)
        self.controller.config.save()
        if self._speed_value_label is not None:
            self._speed_value_label.configure(text=str(int(value)))

    def _corrections_window(self) -> None:
        self._toggle_window("corrections", self._build_corrections_window)

    def _build_corrections_window(self):
        window = ctk.CTkToplevel(self.app)
        window.title("Corrections")
        window.geometry("320x320")
        content = ctk.CTkFrame(window, fg_color="transparent")
        content.pack(expand=True)
        ctk.CTkLabel(content, text="back").grid(row=0, column=0, padx=15, pady=(0, 8))
        ctk.CTkLabel(content, text="front").grid(row=0, column=1, padx=15, pady=(0, 8))
        ctk.CTkButton(content, text="↑", width=110, height=CORRECTION_BUTTON_HEIGHT, command=lambda: self._correct(self.controller.correct_back_up)).grid(row=1, column=0, padx=15, pady=8)
        ctk.CTkButton(content, text="↑", width=110, height=CORRECTION_BUTTON_HEIGHT, command=lambda: self._correct(self.controller.correct_front_up)).grid(row=1, column=1, padx=15, pady=8)
        ctk.CTkButton(content, text="↓", width=110, height=CORRECTION_BUTTON_HEIGHT, command=lambda: self._correct(self.controller.correct_back_down)).grid(row=2, column=0, padx=15, pady=8)
        ctk.CTkButton(content, text="↓", width=110, height=CORRECTION_BUTTON_HEIGHT, command=lambda: self._correct(self.controller.correct_front_down)).grid(row=2, column=1, padx=15, pady=8)
        return window

    def _not_implemented_window(self) -> None:
        self._toggle_window("not_implemented", self._build_not_implemented_window)

    def _build_not_implemented_window(self):
        window = ctk.CTkToplevel(self.app)
        window.title("Not Implemented!")
        window.geometry("260x110")
        ctk.CTkLabel(window, text="not implemented!").pack(padx=20, pady=25)
        return window

    def display(self) -> None:
        self.app.mainloop()
