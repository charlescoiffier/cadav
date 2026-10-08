"""Client UI tests: the Textual app driven by Pilot against a real server."""

import json
import random
import time
from datetime import timedelta

import pytest
import websockets
from helpers import Client
from textual.widgets import Button, Input, OptionList, Select, Static

from cadavre.client.app import CadavreApp
from cadavre.client.config import Config
from cadavre.client.screens import CreateScreen, LobbyScreen, LoginScreen, WaitingScreen
from cadavre.server import Server
from cadavre.storage import Storage

SIZE = (120, 60)
SETTINGS = {"desired_players": 3, "turn_seconds": 120}


class Backend:
    def __init__(self, tmp_path):
        self.server = Server(Storage(tmp_path / "data"), rng=random.Random(3))
        self.tmp = tmp_path
        self.config_path = tmp_path / "client" / "config.json"

    async def start(self):
        await self.server.start()
        self.ws = await self.server.listen("127.0.0.1", 0).__aenter__()
        self.url = f"ws://127.0.0.1:{self.ws.sockets[0].getsockname()[1]}"

    async def stop(self):
        await self.ws.__aexit__(None, None, None)
        await self.server.close()

    def app(self):
        return CadavreApp(config_path=self.config_path, url=self.url, retry_delays=(0.05,))

    async def script_client(self, name):
        c = Client(await websockets.connect(self.url), name)
        await c.send("register", pseudo=name, secret=f"secret-{name}")
        await c.until("my_games")
        return c

    def preregister(self, pseudo="ana"):
        Config(pseudo, "s" * 64, self.url).save(self.config_path)


@pytest.fixture
async def backend(tmp_path):
    b = Backend(tmp_path)
    await b.start()
    yield b
    await b.stop()


