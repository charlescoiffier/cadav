"""JSON persistence with atomic writes. No database.

Layout under the data directory::

    users.json                 accounts
    games/<id>.json            games in progress (waiting or running)
    archive/<date>-<id>.json   finished games
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from cadav.game import Game

log = logging.getLogger("cadav.storage")


def atomic_write_json(path: Path, data: Any) -> None:
    """Write ``data`` to ``path`` so that readers see the old or the new file, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class Storage:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.users_path = self.root / "users.json"
        self.games_dir = self.root / "games"
        self.archive_dir = self.root / "archive"

    # --- users -------------------------------------------------------------

    def load_users(self) -> dict[str, dict[str, str]]:
        try:
            return json.loads(self.users_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def save_users(self, users: dict[str, dict[str, str]]) -> None:
        atomic_write_json(self.users_path, users)

    # --- games in progress -------------------------------------------------

    def save_game(self, game: Game) -> None:
        atomic_write_json(self.games_dir / f"{game.id}.json", game.model_dump(mode="json"))

    def delete_game(self, game_id: str) -> None:
        try:
            (self.games_dir / f"{game_id}.json").unlink()
        except FileNotFoundError:
            pass

    def load_games(self) -> list[Game]:
        return self._load_dir(self.games_dir.glob("*.json"))

    # --- archive -----------------------------------------------------------

    def archive_game(self, game: Game, when: datetime) -> None:
        name = f"{when.date().isoformat()}-{game.id}.json"
        atomic_write_json(self.archive_dir / name, game.model_dump(mode="json"))
        self.delete_game(game.id)

    def load_archived_since(self, since: date) -> list[Game]:
        """Archived games finished on or after ``since`` (the date is in the file name)."""
        paths = []
        for path in self.archive_dir.glob("*.json"):
            try:
                finished = date.fromisoformat(path.name[:10])
            except ValueError:
                continue
            if finished >= since:
                paths.append(path)
        return self._load_dir(paths)

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _load_dir(paths) -> list[Game]:
        games = []
        for path in sorted(paths):
            try:
                games.append(Game.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                # One corrupt file must not prevent the server from starting.
                log.exception("ignoring unreadable game file %s", path)
        return games
