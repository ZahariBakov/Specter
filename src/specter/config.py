"""User settings stored as JSON in the OS config folder."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import List

from platformdirs import user_config_dir

log = logging.getLogger(__name__)

CONFIG_PATH = Path(user_config_dir("specter", appauthor=False)) / "config.json"

DEFAULT_HIDDEN_TILES = ["disk", "fan"]  # CPU, GPU, RAM and NET are shown by default


@dataclass
class Config:
    opacity: float = 0.85  # 0.2 .. 1.0
    interval_ms: int = 1000
    pos_x: int | None = None  # None = default corner
    pos_y: int | None = None
    width: int | None = None  # None = fit the content
    height: int | None = None
    hidden_tiles: List[str] = field(default_factory=lambda: list(DEFAULT_HIDDEN_TILES))
    first_tile: str | None = None  # tile the panel starts cycling from (when not all fit)
    locked: bool = False  # no moving or resizing
    topmost: bool = True  # always on top

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> Config:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.warning("Could not read %s, using defaults", path)
            return cls()
        if not isinstance(data, dict):
            log.warning("Unexpected content in %s, using defaults", path)
            return cls()
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.opacity = min(1.0, max(0.2, float(cfg.opacity)))
        cfg.interval_ms = max(250, int(cfg.interval_ms))
        if cfg.width is None or cfg.height is None:
            cfg.width = cfg.height = None
        else:  # the panel enlarges it to its minimum size if needed
            cfg.width, cfg.height = max(50, int(cfg.width)), max(50, int(cfg.height))
        if isinstance(cfg.hidden_tiles, list):
            cfg.hidden_tiles = [t for t in cfg.hidden_tiles if isinstance(t, str)]
        else:
            cfg.hidden_tiles = list(DEFAULT_HIDDEN_TILES)
        if not isinstance(cfg.first_tile, str):
            cfg.first_tile = None
        cfg.locked = bool(cfg.locked)
        cfg.topmost = bool(cfg.topmost)
        return cfg

    def save(self, path: Path = CONFIG_PATH) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            log.warning("Could not save config to %s", path)
