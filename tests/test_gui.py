"""Tests for the GUI logic. customtkinter is mocked (conftest.py), so no window opens.

The ``ctk_widgets`` fixture makes each widget constructor return a new mock so
buttons/labels/windows can be told apart, and stubs out the message box.
"""

from unittest.mock import MagicMock

import pytest

from bedliftcontrol import gui as gui_module
from bedliftcontrol.gui import (
    BAR_CORNER_RADIUS,
    BED_ICON_MARGIN,
    ICON_HEIGHT,
    STUB_HEIGHT,
    MIN_BAR_FRACTION,
    BedGui,
    MoveContext,
)

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
    "CTkTextbox",
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
    yield
    for name in WIDGETS:
        getattr(customtkinter, name).side_effect = None


FIXED_TODAY = "2026-09-03"


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    """The panel rolls the forecast over at midnight, so "today" has to stand still."""
    monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: FIXED_TODAY)


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
    """The stub left when the bed is up is counted in pixels, so the window and the
    kiosk screen look the same - as a fraction it grew with the window."""

    STUB_PIXELS = STUB_HEIGHT

    def test_the_stub_is_sized_to_the_icon(self, gui):
        gui.progress_track.winfo_height.return_value = 200
        gui._set_bar(1.0)  # 1.0 == bed up
        gui.progress_fill.place.assert_called_with(
            relx=0, rely=0, relwidth=1.0, relheight=self.STUB_PIXELS / 200, anchor="nw")

    def test_the_same_pixels_on_a_taller_screen(self, gui):
        """The kiosk track is 60px taller than the window's; the stub must not follow."""
        gui.progress_track.winfo_height.return_value = 400
        gui._set_bar(1.0)
        gui.progress_fill.place.assert_called_with(
            relx=0, rely=0, relwidth=1.0, relheight=self.STUB_PIXELS / 400, anchor="nw")

    def test_the_rounding_has_room_above_the_icon(self):
        """With less than its radius above the icon, the cap shows as two corners."""
        above_the_icon = STUB_HEIGHT - ICON_HEIGHT - BED_ICON_MARGIN
        assert above_the_icon >= BAR_CORNER_RADIUS - 2

    def test_before_the_layout_it_falls_back(self, gui):
        gui._set_bar(1.0)  # the mock track reports height 0
        gui.progress_fill.place.assert_called_with(
            relx=0, rely=0, relwidth=1.0, relheight=MIN_BAR_FRACTION, anchor="nw")

    def test_bar_still_fills_the_track_when_down(self, gui):
        gui.progress_track.winfo_height.return_value = 200
        gui._set_bar(0.0)  # 0.0 == bed down
        gui.progress_fill.place.assert_called_with(relx=0, rely=0, relwidth=1.0, relheight=1.0, anchor="nw")

    def test_clamps_out_of_range(self, gui):
        gui._set_bar(2.0)  # clamps to bed up -> stub
        gui.progress_fill.place.assert_called_with(
            relx=0, rely=0, relwidth=1.0, relheight=MIN_BAR_FRACTION, anchor="nw")


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


class TestViewToggle:
    """The panels live in the centre area now; the bar button leads in and out again."""

    def test_the_settings_button_opens_the_settings(self, gui):
        gui._on_settings_button()
        assert gui._view == gui_module.VIEW_SETTINGS

    def test_pressing_it_again_goes_back_to_the_weather(self, gui):
        gui._on_settings_button()
        gui._on_settings_button()
        assert gui._view == gui_module.VIEW_WEATHER

    def test_the_corrections_button_works_the_same_way(self, gui):
        gui._on_corrections_button()
        assert gui._view == gui_module.VIEW_CORRECTIONS
        gui._on_corrections_button()
        assert gui._view == gui_module.VIEW_WEATHER

    def test_one_panel_replaces_the_other(self, gui):
        """Two panels at once is what the separate windows allowed and this must not."""
        gui._on_settings_button()
        gui._on_corrections_button()
        assert gui._view == gui_module.VIEW_CORRECTIONS

    def test_the_settings_button_leads_out_of_a_sub_panel(self, gui):
        gui._on_settings_button()
        gui._show_history()
        gui._on_settings_button()
        assert gui._view == gui_module.VIEW_SETTINGS

    def test_entering_the_same_view_twice_rebuilds_nothing(self, gui):
        gui._show_view(gui_module.VIEW_SETTINGS)
        first = gui._kiosk_button
        gui._show_view(gui_module.VIEW_SETTINGS)
        assert gui._kiosk_button is first


class TestSettingsValues:
    def test_steps_change_updates_value_label(self, gui, controller):
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui._on_steps_change(29000)
        assert controller.config.total_steps == 29000
        gui._steps_value_label.configure.assert_any_call(text="29000")

    def test_speed_change_updates_value_label(self, gui, controller):
        gui._show_view(gui_module.VIEW_SETTINGS)
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
        gui._show_view(gui_module.VIEW_SETTINGS)
        assert gui._kiosk_button is not None

    def test_leaving_the_settings_drops_the_button_reference(self, gui):
        """_refresh_kiosk_button must not configure a destroyed widget."""
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui._go_back()
        assert gui._kiosk_button is None
        gui._toggle_kiosk()  # must not raise

    @pytest.mark.parametrize("view", ["settings", "corrections", "secure"])
    def test_no_panel_needs_a_window_any_more(self, gui, controller, view):
        """Every panel used to be a Toplevel that had to be forced over the fullscreen
        parent. In the centre area there is nothing left to raise."""
        import customtkinter

        controller.config.kiosk = True
        customtkinter.CTkToplevel.reset_mock()
        gui._show_view(view)
        assert gui._view == view
        assert not customtkinter.CTkToplevel.called


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

        gui._move_context = MoveContext.UP
        controller.is_moving = False
        controller.at_top = False
        gui._poll_movement()
        assert gui._view != gui_module.VIEW_SECURE

    def test_rope_prompt_when_the_top_is_actually_reached(self, gui, controller):
        gui._move_context = MoveContext.UP
        controller.is_moving = False
        controller.at_top = True
        gui._poll_movement()
        assert gui._view == gui_module.VIEW_SECURE


