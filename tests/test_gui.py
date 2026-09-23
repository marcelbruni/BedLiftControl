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
    "CTkOptionMenu",
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


@pytest.fixture(autouse=True)
def elapsed(monkeypatch):
    """The waiting clock, under test control: elapsed[0] += n skips n seconds."""
    seconds = [1000.0]
    monkeypatch.setattr(gui_module, "_now", lambda: seconds[0])
    return seconds


@pytest.fixture(autouse=True)
def ready_inverter(monkeypatch):
    """Tests that are not about the inverter get one that is already running, so a
    movement starts straight away instead of waiting out the start-up."""
    inverter = MagicMock()
    inverter.on = True
    inverter.ready = True
    inverter.seconds_until_ready = 0.0
    monkeypatch.setattr(gui_module, "Inverter", lambda *args, **kwargs: inverter)
    return inverter


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
    fake.config.inverter_startup_seconds = 10.0
    fake.config.rope_delay_seconds = 10.0
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

    def test_the_rain_probability_is_drawn_not_an_emoji(self, gui, monkeypatch):
        """Noto Color Emoji on the Pi has no drop glyph and renders a tofu box."""
        from bedliftcontrol.weather import DailyForecast

        drawn = []
        monkeypatch.setattr(gui_module.tkinter, "Canvas", lambda *a, **k: MagicMock())
        monkeypatch.setattr(gui_module.icons, "draw_drop",
                            lambda canvas, size: drawn.append(size))
        import customtkinter

        customtkinter.CTkLabel.reset_mock()
        gui._render_forecast([DailyForecast("Do", "2026-09-03", "sun", 22.0, 12.0, rain=80)])
        texts = [c.kwargs.get("text", "") for c in customtkinter.CTkLabel.call_args_list]
        assert drawn == [gui_module.RAIN_DROP_SIZE]
        assert "80%" in texts
        assert not any("💧" in (text or "") for text in texts)

    def test_a_day_without_a_rain_value_gets_no_drop(self, gui, monkeypatch):
        from bedliftcontrol.weather import DailyForecast

        drawn = []
        monkeypatch.setattr(gui_module.icons, "draw_drop",
                            lambda canvas, size: drawn.append(size))
        gui._render_forecast([DailyForecast("Do", "2026-09-03", "sun", 22.0, 12.0, rain=None)])
        assert drawn == []


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
        from bedliftcontrol.gui import WINDOW_PAD

        visible = gui._icon_table_visible_height(480, 28)
        window_height = visible + 2 * WINDOW_PAD
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
        from bedliftcontrol.gui import WINDOW_PAD

        for rows in (1, 28, 200):
            assert gui._icon_table_visible_height(480, rows) + 2 * WINDOW_PAD + 30 <= 480

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


