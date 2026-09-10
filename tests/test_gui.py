"""Tests for the GUI logic. customtkinter is mocked (conftest.py), so no window opens.

The ``ctk_widgets`` fixture makes each widget constructor return a new mock so
buttons/labels/windows can be told apart, and stubs out the message box.
"""

from unittest.mock import MagicMock

import pytest

from bedliftcontrol import gui as gui_module
from bedliftcontrol.gui import MIN_BAR_FRACTION, STUB_TRIM_PX, BedGui, MoveContext

WIDGETS = [
    "CTk",
    "CTkFrame",
    "CTkScrollableFrame",
    "CTkButton",
    "CTkProgressBar",
    "CTkLabel",
    "CTkToplevel",
    "CTkSlider",
    "CTkFont",
]


def _states(button):
    return [call.kwargs.get("state") for call in button.configure.call_args_list]


def _widget_mock():
    """A fresh widget mock. winfo_height() answers 0 ("not laid out yet"), because
    MagicMock's default would blow up the numeric comparison in BedGui._stub_trim."""
    widget = MagicMock()
    widget.winfo_height.return_value = 0
    # real numbers, because the sizing code compares them
    widget.winfo_screenheight.return_value = 1050
    widget.winfo_screenwidth.return_value = 1680
    return widget


@pytest.fixture(autouse=True)
def ctk_widgets(monkeypatch):
    import customtkinter

    for name in WIDGETS:
        getattr(customtkinter, name).side_effect = lambda *args, **kwargs: _widget_mock()
    monkeypatch.setattr(gui_module, "messagebox", MagicMock())
    yield
    for name in WIDGETS:
        getattr(customtkinter, name).side_effect = None


@pytest.fixture
def controller():
    fake = MagicMock()
    fake.is_moving = False
    fake.progress = 0.0
    # the bed sits at the bottom: position 0, so only the up arrow is live
    fake.position_fraction = 0.0
    fake.at_top = False
    fake.at_bottom = True
    fake.config.bed_up = False
    fake.config.position_steps = 0
    fake.config.total_steps = 28000
    fake.config.speed_pps = 800.0
    fake.config.kiosk = False
    return fake


@pytest.fixture
def weather():
    fake = MagicMock()
    fake.current = None
    fake.selected = "phone"
    fake.readings = {}
    return fake


@pytest.fixture
def gui(controller, weather):
    return BedGui(controller, weather)


class TestInitialState:
    def test_bed_down_disables_down_button(self, controller, weather):
        controller.config.bed_up = False
        built = BedGui(controller, weather)
        assert "disabled" in _states(built.down_button)

    def test_bed_up_disables_up_button(self, controller, weather):
        """The arrow state comes from the absolute position now, not from the flag."""
        controller.at_top = True
        controller.at_bottom = False
        controller.position_fraction = 1.0
        controller.config.bed_up = True
        built = BedGui(controller, weather)
        assert "disabled" in _states(built.up_button)

    def test_a_position_in_between_leaves_both_arrows_live(self, controller, weather):
        controller.at_top = False
        controller.at_bottom = False
        controller.position_fraction = 0.4
        built = BedGui(controller, weather)
        assert "normal" in _states(built.up_button)
        assert "normal" in _states(built.down_button)

    def test_build_sets_initial_bar(self, gui):
        gui.progress_fill.place.assert_called()


class TestOnUp:
    def test_disables_both_and_starts_move(self, gui, controller):
        gui._on_up()
        assert "disabled" in _states(gui.up_button)
        assert "disabled" in _states(gui.down_button)
        assert gui._move_context is MoveContext.UP
        controller.run_async.assert_called_once_with(controller.move_up)
        gui.app.after.assert_called()

    def test_ignored_while_moving(self, gui, controller):
        controller.is_moving = True
        gui._on_up()
        controller.run_async.assert_not_called()


class TestOnDown:
    def test_starts_down_move(self, gui, controller):
        gui._on_down()
        assert gui._move_context is MoveContext.DOWN
        controller.run_async.assert_called_once_with(controller.move_down)

    def test_ignored_while_moving(self, gui, controller):
        controller.is_moving = True
        gui._on_down()
        controller.run_async.assert_not_called()


