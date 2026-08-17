"""The triage graph workflow + its app.py wiring — scripted, zero network.

SCRIPTED-RESPONSE ORDER, read this before adding cases: with graph_workflows
ON, the FIRST scripted response is the triage classifier. A quick turn then
consumes one quick-reply response. A full turn consumes the retrieval gate
next, THEN the loop's responses — i.e. everything test_tool_trigger.py taught
you, shifted one response later.
"""

from __future__ import annotations

import json

from evals.helpers import ScriptedClient, make_syrup, response, text_block, tool_block
from syrup.graph.workflows.triage import classify_message, todays_events
from syrup.loop.agent import ApprovalDecision
from syrup.tools.registry import Tool


def last_meta(app) -> dict:
    """The persisted turn meta, exactly as a reopened thread would read it."""
    row = app.conn.execute(
        "SELECT meta FROM chat_log WHERE role='assistant' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return json.loads(row["meta"])


class Boom:
    """A client whose every call explodes — for the fail-open cases."""

    def __init__(self):
        from types import SimpleNamespace
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        raise RuntimeError("boom")


def classify(reply_text: str):
    return classify_message(ScriptedClient([response([text_block(reply_text)])]),
                            "small-model", "hello")


def test_classifier_parses_routes_and_fails_open_on_garbage():
    assert classify('{"route": "quick", "reason": "just a greeting"}') == (
        "quick", "just a greeting")
    assert classify('{"route": "full", "reason": "needs calendar"}')[0] == "full"
    # every malformed shape falls open to full — capability over latency
    assert classify("no json here at all")[0] == "full"
    assert classify('{"route": "sideways"}')[0] == "full"
    assert classify_message(Boom(), "small-model", "hi")[0] == "full"


def test_todays_events_reads_the_ics(tmp_path):
    assert todays_events(tmp_path) == "(no calendar)"
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    (tmp_path / "calendar.ics").write_text(
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:swim\n"
        f"DTSTART:{today}T090000\nEND:VEVENT\nEND:VCALENDAR\n", encoding="utf-8")
    assert todays_events(tmp_path) == "swim"


def test_flag_off_is_byte_for_byte_the_old_world(tmp_path):
    gate = response([text_block('{"retrieve": false, "query": "", "reason": "test"}')])
    app = make_syrup(tmp_path / "home",
                    client=ScriptedClient([gate, response([text_block("Hi!")])]),
                    graph_workflows=False)
    events = []
    result = app.respond("hello", observer=lambda k, ev: events.append(k))
    assert result.reply == "Hi!"
    assert not any(k in ("graph_start", "route", "graph_end") for k in events)
    meta = last_meta(app)
    assert meta["graph"] is None


def test_quick_turn_answers_on_the_small_model_and_skips_the_gate(tmp_path):
    script = [
        response([text_block('{"route": "quick", "reason": "just thanks"}')]),  # triage
        response([text_block("You're welcome!")]),                              # quick reply
    ]
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script),
                    graph_workflows=True, small_model="small-model")
    events: list[tuple[str, dict]] = []
    result = app.respond("thanks!", observer=lambda k, ev: events.append((k, ev)))

    assert result.reply == "You're welcome!"
    assert result.iterations == 1 and result.tool_calls == []
    kinds = [k for k, _ in events]
    assert "graph_start" in kinds and "route" in kinds and "graph_end" in kinds
    assert "gate" not in kinds, "quick turns never touch memory retrieval"
    assert "llm" not in kinds, "quick turns never wake the big model's loop"
    meta = last_meta(app)
    assert meta["graph"]["route"] == "quick"
    assert meta["graph"]["reason"] == "just thanks"
    assert meta["gate"] is None
    assert meta["model"] == "small-model"          # honest per-path model


def test_full_turn_runs_the_real_loop_with_both_funnel_stages(tmp_path):
    script = [
        response([text_block('{"route": "full", "reason": "wants an event"}')]),   # triage
        response([text_block('{"retrieve": false, "query": "", "reason": "n"}')]),  # gate
        response([tool_block("create_event", {"title": "Swim", "start": "2026-08-01 09:00",
                                              "end": "2026-08-01 10:00"})], "tool_use"),
        response([text_block("Booked!")]),
    ]
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script),
                    graph_workflows=True)
    events: list[str] = []
    result = app.respond("swim saturday 9am", observer=lambda k, ev: events.append(k))

    assert result.reply == "Booked!"
    assert result.tool_calls and result.tool_calls[0]["tool"] == "create_event"
    assert "route" in events and "gate" in events   # both funnel stages recorded
    meta = last_meta(app)
    assert meta["graph"]["route"] == "full"
    assert meta["gate"] is not None
    assert meta["model"] == app.settings.model
    assert "full_agent" in meta["graph"]["path"]