class TestIconTable:
    """The 28 row table is far taller than the centre area, so it scrolls."""

    def test_uses_a_scrollable_frame(self, gui):
        import customtkinter

        customtkinter.CTkScrollableFrame.reset_mock()
        gui._show_weather_icons()
        assert customtkinter.CTkScrollableFrame.called

    def test_it_takes_the_space_it_is_given(self, gui):
        """No fixed height any more: the frame fills the centre area, whatever that is
        on the Pi, and scrolls the rest."""
        import customtkinter

        customtkinter.CTkScrollableFrame.reset_mock()
        gui._show_weather_icons()
        kwargs = customtkinter.CTkScrollableFrame.call_args.kwargs
        assert "height" not in kwargs and "width" not in kwargs

    def test_it_lists_every_code(self, gui):
        import customtkinter

        from bedliftcontrol.weather import WEATHER_CODES

        customtkinter.CTkLabel.reset_mock()
        gui._show_weather_icons()
        texts = [c.kwargs.get("text") for c in customtkinter.CTkLabel.call_args_list]
        assert all(str(code) in texts for code in WEATHER_CODES)

    def test_the_settings_offer_it(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._show_view(gui_module.VIEW_SETTINGS)
        texts = [c.kwargs.get("text") for c in customtkinter.CTkButton.call_args_list]
        assert "Wetter-Icons" in texts


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

    def test_lowering_from_the_top_asks_nothing(self, gui, controller, elapsed):
        """No prompt of any kind - the rope reminder rides on the countdown instead."""
        controller.at_top = True
        gui._on_down()
        assert gui._view == gui_module.VIEW_WEATHER, "no panel, no dialog"
        elapsed[0] += 30
        gui._wait_before_move()
        controller.run_async.assert_called_once_with(controller.move_down)

    def test_raising_from_the_bottom_asks_nothing(self, gui, controller):
        controller.at_bottom = True
        gui._on_up()
        assert gui._view == gui_module.VIEW_WEATHER, "no panel, no dialog"
        controller.run_async.assert_called_once_with(controller.move_up)

    def test_carrying_on_after_a_stop_asks_nothing(self, gui, controller):
        controller.at_top = False
        controller.at_bottom = False
        gui._on_down()
        assert gui._view == gui_module.VIEW_WEATHER, "no panel, no dialog"


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
    """What the bed says when it arrives at an end stop. It is a panel in the centre
    area like every other one, not a window of its own."""

    @staticmethod
    def arrive(gui, controller, context, at_top=False, at_bottom=False):
        controller.is_moving = False
        controller.at_top = at_top
        controller.at_bottom = at_bottom
        gui._move_context = context
        gui._poll_movement()

    def test_arriving_at_the_bottom_says_nothing(self, gui, controller):
        """Mains switches itself off down there, so there is nothing left to instruct."""
        self.arrive(gui, controller, MoveContext.DOWN, at_bottom=True)
        assert gui._view == gui_module.VIEW_WEATHER

    def test_arriving_at_the_top_asks_for_the_ropes(self, gui, controller):
        self.arrive(gui, controller, MoveContext.UP, at_top=True)
        assert gui._view == gui_module.VIEW_SECURE

    def test_it_says_what_to_do(self, gui, controller):
        import customtkinter

        customtkinter.CTkLabel.reset_mock()
        self.arrive(gui, controller, MoveContext.UP, at_top=True)
        texts = [c.kwargs.get("text") for c in customtkinter.CTkLabel.call_args_list]
        assert "Sicherungsseile anbringen!" in texts

    def test_it_is_no_system_dialog(self, gui, controller):
        """A messagebox is the one window that ignores the CustomTkinter theme."""
        import inspect

        self.arrive(gui, controller, MoveContext.UP, at_top=True)
        assert "messagebox" not in inspect.getsource(gui_module)

    def test_the_back_button_leads_to_the_weather(self, gui, controller):
        self.arrive(gui, controller, MoveContext.UP, at_top=True)
        gui._go_back()
        assert gui._view == gui_module.VIEW_WEATHER

    def test_it_replaces_whatever_panel_was_up(self, gui, controller):
        """The prompt matters more than the settings somebody left open."""
        gui._show_view(gui_module.VIEW_SETTINGS)
        self.arrive(gui, controller, MoveContext.UP, at_top=True)
        assert gui._view == gui_module.VIEW_SECURE

    def test_no_prompt_after_a_stop_in_between(self, gui, controller):
        self.arrive(gui, controller, MoveContext.UP)
        assert gui._view == gui_module.VIEW_WEATHER

    def test_a_new_movement_leaves_the_prompt(self, gui, controller):
        self.arrive(gui, controller, MoveContext.UP, at_top=True)
        gui._on_down()
        assert gui._view == gui_module.VIEW_WEATHER


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

    def test_the_correction_panel_is_left_when_a_move_starts(self, gui, controller):
        gui._show_view(gui_module.VIEW_CORRECTIONS)
        gui._on_up()
        assert gui._view == gui_module.VIEW_WEATHER

    def test_a_move_from_the_weather_stays_there(self, gui):
        gui._on_up()  # must not raise
        assert gui._view == gui_module.VIEW_WEATHER


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

    def test_leaving_the_panel_ends_a_running_hold(self, gui, controller):
        """No release event is coming once the buttons are destroyed."""
        gui._show_view(gui_module.VIEW_CORRECTIONS)
        gui._correction_pressed(controller.hold_front_up)
        gui.app.after.call_args.args[1]()
        gui._go_back()
        controller.stop.assert_called_once()
        assert gui._correction_holding is False

    def test_leaving_the_panel_cancels_a_pending_threshold(self, gui, controller):
        gui._show_view(gui_module.VIEW_CORRECTIONS)
        gui._correction_pressed(controller.hold_front_up)
        gui._go_back()
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
        gui._show_view(gui_module.VIEW_SETTINGS)
        values = customtkinter.CTkOptionMenu.call_args.kwargs["values"]
        assert values == [place.label for place in LOCATIONS]

    def test_the_dropdown_starts_on_the_selected_one(self, gui, weather):
        weather.selected = "lacure"
        gui._show_view(gui_module.VIEW_SETTINGS)
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


class TestHistoryPanel:
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
        gui._show_view(gui_module.VIEW_SETTINGS)
        texts = [c.kwargs.get("text") for c in customtkinter.CTkButton.call_args_list]
        assert "Historie" in texts

    def test_it_opens_in_the_centre_area(self, gui):
        gui._show_history()
        assert gui._view == gui_module.VIEW_HISTORY

    def test_shows_the_night_count(self, gui_with_history):
        import customtkinter

        built, _ = gui_with_history
        customtkinter.CTkLabel.reset_mock()
        built._show_history()
        texts = [c.kwargs.get("text") for c in customtkinter.CTkLabel.call_args_list]
        assert "\u00dcbernachtungen: 7" in texts

    def test_lists_the_newest_location_first(self, gui_with_history):
        import customtkinter

        built, _ = gui_with_history
        customtkinter.CTkLabel.reset_mock()
        built._show_history()
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
        gui._show_history()
        texts = [c.kwargs.get("text") for c in customtkinter.CTkLabel.call_args_list]
        assert "Noch keine Standorte aufgezeichnet" in texts

    def test_works_without_a_tracker(self, gui):
        gui.history = None
        gui._show_history()  # must not raise
        assert gui._view == gui_module.VIEW_HISTORY

    def test_the_timestamp_is_formatted(self, gui):
        from bedliftcontrol.history import LocationVisit

        visit = LocationVisit("2026-09-14T17:04:12", "Thun", 46.7210, 7.5644)
        assert gui._format_visit(visit).startswith("14.09.2026 17:04   Thun   (46.7210, 7.5644)")

    def test_an_unparsable_timestamp_is_shown_raw(self, gui):
        from bedliftcontrol.history import LocationVisit

        visit = LocationVisit("kaputt", "Thun", 46.7210, 7.5644)
        assert gui._format_visit(visit).startswith("kaputt")

    def test_the_list_scrolls(self, gui):
        """500 stops do not fit any panel, so the list takes what it gets and scrolls."""
        import customtkinter

        customtkinter.CTkScrollableFrame.reset_mock()
        gui._show_history()
        assert customtkinter.CTkScrollableFrame.called
        assert "height" not in customtkinter.CTkScrollableFrame.call_args.kwargs


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
    """The start-up delay used to be a slider. It is fixed now, so the settings must
    not offer it any more - and the inverter must still wait."""

    @pytest.fixture
    def settings(self, controller, weather):
        import customtkinter

        inverter = FakeInverter()
        built = BedGui(controller, weather, inverter=inverter)
        customtkinter.CTkSlider.reset_mock()
        customtkinter.CTkLabel.reset_mock()
        customtkinter.CTkButton.reset_mock()
        built._show_view(gui_module.VIEW_SETTINGS)
        return built, inverter

    @staticmethod
    def texts(widget):
        import customtkinter

        return [c.kwargs.get("text") for c in getattr(customtkinter, widget).call_args_list]

    def test_no_row_for_the_start_up_delay(self, settings):
        assert not any("230V" in (text or "") for text in self.texts("CTkLabel"))

    def test_no_switch_for_the_automatic(self, settings):
        """It was removed: without it a movement has no power, which is not an option
        worth offering."""
        assert not any("Automatik" in (text or "") for text in self.texts("CTkButton"))

    def test_the_delay_is_five_seconds(self):
        from bedliftcontrol.inverter import STARTUP_SECONDS

        assert STARTUP_SECONDS == 5.0

    def test_the_config_no_longer_carries_it(self):
        from bedliftcontrol.config import Config

        assert not hasattr(Config(), "inverter_startup_seconds")


class TestSettingsLabels:
    """Everything the panel says is German."""

    @pytest.fixture
    def opened(self, controller, weather):
        import customtkinter

        built = BedGui(controller, weather, updater=FakeUpdater())
        customtkinter.CTkLabel.reset_mock()
        customtkinter.CTkButton.reset_mock()
        customtkinter.CTkSlider.reset_mock()
        built._show_view(gui_module.VIEW_SETTINGS)
        return built

    @staticmethod
    def texts(widget):
        import customtkinter

        return [c.kwargs.get("text") for c in getattr(customtkinter, widget).call_args_list]

    @pytest.mark.parametrize("label", ["Anzahl Schritte", "Geschwindigkeit PPS",
                                       "Seile lösen", "Ort"])
    def test_the_rows_are_named_in_german(self, opened, label):
        assert label in self.texts("CTkLabel")

    @pytest.mark.parametrize("gone", ["total steps", "speed pps"])
    def test_the_english_names_are_gone(self, opened, gone):
        assert gone not in self.texts("CTkLabel")

    def test_the_update_button_is_german(self, opened):
        assert "Updates installieren" in self.texts("CTkButton")
        assert gui_module.UPDATE_BUTTON_TEXT == "Updates installieren"


class TestVersionRow:
    """Version and update button share the width of the button row above them, so all
    three bottom rows line up on both edges."""

    @pytest.fixture
    def opened(self, controller, weather):
        import customtkinter

        built = BedGui(controller, weather, updater=FakeUpdater())
        customtkinter.CTkFrame.reset_mock()
        built._show_view(gui_module.VIEW_SETTINGS)
        return built

    @staticmethod
    def version_frame():
        import customtkinter

        rows = [c.kwargs for c in customtkinter.CTkFrame.call_args_list
                if c.kwargs.get("width") == gui_module.SETTINGS_ROW_WIDTH]
        assert rows, "no row the width of the button block"
        return rows[0]

    def test_it_is_as_wide_as_the_button_row(self, opened):
        assert self.version_frame()["width"] == gui_module.SETTINGS_ROW_WIDTH

    def test_it_keeps_that_width(self, controller, weather):
        """Without this the frame shrinks around its two children and drifts inwards.
        It has to be pack, not grid: the two children are packed."""
        import customtkinter

        made = []

        def record(*args, **kwargs):
            widget = _widget_mock()
            made.append((kwargs, widget))
            return widget

        customtkinter.CTkFrame.side_effect = record
        built = BedGui(controller, weather, updater=FakeUpdater())
        built._show_view(gui_module.VIEW_SETTINGS)
        rows = [widget for kwargs, widget in made
                if kwargs.get("width") == gui_module.SETTINGS_ROW_WIDTH]
        assert len(rows) == 1
        rows[0].pack_propagate.assert_called_once_with(False)
        assert not rows[0].grid_propagate.called

    def test_the_height_is_fixed_too(self, opened):
        """pack_propagate(False) freezes both, so the height has to be given."""
        assert self.version_frame()["height"] == gui_module.VERSION_ROW_HEIGHT

    def test_the_button_row_above_has_the_same_width(self, opened):
        """Both rows are built from the same constant, so they cannot drift apart."""
        assert (gui_module.KIOSK_BUTTON_WIDTH + 2 * gui_module.SETTINGS_BUTTON_WIDTH + 32
                == gui_module.SETTINGS_ROW_WIDTH)

    def test_it_fits_the_pi_panel(self, controller, weather):
        """The panel sits between the progress bar and the arrow buttons."""
        from bedliftcontrol.gui import SETTINGS_ROW_WIDTH

        assert SETTINGS_ROW_WIDTH + 60 + 200 <= 800


class TestSpeedSlider:
    @pytest.fixture
    def opened(self, controller, weather):
        import customtkinter

        built = BedGui(controller, weather)
        customtkinter.CTkSlider.reset_mock()
        built._show_view(gui_module.VIEW_SETTINGS)
        return built

    def test_it_spans_four_hundred_to_a_thousand(self, opened):
        import customtkinter

        bounds = [(c.kwargs.get("from_"), c.kwargs.get("to"))
                  for c in customtkinter.CTkSlider.call_args_list]
        assert (400, 1000) in bounds

    def test_the_default_is_seven_hundred(self):
        from bedliftcontrol.config import DEFAULT_SPEED_PPS, Config

        assert DEFAULT_SPEED_PPS == 700.0
        assert Config().speed_pps == 700.0

    def test_the_default_sits_inside_the_range(self):
        """A slider cannot show a value it has no position for."""
        from bedliftcontrol.config import DEFAULT_SPEED_PPS

        assert gui_module.SPEED_MIN <= DEFAULT_SPEED_PPS <= gui_module.SPEED_MAX


class TestPowerAfterMoving:
    """Mains is switched off again once the bed is parked at an end stop."""

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

    def test_arriving_at_the_top_switches_it_off(self, running, controller):
        built, inverter = running
        self.arrive(built, controller, MoveContext.UP, at_top=True)
        built._go_back()
        assert inverter.on is False

    def test_arriving_at_the_bottom_switches_it_off(self, running, controller):
        built, inverter = running
        self.arrive(built, controller, MoveContext.DOWN, at_bottom=True)
        assert inverter.on is False

    def test_the_rope_prompt_comes_while_mains_is_still_on(self, running, controller):
        """The motors hold the bed until the ropes are on; only the OK cuts the power."""
        built, inverter = running
        self.arrive(built, controller, MoveContext.UP, at_top=True)
        assert inverter.on is True, "the ropes go on while the motors still hold it"
        built._go_back()
        assert inverter.on is False

    def test_a_movement_started_from_the_prompt_keeps_mains(self, running, controller):
        """Closing the window must not cut the power out from under a new movement."""
        built, inverter = running
        self.arrive(built, controller, MoveContext.UP, at_top=True)
        controller.is_moving = True
        built._go_back()
        assert inverter.on is True

    def test_the_button_follows(self, running, controller):
        built, inverter = running
        self.arrive(built, controller, MoveContext.UP, at_top=True)
        built._go_back()
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_OFF_COLOR

    def test_a_stop_in_between_leaves_it_running(self, running, controller):
        built, inverter = running
        self.arrive(built, controller, MoveContext.DOWN)
        assert inverter.on is True

    def test_the_whole_round_trip(self, controller, weather, elapsed):
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
        built._go_back()
        assert inverter.on is False
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_OFF_COLOR

    def test_an_inverter_that_is_already_off_is_left_alone(self, controller, weather):
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
        built._show_view(gui_module.VIEW_SETTINGS)
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

    def test_it_comes_on_top_of_the_fixed_start_up(self, settings, controller):
        """The inverter start-up is no longer a setting; this delay is the only one left."""
        from bedliftcontrol.inverter import STARTUP_SECONDS

        settings._on_rope_delay_change(3.0)
        assert controller.config.rope_delay_seconds == 3.0
        assert STARTUP_SECONDS == 5.0


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


class TestCountdownRedraws:
    """Every write to the STOP button redraws a large red surface, so the countdown
    must make as few of them as it can - and the same number either way the bed goes."""

    @pytest.fixture
    def counting(self, gui):
        gui.stop_button.configure.reset_mock()
        return gui

    def test_the_same_second_is_not_rewritten(self, counting):
        """The countdown ticks four times a second but only changes once."""
        counting._set_stop_button_text("230V 5s", counting._countdown_font)
        counting._set_stop_button_text("230V 5s", counting._countdown_font)
        assert counting.stop_button.configure.call_count == 1

    def test_the_font_is_sent_once_per_phase(self, counting):
        """Handing CustomTkinter the same font object again still rebinds it and
        re-measures the whole button."""
        for second in (5, 4, 3):
            counting._set_stop_button_text(f"230V {second}s", counting._countdown_font)
        with_font = [c for c in counting.stop_button.configure.call_args_list
                     if "font" in c.kwargs]
        assert len(with_font) == 1

    def test_a_real_font_change_still_gets_through(self, counting):
        counting._set_stop_button_text("230V 1s", counting._countdown_font)
        counting.stop_button.configure.reset_mock()
        counting._set_stop_button_text("STOP", counting._stop_font)
        assert counting.stop_button.configure.call_args.kwargs["font"] is counting._stop_font

    @pytest.mark.parametrize("context, at_top, at_bottom", [
        (MoveContext.UP, False, True),
        (MoveContext.DOWN, True, False),
    ])
    def test_both_directions_write_the_same_amount(self, gui, controller,
                                                   context, at_top, at_bottom):
        """Whatever the flicker is, it must not depend on which way the bed goes."""
        controller.at_top = at_top
        controller.at_bottom = at_bottom
        gui._move_context = context
        gui.stop_button.configure.reset_mock()
        for second in (3, 3, 2, 2, 1, 1):
            gui._set_stop_button_text(gui._countdown_text(second), gui._countdown_font)
        assert gui.stop_button.configure.call_count == 3


class TestLogPanel:
    """The log is the only thing that says why an update failed, so it has to be
    readable on the machine itself."""

    @staticmethod
    def capture_box(monkeypatch, text):
        """The widget mocks hand out a fresh object per call, so the box has to be
        caught on the way out."""
        import customtkinter

        made = []

        def build(*args, **kwargs):
            made.append(_widget_mock())
            return made[-1]

        monkeypatch.setattr(gui_module.logsetup, "read_tail", lambda *a, **k: text)
        customtkinter.CTkTextbox.side_effect = build
        return made

    @pytest.fixture
    def opened(self, gui, monkeypatch):
        boxes = self.capture_box(monkeypatch, "erste Zeile\nletzte Zeile")
        gui._show_log()
        assert boxes, "no textbox was built"
        return gui, boxes[0]

    def test_the_settings_offer_it(self, gui):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        gui._show_view(gui_module.VIEW_SETTINGS)
        texts = [c.kwargs.get("text") for c in customtkinter.CTkButton.call_args_list]
        assert "Log" in texts

    def test_it_opens_in_the_centre_area(self, opened):
        gui, _ = opened
        assert gui._view == gui_module.VIEW_LOG

    def test_it_shows_the_file(self, opened):
        _, box = opened
        written = [c.args[1] for c in box.insert.call_args_list if len(c.args) > 1]
        assert any("letzte Zeile" in text for text in written)

    def test_it_scrolls(self, opened):
        """Four hundred lines do not fit any panel."""
        import customtkinter

        assert customtkinter.CTkTextbox.call_args.kwargs.get("activate_scrollbars") is True

    def test_it_opens_at_the_end(self, opened):
        """The newest line is the one being looked for."""
        _, box = opened
        box.see.assert_called_with("end")

    def test_it_opens_at_the_left_edge(self, opened):
        """see() moves both axes; without this the panel opens past the timestamps."""
        _, box = opened
        box.xview_moveto.assert_called_with(0)

    def test_it_cannot_be_typed_into(self, opened):
        _, box = opened
        states = [c.kwargs.get("state") for c in box.configure.call_args_list]
        assert "disabled" in states

    def test_an_empty_log_says_so(self, gui, monkeypatch):
        boxes = self.capture_box(monkeypatch, "")
        gui._show_log()
        written = [c.args[1] for c in boxes[0].insert.call_args_list if len(c.args) > 1]
        assert any("leer" in text for text in written)

    def test_the_back_button_leads_to_the_settings(self, opened):
        gui, _ = opened
        gui._go_back()
        assert gui._view == gui_module.VIEW_SETTINGS


class TestTodaysWarningIsReachable:
    """The marker on the big icon was drawn but could not be pressed - the binding
    only ever went on the forecast columns."""

    @pytest.fixture
    def built(self, controller, weather, monkeypatch):
        """IconCanvas is a real Tk widget, so it has to be replaced to see the binding."""
        monkeypatch.setattr(gui_module.icons, "IconCanvas",
                            lambda master, size, background: MagicMock())
        return BedGui(controller, weather)

    @staticmethod
    def handler(built):
        bindings = [c for c in built.weather_icon.bind.call_args_list
                    if c.args and c.args[0] == "<Button-1>"]
        assert bindings, "the big icon is not bound"
        return bindings[0].args[1]

    def test_the_big_icon_is_bound(self, built):
        assert self.handler(built)

    def test_pressing_it_opens_todays_warning(self, built, weather, monkeypatch):
        from bedliftcontrol.alerts import WeatherWarning

        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: FIXED_TODAY)
        weather.warning_on.return_value = WeatherWarning(
            "Sturm", "Severe", "Bern", f"{FIXED_TODAY}T12:00:00+00:00",
            f"{FIXED_TODAY}T20:00:00+00:00")
        self.handler(built)(None)
        assert built._view == gui_module.VIEW_WARNING

    def test_a_quiet_day_opens_nothing(self, built, weather, monkeypatch):
        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: FIXED_TODAY)
        weather.warning_on.return_value = None
        self.handler(built)(None)
        assert built._view == gui_module.VIEW_WEATHER

    def test_the_day_is_read_when_it_is_pressed(self, built, monkeypatch):
        """The icon outlives every midnight, so the date must not be baked in."""
        asked = []
        monkeypatch.setattr(gui_module.BedGui, "_show_warning",
                            lambda self, day: asked.append(day))
        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: "2026-12-24")
        self.handler(built)(None)
        assert asked == ["2026-12-24"]

    def test_the_marker_survives_a_stale_reading(self, built, weather):
        """Offline is when a warning matters most - it must not vanish with the
        fallback to today's forecast."""
        from bedliftcontrol.alerts import WeatherWarning
        from bedliftcontrol.weather import DailyForecast

        warning = WeatherWarning("Sturm", "Severe", "Bern",
                                 f"{FIXED_TODAY}T12:00:00+00:00",
                                 f"{FIXED_TODAY}T20:00:00+00:00")
        weather.warning_on.side_effect = lambda key, day: warning if day == FIXED_TODAY else None
        day = DailyForecast("Do", FIXED_TODAY, "sun", 20.0, 9.0, 10, "Klar")
        built._update_current_panel_from_forecast("Thun", day)
        built.weather_icon.show.assert_called_with("sun", warning.color)


