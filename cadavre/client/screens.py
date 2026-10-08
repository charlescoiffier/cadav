"""Screens: login, lobby, game creation and waiting room."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from cadavre.client.config import DEFAULT_URL
from cadavre.client.logic import (
    build_settings,
    describe_settings,
    format_duration,
    primer_text,
    words_text,
)
from cadavre.client.theme import (
    ERROR,
    MUTED,
    PRIMARY,
    SECONDARY,
    SUCCESS,
    WARNING,
    chip,
)
from cadavre.protocol import (
    MIN_PLAYERS,
    CreateGame,
    GameStatus,
    GameView,
    JoinGame,
    LeaveGame,
    LobbyEntry,
    StartGame,
    Visibility,
)

STATE_TEXT = {
    "connecting": ("○", WARNING, "Connexion…"),
    "online": ("●", SUCCESS, "Connecté"),
    "offline": ("○", ERROR, "Hors ligne, nouvelle tentative…"),
    "replaced": ("○", ERROR, "Connecté depuis un autre terminal"),
    "outdated": ("○", ERROR, "Client trop ancien"),
}


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
            Text.assemble(("▌cadav", "bold"), (f"  ›  {self.place}", MUTED))
        )
        dot, color, label = STATE_TEXT.get(app.status, ("○", MUTED, app.status))
        server = app.config.url.split("://", 1)[-1]
        who = f"{app.pseudo}@{server}  " if app.pseudo else ""
        self.query_one("#status", Static).update(Text.assemble(who, (f"{dot} {label}", color)))


def _field(label: str, widget, row_id: str | None = None) -> Horizontal:
    return Horizontal(Static(label, classes="flabel"), widget, classes="frow", id=row_id)


def _set_options(widget: OptionList, items: list[tuple[str | None, Text]], empty: str) -> None:
    """Rebuild an option list only if its content changed (keeps the highlight otherwise)."""
    options = [Option(label, id=ident) for ident, label in items]
    if not options:
        options = [Option(Text(empty, style=MUTED), disabled=True)]
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
        badge = chip("ATTENTE", PRIMARY)
        info = f"{len(view.players)}/{view.settings.desired_players} joueurs"
    elif view.status == GameStatus.RUNNING:
        badge = chip("À TOI", WARNING) if view.my_turn else chip("EN COURS", SECONDARY)
        info = "c'est ton tour" if view.my_turn else f"tour de {view.current_player}"
    else:
        badge = chip("TERMINÉE", SUCCESS)
        info = "lis l'histoire"
    return Text.assemble(badge, " ", (theme, "bold"), "\n", (f"{info}", MUTED))


def public_game_prompt(entry: LobbyEntry) -> Text:
    return Text.assemble(
        (entry.theme or "Sans thème", "bold"),
        "\n",
        (
            f"{entry.players}/{entry.desired_players} joueurs · tour {format_duration(entry.turn_seconds)}"
            f" · hôte {entry.host}",
            MUTED,
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
            yield _field("Pseudo", Input(value=config.pseudo, placeholder="2 à 24 caractères", id="pseudo", max_length=24))
            yield _field("Serveur", Input(value=config.url or DEFAULT_URL, id="server"))
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()


class LobbyScreen(Screen):
    ready = False
    BINDINGS = [
        Binding("n", "create", "Nouvelle partie"),
        Binding("c", "focus_code", "Code"),
    ]
    CSS = """
    #lobby-body { height: auto; padding: 1 1 0 1; }
    #mine-pane, #public-pane { width: 1fr; height: auto; max-height: 100%; }
    #mine-pane { margin-right: 1; }
    #join-pane { margin: 1 1 0 1; height: auto; }
    #join-pane Input { width: 24; margin-right: 1; }
    #join-pane .actions { width: 1fr; height: 1; align-horizontal: right; }
    """

    def compose(self) -> ComposeResult:
        yield TopBar("Lobby")
        with Horizontal(id="lobby-body"):
            with Vertical(id="mine-pane", classes="pane") as mine:
                mine.border_title = "Mes parties"
                yield OptionList(id="my-games")
            with Vertical(id="public-pane", classes="pane") as public:
                public.border_title = "Parties publiques"
                yield OptionList(id="public-games")
        with Horizontal(id="join-pane", classes="pane") as join:
            join.border_title = "Rejoindre avec un code"
            yield Input(placeholder="CODE", id="code", max_length=5)
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
        _set_options(
            self.query_one("#my-games", OptionList),
            [(v.game_id, my_game_prompt(v)) for v in app.games.values()],
            "Aucune partie : appuie sur n pour en créer une.",
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
        self.query_one("#code", Input).focus()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        game_id = event.option.id
        if game_id is None:
            return
        if event.option_list.id == "public-games":
            await self.app.send(JoinGame(game_id=game_id))
            return
        view = self.app.games.get(game_id)
        if view is None:
            return
        if view.status == GameStatus.WAITING:
            self.app.push_screen(WaitingScreen(game_id))
        else:
            self.app.notify("L'écran de partie n'est pas encore disponible.")

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
    #create-body { height: auto; padding: 1 1 0 1; }
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
                    Select(
                        [("Publique (dans la liste)", "public"), ("Privée (par code)", "private")],
                        value="public", allow_blank=False, id="visibility",
                    ),
                )
                yield _field(
                    "Joueurs",
                    Select([(str(n), n) for n in range(3, 9)], value=4, allow_blank=False, id="players"),
                )
                yield _field(
                    "Durée d'un tour",
                    Select(
                        [("Rapide (2 min)", "quick"), ("Tranquille (24 h)", "relaxed"), ("Personnalisée…", "custom")],
                        value="relaxed", allow_blank=False, id="deadline",
                    ),
                )
                yield _field(
                    "",
                    Input(placeholder="90s, 10min, 36h, 2j (30 s à 72 h)", id="custom-deadline"),
                    row_id="custom-row",
                )
                yield _field("Thème", Input(placeholder="facultatif", id="theme", max_length=200))
            with Vertical(id="rules-pane", classes="pane") as rules:
                rules.border_title = "Écriture"
                yield _field(
                    "Amorce",
                    Select(
                        [("Dernière phrase", "last_sentence"), ("N derniers mots", "last_words"), ("Aucune", "none")],
                        value="last_sentence", allow_blank=False, id="primer",
                    ),
                )
                yield _field("", Input(placeholder="N (défaut 12)", id="primer-words", type="integer"), row_id="primer-row")
                yield _field("Mots minimum", Input(placeholder="facultatif", id="min-words", type="integer"))
                yield _field("Mots maximum", Input(placeholder="facultatif", id="max-words", type="integer"))
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
        Binding("l", "start", "Lancer"),
        Binding("x", "leave", "Quitter la partie"),
        Binding("escape", "back", "Retour"),
    ]
    CSS = """
    #waiting-body { height: auto; padding: 1 1 0 1; }
    #left, #right { width: 1fr; height: auto; }
    #left { margin-right: 1; }
    #waiting-actions { margin: 1 1 0 1; }
    #code-line { text-align: center; padding: 1 0; }
    """

    def __init__(self, game_id: str) -> None:
        super().__init__()
        self.game_id = game_id

    def compose(self) -> ComposeResult:
        yield TopBar("Salle d'attente")
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
        if view is None or view.status != GameStatus.WAITING:
            self._close()  # left, deleted, expired or already started: the lobby shows the rest
            return
        self.query_one(TopBar).refresh_bar()
        is_host = view.host == self.app.pseudo
        enough = len(view.players) >= MIN_PLAYERS
        self.query_one("#code-line", Static).update(
            Text.assemble((f"  {view.code}  ", f"bold {PRIMARY} on #140a22 reverse"), "\n",
                          ("à partager pour inviter", MUTED))
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
            names.append("♛ " if p == view.host else "  ", style=WARNING)
            names.append(p, style="bold" if p == self.app.pseudo else "")
            if p == self.app.pseudo:
                names.append(" (toi)", style=MUTED)
        self.query_one("#players", Static).update(names)
        lines = Text()
        for i, line in enumerate(describe_settings(view.settings)):
            key, _, value = line.partition(" : ")
            if i:
                lines.append("\n")
            lines.append(f"{key:<18}", style=MUTED)
            lines.append(value)
        self.query_one("#settings", Static).update(lines)
        missing = view.settings.desired_players - len(view.players)
        if is_host and enough:
            hint = "Tu peux lancer la partie maintenant (touche l), ou attendre les autres joueurs."
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