def test_broken_classifier_fails_open_to_the_full_loop(tmp_path):
    script = [
        response([text_block("not json — classifier had a bad day")]),               # triage
        response([text_block('{"retrieve": false, "query": "", "reason": "n"}')]),   # gate
        response([text_block("Still here.")]),                                        # loop
    ]
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script),
                    graph_workflows=True)
    assert app.respond("hello?").reply == "Still here."


def test_broken_graph_engine_fails_open_to_the_plain_loop(tmp_path, monkeypatch):
    """Layer two: even if graph construction itself explodes, respond() answers."""
    from syrup.graph.workflows import triage

    def explode(**kwargs):
        raise RuntimeError("graph machinery on fire")
    monkeypatch.setattr(triage, "build_triage_graph", explode)
    script = [
        response([text_block('{"retrieve": false, "query": "", "reason": "n"}')]),   # gate
        response([text_block("Saved by the loop.")]),
    ]
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script),
                    graph_workflows=True)
    events: list[str] = []
    result = app.respond("hello", observer=lambda k, ev: events.append(k))
    assert result.reply == "Saved by the loop."
    assert "graph_end" in events                     # the failure is on tape
    meta = last_meta(app)
    assert meta["graph"] is None                     # no route happened — honest meta


# #26: the graph front door dropped should_cancel/approve entirely — the
# gates worked on the plain path but vanished the moment a turn routed
# through the triage graph. Everything below drives that path explicitly
# (graph_workflows=True) and proves both callables now reach it.

def _full_route_script(reason: str, *extra):
    """The two responses every full-route turn spends before it ever reaches
    the loop (triage, then the retrieval gate), plus whatever the loop
    itself will consume. Shared by every test below so each one only has to
    say what's distinctive about it."""
    return [
        response([text_block(f'{{"route": "full", "reason": "{reason}"}}')]),        # triage
        response([text_block('{"retrieve": false, "query": "", "reason": "n"}')]),  # gate
        *extra,
    ]


def _register_gated_note_tool(app, calls: list[dict]) -> None:
    app.tools.register(Tool(
        name="gated_tool", description="a tool that requires approval",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        fn=lambda text: (calls.append({"text": text}), "done")[1],
        needs_approval=True,
    ))


def test_full_turn_honours_cancellation_on_the_graph_path(tmp_path):
    """The script below is a COMPLETE, valid turn — if should_cancel is
    dropped (the bug), the loop runs it to completion and books the event.
    A short script would also "pass" here for the wrong reason: the
    retrieval gate fails open on a script it can't read, which can mask a
    missing should_cancel behind an accidental cancellation later. A full
    script is what makes this a real regression test."""
    script = _full_route_script(
        "wants an event",
        response([tool_block("create_event", {"title": "Swim", "start": "2026-08-01 09:00",
                                              "end": "2026-08-01 10:00"})], "tool_use"),
        response([text_block("Booked!")]),
    )
    client = ScriptedClient(script)
    app = make_syrup(tmp_path / "home", client=client, graph_workflows=True)

    result = app.respond("swim saturday 9am", should_cancel=lambda: True)

    assert result.cancelled is True
    assert result.reply == ""
    assert client.remaining() == 2            # the tool_use + final reply were never touched
    row = app.conn.execute("SELECT COUNT(*) c FROM calendar_events").fetchone()
    assert row["c"] == 0                      # the event was never created
    meta = last_meta(app)
    assert meta["cancelled"] is True


def test_full_turn_honours_a_decline_on_the_graph_path(tmp_path):
    calls: list[dict] = []
    script = _full_route_script(
        "wants a note",
        response([tool_block("gated_tool", {"text": "milk"})], "tool_use"),
        response([text_block("ok, not saved")]),
    )
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script), graph_workflows=True)
    _register_gated_note_tool(app, calls)

    result = app.respond(
        "note milk", approve=lambda name, args: ApprovalDecision(approved=False, reason="not now"))

    assert calls == []                        # declined — never dispatched
    assert result.reply == "ok, not saved"


