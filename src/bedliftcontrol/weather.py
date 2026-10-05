"""Fetch, cache and provide the weather for the main panel.

Several locations are offered: the current one, derived from the public IP (rough,
city level), plus a fixed list of places we travel to. Every refresh fetches all of
them in a single Open-Meteo request (free, no API key) and caches the lot to disk, so
switching location works instantly and still shows something once the phone tethering
drops.
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

from bedliftcontrol import alerts, connectivity

logger = logging.getLogger(__name__)

WEATHER_FILE = str(Path(__file__).resolve().parents[2] / "data" / "weather.json")
LOCATION_URL = "https://ipapi.co/json/"
FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lats}&longitude={lons}&current_weather=true"
    "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    "&timezone=auto"
)
REFRESH_INTERVAL_SECONDS = 3600
# While offline nothing is fetched at all; this is only how often the cheap reachability
# probe runs, so the refresh follows a hotspot coming up within seconds.
PROBE_INTERVAL_SECONDS = 15
HTTP_TIMEOUT = 8


def _log_repeated_failure(what: str, attempts: int, error) -> None:
    """The traceback once, a single line after that.

    A machine that is online while the API is down retries every fifteen seconds, and
    a day of full stack traces fills the whole log with the same one - exactly when the
    lines around it are the ones worth reading.
    """
    if attempts == 1:
        logger.warning("%s failed", what, exc_info=True)
    else:
        logger.info("%s still failing (attempt %s): %s", what, attempts, error)


@dataclass(frozen=True)
class Location:
    key: str
    label: str
    latitude: float | None = None
    longitude: float | None = None
    # NUTS3 codes and area names the warning feeds use for this place, see LOCATIONS
    regions: tuple = ()

    @property
    def follows_the_phone(self) -> bool:
        return self.latitude is None or self.longitude is None


PHONE_LOCATION = "phone"

# Coordinates looked up once via the Open-Meteo geocoding API. Schilthorn exists twice
# in that database; this is the Bernese one above Muerren, not the Valais peak.
# The warning feeds carry no geometry, only NUTS3 codes and area names, so a place can
# only be warned about if its region is written down here. The names are matched too,
# because the Swiss feed was empty while this was built and its identifiers could not be
# verified - an unmatched area is logged, which is how the missing ones will surface.
# La Cure sits on the border and takes both sides.
LOCATIONS = (
    Location(PHONE_LOCATION, "Handystandort"),
    Location("hoefen", "Höfen bei Thun", 46.7210, 7.5644,
             ("CH021", "bern", "berne")),
    Location("chatel", "Châtel", 46.2649, 6.8403,
             ("FR718", "haute-savoie")),
    Location("lacure", "La Cure", 46.4647, 6.0742,
             ("FR432", "jura", "CH011", "vaud", "waadt")),
    Location("schilthorn", "Schilthorn", 46.5573, 7.8349,
             ("CH021", "bern", "berne")),
    Location("cransmontana", "Crans-Montana", 46.3132, 7.4791,
             ("CH012", "valais", "wallis")),
)
LOCATIONS_BY_KEY = {location.key: location for location in LOCATIONS}


def location_or_default(key: str) -> Location:
    return LOCATIONS_BY_KEY.get(key, LOCATIONS_BY_KEY[PHONE_LOCATION])

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
    77: ("Schneegriesel",                     "grains"),
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
    # kept alongside the icon so a day can stand in for the current conditions when
    # the connection is gone and the last reading is from yesterday
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "date": self.date,
            "icon": self.icon,
            "temp_max": self.temp_max,
            "temp_min": self.temp_min,
            "rain": self.rain,
            "description": self.description,
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
            # .get: a cache written before the descriptions existed is still usable
            description=str(data.get("description", "")),
        )


@dataclass
class Weather:
    city: str
    temperature: float
    description: str
    icon: str
    fetched_at: str
    daily: list = field(default_factory=list)

    @property
    def date(self) -> str:
        """The day this reading belongs to, as an ISO date."""
        return self.fetched_at[:10]

    @property
    def weekday(self) -> str:
        """Two letters for the day this reading belongs to, taken from its own
        timestamp rather than from today - an old reading stays honest that way."""
        try:
            return _weekday_label(self.date)
        except (ValueError, IndexError):
            return ""

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
        description, icon = describe_weather_code(int(codes[i]))
        rain = int(rains[i]) if i < len(rains) and rains[i] is not None else None
        forecast.append(
            DailyForecast(
                day=_weekday_label(times[i]),
                date=times[i],
                icon=icon,
                temp_max=float(highs[i]),
                temp_min=float(lows[i]),
                rain=rain,
                description=description,
            )
        )
    return forecast


def _parse_weather(entry: dict, city: str) -> Weather:
    current = entry["current_weather"]
    description, icon = describe_weather_code(int(current["weathercode"]))
    return Weather(
        city=city,
        temperature=float(current["temperature"]),
        description=description,
        icon=icon,
        fetched_at=datetime.now().isoformat(timespec="minutes"),
        daily=_parse_daily(entry.get("daily", {})),
    )


def fetch_weather_batch(points: list) -> list:
    """All locations in one request. Open-Meteo answers comma separated coordinates
    with a JSON list, one entry per point, and a bare object for a single point.

    `points` are (latitude, longitude, city) triples; the result keeps their order.
    """
    if not points:
        return []
    lats = ",".join(f"{lat:.4f}" for lat, _, _ in points)
    lons = ",".join(f"{lon:.4f}" for _, lon, _ in points)
    data = _http_get_json(FORECAST_URL.format(lats=lats, lons=lons))
    entries = data if isinstance(data, list) else [data]
    if len(entries) != len(points):
        raise ValueError(f"requested {len(points)} locations, received {len(entries)}")
    return [_parse_weather(entry, city) for entry, (_, _, city) in zip(entries, points)]


class WeatherService:
    def __init__(
        self,
        path: str = WEATHER_FILE,
        refresh_interval: int = REFRESH_INTERVAL_SECONDS,
        probe_interval: int = PROBE_INTERVAL_SECONDS,
        selected: str = PHONE_LOCATION,
        history=None,
    ):
        self.path = path
        self.refresh_interval = refresh_interval
        self.probe_interval = probe_interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._selected = location_or_default(selected).key
        self._last_phone_position = None
        self.history = history
        self.readings: dict = {}
        self.warnings: dict = {}
        self._failures = 0
        self._load_cache()

    @property
    def selected(self) -> str:
        return self._selected

    def select(self, key: str) -> None:
        self._selected = location_or_default(key).key

    @property
    def current(self) -> Weather | None:
        return self.reading_for(self._selected)

    def reading_for(self, key: str) -> Weather | None:
        with self._lock:
            return self.readings.get(key)

    def _load_cache(self) -> None:
        """Readings and warnings alike: both have to survive a start without a network."""
        file = Path(self.path)
        if not file.exists():
            return
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            self.readings = {
                key: Weather.from_dict(value)
                for key, value in data.get("readings", {}).items()
                if key in LOCATIONS_BY_KEY
            }
            self.warnings = {
                key: [alerts.WeatherWarning.from_dict(entry) for entry in entries]
                for key, entries in data.get("warnings", {}).items()
                if key in LOCATIONS_BY_KEY
            }
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
            logger.warning("Could not read weather cache %s (%s)", self.path, error)
            self.readings = {}
            self.warnings = {}

    def _save_cache(self) -> None:
        with self._lock:
            payload = {
                "readings": {key: value.to_dict() for key, value in self.readings.items()},
                "warnings": {key: [warning.to_dict() for warning in entries]
                             for key, entries in self.warnings.items()},
            }
        target = Path(self.path)
        temp = Path(str(target) + ".tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, target)
        except OSError as error:
            # this runs in the refresh thread; letting it out would end the thread and
            # with it the weather, over a cache that is a convenience either way
            logger.warning("Could not write the weather cache %s (%s)", self.path, error)

    def refresh_once(self) -> bool:
        keys, points = self._request_points()
        if not points:
            return False
        try:
            readings = fetch_weather_batch(points)
        except Exception as error:  # network boundary: a failed fetch must never crash
            self._failures += 1
            _log_repeated_failure("Weather refresh", self._failures, error)
            return False
        self._failures = 0
        with self._lock:
            self.readings.update(dict(zip(keys, readings)))
        self._refresh_warnings()
        self._save_cache()
        logger.info("Weather updated for %s", ", ".join(keys))
        return True

    def _refresh_warnings(self) -> None:
        """Official warnings for the places whose region is known.

        Kept apart from the readings: a warning feed that cannot be read must not cost
        us the weather, and the warnings we had stay on screen until better ones arrive.

        Replaced wholesale rather than merged, so an expired warning really goes away.
        None means the feeds could not be read at all, which is not the same as nothing
        being in force - then the old set stays.
        """
        found = alerts.fetch_warnings(LOCATIONS)
        if found is None:
            return
        with self._lock:
            self.warnings = found

    def warnings_for(self, key: str) -> list:
        """Every warning in force for a location, worst first."""
        with self._lock:
            entries = list(self.warnings.get(key, ()))
        return sorted(entries, key=lambda warning: -warning.rank)

    def warning_on(self, key: str, day: str):
        """The worst warning covering `day` at that location, or None."""
        for warning in self.warnings_for(key):
            if warning.covers(day):
                return warning
        return None

    def warned_locations(self) -> set:
        """Keys of the locations that have any warning - for marking the dropdown."""
        with self._lock:
            return {key for key, entries in self.warnings.items() if entries}

    def _request_points(self) -> tuple:
        """Keys and (latitude, longitude, city) triples for the coming request.

        The phone location is only left out while its position has never been resolved;
        the fixed places are always fetched.
        """
        keys, points = [], []
        for location in LOCATIONS:
            if location.follows_the_phone:
                position = self._phone_position()
                if position is None:
                    continue
                points.append(position)
            else:
                points.append((location.latitude, location.longitude, location.label))
            keys.append(location.key)
        return keys, points

    def _phone_position(self):
        """Where the phone is, reusing the last answer when the lookup fails.

        ipapi.co answers HTTP 429 after a handful of calls in quick succession, and a
        parked vehicle has not moved anyway - so a failed lookup must not cost us the
        location, only the update of its coordinates.
        """
        try:
            latitude, longitude, city = fetch_location()
        except Exception:
            if self._last_phone_position is None:
                logger.warning("Cannot locate the phone yet, skipping that location", exc_info=True)
            else:
                logger.info("Phone location lookup failed, keeping the last known position")
            return self._last_phone_position
        self._last_phone_position = (
            latitude,
            longitude,
            city or LOCATIONS_BY_KEY[PHONE_LOCATION].label,
        )
        if self.history is not None:
            self.history.record_position(latitude, longitude, self._last_phone_position[2])
        return self._last_phone_position

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.refresh_once():
                self._stop.wait(self.refresh_interval)
            elif not self._wait_for_connection():
                return

    def _wait_for_connection(self) -> bool:
        """Hold until the machine can reach the internet. False when the service stops.

        Waiting first rather than probing first also spaces out the retries when we are
        online but the API itself is having a bad minute.
        """
        while not self._stop.wait(self.probe_interval):
            if connectivity.is_online():
                logger.info("Connection is back, fetching the weather")
                return True
        return False

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