class TestBackButton:
    """The panels replaced their windows, so the way out is a button in the centre
    area instead of a close button at the bottom of a window."""

    @staticmethod
    def back_button_calls():
        import customtkinter

        return [c for c in customtkinter.CTkButton.call_args_list
                if c.kwargs.get("text") == gui_module.BACK_BUTTON_TEXT]

    def test_it_exists(self, gui):
        assert self.back_button_calls()

    def test_it_is_big_enough_for_a_finger(self, gui):
        assert self.back_button_calls()[0].kwargs["height"] == gui_module.BACK_BUTTON_HEIGHT

    def test_it_sits_on_the_right(self, gui):
        gui.back_button.pack.assert_called_with(side="right")

    def test_the_weather_view_has_no_header(self, gui):
        """Nothing may move in the view the user looks at all day."""
        gui.view_header.pack.reset_mock()
        gui._show_view(gui_module.VIEW_WEATHER)
        assert not gui.view_header.pack.called

    def test_a_panel_shows_the_header(self, gui):
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui.view_header.pack.assert_called()

    def test_going_back_hides_it_again(self, gui):
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui.view_header.pack_forget.reset_mock()
        gui._go_back()
        gui.view_header.pack_forget.assert_called()

    @pytest.mark.parametrize("view, target", [
        ("settings", "weather"),
        ("corrections", "weather"),
        ("history", "settings"),
        ("icons", "settings"),
    ])
    def test_where_it_leads(self, gui, view, target):
        gui._show_view(view)
        gui._go_back()
        assert gui._view == target

    def test_the_settings_are_reachable_again_from_the_history(self, gui):
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui._show_history()
        gui._go_back()
        assert gui._kiosk_button is not None, "the settings were rebuilt, not just shown"


