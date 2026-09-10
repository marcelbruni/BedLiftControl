"""CustomTkinter user interface for the bed lift. Delegates all motion to BedController."""

import logging
import sys
from enum import Enum
from tkinter import messagebox

import customtkinter as ctk

from bedliftcontrol import clock, icons
from bedliftcontrol.controller import BedController
from bedliftcontrol.timesync import TimeSync
from bedliftcontrol.weather import LOCATIONS, WEATHER_CODES, WeatherService, location_or_default

logger = logging.getLogger(__name__)

WINDOW_GEOMETRY = "800x420"  # the Pi 7" display is 800x480, kiosk mode takes all of it
APPEARANCE_MODE = "dark"
COLOR_THEME = "green"
PROGRESS_COLOR = "#43a047"
MIN_BAR_FRACTION = 0.12  # a stub of the bar stays visible even when the bed is up
STUB_TRIM_PX = 10  # shortens that stub; converted to a fraction of the track at runtime
ICON_HEIGHT = 21  # matches the emoji glyph height; trimmed off the label's empty top so
                  # the square label stays inside the bar's rounded top cap
ARROW_FONT_SIZE = 96
# "STOP" is four glyphs wide, not one arrow: at the arrow size it measures 348px in
# a 180px button and gets clipped on both sides. 40 measures 143px.
STOP_FONT_SIZE = 40
BUTTON_COLOR = "#2fa572"
BUTTON_DISABLED_COLOR = "#333333"
STOP_BUTTON_COLOR = "#c62828"
STOP_BUTTON_HOVER_COLOR = "#8e1f1f"
CORRECTION_BUTTON_HEIGHT = 90
# Held longer than this and the correction runs on until the button is let go;
# released sooner and it is a plain click worth CORRECTION_STEPS.
CORRECTION_HOLD_DELAY_MS = 400
LOCATION_BUTTON_WIDTH = 260
LOCATION_BUTTON_HEIGHT = 44