class TestPollMovement:
    def test_finalizes_up(self, gui, controller):
        controller.is_moving = False
        controller.at_top = True
        controller.at_bottom = False
        controller.position_fraction = 1.0
        gui._move_context = MoveContext.UP
        gui._poll_movement()
        assert "disabled" in _states(gui.up_button)
        assert "normal" in _states(gui.down_button)
        assert gui._move_context is None

    def test_finalizes_down(self, gui, controller):
        controller.is_moving = False
        gui._move_context = MoveContext.DOWN
        gui._poll_movement()
        assert "normal" in _states(gui.up_button)
        assert "disabled" in _states(gui.down_button)

    def test_shows_progress_while_moving(self, gui, controller):
        controller.is_moving = True
        controller.position_fraction = 0.5
        gui._move_context = MoveContext.UP
        gui._poll_movement()
        gui.progress_label.configure.assert_any_call(text="50%")
        gui.progress_fill.place.assert_called()

    def test_progress_follows_the_absolute_position(self, gui, controller):
        """A move starting half way up must not send the bar back to the bottom."""
        controller.is_moving = True
        controller.position_fraction = 0.6  # 60% up, so 40% down
        controller.progress = 0.1  # per-move progress, deliberately different
        gui._move_context = MoveContext.UP
        gui._poll_movement()
        gui.progress_label.configure.assert_any_call(text="40%")


class TestProgressBar:
    def test_bar_keeps_a_stub_when_up(self, gui):
        gui._set_bar(1.0)  # 1.0 == bed up
        gui.progress_fill.place.assert_called_with(relx=0, rely=0, relwidth=1.0, relheight=MIN_BAR_FRACTION, anchor="nw")

    def test_stub_is_trimmed_by_ten_pixels_when_up(self, gui):
        gui.progress_track.winfo_height.return_value = 200
        gui._set_bar(1.0)  # 1.0 == bed up
        expected = MIN_BAR_FRACTION - STUB_TRIM_PX / 200
        gui.progress_fill.place.assert_called_with(relx=0, rely=0, relwidth=1.0, relheight=expected, anchor="nw")

    def test_bar_still_fills_the_track_when_down(self, gui):
        gui.progress_track.winfo_height.return_value = 200
        gui._set_bar(0.0)  # 0.0 == bed down, trim must not apply here
        gui.progress_fill.place.assert_called_with(relx=0, rely=0, relwidth=1.0, relheight=1.0, anchor="nw")

    def test_bar_full_when_down(self, gui):
        gui._set_bar(0.0)  # 0.0 == bed down
        gui.progress_fill.place.assert_called_with(relx=0, rely=0, relwidth=1.0, relheight=1.0, anchor="nw")

    def test_clamps_out_of_range(self, gui):
        gui._set_bar(2.0)  # clamps to bed up -> stub
        gui.progress_fill.place.assert_called_with(relx=0, rely=0, relwidth=1.0, relheight=MIN_BAR_FRACTION, anchor="nw")


class TestCorrect:
    def test_runs_when_idle(self, gui, controller):
        controller.is_moving = False
        action = MagicMock()
        gui._correct(action)
        controller.run_async.assert_called_once_with(action)

    def test_ignored_while_moving(self, gui, controller):
        controller.is_moving = True
        action = MagicMock()
        gui._correct(action)
        controller.run_async.assert_not_called()


class TestWindowToggle:
    def test_second_click_closes_the_window(self, gui):
        gui._settings_window()
        window = gui._open_windows["settings"]
        gui._settings_window()
        assert "settings" not in gui._open_windows
        window.destroy.assert_called_once()

    def test_closing_via_protocol_clears_the_reference(self, gui):
        gui._corrections_window()
        gui._on_window_closed("corrections")
        assert "corrections" not in gui._open_windows

    def test_each_button_tracks_its_own_window(self, gui):
        gui._settings_window()
        gui._corrections_window()
        assert set(gui._open_windows) == {"settings", "corrections"}


class TestSettingsValues:
    def test_steps_change_updates_value_label(self, gui, controller):
        gui._settings_window()
        gui._on_steps_change(29000)
        assert controller.config.total_steps == 29000
        gui._steps_value_label.configure.assert_any_call(text="29000")

    def test_speed_change_updates_value_label(self, gui, controller):
        gui._settings_window()
        gui._on_speed_change(1000)
        assert controller.config.speed_pps == 1000.0
        gui._speed_value_label.configure.assert_any_call(text="1000")


