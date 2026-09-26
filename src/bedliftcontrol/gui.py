"""CustomTkinter user interface for the bed lift. Delegates all motion to BedController."""

from __future__ import annotations

import logging
import math
import os
import sys
import threading
import time
import tkinter
from datetime import datetime
from enum import Enum
from tkinter import messagebox

import customtkinter as ctk

from bedliftcontrol import clock, icons
from bedliftcontrol.config import (
    INVERTER_STARTUP_MAX,
    INVERTER_STARTUP_MIN,
    ROPE_DELAY_MAX,
    ROPE_DELAY_MIN,
)
from bedliftcontrol.controller import BedController
from bedliftcontrol.inverter import Inverter
from bedliftcontrol.timesync import TimeSync
from bedliftcontrol.update import UpdateChecker
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
CORRECTION_BUTTON_WIDTH = 110
CORRECTION_BUTTON_HEIGHT = 90
# from the left edge of the left button to the right edge of the right one
CORRECTION_ROW_WIDTH = 2 * CORRECTION_BUTTON_WIDTH + 30
# Held longer than this and the correction runs on until the button is let go;
# released sooner and it is a plain click worth CORRECTION_STEPS.
CORRECTION_HOLD_DELAY_MS = 400
BAR_ICON_WIDTH = 50   # a single glyph
BAR_BUTTON_WIDTH = 70  # a short word
LOCATION_MENU_WIDTH = 300
KIOSK_BUTTON_WIDTH = 190   # the longest label of the three, side by side in one row
SETTINGS_BUTTON_WIDTH = 120
SETTINGS_SLIDER_WIDTH = 300
SETTINGS_VALUE_WIDTH = 60
# the three buttons side by side, including the gaps between them
SETTINGS_ROW_WIDTH = KIOSK_BUTTON_WIDTH + 2 * SETTINGS_BUTTON_WIDTH + 32
CLOSE_BUTTON_HEIGHT = 44  # a finger, not a mouse pointer
HISTORY_ROW_PITCH = 26
HISTORY_WIDTH = 420
HISTORY_HEADER_HEIGHT = 110  # the nights counter and the section title above the list
COUNTDOWN_TICK_MS = 250
COUNTDOWN_FONT_SIZE = 22  # the countdown is short lines, not one word
POWER_ON_COLOR = "#c62828"  # red while mains is live: a warning, not a status
POWER_OFF_COLOR = "#555555"
UPDATE_BUTTON_WIDTH = 90
UPDATE_BUTTON_COLOR = "#1f6aa5"  # blue: neither a warning nor a running motor

POLL_INTERVAL_MS = 100
UPDATE_POLL_MS = 5000  # the checker runs in a thread; the bar reads its result here
WEATHER_UI_REFRESH_MS = 5000
CLOCK_TICK_MS = 1000  # the display shows seconds, so it has to tick once a second
FORECAST_COL_WIDTH = 50
# Emojis must be drawn with an emoji font, otherwise Tk measures them with the
# default (Roboto) font and renders them wider, which shifts them off-center.
_EMOJI_FONT = "Segoe UI Emoji" if sys.platform.startswith("win") else "Noto Color Emoji"
WEATHER_ICON_SIZE = 64      # big icon next to the current temperature
FORECAST_ICON_SIZE = 34     # one per day, must stay inside FORECAST_COL_WIDTH
RAIN_DROP_SIZE = 11         # drawn, because Noto Color Emoji has no drop on the Pi
RAIN_COLOR = "#5aa0e0"

WINDOW_PAD = 16  # inner padding shared by the child windows
# The Pi panel is 800x480; leave room for the title bar so a window fits whole and its
# content scrolls inside it instead of running off the bottom of the screen.
SCREEN_MARGIN = 70

# reference window listing every weather code with its icon
ICON_TABLE_ICON_SIZE = 26
ICON_TABLE_ROW_HEIGHT = 26
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
INVERTER_DELAY_STEPS = int(INVERTER_STARTUP_MAX - INVERTER_STARTUP_MIN)  # whole seconds
ROPE_DELAY_STEPS = int(ROPE_DELAY_MAX - ROPE_DELAY_MIN)


