"""Persistent configuration stored in a single JSON file.

Replaces the previous three plain-text files (steps.txt, speed.txt, position.txt).
"""

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = str(Path(__file__).resolve().parents[2] / "data" / "config.json")


@dataclass
class Config:
    total_steps: int = 28000
    speed_pps: float = 800.0
    bed_up: bool = False
    path: str = CONFIG_FILE

    @classmethod
    def load(cls, path=CONFIG_FILE):
        file = Path(path)
        if not file.exists():
            return cls(path=str(path))
        data = json.loads(file.read_text())
        return cls(
            total_steps=int(data["total_steps"]),
            speed_pps=float(data["speed_pps"]),
            bed_up=bool(data["bed_up"]),
            path=str(path),
        )

    def save(self):
        Path(self.path).write_text(
            json.dumps(
                {
                    "total_steps": self.total_steps,
                    "speed_pps": self.speed_pps,
                    "bed_up": self.bed_up,
                },
                indent=2,
            )
        )