class TestWeatherDisplay:
    def test_updates_labels_from_current(self, gui, weather):
        from bedliftcontrol.weather import Weather

        weather.current = Weather("Thun", 21.4, "Klar", "☀️", "2026-09-03T11:00")
        gui._refresh_weather()
        gui.weather_city.configure.assert_any_call(text="Thun")
        gui.weather_desc.configure.assert_any_call(text="Klar")

    def test_handles_no_data(self, gui, weather):
        weather.current = None
        gui._refresh_weather()  # must not raise

    def test_renders_forecast_columns(self, gui, weather):
        from bedliftcontrol.weather import DailyForecast, Weather

        daily = [
            DailyForecast("Do", "2026-09-03", "☀️", 22.0, 12.0, rain=10),
            DailyForecast("Fr", "2026-09-04", "🌧️", 18.0, 10.0, rain=80),
        ]
        weather.current = Weather("Thun", 21.0, "Klar", "☀️", "2026-09-03T11:00", daily=daily)
        gui._refresh_weather()
        assert len(gui._forecast_labels) == 10  # 2 days x 5 rows (incl. rain)


class TestPanelSeparation:
    """The current-conditions block and the forecast block must stay independent, so
    either can be reworked without disturbing the other."""

    def test_current_panel_has_its_own_frame(self, gui):
        assert gui.current_frame is not None
        assert gui.forecast_frame is not gui.current_frame

    def test_updating_the_current_panel_leaves_the_forecast_alone(self, gui, weather, monkeypatch):
        from bedliftcontrol.weather import Weather

        called = []
        monkeypatch.setattr(gui, "_render_forecast", lambda daily: called.append(daily))
        gui._update_current_panel(Weather("Thun", 21.4, "Klar", "sun", "2026-09-03T11:00"))
        assert not called, "block 1 must not trigger a forecast render"

    def test_rendering_the_forecast_leaves_the_current_panel_alone(self, gui):
        from bedliftcontrol.weather import DailyForecast

        gui.weather_city.configure.reset_mock()
        gui.weather_temp.configure.reset_mock()
        gui.weather_desc.configure.reset_mock()
        gui._render_forecast([DailyForecast("Do", "2026-09-03", "sun", 22.0, 12.0, rain=10)])
        assert not gui.weather_city.configure.called
        assert not gui.weather_temp.configure.called
        assert not gui.weather_desc.configure.called

    def test_refresh_drives_both_blocks(self, gui, weather, monkeypatch):
        from bedliftcontrol.weather import DailyForecast, Weather

        daily = [DailyForecast("Do", "2026-09-03", "sun", 22.0, 12.0, rain=10)]
        weather.current = Weather("Thun", 21.0, "Klar", "sun", "2026-09-03T11:00", daily=daily)
        seen = []
        monkeypatch.setattr(gui, "_update_current_panel", lambda w: seen.append("current"))
        monkeypatch.setattr(gui, "_render_forecast", lambda d: seen.append("forecast"))
        gui._refresh_weather()
        assert seen == ["current", "forecast"]


class TestClock:
    """The clock is its own block: it must tick regardless of the weather."""

    def test_shows_date_and_time(self, gui, monkeypatch):
        from datetime import datetime

        from bedliftcontrol import gui as module

        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8))
        gui._clock_text = None
        gui._update_clock()
        gui.clock_date.configure.assert_any_call(text="Dienstag, 8. September 2026")
        gui.clock_time.configure.assert_any_call(text="12:08:00")

    def test_keeps_ticking_without_a_weather_reading(self, gui, weather, monkeypatch):
        """No internet means _refresh_weather returns early - the clock must not care."""
        from datetime import datetime

        from bedliftcontrol import gui as module

        weather.current = None
        gui._refresh_weather()
        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8))
        gui._clock_text = None
        gui._update_clock()
        gui.clock_time.configure.assert_any_call(text="12:08:00")

    def test_does_not_redraw_twice_within_the_same_second(self, gui, monkeypatch):
        from datetime import datetime

        from bedliftcontrol import gui as module

        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8, 1, 100000))
        gui._clock_text = None
        gui._update_clock()
        gui.clock_time.configure.reset_mock()
        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8, 1, 900000))
        gui._update_clock()
        assert not gui.clock_time.configure.called

    def test_redraws_when_the_second_ticks(self, gui, monkeypatch):
        from datetime import datetime

        from bedliftcontrol import gui as module

        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8, 1))
        gui._clock_text = None
        gui._update_clock()
        gui.clock_time.configure.reset_mock()
        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8, 2))
        gui._update_clock()
        gui.clock_time.configure.assert_any_call(text="12:08:02")

    @pytest.mark.parametrize(
        "microsecond, expected",
        [(0, 1000), (250000, 750), (900000, 100), (999000, 50)],
    )
    def test_tick_aims_at_the_next_second_boundary(self, gui, microsecond, expected):
        """A fixed 1000ms interval would drift and eventually skip a displayed second."""
        from datetime import datetime

        moment = datetime(2026, 9, 8, 12, 8, 1, microsecond)
        assert gui._ms_to_next_second(moment) == expected

    def test_clock_does_not_touch_the_weather_blocks(self, gui, monkeypatch):
        from datetime import datetime

        from bedliftcontrol import gui as module

        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8))
        gui.weather_city.configure.reset_mock()
        called = []
        monkeypatch.setattr(gui, "_render_forecast", lambda daily: called.append(daily))
        gui._clock_text = None
        gui._update_clock()
        assert not gui.weather_city.configure.called
        assert not called


