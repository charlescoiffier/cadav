import pytest

from cadav import cli


def test_no_command_prints_usage_and_succeeds(capsys):
    assert cli.main([]) == 0
    assert "serve" in capsys.readouterr().out


def test_unknown_command_fails(capsys):
    assert cli.main(["nope"]) == 2
    assert "usage" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["serve", "play"])
def test_subcommands_are_wired(command, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([command, "--help"])
    assert e.value.code == 0
    assert f"cadav {command}" in capsys.readouterr().out