POLL_INTERVAL_MS = 100
WEATHER_UI_REFRESH_MS = 5000
CLOCK_TICK_MS = 1000  # the display shows seconds, so it has to tick once a second
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
# The Pi panel is 800x480; leave room for the title bar so the window fits whole and
# the table scrolls inside it instead of running off the bottom of the screen.
ICON_TABLE_SCREEN_MARGIN = 70
ICON_TABLE_ROW_PITCH = ICON_TABLE_ROW_HEIGHT + 4  # row height plus the grid pady
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
    def __init__(self, controller: BedController, weather: WeatherService,
                 timesync: TimeSync | None = None):
        self.controller = controller
        self.weather = weather
        # own default so existing callers keep working; it touches no network until started
        self.timesync = timesync if timesync is not None else TimeSync()
        self._move_context: MoveContext | None = None
        self._bar_fill_level = 0.0
        self._clock_text = None
        self._kiosk_button = None
        self._correction_timer = None
        self._correction_holding = False
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
        self.app.geometry(WINDOW_GEOMETRY)
        # a touch display has no keyboard, but on a dev machine Escape is a quick way out
        self.app.bind("<Escape>", lambda _event: self._leave_kiosk())

        # bottom action bar
        bottom = ctk.CTkFrame(self.app, corner_radius=0)
        bottom.pack(side="bottom", fill="x")
        ctk.CTkButton(bottom, text="⚙", width=50, command=self._settings_window).pack(side="left", padx=4, pady=6)
        self.corrections_button = ctk.CTkButton(bottom, text="↑↓", width=50, command=self._corrections_window)
        self.corrections_button.pack(side="left", padx=4, pady=6)
        ctk.CTkButton(bottom, text="230V on/off", width=120, command=self._not_implemented_window).pack(side="left", padx=4, pady=6)
        ctk.CTkButton(bottom, text="Wetter-Icons", width=120, command=self._weather_icons_window).pack(side="left", padx=4, pady=6)
        self.location_button = ctk.CTkButton(bottom, text="Ort", width=70, command=self._location_window)
        self.location_button.pack(side="left", padx=4, pady=6)
        self._build_clock_panel(bottom)

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
        self.control_frame = ctk.CTkFrame(self.app)
        self.control_frame.pack(side="right", fill="y", padx=10, pady=10)
        arrow_font = ctk.CTkFont(size=ARROW_FONT_SIZE)
        self.up_button = ctk.CTkButton(self.control_frame, text="↑", font=arrow_font, width=180, command=self._on_up)
        self.up_button.pack(side="top", fill="both", expand=True, pady=(0, 5))
        self.down_button = ctk.CTkButton(self.control_frame, text="↓", font=arrow_font, width=180, command=self._on_down)
        self.down_button.pack(side="bottom", fill="both", expand=True)
        # built once and placed over both arrows while a movement runs
        self.stop_button = ctk.CTkButton(
            self.control_frame, text="STOP",
            font=ctk.CTkFont(size=STOP_FONT_SIZE, weight="bold"), width=180,
            fg_color=STOP_BUTTON_COLOR, hover_color=STOP_BUTTON_HOVER_COLOR,
            command=self._on_stop,
        )

        # initial state reflects the stored position
        self._update_move_buttons()
        self._update_corrections_button()
        self._set_bar(self.controller.position_fraction)
        self._update_clock()
        self._refresh_weather()
        self._apply_window_mode()

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

    @staticmethod
    def _descent_percent(position_fraction: float) -> int:
        """How far down the bed is: 0% parked at the top, 100% all the way down.

        Inverted against the position so it counts up while lowering and down while
        raising, which matches the bar - full green is the bed at the bottom.
        """
        return round((1.0 - position_fraction) * 100)

    def _update_move_buttons(self) -> None:
        """An arrow is only dead at the very end of its travel; a stop in between leaves
        both live, so the bed can carry on or turn back."""
        self._set_enabled(self.up_button, not self.controller.at_top)
        self._set_enabled(self.down_button, not self.controller.at_bottom)

    def _update_corrections_button(self) -> None:
        """Corrections only make sense against an end stop, judged by eye on the bed
        itself. So the window can only be opened while the bed is parked fully up or
        fully down and nothing is moving - not mid travel, and not after a stop."""
        at_end_stop = self.controller.at_top or self.controller.at_bottom
        self._set_enabled(self.corrections_button, at_end_stop and not self.controller.is_moving)

    def _show_stop_button(self) -> None:
        # place, not pack: it covers the whole frame and both arrows underneath it
        self.stop_button.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self.stop_button.lift()

    def _hide_stop_button(self) -> None:
        self.stop_button.place_forget()

    def _on_stop(self) -> None:
        self.controller.stop()

    def _start_move(self, context: MoveContext, action) -> None:
        self._set_enabled(self.up_button, False)
        self._set_enabled(self.down_button, False)
        self._set_enabled(self.corrections_button, False)
        # the bed is about to leave its end stop, so a correction window still standing
        # open would be aimed at a position that no longer exists
        self._on_window_closed("corrections")
        self._show_stop_button()
        self._move_context = context
        self.controller.run_async(action)
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        self.app.after(POLL_INTERVAL_MS, self._poll_movement)

    def _on_up(self) -> None:
        if self.controller.is_moving:
            return
        # Parked at the bottom the motors are off, so ask before anything moves.
        # askokcancel, not showinfo: it is the one that reliably reports a dismissed
        # dialog as False on both Windows and the Pi, and closing it must change nothing.
        if self.controller.at_bottom:
            if not messagebox.askokcancel("Bett hochfahren", "Motoren einschalten."):
                return
        self._start_move(MoveContext.UP, self.controller.move_up)

    def _on_down(self) -> None:
        if self.controller.is_moving:
            return
        # only worth saying when the bed is actually parked at the top: that is when the
        # ropes are attached and the motors are off. Carrying on after a stop in between
        # means both are already done.
        if self.controller.at_top:
            messagebox.showinfo("Bett herunterfahren", "Motoren einschalten und Sicherungsseile lösen!")
        self._start_move(MoveContext.DOWN, self.controller.move_down)

    def _poll_movement(self) -> None:
        # runs on the main thread; follow the absolute position until the move finishes.
        # absolute, not per-move progress: a move that starts half way up would otherwise
        # send the bar back to the bottom before climbing again
        if self.controller.is_moving:
            fraction = self.controller.position_fraction
            self._set_bar(fraction)
            self.progress_label.configure(text=f"{self._descent_percent(fraction)}%")
            self._schedule_poll()
            return
        self._hide_stop_button()
        self.progress_label.configure(text="")
        self._set_bar(self.controller.position_fraction)
        self._update_move_buttons()
        self._update_corrections_button()
        # only prompt when the bed really arrived at an end stop - after a stop in
        # between it is hanging somewhere and either prompt would be plain wrong
        if self._move_context == MoveContext.UP and self.controller.at_top:
            messagebox.showinfo("Bett oben", "Sicherungsseile anbringen und Motoren ausschalten!")
        elif self._move_context == MoveContext.DOWN and self.controller.at_bottom:
            messagebox.showinfo("Bett unten", "Motoren ausschalten. Gute Nacht!")
        self._move_context = None

    def _correct(self, action) -> None:
        if self.controller.is_moving:
            return
        self.controller.run_async(action)

    # --- correction buttons: click for a fixed nudge, hold to keep going ----
    # Only one button can be pressed at a time on a touch panel, so the pending timer
    # and the holding flag live on the instance rather than per button.

    def _bind_correction(self, button, click_action, hold_action) -> None:
        button.bind("<ButtonPress-1>", lambda _event: self._correction_pressed(hold_action))
        button.bind("<ButtonRelease-1>", lambda _event: self._correction_released(click_action))

    def _correction_pressed(self, hold_action) -> None:
        self._cancel_correction_timer()
        self._correction_holding = False
        self._correction_timer = self.app.after(
            CORRECTION_HOLD_DELAY_MS, lambda: self._correction_hold_begins(hold_action)
        )

    def _correction_hold_begins(self, hold_action) -> None:
        self._correction_timer = None
        self._correction_holding = True
        self._correct(hold_action)

    def _correction_released(self, click_action) -> None:
        if self._correction_timer is not None:
            # let go before the threshold, so it was a click: the fixed step count
            self._cancel_correction_timer()
            self._correct(click_action)
        else:
            self._end_correction_hold()

    def _end_correction_hold(self) -> None:
        if self._correction_holding:
            self._correction_holding = False
            self.controller.stop()

    def _cancel_correction_timer(self) -> None:
        if self._correction_timer is not None:
            self.app.after_cancel(self._correction_timer)
            self._correction_timer = None

    def _toggle_window(self, name: str, builder) -> None:
        window = self._open_windows.get(name)
        if window is not None:
            self._on_window_closed(name)
            return
        window = builder()
        window.protocol("WM_DELETE_WINDOW", lambda: self._on_window_closed(name))
        # in kiosk mode the main window covers the screen, so a child window would open
        # behind it - and the settings window is the only way back out on a touch display
        window.transient(self.app)
        window.lift()
        if self.controller.config.kiosk:
            window.attributes("-topmost", True)
        self._open_windows[name] = window

    def _on_window_closed(self, name: str) -> None:
        window = self._open_windows.pop(name, None)
        if name == "settings":
            self._kiosk_button = None
        if name == "corrections":
            # the buttons are about to be destroyed, so no release event is coming
            self._cancel_correction_timer()
            self._end_correction_hold()
        self._correction_timer = None
        self._correction_holding = False
        if window is not None:
            window.destroy()

    def _settings_window(self) -> None:
        self._toggle_window("settings", self._build_settings_window)

    def _build_settings_window(self):
        window = ctk.CTkToplevel(self.app)
        window.title("Settings")
        window.geometry("560x220")
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
        self._kiosk_button = ctk.CTkButton(content, text=self._kiosk_button_text(), width=300,
                                           command=self._toggle_kiosk)
        self._kiosk_button.grid(row=2, column=0, columnspan=3, padx=12, pady=(16, 12))
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
        # no command=: a click and a hold have to be told apart, which needs the press
        # and release events. See _bind_correction.
        buttons = [
            ("↑", 1, 0, self.controller.correct_back_up, self.controller.hold_back_up),
            ("↑", 1, 1, self.controller.correct_front_up, self.controller.hold_front_up),
            ("↓", 2, 0, self.controller.correct_back_down, self.controller.hold_back_down),
            ("↓", 2, 1, self.controller.correct_front_down, self.controller.hold_front_down),
        ]
        for text, row, column, click_action, hold_action in buttons:
            button = ctk.CTkButton(content, text=text, width=110, height=CORRECTION_BUTTON_HEIGHT)
            button.grid(row=row, column=column, padx=15, pady=8)
            self._bind_correction(button, click_action, hold_action)
        return window

    def _not_implemented_window(self) -> None:
        self._toggle_window("not_implemented", self._build_not_implemented_window)

    def _build_not_implemented_window(self):
        window = ctk.CTkToplevel(self.app)
        window.title("Not Implemented!")
        window.geometry("260x110")
        ctk.CTkLabel(window, text="not implemented!").pack(padx=20, pady=25)
        return window

    def _location_window(self) -> None:
        self._toggle_window("location", self._build_location_window)

    def _build_location_window(self):
        window = ctk.CTkToplevel(self.app)
        window.title("Ort")
        content = ctk.CTkFrame(window, fg_color="transparent")
        content.pack(padx=ICON_TABLE_PAD, pady=ICON_TABLE_PAD)
        selected = self.weather.selected
        for row, location in enumerate(LOCATIONS):
            active = location.key == selected
            ctk.CTkButton(
                content,
                text=location.label,
                width=LOCATION_BUTTON_WIDTH,
                height=LOCATION_BUTTON_HEIGHT,
                fg_color=BUTTON_COLOR if active else BUTTON_DISABLED_COLOR,
                command=lambda key=location.key: self._select_location(key),
            ).grid(row=row, column=0, padx=6, pady=4)
        return window

    def _select_location(self, key: str) -> None:
        self.weather.select(key)
        self.controller.config.weather_location = key
        self.controller.config.save()
        self._on_window_closed("location")
        self._apply_weather()

    def _weather_icons_window(self) -> None:
        self._toggle_window("weather_icons", self._build_weather_icons_window)

    @staticmethod
    def _icon_table_visible_height(screen_height: int, rows: int) -> int:
        """How much of the table is on screen at once - the rest is scrolled to.

        Budgeted so the finished window (this plus the padding above and below) still
        fits the screen with room for the title bar, which the 800x480 Pi panel needs.
        """
        available = screen_height - ICON_TABLE_SCREEN_MARGIN - 2 * ICON_TABLE_PAD
        wanted = (rows + 1) * ICON_TABLE_ROW_PITCH  # +1 for the header row
        return max(ICON_TABLE_ROW_PITCH, min(wanted, available))

    def _build_weather_icons_window(self):
        """Reference list of every WMO code with its icon.

        The table is taller than the Pi's 480px panel, so it lives in a scrollable frame
        and the window is capped to the screen height.
        """
        window = ctk.CTkToplevel(self.app)
        window.title("Wetter-Icons")
        table_width = sum(width for _, width, _ in ICON_TABLE_COLUMNS) + 12 * len(ICON_TABLE_COLUMNS)
        visible_height = self._icon_table_visible_height(window.winfo_screenheight(), len(WEATHER_CODES))
        content = ctk.CTkScrollableFrame(window, fg_color="transparent",
                                         width=table_width, height=visible_height)
        content.pack(fill="both", expand=True, padx=ICON_TABLE_PAD, pady=ICON_TABLE_PAD)

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

        # size the window to the visible part of the table; the rest is scrolled to
        window.update_idletasks()
        window.geometry(f"{content.winfo_reqwidth() + 2 * ICON_TABLE_PAD}"
                        f"x{visible_height + 2 * ICON_TABLE_PAD}")
        return window

    def _refresh_weather(self) -> None:
        self._apply_weather()
        self.app.after(WEATHER_UI_REFRESH_MS, self._refresh_weather)

    def _apply_weather(self) -> None:
        """Hand the selected reading to both blocks. Separate from the timer above so a
        location change can apply immediately without starting a second timer chain."""
        weather = self.weather.current
        if weather is None:
            self._show_reading_missing()
            return
        self._update_current_panel(weather)
        self._render_forecast(weather.daily)
        self.weather_updated.configure(text="Stand: " + weather.fetched_at.replace("T", " "))

    def _show_reading_missing(self) -> None:
        """A location that has not been fetched yet must not keep showing the previous
        one's numbers."""
        self.weather_city.configure(text=location_or_default(self.weather.selected).label)
        self.weather_icon.show("unknown")
        self.weather_temp.configure(text="")
        self.weather_desc.configure(text="Noch keine Daten")
        self.weather_updated.configure(text="")
        self._render_forecast([])

    # --- window mode -------------------------------------------------------

    def _apply_window_mode(self) -> None:
        """Fullscreen covers the whole 800x480 panel; windowed restores the fixed size."""
        kiosk = self.controller.config.kiosk
        self.app.attributes("-fullscreen", kiosk)
        if not kiosk:
            self.app.geometry(WINDOW_GEOMETRY)

    def _toggle_kiosk(self) -> None:
        self.controller.config.kiosk = not self.controller.config.kiosk
        self.controller.config.save()
        self._apply_window_mode()
        self._refresh_kiosk_button()

    def _leave_kiosk(self) -> None:
        if not self.controller.config.kiosk:
            return
        self._toggle_kiosk()

    def _kiosk_button_text(self) -> str:
        return "Kiosk-Modus ausschalten" if self.controller.config.kiosk else "Kiosk-Modus einschalten"

    def _refresh_kiosk_button(self) -> None:
        if self._kiosk_button is not None:
            self._kiosk_button.configure(text=self._kiosk_button_text())

    # --- block 3: clock ----------------------------------------------------
    # Owns self.clock_date and self.clock_time, driven by its own timer. It does not go
    # through _refresh_weather on purpose - that one returns early without a reading,
    # which is exactly when the clock still has to tick.

    def _build_clock_panel(self, parent) -> None:
        self.clock_time = ctk.CTkLabel(parent, text="", font=ctk.CTkFont(size=20, weight="bold"))
        self.clock_time.pack(side="right", padx=(6, 12))
        self.clock_date = ctk.CTkLabel(parent, text="", font=ctk.CTkFont(size=13), text_color="#888888")
        self.clock_date.pack(side="right")

    def _update_clock(self) -> None:
        moment = self.timesync.now()
        text = (clock.format_date(moment), clock.format_time(moment))
        if text != self._clock_text:  # guards against two ticks landing in one second
            self._clock_text = text
            self.clock_date.configure(text=text[0])
            self.clock_time.configure(text=text[1])
        self.app.after(self._ms_to_next_second(moment), self._update_clock)

    @staticmethod
    def _ms_to_next_second(moment) -> int:
        """A fixed 1000ms interval slowly drifts off the second boundary and then skips
        a displayed second. Aiming at the next boundary instead keeps the tick honest."""
        return max(50, CLOCK_TICK_MS - moment.microsecond // 1000)

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
