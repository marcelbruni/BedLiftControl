"""Tests for the weather module (location + forecast + caching)."""

import json

import pytest

from bedliftcontrol import weather as weather_module
from bedliftcontrol.icons import ICON_SPECS
from bedliftcontrol.weather import (
    LOCATIONS,
    LOCATIONS_BY_KEY,
    PHONE_LOCATION,
    WEATHER_CODES,
    DailyForecast,
    Weather,
    WeatherService,
    describe_weather_code,
    location_or_default,
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


def _reading(city, temperature=21.0):
    return Weather(city, temperature, "Klarer Himmel", "sun", "2026-09-03T11:00")


def _batch(**by_city):
    """Stand in for fetch_weather_batch: one reading per requested point."""

    def fetch(points):
        return [_reading(city, by_city.get(city, 21.0)) for _, _, city in points]

    return fetch


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
    monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch())


class TestWeatherService:
    def test_refresh_fetches_every_location_in_one_request(self, tmp_path, monkeypatch):
        calls = []

        def fetch(points):
            calls.append(points)
            return [_reading(city) for _, _, city in points]

        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", fetch)
        service = WeatherService(path=str(tmp_path / "weather.json"))
        assert service.refresh_once() is True
        assert len(calls) == 1, "all locations must go out as a single request"
        assert len(calls[0]) == len(LOCATIONS)
        assert set(service.readings) == {location.key for location in LOCATIONS}

    def test_the_phone_location_uses_the_resolved_city(self, tmp_path, online):
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.refresh_once()
        assert service.reading_for(PHONE_LOCATION).city == "Thun"

    def test_fixed_locations_use_their_label(self, tmp_path, online):
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.refresh_once()
        assert service.reading_for("schilthorn").city == "Schilthorn"

    def test_current_follows_the_selection(self, tmp_path, online):
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.refresh_once()
        service.select("chatel")
        assert service.current.city == "Châtel"
        service.select("lacure")
        assert service.current.city == "La Cure"

    def test_an_unknown_selection_falls_back_to_the_phone(self, tmp_path, online):
        service = WeatherService(path=str(tmp_path / "weather.json"), selected="atlantis")
        assert service.selected == PHONE_LOCATION
        service.select("also-not-a-place")
        assert service.selected == PHONE_LOCATION

    def test_a_failing_ip_lookup_still_fetches_the_fixed_places(self, tmp_path, monkeypatch):
        """Being unable to locate the phone must not cost us the rest."""

        def boom():
            raise OSError("no network")

        monkeypatch.setattr(weather_module, "fetch_location", boom)
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch())
        service = WeatherService(path=str(tmp_path / "weather.json"))
        assert service.refresh_once() is True
        assert PHONE_LOCATION not in service.readings
        assert service.reading_for("hoefen").city == "Höfen bei Thun"

    def test_a_failing_ip_lookup_keeps_the_previous_phone_reading(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch(Thun=20.0))
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.refresh_once()

        def boom():
            raise OSError("tethering gone")

        monkeypatch.setattr(weather_module, "fetch_location", boom)
        service.refresh_once()
        assert service.reading_for(PHONE_LOCATION).temperature == 20.0

    def test_a_failing_forecast_keeps_every_reading(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch(Thun=20.0))
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.refresh_once()

        def boom(_points):
            raise OSError("no network")

        monkeypatch.setattr(weather_module, "fetch_weather_batch", boom)
        assert service.refresh_once() is False
        assert service.reading_for(PHONE_LOCATION).temperature == 20.0

    def test_every_reading_is_cached_and_read_back(self, tmp_path, online):
        path = tmp_path / "weather.json"
        WeatherService(path=str(path)).refresh_once()
        assert path.exists()
        restored = WeatherService(path=str(path), selected="cransmontana")
        assert restored.current.city == "Crans-Montana"
        assert set(restored.readings) == {location.key for location in LOCATIONS}

    def test_missing_cache_is_none(self, tmp_path):
        service = WeatherService(path=str(tmp_path / "none.json"))
        assert service.current is None
        assert service.readings == {}

    def test_a_cache_from_before_multiple_locations_is_ignored(self, tmp_path):
        """The old file held one bare reading. Refetching costs one cycle, guessing
        which location it belonged to would be worse."""
        path = tmp_path / "weather.json"
        path.write_text(json.dumps(_reading("Bern").to_dict()))
        service = WeatherService(path=str(path))
        assert service.readings == {}

    def test_an_unknown_key_in_the_cache_is_dropped(self, tmp_path):
        path = tmp_path / "weather.json"
        path.write_text(json.dumps({"readings": {"atlantis": _reading("Atlantis").to_dict()}}))
        assert WeatherService(path=str(path)).readings == {}

    def test_a_corrupt_cache_does_not_raise(self, tmp_path):
        path = tmp_path / "weather.json"
        path.write_text("{not json")
        assert WeatherService(path=str(path)).readings == {}


