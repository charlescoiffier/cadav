"""Pure helpers for the client: form parsing and display text (no Textual, no network)."""

from __future__ import annotations

import re

from pydantic import ValidationError

from cadavre.protocol import (
    DEFAULT_PRIMER_WORDS,
    MAX_TURN_SECONDS,
    MIN_TURN_SECONDS,
    GameSettings,
    GameView,
    LobbyEntry,
    PrimerMode,
    Visibility,
)

QUICK_SECONDS = 2 * 60
RELAXED_SECONDS = 24 * 3600

_UNITS = {"s": 1, "m": 60, "min": 60, "h": 3600, "j": 86400, "d": 86400}
_DURATION_RE = re.compile(r"^\s*(\d+)\s*([a-z]*)\s*$", re.IGNORECASE)


def parse_duration(text: str) -> int:
    """``"45s"``, ``"10 min"``, ``"36h"``, ``"2j"``; a bare number means minutes. Returns seconds."""
    match = _DURATION_RE.match(text)
    if not match or (match.group(2).lower() not in _UNITS and match.group(2) != ""):
        raise ValueError("Durée illisible : écris par exemple 90s, 10min, 36h ou 2j.")
    unit = _UNITS[match.group(2).lower()] if match.group(2) else 60
    seconds = int(match.group(1)) * unit
    if not MIN_TURN_SECONDS <= seconds <= MAX_TURN_SECONDS:
        raise ValueError("La durée d'un tour doit être comprise entre 30 secondes et 72 heures.")
    return seconds


def format_duration(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def _optional_int(text: str, label: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    if not text.isdigit() or int(text) < 1:
        raise ValueError(f"{label} : entre un nombre entier supérieur à 0.")
    return int(text)


def build_settings(
    *,
    visibility: str,
    players: int,
    deadline: str,
    custom_deadline: str = "",
    theme: str = "",
    primer_mode: str = PrimerMode.LAST_SENTENCE,
    primer_words: str = "",
    min_words: str = "",
    max_words: str = "",
) -> GameSettings:
    """Turn raw form values into validated settings; raises ``ValueError`` with a French message."""
    if deadline == "quick":
        seconds = QUICK_SECONDS
    elif deadline == "relaxed":
        seconds = RELAXED_SECONDS
    else:
        seconds = parse_duration(custom_deadline)
    lo, hi = _optional_int(min_words, "Mots minimum"), _optional_int(max_words, "Mots maximum")
    if lo is not None and hi is not None and lo > hi:
        raise ValueError("Le minimum de mots ne peut pas dépasser le maximum.")
    words = _optional_int(primer_words, "Nombre de mots de l'amorce") or DEFAULT_PRIMER_WORDS
    if words > 100:
        raise ValueError("L'amorce peut contenir 100 mots au plus.")
    try:
        return GameSettings(
            visibility=Visibility(visibility),
            desired_players=players,
            turn_seconds=seconds,
            theme=theme.strip() or None,
            primer_mode=PrimerMode(primer_mode),
            primer_words=words,
            min_words=lo,
            max_words=hi,
        )
    except ValidationError as exc:  # e.g. theme too long
        raise ValueError("Réglages invalides : vérifie le formulaire.") from exc


def primer_text(settings: GameSettings) -> str:
    if settings.primer_mode is PrimerMode.NONE:
        return "aucune"
    if settings.primer_mode is PrimerMode.LAST_WORDS:
        return f"{settings.primer_words} derniers mots"
    return "dernière phrase"


def words_text(settings: GameSettings) -> str:
    lo, hi = settings.min_words, settings.max_words
    if lo and hi:
        return f"{lo} à {hi} mots"
    if lo:
        return f"au moins {lo} mots"
    if hi:
        return f"au plus {hi} mots"
    return "libre"


def describe_settings(settings: GameSettings) -> list[str]:
    return [
        f"Thème : {settings.theme or 'aucun'}",
        f"Visibilité : {'publique' if settings.visibility is Visibility.PUBLIC else 'privée'}",
        f"Durée d'un tour : {format_duration(settings.turn_seconds)}",
        f"Amorce : {primer_text(settings)}",
        f"Longueur : {words_text(settings)}",
    ]


def lobby_label(entry: LobbyEntry) -> str:
    theme = entry.theme or "Sans thème"
    return (
        f"{theme} — {entry.players}/{entry.desired_players} joueurs"
        f" · tour {format_duration(entry.turn_seconds)} · hôte {entry.host}"
    )


def my_game_label(view: GameView) -> str:
    theme = view.settings.theme or "Sans thème"
    count = f"{len(view.players)}/{view.settings.desired_players}"
    if view.status == "waiting":
        state = f"en attente ({count})"
    elif view.status == "running":
        state = "à toi !" if view.my_turn else f"tour de {view.current_player}"
    else:
        state = "terminée"
    return f"{'★ ' if view.my_turn else ''}{theme} — {state}"