class TestTheWeatherSurvivesAPanel:
    """The weather is unpacked, never destroyed: the refresh keeps writing into it."""

    def test_it_is_hidden_while_a_panel_is_up(self, gui):
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui.weather_view.pack_forget.assert_called()

    def test_it_comes_back(self, gui):
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui.weather_view.pack.reset_mock()
        gui._go_back()
        gui.weather_view.pack.assert_called()

    def test_a_refresh_behind_a_panel_does_not_raise(self, gui, weather):
        from bedliftcontrol.weather import Weather

        gui._show_view(gui_module.VIEW_SETTINGS)
        weather.current = Weather("Thun", 21.0, "Klar", "sun", f"{FIXED_TODAY}T08:00")
        gui._apply_weather()
        gui.weather_city.configure.assert_any_call(text="Thun")

    def test_the_panel_is_emptied_on_the_way_out(self, gui):
        """Left standing, the old panel's widgets would pile up under the new one."""
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui.panel_view.winfo_children.return_value = [MagicMock(), MagicMock()]
        children = gui.panel_view.winfo_children.return_value
        gui._go_back()
        assert all(child.destroy.called for child in children)


class TestNoWindowsLeft:
    """Nothing opens a Toplevel any more - every panel lives in the centre area."""

    @pytest.mark.parametrize("view", ["settings", "corrections", "history", "icons",
                                      "secure"])
    def test_no_panel_opens_a_window(self, gui, view):
        import customtkinter

        customtkinter.CTkToplevel.reset_mock()
        gui._show_view(view)
        assert not customtkinter.CTkToplevel.called

    def test_the_warning_opens_no_window_either(self, gui, weather):
        import customtkinter

        from bedliftcontrol.alerts import WeatherWarning

        weather.warning_on.return_value = WeatherWarning(
            "Sturm", "Severe", "Bern", "2026-09-30T12:00:00+00:00",
            "2026-09-30T20:00:00+00:00")
        customtkinter.CTkToplevel.reset_mock()
        gui._show_warning("2026-09-30")
        assert gui._view == gui_module.VIEW_WARNING
        assert not customtkinter.CTkToplevel.called

    def test_the_source_has_no_toplevel_left(self):
        """A regression guard: this is the whole point of the rework."""
        import inspect

        assert "CTkToplevel" not in inspect.getsource(gui_module)