class TestKioskMode:
    """Toggling between the fixed window and fullscreen on the Pi's 800x480 panel."""

    def test_starts_windowed_by_default(self, gui, controller):
        assert controller.config.kiosk is False
        gui.app.attributes.assert_any_call("-fullscreen", False)

    def test_stored_kiosk_flag_is_applied_on_build(self, controller, weather):
        controller.config.kiosk = True
        built = BedGui(controller, weather)
        built.app.attributes.assert_any_call("-fullscreen", True)

    def test_toggle_turns_it_on_and_persists(self, gui, controller):
        gui._toggle_kiosk()
        assert controller.config.kiosk is True
        controller.config.save.assert_called()
        gui.app.attributes.assert_any_call("-fullscreen", True)

    def test_toggle_turns_it_off_and_restores_the_window_size(self, gui, controller):
        from bedliftcontrol.gui import WINDOW_GEOMETRY

        controller.config.kiosk = True
        gui.app.geometry.reset_mock()
        gui._toggle_kiosk()
        assert controller.config.kiosk is False
        gui.app.geometry.assert_any_call(WINDOW_GEOMETRY)

    def test_escape_leaves_kiosk(self, gui, controller):
        controller.config.kiosk = True
        gui._leave_kiosk()
        assert controller.config.kiosk is False

    def test_escape_does_nothing_when_already_windowed(self, gui, controller):
        controller.config.kiosk = False
        controller.config.save.reset_mock()
        gui._leave_kiosk()
        assert controller.config.kiosk is False
        assert not controller.config.save.called, "a no-op must not rewrite the config"

    def test_button_text_follows_the_state(self, gui, controller):
        controller.config.kiosk = False
        assert gui._kiosk_button_text() == "Kiosk-Modus einschalten"
        controller.config.kiosk = True
        assert gui._kiosk_button_text() == "Kiosk-Modus ausschalten"

    def test_settings_window_offers_the_toggle(self, gui):
        gui._settings_window()
        assert gui._kiosk_button is not None

    def test_closing_settings_drops_the_button_reference(self, gui):
        """_refresh_kiosk_button must not configure a destroyed widget."""
        gui._settings_window()
        gui._on_window_closed("settings")
        assert gui._kiosk_button is None
        gui._toggle_kiosk()  # must not raise

    def test_child_windows_are_raised_over_a_fullscreen_parent(self, gui, controller):
        """In kiosk mode the settings window is the only way back out."""
        controller.config.kiosk = True
        gui._settings_window()
        window = gui._open_windows["settings"]
        window.lift.assert_called()
        window.attributes.assert_any_call("-topmost", True)

    def test_child_windows_are_not_forced_on_top_when_windowed(self, gui, controller):
        controller.config.kiosk = False
        gui._settings_window()
        window = gui._open_windows["settings"]
        assert not any(call.args[:1] == ("-topmost",) for call in window.attributes.call_args_list)


class TestStopButton:
    """A movement can be interrupted; the stop button covers both arrows while it runs."""

    def test_appears_when_a_move_starts(self, gui, controller):
        gui._on_up()
        gui.stop_button.place.assert_called_once_with(x=0, y=0, relwidth=1.0, relheight=1.0)
        gui.stop_button.lift.assert_called()

    def test_covers_the_whole_control_frame(self, gui):
        gui._on_up()
        kwargs = gui.stop_button.place.call_args.kwargs
        assert kwargs["relwidth"] == 1.0 and kwargs["relheight"] == 1.0

    def test_hidden_at_rest(self, gui):
        assert not gui.stop_button.place.called

    def test_pressing_it_asks_the_controller_to_stop(self, gui, controller):
        gui._on_stop()
        controller.stop.assert_called_once()

    def test_disappears_once_the_move_ends(self, gui, controller):
        gui._on_up()
        controller.is_moving = False
        gui._poll_movement()
        gui.stop_button.place_forget.assert_called()

    def test_stays_while_the_move_runs(self, gui, controller):
        gui._on_up()
        controller.is_moving = True
        gui._poll_movement()
        assert not gui.stop_button.place_forget.called

    def test_both_arrows_live_again_after_a_stop_in_between(self, gui, controller):
        gui._on_up()
        controller.is_moving = False
        controller.at_top = False
        controller.at_bottom = False
        controller.position_fraction = 0.4
        gui.up_button.configure.reset_mock()
        gui.down_button.configure.reset_mock()
        gui._poll_movement()
        assert "normal" in _states(gui.up_button)
        assert "normal" in _states(gui.down_button)

    def test_no_rope_prompt_after_a_stop_in_between(self, gui, controller, monkeypatch):
        """'Bett oben' would be wrong and unsafe when the bed hangs half way."""
        from bedliftcontrol import gui as module

        box = MagicMock()
        monkeypatch.setattr(module, "messagebox", box)
        gui._move_context = MoveContext.UP
        controller.is_moving = False
        controller.at_top = False
        gui._poll_movement()
        assert not box.showinfo.called

    def test_rope_prompt_when_the_top_is_actually_reached(self, gui, controller, monkeypatch):
        from bedliftcontrol import gui as module

        box = MagicMock()
        monkeypatch.setattr(module, "messagebox", box)
        gui._move_context = MoveContext.UP
        controller.is_moving = False
        controller.at_top = True
        gui._poll_movement()
        box.showinfo.assert_called_once()


