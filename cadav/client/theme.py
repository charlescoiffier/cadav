"""Look of the client: colour palettes, the Textual theme and the shared stylesheet.

The default palette is the base theme of Posting ("galaxy"), the terminal app this
interface takes its cue from: rounded panels with the title in the border, one-line
fields, colour chips, everything reachable by keyboard. Solarized dark is available too.

All colours live in a :class:`Palette`; the stylesheet only uses theme variables, so a
new palette (a light one, later) needs no change anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from rich.text import Text
from textual.theme import Theme


@dataclass(frozen=True)
class Palette:
    name: str
    dark: bool
    background: str
    surface: str  # bars, fields
    panel: str
    border_dim: str  # border of a panel that does not have the focus
    foreground: str  # body text
    strong: str  # emphasised text
    muted: str  # labels, placeholders, hints
    primary: str
    secondary: str
    accent: str
    success: str
    warning: str
    error: str
    highlight: str  # selected row of a list that does not have the focus
    focus: str  # background of the element that has the focus (text is drawn in `background`)
    editing: str  # background of a field being edited


# Posting's default theme, "galaxy" (colours from its themes.py), with an orange accent and a few derived shades.
GALAXY = Palette(
    name="galaxy",
    dark=True,
    background="#0F0F1F",
    surface="#1E1E3F",
    panel="#2D2B55",
    border_dim="#4b4780",
    foreground="#e4e4f2",
    strong="#ffffff",
    muted="#a9a6d6",
    primary="#C45AFF",
    secondary="#a684e8",
    accent="#FF8C32",  # orange
    success="#00FA9A",
    warning="#FFD700",
    error="#FF4500",
    highlight="#4b2c7a",
    focus="#FF8C32",
    editing="#ffffff",
)

# Solarized (Ethan Schoonover), dark variant, canonical values.
SOLARIZED_DARK = Palette(
    name="solarized-dark",
    dark=True,
    background="#002b36",  # base03
    surface="#073642",  # base02
    panel="#0b3f4d",
    border_dim="#1c5666",
    foreground="#93a1a1",  # base1
    strong="#eee8d5",  # base2
    muted="#839496",  # base0
    primary="#268bd2",
    secondary="#2aa198",
    accent="#cb4b16",  # Solarized orange
    success="#859900",
    warning="#b58900",
    error="#dc322f",
    highlight="#0b4452",
    focus="#2aa198",
    editing="#eee8d5",
)

PALETTES = {p.name: p for p in (GALAXY, SOLARIZED_DARK)}
DEFAULT_PALETTE = GALAXY.name

# The palette in use, read at drawing time by the screens (Rich styles cannot use CSS variables).
colors = SimpleNamespace(**GALAXY.__dict__)


def use_palette(name: str) -> Palette:
    palette = PALETTES.get(name, GALAXY)
    colors.__dict__.update(palette.__dict__)
    return palette


def build_theme(p: Palette) -> Theme:
    return Theme(
        name=p.name,
        primary=p.primary,
        secondary=p.secondary,
        accent=p.accent,
        foreground=p.foreground,
        background=p.background,
        surface=p.surface,
        panel=p.panel,
        success=p.success,
        warning=p.warning,
        error=p.error,
        dark=p.dark,
        variables={
            "cadav-strong": p.strong,
            "cadav-muted": p.muted,
            "cadav-highlight": p.highlight,
            "cadav-focus": p.focus,
            "cadav-editing": p.editing,
            "cadav-on-color": p.background,
            "cadav-border-dim": p.border_dim,
            "border": p.primary,
            "border-blurred": p.border_dim,
            "footer-key-foreground": p.background,
            "footer-key-background": p.primary,
            "footer-description-foreground": p.foreground,
            "footer-background": p.surface,
            "input-selection-background": f"{p.primary} 50%",
            "block-cursor-background": p.focus,
            "block-cursor-foreground": p.background,
        },
    )


def chip(label: str, color: str, fg: str | None = None) -> Text:
    """A small coloured badge, like the method and status chips of Posting."""
    return Text(f" {label} ", style=f"bold {fg or colors.background} on {color}")


APP_CSS = """
Screen { background: $background; color: $foreground; }

