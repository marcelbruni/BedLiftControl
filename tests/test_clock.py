"""Tests for the date and time formatting.

The names must not come from strftime, whose output depends on the process locale, so
these pin the German spelling explicitly.
"""

from datetime import datetime

import pytest

from bedliftcontrol.clock import MONTHS, WEEKDAYS, format_date, format_time, now


class TestFormatDate:
    @pytest.mark.parametrize(
        "moment, expected",
        [
            (datetime(2026, 9, 8, 12, 8), "Dienstag, 8. September 2026"),
            (datetime(2026, 1, 1, 0, 0), "Donnerstag, 1. Januar 2026"),
            (datetime(2026, 12, 25, 18, 30), "Freitag, 25. Dezember 2026"),
            (datetime(2027, 3, 14, 9, 5), "Sonntag, 14. März 2027"),
        ],
    )
    def test_long_german_form(self, moment, expected):
        assert format_date(moment) == expected

    def test_day_is_not_zero_padded(self):
        assert format_date(datetime(2026, 9, 8)).startswith("Dienstag, 8. ")

    def test_every_weekday_is_named(self):
        assert len(WEEKDAYS) == 7
        assert len(set(WEEKDAYS)) == 7

    def test_every_month_is_named(self):
        assert len(MONTHS) == 12
        assert len(set(MONTHS)) == 12


class TestFormatTime:
    @pytest.mark.parametrize(
        "moment, expected",
        [
            (datetime(2026, 9, 8, 12, 8), "12:08"),
            (datetime(2026, 9, 8, 0, 0), "00:00"),
            (datetime(2026, 9, 8, 9, 5), "09:05"),
            (datetime(2026, 9, 8, 23, 59), "23:59"),
        ],
    )
    def test_zero_padded_24_hour(self, moment, expected):
        assert format_time(moment) == expected

    def test_seconds_are_not_shown(self):
        assert format_time(datetime(2026, 9, 8, 12, 8, 45)) == "12:08"


class TestNow:
    def test_returns_a_datetime(self):
        assert isinstance(now(), datetime)
