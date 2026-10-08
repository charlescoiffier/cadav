"""Keyboard-first widgets.

Everything can be reached with the arrows or Tab. A field is *entered* with Enter or
Space, left with Esc (changes dropped) or Enter (changes kept). Outside of editing, the
arrows and the letters of the screen shortcuts are never swallowed by a field.
"""

from __future__ import annotations

import time

from textual import events, on
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, OptionList, Select
from textual.widgets._select import SelectCurrent, SelectOverlay

_INPUT_ACTIONS = {b.action.split("(")[0] for b in Input.BINDINGS if isinstance(b, Binding)}


class NavInput(Input):
    """A one-line field with two modes: navigation (default) and editing."""

    BINDINGS = [
        Binding("enter", "begin_edit", "Modifier"),
        Binding("space", "begin_edit", "Modifier", show=False),
        Binding("enter", "commit_edit", "Valider"),
        Binding("escape", "cancel_edit", "Annuler"),
        Binding("up,down", "ignore", "Ignorer", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("select_on_focus", False)
        super().__init__(*args, **kwargs)
        self.editing = False
        self._backup = ""

    # --- modes -------------------------------------------------------------

    def begin_edit(self) -> None:
        if self.editing:
            return
        self.editing = True
        self._backup = self.value
        self.add_class("-editing")
        self.cursor_position = len(self.value)
        self.refresh_bindings()

    def _end_edit(self) -> None:
        self.editing = False
        self.remove_class("-editing")
        self.refresh_bindings()

    def action_begin_edit(self) -> None:
        self.begin_edit()

    async def action_commit_edit(self) -> None:
        self._end_edit()
        await super().action_submit()
        self.screen.focus_next()  # validated: on to the next element

    def action_cancel_edit(self) -> None:
        self.value = self._backup
        self._end_edit()

    def action_ignore(self) -> None:
        """Up and down do nothing while a value is being typed."""

    async def action_submit(self) -> None:  # replaced by begin_edit / commit_edit
        return None

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "begin_edit":
            return not self.editing
        if action in ("commit_edit", "cancel_edit", "ignore"):
            return self.editing
        if action == "submit":
            return False
        if action in _INPUT_ACTIONS:
            return self.editing  # cursor keys, delete, paste... only while editing
        return super().check_action(action, parameters)


    # --- events ------------------------------------------------------------

    # Textual calls the handlers of every class in the MRO, so these *add* to Input's own
    # handlers: ``prevent_default`` is how a subclass switches the Input ones off, and the event
    # still bubbles up to the app, which is where screen shortcuts and arrow bindings are checked.

    def _on_key(self, event: events.Key) -> None:
        if self.editing:
            return
        if event.is_printable and event.key != "space":
            # Spreadsheet-style: typing on a cell replaces its content (Esc brings the old one back).
            self.begin_edit()
            self.value = ""
            self.cursor_position = 0
        else:
            event.prevent_default()

    def _on_paste(self, event: events.Paste) -> None:
        if not self.editing:
            event.prevent_default()
            event.stop()

    def _on_click(self, event: events.Click) -> None:
        self.begin_edit()

    def _on_blur(self, event: events.Blur) -> None:
        if self.editing:
            self._end_edit()  # leaving the field keeps what was typed


class NavSelectOverlay(SelectOverlay):
    """The menu of a NavSelect: Space validates the highlighted option, like Enter."""

    BINDINGS = [Binding("space", "select", "Valider", show=False)]

    def _on_key(self, event: events.Key) -> None:
        if event.key == "space":
            event.prevent_default()  # not a search character: the binding above handles it

    def check_consume_key(self, key: str, character: str | None = None) -> bool:
        return key != "space" and super().check_consume_key(key, character)


class NavSelect(Select, inherit_bindings=False):
    """A choice field: Enter or Space opens the menu; up and down keep moving between fields.

    Typing a letter or a digit jumps to the first option that starts with it.
    """

    BINDINGS = [Binding("enter,space", "show_overlay", "Choisir")]

    @on(SelectOverlay.UpdateSelection)
    def _chosen(self, event: SelectOverlay.UpdateSelection) -> None:
        # Textual's own handler (run just after) applies the choice and refocuses the select:
        # once it is done, move on to the next element.
        self.call_after_refresh(self._move_on)

    def _move_on(self) -> None:
        screen = self.screen
        chooser = getattr(screen, "focus_after_choice", None)
        target = chooser(self) if chooser else None
        if target is not None:
            target.focus()
        else:
            screen.focus_next()

    def compose(self):
        yield SelectCurrent(self.prompt)
        yield NavSelectOverlay(type_to_search=self._type_to_search).data_bind(compact=Select.compact)

    _query = ""
    _query_time = 0.0

    def _on_key(self, event: events.Key) -> None:
        if not event.is_printable or event.key == "space":
            return
        now = time.monotonic()
        if now - self._query_time > 1.0:
            self._query = ""  # a pause starts a new search
        self._query_time = now
        self._query += (event.character or "").casefold()
        for label, value in self._options:
            if value is self.NULL:
                continue
            if str(label).casefold().startswith(self._query) or str(value).casefold() == self._query:
                self.value = value
                break
        event.stop()


class NavOptionList(OptionList):
    """A list that hands the focus over at its edges, so the arrows never trap the user."""

    BINDINGS = [
        Binding("space", "select", "Ouvrir", show=False),
        Binding("left", "hand_over(-1)", "Précédent", show=False),
        Binding("right", "hand_over(1)", "Suivant", show=False),
    ]

    def _enabled(self) -> list[int]:
        return [i for i, o in enumerate(self.options) if not o.disabled]

    def action_hand_over(self, direction: int) -> None:
        (self.screen.focus_next if direction > 0 else self.screen.focus_previous)()

    def action_cursor_up(self) -> None:
        enabled = self._enabled()
        if not enabled or self.highlighted is None or self.highlighted <= enabled[0]:
            self.screen.focus_previous()
        else:
            super().action_cursor_up()

    def action_cursor_down(self) -> None:
        enabled = self._enabled()
        if not enabled or self.highlighted is None or self.highlighted >= enabled[-1]:
            self.screen.focus_next()
        else:
            super().action_cursor_down()

    def _on_focus(self, event: events.Focus) -> None:
        enabled = self._enabled()
        if enabled and self.highlighted is None:
            self.highlighted = enabled[0]


class NavScroll(VerticalScroll):
    """A scrollable area that hands the focus over once it cannot scroll any further."""

    BINDINGS = [
        Binding("left", "hand_over(-1)", "Précédent", show=False),
        Binding("right", "hand_over(1)", "Suivant", show=False),
    ]

    def action_hand_over(self, direction: int) -> None:
        (self.screen.focus_next if direction > 0 else self.screen.focus_previous)()

    def action_scroll_up(self) -> None:
        if self.scroll_y <= 0:
            self.screen.focus_previous()
        else:
            super().action_scroll_up()

    def action_scroll_down(self) -> None:
        if self.scroll_y >= self.max_scroll_y:
            self.screen.focus_next()
        else:
            super().action_scroll_down()
