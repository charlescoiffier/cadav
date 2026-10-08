"""Pure game logic: no network, no disk, no implicit clock.

Time (``now``, timezone-aware UTC) and randomness (``rng``) are always
injected. Mutating functions change the :class:`Game` in place and return the
list of events the server should broadcast.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from cadav.protocol import (
    DEFAULT_PRIMER_WORDS,
    MAX_CONTRIBUTION_CHARS,
    MIN_PLAYERS,
    GameSettings,
    GameStatus,
    GameView,
    LobbyEntry,
    PrimerMode,
    StoryPart,
    Visibility,
)

CODE_LENGTH = 5
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I, no O (digits are not used)
SHORT_WAIT = timedelta(minutes=15)
LONG_WAIT = timedelta(hours=48)
SHORT_TURN_THRESHOLD = 3600  # seconds

_END_PUNCT = ".!?…"
_CLOSERS = "\"'»”’)]}"


class GameError(Exception):
    """A rule violation. ``message`` is French and displayable as is."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --- State -----------------------------------------------------------------


class Contribution(BaseModel):
    author: str
    text: str
    at: datetime


class Game(BaseModel):
    id: str
    code: str
    status: GameStatus = GameStatus.WAITING
    settings: GameSettings
    host: str
    players: list[str]  # join order; becomes play order at start
    left: list[str] = Field(default_factory=list)  # players who left a running game
    turn: int = 0  # index in `players` of the current turn
    primer: str | None = None  # primer shown to the current player
    contributions: list[Contribution] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    created_at: datetime
    last_activity: datetime
    deadline: datetime | None = None  # turn deadline (running)


# --- Events ----------------------------------------------------------------


@dataclass(frozen=True)
class PlayerJoined:
    pseudo: str


@dataclass(frozen=True)
class PlayerLeft:
    pseudo: str


@dataclass(frozen=True)
class GameStarted:
    pass


@dataclass(frozen=True)
class TurnStarted:
    pass


@dataclass(frozen=True)
class TurnSkipped:
    pseudo: str


@dataclass(frozen=True)
class GameFinished:
    pass


@dataclass(frozen=True)
class GameDeleted:
    """The waiting room became empty: the server should drop the game."""


@dataclass(frozen=True)
class GameExpired:
    pass


Event = (
    PlayerJoined
    | PlayerLeft
    | GameStarted
    | TurnStarted
    | TurnSkipped
    | GameFinished
    | GameDeleted
    | GameExpired
)


# --- Helpers ---------------------------------------------------------------


