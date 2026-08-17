"""CLI gateway — the zero-setup way to talk to your Syrup.

The Gateway Interface box: a gateway only moves text in and out; everything
interesting happens in the loop. The Telegram gateway is the same ~60 lines
with polling instead of input().
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from syrup.app import Syrup

console = Console()


def _observer(kind: str, event: dict) -> None:
    """Show the loop's internals live — the video's 'transparent harness' beat."""
    if kind == "tool":
        console.print(f"  [dim]tool · {event['tool']}({event['args']}) → {event['output'][:80]}[/dim]")
    elif kind == "gate":
        console.print(f"  [dim]gate · {event['decision']} — {event.get('reason','')}[/dim]")
    elif kind == "consolidation":
        console.print(f"  [dim]memory · consolidated {event['new_facts']} fact(s) from recent chats[/dim]")


def _build_syrup(settings=None, client=None) -> Syrup:
    """Construct Syrup and adopt this surface's own thread. `switch` (not a
    bare `session_id =`) is what actually reloads the tail of that thread's
    past chat_log rows into working memory — a close-and-reopen otherwise
    forgets everything said last session (#28). Args are injectable the same
    way `Syrup.__init__`'s are, so evals can build this against a temp home
    with a scripted client instead of the real settings/model."""
    syrup = Syrup(settings=settings, client=client)
    syrup.session.switch("terminal")   # its own conversation thread in the inbox
    return syrup


def main() -> None:
    syrup = _build_syrup()
    console.print(Panel.fit(
        "[bold]Syrup[/bold] — local, yours, transparent.\n"
        f"home: {syrup.settings.home.resolve()}   model: {syrup.settings.model}\n"
        "Commands: /memory · /quit",
        border_style="cyan",
    ))
    while True:
        try:
            user_message = console.input("[bold cyan]you ›[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_message:
            continue
        if user_message in ("/quit", "/exit"):
            break
        if user_message == "/memory":
            console.print(
                Panel(
                    Text(syrup.memory_snapshot()),
                    title="Memory snapshot",
                    border_style="cyan",
                )
            )
            continue
        result = syrup.respond(user_message, observer=_observer, source="cli")
        console.print(f"[bold green]syrup ›[/bold green] {result.reply}\n")
    console.print("[dim]bye — your memory stays in state.db[/dim]")


if __name__ == "__main__":
    main()
