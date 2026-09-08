"""CustomTkinter user interface for the bed lift. Delegates all motion to BedController."""

import logging
import sys
from enum import Enum
from tkinter import messagebox

import customtkinter as ctk

from bedliftcontrol import icons
from bedliftcontrol.controller import BedController
from bedliftcontrol.weather import WEATHER_CODES, WeatherService

logger = logging.getLogger(__name__)

APPEARANCE_MODE = "dark"
COLOR_THEME = "green"
PROGRESS_COLOR = "#43a047"
MIN_BAR_FRACTION = 0.12  # a stub of the bar stays visible even when the bed is up
STUB_TRIM_PX = 10  # shortens that stub; converted to a fraction of the track at runtime
ICON_HEIGHT = 21  # matches the emoji glyph height; trimmed off the label's empty top so
                  # the square label stays inside the bar's rounded top cap
ARROW_FONT_SIZE = 96
BUTTON_COLOR = "#2fa572"
BUTTON_DISABLED_COLOR = "#333333"
CORRECTION_BUTTON_HEIGHT = 90

POLL_INTERVAL_MS = 100
WEATHER_UI_REFRESH_MS = 5000
FORECAST_COL_WIDTH = 50
# Emojis must be drawn with an emoji font, otherwise Tk measures them with the
# default (Roboto) font and renders them wider, which shifts them off-center.
_EMOJI_FONT = "Segoe UI Emoji" if sys.platform.startswith("win") else "Noto Color Emoji"
WEATHER_ICON_SIZE = 64      # big icon next to the current temperature
FORECAST_ICON_SIZE = 34     # one per day, must stay inside FORECAST_COL_WIDTH

# reference window listing every weather code with its icon
ICON_TABLE_ICON_SIZE = 26
ICON_TABLE_ROW_HEIGHT = 26
ICON_TABLE_PAD = 16
ICON_TABLE_COLUMNS = [  # (header, width, anchor)
    ("Code", 50, "e"),
    ("Icon", 60, "center"),
    ("Text", 250, "w"),
]

STEPS_MIN = 27000
STEPS_MAX = 30000
SPEED_MIN = 200
SPEED_MAX = 1400


def _panel_background() -> str:
    """Tk canvases cannot be transparent, so they get painted in the window colour."""
    color = ctk.ThemeManager.theme["CTk"]["fg_color"]
    if isinstance(color, (list, tuple)):
        return color[1] if APPEARANCE_MODE == "dark" else color[0]
    return color


class MoveContext(Enum):
    UP = "up"
    DOWN = "down"


