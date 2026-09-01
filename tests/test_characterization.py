"""Characterization tests that pin the current behaviour before refactoring.

These tests describe what the code does *today*. If any of them start failing
after a refactor, the observable behaviour changed and needs a closer look.
"""

from unittest.mock import MagicMock

import pytest

from bedliftcontrol import main


class TestCalculateSleepFromPps:
    @pytest.mark.parametrize(
        "pps, expected",
        [
            (800, (1 / 800) / 2),
            (200, (1 / 200) / 2),
            (1400, (1 / 1400) / 2),
        ],
    )
    def test_returns_half_pulse_period(self, pps, expected):
        assert main.calculate_sleep_from_pps(pps) == expected


class TestEnums:
    def test_direction_values(self):
        assert main.Direction.UP.value == 0
        assert main.Direction.DOWN.value == 1

    def test_pin_values(self):
        assert main.Pins.FRONT_PUL.value == 27
        assert main.Pins.BACK_PUL.value == 24
        assert main.Pins.FRONT_DIR.value == 22
        assert main.Pins.BACK_DIR.value == 23


class TestReadFiles:
    def test_read_steps_file_returns_int(self, tmp_path, monkeypatch):
        f = tmp_path / "steps.txt"
        f.write_text("28000")
        monkeypatch.setattr(main, "STEPS_FILE", str(f))
        result = main.read_steps_file()
        assert result == 28000
        assert isinstance(result, int)

    def test_read_speed_file_returns_float(self, tmp_path, monkeypatch):
        f = tmp_path / "speed.txt"
        f.write_text("800")
        monkeypatch.setattr(main, "SPEED_FILE", str(f))
        result = main.read_speed_file()
        assert result == 800.0
        assert isinstance(result, float)

    def test_read_position_file_bed_up(self, tmp_path, monkeypatch):
        f = tmp_path / "position.txt"
        f.write_text("1")
        monkeypatch.setattr(main, "POSITION_FILE", str(f))
        assert main.read_position_file() == 1

    def test_read_position_file_bed_down(self, tmp_path, monkeypatch):
        f = tmp_path / "position.txt"
        f.write_text("0")
        monkeypatch.setattr(main, "POSITION_FILE", str(f))
        assert main.read_position_file() == 0


class TestWriteFiles:
    def test_write_steps_file(self, tmp_path, monkeypatch):
        f = tmp_path / "steps.txt"
        monkeypatch.setattr(main, "STEPS_FILE", str(f))
        monkeypatch.setattr(main, "steps_text", MagicMock())
        main.write_steps_file(28000)
        assert f.read_text() == "28000"

    def test_write_speed_file(self, tmp_path, monkeypatch):
        f = tmp_path / "speed.txt"
        monkeypatch.setattr(main, "SPEED_FILE", str(f))
        monkeypatch.setattr(main, "speed_text", MagicMock())
        main.write_speed_file(800)
        assert f.read_text() == "800"

    def test_write_position_file_up(self, tmp_path, monkeypatch):
        f = tmp_path / "position.txt"
        monkeypatch.setattr(main, "POSITION_FILE", str(f))
        monkeypatch.setattr(main, "position_text", MagicMock())
        main.write_position_file("1")
        assert f.read_text() == "1"

    def test_write_position_file_down(self, tmp_path, monkeypatch):
        f = tmp_path / "position.txt"
        monkeypatch.setattr(main, "POSITION_FILE", str(f))
        monkeypatch.setattr(main, "position_text", MagicMock())
        main.write_position_file("0")
        assert f.read_text() == "0"


class TestChangeDirection:
    def test_down_sets_both_dir_pins_to_down(self, monkeypatch):
        gpio = MagicMock()
        monkeypatch.setattr(main, "GPIO", gpio)
        main.change_direction(1)
        gpio.output.assert_any_call(main.Pins.FRONT_DIR.value, main.Direction.DOWN.value)
        gpio.output.assert_any_call(main.Pins.BACK_DIR.value, main.Direction.DOWN.value)

    def test_up_sets_both_dir_pins_to_up(self, monkeypatch):
        gpio = MagicMock()
        monkeypatch.setattr(main, "GPIO", gpio)
        main.change_direction(0)
        gpio.output.assert_any_call(main.Pins.FRONT_DIR.value, main.Direction.UP.value)
        gpio.output.assert_any_call(main.Pins.BACK_DIR.value, main.Direction.UP.value)
