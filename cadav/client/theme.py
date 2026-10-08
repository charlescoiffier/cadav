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
    foreground: str | None  # body text; None = let Textual pick a readable text colour
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


# Posting's default theme, "galaxy": the colours below are those of its themes.py (primary, secondary,
# warning, error, success, accent, background, surface, panel), without any change. The remaining
# fields are shades derived from them (no text colour: Textual computes it, as it does for Posting).
GALAXY = Palette(
    name="galaxy",
    dark=True,
    background="#0F0F1F",
    surface="#1E1E3F",
    panel="#2D2B55",
    border_dim="#572d79",  # primary at 40% over the background
    foreground=None,
    strong="#ffffff",
    muted="#9f9fa5",  # white at 60%
    primary="#C45AFF",
    secondary="#a684e8",
    accent="#FF69B4",
    success="#00FA9A",
    warning="#FFD700",
    error="#FF4500",
    highlight="#4b2c7a",
    focus="#FF69B4",  # the accent
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
            "cadav-text": "auto 87%" if p.foreground is None else p.foreground,
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
            "footer-description-foreground": "auto 87%" if p.foreground is None else p.foreground,
            "footer-background": "transparent",
            "input-cursor-background": p.primary,
            "input-selection-background": f"{p.primary} 50%",
            "block-cursor-background": p.focus,
            "block-cursor-foreground": p.background,
        },
    )


def chip(label: str, color: str, fg: str | None = None) -> Text:
    """A small coloured badge, like the method and status chips of Posting."""
    return Text(f" {label} ", style=f"bold {fg or colors.background} on {color}")


APP_CSS = """
Screen { background: $background; color: $cadav-text; }

/* top bar and footer */
TopBar { height: 1; dock: top; background: $surface; padding: 0 1; }
TopBar #brand { width: 1fr; color: $secondary; text-style: bold; }
TopBar #status { width: auto; color: $cadav-muted; }
Footer { background: $footer-background; }
FooterKey { background: $footer-background; }
FooterKey .footer-key--key { background: $primary; color: $cadav-on-color; text-style: bold; }
FooterKey .footer-key--description { color: $cadav-text; background: $footer-background; }

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
OptionList > .option-list--option { padding: 0 1; color: $cadav-text; }
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
SelectOverlay { border: round $accent; background: $surface; color: $cadav-text; }

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

/* multi-line text */
TextArea { border: none; background: $surface; color: $cadav-strong; padding: 0 1; }
TextArea:focus { border: none; background: $surface; }
TextArea > .text-area--cursor { background: $cadav-focus; color: $cadav-on-color; text-style: bold; }
TextArea > .text-area--cursor-line { background: $cadav-highlight; }
TextArea > .text-area--selection { background: $primary 50%; }
TextArea > .text-area--placeholder { color: $cadav-muted; }

.muted { color: $cadav-muted; }
.error { color: $error; }
"""

CADAV_THEME = build_theme(GALAXY)