class TestIconTableWindow:
    """The 28 row table is taller than the Pi's 480px panel, so it scrolls."""

    def test_fits_the_pi_panel(self, gui):
        from bedliftcontrol.gui import ICON_TABLE_PAD

        visible = gui._icon_table_visible_height(480, 28)
        window_height = visible + 2 * ICON_TABLE_PAD
        assert window_height + 30 <= 480, "must leave room for the title bar too"

    def test_shows_everything_when_the_screen_is_big_enough(self, gui):
        from bedliftcontrol.gui import ICON_TABLE_ROW_PITCH

        assert gui._icon_table_visible_height(1050, 28) == 29 * ICON_TABLE_ROW_PITCH

    def test_caps_at_the_screen_on_a_small_panel(self, gui):
        from bedliftcontrol.gui import ICON_TABLE_ROW_PITCH

        assert gui._icon_table_visible_height(480, 28) < 29 * ICON_TABLE_ROW_PITCH

    def test_never_collapses_below_one_row(self, gui):
        from bedliftcontrol.gui import ICON_TABLE_ROW_PITCH

        assert gui._icon_table_visible_height(100, 28) == ICON_TABLE_ROW_PITCH

    def test_more_rows_never_make_a_taller_window_than_the_screen_allows(self, gui):
        from bedliftcontrol.gui import ICON_TABLE_PAD

        for rows in (1, 28, 200):
            assert gui._icon_table_visible_height(480, rows) + 2 * ICON_TABLE_PAD + 30 <= 480

    def test_uses_a_scrollable_frame(self, gui):
        import customtkinter

        customtkinter.CTkScrollableFrame.reset_mock()
        gui._weather_icons_window()
        assert customtkinter.CTkScrollableFrame.called


class TestDescentPercent:
    """The number counts the descent: 0% parked at the top, 100% all the way down."""

    @pytest.mark.parametrize(
        "position_fraction, expected",
        [(1.0, 0), (0.75, 25), (0.5, 50), (0.25, 75), (0.0, 100)],
    )
    def test_inverted_against_the_position(self, gui, position_fraction, expected):
        assert gui._descent_percent(position_fraction) == expected

    def test_counts_up_while_lowering(self, gui, controller):
        controller.is_moving = True
        shown = []
        gui.progress_label.configure.side_effect = lambda **kwargs: shown.append(kwargs.get("text"))
        for fraction in (1.0, 0.6, 0.2, 0.0):  # bed travelling down
            controller.position_fraction = fraction
            gui._poll_movement()
        assert shown == ["0%", "40%", "80%", "100%"]

    def test_counts_down_while_raising(self, gui, controller):
        controller.is_moving = True
        shown = []
        gui.progress_label.configure.side_effect = lambda **kwargs: shown.append(kwargs.get("text"))
        for fraction in (0.0, 0.4, 0.8, 1.0):  # bed travelling up
            controller.position_fraction = fraction
            gui._poll_movement()
        assert shown == ["100%", "60%", "20%", "0%"]


