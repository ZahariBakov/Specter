"""User settings stored as JSON in the OS config folder."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from platformdirs import user_config_dir

log = logging.getLogger(__name__)

CONFIG_PATH = Path(user_config_dir("specter", appauthor=False)) / "config.json"


@dataclass
class Config:
    opacity: float = 0.85  # 0.2 .. 1.0
    interval_ms: int = 1000
    pos_x: int | None = None  # None = default corner
    pos_y: int | None = None

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> Config:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.warning("Could not read %s, using defaults", path)
            return cls()
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.opacity = min(1.0, max(0.2, float(cfg.opacity)))
        cfg.interval_ms = max(250, int(cfg.interval_ms))
        return cfg

    def save(self, path: Path = CONFIG_PATH) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            log.warning("Could not save config to %s", path)
