"""Turning a finished story into text, files and clipboard content (pure, apart from the I/O helpers)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from datetime import date
from pathlib import Path

from cadav.protocol import GameView
from cadav.storage import atomic_write_text

MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]  # fmt: skip

FORMATS = {"md": "Markdown (.md)", "txt": "Texte brut (.txt)"}


def french_date(d: date) -> str:
    return f"{d.day}{'er' if d.day == 1 else ''} {MONTHS[d.month - 1]} {d.year}"


def story_title(view: GameView) -> str:
    return view.settings.theme or "Cadavre exquis"


def authors(view: GameView) -> list[str]:
    """Authors in writing order, each once."""
    seen: list[str] = []
    for part in view.story or []:
        if part.author not in seen:
            seen.append(part.author)
    return seen


def _byline(view: GameView, when: date) -> str:
    names = authors(view)
    who = ", ".join(names) if names else "personne"
    return f"Cadavre exquis écrit le {french_date(when)} par {who}."


def render_text(view: GameView, when: date) -> str:
    """Plain text: title, byline, then each contribution under its author."""
    title = story_title(view)
    lines = [title, "=" * len(title), "", _byline(view, when), ""]
    parts = view.story or []
    if not parts:
        lines += ["Personne n'a écrit.", ""]
    for part in parts:
        lines += [f"— {part.author} —", part.text, ""]
    if view.skipped:
        lines += ["Tours sautés : " + ", ".join(view.skipped), ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_markdown(view: GameView, when: date) -> str:
    """Markdown: a title, an italic byline, then each contribution under its author in bold."""
    lines = [f"# {story_title(view)}", "", f"*{_byline(view, when)}*", ""]
    parts = view.story or []
    if not parts:
        lines += ["Personne n'a écrit.", ""]
    for part in parts:
        lines += [f"**{part.author}**", "", part.text.replace("\n", "  \n"), ""]
    if view.skipped:
        lines += [f"*Tours sautés : {', '.join(view.skipped)}.*", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def render(view: GameView, fmt: str, when: date) -> str:
    return render_markdown(view, when) if fmt == "md" else render_text(view, when)


def slug(text: str, limit: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:limit].strip("-")


def export_filename(view: GameView, fmt: str, when: date) -> str:
    name = slug(view.settings.theme or "") or "histoire"
    return f"cadav-{name}-{when.isoformat()}.{fmt}"


def unique_path(directory: Path, filename: str) -> Path:
    """``directory/filename``, or the first free ``name-2.ext``, ``name-3.ext``... (never overwrites)."""
    path = directory / filename
    stem, suffix = path.stem, path.suffix
    n = 2
    while path.exists():
        path = directory / f"{stem}-{n}{suffix}"
        n += 1
    return path


def default_export_dir() -> str:
    home = Path.home()
    return str(home / "Documents" / "cadav" if (home / "Documents").is_dir() else home / "cadav")


def save_story(view: GameView, fmt: str, directory: str | Path, when: date) -> Path:
    """Write the story in ``directory`` (created if needed) and return the file's path."""
    folder = Path(os.path.expanduser(str(directory)))
    path = unique_path(folder, export_filename(view, fmt, when))
    atomic_write_text(path, render(view, fmt, when))
    return path


_CLIPBOARD_TOOLS = {
    "darwin": [["pbcopy"]],
    "win32": [["clip"]],
    "linux": [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]],
}


def copy_with_system_tool(
    text: str,
    run: Callable = subprocess.run,
    which: Callable = shutil.which,
    platform: str = sys.platform,
) -> str | None:
    """Copy through the first clipboard command found; returns its name, or ``None`` if none worked."""
    key = "linux" if platform.startswith("linux") else platform
    for command in _CLIPBOARD_TOOLS.get(key, []):
        if which(command[0]) is None:
            continue
        try:
            run(command, input=text.encode("utf-8"), check=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        return command[0]
    return None