class TestMidnightRollover:
    """The panel has to survive a day change without a connection: the forecast rolls
    over, and the big block falls back to today's forecast once the reading is stale."""

    @staticmethod
    def week(start_day=3):
        from bedliftcontrol.weather import DailyForecast

        names = ["Do", "Fr", "Sa", "So", "Mo", "Di", "Mi"]
        return [
            DailyForecast(names[index], f"2026-09-{start_day + index:02d}", "sun",
                          20.0 + index, 9.0 + index, rain=10, description="Klarer Himmel")
            for index in range(7)
        ]

    @staticmethod
    def reading(fetched_at, daily):
        from bedliftcontrol.weather import Weather

        return Weather("Thun", 21.4, "Klar", "sun", fetched_at, daily=daily)

    def columns(self, gui):
        return [c.kwargs.get("text") for c in gui._forecast_labels
                if hasattr(c, "kwargs")] or None

    def test_today_is_the_first_column(self, gui, weather, monkeypatch):
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        rendered = gui._rendered_forecast_key
        assert rendered[0][0] == "2026-09-03"
        assert len(rendered) == 7

    def test_a_day_later_the_first_column_is_dropped(self, gui, weather, monkeypatch):
        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: "2026-09-04")
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        rendered = gui._rendered_forecast_key
        assert rendered[0][0] == "2026-09-04"
        assert len(rendered) == 6, "no new data offline, so the week grows shorter"

    def test_a_week_later_nothing_is_left(self, gui, weather, monkeypatch):
        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: "2026-09-20")
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        assert gui._rendered_forecast_key == []

    def test_a_reading_from_today_is_shown_as_it_is(self, gui, weather):
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        gui.weather_temp.configure.assert_any_call(text="21°C")

    def test_a_reading_from_yesterday_gives_way_to_the_forecast(self, gui, weather, monkeypatch):
        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: "2026-09-04")
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        gui.weather_temp.configure.assert_any_call(text="21° / 10°")
        gui.weather_day.configure.assert_any_call(text="Fr")
        gui.weather_desc.configure.assert_any_call(text="Klarer Himmel")

    def test_the_stale_panel_says_it_is_a_forecast(self, gui, weather, monkeypatch):
        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: "2026-09-04")
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        stamp = gui.weather_updated.configure.call_args.kwargs["text"]
        assert stamp.startswith("Vorhersage")

    def test_a_fresh_reading_is_not_labelled_a_forecast(self, gui, weather):
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        stamp = gui.weather_updated.configure.call_args.kwargs["text"]
        assert stamp.startswith("Stand:")

    def test_without_a_forecast_for_today_the_old_reading_stays(self, gui, weather, monkeypatch):
        """Better the last thing actually measured than an empty panel."""
        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: "2026-09-20")
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        gui.weather_temp.configure.assert_any_call(text="21°C")

    def test_the_rollover_needs_no_connection(self, gui, weather, monkeypatch):
        """Nothing in the path asks the service for anything."""
        monkeypatch.setattr(gui_module.BedGui, "_today", lambda self: "2026-09-05")
        weather.current = self.reading("2026-09-03T08:00", self.week())
        gui._apply_weather()
        assert not weather.refresh_once.called
        assert not weather.select.called


