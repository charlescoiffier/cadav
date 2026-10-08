"""Shared client/server wire protocol (Pydantic models).

Every message is ``{v, type, game_id?, ...}``. ``v`` is the protocol version;
a message with another version is rejected by :func:`parse_message`.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

PROTOCOL_VERSION = 1

MIN_PLAYERS = 3
MAX_PLAYERS = 8
MIN_TURN_SECONDS = 30
MAX_TURN_SECONDS = 72 * 3600
MAX_CONTRIBUTION_CHARS = 2000
DEFAULT_PRIMER_WORDS = 12


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class PrimerMode(StrEnum):
    LAST_SENTENCE = "last_sentence"
    LAST_WORDS = "last_words"
    NONE = "none"


class GameStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"
    EXPIRED = "expired"


class GameSettings(BaseModel):
    """Options chosen by the host at creation time."""

    visibility: Visibility = Visibility.PUBLIC
    desired_players: int = Field(ge=MIN_PLAYERS, le=MAX_PLAYERS)
    turn_seconds: int = Field(ge=MIN_TURN_SECONDS, le=MAX_TURN_SECONDS)
    theme: str | None = Field(default=None, max_length=200)
    primer_mode: PrimerMode = PrimerMode.LAST_SENTENCE
    primer_words: int = Field(default=DEFAULT_PRIMER_WORDS, ge=1, le=100)
    min_words: int | None = Field(default=None, ge=1)
    max_words: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_word_limits(self) -> GameSettings:
        if (
            self.min_words is not None
            and self.max_words is not None
            and self.min_words > self.max_words
        ):
            raise ValueError("min_words must be <= max_words")
        return self


# --- Projections (what a client is allowed to see) -------------------------


class StoryPart(BaseModel):
    author: str
    text: str


class GameView(BaseModel):
    """Per-player projection of a game. Never contains hidden text."""

    game_id: str
    code: str | None  # only for members of a waiting game
    status: GameStatus
    host: str
    settings: GameSettings
    players: list[str]  # join order while waiting, play order once started
    current_player: str | None = None
    deadline: datetime | None = None  # turn deadline, or waiting-room expiry
    my_turn: bool = False
    primer: str | None = None  # only for the player whose turn it is
    story: list[StoryPart] | None = None  # only once finished
    skipped: list[str] = Field(default_factory=list)  # only once finished


class LobbyEntry(BaseModel):
    game_id: str
    host: str
    theme: str | None
    players: int
    desired_players: int
    turn_seconds: int


# --- Client -> server ------------------------------------------------------


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: int = PROTOCOL_VERSION


class _GameMessage(_Message):
    game_id: str = Field(min_length=1)


class Register(_Message):
    type: Literal["register"] = "register"
    pseudo: str = Field(min_length=1, max_length=24)
    secret: str = Field(min_length=1, max_length=256)


class Auth(_Message):
    type: Literal["auth"] = "auth"
    pseudo: str = Field(min_length=1, max_length=24)
    secret: str = Field(min_length=1, max_length=256)


class ListGames(_Message):
    type: Literal["list_games"] = "list_games"


class CreateGame(_Message):
    type: Literal["create_game"] = "create_game"
    settings: GameSettings


class JoinGame(_Message):
    """Join by id (public list) or by code (private games)."""

    type: Literal["join_game"] = "join_game"
    game_id: str | None = None
    code: str | None = None

    @model_validator(mode="after")
    def _id_or_code(self) -> JoinGame:
        if (self.game_id is None) == (self.code is None):
            raise ValueError("exactly one of game_id or code is required")
        return self


class LeaveGame(_GameMessage):
    type: Literal["leave_game"] = "leave_game"


class StartGame(_GameMessage):
    type: Literal["start_game"] = "start_game"


class SubmitText(_GameMessage):
    type: Literal["submit_text"] = "submit_text"
    text: str = Field(max_length=MAX_CONTRIBUTION_CHARS * 2)  # game.py enforces the real limit


# --- Server -> client ------------------------------------------------------


class AuthOk(_Message):
    type: Literal["auth_ok"] = "auth_ok"
    pseudo: str


class MyGames(_Message):
    type: Literal["my_games"] = "my_games"
    games: list[GameView]


class LobbyUpdate(_Message):
    type: Literal["lobby_update"] = "lobby_update"
    games: list[LobbyEntry]


class GameJoined(_GameMessage):
    type: Literal["game_joined"] = "game_joined"
    view: GameView


class PlayerJoined(_GameMessage):
    type: Literal["player_joined"] = "player_joined"
    pseudo: str
    view: GameView


class PlayerLeft(_GameMessage):
    type: Literal["player_left"] = "player_left"
    pseudo: str
    view: GameView


class GameStarted(_GameMessage):
    type: Literal["game_started"] = "game_started"
    view: GameView


class TurnStarted(_GameMessage):
    type: Literal["turn_started"] = "turn_started"
    view: GameView


class TurnSkipped(_GameMessage):
    type: Literal["turn_skipped"] = "turn_skipped"
    pseudo: str
    view: GameView


class GameFinished(_GameMessage):
    type: Literal["game_finished"] = "game_finished"
    view: GameView


class ErrorMessage(_Message):
    type: Literal["error"] = "error"
    game_id: str | None = None
    code: str
    message: str  # French, displayable as is


ClientMessage = Annotated[
    Register | Auth | ListGames | CreateGame | JoinGame | LeaveGame | StartGame | SubmitText,
    Field(discriminator="type"),
]
ServerMessage = Annotated[
    AuthOk
    | MyGames
    | LobbyUpdate
    | GameJoined
    | PlayerJoined
    | PlayerLeft
    | GameStarted
    | TurnStarted
    | TurnSkipped
    | GameFinished
    | ErrorMessage,
    Field(discriminator="type"),
]

_client_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)
_server_adapter: TypeAdapter[ServerMessage] = TypeAdapter(ServerMessage)


class ProtocolError(ValueError):
    """Malformed message or unsupported protocol version."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _parse(adapter: TypeAdapter, raw: str | bytes):
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProtocolError("bad_message", "Message illisible.") from exc
    if not isinstance(data, dict):
        raise ProtocolError("bad_message", "Message illisible.")
    if data.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(
            "unsupported_version",
            "Version du protocole non prise en charge : mets le client à jour.",
        )
    try:
        return adapter.validate_python(data)
    except ValueError as exc:
        raise ProtocolError("bad_message", "Message invalide.") from exc


def parse_client_message(raw: str | bytes):
    return _parse(_client_adapter, raw)


def parse_server_message(raw: str | bytes):
    return _parse(_server_adapter, raw)


def dump_message(msg: _Message) -> str:
    return msg.model_dump_json()
