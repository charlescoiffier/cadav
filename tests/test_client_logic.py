import pytest

from cadav.client.config import Config, new_secret
from cadav.client.logic import (
    build_settings,
    describe_settings,
    format_duration,
    my_game_label,
    parse_duration,
)
from cadav.protocol import GameSettings, GameStatus, GameView


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


# --- game screen helpers ---------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from cadav.client.logic import format_remaining, primer_help, word_status  # noqa: E402
from cadav.protocol import PrimerMode  # noqa: E402

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "delta,text",
    [
        (timedelta(seconds=12), "12 s"),
        (timedelta(minutes=4, seconds=5), "4 min 05 s"),
        (timedelta(hours=1, minutes=5, seconds=59), "1 h 05"),
        (timedelta(days=2, hours=3, minutes=40), "2 j 3 h"),
        (timedelta(0), "échéance dépassée"),
        (timedelta(seconds=-30), "échéance dépassée"),
    ],
)
def test_format_remaining(delta, text):
    assert format_remaining(NOW + delta, NOW) == text


def test_format_remaining_without_deadline():
    assert format_remaining(None, NOW) == "—"


def test_word_status_free_text():
    s = GameSettings(desired_players=3, turn_seconds=120)
    assert not word_status("", s).ok and word_status("", s).text == "0 mot"
    assert word_status("un", s).text == "1 mot" and word_status("un", s).ok
    assert word_status("un deux trois", s).text == "3 mots"


def test_word_status_limits():
    s = GameSettings(desired_players=3, turn_seconds=120, min_words=3, max_words=5)
    assert not word_status("un deux", s).ok and "encore 1" in word_status("un deux", s).text
    assert word_status("un deux trois", s).ok and "(3 à 5 mots)" in word_status("un deux trois", s).text
    too_many = word_status("a b c d e f g", s)
    assert not too_many.ok and "2 de trop" in too_many.text
    assert not word_status("   ", s).ok


def test_word_status_too_many_characters():
    s = GameSettings(desired_players=3, turn_seconds=120)
    assert not word_status("x" * 2001, s).ok


def test_primer_help():
    def v(**kw):
        s = GameSettings(desired_players=3, turn_seconds=120, **kw.pop("settings", {}))
        return GameView(game_id="g", code=None, status=GameStatus.RUNNING, host="a", settings=s, players=["a", "b", "c"], **kw)

    assert primer_help(v(primer="Une phrase.")) == "Une phrase."
    assert "Page blanche" in primer_help(v())
    assert "Pas d'amorce" in primer_help(v(settings={"primer_mode": PrimerMode.NONE}))


def test_turn_position():
    s = GameSettings(desired_players=4, turn_seconds=120)

    def v(me_turn, current):
        return GameView(
            game_id="g", code=None, status=GameStatus.RUNNING, host="a", settings=s,
            players=["a", "b", "c", "d"], current_player=current, my_turn=me_turn,
        )

    from cadav.client.logic import turn_position

    assert turn_position(v(True, "b"), "b") == ("now", 0)
    assert turn_position(v(False, "b"), "a") == ("past", 0)
    assert turn_position(v(False, "b"), "c") == ("later", 2)
    assert turn_position(v(False, "b"), "d") == ("later", 3)
    assert turn_position(v(False, "b"), "zed") == ("past", 0)
