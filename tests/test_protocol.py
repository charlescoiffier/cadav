import json

import pytest
from pydantic import ValidationError

from cadavre.protocol import (
    PROTOCOL_VERSION,
    CreateGame,
    GameSettings,
    JoinGame,
    ProtocolError,
    SubmitText,
    dump_message,
    parse_client_message,
)


def settings(**kw):
    return GameSettings(**{"desired_players": 4, "turn_seconds": 120, **kw})


def test_roundtrip():
    msg = CreateGame(settings=settings(theme="mer"))
    parsed = parse_client_message(dump_message(msg))
    assert parsed == msg


def test_wrong_version_rejected():
    raw = json.dumps({"v": PROTOCOL_VERSION + 1, "type": "list_games"})
    with pytest.raises(ProtocolError) as e:
        parse_client_message(raw)
    assert e.value.code == "unsupported_version"


@pytest.mark.parametrize("raw", ["nope", "[]", '{"v":1}', '{"v":1,"type":"x"}'])
def test_garbage_rejected(raw):
    with pytest.raises(ProtocolError):
        parse_client_message(raw)


def test_game_message_requires_game_id():
    with pytest.raises(ProtocolError):
        parse_client_message('{"v":1,"type":"submit_text","text":"a"}')
    assert SubmitText(game_id="g", text="a").game_id == "g"


def test_join_needs_exactly_one_of_id_or_code():
    JoinGame(game_id="g")
    JoinGame(code="ABCDE")
    with pytest.raises(ValidationError):
        JoinGame()
    with pytest.raises(ValidationError):
        JoinGame(game_id="g", code="ABCDE")


@pytest.mark.parametrize(
    "kw",
    [
        {"desired_players": 2},
        {"desired_players": 9},
        {"turn_seconds": 29},
        {"turn_seconds": 72 * 3600 + 1},
        {"min_words": 10, "max_words": 5},
    ],
)
def test_invalid_settings(kw):
    with pytest.raises(ValidationError):
        settings(**kw)