class TestDescentPrompt:
    """The 'switch the motors on and release the ropes' note only fits a bed parked up."""

    @pytest.fixture
    def box(self, monkeypatch):
        from bedliftcontrol import gui as module

        fake = MagicMock()
        monkeypatch.setattr(module, "messagebox", fake)
        return fake

    def test_shown_when_starting_from_the_top(self, gui, controller, box):
        controller.at_top = True
        gui._on_down()
        box.showinfo.assert_called_once()

    def test_not_shown_when_carrying_on_after_a_stop(self, gui, controller, box):
        controller.at_top = False
        controller.at_bottom = False
        gui._on_down()
        assert not box.showinfo.called

    def test_the_move_still_starts_without_the_prompt(self, gui, controller, box):
        controller.at_top = False
        gui._on_down()
        controller.run_async.assert_called_once_with(controller.move_down)

    def test_going_up_never_prompts(self, gui, controller, box):
        gui._on_up()
        assert not box.showinfo.called


class TestStopButtonLabel:
    def test_uses_a_smaller_font_than_the_arrows(self):
        """STOP is four glyphs; at the arrow size it is 348px wide in a 180px button."""
        from bedliftcontrol.gui import ARROW_FONT_SIZE, STOP_FONT_SIZE

        assert STOP_FONT_SIZE < ARROW_FONT_SIZE

    def test_the_label_fits_the_button(self):
        import tkinter
        import tkinter.font as tkfont

        from bedliftcontrol.gui import STOP_FONT_SIZE

        root = tkinter.Tk()
        root.withdraw()
        try:
            width = tkfont.Font(family="Roboto", size=STOP_FONT_SIZE, weight="bold").measure("STOP")
        finally:
            root.destroy()
        assert width <= 160, f"STOP renders {width}px into a 180px button"


class TestEndStopPrompts:
    """The prompts that bracket a full travel: motors on before, motors off after."""

    @pytest.fixture
    def box(self, monkeypatch):
        from bedliftcontrol import gui as module

        fake = MagicMock()
        monkeypatch.setattr(module, "messagebox", fake)
        return fake

    # --- starting up from the very bottom ---------------------------------

    def test_asks_before_leaving_the_bottom(self, gui, controller, box):
        controller.at_bottom = True
        box.askokcancel.return_value = True
        gui._on_up()
        box.askokcancel.assert_called_once_with("Bett hochfahren", "Motoren einschalten.")

    def test_confirming_starts_the_move(self, gui, controller, box):
        controller.at_bottom = True
        box.askokcancel.return_value = True
        gui._on_up()
        controller.run_async.assert_called_once_with(controller.move_up)

    def test_dismissing_the_dialog_changes_nothing(self, gui, controller, box):
        """Closing the window with X reports False, and then nothing may move."""
        controller.at_bottom = True
        box.askokcancel.return_value = False
        gui._on_up()
        assert not controller.run_async.called
        assert gui._move_context is None
        assert not gui.stop_button.place.called, "no stop button without a movement"

    def test_no_question_when_carrying_on_after_a_stop(self, gui, controller, box):
        controller.at_bottom = False
        controller.at_top = False
        gui._on_up()
        assert not box.askokcancel.called
        controller.run_async.assert_called_once_with(controller.move_up)

    # --- arriving at the very bottom --------------------------------------

    def test_says_good_night_at_the_bottom(self, gui, controller, box):
        controller.is_moving = False
        controller.at_bottom = True
        gui._move_context = MoveContext.DOWN
        gui._poll_movement()
        box.showinfo.assert_called_once_with("Bett unten", "Motoren ausschalten. Gute Nacht!")

    def test_no_good_night_after_a_stop_in_between(self, gui, controller, box):
        controller.is_moving = False
        controller.at_bottom = False
        controller.at_top = False
        gui._move_context = MoveContext.DOWN
        gui._poll_movement()
        assert not box.showinfo.called

    def test_no_good_night_when_arriving_at_the_top(self, gui, controller, box):
        controller.is_moving = False
        controller.at_top = True
        controller.at_bottom = False
        gui._move_context = MoveContext.UP
        gui._poll_movement()
        box.showinfo.assert_called_once_with(
            "Bett oben", "Sicherungsseile anbringen und Motoren ausschalten!"
        )

    def test_the_two_arrival_prompts_never_both_fire(self, gui, controller, box):
        """at_top and at_bottom are mutually exclusive, but the branch must be too."""
        controller.is_moving = False
        controller.at_top = True
        controller.at_bottom = True  # nonsense state, e.g. total_steps 0
        gui._move_context = MoveContext.DOWN
        gui._poll_movement()
        assert box.showinfo.call_count <= 1


