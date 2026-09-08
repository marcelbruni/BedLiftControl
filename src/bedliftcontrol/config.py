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
DEFAULT_KIOSK = False


@dataclass
class Config:
    total_steps: int = DEFAULT_TOTAL_STEPS
    speed_pps: float = DEFAULT_SPEED_PPS
    bed_up: bool = DEFAULT_BED_UP
    kiosk: bool = DEFAULT_KIOSK
    # 0 = bed fully down, total_steps = fully up. Anything in between is a position
    # the user stopped at, from which the next move continues or reverses.
    position_steps: int = -1  # -1 means "derive from bed_up", see load() and _validate()
    path: str = field(default=CONFIG_FILE, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # runs for every construction path, not just load(), so position_steps is never
        # left on its sentinel
        self._validate()

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
                # .get, not [], so a config file written before kiosk mode existed keeps
                # its other values instead of falling into the except and resetting all
                kiosk=bool(data.get("kiosk", DEFAULT_KIOSK)),
                position_steps=int(data.get("position_steps", -1)),
                path=str(path),
            )
        except (ValueError, KeyError, OSError) as error:
            logger.warning("Could not read config %s (%s), using defaults", path, error)
            return cls(path=str(path))
        config._validate()
        return config

    def _validate(self) -> None:
        if self.position_steps < 0:
            # no stored position (fresh config, or one written before partial positions
            # existed): fall back to the coarse up/down flag
            self.position_steps = self.total_steps if self.bed_up else 0
        elif self.position_steps > self.total_steps:
            logger.warning(
                "position_steps %s above total_steps %s, clamping",
                self.position_steps, self.total_steps,
            )
            self.position_steps = self.total_steps
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
                "kiosk": self.kiosk,
                "position_steps": self.position_steps,
            },
            indent=2,
        )
        target = Path(self.path)
        temp = Path(str(target) + ".tmp")
        with self._lock:
            temp.write_text(payload)
            os.replace(temp, target)  # atomic on the same filesystem