def test_gated_tool_runs_straight_through_with_neither_callable_on_the_graph_path(tmp_path):
    """Regression-critical: the flag must never change whether an unattended
    caller (the scheduled briefing, both arenas) gets asked anything — with
    no should_cancel and no approve supplied, a gated tool still just runs,
    on the graph path exactly as it always has on the plain one."""
    calls: list[dict] = []
    script = _full_route_script(
        "wants a note",
        response([tool_block("gated_tool", {"text": "milk"})], "tool_use"),
        response([text_block("saved")]),
    )
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script), graph_workflows=True)
    _register_gated_note_tool(app, calls)

    result = app.respond("note milk")

    assert calls == [{"text": "milk"}]
    assert result.reply == "saved"


def test_mcp_tool_still_requires_approval_on_the_graph_path(tmp_path):
    """An MCP-registered tool (needs_approval=True, not overridable) must
    still be asked about on the graph path when a caller supplies approve —
    the same default #24 gave the plain loop."""
    from syrup.tools.mcp_client import MCPBridge

    bridge = MCPBridge(config_path=tmp_path / "mcp.json")  # never started; path unused here
    tool = bridge._build_tool("fs", {"name": "read_file", "description": "reads a file"})
    tool.fn = lambda **kwargs: "file contents"
    approver_calls: list[str] = []
    script = _full_route_script(
        "wants a file",
        response([tool_block("fs_read_file", {"path": "a.txt"})], "tool_use"),
        response([text_block("here it is")]),
    )
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script), graph_workflows=True)
    app.tools.register(tool)

    def approve(name, args):
        approver_calls.append(name)
        return ApprovalDecision(approved=True)

    result = app.respond("read a.txt", approve=approve)

    assert approver_calls == ["fs_read_file"]
    assert result.reply == "here it is"


def test_cancellation_is_consulted_before_approval_on_the_graph_path(tmp_path):
    """Same shape as the cancellation test above, and for the same reason: a
    COMPLETE script, so a dropped should_cancel would let the gated tool
    actually run (auto-approved, since a dropped approve means run_loop's
    own default kicks in) instead of merely raising and masking the bug."""
    calls: list[dict] = []
    approver_calls: list[str] = []
    script = _full_route_script(
        "wants a note",
        response([tool_block("gated_tool", {"text": "milk"})], "tool_use"),
        response([text_block("done")]),
    )
    client = ScriptedClient(script)
    app = make_syrup(tmp_path / "home", client=client, graph_workflows=True)
    _register_gated_note_tool(app, calls)

    def approve(name, args):
        approver_calls.append(name)
        return ApprovalDecision(approved=True)

    result = app.respond("note milk", should_cancel=lambda: True, approve=approve)

    assert result.cancelled is True
    assert result.reply == ""
    assert client.remaining() == 2             # tool_use + final reply never touched
    assert approver_calls == []                # cancellation wins — approve never asked
    assert calls == []


def test_fail_open_fallback_still_honours_cancellation(tmp_path, monkeypatch):
    """Layer two of #26: even when graph construction itself explodes and
    respond() falls open to the plain loop, should_cancel must still reach
    that fallback call — the same guarantee the flag-off default gives."""
    from syrup.graph.workflows import triage

    def explode(**kwargs):
        raise RuntimeError("graph machinery on fire")
    monkeypatch.setattr(triage, "build_triage_graph", explode)
    script = [response([text_block('{"retrieve": false, "query": "", "reason": "n"}')])]  # gate
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script), graph_workflows=True)

    result = app.respond("hello", should_cancel=lambda: True)

    assert result.cancelled is True
    assert result.reply == ""


# #27: #26 wired should_cancel/approve onto the FULL route only. The quick
# route (classify_message then quick_reply, no loop involved) still could
# not be cancelled — a cancelled quick turn used to persist as an ordinary
# completed one while the TUI painted it as interrupted. Everything below
# forces the quick route explicitly and proves the record now agrees.

def _quick_route_script(reason: str, reply: str):
    """The two responses every quick-route turn spends: triage, then the
    small model's actual reply. Shared so each test below only says what's
    distinctive about it — same idea as _full_route_script above."""
    return [
        response([text_block(f'{{"route": "quick", "reason": "{reason}"}}')]),  # triage
        response([text_block(reply)]),                                          # quick reply
    ]


