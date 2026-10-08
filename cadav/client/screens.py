"""Screens: login, lobby, game creation and waiting room."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, OptionList, Select, Static, TextArea
from textual.widgets.option_list import Option

from cadav.client.config import DEFAULT_URL
from cadav.client.logic import (
    build_settings,
    describe_settings,
    format_duration,
    format_remaining,
    primer_help,
    turn_position,
    word_status,
)
from cadav import __version__
from cadav.client import export
from cadav.client.widgets import NavInput, NavOptionList, NavScroll, NavSelect
from cadav.client.theme import chip, colors
from cadav.protocol import (
    MIN_PLAYERS,
    CreateGame,
    GameStatus,
    GameView,
    JoinGame,
    LeaveGame,
    LobbyEntry,
    StartGame,
    SubmitText,
    Visibility,
)

def state_text(state: str) -> tuple[str, str, str]:
    """Dot, colour and label of a connection state."""
    return {
        "connecting": ("○", colors.warning, "Connexion…"),
        "online": ("●", colors.success, "Connecté"),
        "offline": ("○", colors.error, "Hors ligne, nouvelle tentative…"),
        "replaced": ("○", colors.error, "Connecté depuis un autre terminal"),
        "outdated": ("○", colors.error, "Client trop ancien"),
    }.get(state, ("○", colors.muted, state))


class TopBar(Horizontal):
    """One-line header: app name and place on the left, ``pseudo@server ● state`` on the right."""

    def __init__(self, place: str) -> None:
        super().__init__()
        self.place = place

    def compose(self) -> ComposeResult:
        yield Static("", id="brand")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.refresh_bar()

    def refresh_bar(self) -> None:
        app = self.app
        self.query_one("#brand", Static).update(
            Text.assemble(("cadav", "bold"), (f"\u00a0{__version__}", colors.muted), (f"\u00a0\u00a0\u00a0›\u00a0\u00a0\u00a0{self.place}", colors.muted))
        )
        dot, color, label = state_text(app.status)
        server = app.config.url.split("://", 1)[-1]
        who = f"{app.pseudo}@{server}  " if app.pseudo else ""
        self.query_one("#status", Static).update(Text.assemble(who, (f"{dot} {label}", color)))


class Banner(Static):
    """A discreet one-line notice about what happens in the other games."""

    DEFAULT_CSS = """
    Banner { height: 1; padding: 0 1; background: $surface; color: $warning; display: none; }
    """

    def refresh_banner(self) -> None:
        text = self.app.banner
        self.display = bool(text)
        self.update(Text.assemble(("● ", colors.warning), text) if text else "")


def _field(label: str, widget, row_id: str | None = None) -> Horizontal:
    return Horizontal(Static(label, classes="flabel"), widget, classes="frow", id=row_id)


def _set_options(widget: OptionList, items: list[tuple[str | None, Text]], empty: str) -> None:
    """Rebuild an option list only if its content changed (keeps the highlight otherwise)."""
    options = [Option(label, id=ident) for ident, label in items]
    if not options:
        options = [Option(Text(empty, style=colors.muted), disabled=True)]
    current = [(o.id, str(o.prompt)) for o in widget.options]
    if current == [(o.id, str(o.prompt)) for o in options]:
        return
    highlighted = widget.highlighted
    widget.clear_options()
    widget.add_options(options)
    if items and highlighted is not None:
        widget.highlighted = min(highlighted, len(items) - 1)
    elif items:
        widget.highlighted = 0


def my_game_prompt(view: GameView) -> Text:
    theme = view.settings.theme or "Sans thème"
    if view.status == GameStatus.WAITING:
        badge = chip("ATTENTE", colors.primary)
        info = f"{len(view.players)}/{view.settings.desired_players} joueurs"
    elif view.status == GameStatus.RUNNING:
        badge = chip("À TOI", colors.warning) if view.my_turn else chip("EN COURS", colors.secondary)
        info = "c'est ton tour" if view.my_turn else f"tour de {view.current_player}"
    else:
        badge = chip("TERMINÉE", colors.success)
        info = "lire et garder l'histoire"
    return Text.assemble(badge, " ", (theme, "bold"), "\n", info)


def public_game_prompt(entry: LobbyEntry) -> Text:
    return Text.assemble(
        (entry.theme or "Sans thème", "bold"),
        "\n",
        (
            f"{entry.players}/{entry.desired_players} joueurs · tour {format_duration(entry.turn_seconds)}"
            f" · hôte {entry.host}"
        ),
    )


class LoginScreen(Screen):
    CSS = """
    LoginScreen { align: center middle; }
    #login-card { width: 64; max-width: 100%; padding: 1 2; }
    #logo { text-align: center; color: $secondary; text-style: bold; margin-bottom: 1; }
    #tagline { text-align: center; margin-bottom: 1; }
    """

    def __init__(self, error: str = "") -> None:
        super().__init__()
        self._error = error

    def compose(self) -> ComposeResult:
        config = self.app.config
        with Vertical(id="login-card", classes="pane") as card:
            card.border_title = "Connexion"
            yield Static("░▒▓   c a d a v   ▓▒░", id="logo")
            yield Static(
                "Le cadavre exquis en terminal.\nChoisis un pseudo, sans mot de passe : un secret est créé et gardé sur cet ordinateur.",
                id="tagline",
                classes="muted",
            )
            yield _field("Pseudo", NavInput(value=config.pseudo, placeholder="2 à 24 caractères", id="pseudo", max_length=24))
            yield _field("Serveur", NavInput(value=config.url or DEFAULT_URL, id="server"))
            yield Static(self._error, id="login-error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Entrer", id="connect", variant="primary")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.query_one("#pseudo", Input).focus()

    def show_error(self, message: str) -> None:
        self.query_one("#login-error", Static).update(message)

    def _submit(self) -> None:
        pseudo = self.query_one("#pseudo", Input).value.strip()
        url = self.query_one("#server", Input).value.strip() or DEFAULT_URL
        if not pseudo:
            self.show_error("Choisis un pseudo.")
            return
        self.show_error("")
        self.app.begin_login(pseudo, url)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._submit()


class LobbyScreen(Screen):
    ready = False
    BINDINGS = [
        Binding("ctrl+n", "create", "Nouvelle partie"),
        Binding("ctrl+k", "focus_code", "Code"),
    ]
    CSS = """
    #lobby-body { height: auto; padding: 0 2; }
    #mine-pane, #public-pane { width: 1fr; height: auto; max-height: 100%; }
    #mine-pane { margin-right: 1; }
    #join-pane { margin: 1 2 0 2; height: auto; }
    #join-pane Input { width: 24; margin-right: 1; }
    #join-pane .actions { width: 1fr; height: 1; align-horizontal: right; }
    """

    def compose(self) -> ComposeResult:
        yield TopBar("Lobby")
        yield Banner()
        with Horizontal(id="lobby-body"):
            with Vertical(id="mine-pane", classes="pane") as mine:
                mine.border_title = "Mes parties"
                yield NavOptionList(id="my-games")
            with Vertical(id="public-pane", classes="pane") as public:
                public.border_title = "Parties publiques"
                yield NavOptionList(id="public-games")
        with Horizontal(id="join-pane", classes="pane") as join:
            join.border_title = "Rejoindre avec un code"
            yield NavInput(placeholder="CODE", id="code", max_length=5)
            yield Button("Rejoindre", id="join-code")
            with Horizontal(classes="actions"):
                yield Button("Créer une partie", id="create", variant="primary")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.ready = True
        self.query_one("#my-games", OptionList).focus()
        self.refresh_view()

    def on_screen_resume(self) -> None:
        # Back from another screen: put the focus on a list so that the shortcuts (n, c) work.
        self.query_one("#my-games", OptionList).focus()

    def refresh_view(self) -> None:
        app = self.app
        self.query_one(TopBar).refresh_bar()
        self.query_one(Banner).refresh_banner()
        _set_options(
            self.query_one("#my-games", OptionList),
            [(v.game_id, my_game_prompt(v)) for v in app.games.values()],
            "Aucune partie : Ctrl+N pour en créer une.",
        )
        _set_options(
            self.query_one("#public-games", OptionList),
            [(e.game_id, public_game_prompt(e)) for e in app.lobby if e.game_id not in app.games],
            "Aucune partie publique en attente.",
        )
        self.query_one("#mine-pane").border_subtitle = f"{len(app.games)}/5" if app.games else ""

    def action_create(self) -> None:
        self.app.push_screen(CreateScreen())

    def action_focus_code(self) -> None:
        code = self.query_one("#code", NavInput)
        code.focus()
        code.begin_edit()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        game_id = event.option.id
        if game_id is None:
            return
        if event.option_list.id == "public-games":
            await self.app.send(JoinGame(game_id=game_id))
            return
        self.app.open_game(game_id)

    async def _join_code(self) -> None:
        code = self.query_one("#code", Input).value.strip()
        if not code:
            self.app.notify("Saisis le code de la partie.", severity="warning")
            return
        await self.app.send(JoinGame(code=code))
        self.query_one("#code", Input).value = ""
        self.query_one("#my-games", OptionList).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            self.action_create()
        elif event.button.id == "join-code":
            await self._join_code()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "code":
            await self._join_code()


class CreateScreen(Screen):
    BINDINGS = [
        Binding("ctrl+s", "submit", "Créer la partie"),
        Binding("escape", "back", "Annuler"),
    ]
    CSS = """
    #create-body { height: auto; padding: 0 2; }
    #form-pane, #rules-pane { width: 1fr; height: auto; }
    #form-pane { margin-right: 1; }
    #form-error { height: auto; }
    """

    def compose(self) -> ComposeResult:
        yield TopBar("Nouvelle partie")
        with Horizontal(id="create-body"):
            with Vertical(id="form-pane", classes="pane") as form:
                form.border_title = "Partie"
                yield _field(
                    "Visibilité",
                    NavSelect(
                        [("Publique (dans la liste)", "public"), ("Privée (par code)", "private")],
                        value="public", allow_blank=False, id="visibility",
                    ),
                )
                yield _field(
                    "Joueurs",
                    NavSelect([(str(n), n) for n in range(3, 9)], value=4, allow_blank=False, id="players"),
                )
                yield _field(
                    "Durée d'un tour",
                    NavSelect(
                        [("Rapide (2 min)", "quick"), ("Tranquille (24 h)", "relaxed"), ("Personnalisée…", "custom")],
                        value="relaxed", allow_blank=False, id="deadline",
                    ),
                )
                yield _field(
                    "",
                    NavInput(placeholder="90s, 10min, 36h, 2j (30 s à 72 h)", id="custom-deadline"),
                    row_id="custom-row",
                )
                yield _field("Thème", NavInput(placeholder="facultatif", id="theme", max_length=200))
            with Vertical(id="rules-pane", classes="pane") as rules:
                rules.border_title = "Écriture"
                yield _field(
                    "Amorce",
                    NavSelect(
                        [("Dernière phrase", "last_sentence"), ("N derniers mots", "last_words"), ("Aucune", "none")],
                        value="last_sentence", allow_blank=False, id="primer",
                    ),
                )
                yield _field("", NavInput(placeholder="N (défaut 12)", id="primer-words", type="integer"), row_id="primer-row")
                yield _field("Mots minimum", NavInput(placeholder="facultatif", id="min-words", type="integer"))
                yield _field("Mots maximum", NavInput(placeholder="facultatif", id="max-words", type="integer"))
                yield Static("", id="form-error", classes="error")
                with Horizontal(classes="buttons"):
                    yield Button("Créer", id="submit", variant="primary")
                    yield Button("Annuler", id="cancel")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self._sync_visibility()
        self.query_one("#visibility", Select).focus()

    def _sync_visibility(self) -> None:
        self.query_one("#custom-row").display = self.query_one("#deadline", Select).value == "custom"
        self.query_one("#primer-row").display = self.query_one("#primer", Select).value == "last_words"

    def on_select_changed(self, event: Select.Changed) -> None:
        self._sync_visibility()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _error(self, text: str) -> None:
        self.query_one("#form-error", Static).update(text)

    async def action_submit(self) -> None:
        q = self.query_one
        try:
            settings = build_settings(
                visibility=q("#visibility", Select).value,
                players=q("#players", Select).value,
                deadline=q("#deadline", Select).value,
                custom_deadline=q("#custom-deadline", Input).value,
                theme=q("#theme", Input).value,
                primer_mode=q("#primer", Select).value,
                primer_words=q("#primer-words", Input).value,
                min_words=q("#min-words", Input).value,
                max_words=q("#max-words", Input).value,
            )
        except ValueError as exc:
            self._error(str(exc))
            return
        self._error("")
        await self.app.send(CreateGame(settings=settings))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_back()
        else:
            await self.action_submit()


class WaitingScreen(Screen):
    ready = False
    BINDINGS = [
        Binding("ctrl+l", "start", "Lancer"),
        Binding("ctrl+o", "leave", "Quitter la partie"),
        Binding("escape", "back", "Retour"),
    ]
    CSS = """
    #waiting-body { height: auto; padding: 0 2; }
    #left, #right { width: 1fr; height: auto; }
    #left { margin-right: 1; }
    #waiting-actions { margin: 1 2 0 2; }
    #code-line { text-align: center; padding: 1 0; }
    """

    def __init__(self, game_id: str) -> None:
        super().__init__()
        self.game_id = game_id

    def compose(self) -> ComposeResult:
        yield TopBar("Salle d'attente")
        yield Banner()
        with Horizontal(id="waiting-body"):
            with Vertical(id="left"):
                with Vertical(id="code-pane", classes="pane") as code:
                    code.border_title = "Code de la partie"
                    yield Static("", id="code-line")
                with Vertical(id="players-pane", classes="pane") as players:
                    players.border_title = "Joueurs"
                    yield Static("", id="players")
            with Vertical(id="right"):
                with Vertical(id="settings-pane", classes="pane") as settings:
                    settings.border_title = "Réglages"
                    yield Static("", id="settings")
                with Vertical(id="hint-pane", classes="pane") as hint:
                    hint.border_title = "Prochaine étape"
                    yield Static("", id="hint")
        with Horizontal(id="waiting-actions", classes="buttons"):
            yield Button("Lancer la partie", id="start", variant="primary")
            yield Button("Quitter la partie", id="leave", variant="warning")
            yield Button("Retour", id="back")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.ready = True
        self.refresh_view()

    def _close(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()

    def refresh_view(self) -> None:
        view = self.app.games.get(self.game_id)
        if view is not None and view.status != GameStatus.WAITING and self.app.screen is self:
            # the game has started (or is already over)
            self.app.switch_screen(
                FinalScreen(self.game_id) if view.status == GameStatus.FINISHED else GameScreen(self.game_id)
            )
            return
        if view is None or view.status != GameStatus.WAITING:
            self._close()  # left, deleted or expired: the lobby shows the rest
            return
        self.query_one(TopBar).refresh_bar()
        self.query_one(Banner).refresh_banner()
        is_host = view.host == self.app.pseudo
        enough = len(view.players) >= MIN_PLAYERS
        self.query_one("#code-line", Static).update(
            Text.assemble(chip(f"  {view.code}  ", colors.primary), "\n", ("à partager pour inviter", colors.muted))
            if view.code
            else Text("")
        )
        self.query_one("#code-pane").display = bool(view.code)
        self.query_one("#players-pane").border_title = (
            f"Joueurs  {len(view.players)}/{view.settings.desired_players}"
        )
        names = Text()
        for i, p in enumerate(view.players):
            if i:
                names.append("\n")
            names.append("♛ " if p == view.host else "  ", style=colors.warning)
            names.append(p, style="bold" if p == self.app.pseudo else "")
            if p == self.app.pseudo:
                names.append(" (toi)", style=colors.muted)
        self.query_one("#players", Static).update(names)
        lines = Text()
        for i, line in enumerate(describe_settings(view.settings)):
            key, _, value = line.partition(" : ")
            if i:
                lines.append("\n")
            lines.append(f"{key:<18}", style=colors.muted)
            lines.append(value)
        self.query_one("#settings", Static).update(lines)
        missing = view.settings.desired_players - len(view.players)
        if is_host and enough:
            hint = "Tu peux lancer la partie maintenant (Ctrl+L), ou attendre les autres joueurs."
        elif is_host:
            hint = f"Il faut au moins {MIN_PLAYERS} joueurs pour lancer la partie."
        else:
            hint = "L'hôte lancera la partie."
        self.query_one("#hint", Static).update(
            f"{hint}\nLancement automatique dans {missing} place(s)." if missing else hint
        )
        start = self.query_one("#start", Button)
        start.display = is_host
        start.disabled = not enough

    async def action_start(self) -> None:
        view = self.app.games.get(self.game_id)
        if view and view.host == self.app.pseudo and len(view.players) >= MIN_PLAYERS:
            await self.app.send(StartGame(game_id=self.game_id))

    async def action_leave(self) -> None:
        await self.app.send(LeaveGame(game_id=self.game_id))

    def action_back(self) -> None:
        self._close()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            await self.action_start()
        elif event.button.id == "leave":
            await self.action_leave()
        else:
            self._close()


class GameScreen(Screen):
    """A running or finished game: who writes, the primer, the draft and the deadline."""

    ready = False
    AUTO_FOCUS = ""  # the focus is placed by hand: the text area only exists on our turn
    BINDINGS = [
        Binding("ctrl+s", "send", "Envoyer"),
        Binding("ctrl+o", "leave", "Quitter la partie"),
        Binding("escape", "leave_text", "Quitter la saisie"),
        Binding("escape", "back", "Retour"),
    ]
    CSS = """
    #game-body { height: auto; padding: 0 2; }
    #side { width: 34; height: auto; margin-right: 1; }
    #main { width: 1fr; height: auto; }
    #draft { height: 6; }
    #counter { height: 1; margin-bottom: 1; }
    #game-actions { margin: 1 2 0 2; }
    """

    def __init__(self, game_id: str) -> None:
        super().__init__()
        self.game_id = game_id
        self._was_my_turn = False
        self._leave_armed = False

    def compose(self) -> ComposeResult:
        yield TopBar("Partie")
        yield Banner()
        with Horizontal(id="game-body"):
            with Vertical(id="side"):
                with Vertical(id="info-pane", classes="pane") as info:
                    info.border_title = "Partie"
                    yield Static("", id="info")
                with Vertical(id="deadline-pane", classes="pane") as deadline:
                    deadline.border_title = "Échéance du tour"
                    yield Static("", id="deadline")
            with Vertical(id="main"):
                with Vertical(id="primer-pane", classes="pane") as primer:
                    primer.border_title = "Amorce"
                    yield Static("", id="primer")
                with Vertical(id="write-pane", classes="pane") as write:
                    write.border_title = "Ton texte"
                    yield TextArea(id="draft", soft_wrap=True, show_line_numbers=False, tab_behavior="focus")
                    yield Static("", id="counter")
                    with Horizontal(classes="buttons"):
                        yield Button("Envoyer", id="send", variant="primary")
        with Horizontal(id="game-actions", classes="buttons"):
            yield Button("Retour", id="back")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.ready = True
        self.query_one("#draft", TextArea).text = self.app.drafts.get(self.game_id, "")
        self.set_interval(1.0, self._tick)
        self.refresh_view()

    # --- bindings that depend on where the focus is ---------------------------

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        in_text = isinstance(self.app.focused, TextArea)
        if action == "leave_text":
            return in_text
        if action == "back":
            return not in_text
        view = self.app.games.get(self.game_id)
        if action == "send":
            return bool(view and view.my_turn)
        if action == "leave":
            return bool(view and view.status == GameStatus.RUNNING)
        return True

    def _place_focus(self) -> None:
        view = self.app.games.get(self.game_id)
        if view is not None and view.my_turn and view.status == GameStatus.RUNNING:
            self.query_one("#draft", TextArea).focus()
        else:
            self.query_one("#back", Button).focus()

    def _close(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()

    # --- drawing ----------------------------------------------------------------

    def _tick(self) -> None:
        view = self.app.games.get(self.game_id)
        if view is not None and view.status == GameStatus.RUNNING:
            self.query_one("#deadline", Static).update(
                format_remaining(view.deadline, self.app.clock())
            )

    def refresh_view(self) -> None:
        app = self.app
        view = app.games.get(self.game_id)
        if view is None:
            self._close()  # left the game
            return
        if view.status == GameStatus.WAITING and app.screen is self:
            app.switch_screen(WaitingScreen(self.game_id))
            return
        if view.status == GameStatus.FINISHED and app.screen is self:
            app.switch_screen(FinalScreen(self.game_id))  # the story is revealed
            return
        self.query_one(TopBar).refresh_bar()
        self.query_one(Banner).refresh_banner()
        running = view.status == GameStatus.RUNNING

        info = Text()
        info.append("Thème\n", style=colors.muted)
        info.append(f"{view.settings.theme or 'aucun'}\n\n")
        for i, p in enumerate(view.players):
            marker = "▶ " if running and p == view.current_player else "  "
            info.append(marker, style=colors.accent)
            info.append(p, style="bold" if p == app.pseudo else "")
            if p == app.pseudo:
                info.append(" (toi)", style=colors.muted)
            if i < len(view.players) - 1:
                info.append("\n")
        self.query_one("#info", Static).update(info)

        self.query_one("#deadline-pane").display = running
        if running:
            self._tick()

        primer_pane = self.query_one("#primer-pane")
        write_pane = self.query_one("#write-pane")
        write_pane.display = running and view.my_turn
        if running and view.my_turn:
            primer_pane.border_title = "Amorce"
            self.query_one("#primer", Static).update(primer_help(view))
            self._update_counter(view)
            if not self._was_my_turn and app.screen is self:
                self.query_one("#draft", TextArea).focus()
        elif running:
            primer_pane.border_title = "En cours"
            where, ahead = turn_position(view, app.pseudo or "")
            if where == "later":
                tail = "Tu es le prochain." if ahead == 2 else f"Ton tour viendra après {ahead - 2} autre(s) joueur(s)."
            else:
                tail = "Ton tour est passé : tu verras l'histoire complète à la fin."
            self.query_one("#primer", Static).update(f"C'est le tour de {view.current_player}.\n{tail}")
        self._was_my_turn = bool(running and view.my_turn)
        self.refresh_bindings()  # the footer follows the state (send, leave...)
        focused = app.focused
        if app.screen is self and (focused is None or not focused.display or not focused.visible):
            self._place_focus()
        elif app.screen is self and isinstance(focused, TextArea) and not write_pane.display:
            self._place_focus()

    def _update_counter(self, view) -> None:
        draft = self.query_one("#draft", TextArea).text
        status = word_status(draft, view.settings)
        color = colors.success if status.ok else (colors.muted if not draft.strip() else colors.error)
        self.query_one("#counter", Static).update(Text(status.text, style=color))
        self.query_one("#send", Button).disabled = not status.ok

    # --- actions ----------------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.app.drafts[self.game_id] = event.text_area.text
        view = self.app.games.get(self.game_id)
        if view is not None and view.my_turn:
            self._update_counter(view)

    async def action_send(self) -> None:
        view = self.app.games.get(self.game_id)
        if view is None or not view.my_turn:
            return
        draft = self.query_one("#draft", TextArea).text
        status = word_status(draft, view.settings)
        if not status.ok:
            self.app.notify(status.text, severity="warning")
            return
        self.app.submitted.add(self.game_id)
        await self.app.send(SubmitText(game_id=self.game_id, text=draft.strip()))

    def action_leave_text(self) -> None:
        self.query_one("#send", Button).focus()

    def action_back(self) -> None:
        self._close()

    async def action_leave(self) -> None:
        if not self._leave_armed:
            self._leave_armed = True
            self.app.notify("Ctrl+O encore une fois pour quitter la partie.", severity="warning")
            self.set_timer(5, lambda: setattr(self, "_leave_armed", False))
            return
        self._leave_armed = False
        await self.app.send(LeaveGame(game_id=self.game_id))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send":
            await self.action_send()
        else:
            self._close()


class FinalScreen(Screen):
    """The finished story: read it, copy it, save it as .md or .txt."""

    ready = False
    BINDINGS = [
        Binding("ctrl+s", "save", "Enregistrer"),
        Binding("ctrl+y", "copy", "Copier"),
        Binding("escape", "back", "Retour"),
    ]
    CSS = """
    #final-body { height: 1fr; padding: 0 2; }
    #final-side { width: 34; height: auto; margin-right: 1; }
    #final-main { width: 1fr; height: 1fr; }
    #story-scroll { height: 1fr; }
    #save-pane { margin: 1 2 0 2; height: auto; }
    #save-pane .frow { margin-bottom: 0; }
    #final-actions { height: 1; margin-top: 1; }
    """

    def __init__(self, game_id: str) -> None:
        super().__init__()
        self.game_id = game_id

    def compose(self) -> ComposeResult:
        config = self.app.config
        yield TopBar("L'histoire")
        yield Banner()
        with Horizontal(id="final-body"):
            with Vertical(id="final-side"):
                with Vertical(id="final-info-pane", classes="pane") as info:
                    info.border_title = "Partie terminée"
                    yield Static("", id="final-info")
            with Vertical(id="final-main", classes="pane") as main:
                main.border_title = "L'histoire"
                with NavScroll(id="story-scroll"):
                    yield Static("", id="story")
        with Vertical(id="save-pane", classes="pane") as save:
            save.border_title = "Garder l'histoire"
            yield _field("Dossier", NavInput(value=config.export_dir or export.default_export_dir(), id="export-dir"))
            yield _field(
                "Format",
                NavSelect([(label, key) for key, label in export.FORMATS.items()], value="md", allow_blank=False, id="export-format"),
            )
            with Horizontal(id="final-actions"):
                yield Button("Enregistrer", id="save", variant="primary")
                yield Button("Copier", id="copy")
                yield Button("Retour", id="back")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.ready = True
        self.refresh_view()
        self.query_one("#story-scroll").focus()

    def _close(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()

    def refresh_view(self) -> None:
        app = self.app
        view = app.games.get(self.game_id)
        if view is None:
            self._close()
            return
        self.query_one(TopBar).refresh_bar()
        self.query_one(Banner).refresh_banner()
        parts = view.story or []
        info = Text()
        info.append("Thème\n", style=colors.muted)
        info.append(f"{view.settings.theme or 'aucun'}\n\n")
        info.append("Auteurs\n", style=colors.muted)
        for name in export.authors(view) or ["personne"]:
            info.append(f"{name}\n", style="bold" if name == app.pseudo else "")
        if view.skipped:
            info.append("\nTours sautés\n", style=colors.muted)
            info.append(", ".join(view.skipped))
        self.query_one("#final-info", Static).update(info)
        story = Text()
        for part in parts:
            story.append(f"{part.author}\n", style=f"bold {colors.secondary}")
            story.append(f"{part.text}\n\n")
        if not parts:
            story.append("Personne n'a écrit.", style=colors.muted)
        self.query_one("#story", Static).update(story)

    # --- actions ----------------------------------------------------------------

    def _today(self):
        return self.app.clock().astimezone().date()

    def _view(self):
        return self.app.games.get(self.game_id)

    def action_copy(self) -> None:
        view = self._view()
        if view is None:
            return
        text = export.render_text(view, self._today())
        tool = export.copy_with_system_tool(text)
        self.app.copy_to_clipboard(text)  # also asks the terminal (works over SSH in most terminals)
        if tool:
            self.app.notify("Histoire copiée dans le presse-papiers.")
        else:
            self.app.notify("Histoire envoyée au terminal pour le presse-papiers (selon le terminal).")

    def action_save(self) -> None:
        view = self._view()
        if view is None:
            return
        directory = self.query_one("#export-dir", Input).value.strip() or export.default_export_dir()
        fmt = self.query_one("#export-format", Select).value
        try:
            path = export.save_story(view, fmt, directory, self._today())
        except OSError as exc:
            self.app.notify(f"Enregistrement impossible : {exc.strerror or exc}", severity="error")
            return
        config = self.app.config
        if config.export_dir != directory:
            config.export_dir = directory
            if config.registered:
                config.save(self.app.config_path)
        self.app.notify(f"Enregistré : {path}")

    def action_back(self) -> None:
        self._close()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        {"save": self.action_save, "copy": self.action_copy}.get(event.button.id, self._close)()
