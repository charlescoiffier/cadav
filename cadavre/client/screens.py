"""Screens: login, lobby, game creation and waiting room."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from cadavre.client.config import DEFAULT_URL
from cadavre.client.logic import (
    build_settings,
    describe_settings,
    lobby_label,
    my_game_label,
)
from cadavre.protocol import (
    MIN_PLAYERS,
    CreateGame,
    GameStatus,
    JoinGame,
    LeaveGame,
    StartGame,
)

STATUS_TEXT = {
    "connecting": "Connexion…",
    "online": "● Connecté",
    "offline": "○ Hors ligne, nouvelle tentative…",
    "replaced": "○ Connecté depuis un autre terminal",
    "outdated": "○ Client trop ancien",
}


def _set_options(widget: OptionList, items: list[tuple[str, str]]) -> None:
    """Rebuild an option list only if its content changed (keeps the highlight otherwise)."""
    current = [(o.id, str(o.prompt)) for o in widget.options]
    if current == items:
        return
    highlighted = widget.highlighted
    widget.clear_options()
    widget.add_options([Option(label, id=ident) for ident, label in items])
    if items and highlighted is not None:
        widget.highlighted = min(highlighted, len(items) - 1)


class LoginScreen(Screen):
    def __init__(self, error: str = "") -> None:
        super().__init__()
        self._error = error

    def compose(self) -> ComposeResult:
        config = self.app.config
        yield Header()
        with VerticalScroll(classes="panel"):
            yield Static("Bienvenue au cadavre exquis", classes="title")
            yield Static(
                "Choisis un pseudo : pas de mot de passe, un secret est créé et gardé sur cet ordinateur.",
                classes="muted",
            )
            yield Label("Pseudo")
            yield Input(value=config.pseudo, placeholder="2 à 24 caractères", id="pseudo", max_length=24)
            yield Label("Serveur")
            yield Input(value=config.url or DEFAULT_URL, id="server")
            yield Static(self._error, id="login-error", classes="error")
            yield Button("Entrer", id="connect", variant="primary")
        yield Footer()

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
    BINDINGS = [Binding("n", "create", "Nouvelle partie")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="panel"):
            yield Static("", id="status")
            yield Static("Mes parties", classes="title")
            yield OptionList(id="my-games")
            yield Static("Parties publiques en attente de joueurs", classes="title")
            yield OptionList(id="public-games")
            yield Static("Rejoindre avec un code", classes="title")
            with Horizontal(classes="row"):
                yield Input(placeholder="Code à 5 lettres", id="code", max_length=5)
                yield Button("Rejoindre", id="join-code")
            yield Button("Créer une partie", id="create", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.ready = True  # widgets exist: the app may now call refresh_view
        self.refresh_view()

    def refresh_view(self) -> None:
        app = self.app
        who = f" — {app.pseudo}" if app.pseudo else ""
        self.query_one("#status", Static).update(STATUS_TEXT.get(app.status, app.status) + who)
        _set_options(
            self.query_one("#my-games", OptionList),
            [(v.game_id, my_game_label(v)) for v in app.games.values()],
        )
        _set_options(
            self.query_one("#public-games", OptionList),
            [(e.game_id, lobby_label(e)) for e in app.lobby if e.game_id not in app.games],
        )

    def action_create(self) -> None:
        self.app.push_screen(CreateScreen())

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        game_id = event.option.id
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

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            self.action_create()
        elif event.button.id == "join-code":
            await self._join_code()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "code":
            await self._join_code()


class CreateScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Retour")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="panel"):
            yield Static("Créer une partie", classes="title")
            yield Label("Visibilité")
            yield Select(
                [("Publique (visible dans la liste)", "public"), ("Privée (accès par code)", "private")],
                value="public", allow_blank=False, id="visibility",
            )
            yield Label("Joueurs souhaités (la partie démarre quand ils sont tous là)")
            yield Select(
                [(str(n), n) for n in range(3, 9)], value=4, allow_blank=False, id="players"
            )
            yield Label("Durée d'un tour")
            yield Select(
                [("Rapide (2 min)", "quick"), ("Tranquille (24 h)", "relaxed"), ("Personnalisée…", "custom")],
                value="relaxed", allow_blank=False, id="deadline",
            )
            yield Input(placeholder="ex. 90s, 10min, 36h, 2j (30 s à 72 h)", id="custom-deadline")
            yield Label("Thème (facultatif)")
            yield Input(placeholder="ex. Une enquête dans un phare", id="theme", max_length=200)
            yield Label("Amorce transmise au joueur suivant")
            yield Select(
                [("Dernière phrase", "last_sentence"), ("N derniers mots", "last_words"), ("Aucune", "none")],
                value="last_sentence", allow_blank=False, id="primer",
            )
            yield Input(placeholder="N (défaut 12)", id="primer-words", type="integer")
            yield Label("Longueur d'une contribution, en mots (facultatif)")
            with Horizontal(classes="row"):
                yield Input(placeholder="minimum", id="min-words", type="integer")
                yield Input(placeholder="maximum", id="max-words", type="integer")
            yield Static("", id="form-error", classes="error")
            with Horizontal(classes="row"):
                yield Button("Créer", id="submit", variant="primary")
                yield Button("Annuler", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        self.query_one("#custom-deadline").display = self.query_one("#deadline", Select).value == "custom"
        self.query_one("#primer-words").display = self.query_one("#primer", Select).value == "last_words"

    def on_select_changed(self, event: Select.Changed) -> None:
        self._sync_visibility()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _error(self, text: str) -> None:
        self.query_one("#form-error", Static).update(text)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_back()
            return
        q = lambda i: self.query_one(i)  # noqa: E731
        try:
            settings = build_settings(
                visibility=q("#visibility").value,
                players=q("#players").value,
                deadline=q("#deadline").value,
                custom_deadline=q("#custom-deadline").value,
                theme=q("#theme").value,
                primer_mode=q("#primer").value,
                primer_words=q("#primer-words").value,
                min_words=q("#min-words").value,
                max_words=q("#max-words").value,
            )
        except ValueError as exc:
            self._error(str(exc))
            return
        self._error("")
        await self.app.send(CreateGame(settings=settings))


class WaitingScreen(Screen):
    ready = False
    BINDINGS = [Binding("escape", "back", "Retour")]

    def __init__(self, game_id: str) -> None:
        super().__init__()
        self.game_id = game_id

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="panel"):
            yield Static("Salle d'attente", classes="title")
            yield Static("", id="code-line")
            yield Static("", id="settings")
            yield Static("", id="players")
            yield Static("", id="hint", classes="muted")
            with Horizontal(classes="row"):
                yield Button("Lancer la partie", id="start", variant="primary")
                yield Button("Quitter la partie", id="leave", variant="warning")
                yield Button("Retour", id="back")
        yield Footer()

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
        is_host = view.host == self.app.pseudo
        self.query_one("#code-line", Static).update(
            f"Code de la partie : [b]{view.code}[/b]  — à partager pour inviter" if view.code else ""
        )
        self.query_one("#settings", Static).update("\n".join(describe_settings(view.settings)))
        names = "\n".join(
            f"• {p}{' (hôte)' if p == view.host else ''}{' (toi)' if p == self.app.pseudo else ''}"
            for p in view.players
        )
        self.query_one("#players", Static).update(
            f"Joueurs ({len(view.players)}/{view.settings.desired_players}) :\n{names}"
        )
        missing = view.settings.desired_players - len(view.players)
        if is_host and len(view.players) >= MIN_PLAYERS:
            hint = "Tu peux lancer la partie maintenant, ou attendre les autres joueurs."
        elif is_host:
            hint = f"Il faut au moins {MIN_PLAYERS} joueurs pour lancer la partie."
        else:
            hint = "L'hôte lancera la partie."
        self.query_one("#hint", Static).update(f"{hint} Encore {missing} place(s) avant le lancement automatique.")
        start = self.query_one("#start", Button)
        start.display = is_host
        start.disabled = len(view.players) < MIN_PLAYERS

    def action_back(self) -> None:
        self._close()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            await self.app.send(StartGame(game_id=self.game_id))
        elif event.button.id == "leave":
            await self.app.send(LeaveGame(game_id=self.game_id))
        else:
            self._close()