/* top bar and footer */
TopBar { height: 1; dock: top; background: $surface; padding: 0 1; }
TopBar #brand { width: 1fr; color: $secondary; text-style: bold; }
TopBar #status { width: auto; color: $cadav-muted; }
Footer { background: $surface; }
FooterKey { background: $surface; }
FooterKey .footer-key--key { background: $primary; color: $cadav-on-color; text-style: bold; }
FooterKey .footer-key--description { color: $foreground; background: $surface; }

/* panels: rounded border with the title inside; heavy accent border when they hold the focus */
.pane {
    border: round $cadav-border-dim;
    border-title-color: $secondary;
    border-title-style: bold;
    border-subtitle-color: $cadav-muted;
    background: $background;
    padding: 0 1;
    height: auto;
}
.pane:focus-within { border: heavy $accent; border-title-color: $cadav-strong; }

/* lists: the row that has the focus is drawn in inverse video */
OptionList { border: none; background: transparent; padding: 0; height: auto; min-height: 3; max-height: 12; }
OptionList:focus { border: none; background: transparent; }
OptionList > .option-list--option { padding: 0 1; color: $foreground; }
OptionList > .option-list--option-highlighted { background: $cadav-highlight; color: $cadav-strong; text-style: none; }
OptionList:focus > .option-list--option-highlighted { background: $cadav-focus; color: $cadav-on-color; text-style: none; }
OptionList > .option-list--option-disabled { color: $cadav-muted; }

/* one-line form fields */
.frow { height: 1; margin-bottom: 1; }
.flabel { width: 18; color: $cadav-muted; }
Input { border: none; height: 1; padding: 0 1; background: $surface; width: 1fr; color: $cadav-strong; }
Input:focus { border: none; background: $cadav-focus; color: $cadav-on-color; text-style: bold; }
Input.-invalid, Input.-invalid:focus { border: none; }
Input > .input--placeholder { color: $cadav-muted; }
NavInput:focus > .input--placeholder { color: $cadav-on-color 75%; }
NavInput > .input--cursor { background: transparent; color: $cadav-strong; text-style: none; }
NavInput:focus > .input--cursor { background: transparent; color: $cadav-on-color; text-style: bold; }
NavInput.-editing, NavInput.-editing:focus { background: $cadav-editing; color: $cadav-on-color; text-style: none; }
NavInput.-editing > .input--cursor { background: $cadav-on-color; color: $cadav-editing; text-style: bold; }
Select { height: 1; width: 1fr; }
Select > SelectCurrent { border: none; height: 1; padding: 0 1; background: $surface; color: $cadav-strong; }
Select:focus > SelectCurrent { border: none; background: $cadav-focus; color: $cadav-on-color; text-style: bold; }
SelectCurrent .arrow { color: $cadav-muted; }
Select:focus > SelectCurrent .arrow { color: $cadav-on-color; }
SelectOverlay { border: round $accent; background: $surface; color: $foreground; }

/* compact buttons */
Button { min-width: 0; height: 1; border: none; padding: 0 2; margin-right: 1; background: $surface; color: $cadav-strong; text-style: none; }
Button:hover { background: $cadav-highlight; }
Button:focus { background: $cadav-focus; color: $cadav-on-color; text-style: bold; }
Button.-primary { background: $primary; color: $cadav-on-color; text-style: bold; }
Button.-primary:hover { background: $secondary; }
Button.-primary:focus { background: $cadav-focus; }
Button.-warning { background: $surface; color: $warning; }
Button.-warning:focus { background: $cadav-focus; color: $cadav-on-color; }
Button:disabled { opacity: 0.45; }
.buttons { height: 1; margin-top: 1; }

.muted { color: $cadav-muted; }
.error { color: $error; }
"""

CADAV_THEME = build_theme(GALAXY)