class FakeUpdater:
    def __init__(self, outcome=None, version="e28a2d1 · 29.09.2026 21:52"):
        from bedliftcontrol import update

        self.outcome = outcome if outcome is not None else update.UPDATED
        self._version = version
        self.installs = 0

    def install(self):
        self.installs += 1
        return self.outcome

    def version(self):
        return self._version


class TestInstallUpdates:
    """The button lives in the settings and does the looking itself."""

    @pytest.fixture
    def settings(self, controller, weather, monkeypatch):
        monkeypatch.setattr(gui_module.os, "execv", MagicMock())
        updater = FakeUpdater()
        built = BedGui(controller, weather, updater=updater)
        built._show_view(gui_module.VIEW_SETTINGS)
        return built, updater

    def test_the_menu_bar_has_no_update_button(self, controller, weather):
        """It used to sit in the bar and wait for a background check."""
        built = BedGui(controller, weather, updater=FakeUpdater())
        assert not hasattr(built, "update_button")

    def test_nothing_is_checked_in_the_background(self, controller, weather):
        updater = FakeUpdater()
        BedGui(controller, weather, updater=updater)
        assert updater.installs == 0

    def test_the_settings_offer_the_button(self, settings):
        import customtkinter

        labels = [c.kwargs.get("text") for c in customtkinter.CTkButton.call_args_list]
        assert gui_module.UPDATE_BUTTON_TEXT in labels

    def test_the_settings_show_the_version(self, settings):
        import customtkinter

        texts = [c.kwargs.get("text", "") for c in customtkinter.CTkLabel.call_args_list]
        assert any("e28a2d1 · 29.09.2026 21:52" in text for text in texts)

    def test_pressing_it_installs(self, settings):
        built, updater = settings
        built._run_update()
        assert updater.installs == 1

    def test_a_successful_update_restarts_the_app(self, settings, monkeypatch):
        from bedliftcontrol import update

        built, _ = settings
        restarted = []
        monkeypatch.setattr(built, "_restart", lambda: restarted.append(True))
        built._update_finished(update.UPDATED)
        assert restarted == [True]

    def test_being_up_to_date_says_so_on_the_button(self, settings, monkeypatch):
        from bedliftcontrol import update

        built, _ = settings
        monkeypatch.setattr(built, "_restart", MagicMock())
        built._on_update()
        built._update_finished(update.UP_TO_DATE)
        written = built._update_button.configure.call_args.kwargs
        assert written["text"] == gui_module.UPDATE_UP_TO_DATE_TEXT
        assert not built._restart.called

    def test_a_failure_says_so_on_the_button(self, settings):
        from bedliftcontrol import update

        built, _ = settings
        built._on_update()
        built._update_finished(update.FAILED)
        assert built._update_button.configure.call_args.kwargs["text"] == gui_module.UPDATE_FAILED_TEXT

    @pytest.mark.parametrize("outcome", ["up_to_date", "failed"])
    def test_the_button_is_dead_afterwards(self, settings, monkeypatch, outcome):
        """Nothing more to get, or something pressing again will not mend."""
        built, _ = settings
        monkeypatch.setattr(built, "_restart", MagicMock())
        built._on_update()
        built._update_finished(outcome)
        assert built._update_button.configure.call_args.kwargs["state"] == "disabled"

    def test_reopening_the_settings_gives_a_fresh_button(self, settings, monkeypatch):
        """That is the way to try again - the panel is rebuilt from scratch."""
        import customtkinter

        built, _ = settings
        built._on_update()
        built._update_finished("failed")
        built._go_back()
        customtkinter.CTkButton.reset_mock()
        built._show_view(gui_module.VIEW_SETTINGS)
        fresh = [c.kwargs for c in customtkinter.CTkButton.call_args_list
                 if c.kwargs.get("text") == gui_module.UPDATE_BUTTON_TEXT]
        assert len(fresh) == 1
        assert "state" not in fresh[0]

    def test_no_system_dialog_is_opened(self, settings, monkeypatch):
        """A messagebox is the one window that ignores the CustomTkinter theme."""
        import inspect

        from bedliftcontrol import update

        built, _ = settings
        monkeypatch.setattr(built, "_restart", MagicMock())
        built._on_update()
        built._update_finished(update.FAILED)
        assert "messagebox" not in inspect.getsource(gui_module)

    def test_the_button_says_it_is_working(self, settings, monkeypatch):
        monkeypatch.setattr(gui_module.threading, "Thread", MagicMock())
        built, _ = settings
        built._on_update()
        assert built._update_button.configure.call_args.kwargs["state"] == "disabled"

    def test_it_will_not_pull_out_from_under_a_moving_bed(self, settings, controller):
        built, updater = settings
        controller.is_moving = True
        built._on_update()
        assert updater.installs == 0

    def test_a_second_press_while_running_is_ignored(self, settings, monkeypatch):
        built, _ = settings
        monkeypatch.setattr(gui_module.threading, "Thread", MagicMock())
        built._on_update()
        built._on_update()
        assert gui_module.threading.Thread.call_count == 1

    def test_leaving_the_settings_mid_update_breaks_nothing(self, settings, monkeypatch):
        """The panel is gone by then; the pull outlives it."""
        from bedliftcontrol import update

        built, _ = settings
        monkeypatch.setattr(gui_module.threading, "Thread", MagicMock())
        built._on_update()
        built._go_back()
        built._update_finished(update.FAILED)  # must not raise


class TestRestart:
    @pytest.fixture
    def restarting(self, controller, weather, monkeypatch):
        execv = MagicMock()
        monkeypatch.setattr(gui_module.os, "execv", execv)
        built = BedGui(controller, weather, inverter=FakeInverter(on=True, ready=True),
                       updater=FakeUpdater())
        return built, execv

    def test_the_live_config_is_written_first(self, restarting, controller):
        """The pull reset the checked-in file; the bed position must not go with it."""
        built, _ = restarting
        built._restart()
        controller.config.save.assert_called()

    def test_mains_is_switched_off(self, restarting):
        built, _ = restarting
        built._restart()
        assert built.inverter.on is False

    def test_the_pins_are_released(self, restarting, controller):
        built, _ = restarting
        built._restart()
        controller.cleanup.assert_called_once()

    def test_it_starts_the_same_entry_point_again(self, restarting):
        built, execv = restarting
        built._restart()
        arguments = execv.call_args.args[1]
        assert arguments[1:] == ["-m", "bedliftcontrol.main"]