class TestRetryInterval:
    """Requirement: pick the weather up as soon as a connection appears, rather than
    sitting out the full refresh interval."""

    def test_a_failed_refresh_retries_sooner(self, tmp_path, monkeypatch):
        waits = []

        def boom(_points):
            raise OSError("offline")

        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", boom)
        service = WeatherService(path=str(tmp_path / "weather.json"),
                                 refresh_interval=1800, retry_interval=60)

        def wait(seconds):
            waits.append(seconds)
            service._stop.set()
            return True

        monkeypatch.setattr(service._stop, "wait", wait)
        service._loop()
        assert waits == [60]

    def test_a_successful_refresh_waits_the_full_interval(self, tmp_path, monkeypatch):
        waits = []
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch())
        service = WeatherService(path=str(tmp_path / "weather.json"),
                                 refresh_interval=1800, retry_interval=60)

        def wait(seconds):
            waits.append(seconds)
            service._stop.set()
            return True

        monkeypatch.setattr(service._stop, "wait", wait)
        service._loop()
        assert waits == [1800]


class TestFetchWeatherBatch:
    def test_a_single_point_answer_is_a_bare_object(self, monkeypatch):
        """Open-Meteo returns a list for several coordinates but an object for one."""
        payload = {
            "current_weather": {"temperature": 12.0, "weathercode": 0},
            "daily": {},
        }
        monkeypatch.setattr(weather_module, "_http_get_json", lambda _url: payload)
        result = weather_module.fetch_weather_batch([(46.7, 7.6, "Thun")])
        assert [reading.city for reading in result] == ["Thun"]

    def test_several_points_keep_their_order(self, monkeypatch):
        def entry(temperature):
            return {"current_weather": {"temperature": temperature, "weathercode": 0}, "daily": {}}

        monkeypatch.setattr(weather_module, "_http_get_json",
                            lambda _url: [entry(1.0), entry(2.0), entry(3.0)])
        points = [(1.0, 1.0, "A"), (2.0, 2.0, "B"), (3.0, 3.0, "C")]
        result = weather_module.fetch_weather_batch(points)
        assert [(r.city, r.temperature) for r in result] == [("A", 1.0), ("B", 2.0), ("C", 3.0)]

    def test_a_short_answer_is_refused(self, monkeypatch):
        """Silently zipping would attach the wrong weather to a location."""
        monkeypatch.setattr(
            weather_module, "_http_get_json",
            lambda _url: [{"current_weather": {"temperature": 1.0, "weathercode": 0}, "daily": {}}],
        )
        with pytest.raises(ValueError):
            weather_module.fetch_weather_batch([(1.0, 1.0, "A"), (2.0, 2.0, "B")])

    def test_no_points_means_no_request(self, monkeypatch):
        def boom(_url):
            raise AssertionError("must not reach the network")

        monkeypatch.setattr(weather_module, "_http_get_json", boom)
        assert weather_module.fetch_weather_batch([]) == []

    def test_all_coordinates_go_into_one_url(self, monkeypatch):
        seen = {}

        def capture(url):
            seen["url"] = url
            return [{"current_weather": {"temperature": 1.0, "weathercode": 0}, "daily": {}}] * 2

        monkeypatch.setattr(weather_module, "_http_get_json", capture)
        weather_module.fetch_weather_batch([(46.7210, 7.5644, "A"), (46.2649, 6.8403, "B")])
        assert "latitude=46.7210,46.2649" in seen["url"]
        assert "longitude=7.5644,6.8403" in seen["url"]


