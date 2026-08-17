"""DETERMINISTIC EVAL — what each `syrup ...` invocation actually opens.

The entrypoint is deliberately thin: a bare `syrup` opens the terminal chat,
and everything else is a name looked up in `SUBCOMMANDS`. These tests pin that
dispatch, because it is the one piece of the package every other surface is
reached through — a typo here is a broken front door.

Nothing is imported for real: each handler is monkeypatched at its module
path, so the test never needs a provider key, a token, or an optional extra.
"""

from __future__ import annotations

import sys

import pytest

import syrup.__main__ as entrypoint


def test_bare_command_opens_the_terminal_chat(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["syrup"])
    called = {}
    monkeypatch.setattr("syrup.gateway.cli.main", lambda: called.setdefault("chat", True))
    entrypoint.main()
    assert called.get("chat") is True


def test_named_subcommand_reaches_its_own_handler(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["syrup", "dashboard"])
    called = {}
    monkeypatch.setattr("syrup.ops.dashboard.main", lambda: called.setdefault("dashboard", True))
    entrypoint.main()
    assert called.get("dashboard") is True


def test_a_subcommand_never_falls_through_to_the_chat(monkeypatch):
    """Every declared subcommand must dispatch by name. If one ever fell
    through to the bare-command branch, `syrup voice` would silently open a
    text prompt instead — a wrong surface is worse than an error."""
    monkeypatch.setattr(
        "syrup.gateway.cli.main", lambda: pytest.fail("a subcommand opened the chat")
    )
    handled: list[str] = []
    for name in entrypoint.SUBCOMMANDS:
        monkeypatch.setattr(sys, "argv", ["syrup", name])
        monkeypatch.setitem(entrypoint.SUBCOMMANDS, name, lambda args: handled.append(args[0]))
        entrypoint.main()
        assert handled[-1] == name


def test_an_unknown_command_prints_the_help_and_exits_nonzero(monkeypatch, capsys):
    """A typo'd subcommand in a script must fail loudly, not look like a
    successful no-op."""
    monkeypatch.setattr(sys, "argv", ["syrup", "dashbord"])
    with pytest.raises(SystemExit) as exit_info:
        entrypoint.main()
    assert exit_info.value.code == 1
    assert "syrup dashboard" in capsys.readouterr().out