class TestNoPromptBeforeMoving:
    """A tap on an arrow moves the bed. Mains is handled by the app, so there is
    nothing left to confirm before it does."""

    @pytest.fixture
    def box(self, monkeypatch):
        fake = MagicMock()
        monkeypatch.setattr(gui_module, "messagebox", fake)
        return fake

    def test_lowering_from_the_top_asks_nothing(self, gui, controller, box, elapsed):
        """No dialog - the rope reminder rides on the countdown instead."""
        controller.at_top = True
        gui._on_down()
        assert not box.showinfo.called and not box.askokcancel.called
        elapsed[0] += 30
        gui._wait_before_move()
        controller.run_async.assert_called_once_with(controller.move_down)

    def test_raising_from_the_bottom_asks_nothing(self, gui, controller, box):
        controller.at_bottom = True
        gui._on_up()
        assert not box.showinfo.called and not box.askokcancel.called
        controller.run_async.assert_called_once_with(controller.move_up)

    def test_carrying_on_after_a_stop_asks_nothing(self, gui, controller, box):
        controller.at_top = False
        controller.at_bottom = False
        gui._on_down()
        assert not box.showinfo.called and not box.askokcancel.called


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
    """What the bed says when it arrives at an end stop."""

    @pytest.fixture
    def box(self, monkeypatch):
        from bedliftcontrol import gui as module

        fake = MagicMock()
        monkeypatch.setattr(module, "messagebox", fake)
        return fake

    def test_arriving_at_the_bottom_says_nothing(self, gui, controller, box):
        """Mains switches itself off down there, so there is nothing left to instruct."""
        controller.is_moving = False
        controller.at_bottom = True
        gui._move_context = MoveContext.DOWN
        gui._poll_movement()
        assert not box.showinfo.called

    def test_arriving_at_the_top_asks_for_the_ropes(self, gui, controller, box):
        controller.is_moving = False
        controller.at_top = True
        controller.at_bottom = False
        gui._move_context = MoveContext.UP
        gui._poll_movement()
        box.showinfo.assert_called_once_with("Bett sichern", "Sicherungsseile anbringen!")

    def test_no_prompt_after_a_stop_in_between(self, gui, controller, box):
        controller.is_moving = False
        controller.at_bottom = False
        controller.at_top = False
        gui._move_context = MoveContext.UP
        gui._poll_movement()
        assert not box.showinfo.called

    def test_the_two_arrival_branches_never_both_fire(self, gui, controller, box):
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

    def test_the_dropdown_offers_every_location(self, gui):
        import customtkinter

        from bedliftcontrol.weather import LOCATIONS

        customtkinter.CTkOptionMenu.reset_mock()
        gui._settings_window()
        values = customtkinter.CTkOptionMenu.call_args.kwargs["values"]
        assert values == [place.label for place in LOCATIONS]

    def test_the_dropdown_starts_on_the_selected_one(self, gui, weather):
        weather.selected = "lacure"
        gui._settings_window()
        gui._location_menu.set.assert_called_once_with("La Cure")

    def test_choosing_a_label_selects_its_location(self, gui, weather):
        gui._on_location_chosen("Châtel")
        weather.select.assert_called_once_with("chatel")

    def test_an_unknown_label_changes_nothing(self, gui, weather):
        gui._on_location_chosen("Gibt es nicht")
        assert not weather.select.called

    def test_selecting_tells_the_service(self, gui, weather):
        gui._select_location("chatel")
        weather.select.assert_called_once_with("chatel")

    def test_selecting_is_persisted(self, gui, controller):
        gui._select_location("chatel")
        assert controller.config.weather_location == "chatel"
        controller.config.save.assert_called()

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


