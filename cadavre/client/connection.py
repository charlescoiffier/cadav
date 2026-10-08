"""WebSocket connection to the server, with automatic reconnection."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from cadavre.protocol import ProtocolError, dump_message, parse_server_message

log = logging.getLogger("cadavre.client")

CLOSE_REPLACED = 4000
CLOSE_VERSION = 4001
RETRY_DELAYS = (1, 2, 4, 8)


class Connection:
    """Keeps one WebSocket open; calls ``hello()`` after every (re)connection.

    ``on_message`` receives each parsed server message, ``on_state`` receives one of
    ``"connecting"``, ``"online"``, ``"offline"``, ``"replaced"``, ``"outdated"``.
    """

    def __init__(
        self,
        url: str,
        hello: Callable[[], object],
        on_message: Callable[[object], Awaitable[None] | None],
        on_state: Callable[[str], None],
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ) -> None:
        self.url = url
        self._hello = hello
        self._on_message = on_message
        self._on_state = on_state
        self._retry_delays = retry_delays
        self._ws = None
        self._stopped = False

    @property
    def online(self) -> bool:
        return self._ws is not None

    async def send(self, msg) -> bool:
        if self._ws is None:
            return False
        try:
            await self._ws.send(dump_message(msg))
        except ConnectionClosed:
            return False
        return True

    def stop(self) -> None:
        self._stopped = True
        if self._ws is not None:
            asyncio.ensure_future(self._ws.close())

    async def run(self) -> None:
        attempt = 0
        while not self._stopped:
            self._notify_state("connecting")
            try:
                async with websockets.connect(self.url, max_size=1 << 20) as ws:
                    self._ws = ws
                    attempt = 0
                    self._notify_state("online")
                    await self.send(self._hello())
                    async for raw in ws:
                        await self._handle(raw)
                    code = ws.close_code
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
            except (OSError, websockets.InvalidURI, websockets.InvalidHandshake):
                code = None
            finally:
                self._ws = None
            if self._stopped:
                return
            if code == CLOSE_REPLACED:
                self._notify_state("replaced")
                return
            if code == CLOSE_VERSION:
                self._notify_state("outdated")
                return
            self._notify_state("offline")
            await asyncio.sleep(self._retry_delays[min(attempt, len(self._retry_delays) - 1)])
            attempt += 1

    def _notify_state(self, state: str) -> None:
        try:
            self._on_state(state)
        except Exception:
            log.exception("error while handling state %s", state)

    async def _handle(self, raw) -> None:
        try:
            msg = parse_server_message(raw)
        except ProtocolError:
            log.warning("ignoring unreadable server message")
            return
        try:
            result = self._on_message(msg)
            if result is not None:
                await result
        except Exception:
            log.exception("error while handling %s", type(msg).__name__)
