"""Local client configuration: pseudo, secret and server URL."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from cadav.storage import atomic_write_json

DEFAULT_URL = "ws://localhost:8765"


def default_config_path() -> Path:
    if env := os.environ.get("CADAV_CONFIG"):
        return Path(env)
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "cadav" / "config.json"


def new_secret() -> str:
    return secrets.token_hex(32)


@dataclass
class Config:
    pseudo: str = ""
    secret: str = ""
    url: str = DEFAULT_URL
    theme: str = ""  # name of a palette ("galaxy", "solarized-dark"); empty = default
    export_dir: str = ""  # where stories are saved; empty = a default folder

    @classmethod
    def load(cls, path: Path) -> Config:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(**{k: str(v) for k, v in data.items() if k in ("pseudo", "secret", "url", "theme", "export_dir")})

    def save(self, path: Path) -> None:
        atomic_write_json(path, asdict(self))  # temp files are created 0600: the secret stays private

    @property
    def registered(self) -> bool:
        return bool(self.pseudo and self.secret)
