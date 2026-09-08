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
    fake.config.bed_up = False
    fake.config.total_steps = 28000
    fake.config.speed_pps = 800.0
    return fake


@pytest.fixture
def weather():
    fake = MagicMock()
    fake.current = None
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
        controller.config.bed_up = True
        built = BedGui(controller, weather)
        assert "disabled" in _states(built.up_button)

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
        controller.progress = 0.5
        gui._move_context = MoveContext.UP
        gui._poll_movement()
        gui.progress_label.configure.assert_any_call(text="50%")
        gui.progress_fill.place.assert_called()


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
        gui.clock_time.configure.assert_any_call(text="12:08")

    def test_keeps_ticking_without_a_weather_reading(self, gui, weather, monkeypatch):
        """No internet means _refresh_weather returns early - the clock must not care."""
        from datetime import datetime

        from bedliftcontrol import gui as module

        weather.current = None
        gui._refresh_weather()
        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8))
        gui._clock_text = None
        gui._update_clock()
        gui.clock_time.configure.assert_any_call(text="12:08")

    def test_does_not_redraw_within_the_same_minute(self, gui, monkeypatch):
        from datetime import datetime

        from bedliftcontrol import gui as module

        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8, 1))
        gui._clock_text = None
        gui._update_clock()
        gui.clock_time.configure.reset_mock()
        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8, 59))
        gui._update_clock()
        assert not gui.clock_time.configure.called

    def test_redraws_when_the_minute_flips(self, gui, monkeypatch):
        from datetime import datetime

        from bedliftcontrol import gui as module

        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 8))
        gui._clock_text = None
        gui._update_clock()
        gui.clock_time.configure.reset_mock()
        monkeypatch.setattr(module.clock, "now", lambda: datetime(2026, 9, 8, 12, 9))
        gui._update_clock()
        gui.clock_time.configure.assert_any_call(text="12:09")

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