class TestCorrectionsPower:
    """The correction buttons drive motors, so mains follows the panel."""

    @pytest.fixture
    def gui_with_power(self, controller, weather):
        controller.at_bottom = True
        controller.at_top = False
        inverter = FakeInverter()
        return BedGui(controller, weather, inverter=inverter), inverter

    def test_opening_switches_it_on(self, gui_with_power):
        built, inverter = gui_with_power
        built._show_view(gui_module.VIEW_CORRECTIONS)
        assert inverter.on is True

    def test_the_button_shows_it(self, gui_with_power):
        built, _ = gui_with_power
        built._show_view(gui_module.VIEW_CORRECTIONS)
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_ON_COLOR

    def test_closing_switches_it_off(self, gui_with_power):
        built, inverter = gui_with_power
        built._show_view(gui_module.VIEW_CORRECTIONS)
        built._go_back()
        assert inverter.on is False

    def test_closing_updates_the_button(self, gui_with_power):
        built, _ = gui_with_power
        built._show_view(gui_module.VIEW_CORRECTIONS)
        built._go_back()
        assert built.power_button.configure.call_args.kwargs["fg_color"] == gui_module.POWER_OFF_COLOR

    def test_a_starting_movement_does_not_take_mains_down(self, gui_with_power, controller):
        """The window is closed when a movement starts - but that movement needs power."""
        built, inverter = gui_with_power
        built._show_view(gui_module.VIEW_CORRECTIONS)
        built._start_move(MoveContext.UP, controller.move_up)
        assert inverter.on is True

    def test_mains_is_left_alone_while_the_motors_run(self, gui_with_power, controller):
        built, inverter = gui_with_power
        built._show_view(gui_module.VIEW_CORRECTIONS)
        controller.is_moving = True
        built._go_back()
        assert inverter.on is True

    def test_leaving_the_settings_again_changes_nothing(self, gui_with_power):
        """Only the corrections own the mains; the other panels must not touch it."""
        built, inverter = gui_with_power
        built._show_view(gui_module.VIEW_SETTINGS)
        built._go_back()
        assert inverter.on is False


class TestTouchFriendliness:
    """The panel is operated with a finger: no hover states, no flicker."""

    @staticmethod
    def constructions():
        import customtkinter

        return (customtkinter.CTkButton.call_args_list
                + customtkinter.CTkOptionMenu.call_args_list)

    def test_no_widget_reacts_to_hovering(self, gui, controller):
        """A touch screen sends no leave event, so a tapped button would keep its
        hover colour until something else is touched."""
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        customtkinter.CTkOptionMenu.reset_mock()
        controller.at_bottom = True
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui._show_view(gui_module.VIEW_CORRECTIONS)
        gui._show_history()
        gui._show_weather_icons()
        assert self.constructions(), "nothing was built, the test proves nothing"
        for call in self.constructions():
            assert call.kwargs.get("hover") is False, call.kwargs.get("text")

    def test_the_countdown_is_not_rewritten_on_every_tick(self, controller, weather, elapsed):
        """Rewriting the same text four times a second makes the button blink."""
        built = BedGui(controller, weather, inverter=FakeInverter())
        built._start_move(MoveContext.UP, controller.move_up)
        built.stop_button.configure.reset_mock()
        for _ in range(4):
            built._wait_before_move()  # same second, same text
        assert not built.stop_button.configure.called

    def test_a_changed_second_does_reach_the_button(self, controller, weather, elapsed):
        built = BedGui(controller, weather, inverter=FakeInverter())
        built._start_move(MoveContext.UP, controller.move_up)
        built.stop_button.configure.reset_mock()
        elapsed[0] += 2
        built._wait_before_move()
        assert built.stop_button.configure.called

    def test_the_fonts_are_built_once(self, gui, controller, elapsed):
        """A fresh CTkFont per tick is what made it flicker in the first place."""
        import customtkinter

        customtkinter.CTkFont.reset_mock()
        gui._start_move(MoveContext.UP, controller.move_up)
        for _ in range(4):
            elapsed[0] += 1
            gui._wait_before_move()
        assert not customtkinter.CTkFont.called


class TestBarLayout:
    """One block of equal buttons, and a clock that fits between them and the edge."""

    def test_the_bar_is_fifty_five_pixels(self):
        assert gui_module.BAR_BUTTON_HEIGHT + 2 * gui_module.BAR_PAD_Y == 55

    def test_every_button_has_the_same_size(self, controller, weather):
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        BedGui(controller, weather)
        bar_buttons = [c.kwargs for c in customtkinter.CTkButton.call_args_list
                       if c.kwargs.get("height") == gui_module.BAR_BUTTON_HEIGHT]
        assert len(bar_buttons) == 3, "settings, corrections, 230V"
        assert {kwargs["width"] for kwargs in bar_buttons} == {gui_module.BAR_BUTTON_WIDTH}

    def test_the_width_holds_the_longest_label(self, controller, weather):
        """230V is the longest word left in the bar; nothing may be narrower than it."""
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        BedGui(controller, weather)
        widths = {c.kwargs.get("text"): c.kwargs.get("width")
                  for c in customtkinter.CTkButton.call_args_list}
        assert widths["230V"] == gui_module.BAR_BUTTON_WIDTH

    def test_the_labels_use_the_bigger_bar_font(self, controller, weather):
        import customtkinter

        customtkinter.CTkFont.reset_mock()
        customtkinter.CTkButton.reset_mock()
        BedGui(controller, weather)
        sizes = [c.kwargs.get("size") for c in customtkinter.CTkFont.call_args_list]
        assert gui_module.BAR_FONT_SIZE in sizes
        fonts = [c.kwargs.get("font") for c in customtkinter.CTkButton.call_args_list
                 if c.kwargs.get("height") == gui_module.BAR_BUTTON_HEIGHT]
        assert len(fonts) == 3 and all(font is not None for font in fonts)

    def test_one_font_serves_the_whole_bar(self, controller, weather):
        """Identical CTkFonts would be several objects doing the same job."""
        import customtkinter

        customtkinter.CTkButton.reset_mock()
        BedGui(controller, weather)
        fonts = {id(c.kwargs.get("font")) for c in customtkinter.CTkButton.call_args_list
                 if c.kwargs.get("height") == gui_module.BAR_BUTTON_HEIGHT}
        assert len(fonts) == 1

    def test_the_longest_label_still_fits(self):
        """Measured at size 18: Update renders 58px into a 90px button."""
        assert gui_module.BAR_FONT_SIZE <= 20

    def test_the_clock_stays_inside_the_bar(self):
        """The buttons size the bar; a taller clock would push it open."""
        clock = gui_module.CLOCK_TIME_HEIGHT + gui_module.CLOCK_DATE_HEIGHT
        assert clock <= gui_module.BAR_BUTTON_HEIGHT + 2 * gui_module.BAR_PAD_Y

    def test_each_clock_line_has_room_for_its_font(self):
        assert gui_module.CLOCK_TIME_HEIGHT > gui_module.CLOCK_TIME_SIZE
        assert gui_module.CLOCK_DATE_HEIGHT > gui_module.CLOCK_DATE_SIZE

    def test_the_time_is_the_bigger_line(self):
        assert gui_module.CLOCK_TIME_SIZE > gui_module.CLOCK_DATE_SIZE

    def test_both_clock_lines_are_right_aligned(self, controller, weather):
        import customtkinter

        customtkinter.CTkLabel.reset_mock()
        BedGui(controller, weather)
        anchors = [c.kwargs.get("anchor") for c in customtkinter.CTkLabel.call_args_list
                   if c.kwargs.get("height") in (gui_module.CLOCK_TIME_HEIGHT,
                                                 gui_module.CLOCK_DATE_HEIGHT)]
        assert anchors == ["e", "e"]