class TestLocations:
    def test_the_phone_location_comes_first(self):
        assert LOCATIONS[0].key == PHONE_LOCATION

    def test_only_the_phone_location_has_no_coordinates(self):
        for location in LOCATIONS:
            assert location.follows_the_phone == (location.key == PHONE_LOCATION)

    def test_keys_and_labels_are_unique(self):
        assert len({location.key for location in LOCATIONS}) == len(LOCATIONS)
        assert len({location.label for location in LOCATIONS}) == len(LOCATIONS)

    @pytest.mark.parametrize(
        "key, label, latitude, longitude",
        [
            ("hoefen", "H\u00f6fen bei Thun", 46.7210, 7.5644),
            ("chatel", "Ch\u00e2tel", 46.2649, 6.8403),
            ("lacure", "La Cure", 46.4647, 6.0742),
            ("schilthorn", "Schilthorn", 46.5573, 7.8349),
            ("cransmontana", "Crans-Montana", 46.3132, 7.4791),
        ],
    )
    def test_coordinates_are_the_looked_up_ones(self, key, label, latitude, longitude):
        location = LOCATIONS_BY_KEY[key]
        assert location.label == label
        assert (location.latitude, location.longitude) == (latitude, longitude)

    def test_all_locations_are_in_the_alps_or_nearby(self):
        """A transposed pair of coordinates would silently fetch weather for the sea."""
        for location in LOCATIONS:
            if location.follows_the_phone:
                continue
            assert 45.0 < location.latitude < 48.0, location.key
            assert 5.0 < location.longitude < 11.0, location.key

    def test_location_or_default_resolves_known_keys(self):
        assert location_or_default("schilthorn").key == "schilthorn"

    def test_location_or_default_falls_back(self):
        assert location_or_default("nowhere").key == PHONE_LOCATION


class TestPhonePosition:
    """ipapi.co answers HTTP 429 after a few calls in quick succession, so a failed
    lookup must not cost us the location - only the update of its coordinates."""

    def test_a_failed_lookup_reuses_the_last_position(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch())
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.refresh_once()

        def rate_limited():
            raise OSError("HTTP Error 429: Too Many Requests")

        monkeypatch.setattr(weather_module, "fetch_location", rate_limited)
        keys, points = service._request_points()
        assert PHONE_LOCATION in keys
        assert points[0] == (46.7, 7.6, "Thun")

    def test_the_phone_location_keeps_being_refreshed_while_rate_limited(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch(Thun=20.0))
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.refresh_once()

        def rate_limited():
            raise OSError("HTTP Error 429: Too Many Requests")

        monkeypatch.setattr(weather_module, "fetch_location", rate_limited)
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch(Thun=25.0))
        assert service.refresh_once() is True
        assert service.reading_for(PHONE_LOCATION).temperature == 25.0

    def test_without_any_position_the_location_is_skipped(self, tmp_path, monkeypatch):
        def boom():
            raise OSError("never resolved")

        monkeypatch.setattr(weather_module, "fetch_location", boom)
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch())
        service = WeatherService(path=str(tmp_path / "weather.json"))
        keys, _ = service._request_points()
        assert PHONE_LOCATION not in keys

    def test_a_later_success_adopts_the_new_position(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, "Thun"))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch())
        service = WeatherService(path=str(tmp_path / "weather.json"))
        service.refresh_once()
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.2, 6.8, "Sion"))
        _, points = service._request_points()
        assert points[0] == (46.2, 6.8, "Sion")

    def test_an_empty_city_falls_back_to_the_label(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weather_module, "fetch_location", lambda: (46.7, 7.6, ""))
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch())
        service = WeatherService(path=str(tmp_path / "weather.json"))
        _, points = service._request_points()
        assert points[0][2] == "Handystandort"

    def test_the_lookup_happens_once_per_refresh(self, tmp_path, monkeypatch):
        """Not once per location - that would multiply the rate limit problem."""
        calls = []

        def counting():
            calls.append(1)
            return 46.7, 7.6, "Thun"

        monkeypatch.setattr(weather_module, "fetch_location", counting)
        monkeypatch.setattr(weather_module, "fetch_weather_batch", _batch())
        WeatherService(path=str(tmp_path / "weather.json")).refresh_once()
        assert len(calls) == 1
