"""DETERMINISTIC EVAL — the line-oriented CLI resumes its own thread (#28).

Live bug: `main()` pinned itself to a fixed thread tag
(`syrup.session.session_id = "terminal"`) and never read it back. Everything
said last session sat in chat_log under that very tag, unread — close the
terminal and reopen it, and Syrup had forgotten the conversation. The
dashboard already avoided this by adopting a thread through
`Session.switch()`, which both reloads AND retags; #28's fix is for the
terminal surface to call that instead of assigning the tag as a bare
attribute.

Testing seam (per the ticket's own guidance): the wiring object (`Syrup`,
via `syrup.gateway.cli._build_syrup`), exercised twice over the SAME temp
home — construct, converse, discard, construct again. That's exactly the
close-and-reopen a person experiences, and it needs no terminal (`main()`'s
`input()` loop is never touched).

These tests call `_build_syrup` — the real function `main()` calls — not
`Session.switch()` directly. Reverting `_build_syrup` to a bare
`session_id =` assignment makes `test_cli_resumes_thread_across_launches`
fail (working memory stays empty on the second launch), which is the
regression guard #28 asks for.
"""

from __future__ import annotations

from evals.helpers import ScriptedClient, make_syrup, response, settings_for, text_block
from syrup.gateway.cli import _build_syrup


def _gate_skip():
    return response([text_block('{"retrieve": false, "query": "", "reason": "t"}')])


def _seed_pair(app, session_id, user_text, assistant_text, source="cli"):
    app.conn.execute(
        "INSERT INTO chat_log (role, content, session_id, source) VALUES ('user', ?, ?, ?)",
        (user_text, session_id, source),
    )
    app.conn.execute(
        "INSERT INTO chat_log (role, content, session_id, source) VALUES ('assistant', ?, ?, ?)",
        (assistant_text, session_id, source),
    )
    app.conn.commit()


def test_cli_resumes_thread_across_launches(tmp_path):
    """Close and reopen the CLI: the previous launch's turn is already in
    working memory — no re-explaining what was already said."""
    home = tmp_path / "home"
    client1 = ScriptedClient([_gate_skip(), response([text_block("Tokyo it is.")])])
    syrup1 = _build_syrup(settings=settings_for(home), client=client1)
    syrup1.respond("let's plan a trip to Tokyo", source="cli")
    del syrup1  # "close the terminal"

    syrup2 = _build_syrup(settings=settings_for(home), client=ScriptedClient([]))
    texts = [h["content"] for h in syrup2.session.history]
    assert any("plan a trip to Tokyo" in t for t in texts)
    assert any("Tokyo it is" in t for t in texts)


def test_cli_first_launch_on_empty_home_is_a_noop(tmp_path):
    """A brand-new install has nothing to resume: working memory starts
    empty and construction doesn't error."""
    syrup = _build_syrup(settings=settings_for(tmp_path / "home"), client=ScriptedClient([]))
    assert syrup.session.history == []


def test_cli_reloaded_tail_is_bounded_by_history_window(tmp_path):
    """Resuming must not widen the window a live conversation already uses
    — reloading ten past turns with a window of 3 keeps only the newest 3."""
    home = tmp_path / "home"
    seed = make_syrup(home, client=ScriptedClient([]))
    for i in range(10):
        _seed_pair(seed, "terminal", f"message {i}", f"reply {i}")

    syrup = _build_syrup(settings=settings_for(home, history_turns=3), client=ScriptedClient([]))
    assert len(syrup.session.history) == 3 * 2
    texts = " ".join(h["content"] for h in syrup.session.history)
    assert "message 9" in texts and "reply 9" in texts  # newest kept
    assert "message 0" not in texts and "reply 0" not in texts  # oldest trimmed


def test_cli_thread_with_a_cancelled_last_turn_reloads_without_error(tmp_path):
    """A turn cancelled mid-flight (#22) still leaves a full user+assistant
    pair in chat_log (a placeholder, never an empty row) — reloading it on
    the next launch must not error."""
    home = tmp_path / "home"
    seed = make_syrup(home, client=ScriptedClient([]))
    _seed_pair(seed, "terminal", "book something", "[cancelled before replying]")

    syrup = _build_syrup(settings=settings_for(home), client=ScriptedClient([]))
    texts = [h["content"] for h in syrup.session.history]
    assert texts == ["book something", "[cancelled before replying]"]


def test_cli_does_not_pick_up_another_surface_s_history(tmp_path):
    """Each surface keeps its own distinct thread tag — the CLI's launch
    must not see turns logged under the dashboard's tag."""
    home = tmp_path / "home"
    seed = make_syrup(home, client=ScriptedClient([]))
    _seed_pair(seed, "terminal", "cli-only message", "cli-only reply")
    _seed_pair(seed, "dashboard-1", "web-only message", "web-only reply",
               source="dashboard")

    syrup = _build_syrup(settings=settings_for(home), client=ScriptedClient([]))
    texts = " ".join(h["content"] for h in syrup.session.history)
    assert "cli-only message" in texts
    assert "web-only message" not in texts
