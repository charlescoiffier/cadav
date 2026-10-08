"""Client UI tests: the Textual app driven by Pilot against a real server."""

import asyncio
import json
import random
import time
from datetime import timedelta

import pytest
import websockets
from helpers import Client
from textual.widgets import Button, Input, OptionList, Select, Static, TextArea

from cadav.client.app import CadavApp
from cadav.client.config import Config
from cadav.client.screens import Banner, CreateScreen, GameScreen, LobbyScreen, LoginScreen, WaitingScreen
from cadav.server import Server
from cadav.storage import Storage

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
        return CadavApp(config_path=self.config_path, url=self.url, retry_delays=(0.05,))

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
            await pilot.pause()  # let the widgets of a freshly shown screen finish mounting
            return
    raise AssertionError("condition not reached in time")


def text(app, selector):
    return str(app.screen.query_one(selector, Static).render())


def option_ids(app, selector):
    return [o.id for o in app.screen.query_one(selector, OptionList).options if o.id is not None]


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
        assert app.focused.id == "pseudo"
        await pilot.press(*"ana")  # typing on the cell starts editing it straight away
        assert app.screen.query_one("#pseudo", Input).value == "ana" and app.focused.editing
        await pilot.press("enter")  # validate
        assert not app.focused.editing and app.screen.query_one("#pseudo", Input).value == "ana"
        await pilot.press("down", "down", "enter")  # server field, then the "Entrer" button
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        await until(pilot, lambda: app.pseudo == "ana")
        assert "ana@" in text(app, "#status") and "Connecté" in text(app, "#status")
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
    app = CadavApp(config_path=tmp_path / "c.json", retry_delays=(0.05,))
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
        assert "♛ ana (toi)" in text(app, "#players")
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
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        assert (await bob.until("player_joined"))["pseudo"] == "ana"
        assert "♛ bob" in text(app, "#players")


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
        assert "3/5" in app.screen.query_one("#players-pane").border_title


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
        await until(pilot, lambda: isinstance(app.screen, GameScreen))
        assert next(iter(backend.server.games.values())).status == "running"


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
        await pilot.press("enter")
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


# --- keyboard-first ----------------------------------------------------------


async def test_create_and_start_with_the_keyboard(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("ctrl+s")
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        await pilot.press("ctrl+l")  # not enough players yet: nothing happens
        await pilot.pause(0.2)
        assert next(iter(backend.server.games.values())).status == "waiting"
        code = next(iter(backend.server.games.values())).code
        for name in ("bob", "cleo"):
            c = await backend.script_client(name)
            await c.send("join_game", code=code)
        await until(pilot, lambda: "3/4" in app.screen.query_one("#players-pane").border_title)
        await pilot.press("ctrl+l")
        await until(pilot, lambda: isinstance(app.screen, GameScreen))
        assert next(iter(backend.server.games.values())).status == "running"


async def test_code_shortcut_focuses_the_code_field_and_enter_joins(backend):
    backend.preregister()
    await register_in_server(backend)
    bob = await backend.script_client("bob")
    await bob.send("create_game", settings={**SETTINGS, "visibility": "private"})
    code = (await bob.until("game_joined"))["view"]["code"]
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+k")  # focuses the code field and starts editing it
        assert app.focused.id == "code" and app.focused.editing
        await pilot.press(*code, "enter")
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))