async def until(pilot, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        await pilot.pause(0.03)
        if cond():
            return
    raise AssertionError("condition not reached in time")


def text(app, selector):
    return str(app.screen.query_one(selector, Static).render())


def option_ids(app, selector):
    return [o.id for o in app.screen.query_one(selector, OptionList).options]


async def register_in_server(backend, pseudo="ana"):
    """Make the server know `pseudo` with the secret of `preregister`."""
    c = Client(await websockets.connect(backend.url))
    await c.send("register", pseudo=pseudo, secret="s" * 64)
    await c.until("my_games")
    await c.ws.close()


# --- login -----------------------------------------------------------------


async def test_first_launch_registers_and_saves_config(backend):
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        assert isinstance(app.screen, LoginScreen)
        await pilot.click("#pseudo")
        await pilot.press(*"ana")
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        await until(pilot, lambda: app.pseudo == "ana")
        assert "Connecté — ana" in text(app, "#status")
    saved = Config.load(backend.config_path)
    assert saved.pseudo == "ana" and len(saved.secret) == 64
    assert saved.secret not in json.dumps(list(backend.server.users.values()))


async def test_returning_user_authenticates_with_stored_secret(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        assert isinstance(app.screen, LobbyScreen)
        await until(pilot, lambda: app.pseudo == "ana")


async def test_pseudo_taken_shows_error_on_login_screen(backend):
    other = await backend.script_client("Ana")
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        app.screen.query_one("#pseudo", Input).value = "ana"
        app.screen.query_one("#connect", Button).press()
        await until(pilot, lambda: "déjà pris" in text(app, "#login-error"))
        assert isinstance(app.screen, LoginScreen)
        assert not backend.config_path.exists()
    await other.ws.close()


async def test_refused_stored_secret_returns_to_login(backend):
    backend.preregister()  # the server has never heard of ana
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await until(pilot, lambda: isinstance(app.screen, LoginScreen))
        await until(pilot, lambda: "incorrect" in text(app, "#login-error"))


async def test_offline_status_when_server_is_unreachable(tmp_path):
    Config("ana", "s" * 64, "ws://127.0.0.1:1").save(tmp_path / "c.json")
    app = CadavreApp(config_path=tmp_path / "c.json", retry_delays=(0.05,))
    async with app.run_test(size=SIZE) as pilot:
        await until(pilot, lambda: "Hors ligne" in text(app, "#status"))
        app.screen.query_one("#create", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, CreateScreen)
        app.screen.query_one("#submit", Button).press()
        await until(pilot, lambda: any("Hors ligne" in n.message for n in app._notifications))


# --- lobby, creation, waiting room -------------------------------------------


async def logged_in(backend, pilot, app, pseudo="ana"):
    await until(pilot, lambda: app.pseudo == pseudo and isinstance(app.screen, LobbyScreen))


async def test_create_game_opens_waiting_room(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        app.screen.query_one("#create", Button).press()
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        app.screen.query_one("#theme", Input).value = "Une enquête"
        app.screen.query_one("#visibility", Select).value = "private"
        app.screen.query_one("#players", Select).value = 5
        app.screen.query_one("#submit", Button).press()
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        game = next(iter(backend.server.games.values()))
        assert game.settings.theme == "Une enquête" and game.settings.desired_players == 5
        assert game.settings.visibility == "private" and game.settings.turn_seconds == 86400
        await until(pilot, lambda: game.code in text(app, "#code-line"))
        assert "ana (hôte) (toi)" in text(app, "#players")
        assert app.screen.query_one("#start", Button).disabled  # 1 player < 3


async def test_create_form_validation_error(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        app.screen.query_one("#create", Button).press()
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        app.screen.query_one("#deadline", Select).value = "custom"
        await pilot.pause()
        assert app.screen.query_one("#custom-deadline").display
        app.screen.query_one("#custom-deadline", Input).value = "nope"
        app.screen.query_one("#submit", Button).press()
        await until(pilot, lambda: "Durée illisible" in text(app, "#form-error"))
        assert backend.server.games == {} and isinstance(app.screen, CreateScreen)
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))


async def test_public_game_listed_and_joined_from_lobby(backend):
    backend.preregister()
    await register_in_server(backend)
    bob = await backend.script_client("bob")
    await bob.send("create_game", settings={**SETTINGS, "theme": "Le phare"})
    gid = (await bob.until("game_joined"))["game_id"]
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await until(pilot, lambda: option_ids(app, "#public-games") == [gid])
        assert "Le phare" in str(app.screen.query_one("#public-games", OptionList).options[0].prompt)
        public = app.screen.query_one("#public-games", OptionList)
        public.focus()
        await pilot.press("down", "enter")
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        assert (await bob.until("player_joined"))["pseudo"] == "ana"
        assert "bob (hôte)" in text(app, "#players")


async def test_join_private_game_with_code_and_see_new_players_live(backend):
    backend.preregister()
    await register_in_server(backend)
    bob = await backend.script_client("bob")
    await bob.send("create_game", settings={**SETTINGS, "visibility": "private", "desired_players": 5})
    created = await bob.until("game_joined")
    code = created["view"]["code"]
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        assert option_ids(app, "#public-games") == []
        app.screen.query_one("#code", Input).value = code.lower()
        app.screen.query_one("#join-code", Button).press()
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        cleo = await backend.script_client("cleo")
        await cleo.send("join_game", code=code)
        await until(pilot, lambda: "cleo" in text(app, "#players"))
        assert "(3/5)" in text(app, "#players")


async def test_bad_code_shows_error_toast(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        app.screen.query_one("#code", Input).value = "ZZZZZ"
        app.screen.query_one("#join-code", Button).press()
        await until(pilot, lambda: any("introuvable" in n.message for n in app._notifications))


async def test_host_starts_game_and_lobby_shows_it(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        app.screen.query_one("#create", Button).press()
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        app.screen.query_one("#players", Select).value = 6
        app.screen.query_one("#submit", Button).press()
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        code = next(iter(backend.server.games.values())).code
        for name in ("bob", "cleo"):
            c = await backend.script_client(name)
            await c.send("join_game", code=code)
        await until(pilot, lambda: not app.screen.query_one("#start", Button).disabled)
        app.screen.query_one("#start", Button).press()
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        await until(pilot, lambda: any("lancée" in n.message for n in app._notifications))
        label = str(app.screen.query_one("#my-games", OptionList).options[0].prompt)
        assert "à toi" in label or "tour de" in label


async def test_leave_game_returns_to_lobby(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        app.screen.query_one("#create", Button).press()
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        app.screen.query_one("#submit", Button).press()
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        app.screen.query_one("#leave", Button).press()
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        assert option_ids(app, "#my-games") == [] and backend.server.games == {}


async def test_reopening_a_waiting_game_from_my_games(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        app.screen.query_one("#create", Button).press()
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        app.screen.query_one("#submit", Button).press()
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        app.screen.query_one("#my-games", OptionList).focus()
        await pilot.press("down", "enter")
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))


async def test_waiting_room_expiry_removes_game_from_client(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        app.screen.query_one("#create", Button).press()
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        app.screen.query_one("#submit", Button).press()
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        gid = next(iter(backend.server.games))
        game = backend.server.games[gid]
        game.last_activity -= timedelta(days=3)
        await backend.server.expire(gid)
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        assert option_ids(app, "#my-games") == []


async def test_client_reconnects_after_server_side_drop(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        session = backend.server.sessions["ana"]
        await session.close(1011, "drop")  # not the 'replaced' code: the client must retry
        await until(pilot, lambda: backend.server.sessions.get("ana") not in (None, session))
        await until(pilot, lambda: app.status == "online" and app.pseudo == "ana")
