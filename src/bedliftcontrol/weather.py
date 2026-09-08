"""Fetch, cache and provide the current weather for the main panel.

Location comes from the public IP (rough, city level); the forecast from Open-Meteo
(free, no API key). The last result is cached to disk so something is still shown
when the internet connection (phone tethering) drops.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

WEATHER_FILE = str(Path(__file__).resolve().parents[2] / "data" / "weather.json")
LOCATION_URL = "https://ipapi.co/json/"
FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}&current_weather=true"
    "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    "&timezone=auto"
)
REFRESH_INTERVAL_SECONDS = 1800
HTTP_TIMEOUT = 8

# Open-Meteo WMO weather codes -> (description, icon key). Texts follow the official
# WMO interpretation wording from https://open-meteo.com/en/docs, in German.
# The icon key names a drawing in bedliftcontrol.icons - one icon per code, scaled to
# whatever size the caller needs. Emoji were dropped because Unicode has no graded
# weather glyphs (no "cloud with two drops") and Tk shows tofu boxes for the ones the
# installed emoji font has no monochrome outline for.
WEATHER_CODES = {
    0: ("Klarer Himmel",                     "sun"),
    1: ("Überwiegend klar",                  "sun-cloud-light"),
    2: ("Teilweise bewölkt",                 "sun-cloud"),
    3: ("Bedeckt",                           "cloud"),
    45: ("Nebel",                             "fog"),
    48: ("Reifnebel",                         "fog-ice"),
    51: ("Leichter Nieselregen",              "drizzle-1"),
    53: ("Mässiger Nieselregen",              "drizzle-2"),
    55: ("Dichter Nieselregen",               "drizzle-3"),
    56: ("Leichter gefrierender Nieselregen", "drizzle-ice-1"),
    57: ("Dichter gefrierender Nieselregen",  "drizzle-ice-2"),
    61: ("Leichter Regen",                    "rain-1"),
    63: ("Mässiger Regen",                    "rain-2"),
    65: ("Starker Regen",                     "rain-3"),
    66: ("Leichter gefrierender Regen",       "rain-ice-3"),
    67: ("Starker gefrierender Regen",        "rain-ice-4"),
    71: ("Leichter Schneefall",               "snow-1"),
    73: ("Mässiger Schneefall",               "snow-2"),
    75: ("Starker Schneefall",                "snow-3"),
    77: ("Schneegriesel",                     "flake"),
    80: ("Leichte Regenschauer",              "shower-1"),
    81: ("Mässige Regenschauer",              "shower-2"),
    82: ("Heftige Regenschauer",              "shower-3"),
    85: ("Leichte Schneeschauer",             "snow-shower-1"),
    86: ("Starke Schneeschauer",              "snow-shower-2"),
    95: ("Gewitter",                          "thunder"),
    96: ("Gewitter mit leichtem Hagel",       "thunder-hail-2"),
    99: ("Gewitter mit starkem Hagel",        "thunder-hail-4"),
}


def describe_weather_code(code: int) -> tuple[str, str]:
    """(description, icon key) for a WMO code. See WEATHER_CODES."""
    return WEATHER_CODES.get(code, ("Unbekannt", "unknown"))


WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _weekday_label(date_iso: str) -> str:
    return WEEKDAY_LABELS[datetime.strptime(date_iso, "%Y-%m-%d").weekday()]


@dataclass
class DailyForecast:
    day: str
    date: str
    icon: str
    temp_max: float
    temp_min: float
    rain: int | None = None

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "date": self.date,
            "icon": self.icon,
            "temp_max": self.temp_max,
            "temp_min": self.temp_min,
            "rain": self.rain,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DailyForecast":
        return cls(
            day=str(data["day"]),
            date=str(data["date"]),
            icon=str(data["icon"]),
            temp_max=float(data["temp_max"]),
            temp_min=float(data["temp_min"]),
            rain=data.get("rain"),
        )


@dataclass
class Weather:
    city: str
    temperature: float
    description: str
    icon: str
    fetched_at: str
    daily: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "temperature": self.temperature,
            "description": self.description,
            "icon": self.icon,
            "fetched_at": self.fetched_at,
            "daily": [day.to_dict() for day in self.daily],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Weather":
        return cls(
            city=str(data["city"]),
            temperature=float(data["temperature"]),
            description=str(data["description"]),
            icon=str(data["icon"]),
            fetched_at=str(data["fetched_at"]),
            daily=[DailyForecast.from_dict(day) for day in data.get("daily", [])],
        )


def _http_get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "BedLiftControl/1.0"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_location() -> tuple[float, float, str]:
    data = _http_get_json(LOCATION_URL)
    return float(data["latitude"]), float(data["longitude"]), str(data.get("city", ""))


def _parse_daily(daily_data: dict) -> list:
    times = daily_data.get("time", [])
    codes = daily_data.get("weathercode", [])
    highs = daily_data.get("temperature_2m_max", [])
    lows = daily_data.get("temperature_2m_min", [])
    rains = daily_data.get("precipitation_probability_max", [])
    count = min(len(times), len(codes), len(highs), len(lows), 7)
    forecast = []
    for i in range(count):
        _, icon = describe_weather_code(int(codes[i]))
        rain = int(rains[i]) if i < len(rains) and rains[i] is not None else None
        forecast.append(
            DailyForecast(
                day=_weekday_label(times[i]),
                date=times[i],
                icon=icon,
                temp_max=float(highs[i]),
                temp_min=float(lows[i]),
                rain=rain,
            )
        )
    return forecast


def fetch_weather(lat: float, lon: float, city: str) -> Weather:
    data = _http_get_json(FORECAST_URL.format(lat=lat, lon=lon))
    current = data["current_weather"]
    description, icon = describe_weather_code(int(current["weathercode"]))
    return Weather(
        city=city,
        temperature=float(current["temperature"]),
        description=description,
        icon=icon,
        fetched_at=datetime.now().isoformat(timespec="minutes"),
        daily=_parse_daily(data.get("daily", {})),
    )


class WeatherService:
    def __init__(self, path: str = WEATHER_FILE, refresh_interval: int = REFRESH_INTERVAL_SECONDS):
        self.path = path
        self.refresh_interval = refresh_interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current: Weather | None = self._load_cache()

    def _load_cache(self) -> Weather | None:
        file = Path(self.path)
        if not file.exists():
            return None
        try:
            return Weather.from_dict(json.loads(file.read_text(encoding="utf-8")))
        except (ValueError, KeyError, OSError) as error:
            logger.warning("Could not read weather cache %s (%s)", self.path, error)
            return None

    def _save_cache(self, weather: Weather) -> None:
        target = Path(self.path)
        temp = Path(str(target) + ".tmp")
        temp.write_text(json.dumps(weather.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, target)

    def refresh_once(self) -> bool:
        try:
            lat, lon, city = fetch_location()
            weather = fetch_weather(lat, lon, city)
        except Exception:  # network boundary: a failed fetch must never crash the app
            logger.warning("Weather refresh failed", exc_info=True)
            return False
        with self._lock:
            self.current = weather
        self._save_cache(weather)
        return True

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh_once()
            self._stop.wait(self.refresh_interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
