"""Textual application: connection, shared state and screen navigation."""

from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from cadavre.client.config import Config, default_config_path, new_secret
from cadavre.client.connection import RETRY_DELAYS, Connection
from cadavre.client.theme import APP_CSS, CADAVRE_THEME
from cadavre.client.screens import CreateScreen, LobbyScreen, LoginScreen, WaitingScreen
from cadavre.protocol import (
    Auth,
    AuthOk,
    ErrorMessage,
    GameFinished,
    GameJoined,
    GameStarted,
    GameStatus,
    GameView,
    ListGames,
    LobbyEntry,
    LobbyUpdate,
    MyGames,
    PlayerJoined,
    PlayerLeft,
    Register,
    TurnSkipped,
    TurnStarted,
)

# Errors that mean "these credentials cannot be used": go back to the login screen.
LOGIN_ERRORS = {
    "bad_credentials",
    "pseudo_taken",
    "bad_pseudo",
    "too_many_attempts",
    "unsupported_version",
    "not_authenticated",
}

_EVENTS_WITH_VIEW = (PlayerJoined, PlayerLeft, GameStarted, TurnStarted, TurnSkipped, GameFinished)


class CadavreApp(App):
    TITLE = "cadav"
    CSS = APP_CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("ctrl+q", "quit", "Quitter")]

    def __init__(
        self,
        config_path: Path | None = None,
        url: str | None = None,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ) -> None:
        super().__init__()
        self.register_theme(CADAVRE_THEME)
        self.theme = CADAVRE_THEME.name
        self.config_path = config_path or default_config_path()
        self.config = Config.load(self.config_path)
        if url:
            self.config.url = url
        self.retry_delays = retry_delays
        self.games: dict[str, GameView] = {}
        self.lobby: list[LobbyEntry] = []
        self.pseudo: str | None = None
        self.status = "connecting"
        self.conn: Connection | None = None
        self._candidate = self.config
        self._registering = False

    # --- startup -----------------------------------------------------------

    def on_mount(self) -> None:
        if self.config.registered:
            self.push_screen(LobbyScreen())
            self.connect(self.config, registering=False)
        else:
            self.push_screen(LoginScreen())

    def connect(self, creds: Config, registering: bool) -> None:
        if self.conn is not None:
            self.conn.stop()
        self._candidate, self._registering, self.pseudo = creds, registering, None
        self.conn = Connection(
            creds.url, self._hello, self.on_server_message, self.on_conn_state, self.retry_delays
        )
        self.run_worker(self.conn.run(), exit_on_error=False)

    def begin_login(self, pseudo: str, url: str) -> None:
        """Called by the login screen: reuse the stored secret for the same pseudo, else register."""
        same = self.config.registered and pseudo.casefold() == self.config.pseudo.casefold()
        if same:
            creds = Config(self.config.pseudo, self.config.secret, url)
        else:
            creds = Config(pseudo, new_secret(), url)
        self.connect(creds, registering=not same)

    def _hello(self):
        c = self._candidate
        return (Register if self._registering else Auth)(pseudo=c.pseudo, secret=c.secret)

    async def send(self, msg) -> None:
        if self.conn is None or not await self.conn.send(msg):
            self.notify("Hors ligne : réessaie dans un instant.", severity="warning")

    async def on_unmount(self) -> None:
        if self.conn is not None:
            self.conn.stop()

    # --- incoming ----------------------------------------------------------

    def on_conn_state(self, state: str) -> None:
        self.status = state
        if state == "replaced":
            self.notify("Ce pseudo s'est connecté depuis un autre terminal.", severity="error")
        elif state == "outdated":
            self.notify("Version du client trop ancienne : mets-la à jour.", severity="error")
        self.refresh_screens()

    async def on_server_message(self, msg) -> None:
        if isinstance(msg, AuthOk):
            await self._on_auth_ok(msg)
        elif isinstance(msg, MyGames):
            self.games = {v.game_id: v for v in msg.games}
        elif isinstance(msg, LobbyUpdate):
            self.lobby = msg.games
        elif isinstance(msg, GameJoined):
            self.games[msg.game_id] = msg.view
            self._open_waiting(msg.game_id)
        elif isinstance(msg, _EVENTS_WITH_VIEW):
            self.games[msg.game_id] = msg.view
            if isinstance(msg, GameStarted):
                self.notify("La partie est lancée !")
        elif isinstance(msg, ErrorMessage):
            self._on_error(msg)
        self.refresh_screens()

    async def _on_auth_ok(self, msg: AuthOk) -> None:
        self.pseudo = msg.pseudo
        if self._registering:
            self.config = Config(msg.pseudo, self._candidate.secret, self._candidate.url)
            self.config.save(self.config_path)
            self._registering = False
        if isinstance(self.screen, LoginScreen):
            self.switch_screen(LobbyScreen())
        await self.send(ListGames())

    def _on_error(self, msg: ErrorMessage) -> None:
        if self.pseudo is None and msg.code in LOGIN_ERRORS:
            if self.conn is not None:
                self.conn.stop()
            self.show_login(msg.message)
        elif msg.code == "game_expired" and msg.game_id:
            self.games.pop(msg.game_id, None)
            self.notify(msg.message, severity="warning")
        else:
            self.notify(msg.message, severity="error")

    def show_login(self, error: str) -> None:
        if isinstance(self.screen, LoginScreen):
            self.screen.show_error(error)
            return
        screen = LoginScreen(error)
        # Replace everything above the base screen: the old session is unusable.
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(screen)

    # --- navigation --------------------------------------------------------

    def _open_waiting(self, game_id: str) -> None:
        if isinstance(self.screen, CreateScreen):
            self.pop_screen()
        view = self.games.get(game_id)
        if view and view.status == GameStatus.WAITING and isinstance(self.screen, LobbyScreen):
            self.push_screen(WaitingScreen(game_id))

    def refresh_screens(self) -> None:
        for screen in list(self.screen_stack):
            refresh = getattr(screen, "refresh_view", None)
            if refresh is not None and getattr(screen, "ready", False):
                refresh()
