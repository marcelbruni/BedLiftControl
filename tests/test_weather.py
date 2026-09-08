"""Tests for the weather module (location + forecast + caching)."""

import json

import pytest

from bedliftcontrol import weather as weather_module
from bedliftcontrol.icons import ICON_SPECS
from bedliftcontrol.weather import (
    WEATHER_CODES,
    DailyForecast,
    Weather,
    WeatherService,
    describe_weather_code,
)


class TestDescribeWeatherCode:
    def test_known_code(self):
        description, icon_key = describe_weather_code(0)
        assert description == "Klarer Himmel"
        assert icon_key == "sun"

    def test_unknown_code_falls_back(self):
        assert describe_weather_code(12345) == ("Unbekannt", "unknown")

    @pytest.mark.parametrize("code", [0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65,
                                      66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99])
    def test_every_wmo_code_is_mapped(self, code):
        """Open-Meteo only ever sends these codes, so none of them may hit the fallback."""
        description, icon_key = describe_weather_code(code)
        assert description != "Unbekannt"
        assert icon_key != "unknown"

    def test_no_sharp_s_in_descriptions(self):
        """Swiss spelling: ss, never sz."""
        assert not any("ß" in entry[0] for entry in WEATHER_CODES.values())

    def test_every_icon_key_is_drawable(self):
        """A key with no drawing would silently render as the unknown placeholder."""
        missing = {code: key for code, (_, key) in WEATHER_CODES.items() if key not in ICON_SPECS}
        assert not missing

    def test_no_emoji_left_in_the_table(self):
        """Icons are drawn now - a stray glyph would mean a forgotten entry."""
        assert all(key.replace("-", "").isalnum() and key.isascii()
                   for _, key in WEATHER_CODES.values())


class TestWeatherDataclass:
    def test_dict_roundtrip(self):
        weather = Weather("Thun", 21.0, "Klar", "☀️", "2026-09-03T11:00")
        assert Weather.from_dict(weather.to_dict()) == weather

    def test_dict_roundtrip_with_daily(self):
        daily = [DailyForecast("Do", "2026-09-03", "☀️", 22.0, 12.0)]
        weather = Weather("Thun", 21.0, "Klar", "☀️", "2026-09-03T11:00", daily=daily)
        assert Weather.from_dict(weather.to_dict()) == weather


class TestDailyForecast:
    def test_weekday_label(self):
        # 2026-09-03 is a Thursday
        assert weather_module._weekday_label("2026-09-03") == "Do"

    def test_parse_daily_builds_list(self):
        data = {
            "time": ["2026-09-03", "2026-09-04"],
            "weathercode": [0, 61],
            "temperature_2m_max": [22.0, 18.0],
            "temperature_2m_min": [12.0, 10.0],
            "precipitation_probability_max": [10, 80],
        }
        daily = weather_module._parse_daily(data)
        assert len(daily) == 2
        assert daily[0].day == "Do"
        assert daily[0].temp_max == 22.0
        assert daily[0].rain == 10
        assert daily[1].rain == 80
        assert daily[1].icon

    def test_parse_daily_without_rain_is_none(self):
        data = {
            "time": ["2026-09-03"],
            "weathercode": [0],
            "temperature_2m_max": [22.0],
            "temperature_2m_min": [12.0],
        }
        assert weather_module._parse_daily(data)[0].rain is None

    def test_parse_daily_caps_at_seven(self):
        data = {
            "time": [f"2026-09-{d:02d}" for d in range(1, 12)],
            "weathercode": [0] * 11,
            "temperature_2m_max": [20.0] * 11,
            "temperature_2m_min": [10.0] * 11,
        }
        assert len(weather_module._parse_daily(data)) == 7


class TestWeatherService:
    def test_refresh_once_success_updates_and_caches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(
            weather_module,
            "fetch_weather",
            lambda lat, lon, city: Weather(city, 21.0, "Klar", "☀️", "2026-09-03T11:00"),
        )
        service = WeatherService(path=str(tmp_path / "weather.json"))
        assert service.refresh_once() is True
        assert service.current.city == "Thun"
        assert (tmp_path / "weather.json").exists()

    def test_refresh_once_failure_keeps_current(self, tmp_path, monkeypatch):
        def boom():
            raise OSError("no network")

        monkeypatch.setattr(weather_module, "fetch_location", boom)
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.current = Weather("Thun", 20.0, "Klar", "☀️", "old")
        assert service.refresh_once() is False
        assert service.current.temperature == 20.0

    def test_loads_cache_on_init(self, tmp_path):
        path = tmp_path / "weather.json"
        cached = Weather("Bern", 18.0, "Bewölkt", "☁️", "2026-09-03T10:00")
        path.write_text(json.dumps(cached.to_dict()))
        service = WeatherService(path=str(path))
        assert service.current == cached

    def test_missing_cache_is_none(self, tmp_path):
        service = WeatherService(path=str(tmp_path / "none.json"))
        assert service.current is None