class TestWarnings:
    """A warning marks the icon of the day it is in force on, and opens on a tap.
    Nothing may move: the marker is drawn onto the icon, not placed beside it."""

    TODAY = FIXED_TODAY

    @staticmethod
    def warning(onset, expires, severity="Severe", **extra):
        from bedliftcontrol.alerts import WeatherWarning

        return WeatherWarning("Thunderstorm", severity, "Bern", onset, expires, **extra)

    @pytest.fixture
    def warned(self, gui, weather):
        from bedliftcontrol.weather import DailyForecast, Weather

        days = ["2026-09-03", "2026-09-04", "2026-09-05"]
        daily = [DailyForecast(name, date, "sun", 20.0, 9.0, 10, "Klar")
                 for name, date in zip(("Do", "Fr", "Sa"), days)]
        weather.current = Weather("Thun", 21.0, "Klar", "sun", f"{self.TODAY}T08:00",
                                  daily=daily)
        today = self.warning(f"{self.TODAY}T12:00:00+00:00", f"{self.TODAY}T20:00:00+00:00")
        later = self.warning("2026-09-05T06:00:00+00:00", "2026-09-05T18:00:00+00:00",
                             severity="Moderate")
        answers = {self.TODAY: today, "2026-09-05": later}
        weather.warning_on.side_effect = lambda key, day: answers.get(day)
        weather.warnings_for.return_value = [today]
        weather.warned_locations.return_value = {"chatel"}
        return gui, answers

    def test_todays_warning_marks_the_big_icon(self, warned, monkeypatch):
        """The canvas is real here, so its show() has to be replaced to be watched."""
        gui, answers = warned
        shown = MagicMock()
        monkeypatch.setattr(gui.weather_icon, "show", shown)
        gui._apply_weather()
        shown.assert_called_with("sun", answers[FIXED_TODAY].color)

    def test_a_quiet_day_leaves_the_icon_alone(self, gui, weather, monkeypatch):
        from bedliftcontrol.weather import Weather

        weather.current = Weather("Thun", 21.0, "Klar", "sun", f"{FIXED_TODAY}T08:00")
        weather.warning_on.return_value = None
        shown = MagicMock()
        monkeypatch.setattr(gui.weather_icon, "show", shown)
        gui._apply_weather()
        shown.assert_called_with("sun", None)

    def test_the_forecast_marks_only_the_warned_day(self, warned, monkeypatch):
        gui, answers = warned
        drawn = []
        monkeypatch.setattr(gui_module.icons, "IconCanvas",
                            lambda master, size, background: MagicMock())
        gui._apply_weather()
        for label in gui._forecast_labels:
            if hasattr(label, "show") and label.show.call_args:
                drawn.append(label.show.call_args.args)
        assert (("sun", None) in drawn) and (("sun", answers["2026-09-05"].color) in drawn)

    def test_a_new_warning_redraws_the_week(self, warned):
        """The forecast only rebuilds when its key changes, so the warning is in it."""
        gui, _ = warned
        gui._apply_weather()
        first = gui._rendered_forecast_key
        gui.weather.warning_on.side_effect = lambda key, day: None
        gui._apply_weather()
        assert gui._rendered_forecast_key != first

    def test_tapping_a_warned_day_opens_the_panel(self, warned):
        gui, _ = warned
        gui._show_warning(FIXED_TODAY)
        assert gui._view == gui_module.VIEW_WARNING

    def test_tapping_a_quiet_day_opens_nothing(self, warned):
        gui, _ = warned
        gui._show_warning("2026-09-04")
        assert gui._view == gui_module.VIEW_WEATHER

    def test_the_panel_shows_the_text(self, gui, weather):
        import customtkinter

        warning = self.warning(f"{FIXED_TODAY}T12:00:00+00:00", f"{FIXED_TODAY}T20:00:00+00:00",
                               headline="Gewitterwarnung", description="Hagel und Boeen.",
                               instruction="Fahrzeuge sichern.", sender="MeteoSchweiz")
        weather.warning_on.side_effect = lambda key, day: warning
        customtkinter.CTkLabel.reset_mock()
        gui._show_warning(FIXED_TODAY)
        texts = [c.kwargs.get("text", "") for c in customtkinter.CTkLabel.call_args_list]
        assert "Gewitterwarnung" in texts
        assert "Hagel und Boeen." in texts
        assert "Fahrzeuge sichern." in texts
        assert any("MeteoSchweiz" in text for text in texts)

    def test_the_window_names_area_and_time(self, gui, weather):
        warning = self.warning(f"{FIXED_TODAY}T12:00:00+00:00", f"{FIXED_TODAY}T20:00:00+00:00")
        assert "Bern" in gui._warning_subtitle(warning)
        assert "03.09. 12:00" in gui._warning_subtitle(warning)

    def test_an_unreadable_timestamp_leaves_the_subtitle_short(self, gui):
        warning = self.warning("gestern", "morgen")
        assert gui._warning_subtitle(warning) == "Bern"

    def test_the_text_can_scroll(self, gui, weather):
        """A CAP text can be a paragraph or a page."""
        import customtkinter

        warning = self.warning(f"{FIXED_TODAY}T12:00:00+00:00", f"{FIXED_TODAY}T20:00:00+00:00")
        weather.warning_on.side_effect = lambda key, day: warning
        customtkinter.CTkScrollableFrame.reset_mock()
        gui._show_warning(FIXED_TODAY)
        assert customtkinter.CTkScrollableFrame.called

    def test_the_back_button_leads_to_the_weather(self, warned):
        gui, _ = warned
        gui._show_warning(FIXED_TODAY)
        gui._go_back()
        assert gui._view == gui_module.VIEW_WEATHER


class TestWarnedLocationsInTheDropdown:
    def test_a_warned_location_is_marked(self, gui, weather):
        weather.warned_locations.return_value = {"chatel"}
        labels = gui._location_labels()
        assert f"{gui_module.WARNING_MARKER}Châtel" in labels

    def test_the_others_stay_plain(self, gui, weather):
        weather.warned_locations.return_value = {"chatel"}
        assert "Schilthorn" in gui._location_labels()

    def test_choosing_a_marked_entry_still_works(self, gui, weather):
        """The marker is part of the label, so it has to come off again."""
        weather.warned_locations.return_value = {"chatel"}
        gui._on_location_chosen(f"{gui_module.WARNING_MARKER}Châtel")
        weather.select.assert_called_once_with("chatel")

    def test_the_dropdown_opens_on_the_marked_label(self, gui, weather):
        weather.selected = "chatel"
        weather.warned_locations.return_value = {"chatel"}
        gui._show_view(gui_module.VIEW_SETTINGS)
        gui._location_menu.set.assert_called_once_with(f"{gui_module.WARNING_MARKER}Châtel")