class TestHistoryWindow:
    @pytest.fixture
    def gui_with_history(self, controller, weather):
        from bedliftcontrol.history import LocationVisit

        tracker = MagicMock()
        tracker.nights = 7
        tracker.locations = [
            LocationVisit("2026-09-12T18:30:00", "Thun", 46.7210, 7.5644),
            LocationVisit("2026-09-14T17:04:12", "Zurich", 47.3667, 8.5500),
        ]
        return BedGui(controller, weather, history=tracker), tracker

    def test_the_settings_window_offers_it(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._settings_window()
        texts = [c.kwargs.get("text") for c in customtkinter.CTkButton.call_args_list]
        assert "Historie" in texts

    def test_opens_and_closes(self, gui):
        gui._history_window()
        assert "history" in gui._open_windows
        gui._history_window()
        assert "history" not in gui._open_windows

    def test_shows_the_night_count(self, gui_with_history):
        import customtkinter

        built, _ = gui_with_history
        customtkinter.CTkLabel.reset_mock()
        built._history_window()
        texts = [c.kwargs.get("text") for c in customtkinter.CTkLabel.call_args_list]
        assert "\u00dcbernachtungen: 7" in texts

    def test_lists_the_newest_location_first(self, gui_with_history):
        import customtkinter

        built, _ = gui_with_history
        customtkinter.CTkLabel.reset_mock()
        built._history_window()
        texts = [c.kwargs.get("text") or "" for c in customtkinter.CTkLabel.call_args_list]
        entries = [text for text in texts if "(" in text and ")" in text]
        assert entries[0].startswith("14.09.2026 17:04")
        assert "Zurich" in entries[0]
        assert "Thun" in entries[1]

    def test_says_so_when_there_is_nothing_yet(self, gui):
        import customtkinter

        tracker = MagicMock()
        tracker.nights = 0
        tracker.locations = []
        gui.history = tracker
        customtkinter.CTkLabel.reset_mock()
        gui._history_window()
        texts = [c.kwargs.get("text") for c in customtkinter.CTkLabel.call_args_list]
        assert "Noch keine Standorte aufgezeichnet" in texts

    def test_works_without_a_tracker(self, gui):
        gui.history = None
        gui._history_window()  # must not raise
        assert "history" in gui._open_windows

    def test_the_timestamp_is_formatted(self, gui):
        from bedliftcontrol.history import LocationVisit

        visit = LocationVisit("2026-09-14T17:04:12", "Thun", 46.7210, 7.5644)
        assert gui._format_visit(visit).startswith("14.09.2026 17:04   Thun   (46.7210, 7.5644)")

    def test_an_unparsable_timestamp_is_shown_raw(self, gui):
        from bedliftcontrol.history import LocationVisit

        visit = LocationVisit("kaputt", "Thun", 46.7210, 7.5644)
        assert gui._format_visit(visit).startswith("kaputt")

    def test_the_window_fits_the_pi_panel(self, gui):
        from bedliftcontrol.gui import WINDOW_PAD

        visible = gui._history_visible_height(480, 500)
        assert visible + 2 * WINDOW_PAD + gui_module.HISTORY_HEADER_HEIGHT + 30 <= 480


class FakeInverter:
    """Stateful stand-in: the GUI has to see its own switching reflected."""

    def __init__(self, on=False, ready=False):
        self.on = on
        self.startup_seconds = 10.0
        self._ready = ready
        self.turn_on_calls = 0

    @property
    def ready(self):
        return self._ready

    @property
    def seconds_until_ready(self):
        return 0.0 if self._ready else 7.2

    def turn_on(self):
        self.turn_on_calls += 1
        if self.on:
            return False
        self.on = True
        return True

    def turn_off(self):
        was_on, self.on = self.on, False
        self._ready = False
        return was_on

    def toggle(self):
        self.turn_off() if self.on else self.turn_on()
        return self.on

    def finish_starting(self):
        self._ready = True


class TestPowerButton:
    @pytest.fixture
    def powered(self, controller, weather):
        inverter = FakeInverter()
        return BedGui(controller, weather, inverter=inverter), inverter

    def test_it_starts_grey(self, powered):
        built, _ = powered
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_OFF_COLOR

    def test_the_label_never_changes(self, powered):
        """The state is the colour; the text stays put."""
        built, _ = powered
        built._toggle_inverter()
        assert "text" not in built.power_button.configure.call_args.kwargs

    def test_tapping_switches_it_on(self, powered):
        built, inverter = powered
        built._toggle_inverter()
        assert inverter.on is True
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_ON_COLOR

    def test_tapping_again_switches_it_off(self, powered):
        built, inverter = powered
        built._toggle_inverter()
        built._toggle_inverter()
        assert inverter.on is False

    def test_the_colour_follows_the_state(self, powered):
        built, _ = powered
        built._toggle_inverter()
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_ON_COLOR

    def test_it_cannot_be_switched_while_the_bed_moves(self, powered, controller):
        """Cutting mains mid travel drops the motors and the stored position with them."""
        built, inverter = powered
        built._toggle_inverter()
        controller.is_moving = True
        built._toggle_inverter()
        assert inverter.on is True

    def test_it_is_greyed_out_while_the_bed_moves(self, powered, controller):
        built, _ = powered
        controller.is_moving = True
        built._update_power_button()
        assert built.power_button.configure.call_args.kwargs["state"] == "disabled"


class TestInverterBeforeMoving:
    @pytest.fixture
    def cold(self, controller, weather):
        inverter = FakeInverter()
        return BedGui(controller, weather, inverter=inverter), inverter

    @pytest.fixture
    def warm(self, controller, weather):
        inverter = FakeInverter(on=True, ready=True)
        return BedGui(controller, weather, inverter=inverter), inverter

    def test_a_running_inverter_lets_the_move_start_at_once(self, warm, controller):
        built, _ = warm
        built._start_move(MoveContext.UP, controller.move_up)
        controller.run_async.assert_called_once_with(controller.move_up)

    def test_a_cold_inverter_is_switched_on(self, cold, controller):
        built, inverter = cold
        built._start_move(MoveContext.UP, controller.move_up)
        assert inverter.on is True

    def test_the_move_waits_for_the_start_up(self, cold, controller):
        built, _ = cold
        built._start_move(MoveContext.UP, controller.move_up)
        assert not controller.run_async.called

    def test_the_stop_button_shows_the_countdown(self, cold, controller):
        built, _ = cold
        built._start_move(MoveContext.UP, controller.move_up)
        assert "230V" in built.stop_button.configure.call_args.kwargs["text"]
        assert "8s" in built.stop_button.configure.call_args.kwargs["text"], "7.2s rounds up"

    def test_the_countdown_keeps_itself_going(self, cold, controller):
        built, _ = cold
        built.app.after.reset_mock()
        built._start_move(MoveContext.UP, controller.move_up)
        delays = [c.args[0] for c in built.app.after.call_args_list]
        assert gui_module.COUNTDOWN_TICK_MS in delays

    def test_the_move_starts_once_the_inverter_is_up(self, cold, controller, elapsed):
        built, inverter = cold
        built._start_move(MoveContext.UP, controller.move_up)
        inverter.finish_starting()
        elapsed[0] += 10
        built._wait_before_move()
        controller.run_async.assert_called_once_with(controller.move_up)

    def test_the_stop_button_says_stop_again_once_it_moves(self, cold, controller, elapsed):
        built, inverter = cold
        built._start_move(MoveContext.UP, controller.move_up)
        inverter.finish_starting()
        elapsed[0] += 10
        built._wait_before_move()
        assert built.stop_button.configure.call_args.kwargs["text"] == "STOP"

    def test_the_move_starts_only_once(self, cold, controller, elapsed):
        """A tick that arrives after the movement already started must not start it twice."""
        built, inverter = cold
        built._start_move(MoveContext.UP, controller.move_up)
        inverter.finish_starting()
        elapsed[0] += 10
        built._wait_before_move()
        built._wait_before_move()
        assert controller.run_async.call_count == 1

    def test_stop_during_the_countdown_drops_the_move(self, cold, controller, elapsed):
        built, inverter = cold
        built._start_move(MoveContext.UP, controller.move_up)
        built._on_stop()
        inverter.finish_starting()
        elapsed[0] += 10
        built._wait_before_move()
        assert not controller.run_async.called

    def test_stop_during_the_countdown_does_not_stop_the_controller(self, cold, controller):
        """Nothing is moving yet; the stop belongs to the pending move, not the motors."""
        built, _ = cold
        built._start_move(MoveContext.UP, controller.move_up)
        built._on_stop()
        assert not controller.stop.called

    def test_stop_during_the_countdown_leaves_the_inverter_running(self, cold, controller):
        """It was asked for; switching it back off is the 230V button's job."""
        built, inverter = cold
        built._start_move(MoveContext.UP, controller.move_up)
        built._on_stop()
        assert inverter.on is True

    def test_stop_during_the_countdown_gives_the_arrows_back(self, cold, controller):
        built, _ = cold
        built._start_move(MoveContext.UP, controller.move_up)
        built.up_button.configure.reset_mock()
        built._on_stop()
        assert _states(built.up_button)[-1] == "normal"

    def test_a_stop_while_moving_still_stops_the_motors(self, warm, controller):
        built, _ = warm
        built._start_move(MoveContext.UP, controller.move_up)
        built._on_stop()
        controller.stop.assert_called_once()


class TestInverterSettings:
    @pytest.fixture
    def settings(self, controller, weather):
        import customtkinter

        inverter = FakeInverter()
        built = BedGui(controller, weather, inverter=inverter)
        customtkinter.CTkSlider.reset_mock()
        customtkinter.CTkButton.reset_mock()
        built._settings_window()
        return built, inverter

    @staticmethod
    def button_texts():
        import customtkinter

        return [c.kwargs.get("text") for c in customtkinter.CTkButton.call_args_list]


    def test_the_delay_slider_spans_zero_to_fifteen(self, settings):
        import customtkinter

        bounds = [(c.kwargs.get("from_"), c.kwargs.get("to"))
                  for c in customtkinter.CTkSlider.call_args_list]
        assert (0.0, 15.0) in bounds

    def test_the_delay_slider_snaps_to_whole_seconds(self, settings):
        import customtkinter

        steps = [c.kwargs.get("number_of_steps") for c in customtkinter.CTkSlider.call_args_list]
        assert 15 in steps

    def test_moving_the_slider_stores_the_value(self, settings, controller):
        built, _ = settings
        built._on_inverter_delay_change(4.0)
        assert controller.config.inverter_startup_seconds == 4.0
        controller.config.save.assert_called()

    def test_moving_the_slider_reaches_the_inverter(self, settings):
        """Otherwise the new value would only take effect after a restart."""
        built, inverter = settings
        built._on_inverter_delay_change(3.0)
        assert inverter.startup_seconds == 3.0

    def test_a_slider_position_between_seconds_is_rounded(self, settings, controller):
        built, _ = settings
        built._on_inverter_delay_change(6.4)
        assert controller.config.inverter_startup_seconds == 6.0

    def test_the_value_is_shown_next_to_the_slider(self, settings):
        built, _ = settings
        built._on_inverter_delay_change(7.0)
        built._delay_value_label.configure.assert_called_with(text="7 s")

    def test_zero_seconds_can_be_set(self, settings, controller):
        built, inverter = settings
        built._on_inverter_delay_change(0.0)
        assert controller.config.inverter_startup_seconds == 0.0
        assert inverter.startup_seconds == 0.0

    def test_no_switch_for_the_automatic(self):
        """It was removed: without it a movement has no power, which is not an option
        worth offering."""
        assert not any("Automatik" in (text or "") for text in self.button_texts())
class TestPowerAfterMoving:
    """Mains is switched off again once the bed is parked at an end stop."""

    @pytest.fixture
    def box(self, monkeypatch):
        fake = MagicMock()
        monkeypatch.setattr(gui_module, "messagebox", fake)
        return fake

    @pytest.fixture
    def running(self, controller, weather):
        inverter = FakeInverter(on=True, ready=True)
        controller.is_moving = False
        return BedGui(controller, weather, inverter=inverter), inverter

    @staticmethod
    def arrive(built, controller, context, at_top=False, at_bottom=False):
        controller.is_moving = False
        controller.at_top = at_top
        controller.at_bottom = at_bottom
        built._move_context = context
        built._poll_movement()

    def test_arriving_at_the_top_switches_it_off(self, running, controller, box):
        built, inverter = running
        self.arrive(built, controller, MoveContext.UP, at_top=True)
        assert inverter.on is False

    def test_arriving_at_the_bottom_switches_it_off(self, running, controller, box):
        built, inverter = running
        self.arrive(built, controller, MoveContext.DOWN, at_bottom=True)
        assert inverter.on is False

    def test_the_rope_prompt_comes_while_mains_is_still_on(self, running, controller, box):
        """The motors hold the bed until the ropes are on; only the OK cuts the power."""
        built, inverter = running
        seen = []
        box.showinfo.side_effect = lambda *args, **kwargs: seen.append(inverter.on)
        self.arrive(built, controller, MoveContext.UP, at_top=True)
        assert seen == [True]
        assert inverter.on is False

    def test_the_button_follows(self, running, controller, box):
        built, inverter = running
        self.arrive(built, controller, MoveContext.UP, at_top=True)
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_OFF_COLOR

    def test_a_stop_in_between_leaves_it_running(self, running, controller, box):
        built, inverter = running
        self.arrive(built, controller, MoveContext.DOWN)
        assert inverter.on is True

    def test_the_whole_round_trip(self, controller, weather, box, elapsed):
        """Down a bit, STOP, then all the way up: red throughout, off at the top."""
        inverter = FakeInverter()
        built = BedGui(controller, weather, inverter=inverter)

        controller.at_top = True
        controller.at_bottom = False
        built._start_move(MoveContext.DOWN, controller.move_down)
        inverter.finish_starting()
        elapsed[0] += 30
        built._wait_before_move()
        assert inverter.on is True
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_ON_COLOR

        self.arrive(built, controller, MoveContext.DOWN)  # stopped half way
        assert inverter.on is True, "still hanging, the motors still need power"

        built._start_move(MoveContext.UP, controller.move_up)
        elapsed[0] += 30
        built._wait_before_move()
        self.arrive(built, controller, MoveContext.UP, at_top=True)
        assert inverter.on is False
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_OFF_COLOR

    def test_an_inverter_that_is_already_off_is_left_alone(self, controller, weather, box):
        built = BedGui(controller, weather, inverter=FakeInverter())
        built.power_button.configure.reset_mock()
        self.arrive(built, controller, MoveContext.DOWN, at_bottom=True)
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_OFF_COLOR


class TestCountdownText:
    """The start-up wait is dead time at the bed, so the button uses it for the one
    thing that has to happen before the bed can be lowered."""

    @pytest.fixture
    def waiting(self, controller, weather):
        inverter = FakeInverter()
        built = BedGui(controller, weather, inverter=inverter)
        return built, inverter

    @staticmethod
    def countdown(built):
        return built.stop_button.configure.call_args.kwargs["text"]

    def test_lowering_from_the_top_asks_for_the_ropes(self, waiting, controller):
        built, _ = waiting
        controller.at_top = True
        controller.at_bottom = False
        built._start_move(MoveContext.DOWN, controller.move_down)
        assert "Seile lösen!" in self.countdown(built)
        assert "230V" in self.countdown(built)

    def test_once_mains_is_up_only_the_ropes_are_left(self, waiting, controller, elapsed):
        built, inverter = waiting
        controller.at_top = True
        built._start_move(MoveContext.DOWN, controller.move_down)
        inverter.finish_starting()
        elapsed[0] += 7
        built._wait_before_move()
        assert "230V" not in self.countdown(built)
        assert "Seile" in self.countdown(built)

    def test_raising_says_nothing_about_ropes(self, waiting, controller):
        built, _ = waiting
        controller.at_bottom = True
        controller.at_top = False
        built._start_move(MoveContext.UP, controller.move_up)
        assert "Seile" not in self.countdown(built)

    def test_carrying_on_after_a_stop_says_nothing_about_ropes(self, waiting, controller):
        """Half way down the ropes are long off."""
        built, _ = waiting
        controller.at_top = False
        controller.at_bottom = False
        built._start_move(MoveContext.DOWN, controller.move_down)
        assert "Seile" not in self.countdown(built)

    def test_the_hint_is_gone_once_it_moves(self, waiting, controller, elapsed):
        built, inverter = waiting
        controller.at_top = True
        built._start_move(MoveContext.DOWN, controller.move_down)
        inverter.finish_starting()
        elapsed[0] += 30
        built._wait_before_move()
        assert self.countdown(built) == "STOP"

    def test_it_counts_down(self, waiting, controller, elapsed):
        built, _ = waiting
        controller.at_top = True
        built._start_move(MoveContext.DOWN, controller.move_down)
        first = self.countdown(built)
        elapsed[0] += 5
        built._wait_before_move()
        assert self.countdown(built) != first


class TestRopeDelay:
    """Lowering from the top waits longer on purpose: the safety ropes have to come
    off first, and that time is on top of the inverter's start-up."""

    @pytest.fixture
    def parked_up(self, controller, weather):
        controller.at_top = True
        controller.at_bottom = False
        controller.config.inverter_startup_seconds = 10.0
        controller.config.rope_delay_seconds = 10.0
        inverter = FakeInverter(on=True, ready=True)  # mains already up: only ropes left
        return BedGui(controller, weather, inverter=inverter), inverter

    def test_lowering_from_the_top_waits(self, parked_up, controller):
        built, _ = parked_up
        built._start_move(MoveContext.DOWN, controller.move_down)
        assert not controller.run_async.called

    def test_and_starts_once_the_time_is_up(self, parked_up, controller, elapsed):
        built, _ = parked_up
        built._start_move(MoveContext.DOWN, controller.move_down)
        elapsed[0] += 10
        built._wait_before_move()
        controller.run_async.assert_called_once_with(controller.move_down)

    def test_it_is_not_up_a_second_too_early(self, parked_up, controller, elapsed):
        built, _ = parked_up
        built._start_move(MoveContext.DOWN, controller.move_down)
        elapsed[0] += 9
        built._wait_before_move()
        assert not controller.run_async.called

    def test_raising_never_waits_for_ropes(self, controller, weather, elapsed):
        controller.at_bottom = True
        controller.at_top = False
        built = BedGui(controller, weather, inverter=FakeInverter(on=True, ready=True))
        built._start_move(MoveContext.UP, controller.move_up)
        controller.run_async.assert_called_once_with(controller.move_up)

    def test_carrying_on_downwards_after_a_stop_never_waits(self, controller, weather):
        """Half way down the ropes are long off."""
        controller.at_top = False
        controller.at_bottom = False
        built = BedGui(controller, weather, inverter=FakeInverter(on=True, ready=True))
        built._start_move(MoveContext.DOWN, controller.move_down)
        controller.run_async.assert_called_once_with(controller.move_down)

    def test_it_adds_to_the_inverter_start_up(self, controller, weather, elapsed):
        """Ten seconds of mains plus ten of ropes is twenty, not ten."""
        controller.at_top = True
        controller.at_bottom = False
        cold = FakeInverter()  # answers 7.2s until ready
        built = BedGui(controller, weather, inverter=cold)
        built._start_move(MoveContext.DOWN, controller.move_down)
        cold.finish_starting()
        elapsed[0] += 8
        built._wait_before_move()
        assert not controller.run_async.called, "the rope time still has to run"
        elapsed[0] += 10
        built._wait_before_move()
        controller.run_async.assert_called_once_with(controller.move_down)

    def test_zero_seconds_means_no_wait(self, controller, weather):
        controller.at_top = True
        controller.config.rope_delay_seconds = 0.0
        built = BedGui(controller, weather, inverter=FakeInverter(on=True, ready=True))
        built._start_move(MoveContext.DOWN, controller.move_down)
        controller.run_async.assert_called_once_with(controller.move_down)

    def test_stop_during_the_rope_time_drops_the_move(self, parked_up, controller, elapsed):
        built, _ = parked_up
        built._start_move(MoveContext.DOWN, controller.move_down)
        built._on_stop()
        elapsed[0] += 30
        built._wait_before_move()
        assert not controller.run_async.called


class TestRopeDelaySetting:
    @pytest.fixture
    def settings(self, controller, weather):
        import customtkinter

        built = BedGui(controller, weather, inverter=FakeInverter())
        customtkinter.CTkSlider.reset_mock()
        built._settings_window()
        return built

    def test_the_slider_spans_zero_to_twenty(self, settings):
        import customtkinter

        bounds = [(c.kwargs.get("from_"), c.kwargs.get("to"))
                  for c in customtkinter.CTkSlider.call_args_list]
        assert (0.0, 20.0) in bounds

    def test_it_snaps_to_whole_seconds(self, settings):
        import customtkinter

        steps = [c.kwargs.get("number_of_steps") for c in customtkinter.CTkSlider.call_args_list]
        assert 20 in steps

    def test_moving_it_stores_the_value(self, settings, controller):
        settings._on_rope_delay_change(6.0)
        assert controller.config.rope_delay_seconds == 6.0
        controller.config.save.assert_called()

    def test_the_value_is_shown(self, settings):
        settings._on_rope_delay_change(6.0)
        settings._rope_value_label.configure.assert_called_with(text="6 s")

    def test_it_is_rounded_to_whole_seconds(self, settings, controller):
        settings._on_rope_delay_change(6.7)
        assert controller.config.rope_delay_seconds == 7.0

    def test_the_two_delays_are_separate_settings(self, settings, controller):
        settings._on_rope_delay_change(3.0)
        settings._on_inverter_delay_change(12.0)
        assert controller.config.rope_delay_seconds == 3.0
        assert controller.config.inverter_startup_seconds == 12.0


class TestWeekdayLabel:
    def test_it_shows_the_day_of_the_reading(self, gui, weather):
        from bedliftcontrol.weather import Weather

        weather.current = Weather("Thun", 21.4, "Klar", "sun", "2026-09-23T11:00")
        gui._refresh_weather()
        gui.weather_day.configure.assert_any_call(text="Mi")

    def test_it_is_blank_without_a_reading(self, gui, weather):
        weather.current = None
        gui._refresh_weather()
        gui.weather_day.configure.assert_any_call(text="")


class TestCloseButtons:
    """A touch panel has no comfortable window decoration, so both windows that are
    opened often carry their own close button."""

    @staticmethod
    def close_button(window_name):
        import customtkinter

        return [c for c in customtkinter.CTkButton.call_args_list
                if c.kwargs.get("text") == "Schliessen"]

    def test_the_settings_window_has_one(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._settings_window()
        assert self.close_button("settings")

    def test_it_spans_the_three_buttons_above(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._settings_window()
        width = self.close_button("settings")[0].kwargs["width"]
        assert width == gui_module.SETTINGS_ROW_WIDTH

    def test_the_corrections_window_has_one(self, gui, controller):
        import customtkinter

        controller.at_bottom = True
        customtkinter.CTkButton.reset_mock()
        gui._corrections_window()
        assert self.close_button("corrections")

    def test_it_spans_both_correction_columns(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._corrections_window()
        width = self.close_button("corrections")[0].kwargs["width"]
        assert width == gui_module.CORRECTION_ROW_WIDTH

    def test_it_closes_the_settings_window(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._settings_window()
        assert "settings" in gui._open_windows
        self.close_button("settings")[0].kwargs["command"]()
        assert "settings" not in gui._open_windows

    def test_it_closes_the_corrections_window(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._corrections_window()
        assert "corrections" in gui._open_windows
        self.close_button("corrections")[0].kwargs["command"]()
        assert "corrections" not in gui._open_windows

    def test_it_is_big_enough_for_a_finger(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._settings_window()
        assert self.close_button("settings")[0].kwargs["height"] == gui_module.CLOSE_BUTTON_HEIGHT


class TestWindowPlacement:
    """Both windows open where the hand already is: right of the bar, at the top."""

    @pytest.fixture
    def positioned(self, gui):
        gui.progress_frame.winfo_rootx.return_value = 12
        gui.progress_frame.winfo_width.return_value = 48
        return gui

    def test_the_settings_window_sits_beside_the_bar(self, positioned):
        positioned._settings_window()
        window = positioned._open_windows["settings"]
        assert window.geometry.call_args.args[0] == "+60+0"

    def test_the_corrections_window_sits_beside_the_bar(self, positioned):
        positioned._corrections_window()
        window = positioned._open_windows["corrections"]
        assert window.geometry.call_args.args[0] == "+60+0"

    def test_the_size_is_set_before_the_position(self, positioned):
        """geometry() with only a position keeps the size that was set before it."""
        positioned._settings_window()
        window = positioned._open_windows["settings"]
        sizes = [c.args[0] for c in window.geometry.call_args_list]
        assert sizes[0] == "520x390" and sizes[-1] == "+60+0"
