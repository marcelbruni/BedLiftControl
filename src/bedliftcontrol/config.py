"""Persistent configuration stored in a single JSON file.

Loading is defensive (missing/corrupt file falls back to defaults) and saving is
atomic and thread-safe, which matters in a vehicle where power can drop mid-write.
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_FILE = str(Path(__file__).resolve().parents[2] / "data" / "config.json")

DEFAULT_TOTAL_STEPS = 28000
DEFAULT_SPEED_PPS = 800.0
DEFAULT_BED_UP = True


@dataclass
class Config:
    total_steps: int = DEFAULT_TOTAL_STEPS
    speed_pps: float = DEFAULT_SPEED_PPS
    bed_up: bool = DEFAULT_BED_UP
    path: str = field(default=CONFIG_FILE, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    @classmethod
    def load(cls, path: str = CONFIG_FILE) -> "Config":
        file = Path(path)
        if not file.exists():
            logger.info("Config file %s not found, using defaults", path)
            return cls(path=str(path))
        try:
            data = json.loads(file.read_text())
            config = cls(
                total_steps=int(data["total_steps"]),
                speed_pps=float(data["speed_pps"]),
                bed_up=bool(data["bed_up"]),
                path=str(path),
            )
        except (ValueError, KeyError, OSError) as error:
            logger.warning("Could not read config %s (%s), using defaults", path, error)
            return cls(path=str(path))
        config._validate()
        return config

    def _validate(self) -> None:
        if self.total_steps <= 0:
            logger.warning("total_steps %s invalid, resetting to %s", self.total_steps, DEFAULT_TOTAL_STEPS)
            self.total_steps = DEFAULT_TOTAL_STEPS
        if self.speed_pps <= 0:
            logger.warning("speed_pps %s invalid, resetting to %s", self.speed_pps, DEFAULT_SPEED_PPS)
            self.speed_pps = DEFAULT_SPEED_PPS

    def save(self) -> None:
        payload = json.dumps(
            {
                "total_steps": self.total_steps,
                "speed_pps": self.speed_pps,
                "bed_up": self.bed_up,
            },
            indent=2,
        )
        target = Path(self.path)
        temp = Path(str(target) + ".tmp")
        with self._lock:
            temp.write_text(payload)
            os.replace(temp, target)  # atomic on the same filesystem
