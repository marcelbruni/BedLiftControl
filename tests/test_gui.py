"""Tests for the GUI logic. customtkinter is mocked (conftest.py), so no window opens.

The ``ctk_widgets`` fixture makes each widget constructor return a new mock so
buttons/labels/windows can be told apart, and stubs out the message box.
"""

from unittest.mock import MagicMock

import pytest

from bedliftcontrol import gui as gui_module
from bedliftcontrol.gui import BedGui, MoveContext

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


@pytest.fixture(autouse=True)
def ctk_widgets(monkeypatch):
    import customtkinter

    for name in WIDGETS:
        getattr(customtkinter, name).side_effect = lambda *args, **kwargs: MagicMock()
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
def gui(controller):
    return BedGui(controller)


class TestInitialState:
    def test_bed_down_disables_down_button(self, controller):
        controller.config.bed_up = False
        built = BedGui(controller)
        assert "disabled" in _states(built.down_button)

    def test_bed_up_disables_up_button(self, controller):
        controller.config.bed_up = True
        built = BedGui(controller)
        assert "disabled" in _states(built.up_button)

    def test_build_sets_initial_bar(self, gui):
        gui.progress_bar.set.assert_called()


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
        gui.progress_bar.set.assert_called()


class TestProgressBar:
    def test_set_bar_clamps_high(self, gui):
        gui._set_bar(2.0)
        gui.progress_bar.set.assert_called_with(1.0)

    def test_set_bar_clamps_low(self, gui):
        gui._set_bar(-1.0)
        gui.progress_bar.set.assert_called_with(0.0)


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
