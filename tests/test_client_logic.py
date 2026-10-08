import pytest

from cadavre.client.config import Config, new_secret
from cadavre.client.logic import (
    build_settings,
    describe_settings,
    format_duration,
    my_game_label,
    parse_duration,
)
from cadavre.protocol import GameSettings, GameStatus, GameView


@pytest.mark.parametrize(
    "text,seconds",
    [("90s", 90), ("30", 1800), ("10min", 600), ("10 MIN", 600), ("36h", 129600), ("2j", 172800), ("72h", 259200), (" 45 s ", 45)],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "5x", "-3m", "29s", "73h", "4j", "1.5h"])
def test_parse_duration_rejects(text):
    with pytest.raises(ValueError):
        parse_duration(text)


@pytest.mark.parametrize("seconds,text", [(45, "45 s"), (120, "2 min"), (5400, "90 min"), (86400, "24 h")])
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text


def form(**kw):
    return build_settings(**{"visibility": "public", "players": 4, "deadline": "quick", **kw})


def test_presets_and_defaults():
    s = form()
    assert (s.turn_seconds, s.primer_mode, s.theme, s.min_words) == (120, "last_sentence", None, None)
    assert form(deadline="relaxed").turn_seconds == 86400
    assert form(deadline="custom", custom_deadline="3h").turn_seconds == 10800


def test_optional_fields():
    s = form(theme="  la mer ", primer_mode="last_words", primer_words="5", min_words="3", max_words="40")
    assert (s.theme, s.primer_words, s.min_words, s.max_words) == ("la mer", 5, 3, 40)


@pytest.mark.parametrize(
    "kw",
    [
        {"deadline": "custom", "custom_deadline": "nope"},
        {"min_words": "10", "max_words": "5"},
        {"min_words": "abc"},
        {"max_words": "0"},
        {"primer_words": "101"},
        {"theme": "x" * 201},
    ],
)
def test_invalid_form(kw):
    with pytest.raises(ValueError):
        form(**kw)


def test_describe_settings_is_french():
    lines = describe_settings(GameSettings(desired_players=3, turn_seconds=86400, theme="mer", min_words=2))
    assert lines == [
        "Thème : mer",
        "Visibilité : publique",
        "Durée d'un tour : 24 h",
        "Amorce : dernière phrase",
        "Longueur : au moins 2 mots",
    ]


def view(**kw):
    base = dict(
        game_id="g", code=None, status=GameStatus.RUNNING, host="ana",
        settings=GameSettings(desired_players=3, turn_seconds=120), players=["ana", "bob", "cleo"],
    )
    return GameView(**{**base, **kw})


def test_my_game_label():
    assert "★" in my_game_label(view(my_turn=True, current_player="ana")) and "à toi" in my_game_label(view(my_turn=True))
    assert "tour de bob" in my_game_label(view(current_player="bob"))
    assert "en attente (3/3)" in my_game_label(view(status=GameStatus.WAITING))


def test_config_roundtrip_and_resilience(tmp_path):
    path = tmp_path / "x" / "config.json"
    assert not Config.load(path).registered
    cfg = Config(pseudo="ana", secret=new_secret(), url="ws://h:1")
    cfg.save(path)
    assert Config.load(path) == cfg and cfg.registered
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    path.write_text("garbage")
    assert Config.load(path) == Config()
    path.write_text("[1]")
    assert Config.load(path) == Config()
    assert len(new_secret()) == 64 and new_secret() != new_secret()