def test_quick_turn_honours_cancellation_after_both_model_calls(tmp_path):
    """A COMPLETE quick-route script (classify + quick_reply), same reasoning
    as the full-route cancellation test above: if should_cancel were still
    dropped on this path, the turn would report cancelled=False and the reply
    would be the model's real text instead of being marked cancelled."""
    script = _quick_route_script("just thanks", "You're welcome!")
    client = ScriptedClient(script)
    app = make_syrup(tmp_path / "home", client=client, graph_workflows=True)

    result = app.respond("thanks!", should_cancel=lambda: True)

    assert result.cancelled is True
    assert client.remaining() == 0            # both model calls ran — nothing to protect mid-flight
    assert result.reply == "You're welcome!"  # persisted, not discarded (#22)
    meta = last_meta(app)
    assert meta["cancelled"] is True
    assert meta["graph"]["route"] == "quick"
    row = app.conn.execute(
        "SELECT content FROM chat_log WHERE role='assistant' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["content"] == "You're welcome!"   # reply persisted, not discarded (#22)


def test_quick_turn_with_no_cancel_callable_is_unchanged(tmp_path):
    """With the flag on and no should_cancel supplied, the quick route must
    behave exactly as it did before #27 — this is the regression that would
    catch an accidental unconditional should_cancel() call."""
    script = _quick_route_script("just thanks", "You're welcome!")
    app = make_syrup(tmp_path / "home", client=ScriptedClient(script), graph_workflows=True)

    result = app.respond("thanks!")

    assert result.cancelled is False
    assert result.reply == "You're welcome!"


# ---- triage must classify IN CONTEXT (the "是" black hole)
#
# Live bug, found on the dashboard on 2026-08-12. Turn 1 asked to book a
# meeting at a time that had already passed; the reply did the right thing and
# asked "did you mean this afternoon?". Turn 2 was the single character 是 —
# yes. Triage saw one word with no conversation around it, called it
# "简单确认" and routed quick. quick_reply runs no tools, so the confirmed
# meeting was never created: the user got "好的，有需要随时告诉我。" and an
# empty calendar.
#
# Two causes, both the shape #26 and #27 already established — the graph front
# door missing something the plain loop has, with no error and no visible
# degradation:
#   1. the classifier was shown only the current message, never the turn before
#   2. quick_reply's prompt carried no history either, so even a correctly
#      routed quick turn could not resolve 是 to anything
#
# A bare confirmation after a question is the commonest follow-up there is, and
# the scheduling skill is instructed to ask whenever memory gives it nothing —
# so the skill behaving well is what walks the user into this.


class RecordingClient(ScriptedClient):
    """A ScriptedClient that keeps every request payload, so a test can assert
    what the model was actually shown rather than only what it replied."""

    def __init__(self, script):
        super().__init__(script)
        self.calls: list[list[dict]] = []

    def _create(self, **kwargs):
        self.calls.append(kwargs.get("messages", []))
        return super()._create(**kwargs)


def _as_text(messages: list[dict]) -> str:
    return " ".join(
        m.get("content", "") if isinstance(m.get("content"), str) else str(m.get("content"))
        for m in messages
    )


PENDING = [
    {"role": "user", "content": "帮我安排今天上午3.30跟柏林团队开会"},
    {"role": "assistant", "content": "今天上午 3:30 已经过去了。你是想安排今天下午 3:30 和柏林团队开会吗？"},
]


def test_the_classifier_is_shown_the_conversation(tmp_path):
    """The routing decision for 是 is only answerable with the turn before it.
    Shown the question, a classifier can see this continues a booking; shown
    one character, the only honest reading is small talk."""
    client = RecordingClient([
        response([text_block('{"route": "full", "reason": "continues the booking"}')]),
        response([text_block('{"retrieve": false, "query": "", "reason": "t"}')]),
        response([text_block("booked")]),
    ])
    app = make_syrup(tmp_path / "home", client=client, graph_workflows=True)
    app.session.history.extend(PENDING)

    app.respond("是")

    triage_payload = _as_text(client.calls[0])
    assert "柏林" in triage_payload, (
        "the triage classifier was given only the current message — it cannot "
        "tell a confirmation from small talk without the turn it answers"
    )


def test_a_quick_turn_can_still_see_the_conversation(tmp_path):
    """Even when quick IS the right route, the reply has to resolve what the
    message refers to."""
    client = RecordingClient([
        response([text_block('{"route": "quick", "reason": "small talk"}')]),
        response([text_block("好的")]),
    ])
    app = make_syrup(tmp_path / "home", client=client, graph_workflows=True)
    app.session.history.extend(PENDING)

    app.respond("谢谢")

    quick_payload = _as_text(client.calls[-1])
    assert "柏林" in quick_payload, "quick_reply was built with no conversation history"