class TestCorrectionsButtonGating:
    """Corrections are judged by eye against an end stop, so the window may only be
    opened while the bed is parked fully up or fully down and nothing is moving."""

    def test_enabled_at_the_bottom(self, controller, weather):
        controller.at_bottom = True
        controller.at_top = False
        built = BedGui(controller, weather)
        assert _states(built.corrections_button)[-1] == "normal"

    def test_enabled_at_the_top(self, controller, weather):
        controller.at_bottom = False
        controller.at_top = True
        controller.position_fraction = 1.0
        built = BedGui(controller, weather)
        assert _states(built.corrections_button)[-1] == "normal"

    def test_disabled_at_a_position_in_between(self, controller, weather):
        """That is the state a stop leaves behind."""
        controller.at_bottom = False
        controller.at_top = False
        controller.position_fraction = 0.4
        built = BedGui(controller, weather)
        assert _states(built.corrections_button)[-1] == "disabled"

    def test_disabled_while_moving(self, controller, weather):
        controller.at_bottom = True
        controller.is_moving = True
        built = BedGui(controller, weather)
        assert _states(built.corrections_button)[-1] == "disabled"

    def test_disabled_the_moment_a_move_starts(self, gui, controller):
        gui.corrections_button.configure.reset_mock()
        gui._on_up()
        assert "disabled" in _states(gui.corrections_button)

    def test_enabled_again_once_an_end_stop_is_reached(self, gui, controller):
        gui._on_up()
        controller.is_moving = False
        controller.at_top = True
        controller.at_bottom = False
        gui.corrections_button.configure.reset_mock()
        gui._poll_movement()
        assert _states(gui.corrections_button)[-1] == "normal"

    def test_stays_disabled_after_a_stop_in_between(self, gui, controller):
        gui._on_up()
        controller.is_moving = False
        controller.at_top = False
        controller.at_bottom = False
        gui.corrections_button.configure.reset_mock()
        gui._poll_movement()
        assert _states(gui.corrections_button)[-1] == "disabled"

    def test_an_open_correction_window_is_closed_when_a_move_starts(self, gui, controller):
        gui._corrections_window()
        assert "corrections" in gui._open_windows
        gui._on_up()
        assert "corrections" not in gui._open_windows

    def test_closing_it_is_harmless_when_it_was_never_open(self, gui):
        gui._on_up()  # must not raise
        assert "corrections" not in gui._open_windows


class TestCorrectionClickVersusHold:
    """A short press is worth a fixed nudge, a long press keeps the motor turning."""

    def test_press_schedules_the_hold_threshold(self, gui, controller):
        from bedliftcontrol.gui import CORRECTION_HOLD_DELAY_MS

        gui.app.after.reset_mock()
        gui._correction_pressed(controller.hold_front_up)
        assert gui.app.after.call_args.args[0] == CORRECTION_HOLD_DELAY_MS

    def test_press_alone_moves_nothing(self, gui, controller):
        gui._correction_pressed(controller.hold_front_up)
        assert not controller.run_async.called

    def test_quick_release_runs_the_fixed_correction(self, gui, controller):
        gui._correction_pressed(controller.hold_front_up)
        gui._correction_released(controller.correct_front_up)
        controller.run_async.assert_called_once_with(controller.correct_front_up)

    def test_quick_release_cancels_the_threshold(self, gui, controller):
        gui._correction_pressed(controller.hold_front_up)
        timer = gui._correction_timer
        gui._correction_released(controller.correct_front_up)
        gui.app.after_cancel.assert_called_once_with(timer)
        assert gui._correction_timer is None

    def test_the_threshold_starts_the_hold(self, gui, controller):
        gui._correction_pressed(controller.hold_front_up)
        gui.app.after.call_args.args[1]()  # the scheduled callback fires
        controller.run_async.assert_called_once_with(controller.hold_front_up)
        assert gui._correction_holding is True

    def test_releasing_a_hold_stops_the_motor(self, gui, controller):
        gui._correction_pressed(controller.hold_front_up)
        gui.app.after.call_args.args[1]()
        gui._correction_released(controller.correct_front_up)
        controller.stop.assert_called_once()

    def test_releasing_a_hold_does_not_also_nudge(self, gui, controller):
        gui._correction_pressed(controller.hold_front_up)
        gui.app.after.call_args.args[1]()
        controller.run_async.reset_mock()
        gui._correction_released(controller.correct_front_up)
        assert not controller.run_async.called, "a hold must not end in an extra click"
        assert gui._correction_holding is False

    def test_closing_the_window_ends_a_running_hold(self, gui, controller):
        """No release event is coming once the buttons are destroyed."""
        gui._corrections_window()
        gui._correction_pressed(controller.hold_front_up)
        gui.app.after.call_args.args[1]()
        gui._on_window_closed("corrections")
        controller.stop.assert_called_once()
        assert gui._correction_holding is False

    def test_closing_the_window_cancels_a_pending_threshold(self, gui, controller):
        gui._corrections_window()
        gui._correction_pressed(controller.hold_front_up)
        gui._on_window_closed("corrections")
        assert gui._correction_timer is None
        assert not controller.run_async.called

    def test_both_events_are_bound_on_every_button(self, gui, controller):
        button = MagicMock()
        gui._bind_correction(button, controller.correct_front_up, controller.hold_front_up)
        bound = {c.args[0] for c in button.bind.call_args_list}
        assert bound == {"<ButtonPress-1>", "<ButtonRelease-1>"}


