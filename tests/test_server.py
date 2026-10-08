"""End-to-end tests: a real WebSocket server driven by scripted clients."""

import asyncio
import json
import random
from datetime import UTC, datetime, timedelta

import pytest
import websockets

from cadavre.protocol import PROTOCOL_VERSION
from cadavre.server import CLOSE_REPLACED, Limits, Server
from cadavre.storage import Storage

T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)
SETTINGS = {"desired_players": 3, "turn_seconds": 120}


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class Client:
    def __init__(self, ws, name=None):
        self.ws, self.name = ws, name

    async def send(self, type, **fields):
        await self.ws.send(json.dumps({"v": PROTOCOL_VERSION, "type": type, **fields}))

    async def recv(self, timeout=2):
        return json.loads(await asyncio.wait_for(self.ws.recv(), timeout))

    async def until(self, type, timeout=2):
        """Next message of this type; fails if another one of these arrives first only by timeout."""
        while True:
            msg = await self.recv(timeout)
            if msg["type"] == type:
                return msg

    async def nothing(self, delay=0.05):
        with pytest.raises(asyncio.TimeoutError):
            await self.recv(delay)


class Env:
    def __init__(self, tmp_path, limits=None):
        self.clock = Clock()
        self.storage = Storage(tmp_path)
        self.limits = limits
        self.server = None
        self.ws_server = None
        self.clients = []

    async def boot(self):
        self.server = Server(self.storage, self.clock, random.Random(7), self.limits)
        await self.server.start()
        self.ws_server = await self.server.listen("127.0.0.1", 0).__aenter__()
        self.port = self.ws_server.sockets[0].getsockname()[1]

    async def shutdown(self):
        for c in self.clients:
            await c.ws.close()
        await self.ws_server.__aexit__(None, None, None)
        await self.server.close()

    async def connect(self, name=None):
        c = Client(await websockets.connect(f"ws://127.0.0.1:{self.port}"), name)
        self.clients.append(c)
        return c

    async def login(self, name):
        c = await self.connect(name)
        await c.send("register", pseudo=name, secret=f"secret-{name}")
        assert (await c.recv())["type"] == "auth_ok"
        assert (await c.recv())["type"] == "my_games"
        return c

    async def full_game(self, **settings):
        """Three players in a started game; returns (clients by name, game_id, first view)."""
        ana, bob, cleo = [await self.login(n) for n in ("ana", "bob", "cleo")]
        await ana.send("create_game", settings={**SETTINGS, **settings})
        gid = (await ana.until("game_joined"))["game_id"]
        await bob.send("join_game", game_id=gid)
        await cleo.send("join_game", game_id=gid)
        started = {}
        for c in (ana, bob, cleo):
            started[c.name] = await c.until("game_started")
        return {c.name: c for c in (ana, bob, cleo)}, gid, started


@pytest.fixture
async def env(tmp_path):
    e = Env(tmp_path)
    await e.boot()
    yield e
    await e.shutdown()


# --- accounts ---------------------------------------------------------------


async def test_register_then_auth_on_new_connection(env):
    ana = await env.login("ana")
    await ana.ws.close()
    again = await env.connect("ana")
    await again.send("auth", pseudo="ana", secret="secret-ana")
    assert (await again.recv()) == {"v": 1, "type": "auth_ok", "pseudo": "ana"}
    assert (await again.recv())["games"] == []


async def test_pseudo_unique_case_insensitive_and_validated(env):
    await env.login("Ana")
    c = await env.connect()
    await c.send("register", pseudo="ANA", secret="x")
    assert (await c.recv())["code"] == "pseudo_taken"
    await c.send("register", pseudo="a b!", secret="x")
    assert (await c.recv())["code"] == "bad_pseudo"
    await c.send("auth", pseudo="ana", secret="secret-Ana")  # case-insensitive login
    assert (await c.recv())["pseudo"] == "Ana"


async def test_bad_credentials(env):
    await env.login("ana")
    c = await env.connect()
    await c.send("auth", pseudo="ana", secret="wrong")
    assert (await c.recv())["code"] == "bad_credentials"
    await c.send("auth", pseudo="ghost", secret="x")
    assert (await c.recv())["code"] == "bad_credentials"


async def test_users_file_holds_hash_not_secret(env):
    await env.login("ana")
    raw = env.storage.users_path.read_text()
    assert "secret-ana" not in raw and '"hash"' in raw and '"salt"' in raw