class BedGui:
    def __init__(self, controller: BedController, weather: WeatherService):
        self.controller = controller
        self.weather = weather
        self._move_context: MoveContext | None = None
        self._bar_fill_level = 0.0
        self._open_windows: dict[str, object] = {}
        self._steps_value_label = None
        self._speed_value_label = None
        self._forecast_labels = []
        self._rendered_forecast_key = None
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
        ctk.CTkButton(bottom, text="Wetter-Icons", width=120, command=self._weather_icons_window).pack(side="left", padx=4, pady=6)

        # left vertical bar: empty when the bed is up, fills from the top down as the
        # bed is lowered (custom, since CTkProgressBar only ever fills from the bottom)
        left = ctk.CTkFrame(self.app)
        left.pack(side="left", fill="y", padx=10, pady=10)
        self.progress_track = ctk.CTkFrame(left, width=28, fg_color="#3a3a3a", corner_radius=10)
        self.progress_track.pack(side="top", fill="y", expand=True, padx=6, pady=(6, 4))
        self.progress_track.pack_propagate(False)
        self.progress_track.bind("<Configure>", lambda _event: self._set_bar(self._bar_fill_level))
        self.progress_fill = ctk.CTkFrame(self.progress_track, fg_color=PROGRESS_COLOR, corner_radius=10)
        # bed icon rides on the bottom edge of the green fill (moves with it automatically).
        # ICON_HEIGHT shrinks the label from CTk's default 28px, anchor="s" keeps the glyph
        # on the bottom edge, so the trim comes off the empty top - otherwise the label's
        # square green box would overdraw the rounded top cap of the bar.
        self.bed_icon = ctk.CTkLabel(self.progress_fill, text="🛏", font=ctk.CTkFont(family=_EMOJI_FONT, size=16), fg_color="transparent", height=ICON_HEIGHT, anchor="s")
        self.bed_icon.place(relx=0.5, rely=1.0, y=-4, anchor="s")
        self.progress_label = ctk.CTkLabel(left, text="", width=48)
        self.progress_label.pack(side="bottom", pady=4)

        # center weather panel: two independent blocks stacked in one column
        center = ctk.CTkFrame(self.app, fg_color="transparent")
        center.pack(side="left", fill="both", expand=True, padx=20, pady=(20, 0))
        self._build_current_panel(center)
        self._build_forecast_panel(center)
        # last-updated line belongs to neither block, it reports the age of the fetch
        self.weather_updated = ctk.CTkLabel(center, text="", font=ctk.CTkFont(size=11), text_color="#888888")
        self.weather_updated.pack(side="bottom", pady=(0, 4))

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
        self._refresh_weather()

    @staticmethod
    def _set_enabled(widget, enabled: bool) -> None:
        widget.configure(
            state="normal" if enabled else "disabled",
            fg_color=BUTTON_COLOR if enabled else BUTTON_DISABLED_COLOR,
        )

    def _stub_trim(self) -> float:
        """STUB_TRIM_PX as a fraction of the track, 0.0 while the track has no size yet."""
        height = self.progress_track.winfo_height()
        if height <= 1:
            return 0.0
        return STUB_TRIM_PX / height

    def _set_bar(self, fill_level: float) -> None:
        # inverted + top-anchored: a stub stays visible when the bed is up, fills from
        # the top down as the bed is lowered
        self._bar_fill_level = fill_level
        fraction = 1.0 - max(0.0, min(1.0, fill_level))
        # map [0,1] onto [MIN_BAR_FRACTION,1.0] so the fill keeps moving over the whole
        # travel instead of freezing on the stub for the last few percent
        relheight = MIN_BAR_FRACTION + fraction * (1.0 - MIN_BAR_FRACTION)
        # trim the stub only: full weight when the bed is up, gone when it is fully down,
        # so the bar still reaches the bottom of the track
        relheight -= self._stub_trim() * (1.0 - fraction)
        self.progress_fill.place(relx=0, rely=0, relwidth=1.0, relheight=relheight, anchor="nw")

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

    def _weather_icons_window(self) -> None:
        self._toggle_window("weather_icons", self._build_weather_icons_window)

    def _build_weather_icons_window(self):
        """Reference list of every WMO code with both of its icons, for eyeballing them
        side by side. Sized to fit all rows at once, so the whole table screenshots."""
        window = ctk.CTkToplevel(self.app)
        window.title("Wetter-Icons")
        content = ctk.CTkFrame(window, fg_color="transparent")
        content.pack(padx=ICON_TABLE_PAD, pady=ICON_TABLE_PAD)

        header_font = ctk.CTkFont(size=13, weight="bold")
        for column, (title, width, anchor) in enumerate(ICON_TABLE_COLUMNS):
            ctk.CTkLabel(content, text=title, font=header_font, width=width, anchor=anchor).grid(
                row=0, column=column, padx=6, pady=(0, 6), sticky="ew"
            )
        for row, (code, (description, icon_key)) in enumerate(WEATHER_CODES.items(), start=1):
            for column, text in ((0, str(code)), (2, description)):
                _, width, anchor = ICON_TABLE_COLUMNS[column]
                ctk.CTkLabel(content, text=text, width=width, anchor=anchor, height=ICON_TABLE_ROW_HEIGHT).grid(
                    row=row, column=column, padx=6, sticky="ew"
                )
            icon = icons.IconCanvas(content, size=ICON_TABLE_ICON_SIZE, background=_panel_background())
            icon.show(icon_key)
            icon.grid(row=row, column=1, padx=6)

        # size the window to whatever the table actually needs, so nothing is cut off
        window.update_idletasks()
        window.geometry(f"{content.winfo_reqwidth() + 2 * ICON_TABLE_PAD}x{content.winfo_reqheight() + 2 * ICON_TABLE_PAD}")
        return window

    def _refresh_weather(self) -> None:
        """Pull the latest reading and hand it to each block, then re-arm the timer."""
        weather = self.weather.current
        if weather is not None:
            self._update_current_panel(weather)
            self._render_forecast(weather.daily)
            self.weather_updated.configure(text="Stand: " + weather.fetched_at.replace("T", " "))
        self.app.after(WEATHER_UI_REFRESH_MS, self._refresh_weather)

    # --- block 1: current conditions ---------------------------------------
    # Owns self.current_frame and nothing outside it, so it can be rebuilt, restyled or
    # hidden without touching the forecast below.

    def _build_current_panel(self, parent) -> None:
        self.current_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.current_frame.pack(fill="x", pady=(20, 0))
        self.weather_city = ctk.CTkLabel(self.current_frame, text="", font=ctk.CTkFont(size=22))
        self.weather_city.pack()
        weather_row = ctk.CTkFrame(self.current_frame, fg_color="transparent")
        weather_row.pack(pady=6, padx=(40, 0))  # left pad shifts the centred group ~20px right
        self.weather_icon = icons.IconCanvas(weather_row, size=WEATHER_ICON_SIZE, background=_panel_background())
        self.weather_icon.pack(side="left", padx=(0, 20))
        self.weather_temp = ctk.CTkLabel(weather_row, text="", font=ctk.CTkFont(size=52))
        self.weather_temp.pack(side="left", padx=(20, 0))
        self.weather_desc = ctk.CTkLabel(self.current_frame, text="", font=ctk.CTkFont(size=16))
        self.weather_desc.pack()

    def _update_current_panel(self, weather) -> None:
        """Conditions right now - a point in time, not the day as a whole."""
        self.weather_city.configure(text=weather.city)
        self.weather_icon.show(weather.icon)
        self.weather_temp.configure(text=f"{round(weather.temperature)}°C")
        self.weather_desc.configure(text=weather.description)

    # --- block 2: seven day forecast ---------------------------------------
    # Owns self.forecast_frame and self._forecast_labels, driven purely by the daily list.

    def _build_forecast_panel(self, parent) -> None:
        self.forecast_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.forecast_frame.pack(pady=(18, 0))

    def _render_forecast(self, daily) -> None:
        key = [(day.date, day.icon, day.temp_max, day.temp_min, day.rain) for day in daily]
        if key == self._rendered_forecast_key:
            return
        self._rendered_forecast_key = key
        for label in self._forecast_labels:
            label.destroy()
        self._forecast_labels = []
        for index, day in enumerate(daily):
            self.forecast_frame.grid_columnconfigure(index, weight=1, uniform="forecast", minsize=FORECAST_COL_WIDTH)
            rows = [
                (day.day, ctk.CTkFont(size=13, weight="bold"), None),
                (f"{round(day.temp_max)}°", ctk.CTkFont(size=12), None),
                (f"{round(day.temp_min)}°", ctk.CTkFont(size=12), "#888888"),
            ]
            if day.rain is not None:
                rows.append((f"💧 {day.rain}%", ctk.CTkFont(size=12), "#5aa0e0"))
            # the icon is drawn, not text, so it gets its own row between name and temps
            icon = icons.IconCanvas(self.forecast_frame, size=FORECAST_ICON_SIZE, background=_panel_background())
            icon.show(day.icon)
            icon.grid(row=1, column=index, padx=8, pady=2)
            self._forecast_labels.append(icon)
            for row, (text, font, color) in enumerate(rows):
                label = ctk.CTkLabel(self.forecast_frame, text=text, anchor="center", font=font, text_color=color)
                label.grid(row=row if row == 0 else row + 1, column=index, padx=8, pady=1, sticky="ew")
                self._forecast_labels.append(label)

    def display(self) -> None:
        self.app.mainloop()
