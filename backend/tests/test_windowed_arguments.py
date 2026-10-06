import sys

import pytest

from backend.app.launcher import StudioArgumentParser


@pytest.mark.parametrize("argument,code", [("--help", 0), ("--invalid-option", 2)])
def test_windowed_arguments_exit_without_console_exception(monkeypatch, argument, code):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        with pytest.raises(SystemExit) as raised:
            StudioArgumentParser(description="NovelAI LAN Studio").parse_args([argument])
        assert raised.value.code == code


def test_console_help_remains_visible(capsys):
    with pytest.raises(SystemExit) as raised:
        StudioArgumentParser(description="NovelAI LAN Studio").parse_args(["--help"])
    assert raised.value.code == 0
    assert "NovelAI LAN Studio" in capsys.readouterr().out
