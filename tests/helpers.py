"""Shared test helpers: fake clock and a scripted WebSocket client."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from cadavre.protocol import PROTOCOL_VERSION

T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)


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
