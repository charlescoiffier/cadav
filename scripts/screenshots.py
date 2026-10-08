"""Regenerate the README screenshots (docs/images/*.png) from the real client.

Starts a throwaway server in-process, drives the Textual app with its test pilot
and converts the SVG exports with ``rsvg-convert`` (brew install librsvg).
Usage: ``.venv/bin/python scripts/screenshots.py``
"""

import asyncio
import json
import random
import subprocess
import tempfile
from pathlib import Path

import websockets

from cadav.client.app import CadavApp
from cadav.client.config import Config
from cadav.protocol import PROTOCOL_VERSION
from cadav.server import Server
from cadav.storage import Storage

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
SIZE = (110, 30)


async def player(url: str, name: str, secret: str | None = None):
    ws = await websockets.connect(url)

    async def send(type, **fields):
        await ws.send(json.dumps({"v": PROTOCOL_VERSION, "type": type, **fields}))

    async def until(kind):
        while json.loads(await ws.recv())["type"] != kind:
            pass

    await send("register", pseudo=name, secret=secret or f"secret-{name}")
    await until("my_games")
    return ws, send, until


def save(app, name: str) -> None:
    svg = Path(tempfile.mkdtemp()) / f"{name}.svg"
    svg.write_text(app.export_screenshot())
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsvg-convert", "-w", "1100", str(svg), "-o", str(OUT / f"{name}.png")], check=True)


class OrderRng(random.Random):
    """A rng whose shuffle puts the players in a chosen order (for a predictable screenshot)."""

    def __init__(self, order):
        super().__init__(1)
        self.order = list(order)

    def shuffle(self, x):
        x.sort(key=self.order.index)


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    server = Server(Storage(tmp / "data"), rng=random.Random(11))
    await server.start()
    async with server.listen("127.0.0.1", 0) as ws_server:
        url = f"ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}"

        # other players, so that the lobby is not empty
        for name, theme in (("bob", "Une enquête dans un phare"), ("cleo", "Le dernier train de nuit")):
            _, send, until = await player(url, name)
            await send("create_game", settings={"desired_players": 5, "turn_seconds": 86400, "theme": theme})
            await until("game_joined")

        config = tmp / "client.json"
        Config("", "", url, export_dir="~/Documents/cadav").save(config)
        app = CadavApp(config_path=config, url=url, retry_delays=(0.05,))
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.3)
            save(app, "connexion")
            app.screen.query_one("#pseudo").value = "ana"
            app.screen.query_one("#connect").press()
            await pilot.pause(0.8)
            save(app, "lobby")
            await pilot.press("ctrl+n")
            await pilot.pause(0.4)
            await pilot.press("down", "down", "down", "enter")  # the theme field, in editing mode
            await pilot.press(*"Un naufrage")
            app.screen.query_one("#min-words").value = "10"
            app.screen.query_one("#max-words").value = "60"
            await pilot.pause(0.2)
            save(app, "creation")
            app.screen.query_one("#theme").value = "Le phare dans le brouillard"
            await pilot.press("ctrl+s")
            await pilot.pause(0.6)
            game = next(g for g in server.games.values() if g.host == "ana")
            players = {}
            for name in ("dan", "eve"):
                players[name] = await player(url, name)
                await players[name][1]("join_game", code=game.code)
            await pilot.pause(0.6)
            save(app, "salle-attente")

            # the fourth player fills the room: the game starts, dan writes first
            server.rng = OrderRng(["dan", "ana", "eve", "fay"])
            players["fay"] = await player(url, "fay")
            await players["fay"][1]("join_game", code=game.code)
            await pilot.pause(0.6)
            await players["dan"][1](
                "submit_text", game_id=game.id,
                text="Le brouillard avait tout avalé, même le phare. Personne n'osait plus parler de la tempête.",
            )
            await pilot.pause(0.6)
            draft = app.screen.query_one("#draft")
            draft.text = "On entendait pourtant, très loin, une cloche qui ne sonnait pas à l'heure."
            await pilot.pause(0.3)
            save(app, "partie")

            await pilot.press("ctrl+s")
            await pilot.pause(0.5)
            await players["eve"][1]("submit_text", game_id=game.id, text="Eve ouvrit la porte du phare et trouva la lampe éteinte.")
            await pilot.pause(0.4)
            await players["fay"][1]("submit_text", game_id=game.id, text="Alors le brouillard se leva d'un seul coup, comme un rideau.")
            await pilot.pause(0.8)
            save(app, "histoire")
    await server.close()


if __name__ == "__main__":
    asyncio.run(main())
