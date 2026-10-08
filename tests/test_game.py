import random
from datetime import UTC, datetime, timedelta

import pytest

from cadavre import game as g
from cadavre.protocol import GameSettings, GameStatus, PrimerMode, Visibility

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def mk(players=("ana", "bob", "cleo"), desired=None, now=T0, **kw):
    s = GameSettings(
        **{"desired_players": desired or len(players), "turn_seconds": 120, **kw}
    )
    game = g.create_game("g1", "ABCDE", players[0], s, now)
    rng = random.Random(1)
    for p in players[1:]:
        g.join(game, p, now, rng)
    return game


def running(**kw):
    game = mk(**kw)
    assert game.status is GameStatus.RUNNING
    return game


# --- primer ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Il pleut. Elle sortit sans parapluie.", "Elle sortit sans parapluie."),
        ("Une seule phrase.", "Une seule phrase."),
        ("Quoi ? Vraiment ! Oui…", "Oui…"),
        ("« Non. » Il partit.", "Il partit."),
        ("Il dit : « Pars. »", "Il dit : « Pars. »"),
        ("Fin brutale... Et puis ?", "Et puis ?"),
        ("  espaces autour.  ", "espaces autour."),
    ],
)
def test_last_sentence(text, expected):
    assert g.extract_primer(text, PrimerMode.LAST_SENTENCE) == expected


def test_last_sentence_without_final_punctuation_takes_12_words():
    text = " ".join(f"m{i}" for i in range(20))
    assert g.extract_primer(text, PrimerMode.LAST_SENTENCE) == " ".join(
        f"m{i}" for i in range(8, 20)
    )


def test_last_words_and_none():
    assert g.extract_primer("a b c d e", PrimerMode.LAST_WORDS, 2) == "d e"
    assert g.extract_primer("a b", PrimerMode.LAST_WORDS, 5) == "a b"
    assert g.extract_primer("a b.", PrimerMode.NONE) is None


# --- lobby ------------------------------------------------------------------


def test_code_alphabet_has_no_ambiguous_chars():
    rng = random.Random(0)
    for _ in range(200):
        code = g.generate_code(rng)
        assert len(code) == 5 and not set(code) & set("OI01")


def test_code_avoids_taken():
    rng = random.Random(0)
    first = g.generate_code(random.Random(0))
    assert g.generate_code(rng, {first}) != first


def test_join_rules():
    game = mk(("ana",), desired=3)
    rng = random.Random(0)
    g.join(game, "bob", T0, rng)
    with pytest.raises(g.GameError) as e:
        g.join(game, "bob", T0, rng)
    assert e.value.code == "already_in_game"
    g.join(game, "cleo", T0, rng)  # full -> auto start
    assert game.status is GameStatus.RUNNING
    with pytest.raises(g.GameError) as e:
        g.join(game, "dan", T0, rng)
    assert e.value.code == "game_started"


def test_auto_start_events_and_deadline():
    game = mk(("ana", "bob"), desired=3)
    events = g.join(game, "cleo", T0, random.Random(0))
    assert [type(e) for e in events] == [g.PlayerJoined, g.GameStarted, g.TurnStarted]
    assert game.deadline == T0 + timedelta(seconds=120)
    assert sorted(game.players) == ["ana", "bob", "cleo"]


def test_order_is_random_but_seeded():
    orders = set()
    for seed in range(20):
        game = mk(("ana", "bob", "cleo", "dan"), desired=4)
        game2 = g.create_game("x", "AAAAA", "ana", game.settings, T0)
        for p in ("bob", "cleo"):
            g.join(game2, p, T0, random.Random(0))
        g.join(game2, "dan", T0, random.Random(seed))
        orders.add(tuple(game2.players))
    assert len(orders) > 1


def test_manual_start_rules():
    game = mk(("ana", "bob"), desired=5)
    with pytest.raises(g.GameError) as e:
        g.start(game, "ana", T0, random.Random(0))
    assert e.value.code == "not_enough_players"
    g.join(game, "cleo", T0, random.Random(0))
    with pytest.raises(g.GameError) as e:
        g.start(game, "bob", T0, random.Random(0))
    assert e.value.code == "not_host"
    g.start(game, "ana", T0, random.Random(0))
    assert game.status is GameStatus.RUNNING
    with pytest.raises(g.GameError):
        g.start(game, "ana", T0, random.Random(0))