async def test_must_authenticate_first(env):
    c = await env.connect()
    await c.send("list_games")
    assert (await c.recv())["code"] == "not_authenticated"


async def test_old_client_version_refused_and_closed(env):
    c = await env.connect()
    await c.ws.send(json.dumps({"v": 99, "type": "list_games"}))
    assert (await c.recv())["code"] == "unsupported_version"
    with pytest.raises(websockets.ConnectionClosed):
        await c.recv()


async def test_garbage_message_gets_an_error(env):
    c = await env.connect()
    await c.ws.send("not json")
    assert (await c.recv())["code"] == "bad_message"


async def test_new_connection_replaces_the_old_one(env):
    old = await env.login("ana")
    new = await env.connect("ana")
    await new.send("auth", pseudo="ana", secret="secret-ana")
    await new.until("my_games")
    with pytest.raises(websockets.ConnectionClosed):
        await old.recv()
    assert old.ws.close_code == CLOSE_REPLACED


async def test_auth_attempts_are_rate_limited(tmp_path):
    e = Env(tmp_path, Limits(auth_attempts=3))
    await e.boot()
    try:
        c = await e.connect()
        for _ in range(3):
            await c.send("auth", pseudo="ghost", secret="x")
            assert (await c.recv())["code"] == "bad_credentials"
        await c.send("auth", pseudo="ghost", secret="x")
        assert (await c.recv())["code"] == "too_many_attempts"
        e.clock.advance(minutes=11)
        await c.send("auth", pseudo="ghost", secret="x")
        assert (await c.recv())["code"] == "bad_credentials"
    finally:
        await e.shutdown()


# --- a full game ------------------------------------------------------------


async def test_full_game_with_private_views(env):
    clients, gid, started = await env.full_game()
    order = started["ana"]["view"]["players"]
    assert sorted(order) == ["ana", "bob", "cleo"]
    texts = ["Alpha secret. Fin alpha.", "Bravo secret. Fin bravo.", "Charlie secret. Fin charlie."]

    for name in order[1:]:  # the opening turn_started, addressed to everyone
        opening = await clients[name].until("turn_started")
        assert not opening["view"]["my_turn"]

    for i, text in enumerate(texts):
        current = order[i]
        turn = await clients[current].until("turn_started")
        assert turn["view"]["my_turn"] and turn["view"]["current_player"] == current
        if i > 0:
            assert turn["view"]["primer"] == ["Fin alpha.", "Fin bravo."][i - 1]
        await clients[current].send("submit_text", game_id=gid, text=text)
        if i < 2:
            for name, c in clients.items():
                if name != order[i + 1]:
                    msg = await c.until("turn_started")
                    blob = json.dumps(msg)
                    assert not msg["view"]["my_turn"] and msg["view"].get("primer") is None
                    assert all(t not in blob for t in texts[: i + 1])

    for c in clients.values():
        done = await c.until("game_finished")
        assert [p["text"] for p in done["view"]["story"]] == texts
        assert [p["author"] for p in done["view"]["story"]] == order

    assert env.storage.load_games() == []
    assert len(list(env.storage.archive_dir.glob("*.json"))) == 1

    # A player who reconnects later still finds the story.
    await clients["bob"].ws.close()
    bob = await env.connect("bob")
    await bob.send("auth", pseudo="bob", secret="secret-bob")
    await bob.until("auth_ok")
    mine = (await bob.until("my_games"))["games"]
    assert mine[0]["status"] == "finished" and len(mine[0]["story"]) == 3


async def test_only_current_player_receives_primer_in_my_games(env):
    clients, gid, started = await env.full_game()
    order = started["ana"]["view"]["players"]
    await clients[order[0]].send("submit_text", game_id=gid, text="Début. Le secret du premier.")
    await clients[order[1]].until("turn_started")
    for name in order:
        await clients[name].ws.close()
        c = await env.connect(name)
        await c.send("auth", pseudo=name, secret=f"secret-{name}")
        await c.until("auth_ok")
        view = (await c.until("my_games"))["games"][0]
        assert (view["primer"] == "Le secret du premier.") == (name == order[1])
        assert view.get("story") is None
        assert "Début" not in json.dumps(view)
        clients[name] = c