def _now() -> float:
    """Wrapped so a test can run the waiting out without actually waiting."""
    return time.monotonic()


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
                 timesync: TimeSync | None = None, history=None, inverter=None,
                 updater=None):
        self.controller = controller
        self.weather = weather
        self.history = history
        self.inverter = inverter if inverter is not None else Inverter()
        self.updater = updater if updater is not None else UpdateChecker()
        # own default so existing callers keep working; it touches no network until started
        self.timesync = timesync if timesync is not None else TimeSync()
        self._move_context: MoveContext | None = None
        self._pending_move = None
        self._wait_timer = None
        self._updating = False
        self._wait_until = 0.0
        self._bar_fill_level = 0.0
        self._clock_text = None
        self._kiosk_button = None
        self._correction_timer = None
        self._correction_holding = False
        self._open_windows: dict[str, object] = {}
        self._steps_value_label = None
        self._speed_value_label = None
        self._delay_value_label = None
        self._rope_value_label = None
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
        ctk.CTkButton(bottom, text="⚙", width=BAR_ICON_WIDTH,
                      command=self._settings_window).pack(side="left", padx=4, pady=6)
        self.corrections_button = ctk.CTkButton(bottom, text="↑↓", width=BAR_ICON_WIDTH,
                                                command=self._corrections_window)
        self.corrections_button.pack(side="left", padx=4, pady=6)
        self.power_button = ctk.CTkButton(bottom, text="230V", width=BAR_BUTTON_WIDTH,
                                          command=self._toggle_inverter)
        self.power_button.pack(side="left", padx=4, pady=6)
        # built here, shown only once an update is actually waiting
        self.update_button = ctk.CTkButton(bottom, text="Update", width=UPDATE_BUTTON_WIDTH,
                                           fg_color=UPDATE_BUTTON_COLOR,
                                           command=self._on_update)
        self._build_clock_panel(bottom)

        # left vertical bar: empty when the bed is up, fills from the top down as the
        # bed is lowered (custom, since CTkProgressBar only ever fills from the bottom)
        self.progress_frame = ctk.CTkFrame(self.app)
        self.progress_frame.pack(side="left", fill="y", padx=10, pady=10)
        left = self.progress_frame
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
        self._update_power_button()
        self._set_bar(self.controller.position_fraction)
        self._update_clock()
        self._refresh_update_button()
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
        if self._pending_move is not None:
            self._cancel_pending_move()
            return
        self.controller.stop()

    def _toggle_inverter(self) -> None:
        # cutting mains mid travel would drop the motors and leave the stored position
        # pointing somewhere the bed no longer is
        if self.controller.is_moving:
            return
        self.inverter.toggle()
        self._update_power_button()

    def _update_power_button(self) -> None:
        """The label stays "230V"; red or grey says whether it is live."""
        self.power_button.configure(
            fg_color=POWER_ON_COLOR if self.inverter.on else POWER_OFF_COLOR,
            state="disabled" if self.controller.is_moving else "normal",
        )

    def _start_move(self, context: MoveContext, action) -> None:
        self._set_enabled(self.up_button, False)
        self._set_enabled(self.down_button, False)
        self._set_enabled(self.corrections_button, False)
        self._move_context = context
        self._pending_move = action
        # the bed is about to leave its end stop, so a correction window still standing
        # open would be aimed at a position that no longer exists. Closed after the
        # pending move is set, so it does not take mains down with it.
        self._on_window_closed("corrections")
        self._show_stop_button()
        self.inverter.turn_on()
        self._update_power_button()
        self._wait_until = _now() + self.inverter.seconds_until_ready + self._rope_delay(context)
        self._wait_before_move()

    def _ropes_to_release(self, context: MoveContext | None) -> bool:
        """Only on the way down from the very top are the safety ropes still attached."""
        return context == MoveContext.DOWN and self.controller.at_top

    def _rope_delay(self, context: MoveContext) -> float:
        """Extra time before the bed leaves the top, to get the safety ropes off."""
        return self.controller.config.rope_delay_seconds if self._ropes_to_release(context) else 0.0

    def _wait_before_move(self) -> None:
        """The motors hang off the inverter, so the movement waits out its start-up -
        and, on the way down from the top, the extra time for the ropes."""
        if self._pending_move is None:  # STOP was pressed during the countdown
            return
        remaining = self._wait_until - _now()
        if remaining <= 0:
            action, self._pending_move = self._pending_move, None
            self._set_stop_button_text("STOP", STOP_FONT_SIZE)
            self.controller.run_async(action)
            self._schedule_poll()
            return
        self._set_stop_button_text(self._countdown_text(math.ceil(remaining)),
                                   COUNTDOWN_FONT_SIZE)
        self._wait_timer = self.app.after(COUNTDOWN_TICK_MS, self._wait_before_move)

    def _countdown_text(self, seconds: int) -> str:
        # the waiting time is exactly what the ropes need, so the button says so
        ropes = self._ropes_to_release(self._move_context)
        if ropes and self.inverter.ready:
            return f"Seile\nlösen!\n{seconds}s"
        text = f"230V\nstartet\n{seconds}s"
        if ropes:
            text += "\n\nSeile lösen!"
        return text

    def _set_stop_button_text(self, text: str, size: int) -> None:
        self.stop_button.configure(text=text, font=ctk.CTkFont(size=size, weight="bold"))

    def _cancel_pending_move(self) -> None:
        """STOP during the start-up: the movement is dropped, the inverter keeps running.
        It was switched on deliberately and the 230V button is the way back off."""
        self._pending_move = None
        if self._wait_timer is not None:
            self.app.after_cancel(self._wait_timer)
            self._wait_timer = None
        self._set_stop_button_text("STOP", STOP_FONT_SIZE)
        self._hide_stop_button()
        self._move_context = None
        self._update_move_buttons()
        self._update_corrections_button()
        self._update_power_button()

    def _refresh_update_button(self) -> None:
        """The button only exists while there is something to install."""
        if self.updater.update_available and not self._updating:
            self.update_button.pack(side="left", padx=4, pady=6)
        elif not self._updating:
            self.update_button.pack_forget()
        self.app.after(UPDATE_POLL_MS, self._refresh_update_button)

    def _on_update(self) -> None:
        # pulling out from under a moving bed would leave the position unwritten
        if self.controller.is_moving or self._updating:
            return
        self._updating = True
        self.update_button.configure(text="läuft…", state="disabled")
        threading.Thread(target=self._run_update, daemon=True).start()

    def _run_update(self) -> None:
        """The pull can take a moment on a phone connection, so it runs off the UI."""
        succeeded = self.updater.apply()
        self.app.after(0, lambda: self._update_finished(succeeded))

    def _update_finished(self, succeeded: bool) -> None:
        self._updating = False
        if not succeeded:
            self.update_button.configure(text="Update", state="normal")
            messagebox.showerror("Update", "Update fehlgeschlagen. Details im Log.")
            return
        self._restart()

    def _restart(self) -> None:
        """Replace the process with a fresh one of the just pulled version.

        The config is written first: the pull reset the checked-in file, and the live
        values - bed position above all - are the ones that must survive.
        """
        self.controller.config.save()
        self.inverter.turn_off()
        self.controller.cleanup()
        self.app.destroy()
        logger.info("Restarting into the updated version")
        os.execv(sys.executable, [sys.executable, "-m", "bedliftcontrol.main"])

    def _schedule_poll(self) -> None:
        self.app.after(POLL_INTERVAL_MS, self._poll_movement)

    def _on_up(self) -> None:
        if self.controller.is_moving:
            return
        self._start_move(MoveContext.UP, self.controller.move_up)

    def _on_down(self) -> None:
        if self.controller.is_moving:
            return
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
        self._update_power_button()
        # only act when the bed really arrived at an end stop - after a stop in
        # between it is hanging somewhere and still needs the motors
        if self._move_context == MoveContext.UP and self.controller.at_top:
            # the ropes go on while the motors still hold the bed, so the prompt comes
            # first and mains is cut once it is acknowledged
            messagebox.showinfo("Bett sichern", "Sicherungsseile anbringen!")
            self._switch_off_after_move()
        elif self._move_context == MoveContext.DOWN and self.controller.at_bottom:
            self._switch_off_after_move()
        self._move_context = None

    def _switch_off_after_move(self) -> None:
        """Parked at an end stop, nothing draws mains any more."""
        if self.inverter.turn_off():
            self._update_power_button()

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
            self._delay_value_label = None
            self._rope_value_label = None
        if name == "corrections":
            # the buttons are about to be destroyed, so no release event is coming
            self._cancel_correction_timer()
            self._end_correction_hold()
            self._release_corrections_power()
        if window is not None:
            window.destroy()

    def _add_close_button(self, parent, row: int, width: int, name: str, columnspan: int):
        """Closing by the window decoration is a small target on a touch panel."""
        button = ctk.CTkButton(parent, text="Schliessen", width=width,
                               height=CLOSE_BUTTON_HEIGHT,
                               command=lambda: self._on_window_closed(name))
        button.grid(row=row, column=0, columnspan=columnspan, padx=12, pady=(12, 0))
        return button

    def _place_beside_the_bar(self, window) -> None:
        """Right of the progress bar, at the top edge - where the hand already is."""
        window.update_idletasks()
        left_edge = self.progress_frame.winfo_rootx() + self.progress_frame.winfo_width()
        window.geometry(f"+{left_edge}+0")

    def _settings_window(self) -> None:
        self._toggle_window("settings", self._build_settings_window)

    def _build_settings_window(self):
        window = ctk.CTkToplevel(self.app)
        window.title("Settings")
        window.geometry("520x390")
        content = ctk.CTkFrame(window, fg_color="transparent")
        content.pack(expand=True)
        config = self.controller.config
        self._steps_value_label = self._add_slider_row(
            content, 0, "total steps", STEPS_MIN, STEPS_MAX, config.total_steps,
            self._on_steps_change, str(config.total_steps))
        self._speed_value_label = self._add_slider_row(
            content, 1, "speed pps", SPEED_MIN, SPEED_MAX, config.speed_pps,
            self._on_speed_change, str(int(config.speed_pps)))
        self._delay_value_label = self._add_slider_row(
            content, 2, "230V Anlauf", INVERTER_STARTUP_MIN, INVERTER_STARTUP_MAX,
            config.inverter_startup_seconds, self._on_inverter_delay_change,
            self._delay_text(config.inverter_startup_seconds), steps=INVERTER_DELAY_STEPS)
        self._rope_value_label = self._add_slider_row(
            content, 3, "Seile lösen", ROPE_DELAY_MIN, ROPE_DELAY_MAX,
            config.rope_delay_seconds, self._on_rope_delay_change,
            self._delay_text(config.rope_delay_seconds), steps=ROPE_DELAY_STEPS)
        ctk.CTkLabel(content, text="Ort").grid(row=4, column=0, padx=12, pady=12, sticky="e")
        self._location_menu = ctk.CTkOptionMenu(
            content, width=LOCATION_MENU_WIDTH, values=[place.label for place in LOCATIONS],
            command=self._on_location_chosen)
        self._location_menu.set(location_or_default(self.weather.selected).label)
        self._location_menu.grid(row=4, column=1, padx=12, pady=12, sticky="w")

        buttons = ctk.CTkFrame(content, fg_color="transparent")
        buttons.grid(row=5, column=0, columnspan=3, padx=12, pady=(16, 0))
        self._kiosk_button = ctk.CTkButton(buttons, text=self._kiosk_button_text(),
                                           width=KIOSK_BUTTON_WIDTH, command=self._toggle_kiosk)
        self._kiosk_button.pack(side="left", padx=(0, 8))
        ctk.CTkButton(buttons, text="Wetter-Icons", width=SETTINGS_BUTTON_WIDTH,
                      command=self._weather_icons_window).pack(side="left", padx=8)
        ctk.CTkButton(buttons, text="Historie", width=SETTINGS_BUTTON_WIDTH,
                      command=self._history_window).pack(side="left", padx=(8, 0))
        self._add_close_button(content, row=6, width=SETTINGS_ROW_WIDTH,
                               name="settings", columnspan=3)
        self._place_beside_the_bar(window)
        return window

    @staticmethod
    def _add_slider_row(parent, row, label, low, high, value, command, value_text, steps=None):
        """One settings line: name, slider, current value. Returns the value label."""
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, padx=12, pady=12, sticky="e")
        slider = ctk.CTkSlider(parent, from_=low, to=high, width=SETTINGS_SLIDER_WIDTH,
                               number_of_steps=steps, command=command)
        slider.set(value)
        slider.grid(row=row, column=1, padx=12, pady=12)
        value_label = ctk.CTkLabel(parent, text=value_text, width=SETTINGS_VALUE_WIDTH)
        value_label.grid(row=row, column=2, padx=(4, 0))
        return value_label

    @staticmethod
    def _delay_text(seconds) -> str:
        return f"{round(seconds)} s"

    def _store_setting(self, name: str, value, label, text: str) -> None:
        """Settings are written straight through: the sliders have no OK button, and a
        vehicle can lose power between two taps."""
        setattr(self.controller.config, name, value)
        self.controller.config.save()
        if label is not None:  # the settings window may be closed again by now
            label.configure(text=text)

    def _on_inverter_delay_change(self, value) -> None:
        seconds = float(round(value))
        self.inverter.startup_seconds = seconds
        self._store_setting("inverter_startup_seconds", seconds,
                            self._delay_value_label, self._delay_text(seconds))

    def _on_rope_delay_change(self, value) -> None:
        seconds = float(round(value))
        self._store_setting("rope_delay_seconds", seconds,
                            self._rope_value_label, self._delay_text(seconds))

    def _on_steps_change(self, value) -> None:
        self._store_setting("total_steps", int(value),
                            self._steps_value_label, str(int(value)))

    def _on_speed_change(self, value) -> None:
        self._store_setting("speed_pps", float(value),
                            self._speed_value_label, str(int(value)))

    def _corrections_window(self) -> None:
        self._toggle_window("corrections", self._build_corrections_window)

    def _release_corrections_power(self) -> None:
        """Mains came on with the window and goes off with it - unless a movement is
        starting, which needs it and switches it off itself at the end stop."""
        if self.controller.is_moving or self._pending_move is not None:
            return
        if self.inverter.turn_off():
            self._update_power_button()

    def _build_corrections_window(self):
        # the corrections drive the motors, so mains comes on with the window; by the
        # time a button is aimed at, the inverter has had its start-up
        self.inverter.turn_on()
        self._update_power_button()
        window = ctk.CTkToplevel(self.app)
        window.title("Corrections")
        window.geometry("320x350")
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
            button = ctk.CTkButton(content, text=text, width=CORRECTION_BUTTON_WIDTH,
                                   height=CORRECTION_BUTTON_HEIGHT)
            button.grid(row=row, column=column, padx=15, pady=8)
            self._bind_correction(button, click_action, hold_action)
        self._add_close_button(content, row=3, width=CORRECTION_ROW_WIDTH,
                               name="corrections", columnspan=2)
        self._place_beside_the_bar(window)
        return window

    def _on_location_chosen(self, label: str) -> None:
        for location in LOCATIONS:
            if location.label == label:
                self._select_location(location.key)
                return

    def _select_location(self, key: str) -> None:
        self.weather.select(key)
        self.controller.config.weather_location = key
        self.controller.config.save()
        self._apply_weather()

    def _history_window(self) -> None:
        self._toggle_window("history", self._build_history_window)

    def _build_history_window(self):
        window = ctk.CTkToplevel(self.app)
        window.title("Historie")
        content = ctk.CTkFrame(window, fg_color="transparent")
        content.pack(padx=WINDOW_PAD, pady=WINDOW_PAD, fill="both", expand=True)

        nights = self.history.nights if self.history is not None else 0
        ctk.CTkLabel(content, text=f"Übernachtungen: {nights}",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(0, 12))
        ctk.CTkLabel(content, text="Standort-Historie",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")

        entries = list(reversed(self.history.locations)) if self.history is not None else []
        visible = self._history_visible_height(window.winfo_screenheight(), len(entries))
        listing = ctk.CTkScrollableFrame(content, fg_color="transparent",
                                         width=HISTORY_WIDTH, height=visible)
        listing.pack(fill="both", expand=True, pady=(4, 0))
        if not entries:
            ctk.CTkLabel(listing, text="Noch keine Standorte aufgezeichnet",
                         text_color="#888888").pack(anchor="w", pady=4)
        for entry in entries:
            ctk.CTkLabel(listing, text=self._format_visit(entry), anchor="w",
                         height=HISTORY_ROW_PITCH).pack(fill="x")
        return window

    @staticmethod
    def _history_visible_height(screen_height: int, rows: int) -> int:
        available = screen_height - SCREEN_MARGIN - 2 * WINDOW_PAD - HISTORY_HEADER_HEIGHT
        wanted = max(rows, 1) * HISTORY_ROW_PITCH
        return max(HISTORY_ROW_PITCH, min(wanted, available))

    @staticmethod
    def _format_visit(visit) -> str:
        try:
            moment = datetime.fromisoformat(visit.at)
            stamp = f"{moment.day:02d}.{moment.month:02d}.{moment.year} {moment.hour:02d}:{moment.minute:02d}"
        except ValueError:
            stamp = visit.at
        return f"{stamp}   {visit.city}   ({visit.latitude:.4f}, {visit.longitude:.4f})"

    def _weather_icons_window(self) -> None:
        self._toggle_window("weather_icons", self._build_weather_icons_window)

    @staticmethod
    def _icon_table_visible_height(screen_height: int, rows: int) -> int:
        """How much of the table is on screen at once - the rest is scrolled to.

        Budgeted so the finished window (this plus the padding above and below) still
        fits the screen with room for the title bar, which the 800x480 Pi panel needs.
        """
        available = screen_height - SCREEN_MARGIN - 2 * WINDOW_PAD
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
        content.pack(fill="both", expand=True, padx=WINDOW_PAD, pady=WINDOW_PAD)

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
        window.geometry(f"{content.winfo_reqwidth() + 2 * WINDOW_PAD}"
                        f"x{visible_height + 2 * WINDOW_PAD}")
        return window

    def _refresh_weather(self) -> None:
        self._apply_weather()
        self.app.after(WEATHER_UI_REFRESH_MS, self._refresh_weather)

    def _apply_weather(self) -> None:
        """Hand the selected reading to both blocks. Separate from the timer above so a
        location change can apply immediately without starting a second timer chain.

        Runs every few seconds, which is also what carries the panel over midnight: days
        that are past drop out of the forecast, and a reading from yesterday gives way to
        today's forecast. Both work offline - no fetch is involved.
        """
        weather = self.weather.current
        if weather is None:
            self._show_reading_missing()
            return
        today = self._today()
        daily = [day for day in weather.daily if day.date >= today]
        stale = weather.date != today
        forecast_today = daily[0] if daily and daily[0].date == today else None
        if stale and forecast_today is not None:
            self._update_current_panel_from_forecast(weather.city, forecast_today)
            stamp = "Vorhersage, Stand: " + weather.fetched_at.replace("T", " ")
        else:
            self._update_current_panel(weather)
            stamp = "Stand: " + weather.fetched_at.replace("T", " ")
        self._render_forecast(daily)
        self.weather_updated.configure(text=stamp)

    def _today(self) -> str:
        """Today as an ISO date, off the corrected clock rather than the machine one."""
        return self.timesync.now().date().isoformat()

    def _show_reading_missing(self) -> None:
        """A location that has not been fetched yet must not keep showing the previous
        one's numbers."""
        self.weather_city.configure(text=location_or_default(self.weather.selected).label)
        self.weather_day.configure(text="")
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
        # expand, so the height a kiosk screen has over the window goes into the gaps
        # between the blocks instead of piling up under the last one
        self.current_frame.pack(fill="x", expand=True, pady=(20, 0))
        city_row = ctk.CTkFrame(self.current_frame, fg_color="transparent")
        city_row.pack()
        self.weather_city = ctk.CTkLabel(city_row, text="", font=ctk.CTkFont(size=22))
        self.weather_city.pack(side="left")
        self.weather_day = ctk.CTkLabel(city_row, text="", font=ctk.CTkFont(size=22),
                                        text_color="#888888")
        self.weather_day.pack(side="left", padx=(10, 0))
        weather_row = ctk.CTkFrame(self.current_frame, fg_color="transparent")
        weather_row.pack(pady=6, padx=(40, 0))  # left pad shifts the centred group ~20px right
        self.weather_icon = icons.IconCanvas(weather_row, size=WEATHER_ICON_SIZE, background=_panel_background())
        self.weather_icon.pack(side="left", padx=(0, 20))
        self.weather_temp = ctk.CTkLabel(weather_row, text="", font=ctk.CTkFont(size=52))
        self.weather_temp.pack(side="left", padx=(20, 0))
        self.weather_desc = ctk.CTkLabel(self.current_frame, text="", font=ctk.CTkFont(size=16))
        self.weather_desc.pack()

    def _update_current_panel_from_forecast(self, city: str, day) -> None:
        """Yesterday's measurement is no longer "now". Once the connection is gone, the
        forecast for today is the best thing left, so the block shows that instead - with
        the day's high and low in place of a single temperature, because that is what a
        forecast has.
        """
        self.weather_city.configure(text=city)
        self.weather_day.configure(text=day.day)
        self.weather_icon.show(day.icon)
        self.weather_temp.configure(text=f"{round(day.temp_max)}° / {round(day.temp_min)}°")
        self.weather_desc.configure(text=day.description)

    def _update_current_panel(self, weather) -> None:
        """Conditions right now - a point in time, not the day as a whole."""
        self.weather_city.configure(text=weather.city)
        self.weather_day.configure(text=weather.weekday)
        self.weather_icon.show(weather.icon)
        self.weather_temp.configure(text=f"{round(weather.temperature)}°C")
        self.weather_desc.configure(text=weather.description)

    # --- block 2: seven day forecast ---------------------------------------
    # Owns self.forecast_frame and self._forecast_labels, driven purely by the daily list.

    def _build_forecast_panel(self, parent) -> None:
        self.forecast_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.forecast_frame.pack(expand=True, pady=(18, 0))

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
            # the icon is drawn, not text, so it gets its own row between name and temps
            icon = icons.IconCanvas(self.forecast_frame, size=FORECAST_ICON_SIZE, background=_panel_background())
            icon.show(day.icon)
            icon.grid(row=1, column=index, padx=8, pady=2)
            self._forecast_labels.append(icon)
            for row, (text, font, color) in enumerate(rows):
                label = ctk.CTkLabel(self.forecast_frame, text=text, anchor="center", font=font, text_color=color)
                label.grid(row=row if row == 0 else row + 1, column=index, padx=8, pady=1, sticky="ew")
                self._forecast_labels.append(label)
            if day.rain is not None:
                self._forecast_labels.append(self._build_rain_cell(index, len(rows) + 1, day.rain))

    def _build_rain_cell(self, column: int, row: int, rain: int):
        cell = ctk.CTkFrame(self.forecast_frame, fg_color="transparent")
        cell.grid(row=row, column=column, padx=2, pady=1)
        drop = tkinter.Canvas(cell, width=RAIN_DROP_SIZE, height=RAIN_DROP_SIZE,
                              bg=_panel_background(), highlightthickness=0, borderwidth=0)
        icons.draw_drop(drop, RAIN_DROP_SIZE)
        drop.pack(side="left")
        ctk.CTkLabel(cell, text=f"{rain}%", font=ctk.CTkFont(size=12),
                     text_color=RAIN_COLOR).pack(side="left", padx=(2, 0))
        return cell

    def display(self) -> None:
        self.app.mainloop()