def test_host_transfer_and_deletion_in_waiting_room():
    game = mk(("ana", "bob", "cleo"), desired=5)
    g.leave(game, "ana", T0)
    assert game.host == "bob"
    g.leave(game, "cleo", T0)
    events = g.leave(game, "bob", T0)
    assert any(isinstance(e, g.GameDeleted) for e in events)


def test_waiting_expiry_depends_on_turn_length():
    quick = mk(("ana",), desired=3)  # 120 s per turn
    assert g.expire_waiting(quick, T0 + timedelta(minutes=14)) == []
    assert g.expire_waiting(quick, T0 + timedelta(minutes=15)) == [g.GameExpired()]
    assert quick.status is GameStatus.EXPIRED

    slow = mk(("ana",), desired=3, turn_seconds=24 * 3600)
    assert g.expire_waiting(slow, T0 + timedelta(hours=47)) == []
    assert g.expire_waiting(slow, T0 + timedelta(hours=48)) != []


def test_waiting_expiry_counts_from_last_activity():
    game = mk(("ana",), desired=3)
    g.join(game, "bob", T0 + timedelta(minutes=10), random.Random(0))
    assert g.expire_waiting(game, T0 + timedelta(minutes=20)) == []


# --- turns ------------------------------------------------------------------


def play_all(game, texts, now=T0):
    for t in texts:
        g.submit_text(game, g.current_player(game), t, now)


def test_full_game_story_and_primers():
    game = running()
    first = g.current_player(game)
    assert g.view_for(game, first).primer is None
    g.submit_text(game, first, "Il pleut. La nuit tombe.", T0)
    second = g.current_player(game)
    assert second != first
    assert g.view_for(game, second).primer == "La nuit tombe."
    g.submit_text(game, second, "Un chat miaule", T0)
    third = g.current_player(game)
    events = g.submit_text(game, third, "Fin.", T0)
    assert events == [g.GameFinished()]
    assert game.status is GameStatus.FINISHED
    view = g.view_for(game, "ana")
    assert [(p.author, p.text) for p in view.story] == [
        (first, "Il pleut. La nuit tombe."),
        (second, "Un chat miaule"),
        (third, "Fin."),
    ]


def test_submit_guards():
    game = running(min_words=2, max_words=4)
    cur = g.current_player(game)
    other = next(p for p in game.players if p != cur)
    for who, text, code in [
        (other, "un deux", "not_your_turn"),
        ("zed", "un deux", "not_in_game"),
        (cur, "   ", "empty_text"),
        (cur, "seul", "too_short"),
        (cur, "un deux trois quatre cinq", "too_long"),
        (cur, "mot " * 600, "text_too_long"),
    ]:
        with pytest.raises(g.GameError) as e:
            g.submit_text(game, who, text, T0)
        assert e.value.code == code
    assert game.contributions == []


def test_submit_when_not_running():
    game = mk(("ana",), desired=3)
    with pytest.raises(g.GameError) as e:
        g.submit_text(game, "ana", "x", T0)
    assert e.value.code == "not_running"


def test_deadline_resets_each_turn():
    game = running()
    later = T0 + timedelta(seconds=50)
    g.submit_text(game, g.current_player(game), "Un. Deux.", later)
    assert game.deadline == later + timedelta(seconds=120)


def test_skip_keeps_primer_and_counts_one_less():
    game = running()
    a, b, c = game.players
    g.submit_text(game, a, "Début. Suite du récit.", T0)
    assert g.expire_turn(game, T0 + timedelta(seconds=119)) == []
    events = g.expire_turn(game, T0 + timedelta(seconds=120))
    assert events == [g.TurnSkipped(b), g.TurnStarted()]
    assert g.view_for(game, c).primer == "Suite du récit."
    g.submit_text(game, c, "Fin.", T0 + timedelta(seconds=130))
    assert game.status is GameStatus.FINISHED
    view = g.view_for(game, a)
    assert [p.author for p in view.story] == [a, c]
    assert view.skipped == [b]


def test_skip_of_last_player_finishes():
    game = running()
    play_all(game, ["a.", "b."])
    events = g.expire_turn(game, T0 + timedelta(hours=1))
    assert events == [g.TurnSkipped(game.players[2]), g.GameFinished()]


