"""Tests for the weather module (location + forecast + caching)."""

import json

from bedliftcontrol import weather as weather_module
from bedliftcontrol.weather import Weather, WeatherService, describe_weather_code


class TestDescribeWeatherCode:
    def test_known_code(self):
        description, icon = describe_weather_code(0)
        assert description == "Klar"
        assert icon

    def test_unknown_code_falls_back(self):
        assert describe_weather_code(12345) == ("Unbekannt", "❓")


class TestWeatherDataclass:
    def test_dict_roundtrip(self):
        weather = Weather("Thun", 21.0, "Klar", "☀️", "2026-09-03T11:00")
        assert Weather.from_dict(weather.to_dict()) == weather


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
