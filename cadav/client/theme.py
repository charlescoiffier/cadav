"""Look of the client: a dark violet Textual theme and the shared stylesheet.

Panels have rounded borders with their title inside the border, form fields are
one line high, and key hints live in the footer: everything is keyboard-first.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.theme import Theme

@dataclass(frozen=True)
class Palette:
    """Every colour of the interface. A light variant only needs another instance."""

    name: str
    dark: bool
    background: str
    surface: str  # highlights, fields
    panel: str
    border_dim: str
    foreground: str  # body text
    strong: str  # emphasised text
    muted: str  # hints, secondary text
    primary: str
    secondary: str
    accent: str
    success: str
    warning: str
    error: str


# Solarized (Ethan Schoonover), dark variant, with the canonical hex values.
SOLARIZED_DARK = Palette(
    name="cadav",
    dark=True,
    background="#002b36",  # base03
    surface="#073642",  # base02
    panel="#0b3f4d",
    border_dim="#1c5666",
    foreground="#839496",  # base0
    strong="#93a1a1",  # base1
    muted="#657b83",  # base00
    primary="#268bd2",  # blue
    secondary="#2aa198",  # cyan
    accent="#d33682",  # magenta
    success="#859900",  # green
    warning="#b58900",  # yellow
    error="#dc322f",  # red
)

PALETTE = SOLARIZED_DARK

BACKGROUND = PALETTE.background
SURFACE = PALETTE.surface
PANEL = PALETTE.panel
PRIMARY = PALETTE.primary
SECONDARY = PALETTE.secondary
ACCENT = PALETTE.accent
SUCCESS = PALETTE.success
WARNING = PALETTE.warning
ERROR = PALETTE.error
FOREGROUND = PALETTE.foreground
STRONG = PALETTE.strong
MUTED = PALETTE.muted


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
            "border": p.primary,
            "border-blurred": p.border_dim,
            "footer-key-foreground": p.background,
            "footer-key-background": p.primary,
            "footer-description-foreground": p.muted,
            "footer-background": p.surface,
            "input-selection-background": f"{p.primary} 50%",
            "block-cursor-background": p.primary,
            "block-cursor-foreground": p.background,
        },
    )


CADAV_THEME = build_theme(PALETTE)


def chip(label: str, bg: str, fg: str = BACKGROUND) -> Text:
    """A small coloured badge, like the method and status chips of Posting."""
    return Text(f" {label} ", style=f"bold {fg} on {bg}")


APP_CSS = f"""
Screen {{ background: $background; color: $foreground; }}

/* top bar */
TopBar {{ height: 1; dock: top; background: $surface; padding: 0 1; }}
TopBar #brand {{ width: 1fr; color: $secondary; text-style: bold; }}
TopBar #status {{ width: auto; color: {MUTED}; }}

/* footer: key chips on the left, muted descriptions */
Footer {{ background: $surface; }}
FooterKey {{ background: $surface; }}
FooterKey .footer-key--key {{ background: $primary; color: $background; text-style: bold; }}
FooterKey .footer-key--description {{ color: {MUTED}; background: $surface; }}

/* panels: rounded border, title in the border */
.pane {{
    border: round $primary 60%;
    border-title-color: $secondary;
    border-title-style: bold;
    border-subtitle-color: {MUTED};
    background: $background;
    padding: 0 1;
    height: auto;
}}
.pane:focus-within {{ border: round $secondary; }}

/* lists */
OptionList {{
    border: none; background: transparent; padding: 0; height: auto; min-height: 3; max-height: 12;
}}
OptionList:focus {{ border: none; }}
OptionList > .option-list--option {{ padding: 0 1; }}
OptionList > .option-list--option-highlighted {{ background: $primary 35%; color: $foreground; text-style: none; }}
OptionList:focus > .option-list--option-highlighted {{ background: $primary 60%; text-style: bold; }}
OptionList > .option-list--option-disabled {{ color: {MUTED}; }}

/* one-line form fields */
.frow {{ height: 1; margin-bottom: 1; }}
.flabel {{ width: 18; color: {MUTED}; }}
Input {{
    border: none; height: 1; padding: 0 1; background: $surface; width: 1fr; color: {STRONG};
}}
Input:focus {{ border: none; background: $primary 40%; }}
/* navigation mode: no cursor; editing mode: accent background and visible cursor */
NavInput > .input--cursor {{ background: transparent; color: {STRONG}; text-style: none; }}
NavInput.-editing > .input--cursor {{ background: $accent; color: $background; text-style: bold; }}
NavInput.-editing, NavInput.-editing:focus {{ background: $accent 35%; }}
Input.-invalid {{ border: none; }}
Input > .input--placeholder {{ color: {MUTED}; }}
Select {{ height: 1; width: 1fr; }}
Select > SelectCurrent {{ border: none; height: 1; padding: 0 1; background: $surface; color: {STRONG}; }}
Select:focus > SelectCurrent {{ border: none; background: $primary 40%; }}
SelectOverlay {{ border: round $primary; background: $surface; }}

/* compact buttons */
Button {{ min-width: 0; height: 1; border: none; padding: 0 2; margin-right: 1; background: $surface; color: $foreground; }}
Button:hover {{ background: $primary 40%; }}
Button:focus {{ background: $primary 60%; text-style: bold; }}
Button.-primary {{ background: $primary; color: $background; text-style: bold; }}
Button.-primary:hover, Button.-primary:focus {{ background: $secondary; }}
Button.-warning {{ background: $surface; color: $warning; }}
Button:disabled {{ opacity: 0.4; }}
.buttons {{ height: 1; margin-top: 1; }}

.muted {{ color: {MUTED}; }}
.error {{ color: $error; }}
"""
