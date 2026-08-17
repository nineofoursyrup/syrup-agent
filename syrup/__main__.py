"""Entrypoints — installed as the `syrup` command (and `python -m syrup`):

  syrup                       chat in the terminal — the line-oriented prompt
  syrup dashboard             the browser cockpit → localhost:9049 (+ Telegram if configured)
  syrup connections           list configured integrations and their health
  syrup voice                 talk to it (needs the [voice] extra)
  syrup telegram              phone → laptop (needs TELEGRAM_BOT_TOKEN)
  syrup discord               Discord → laptop (needs DISCORD_BOT_TOKEN)
  syrup whatsapp              WhatsApp → laptop (needs WHATSAPP_TOKEN, public URL)
  syrup dingtalk              DingTalk → laptop (needs DINGTALK_CLIENT_ID/SECRET)
  syrup feishu                Feishu → laptop (needs FEISHU_APP_ID/SECRET)
  syrup brief                 morning briefing (calendar + mail + memory) — as a LOOP
  syrup gather                same job as a GRAPH: github, web, calendar and
                             memory fetched together, then one digest
  syrup skill install <url>   install a community skill
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable


def _run_chat() -> None:
    from syrup.gateway.cli import main as cli_main

    cli_main()


def _lazy(module_path: str, attr: str = "main", *, exit_with_result: bool = False):
    """One subcommand's handler, importing its module only when it runs.
    The import has to stay inside the call: `syrup voice` needs the [voice]
    extra and `syrup telegram` needs a token, and neither may be required
    just to type `syrup` or reach a different subcommand."""

    def run(args: list[str]) -> None:
        module = importlib.import_module(module_path)
        result = getattr(module, attr)()
        if exit_with_result:
            sys.exit(result)

    return run


def _usage_and_exit() -> None:
    """Print the help text and fail. Unknown input has always exited 1 here,
    so a typo'd subcommand in a script is caught rather than looking like a
    successful no-op."""
    print(__doc__)
    sys.exit(1)


def _install_skill(args: list[str]) -> None:
    if len(args) < 3 or args[1] != "install":
        _usage_and_exit()
        return  # only reached if sys.exit is stubbed; never index args blindly
    from syrup.memory.procedural.installer import install

    install(args[2])


SUBCOMMANDS: dict[str, Callable[[list[str]], None]] = {
    "dashboard": _lazy("syrup.ops.dashboard"),
    "connections": _lazy("syrup.integrations", "cli_main", exit_with_result=True),
    "voice": _lazy("syrup.gateway.voice"),
    "telegram": _lazy("syrup.gateway.telegram"),
    "discord": _lazy("syrup.gateway.discord"),
    "whatsapp": _lazy("syrup.gateway.whatsapp"),
    "dingtalk": _lazy("syrup.gateway.dingtalk"),
    "feishu": _lazy("syrup.gateway.feishu"),
    "brief": _lazy("syrup.ops.brief"),
    "gather": _lazy("syrup.ops.gather"),
    "skill": _install_skill,
}
"""Every named subcommand, declared in one readable place rather than spread
down a chain of `elif`s. Declared, so it can be READ: a deterministic eval
checks each key against this module's own `--help` text and the README's
command table, which is only possible because the set of commands is data
here instead of control flow."""


def main() -> None:
    """Bare `syrup` opens the terminal chat; anything else is a named
    subcommand looked up in SUBCOMMANDS above."""
    args = sys.argv[1:]
    if not args:
        _run_chat()
        return
    handler = SUBCOMMANDS.get(args[0])
    if handler is None:
        _usage_and_exit()
        return
    handler(args)


if __name__ == "__main__":
    main()