def generate_code(rng: random.Random, taken: set[str] | frozenset[str] = frozenset()) -> str:
    while True:
        code = "".join(rng.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if code not in taken:
            return code


def count_words(text: str) -> int:
    return len(text.split())


def extract_primer(text: str, mode: PrimerMode, words: int = DEFAULT_PRIMER_WORDS) -> str | None:
    """Primer shown to the next player, derived from a contribution."""
    text = text.strip()
    if mode is PrimerMode.NONE or not text:
        return None
    if mode is PrimerMode.LAST_WORDS:
        return " ".join(text.split()[-words:])

    # Last sentence: ends with . ! ? … (optionally followed by closing quotes).
    body = text.rstrip(_CLOSERS + " ")
    if not body or body[-1] not in _END_PUNCT:
        return " ".join(text.split()[-DEFAULT_PRIMER_WORDS:])
    core = body.rstrip(_END_PUNCT)
    # Start after the previous terminator (and its closing quotes), if any.
    matches = list(re.finditer(r"[.!?…]+(?:\s*[" + re.escape(_CLOSERS) + r"])*\s+", core))
    start = matches[-1].end() if matches else 0
    return text[start:].strip()


def _check_member(game: Game, pseudo: str) -> None:
    if pseudo not in game.players or pseudo in game.left:
        raise GameError("not_in_game", "Tu ne fais pas partie de cette partie.")


def current_player(game: Game) -> str | None:
    if game.status is not GameStatus.RUNNING or game.turn >= len(game.players):
        return None
    return game.players[game.turn]


def waiting_expiry(game: Game) -> datetime:
    wait = SHORT_WAIT if game.settings.turn_seconds < SHORT_TURN_THRESHOLD else LONG_WAIT
    return game.last_activity + wait


# --- Lifecycle -------------------------------------------------------------


def create_game(
    game_id: str, code: str, host: str, settings: GameSettings, now: datetime
) -> Game:
    return Game(
        id=game_id,
        code=code,
        settings=settings,
        host=host,
        players=[host],
        created_at=now,
        last_activity=now,
    )


def join(game: Game, pseudo: str, now: datetime, rng: random.Random) -> list[Event]:
    if game.status is not GameStatus.WAITING:
        raise GameError("game_started", "Cette partie est déjà lancée.")
    if pseudo in game.players:
        raise GameError("already_in_game", "Tu es déjà dans cette partie.")
    if len(game.players) >= game.settings.desired_players:
        raise GameError("game_full", "Cette partie est pleine.")
    game.players.append(pseudo)
    game.last_activity = now
    events: list[Event] = [PlayerJoined(pseudo)]
    if len(game.players) == game.settings.desired_players:
        events += _start(game, now, rng)
    return events


def start(game: Game, pseudo: str, now: datetime, rng: random.Random) -> list[Event]:
    _check_member(game, pseudo)
    if game.status is not GameStatus.WAITING:
        raise GameError("game_started", "Cette partie est déjà lancée.")
    if pseudo != game.host:
        raise GameError("not_host", "Seul l'hôte peut lancer la partie.")
    if len(game.players) < MIN_PLAYERS:
        raise GameError("not_enough_players", f"Il faut au moins {MIN_PLAYERS} joueurs.")
    return _start(game, now, rng)


def _start(game: Game, now: datetime, rng: random.Random) -> list[Event]:
    rng.shuffle(game.players)
    game.status = GameStatus.RUNNING
    game.turn = 0
    game.primer = None
    game.last_activity = now
    game.deadline = now + timedelta(seconds=game.settings.turn_seconds)
    return [GameStarted(), TurnStarted()]


def leave(game: Game, pseudo: str, now: datetime) -> list[Event]:
    _check_member(game, pseudo)
    if game.status is GameStatus.WAITING:
        game.players.remove(pseudo)
        game.last_activity = now
        if not game.players:
            return [PlayerLeft(pseudo), GameDeleted()]
        if game.host == pseudo:
            game.host = game.players[0]  # oldest remaining joiner
        return [PlayerLeft(pseudo)]
    if game.status is not GameStatus.RUNNING:
        raise GameError("game_over", "Cette partie est terminée.")

    was_current = current_player(game) == pseudo
    game.left.append(pseudo)
    events: list[Event] = [PlayerLeft(pseudo)]
    if was_current:
        events += _advance(game, now)
    return events


def submit_text(game: Game, pseudo: str, text: str, now: datetime) -> list[Event]:
    _check_member(game, pseudo)
    if game.status is not GameStatus.RUNNING:
        raise GameError("not_running", "Cette partie n'est pas en cours.")
    if current_player(game) != pseudo:
        raise GameError("not_your_turn", "Ce n'est pas ton tour.")
    text = text.strip()
    if not text:
        raise GameError("empty_text", "Écris quelque chose avant d'envoyer.")
    if len(text) > MAX_CONTRIBUTION_CHARS:
        raise GameError(
            "text_too_long", f"Ta contribution dépasse {MAX_CONTRIBUTION_CHARS} caractères."
        )
    words = count_words(text)
    lo, hi = game.settings.min_words, game.settings.max_words
    if lo is not None and words < lo:
        raise GameError("too_short", f"Il faut au moins {lo} mots (tu en as {words}).")
    if hi is not None and words > hi:
        raise GameError("too_long", f"Il faut au plus {hi} mots (tu en as {words}).")

    game.contributions.append(Contribution(author=pseudo, text=text, at=now))
    game.primer = extract_primer(text, game.settings.primer_mode, game.settings.primer_words)
    return _advance(game, now)


def expire_turn(game: Game, now: datetime) -> list[Event]:
    """Skip the current player if the deadline passed. No-op otherwise."""
    if game.status is not GameStatus.RUNNING or game.deadline is None or now < game.deadline:
        return []
    skipped = game.players[game.turn]
    game.skipped.append(skipped)
    return [TurnSkipped(skipped)] + _advance(game, now)


def expire_waiting(game: Game, now: datetime) -> list[Event]:
    if game.status is not GameStatus.WAITING or now < waiting_expiry(game):
        return []
    game.status = GameStatus.EXPIRED
    return [GameExpired()]


def _advance(game: Game, now: datetime) -> list[Event]:
    """Move to the next player who has not left, or finish the game.

    The primer is kept as is: after a skip or a departure the next player sees
    the same one.
    """
    game.last_activity = now
    game.turn += 1
    while game.turn < len(game.players) and game.players[game.turn] in game.left:
        game.turn += 1
    if game.turn >= len(game.players):
        return _finish(game, now)
    game.deadline = now + timedelta(seconds=game.settings.turn_seconds)
    return [TurnStarted()]


def _finish(game: Game, now: datetime) -> list[Event]:
    game.status = GameStatus.FINISHED
    game.deadline = None
    game.primer = None
    game.last_activity = now
    return [GameFinished()]


# --- Projections -----------------------------------------------------------


def view_for(game: Game, pseudo: str) -> GameView:
    """What ``pseudo`` may see. The only text ever included before the end is
    the primer of the player whose turn it is."""
    member = pseudo in game.players and pseudo not in game.left
    waiting = game.status is GameStatus.WAITING
    if not member and not (waiting and game.settings.visibility is Visibility.PUBLIC):
        raise GameError("not_in_game", "Tu ne fais pas partie de cette partie.")

    view = GameView(
        game_id=game.id,
        code=game.code if waiting and member else None,
        status=game.status,
        host=game.host,
        settings=game.settings,
        players=list(game.players),
    )
    if waiting:
        view.deadline = waiting_expiry(game)
    elif game.status is GameStatus.RUNNING:
        view.current_player = current_player(game)
        view.deadline = game.deadline
        view.my_turn = view.current_player == pseudo
        if view.my_turn:
            view.primer = game.primer
    elif game.status is GameStatus.FINISHED:
        view.story = [StoryPart(author=c.author, text=c.text) for c in game.contributions]
        view.skipped = list(game.skipped)
    return view


def lobby_entry(game: Game) -> LobbyEntry:
    return LobbyEntry(
        game_id=game.id,
        host=game.host,
        theme=game.settings.theme,
        players=len(game.players),
        desired_players=game.settings.desired_players,
        turn_seconds=game.settings.turn_seconds,
    )
