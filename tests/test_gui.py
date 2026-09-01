"""Tests for the GUI logic. guizero is mocked (conftest.py), so no window opens.

The mocked guizero module returns a single shared mock per widget class by
default; the ``fresh_widgets`` fixture makes each widget constructor return a
new mock so buttons/labels can be told apart.
"""

from unittest.mock import MagicMock

import pytest

from bedliftcontrol.gui import BedGui, MoveContext


@pytest.fixture(autouse=True)
def fresh_widgets():
    import guizero

    for name in ["App", "Box", "Text", "PushButton", "Slider", "Window"]:
        getattr(guizero, name).side_effect = lambda *args, **kwargs: MagicMock()
    yield
    for name in ["App", "Box", "Text", "PushButton", "Slider", "Window"]:
        getattr(guizero, name).side_effect = None


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
        gui = BedGui(controller)
        assert gui.down_button.enabled is False

    def test_bed_up_disables_up_button(self, controller):
        controller.config.bed_up = True
        gui = BedGui(controller)
        assert gui.up_button.enabled is False


class TestOnUp:
    def test_disables_both_and_starts_move(self, gui, controller):
        gui._on_up()
        assert gui.up_button.enabled is False
        assert gui.down_button.enabled is False
        assert gui._move_context is MoveContext.UP
        controller.run_async.assert_called_once_with(controller.move_up)
        gui.app.repeat.assert_called_once()

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
        gui.app.cancel.assert_called_once()
        assert gui.up_button.enabled is False
        assert gui.down_button.enabled is True
        assert gui._move_context is None

    def test_finalizes_down(self, gui, controller):
        controller.is_moving = False
        gui._move_context = MoveContext.DOWN
        gui._poll_movement()
        assert gui.up_button.enabled is True
        assert gui.down_button.enabled is False

    def test_shows_progress_while_moving(self, gui, controller):
        controller.is_moving = True
        controller.progress = 0.5
        gui._poll_movement()
        assert "50" in gui.progress_text.value


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
        gui._settings_window()  # opens
        window = gui._open_windows["settings"]
        gui._settings_window()  # same button again -> closes
        assert "settings" not in gui._open_windows
        window.destroy.assert_called_once()

    def test_closing_via_x_clears_the_reference(self, gui):
        gui._corrections_window()
        gui._on_window_closed("corrections")
        assert "corrections" not in gui._open_windows

    def test_each_button_tracks_its_own_window(self, gui):
        gui._settings_window()
        gui._corrections_window()
        assert set(gui._open_windows) == {"settings", "corrections"}
