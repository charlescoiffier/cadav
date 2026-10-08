"""Look of the client: a dark violet Textual theme and the shared stylesheet.

Panels have rounded borders with their title inside the border, form fields are
one line high, and key hints live in the footer: everything is keyboard-first.
"""

from __future__ import annotations

from rich.text import Text
from textual.theme import Theme

BACKGROUND = "#140a22"
SURFACE = "#1f1233"
PANEL = "#2a1a45"
PRIMARY = "#9b5de5"
SECONDARY = "#cf9bff"
ACCENT = "#f15bb5"
SUCCESS = "#3ddc97"
WARNING = "#ffb454"
ERROR = "#ff5c7a"
FOREGROUND = "#e9e1f5"
MUTED = "#8f7fb0"

CADAVRE_THEME = Theme(
    name="cadavre",
    primary=PRIMARY,
    secondary=SECONDARY,
    accent=ACCENT,
    foreground=FOREGROUND,
    background=BACKGROUND,
    surface=SURFACE,
    panel=PANEL,
    success=SUCCESS,
    warning=WARNING,
    error=ERROR,
    dark=True,
    variables={
        "border": PRIMARY,
        "border-blurred": "#4b2f78",
        "footer-key-foreground": BACKGROUND,
        "footer-key-background": PRIMARY,
        "footer-description-foreground": MUTED,
        "footer-background": SURFACE,
        "input-selection-background": "#9b5de5 50%",
        "block-cursor-background": PRIMARY,
        "block-cursor-foreground": BACKGROUND,
    },
)


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
    border: round $primary 70%;
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
    border: none; height: 1; padding: 0 1; background: $surface; width: 1fr;
}}
Input:focus {{ border: none; background: $primary 40%; }}
Input.-invalid {{ border: none; }}
Input > .input--placeholder {{ color: #6d5c8f; }}
Select {{ height: 1; width: 1fr; }}
Select > SelectCurrent {{ border: none; height: 1; padding: 0 1; background: $surface; }}
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
