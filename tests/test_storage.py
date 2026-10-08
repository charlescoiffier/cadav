import json
import os
from datetime import UTC, date, datetime

import pytest

from cadavre import game as G
from cadavre.protocol import GameSettings
from cadavre.storage import Storage, atomic_write_json

T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)


def make_game(gid="abc"):
    s = GameSettings(desired_players=3, turn_seconds=120)
    return G.create_game(gid, "ABCDE", "ana", s, T0)


def test_atomic_write_replaces_and_leaves_no_temp(tmp_path):
    path = tmp_path / "sub" / "f.json"
    atomic_write_json(path, {"a": 1})
    atomic_write_json(path, {"a": 2, "é": "ü"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2, "é": "ü"}
    assert [p.name for p in path.parent.iterdir()] == ["f.json"]


def test_failed_write_keeps_old_file_and_cleans_up(tmp_path):
    path = tmp_path / "f.json"
    atomic_write_json(path, {"ok": True})
    with pytest.raises(TypeError):
        atomic_write_json(path, {"bad": object()})
    assert json.loads(path.read_text()) == {"ok": True}
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


def test_replace_failure_cleans_up(tmp_path, monkeypatch):
    path = tmp_path / "f.json"
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        atomic_write_json(path, {"a": 1})
    assert list(tmp_path.iterdir()) == []


def test_users_roundtrip(tmp_path):
    st = Storage(tmp_path)
    assert st.load_users() == {}
    st.save_users({"ana": {"pseudo": "Ana", "salt": "00", "hash": "ff"}})
    assert Storage(tmp_path).load_users()["ana"]["pseudo"] == "Ana"


def test_games_roundtrip_and_delete(tmp_path):
    st = Storage(tmp_path)
    game = make_game()
    st.save_game(game)
    assert st.load_games() == [game]
    st.delete_game("abc")
    st.delete_game("abc")  # idempotent
    assert st.load_games() == []


def test_corrupt_game_file_is_ignored(tmp_path):
    st = Storage(tmp_path)
    st.save_game(make_game("good"))
    (st.games_dir / "bad.json").write_text("{not json")
    assert [g.id for g in st.load_games()] == ["good"]


def test_archive_moves_game_and_filters_by_date(tmp_path):
    st = Storage(tmp_path)
    old, new = make_game("old"), make_game("new")
    for g in (old, new):
        st.save_game(g)
    st.archive_game(old, datetime(2026, 1, 1, tzinfo=UTC))
    st.archive_game(new, datetime(2026, 3, 1, tzinfo=UTC))
    assert st.load_games() == []
    assert (st.archive_dir / "2026-01-01-old.json").exists()
    assert [g.id for g in st.load_archived_since(date(2026, 2, 1))] == ["new"]
    assert len(st.load_archived_since(date(2025, 1, 1))) == 2
