"""DETERMINISTIC EVAL — a cancelled turn (#21's should_cancel, threaded
through Syrup.respond by #22) is recorded honestly, not discarded, and the
conversation still works afterwards.

No surface cancels anything yet (that's #23) — these evals drive cancellation
directly through `respond(should_cancel=...)`, the seam #22 adds so this can
be tested before any gateway wires a real cancel button.
"""

from __future__ import annotations

import json

from evals.helpers import ScriptedClient, make_syrup, response, text_block, tool_block


def _gate_skip():
    return response([text_block('{"retrieve": false, "query": "", "reason": "t"}')])


def _last_assistant_row(app):
    return app.conn.execute(
        "SELECT content, meta FROM chat_log WHERE role='assistant' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def test_cancel_before_any_tool_dispatch_then_next_turn_still_works(tmp_path):
    """The concrete regression: cancelling at an iteration boundary, before
    any tool ran, used to append an assistant history entry with EMPTY
    content — which a real provider rejects on the very next call. Here the
    scripted client never inspects message shape, so the test instead asserts
    directly on the shape working-memory assembly produces, and proves the
    conversation keeps going."""
    gate1 = _gate_skip()
    gate2 = _gate_skip()
    reply2 = response([text_block("ok, done")])
    client = ScriptedClient([gate1, gate2, reply2])
    app = make_syrup(tmp_path / "home", client=client)

    result = app.respond("book something", should_cancel=lambda: True)

    assert result.cancelled is True
    assert result.reply == ""
    assert result.tool_calls == []
    assert client.remaining() == 2  # only the gate call was consumed; run_loop never called the model

    # working-memory assembly must tolerate this turn: no empty content block
    last = app.session.history[-1]
    assert last["role"] == "assistant"
    assert last["content"], "assistant history entry must not be empty content"

    row = _last_assistant_row(app)
    assert row["content"], "persisted chat_log row must not be empty content"
    meta = json.loads(row["meta"])
    assert meta["cancelled"] is True
    assert meta["tools"] == []

    # the next turn must actually go through — the empty-assistant-entry bug
    # would have poisoned this call with an unacceptable message shape
    result2 = app.respond("try again")
    assert result2.cancelled is False
    assert result2.reply == "ok, done"


def test_cancel_mid_dispatch_persists_exactly_the_tools_that_ran(tmp_path):
    """A turn asks for two tools; cancellation fires between them. The world
    already changed (create_event ran) so it must be persisted, not
    discarded — and the persisted row must carry exactly the tool that ran,
    not the one that didn't."""
    gate = _gate_skip()
    turn = response(
        [tool_block("create_event", {"title": "A", "start": "2026-07-14T09:00"}, "tu_1"),
         tool_block("save_note", {"subject": "b", "content": "c"}, "tu_2")],
        "tool_use",
    )
    client = ScriptedClient([gate, turn])
    app = make_syrup(tmp_path / "home", client=client)

    checks = {"n": 0}

    def should_cancel() -> bool:
        # 1: iteration boundary (False) · 2: before create_event (False, runs)
        # · 3: before save_note (True, skipped)
        checks["n"] += 1
        return checks["n"] >= 3

    result = app.respond("book A and save a note", should_cancel=should_cancel)

    assert result.cancelled is True
    assert [c["tool"] for c in result.tool_calls] == ["create_event"]

    # the world already changed — create_event's row is really there
    row = app.conn.execute("SELECT title FROM calendar_events").fetchone()
    assert row["title"] == "A"

    persisted = _last_assistant_row(app)
    meta = json.loads(persisted["meta"])
    assert meta["cancelled"] is True
    assert [t["tool"] for t in meta["tools"]] == ["create_event"]
    assert "save_note" not in [t["tool"] for t in meta["tools"]]
    assert "[tools used: create_event" in persisted["content"]
    assert "save_note" not in persisted["content"]


def test_trace_records_the_turn_as_cancelled(tmp_path):
    """The trace must say the turn was cancelled, not just that it ended."""
    client = ScriptedClient([_gate_skip()])
    app = make_syrup(tmp_path / "home", client=client)

    app.respond("book something", should_cancel=lambda: True)

    lines = [json.loads(line) for line in app.tracer.path.read_text().splitlines()]
    turn_end = [rec for rec in lines if rec["type"] == "turn_end"][-1]
    assert turn_end["cancelled"] is True


def test_uncancelled_turn_is_traced_as_not_cancelled(tmp_path):
    """Regression guard: an ordinary turn must not look cancelled."""
    client = ScriptedClient([_gate_skip(), response([text_block("Paris.")])])
    app = make_syrup(tmp_path / "home", client=client)

    app.respond("capital of france?")

    lines = [json.loads(line) for line in app.tracer.path.read_text().splitlines()]
    turn_end = [rec for rec in lines if rec["type"] == "turn_end"][-1]
    assert turn_end["cancelled"] is False
