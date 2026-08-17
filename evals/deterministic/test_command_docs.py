"""DETERMINISTIC EVAL — every subcommand the entrypoint offers is documented,
in both places that claim to list them.

The pattern: read what the interface DECLARES, and fail the gate when the
docs have not kept up. It only works against a declaration, which is why the
CLI could not have it until its subcommands stopped living in a chain of
`elif args[0] ==` — control flow rather than data. `syrup/__main__.py`'s
`SUBCOMMANDS` is that chain turned into a mapping, and this file is the guard
the change makes possible.

Two documents claim to list every command, and both can drift from the code
and from each other:
  - the module docstring, which IS the help text an unknown command prints
  - the README's "所有命令" table, the front-door list

Neither is checked for wording — only that each command appears. Pinning prose
would break on every improved sentence and teach maintainers to fight the test
instead of using it (#30's own settled decision, applied again here).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import syrup.__main__ as entrypoint

REPO = Path(__file__).resolve().parents[2]


def declared_subcommands() -> set[str]:
    """Every named subcommand the entrypoint dispatches, read from its own
    mapping — not a list copied out here and left to go stale the moment a
    thirteenth command is added."""
    return set(entrypoint.SUBCOMMANDS)


def _command_table() -> str:
    """The README's own '## 所有命令' section, isolated up to (not including)
    the next top-level heading — so a command named incidentally elsewhere in
    the README does not count as documented."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    match = re.search(
        r"^## 所有命令\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, "README has no '## 所有命令' section"
    return match.group(1)


def _named_after_syrup(phrases: list[str]) -> set[str]:
    """The command name out of each `syrup <name> ...` phrase. Taken as a
    prefix, so `syrup skill install <url>` documents the `skill` command."""
    return {
        parts[1]
        for phrase in phrases
        if (parts := phrase.split()) and len(parts) >= 2 and parts[0] == "syrup"
    }


def _undocumented_in_markdown(commands: set[str], text: str) -> list[str]:
    """Which of `commands` never appears inside an inline-code literal.
    Backtick-scoped rather than a bare substring search, so a command like
    `gather` cannot pass merely because the word shows up in a sentence."""
    return sorted(commands - _named_after_syrup(re.findall(r"`([^`]+)`", text)))


def _undocumented_in_help(commands: set[str], text: str) -> list[str]:
    """Which of `commands` never begins a line of the help text. The
    docstring is plain terminal output with no markup, so the backtick rule
    above would find nothing — the line itself is the literal here."""
    return sorted(commands - _named_after_syrup(
        [line.strip() for line in text.splitlines()]
    ))


def test_every_subcommand_is_in_the_readme_command_table():
    missing = _undocumented_in_markdown(declared_subcommands(), _command_table())
    assert not missing, (
        f"subcommands missing from the README's command table: {missing}. "
        "A command nobody can find is a command that does not exist."
    )


def test_every_subcommand_is_in_the_help_text():
    """The docstring is what `syrup <typo>` prints. A command absent from it
    is undiscoverable from the terminal even by someone looking."""
    missing = _undocumented_in_help(declared_subcommands(), entrypoint.__doc__)
    assert not missing, f"subcommands missing from the help text: {missing}"


def test_the_guard_actually_fails_on_an_undocumented_command():
    """A documentation guard nobody has seen fail is indistinguishable from
    one that cannot fail (#30's words, and the reason that ticket demanded
    this test) — so inject a command neither document could mention."""
    injected = "notarealsyrupcommand"
    commands = declared_subcommands() | {injected}

    assert injected in _undocumented_in_markdown(commands, _command_table())
    assert injected in _undocumented_in_help(commands, entrypoint.__doc__)


@pytest.mark.parametrize("name", sorted(entrypoint.SUBCOMMANDS))
def test_every_declared_subcommand_is_callable(name):
    """The mapping replaced a dispatch chain; a key whose value is not
    callable would be a command that exists in the docs and crashes when
    run."""
    assert callable(entrypoint.SUBCOMMANDS[name])
