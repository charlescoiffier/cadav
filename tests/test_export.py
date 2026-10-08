import subprocess
from datetime import date

import pytest

from cadav.client import export
from cadav.protocol import GameSettings, GameStatus, GameView, StoryPart

D = date(2026, 10, 8)


def story_view(theme="Le phare", parts=(("ana", "Il pleut."), ("bob", "La nuit.\nVraiment.")), skipped=()):
    return GameView(
        game_id="abcdef123456",
        code=None,
        status=GameStatus.FINISHED,
        host="ana",
        settings=GameSettings(desired_players=3, turn_seconds=120, theme=theme),
        players=["ana", "bob", "cleo"],
        story=[StoryPart(author=a, text=t) for a, t in parts],
        skipped=list(skipped),
    )


def test_french_date():
    assert export.french_date(D) == "8 octobre 2026"
    assert export.french_date(date(2026, 1, 1)) == "1er janvier 2026"


def test_text_rendering():
    assert export.render_text(story_view(skipped=["cleo"]), D) == (
        "Le phare\n========\n\n"
        "Cadavre exquis écrit le 8 octobre 2026 par ana, bob.\n\n"
        "— ana —\nIl pleut.\n\n"
        "— bob —\nLa nuit.\nVraiment.\n\n"
        "Tours sautés : cleo\n"
    )


def test_markdown_rendering():
    assert export.render_markdown(story_view(skipped=["cleo"]), D) == (
        "# Le phare\n\n"
        "*Cadavre exquis écrit le 8 octobre 2026 par ana, bob.*\n\n"
        "**ana**\n\nIl pleut.\n\n"
        "**bob**\n\nLa nuit.  \nVraiment.\n\n"
        "*Tours sautés : cleo.*\n"
    )


def test_untitled_and_empty_stories():
    empty = story_view(theme=None, parts=())
    assert export.render_text(empty, D).startswith("Cadavre exquis\n==============\n")
    assert "Personne n'a écrit." in export.render_markdown(empty, D)
    assert "par personne." in export.render_text(empty, D)


def test_render_dispatches_on_format():
    v = story_view()
    assert export.render(v, "md", D) == export.render_markdown(v, D)
    assert export.render(v, "txt", D) == export.render_text(v, D)


@pytest.mark.parametrize(
    "theme,name",
    [
        ("Une enquête dans un phare", "une-enquete-dans-un-phare"),
        ("  L'été / Ça ira !  ", "l-ete-ca-ira"),
        ("日本語", "histoire"),
        (None, "histoire"),
        ("x" * 80, "x" * 40),
    ],
)
def test_filename(theme, name):
    assert export.export_filename(story_view(theme=theme), "md", D) == f"cadav-{name}-2026-10-08.md"


def test_save_creates_folder_and_never_overwrites(tmp_path):
    v = story_view()
    folder = tmp_path / "a" / "b"
    first = export.save_story(v, "md", folder, D)
    second = export.save_story(v, "md", folder, D)
    third = export.save_story(v, "txt", folder, D)
    assert first.name == "cadav-le-phare-2026-10-08.md"
    assert second.name == "cadav-le-phare-2026-10-08-2.md"
    assert third.name == "cadav-le-phare-2026-10-08.txt"
    assert first.read_text(encoding="utf-8") == export.render_markdown(v, D)
    assert sorted(p.name for p in folder.iterdir()) == sorted([first.name, second.name, third.name])


def test_save_expands_the_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = export.save_story(story_view(), "txt", "~/out", D)
    assert path.parent == tmp_path / "out" and path.exists()


def test_default_export_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert export.default_export_dir() == str(tmp_path / "cadav")
    (tmp_path / "Documents").mkdir()
    assert export.default_export_dir() == str(tmp_path / "Documents" / "cadav")


class Runner:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, command, **kw):
        self.calls.append((command, kw["input"]))
        if command[0] in self.fail:
            raise subprocess.CalledProcessError(1, command)


def test_clipboard_uses_the_first_available_tool():
    run = Runner()
    which = lambda name: f"/usr/bin/{name}" if name in ("xclip", "xsel") else None  # noqa: E731
    assert export.copy_with_system_tool("été", run, which, "linux") == "xclip"
    assert run.calls == [(["xclip", "-selection", "clipboard"], "été".encode())]


def test_clipboard_falls_back_when_a_tool_fails_or_is_missing():
    run = Runner(fail={"wl-copy"})
    which = lambda name: f"/usr/bin/{name}"  # noqa: E731
    assert export.copy_with_system_tool("x", run, which, "linux") == "xclip"
    assert export.copy_with_system_tool("x", Runner(), lambda n: None, "linux") is None
    assert export.copy_with_system_tool("x", Runner(), which, "freebsd") is None
    assert export.copy_with_system_tool("x", Runner(), which, "darwin") == "pbcopy"