async def test_game_actions_check_membership_and_turn(env):
    clients, gid, started = await env.full_game()
    order = started["ana"]["view"]["players"]
    outsider = await env.login("zed")
    await outsider.send("submit_text", game_id=gid, text="intrus")
    assert (await outsider.recv())["code"] == "not_in_game"
    await outsider.send("leave_game", game_id=gid)
    assert (await outsider.recv())["code"] == "not_in_game"
    await clients[order[1]].send("submit_text", game_id=gid, text="trop tôt")
    err = await clients[order[1]].until("error")
    assert err["code"] == "not_your_turn" and err["game_id"] == gid


# --- lobby ------------------------------------------------------------------


async def test_public_game_listed_and_lobby_pushed_to_watchers(env):
    ana, bob = await env.login("ana"), await env.login("bob")
    await bob.send("list_games")
    assert (await bob.until("lobby_update"))["games"] == []
    await ana.send("create_game", settings={**SETTINGS, "theme": "mer"})
    gid = (await ana.until("game_joined"))["game_id"]
    pushed = (await bob.until("lobby_update"))["games"]
    assert [(g["game_id"], g["theme"], g["players"]) for g in pushed] == [(gid, "mer", 1)]
    assert "code" not in pushed[0]
    await bob.send("join_game", game_id=gid)
    assert (await bob.until("lobby_update"))["games"][0]["players"] == 2


async def test_private_game_joinable_by_code_only(env):
    ana, bob = await env.login("ana"), await env.login("bob")
    await ana.send("create_game", settings={**SETTINGS, "visibility": "private"})
    joined = await ana.until("game_joined")
    code = joined["view"]["code"]
    assert len(code) == 5
    await bob.send("list_games")
    assert (await bob.until("lobby_update"))["games"] == []
    await bob.send("join_game", game_id=joined["game_id"])
    assert (await bob.until("error"))["code"] == "game_not_found"
    await bob.send("join_game", code=code.lower())
    view = (await bob.until("game_joined"))["view"]
    assert view["players"] == ["ana", "bob"] and view["code"] == code
    assert (await ana.until("player_joined"))["pseudo"] == "bob"


async def test_join_refusals(env):
    clients, gid, _ = await env.full_game()
    late = await env.login("dan")
    await late.send("join_game", game_id=gid)
    assert (await late.until("error"))["code"] == "game_started"
    await late.send("join_game", game_id="nope")
    assert (await late.until("error"))["code"] == "game_not_found"
    await clients["ana"].send("join_game", game_id=gid)
    assert (await clients["ana"].until("error"))["code"] == "game_started"


async def test_waiting_room_leave_transfers_host_and_deletes_when_empty(env):
    ana, bob = await env.login("ana"), await env.login("bob")
    await ana.send("create_game", settings={**SETTINGS, "desired_players": 5})
    gid = (await ana.until("game_joined"))["game_id"]
    await bob.send("join_game", game_id=gid)
    await ana.until("player_joined")
    await ana.send("leave_game", game_id=gid)
    assert (await ana.until("my_games"))["games"] == []
    left = await bob.until("player_left")
    assert left["pseudo"] == "ana" and left["view"]["host"] == "bob"
    await bob.send("leave_game", game_id=gid)
    await bob.until("my_games")
    assert env.server.games == {} and env.storage.load_games() == []


async def test_host_starts_early_with_three_players(env):
    ana, bob, cleo = [await env.login(n) for n in ("ana", "bob", "cleo")]
    await ana.send("create_game", settings={**SETTINGS, "desired_players": 5})
    gid = (await ana.until("game_joined"))["game_id"]
    await bob.send("join_game", game_id=gid)
    await bob.until("game_joined")
    await bob.send("start_game", game_id=gid)
    assert (await bob.until("error"))["code"] == "not_host"
    await ana.send("start_game", game_id=gid)
    assert (await ana.until("error"))["code"] == "not_enough_players"
    await cleo.send("join_game", game_id=gid)
    await ana.send("start_game", game_id=gid)
    assert (await ana.until("game_started"))["view"]["status"] == "running"


# --- limits -----------------------------------------------------------------


