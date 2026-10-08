"""WebSocket server: accounts, lobby, games and turn deadlines.

The transport (``websockets``) is only used by :meth:`Server.listen`; everything
else works on :class:`Session` objects, and time and randomness are injected.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import random
import re
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cadavre import game as G
from cadavre.game import Game, GameError
from cadavre.protocol import (
    Auth,
    AuthOk,
    CreateGame,
    ErrorMessage,
    GameFinished,
    GameJoined,
    GameStarted,
    GameStatus,
    JoinGame,
    LeaveGame,
    ListGames,
    LobbyUpdate,
    MyGames,
    PlayerJoined,
    PlayerLeft,
    ProtocolError,
    Register,
    StartGame,
    SubmitText,
    TurnSkipped,
    TurnStarted,
    Visibility,
    dump_message,
    parse_client_message,
)
from cadavre.storage import Storage

log = logging.getLogger("cadavre.server")

PSEUDO_RE = re.compile(r"^[\w-]{2,24}$")
CLOSE_REPLACED = 4000
CLOSE_VERSION = 4001
MAX_MESSAGE_BYTES = 64 * 1024


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Limits:
    max_active_games_per_pseudo: int = 5
    max_games: int = 1000
    creations_per_hour: int = 10
    auth_attempts: int = 20  # registrations and failed logins, per IP
    auth_window: timedelta = timedelta(minutes=10)
    finished_ttl: timedelta = timedelta(days=7)  # finished games stay viewable this long


@dataclass(eq=False)
class Session:
    send: Callable[[str], Awaitable[None]]
    close: Callable[[int, str], Awaitable[None]]
    ip: str = "?"
    pseudo: str | None = None
    watching_lobby: bool = False


class Server:
    def __init__(
        self,
        storage: Storage,
        clock: Callable[[], datetime] = utcnow,
        rng: random.Random | None = None,
        limits: Limits | None = None,
    ) -> None:
        self.storage = storage
        self.clock = clock
        self.rng = rng or random.Random()
        self.limits = limits or Limits()
        self.users: dict[str, dict[str, str]] = {}
        self.games: dict[str, Game] = {}
        self.sessions: dict[str, Session] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)
        self._creations: dict[str, deque[datetime]] = defaultdict(deque)

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Load persisted state and re-arm the deadlines."""
        self.users = self.storage.load_users()
        now = self.clock()
        for game in self.storage.load_games():
            self.games[game.id] = game
        since = (now - self.limits.finished_ttl).date()
        for game in self.storage.load_archived_since(since):
            self.games.setdefault(game.id, game)
        for game in list(self.games.values()):
            self._arm(game)

    async def close(self) -> None:
        for task in list(self._timers.values()):
            task.cancel()
        await asyncio.gather(*self._timers.values(), return_exceptions=True)
        self._timers.clear()

    def listen(self, host: str, port: int, ssl=None):
        """Return a ``websockets`` server, usable with ``async with``."""
        from websockets.asyncio.server import serve

        return serve(self._ws_handler, host, port, ssl=ssl, max_size=MAX_MESSAGE_BYTES)

    async def _ws_handler(self, ws) -> None:
        from websockets.exceptions import ConnectionClosed

        remote = ws.remote_address
        session = Session(send=ws.send, close=ws.close, ip=remote[0] if remote else "?")
        try:
            async for raw in ws:
                await self.handle_raw(session, raw)
        except ConnectionClosed:
            pass
        finally:
            await self.disconnect(session)

    async def disconnect(self, session: Session) -> None:
        if session.pseudo and self.sessions.get(session.pseudo) is session:
            del self.sessions[session.pseudo]

    # --- message dispatch --------------------------------------------------

    async def handle_raw(self, session: Session, raw: str | bytes) -> None:
        try:
            msg = parse_client_message(raw)
        except ProtocolError as exc:
            await self._error(session, exc.code, exc.message)
            if exc.code == "unsupported_version":
                await session.close(CLOSE_VERSION, "unsupported version")
            return
        try:
            await self._dispatch(session, msg)
        except GameError as exc:
            await self._error(session, exc.code, exc.message, getattr(msg, "game_id", None))
        except Exception:
            log.exception("unexpected error handling %s", type(msg).__name__)
            await self._error(session, "internal", "Erreur interne du serveur.")

    async def _dispatch(self, session: Session, msg) -> None:
        if isinstance(msg, Register):
            return await self._register(session, msg)
        if isinstance(msg, Auth):
            return await self._auth(session, msg)
        if session.pseudo is None:
            raise GameError("not_authenticated", "Connecte-toi d'abord.")
        pseudo = session.pseudo
        if isinstance(msg, ListGames):
            session.watching_lobby = True
            await self._send(session, LobbyUpdate(games=self._lobby()))
        elif isinstance(msg, CreateGame):
            await self._create(session, pseudo, msg)
        elif isinstance(msg, JoinGame):
            await self._join(session, pseudo, msg)
        elif isinstance(msg, LeaveGame):
            await self._leave(session, pseudo, msg)
        elif isinstance(msg, StartGame):
            game = self._member_game(pseudo, msg.game_id)
            await self._apply(game, G.start(game, pseudo, self.clock(), self.rng), was_waiting=True)
        elif isinstance(msg, SubmitText):
            game = self._member_game(pseudo, msg.game_id)
            await self._apply(game, G.submit_text(game, pseudo, msg.text, self.clock()))
        else:  # server->client messages sent by a client
            raise GameError("bad_message", "Message invalide.")

    # --- accounts ----------------------------------------------------------

    @staticmethod
    def _hash(salt: str, secret: str) -> str:
        # The secret is 32 random bytes generated by the client, not a human
        # password: a salted fast hash is enough, no key stretching needed.
        return hashlib.sha256(bytes.fromhex(salt) + secret.encode()).hexdigest()

    def _throttle(self, ip: str) -> None:
        window = self._failures[ip]
        now = self.clock()
        while window and now - window[0] > self.limits.auth_window:
            window.popleft()
        if len(window) >= self.limits.auth_attempts:
            raise GameError("too_many_attempts", "Trop de tentatives, réessaie plus tard.")

    def _fail(self, ip: str) -> None:
        self._failures[ip].append(self.clock())

    async def _register(self, session: Session, msg: Register) -> None:
        if session.pseudo:
            raise GameError("already_authenticated", "Tu es déjà connecté.")
        self._throttle(session.ip)
        self._fail(session.ip)  # registrations count against the IP budget
        pseudo = msg.pseudo.strip()
        if not PSEUDO_RE.match(pseudo):
            raise GameError(
                "bad_pseudo", "Le pseudo doit faire 2 à 24 caractères : lettres, chiffres, _ ou -."
            )
        key = pseudo.casefold()
        if key in self.users:
            raise GameError("pseudo_taken", "Ce pseudo est déjà pris.")
        salt = os.urandom(16).hex()
        self.users[key] = {"pseudo": pseudo, "salt": salt, "hash": self._hash(salt, msg.secret)}
        self.storage.save_users(self.users)
        await self._login(session, pseudo)

    async def _auth(self, session: Session, msg: Auth) -> None:
        if session.pseudo:
            raise GameError("already_authenticated", "Tu es déjà connecté.")
        self._throttle(session.ip)
        user = self.users.get(msg.pseudo.strip().casefold())
        # Always hash, so that an unknown pseudo costs the same as a wrong secret.
        salt = user["salt"] if user else "00" * 16
        ok = hmac.compare_digest(
            self._hash(salt, msg.secret), user["hash"] if user else "0" * 64
        )
        if not (user and ok):
            self._fail(session.ip)
            raise GameError("bad_credentials", "Pseudo ou secret incorrect.")
        await self._login(session, user["pseudo"])

    async def _login(self, session: Session, pseudo: str) -> None:
        self.purge_finished()
        old = self.sessions.get(pseudo)
        session.pseudo = pseudo
        self.sessions[pseudo] = session
        if old is not None and old is not session:
            old.pseudo = None
            try:
                await old.close(CLOSE_REPLACED, "replaced by a new connection")
            except Exception:
                log.debug("closing replaced session failed", exc_info=True)
        await self._send(session, AuthOk(pseudo=pseudo))
        await self._send(session, MyGames(games=self._my_views(pseudo)))

    # --- lobby and games ---------------------------------------------------

    def _lobby(self):
        return [
            G.lobby_entry(g)
            for g in self.games.values()
            if g.status is GameStatus.WAITING and g.settings.visibility is Visibility.PUBLIC
        ]

    def _active_games(self, pseudo: str) -> list[Game]:
        return [
            g
            for g in self.games.values()
            if g.status in (GameStatus.WAITING, GameStatus.RUNNING)
            and pseudo in g.players
            and pseudo not in g.left
        ]

    def _my_views(self, pseudo: str):
        return [
            G.view_for(g, pseudo)
            for g in self.games.values()
            if pseudo in g.players and pseudo not in g.left
        ]

    def _member_game(self, pseudo: str, game_id: str) -> Game:
        game = self.games.get(game_id)
        if game is None or pseudo not in game.players or pseudo in game.left:
            raise GameError("not_in_game", "Tu ne fais pas partie de cette partie.")
        return game

    def _check_active_cap(self, pseudo: str) -> None:
        if len(self._active_games(pseudo)) >= self.limits.max_active_games_per_pseudo:
            raise GameError(
                "too_many_games",
                f"Tu as déjà {self.limits.max_active_games_per_pseudo} parties en cours.",
            )

    async def _create(self, session: Session, pseudo: str, msg: CreateGame) -> None:
        self._check_active_cap(pseudo)
        live = sum(1 for g in self.games.values() if g.status in (GameStatus.WAITING, GameStatus.RUNNING))
        if live >= self.limits.max_games:
            raise GameError("server_full", "Le serveur est complet, réessaie plus tard.")
        now = self.clock()
        recent = self._creations[pseudo]
        while recent and now - recent[0] > timedelta(hours=1):
            recent.popleft()
        if len(recent) >= self.limits.creations_per_hour:
            raise GameError("too_many_creations", "Tu crées trop de parties, patiente un peu.")
        recent.append(now)

        taken = {g.code for g in self.games.values()}
        code = G.generate_code(self.rng, taken)
        game_id = f"{self.rng.getrandbits(48):012x}"
        while game_id in self.games:
            game_id = f"{self.rng.getrandbits(48):012x}"
        game = G.create_game(game_id, code, pseudo, msg.settings, now)
        self.games[game.id] = game
        await self._send(session, GameJoined(game_id=game.id, view=G.view_for(game, pseudo)))
        await self._after(game, was_waiting=True)

    async def _join(self, session: Session, pseudo: str, msg: JoinGame) -> None:
        if msg.code is not None:
            code = msg.code.strip().upper()
            game = next((g for g in self.games.values() if g.code == code), None)
        else:
            game = self.games.get(msg.game_id or "")
            if game is not None and game.settings.visibility is not Visibility.PUBLIC:
                game = None  # private games are only reachable by code
        if game is None:
            raise GameError("game_not_found", "Partie introuvable.")
        self._check_active_cap(pseudo)
        events = G.join(game, pseudo, self.clock(), self.rng)
        await self._send(session, GameJoined(game_id=game.id, view=G.view_for(game, pseudo)))
        await self._apply(game, events, was_waiting=True)

    async def _leave(self, session: Session, pseudo: str, msg: LeaveGame) -> None:
        game = self._member_game(pseudo, msg.game_id)
        was_waiting = game.status is GameStatus.WAITING
        events = G.leave(game, pseudo, self.clock())
        await self._send(session, MyGames(games=self._my_views(pseudo)))
        await self._apply(game, events, was_waiting=was_waiting)

    # --- applying events ---------------------------------------------------

    async def _apply(self, game: Game, events, was_waiting: bool = False) -> None:
        await self._broadcast(game, events)
        await self._after(game, was_waiting=was_waiting, events=events)

    def _members(self, game: Game) -> list[str]:
        return [p for p in game.players if p not in game.left]

    async def _broadcast(self, game: Game, events) -> None:
        for ev in events:
            for p in self._members(game):
                view = G.view_for(game, p)
                msg = None
                if isinstance(ev, G.PlayerJoined):
                    if p != ev.pseudo:  # the joiner already got game_joined
                        msg = PlayerJoined(game_id=game.id, pseudo=ev.pseudo, view=view)
                elif isinstance(ev, G.PlayerLeft):
                    msg = PlayerLeft(game_id=game.id, pseudo=ev.pseudo, view=view)
                elif isinstance(ev, G.GameStarted):
                    msg = GameStarted(game_id=game.id, view=view)
                elif isinstance(ev, G.TurnStarted):
                    msg = TurnStarted(game_id=game.id, view=view)
                elif isinstance(ev, G.TurnSkipped):
                    msg = TurnSkipped(game_id=game.id, pseudo=ev.pseudo, view=view)
                elif isinstance(ev, G.GameFinished):
                    msg = GameFinished(game_id=game.id, view=view)
                elif isinstance(ev, G.GameExpired):
                    msg = ErrorMessage(
                        game_id=game.id,
                        code="game_expired",
                        message="La salle d'attente a expiré : la partie est supprimée.",
                    )
                if msg is not None:
                    await self._send_to(p, msg)

    async def _after(self, game: Game, was_waiting: bool, events=()) -> None:
        """Persist, (re)arm timers and refresh the lobby after a change."""
        gone = any(isinstance(e, (G.GameDeleted, G.GameExpired)) for e in events)
        try:
            if gone:
                self.games.pop(game.id, None)
                self.storage.delete_game(game.id)
            elif game.status is GameStatus.FINISHED:
                self.storage.archive_game(game, self.clock())
            else:
                self.storage.save_game(game)
        except OSError:
            log.exception("could not persist game %s", game.id)
        self._arm(game, cancel_only=gone)
        public = game.settings.visibility is Visibility.PUBLIC
        if public and (was_waiting or game.status is GameStatus.WAITING):
            await self._push_lobby()

    async def _push_lobby(self) -> None:
        entries = self._lobby()
        for s in list(self.sessions.values()):
            if s.watching_lobby:
                await self._send(s, LobbyUpdate(games=entries))

    # --- deadlines ---------------------------------------------------------

    def _due(self, game: Game) -> datetime | None:
        if game.status is GameStatus.WAITING:
            return G.waiting_expiry(game)
        if game.status is GameStatus.RUNNING:
            return game.deadline
        return None

    def _arm(self, game: Game, cancel_only: bool = False) -> None:
        old = self._timers.pop(game.id, None)
        if old is not None and old is not asyncio.current_task():
            old.cancel()
        due = None if cancel_only else self._due(game)
        if due is not None:
            self._timers[game.id] = asyncio.create_task(self._timer(game.id, due))

    async def _timer(self, game_id: str, due: datetime) -> None:
        try:
            while (remaining := (due - self.clock()).total_seconds()) > 0:
                await asyncio.sleep(remaining)
            await self.expire(game_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("deadline handling failed for game %s", game_id)

    async def expire(self, game_id: str) -> None:
        """Apply the deadline of one game if it has passed."""
        game = self.games.get(game_id)
        if game is None:
            return
        was_waiting = game.status is GameStatus.WAITING
        now = self.clock()
        events = G.expire_waiting(game, now) if was_waiting else G.expire_turn(game, now)
        if events:
            await self._apply(game, events, was_waiting=was_waiting)

    async def check_deadlines(self) -> None:
        """Apply every passed deadline (the timers do this on their own; this is for tests and recovery)."""
        for game_id in list(self.games):
            try:
                await self.expire(game_id)
            except Exception:
                log.exception("deadline handling failed for game %s", game_id)

    def purge_finished(self) -> None:
        """Forget finished games older than the retention delay (archives stay on disk)."""
        limit = self.clock() - self.limits.finished_ttl
        for gid, g in list(self.games.items()):
            if g.status in (GameStatus.FINISHED, GameStatus.EXPIRED) and g.last_activity < limit:
                del self.games[gid]

    # --- sending -----------------------------------------------------------

    async def _send(self, session: Session, msg) -> None:
        try:
            await session.send(dump_message(msg))
        except Exception:
            log.debug("send failed, dropping session", exc_info=True)
            await self.disconnect(session)

    async def _send_to(self, pseudo: str, msg) -> None:
        session = self.sessions.get(pseudo)
        if session is not None:
            await self._send(session, msg)

    async def _error(self, session: Session, code: str, message: str, game_id: str | None = None) -> None:
        await self._send(session, ErrorMessage(game_id=game_id, code=code, message=message))


def main(argv: list[str] | None = None) -> None:
    import argparse
    import ssl as ssl_lib
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="cadavre serve", description="Serveur de cadavre exquis")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--cert", help="certificat TLS (obligatoire si le serveur est public)")
    parser.add_argument("--key", help="clé privée TLS")
    args = parser.parse_args(argv)

    ctx = None
    if args.cert:
        ctx = ssl_lib.SSLContext(ssl_lib.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)

    async def run() -> None:
        server = Server(Storage(Path(args.data_dir)))
        await server.start()
        async with server.listen(args.host, args.port, ssl=ctx):
            log.info("listening on %s:%s", args.host, args.port)
            await asyncio.Future()

    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