def test_first_player_skipped_next_sees_blank():
    game = running()
    g.expire_turn(game, T0 + timedelta(hours=1))
    assert g.view_for(game, game.players[1]).primer is None


def test_expire_turn_noop_when_not_running():
    assert g.expire_turn(mk(("ana",), desired=3), T0 + timedelta(days=9)) == []


def test_leave_current_player_passes_turn_with_same_primer():
    game = running(players=("ana", "bob", "cleo", "dan"))
    a, b, c, d = game.players
    g.submit_text(game, a, "Une phrase.", T0)
    events = g.leave(game, b, T0)
    assert events == [g.PlayerLeft(b), g.TurnStarted()]
    assert g.current_player(game) == c
    assert g.view_for(game, c).primer == "Une phrase."


def test_leave_future_player_is_skipped_later():
    game = running(players=("ana", "bob", "cleo", "dan"))
    a, b, c, d = game.players
    g.leave(game, c, T0)
    g.submit_text(game, a, "x.", T0)
    g.submit_text(game, b, "y.", T0)
    assert g.current_player(game) == d


def test_game_ends_when_fewer_than_two_active_players():
    game = running()
    a, b, c = game.players
    g.submit_text(game, a, "Texte conservé.", T0)
    g.leave(game, b, T0)
    events = g.leave(game, c, T0)
    assert events[-1] == g.GameFinished()
    assert game.status is GameStatus.FINISHED
    assert [p.text for p in g.view_for(game, a).story] == ["Texte conservé."]


def test_departed_player_keeps_authorship_but_loses_view():
    game = running(players=("ana", "bob", "cleo", "dan"))
    a = game.players[0]
    g.submit_text(game, a, "Mon texte.", T0)
    g.leave(game, a, T0)
    with pytest.raises(g.GameError):
        g.view_for(game, a)
    assert game.contributions[0].author == a


def test_last_turn_leave_finishes():
    game = running(players=("ana", "bob", "cleo", "dan"))
    play_all(game, ["a.", "b.", "c."])
    events = g.leave(game, game.players[3], T0)
    assert events[-1] == g.GameFinished()


# --- projection -------------------------------------------------------------


def test_waiting_view_has_code_for_members_only():
    game = mk(("ana",), desired=4)
    assert g.view_for(game, "ana").code == "ABCDE"
    pub = g.view_for(game, "zed")  # public waiting game is browsable
    assert pub.code is None and pub.players == ["ana"]


def test_private_game_hidden_from_non_members():
    game = mk(("ana",), desired=4, visibility=Visibility.PRIVATE)
    with pytest.raises(g.GameError):
        g.view_for(game, "zed")


def test_running_view_never_leaks_other_texts():
    secrets = ["Alpha secret une.", "Bravo secret deux.", "Charlie secret trois."]
    game = running(players=("ana", "bob", "cleo", "dan"))
    texts = [
        "Alpha secret une. Dernier mot alpha.",
        "Bravo secret deux. Dernier mot bravo.",
        "Charlie secret trois. Dernier mot charlie.",
    ]
    for step, text in enumerate(texts):
        g.submit_text(game, g.current_player(game), text, T0)
        cur = g.current_player(game)
        primer = game.primer
        for p in game.players:
            blob = g.view_for(game, p).model_dump_json()
            for t in texts[: step + 1]:
                assert t not in blob
            for s in secrets[: step + 1]:
                assert s not in blob
            if p == cur:
                assert primer in blob
            else:
                assert primer not in blob
        assert g.view_for(game, cur).my_turn
        assert g.view_for(game, cur).story is None


def test_primer_none_mode_gives_blank_every_turn():
    game = running(primer_mode=PrimerMode.NONE)
    g.submit_text(game, g.current_player(game), "Rien à voir.", T0)
    assert g.view_for(game, g.current_player(game)).primer is None


def test_lobby_entry():
    game = mk(("ana",), desired=4, theme="mer")
    e = g.lobby_entry(game)
    assert (e.host, e.theme, e.players, e.desired_players) == ("ana", "mer", 1, 4)
    assert "ABCDE" not in e.model_dump_json()


def test_game_state_roundtrips_through_json():
    game = running()
    g.submit_text(game, g.current_player(game), "Bonjour.", T0)
    assert g.Game.model_validate_json(game.model_dump_json()) == game