async def test_cap_of_five_active_games(env):
    ana, bob = await env.login("ana"), await env.login("bob")
    ids = []
    for _ in range(5):
        await ana.send("create_game", settings=SETTINGS)
        ids.append((await ana.until("game_joined"))["game_id"])
    await ana.send("create_game", settings=SETTINGS)
    assert (await ana.until("error"))["code"] == "too_many_games"
    for gid in ids:
        await bob.send("join_game", game_id=gid)
        await bob.until("game_joined")
    await ana.send("leave_game", game_id=ids[0])
    await ana.until("my_games")
    await ana.send("create_game", settings=SETTINGS)
    await ana.until("game_joined")


async def test_creation_rate_limit_and_server_capacity(tmp_path):
    e = Env(tmp_path, Limits(creations_per_hour=2, max_games=3))
    await e.boot()
    try:
        ana, bob = await e.login("ana"), await e.login("bob")
        for _ in range(2):
            await ana.send("create_game", settings=SETTINGS)
            await ana.until("game_joined")
        await ana.send("create_game", settings=SETTINGS)
        assert (await ana.until("error"))["code"] == "too_many_creations"
        e.clock.advance(hours=1, minutes=1)
        await ana.send("create_game", settings=SETTINGS)
        await ana.until("game_joined")  # 3 live games: the server is now full
        await bob.send("create_game", settings=SETTINGS)
        assert (await bob.until("error"))["code"] == "server_full"
    finally:
        await e.shutdown()


# --- deadlines and persistence ---------------------------------------------


async def test_turn_deadline_skips_player(env):
    clients, gid, started = await env.full_game()
    order = started["ana"]["view"]["players"]
    env.clock.advance(seconds=121)
    await env.server.check_deadlines()
    skipped = await clients["ana"].until("turn_skipped")
    assert skipped["pseudo"] == order[0]
    assert skipped["view"]["current_player"] == order[1]
    nxt = await clients[order[1]].until("turn_started")
    assert nxt["view"]["my_turn"] and nxt["view"]["primer"] is None


async def test_real_timer_fires_when_deadline_arrives(tmp_path):
    e = Env(tmp_path)
    await e.boot()
    try:
        clients, gid, started = await e.full_game(turn_seconds=30)
        e.clock.advance(seconds=31)
        # Re-arm the timer as overdue: the clock is faked, so it must fire at once.
        e.server._timers[gid].cancel()
        e.server._timers[gid] = asyncio.create_task(e.server._timer(gid, e.clock()))
        await clients["ana"].until("turn_skipped", timeout=3)
    finally:
        await e.shutdown()


async def test_waiting_room_expires(env):
    ana, bob = await env.login("ana"), await env.login("bob")
    await bob.send("list_games")
    await bob.until("lobby_update")
    await ana.send("create_game", settings=SETTINGS)
    gid = (await ana.until("game_joined"))["game_id"]
    await bob.until("lobby_update")
    env.clock.advance(minutes=16)
    await env.server.check_deadlines()
    err = await ana.until("error")
    assert err["code"] == "game_expired" and err["game_id"] == gid
    assert (await bob.until("lobby_update"))["games"] == []
    assert env.server.games == {} and env.storage.load_games() == []


async def test_leaving_running_game_passes_the_turn(env):
    clients, gid, started = await env.full_game()
    order = started["ana"]["view"]["players"]
    await clients[order[0]].send("leave_game", game_id=gid)
    left = await clients[order[1]].until("player_left")
    assert left["pseudo"] == order[0]
    turn = await clients[order[1]].until("turn_started")
    assert turn["view"]["current_player"] == order[1]


async def test_state_survives_restart(tmp_path):
    e = Env(tmp_path)
    await e.boot()
    clients, gid, started = await e.full_game()
    order = started["ana"]["view"]["players"]
    await clients[order[0]].send("submit_text", game_id=gid, text="Avant. Le redémarrage.")
    await clients[order[1]].until("turn_started")
    await e.shutdown()

    e2 = Env(tmp_path)
    e2.clock.t = T0 + timedelta(seconds=500)  # the second player's deadline passed while down
    await e2.boot()
    try:
        assert gid in e2.server.games and gid in e2.server._timers
        c = await e2.connect(order[2])
        await c.send("auth", pseudo=order[2], secret=f"secret-{order[2]}")
        await c.until("auth_ok")
        await asyncio.sleep(0.1)  # let the overdue timer fire
        view = e2.server.games[gid]
        assert view.skipped == [order[1]]
        assert (await c.until("my_games"))["games"][0]["game_id"] == gid
    finally:
        await e2.shutdown()
