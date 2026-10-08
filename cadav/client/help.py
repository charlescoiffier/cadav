"""Content of the help window (pure: the screen only displays what this module builds)."""

from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text

HELP_KEYS = "f1,ctrl+f"

_KEY_NAMES = {
    "escape": "Échap",
    "enter": "Entrée",
    "space": "Espace",
    "tab": "Tab",
    "shift+tab": "Maj+Tab",
    "shift": "Maj",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
    "backspace": "Retour arrière",
}


def key_label(key: str) -> str:
    """``ctrl+n`` -> ``Ctrl+N``, ``escape`` -> ``Échap``, ``f1`` -> ``F1``."""
    if key in _KEY_NAMES:
        return _KEY_NAMES[key]
    parts = [_KEY_NAMES.get(p, p.capitalize() if len(p) > 1 else p.upper()) for p in key.split("+")]
    return "+".join(parts)


def binding_label(keys: str, key_display: str | None = None) -> str:
    """Display of a binding that may list several keys (``"f1,ctrl+f"`` -> ``F1 ou Ctrl+F``)."""
    if key_display:
        return key_display
    return " ou ".join(key_label(k) for k in keys.split(","))


def shortcut_rows(bindings: Iterable[tuple[str, str, str | None]]) -> list[tuple[str, str]]:
    """``(keys, description, key_display)`` -> ``(label, description)``: one row per description,
    several keys for the same action are joined (``F1 ou Ctrl+F``)."""
    rows: dict[str, list[str]] = {}
    for keys, description, key_display in bindings:
        if not description:
            continue
        label = binding_label(keys, key_display)
        labels = rows.setdefault(description, [])
        if label not in labels:
            labels.append(label)
    return [(" ou ".join(labels), description) for description, labels in rows.items()]


GAME_RULES = [
    "Chacun écrit une seule fois, à son tour, une partie de l'histoire commune.",
    "Tu ne vois que l'amorce laissée par le joueur précédent (sa dernière phrase, ses derniers mots, ou rien).",
    "Si le temps d'un tour est écoulé, le joueur est sauté : le suivant voit la même amorce.",
    "À la fin, l'histoire complète est révélée à tous, chaque morceau attribué à son auteur.",
]

KEYBOARD = [
    ("↑ ↓ ← →  ·  Tab / Maj+Tab", "passer d'un élément à l'autre"),
    ("Entrée  ·  Espace", "modifier le champ, ouvrir le choix ou la ligne sélectionnée"),
    ("Taper un texte, un chiffre", "sur un champ : commence la saisie (elle remplace le contenu) ; sur un choix : saute à l'option"),
    ("Entrée (en saisie)", "valide et passe à l'élément suivant"),
    ("Échap (en saisie)", "annule et rétablit l'ancienne valeur"),
    ("Dans un menu ouvert", "↑ ↓ pour parcourir, Entrée ou Espace pour valider, Échap pour refermer"),
]


def render_help(
    place: str,
    shortcuts: list[tuple[str, str]],
    version: str,
    config_path: str,
    export_dir: str,
    theme: str,
    muted: str,
    accent: str,
    secondary: str,
) -> Text:
    """The whole help text. Colours are passed in so that the palette in use decides them."""
    text = Text()

    def title(label: str) -> None:
        if text.plain:
            text.append("\n")
        text.append(f"{label}\n", style=f"bold {secondary}")

    title("Le jeu")
    for line in GAME_RULES:
        text.append("• ", style=accent)
        text.append(f"{line}\n")

    title("Au clavier")
    for keys, what in KEYBOARD:
        text.append(f"{keys}\n", style="bold")
        text.append(f"    {what}\n", style=muted)

    title(f"Raccourcis de cet écran ({place})")
    if shortcuts:
        width = max(len(label) for label, _ in shortcuts)
        for label, description in shortcuts:
            text.append(f"{label:<{width}}", style=f"bold {accent}")
            text.append(f"  {description}\n")
    else:
        text.append("Aucun raccourci particulier.\n", style=muted)

    title("Cette installation")
    for label, value in (
        ("Version", version),
        ("Configuration", config_path),
        ("Dossier d'export", export_dir or "(par défaut)"),
        ("Palette", theme),
    ):
        text.append(f"{label:<17}", style=muted)
        text.append(f"{value}\n")
    text.append("\nÉchap ou F1 pour fermer cette fenêtre.\n", style=muted)
    return text