class TestLocationSelection:
    """Choosing a location applies the cached reading at once and is remembered."""

    @pytest.fixture
    def weather_with_readings(self, weather):
        from bedliftcontrol.weather import Weather

        weather.selected = "phone"
        weather.readings = {
            "phone": Weather("Thun", 21.0, "Klarer Himmel", "sun", "2026-09-10T08:00"),
            "schilthorn": Weather("Schilthorn", -3.0, "Bedeckt", "cloud", "2026-09-10T08:00"),
        }
        weather.current = weather.readings["phone"]
        return weather

    def test_the_button_opens_the_window(self, gui):
        gui._location_window()
        assert "location" in gui._open_windows

    def test_one_button_per_location(self, gui):
        import customtkinter

        from bedliftcontrol.weather import LOCATIONS

        customtkinter.CTkButton.reset_mock()
        gui._location_window()
        texts = [c.kwargs.get("text") for c in customtkinter.CTkButton.call_args_list]
        for location in LOCATIONS:
            assert location.label in texts

    def test_the_active_location_is_highlighted(self, gui, weather):
        import customtkinter

        from bedliftcontrol.gui import BUTTON_COLOR, BUTTON_DISABLED_COLOR

        weather.selected = "lacure"
        customtkinter.CTkButton.reset_mock()
        gui._location_window()
        colors = {
            c.kwargs.get("text"): c.kwargs.get("fg_color")
            for c in customtkinter.CTkButton.call_args_list
            if "fg_color" in c.kwargs
        }
        assert colors["La Cure"] == BUTTON_COLOR
        assert colors["Schilthorn"] == BUTTON_DISABLED_COLOR

    def test_selecting_tells_the_service(self, gui, weather):
        gui._select_location("chatel")
        weather.select.assert_called_once_with("chatel")

    def test_selecting_is_persisted(self, gui, controller):
        gui._select_location("chatel")
        assert controller.config.weather_location == "chatel"
        controller.config.save.assert_called()

    def test_selecting_closes_the_window(self, gui):
        gui._location_window()
        gui._select_location("chatel")
        assert "location" not in gui._open_windows

    def test_selecting_applies_the_new_reading_at_once(self, gui, weather_with_readings):
        weather_with_readings.current = weather_with_readings.readings["schilthorn"]
        gui._select_location("schilthorn")
        gui.weather_city.configure.assert_any_call(text="Schilthorn")

    def test_selecting_does_not_start_a_second_timer_chain(self, gui, weather_with_readings):
        """_refresh_weather re-arms the 5s timer; applying must not go through it."""
        gui.app.after.reset_mock()
        gui._select_location("schilthorn")
        weather_calls = [c for c in gui.app.after.call_args_list
                         if c.args[1] is gui._refresh_weather]
        assert not weather_calls


class TestMissingReading:
    """A location that has never been fetched must not show the previous one's numbers."""

    def test_shows_the_label_and_says_so(self, gui, weather):
        weather.current = None
        weather.selected = "schilthorn"
        gui._apply_weather()
        gui.weather_city.configure.assert_any_call(text="Schilthorn")
        gui.weather_desc.configure.assert_any_call(text="Noch keine Daten")

    def test_clears_the_temperature_and_the_age(self, gui, weather):
        weather.current = None
        weather.selected = "schilthorn"
        gui._apply_weather()
        gui.weather_temp.configure.assert_any_call(text="")
        gui.weather_updated.configure.assert_any_call(text="")

    def test_clears_the_forecast_row(self, gui, weather, monkeypatch):
        weather.current = None
        weather.selected = "schilthorn"
        rendered = []
        monkeypatch.setattr(gui, "_render_forecast", lambda daily: rendered.append(daily))
        gui._apply_weather()
        assert rendered == [[]]

    def test_shows_the_placeholder_icon(self, gui, weather, monkeypatch):
        shown = []
        monkeypatch.setattr(gui.weather_icon, "show", shown.append)
        weather.current = None
        weather.selected = "schilthorn"
        gui._apply_weather()
        assert shown == ["unknown"]
