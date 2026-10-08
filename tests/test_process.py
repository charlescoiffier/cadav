"""The server as a real process: start-up, a whole game over the network, SIGTERM, restart, TLS."""

import asyncio
import json
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time

import pytest
import websockets

from cadav.protocol import PROTOCOL_VERSION


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerProcess:
    def __init__(self, data_dir, *extra, port=None):
        self.port = port or free_port()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "cadav.cli", "serve", "--port", str(self.port), "--data-dir", str(data_dir), *extra],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"the server stopped: {self.proc.stderr.read().decode()}")
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        self.proc.kill()
        raise RuntimeError("the server did not start")

    def stop(self) -> int:
        self.proc.send_signal(signal.SIGTERM)
        code = self.proc.wait(timeout=10)
        self.proc.stderr.close()
        return code

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc.stderr.close()


class Player:
    def __init__(self, ws):
        self.ws = ws

    async def send(self, type, **fields):
        await self.ws.send(json.dumps({"v": PROTOCOL_VERSION, "type": type, **fields}))

    async def until(self, type, timeout=5):
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
            if msg["type"] == type:
                return msg


async def connect(port, name, scheme="ws", **kw):
    player = Player(await websockets.connect(f"{scheme}://localhost:{port}", **kw))
    await player.send("register", pseudo=name, secret=f"secret-{name}")
    await player.until("my_games")
    return player


async def play_a_game(port, scheme="ws", **kw):
    """Three players write one contribution each, over real sockets. Returns the game id."""
    names = ["ana", "bob", "cleo"]
    players = {n: await connect(port, n, scheme, **kw) for n in names}
    await players["ana"].send(
        "create_game", settings={"desired_players": 3, "turn_seconds": 3600, "theme": "Essai réel"}
    )
    game_id = (await players["ana"].until("game_joined"))["game_id"]
    for n in ("bob", "cleo"):
        await players[n].send("join_game", game_id=game_id)
    views = {n: (await players[n].until("game_started"))["view"] for n in names}
    for writer in views["ana"]["players"]:
        await players[writer].send("submit_text", game_id=game_id, text=f"Texte de {writer}. Fin de {writer}.")
        await asyncio.sleep(0.15)
    finished = await players["ana"].until("game_finished")
    assert [p["author"] for p in finished["view"]["story"]] == views["ana"]["players"]
    for p in players.values():
        await p.ws.close()
    return game_id


def test_server_process_serves_a_whole_game_and_survives_a_restart(tmp_path):
    server = ServerProcess(tmp_path)
    try:
        game_id = asyncio.run(play_a_game(server.port))
        assert server.stop() == 0  # SIGTERM: clean exit
    finally:
        server.kill()
    assert list((tmp_path / "archive").glob("*.json")) and not list((tmp_path / "games").glob("*.json"))

    again = ServerProcess(tmp_path)  # same data directory, a new process
    try:
        async def check():
            player = Player(await websockets.connect(f"ws://127.0.0.1:{again.port}"))
            await player.send("auth", pseudo="bob", secret="secret-bob")
            await player.until("auth_ok")
            mine = (await player.until("my_games"))["games"]
            await player.ws.close()
            return mine

        mine = asyncio.run(check())
        assert [g["game_id"] for g in mine] == [game_id] and mine[0]["status"] == "finished"
        assert [p["author"] for p in mine[0]["story"]] and mine[0]["settings"]["theme"] == "Essai réel"
        assert again.stop() == 0
    finally:
        again.kill()


def test_a_game_in_progress_is_restored_after_a_restart(tmp_path):
    server = ServerProcess(tmp_path)
    try:
        async def start():
            players = {n: await connect(server.port, n) for n in ("ana", "bob", "cleo")}
            await players["ana"].send("create_game", settings={"desired_players": 3, "turn_seconds": 3600})
            gid = (await players["ana"].until("game_joined"))["game_id"]
            for n in ("bob", "cleo"):
                await players[n].send("join_game", game_id=gid)
            view = (await players["ana"].until("game_started"))["view"]
            for p in players.values():
                await p.ws.close()
            return gid, view["players"]

        gid, order = asyncio.run(start())
        assert server.stop() == 0
    finally:
        server.kill()
    again = ServerProcess(tmp_path)
    try:
        async def check():
            player = Player(await websockets.connect(f"ws://127.0.0.1:{again.port}"))
            await player.send("auth", pseudo=order[0], secret=f"secret-{order[0]}")
            await player.until("auth_ok")
            view = (await player.until("my_games"))["games"][0]
            await player.ws.close()
            return view

        view = asyncio.run(check())
        assert view["game_id"] == gid and view["status"] == "running"
        assert view["my_turn"] and view["players"] == order  # the order and the turn were kept
        assert again.stop() == 0
    finally:
        again.kill()


def test_health_endpoint_of_the_real_process(tmp_path):
    server = ServerProcess(tmp_path)
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/health", timeout=5) as reply:
            assert reply.status == 200 and reply.read() == b"ok\n"
        server.stop()
    finally:
        server.kill()


def test_public_address_without_tls_is_refused(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "cadav.cli", "serve", "--host", "0.0.0.0", "--data-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2 and "sans chiffrement" in result.stderr


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is needed to make a test certificate")
def test_tls_server_plays_a_game_over_wss(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
         "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
        check=True, capture_output=True,
    )
    server = ServerProcess(tmp_path / "data", "--cert", str(cert), "--key", str(key))
    try:
        context = ssl.create_default_context(cafile=str(cert))
        game_id = asyncio.run(play_a_game(server.port, "wss", ssl=context))
        assert game_id
        # a client that does not know this certificate is refused: the check is really done
        async def untrusted():
            with pytest.raises(ssl.SSLError):
                await websockets.connect(f"wss://localhost:{server.port}")

        asyncio.run(untrusted())
        assert server.stop() == 0
    finally:
        server.kill()