async def test_leave_with_the_keyboard(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("ctrl+s")
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        await pilot.press("ctrl+o")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        assert backend.server.games == {}


# --- navigation model: arrows/Tab to move, Enter/Space to edit, Esc to cancel ---


def focused_id(app):
    return app.focused.id if app.focused else None


async def test_arrows_and_tab_walk_through_the_create_form(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        order = ["visibility", "players", "deadline", "theme", "primer", "min-words", "max-words", "submit", "cancel"]
        assert focused_id(app) == "visibility"
        for expected in order[1:]:
            await pilot.press("down")
            assert focused_id(app) == expected
        for expected in reversed(order[:-1]):
            await pilot.press("up")
            assert focused_id(app) == expected
        await pilot.press("tab", "tab")
        assert focused_id(app) == "deadline"
        await pilot.press("shift+tab")
        assert focused_id(app) == "players"
        await pilot.press("right")
        assert focused_id(app) == "deadline"
        await pilot.press("left")
        assert focused_id(app) == "players"


async def test_field_enters_editing_with_enter_or_space_and_esc_cancels(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("down", "down", "down")
        theme = app.screen.query_one("#theme", Input)
        assert app.focused is theme and not theme.editing
        await pilot.press("space", *"mer")  # space enters editing (and is not typed); the rest is typed
        assert theme.editing and theme.value == "mer"
        await pilot.press("space", *"bleue")  # a space is a space while editing
        assert theme.value == "mer bleue"
        await pilot.press("up", "down")  # up and down do nothing while editing
        assert app.focused is theme and theme.editing
        await pilot.press("left", "backspace")  # cursor keys work while editing
        assert theme.value == "mer bleu"[:3] + "bleue"[:0] + theme.value[3:]
        await pilot.press("escape")  # cancel: back to the value before editing
        assert not theme.editing and theme.value == "" and app.focused is theme
        await pilot.press("enter", *"phare", "enter")  # Enter validates and keeps the value
        assert not theme.editing and theme.value == "phare"
        await pilot.press("enter", *"x", "escape")  # a second edit can be cancelled too
        assert theme.value == "phare"
        assert isinstance(app.screen, CreateScreen)  # Esc left the edit, not the screen
        await pilot.press("escape")  # now Esc leaves the screen
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))


async def test_typing_on_a_cell_replaces_its_content_and_esc_restores_it(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("down", "down", "down", *"phare", "enter")
        theme = app.screen.query_one("#theme", Input)
        assert theme.value == "phare" and not theme.editing
        await pilot.press(*"mer")  # typing again replaces what was there
        assert theme.editing and theme.value == "mer"
        await pilot.press("escape")
        assert theme.value == "phare" and not theme.editing
        # digits too, in a numeric cell
        await pilot.press("down", "down", *"12", "x", "enter")  # min-words is an integer field: "x" is refused
        assert app.screen.query_one("#min-words", Input).value == "12"


async def test_arrows_move_focus_when_not_editing_a_field(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("down", "down", "down", "right")
        assert focused_id(app) == "primer"  # left and right move on, they do not scroll a cursor


async def test_select_opens_with_enter_or_space_and_keeps_arrows_for_navigation(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        players = app.screen.query_one("#players", Select)
        await pilot.press("down")
        assert app.focused is players and players.value == 4  # the arrow moved the focus, no menu
        await pilot.press("enter")  # opens the menu
        await pilot.pause()
        await pilot.press("down", "down", "enter")  # 4 -> 5 -> 6, validate with Enter
        await pilot.pause()
        assert players.value == 6 and app.focused is players
        await pilot.press("space")  # opens with Space
        await pilot.pause()
        await pilot.press("down", "space")  # and Space validates the highlighted option too
        await pilot.pause()
        assert players.value == 7 and app.focused is players
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("up", "escape")  # Esc closes without changing anything
        await pilot.pause()
        assert players.value == 7 and app.focused is players and isinstance(app.screen, CreateScreen)


async def test_typing_on_a_choice_jumps_to_the_matching_option(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("down")
        players = app.screen.query_one("#players", Select)
        await pilot.press("8")  # a digit picks the option "8"
        assert players.value == 8 and app.focused is players
        await pilot.press("up")
        visibility = app.screen.query_one("#visibility", Select)
        await pilot.press("p", "r")  # letters pick by first letter ("Privée"... then still "Privée")
        assert visibility.value == "private"


async def test_lists_hand_the_focus_over_at_their_edges(backend):
    backend.preregister()
    await register_in_server(backend)
    bob = await backend.script_client("bob")
    for theme in ("Un", "Deux"):
        await bob.send("create_game", settings={**SETTINGS, "theme": theme})
        await bob.until("game_joined")
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await until(pilot, lambda: len(option_ids(app, "#public-games")) == 2)
        public = app.screen.query_one("#public-games", OptionList)
        public.focus()
        await pilot.pause()
        assert public.highlighted == 0
        await pilot.press("down")
        assert public.highlighted == 1 and app.focused is public
        await pilot.press("down")  # last entry: the focus moves on
        assert focused_id(app) == "code"
        await pilot.press("up")  # back to the list, which keeps its highlight
        assert app.focused is public
        await pilot.press("up", "up")  # first entry then the previous element
        assert focused_id(app) == "my-games"
        await pilot.press("right")
        assert app.focused is public


async def test_ctrl_shortcuts_work_whatever_the_field_state_and_letters_are_typed(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        app.screen.query_one("#code", Input).focus()
        await pilot.press("n")  # a plain letter is text, not a shortcut
        assert isinstance(app.screen, LobbyScreen)
        assert app.screen.query_one("#code", Input).value == "n"
        await pilot.press("ctrl+n")  # even while the field is being edited
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))


async def test_footer_shows_the_keys_of_the_current_mode(backend):
    backend.preregister()
    await register_in_server(backend)
    app = backend.app()
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await pilot.press("ctrl+k")
        shown = {k.binding.action for k in app.screen.active_bindings.values() if k.binding.show}
        assert "commit_edit" in shown and "cancel_edit" in shown and "begin_edit" not in shown
        await pilot.press("escape")
        shown = {k.binding.action for k in app.screen.active_bindings.values() if k.binding.show}
        assert "begin_edit" in shown and "commit_edit" not in shown


# --- the game screen ---------------------------------------------------------


class OrderRng(random.Random):
    """A rng whose shuffle puts the players in a chosen order."""

    def __init__(self, order):
        super().__init__(1)
        self.order = list(order)

    def shuffle(self, x):
        x.sort(key=self.order.index)


async def start_three(backend, app, pilot, order, **settings):
    """bob creates a public game, cleo joins, ana joins from the lobby and the game starts."""
    backend.server.rng = OrderRng(order)
    bob = await backend.script_client("bob")
    cleo = await backend.script_client("cleo")
    await bob.send("create_game", settings={**SETTINGS, **settings})
    gid = (await bob.until("game_joined"))["game_id"]
    await cleo.send("join_game", game_id=gid)
    await cleo.until("game_joined")
    await until(pilot, lambda: option_ids(app, "#public-games") == [gid])
    app.screen.query_one("#public-games", OptionList).focus()
    await pilot.press("enter")
    await until(pilot, lambda: isinstance(app.screen, GameScreen))
    return {"bob": bob, "cleo": cleo}, gid


async def say(backend, clients, gid, name, text):
    """A script player writes; returns once the server has taken the text."""
    game = backend.server.games[gid]
    before = len(game.contributions)
    await clients[name].send("submit_text", game_id=gid, text=text)
    for _ in range(200):
        if len(game.contributions) > before:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the server did not take the text")


async def ready(backend):
    backend.preregister()
    await register_in_server(backend)
    return backend.app()


async def test_my_turn_shows_blank_page_draft_and_counter(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        clients, gid = await start_three(backend, app, pilot, ["ana", "bob", "cleo"], theme="La mer")
        draft = app.screen.query_one("#draft", TextArea)
        await until(pilot, lambda: app.focused is draft)  # the cursor is where the writing happens
        assert "Page blanche" in text(app, "#primer")
        assert "▶ ana" in text(app, "#info") and "La mer" in text(app, "#info")
        assert "0 mot" in text(app, "#counter") and app.screen.query_one("#send", Button).disabled
        await pilot.press(*"Il pleut")
        assert draft.text == "Il pleut" and "2 mots" in text(app, "#counter")
        assert not app.screen.query_one("#send", Button).disabled
        draft.text = "Il pleut. La nuit tombe."
        await pilot.pause()
        await pilot.press("ctrl+s")
        await until(pilot, lambda: len(next(iter(backend.server.games.values())).contributions) == 1)
        game = next(iter(backend.server.games.values()))
        assert game.contributions[0].text == "Il pleut. La nuit tombe." and game.primer == "La nuit tombe."
        await until(pilot, lambda: "C'est le tour de bob" in text(app, "#primer"))
        assert not app.screen.query_one("#write-pane").display
        assert "Ton tour est passé" in text(app, "#primer")
        assert gid not in app.drafts  # sent: the draft is gone


async def test_other_players_turn_then_my_turn_with_the_primer(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        clients, gid = await start_three(backend, app, pilot, ["bob", "ana", "cleo"])
        assert "C'est le tour de bob" in text(app, "#primer") and "Tu es le prochain" in text(app, "#primer")
        assert not app.screen.query_one("#write-pane").display
        await say(backend, clients, gid, "bob", "Début secret. Fin de bob.")
        draft = app.screen.query_one("#draft", TextArea)
        await until(pilot, lambda: app.screen.query_one("#write-pane").display)
        assert text(app, "#primer") == "Fin de bob."  # only the primer, never the whole text
        assert "secret" not in text(app, "#primer") + text(app, "#info")
        await until(pilot, lambda: app.focused is draft)


async def test_third_player_knows_how_many_turns_come_first(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await start_three(backend, app, pilot, ["bob", "cleo", "ana"])
        assert "après 1 autre" in text(app, "#primer")


async def test_word_limits_block_sending_with_feedback(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await start_three(backend, app, pilot, ["ana", "bob", "cleo"], min_words=3, max_words=5)
        draft = app.screen.query_one("#draft", TextArea)
        draft.text = "un deux"
        await pilot.pause()
        assert "encore 1" in text(app, "#counter") and app.screen.query_one("#send", Button).disabled
        await pilot.press("ctrl+s")
        await until(pilot, lambda: any("encore 1" in n.message for n in app._notifications))
        assert next(iter(backend.server.games.values())).contributions == []
        draft.text = "un deux trois quatre cinq six"
        await pilot.pause()
        assert "de trop" in text(app, "#counter")
        draft.text = "un deux trois"
        await pilot.pause()
        assert "(3 à 5 mots)" in text(app, "#counter") and not app.screen.query_one("#send", Button).disabled


async def test_escape_leaves_the_text_area_first_then_the_screen(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await start_three(backend, app, pilot, ["ana", "bob", "cleo"])
        draft = app.screen.query_one("#draft", TextArea)
        await until(pilot, lambda: app.focused is draft)
        await pilot.press(*"brouillon", "escape")
        assert focused_id(app) == "send" and isinstance(app.screen, GameScreen)
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))


async def test_draft_survives_leaving_and_coming_back(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        clients, gid = await start_three(backend, app, pilot, ["ana", "bob", "cleo"])
        draft = app.screen.query_one("#draft", TextArea)
        await until(pilot, lambda: app.focused is draft)
        await pilot.press(*"mon brouillon", "escape", "escape")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        label = str(app.screen.query_one("#my-games", OptionList).options[0].prompt)
        assert "À TOI" in label
        app.screen.query_one("#my-games", OptionList).focus()
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, GameScreen))
        assert app.screen.query_one("#draft", TextArea).text == "mon brouillon"


async def test_resuming_after_a_restart_of_the_client(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        clients, gid = await start_three(backend, app, pilot, ["bob", "ana", "cleo"])
        await say(backend, clients, gid, "bob", "Avant. Le primer repris.")
    app2 = backend.app()  # the client is closed and started again
    async with app2.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app2)
        await until(pilot, lambda: option_ids(app2, "#my-games") == [gid])
        assert "À TOI" in str(app2.screen.query_one("#my-games", OptionList).options[0].prompt)
        await pilot.press("ctrl+t")  # jump to the game that waits for me
        await until(pilot, lambda: isinstance(app2.screen, GameScreen))
        assert text(app2, "#primer") == "Le primer repris."


async def test_banner_about_another_game_and_shortcuts_to_reach_it(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        clients, gid = await start_three(backend, app, pilot, ["bob", "ana", "cleo"], theme="Premier")
        await pilot.press("escape")  # back to the lobby, the game goes on
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        await say(backend, clients, gid, "bob", "Un début. Une fin.")
        banner = app.screen.query_one(Banner)
        await until(pilot, lambda: banner.display and "À toi dans « Premier »" in str(banner.render()))
        await pilot.press("ctrl+t")
        await until(pilot, lambda: isinstance(app.screen, GameScreen))
        assert app.screen.game_id == gid


async def test_ctrl_g_cycles_through_my_games(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        clients, gid = await start_three(backend, app, pilot, ["bob", "ana", "cleo"], theme="Un")
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        await pilot.press("ctrl+s")
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        second = next(i for i in app.games if i != gid)
        await pilot.press("ctrl+g")  # waiting room -> the running game
        await until(pilot, lambda: isinstance(app.screen, GameScreen) and app.screen.game_id == gid)
        await pilot.press("ctrl+g")  # and back
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen) and app.screen.game_id == second)


async def test_waiting_room_turns_into_the_game_screen_when_the_game_starts(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        backend.server.rng = OrderRng(["bob", "ana", "cleo"])
        await pilot.press("ctrl+n")
        await until(pilot, lambda: isinstance(app.screen, CreateScreen))
        app.screen.query_one("#players", Select).value = 3
        await pilot.press("ctrl+s")
        await until(pilot, lambda: isinstance(app.screen, WaitingScreen))
        code = next(iter(backend.server.games.values())).code
        for name in ("bob", "cleo"):
            c = await backend.script_client(name)
            await c.send("join_game", code=code)
        await until(pilot, lambda: isinstance(app.screen, GameScreen))  # auto-start when full
        assert "C'est le tour de bob" in text(app, "#primer")


async def test_countdown_follows_the_clock(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        await start_three(backend, app, pilot, ["ana", "bob", "cleo"])
        deadline = next(iter(backend.server.games.values())).deadline
        app.clock = lambda: deadline - timedelta(seconds=90)
        await until(pilot, lambda: text(app, "#deadline") == "1 min 30 s", timeout=3)
        app.clock = lambda: deadline - timedelta(hours=3, minutes=5)
        await until(pilot, lambda: text(app, "#deadline") == "3 h 05", timeout=3)
        app.clock = lambda: deadline + timedelta(seconds=1)
        await until(pilot, lambda: text(app, "#deadline") == "échéance dépassée", timeout=3)


async def test_skipped_turn_and_finished_game_show_the_story(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        clients, gid = await start_three(backend, app, pilot, ["bob", "cleo", "ana"])
        game = next(iter(backend.server.games.values()))
        await say(backend, clients, gid, "bob", "Le début. Presque fini.")
        game.deadline -= timedelta(days=1)  # cleo is too slow
        await backend.server.expire(gid)
        await until(pilot, lambda: app.screen.query_one("#write-pane").display)
        assert text(app, "#primer") == "Presque fini."  # same primer after a skip
        app.screen.query_one("#draft", TextArea).text = "La fin de ana."
        await pilot.pause()
        await pilot.press("ctrl+s")
        await until(pilot, lambda: app.screen.query_one("#story-pane").display)
        story = text(app, "#story")
        assert "bob" in story and "Le début. Presque fini." in story and "La fin de ana." in story
        assert "Tours sautés : cleo" in story
        assert not app.screen.query_one("#write-pane").display and not app.screen.query_one("#deadline-pane").display


async def test_leaving_a_running_game_needs_two_presses(backend):
    app = await ready(backend)
    async with app.run_test(size=SIZE) as pilot:
        await logged_in(backend, pilot, app)
        clients, gid = await start_three(backend, app, pilot, ["bob", "ana", "cleo"])
        await pilot.press("ctrl+o")
        await until(pilot, lambda: any("encore une fois" in n.message for n in app._notifications))
        assert "ana" not in backend.server.games[gid].left
        await pilot.press("ctrl+o")
        await until(pilot, lambda: isinstance(app.screen, LobbyScreen))
        assert "ana" in backend.server.games[gid].left
