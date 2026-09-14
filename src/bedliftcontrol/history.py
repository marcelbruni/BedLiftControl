"""Long lived tracking: how often the bed was cycled, and where it has been.

Deliberately not in config.json. That file is checked into git, and the update
procedure in DEPLOYMENT.md runs `git checkout -- data/config.json`, which would reset
the counter on every update.
"""

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bedliftcontrol import clock

logger = logging.getLogger(__name__)

HISTORY_FILE = str(Path(__file__).resolve().parents[2] / "data" / "history.json")
MAX_LOCATIONS = 1000
POSITION_PRECISION = 4  # ~11m, enough that float jitter does not look like a move


@dataclass(frozen=True)
class LocationVisit:
    at: str
    city: str
    latitude: float
    longitude: float

    def to_dict(self) -> dict:
        return {
            "at": self.at,
            "city": self.city,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LocationVisit":
        return cls(
            at=str(data["at"]),
            city=str(data["city"]),
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
        )

    @property
    def position(self) -> tuple:
        return round(self.latitude, POSITION_PRECISION), round(self.longitude, POSITION_PRECISION)


class History:
    def __init__(self, path: str = HISTORY_FILE):
        self.path = path
        self._lock = threading.Lock()
        self.nights = 0
        self.locations: list = []
        self._lowered_since_last_night = False
        self._load()

    def _load(self) -> None:
        file = Path(self.path)
        if not file.exists():
            return
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            self.nights = int(data.get("nights", 0))
            self._lowered_since_last_night = bool(data.get("lowered_since_last_night", False))
            self.locations = [LocationVisit.from_dict(entry) for entry in data.get("locations", [])]
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
            logger.warning("Could not read history %s (%s)", self.path, error)

    def _save(self) -> None:
        """Failing to write must never propagate: this runs inside the movement thread,
        and losing a statistic is nothing against aborting a moving bed."""
        payload = {
            "nights": self.nights,
            "lowered_since_last_night": self._lowered_since_last_night,
            "locations": [entry.to_dict() for entry in self.locations],
        }
        target = Path(self.path)
        temp = Path(str(target) + ".tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, target)
        except OSError as error:
            logger.warning("Could not write history %s (%s)", self.path, error)

    @property
    def last_location(self):
        return self.locations[-1] if self.locations else None

    def record_position(self, latitude: float, longitude: float, city: str) -> bool:
        """Append the phone position when it differs from the one before it."""
        visit = LocationVisit(
            at=clock.now().isoformat(timespec="seconds"),
            city=city,
            latitude=latitude,
            longitude=longitude,
        )
        with self._lock:
            previous = self.last_location
            if previous is not None and previous.position == visit.position:
                return False
            self.locations.append(visit)
            if len(self.locations) > MAX_LOCATIONS:
                dropped = len(self.locations) - MAX_LOCATIONS
                logger.info("Location history full, dropping the %s oldest", dropped)
                del self.locations[:dropped]
        self._save()
        logger.info("New location recorded: %s (%s, %s)", city, latitude, longitude)
        return True

    def record_bed_position(self, at_top: bool, at_bottom: bool) -> bool:
        """Count a night once the bed comes back up from having been all the way down.

        The flag is persisted because the two halves are a whole evening apart, with a
        reboot and any number of interrupted moves possibly in between.
        """
        with self._lock:
            if at_bottom:
                if self._lowered_since_last_night:
                    return False
                self._lowered_since_last_night = True
                counted = False
            elif at_top and self._lowered_since_last_night:
                self._lowered_since_last_night = False
                self.nights += 1
                counted = True
            else:
                return False
        self._save()
        if counted:
            logger.info("Night %s recorded", self.nights)
        return counted
