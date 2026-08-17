"""run_loop's cancellation checkpoints (#21) — and the regression guard that
proves every existing caller (scheduled briefing, memory arena, compare arena,
graph nodes) behaves exactly as it did before this ticket, since none of them
supply `should_cancel`.
"""

from __future__ import annotations

from evals.helpers import ScriptedClient, response, text_block, tool_block
from syrup.loop.agent import run_loop
from syrup.tools.registry import Tool, ToolRegistry


def _registry(calls: list[str]) -> ToolRegistry:
    registry = ToolRegistry()
    for name in ("first_tool", "second_tool"):
        registry.register(Tool(
            name=name, description=f"records a call to {name}",
            input_schema={"type": "object", "properties": {}},
            fn=lambda _name=name: (calls.append(_name), "ok")[1],
        ))
    return registry


def _cancel_after(n: int):
    """A should_cancel closure that answers False for its first n-1 calls,
    then True from the nth call onward — the "scripted cancellation closure
    that flips true on its Nth call" the issue asks for."""
    checks = {"count": 0}

    def should_cancel() -> bool:
        checks["count"] += 1
        return checks["count"] >= n

    return should_cancel


def test_no_should_cancel_behaves_exactly_as_before():
    """The regression criterion: callers that pass no cancellation callable
    (today, every caller) get the same multi-turn tool flow they always have."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {})], "tool_use"),
        response([text_block("done")]),
    ])
    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls),
    )
    assert calls == ["first_tool"]
    assert result.reply == "done"
    assert result.iterations == 2
    assert result.cancelled is False


def test_should_cancel_true_at_iteration_boundary_skips_further_model_calls():
    """A closure that flips True on its Nth call, checked at the top of each
    iteration: once it fires, no further model call happens — the loop just
    returns with whatever tool calls already ran."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {})], "tool_use"),
        response([tool_block("second_tool", {})], "tool_use"),  # never reached
    ])
    # call 1: iteration 1's boundary (False) · call 2: before first_tool's
    # dispatch (False, so it runs) · call 3: iteration 2's boundary (True)
    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls),
        should_cancel=_cancel_after(3),
    )
    assert calls == ["first_tool"]      # iteration 1's tool ran before cancellation
    assert result.cancelled is True
    assert result.iterations == 1       # never entered iteration 2's model call
    assert client.remaining() == 1      # iteration 2's scripted response was never consumed


def test_should_cancel_true_before_a_tool_dispatch_skips_it_and_later_tools():
    """A single turn asks for two tools. Cancellation fires right before the
    second dispatch: the first tool (already committed to) still runs, the
    second does not, and the loop returns instead of making another model
    call."""
    calls: list[str] = []
    client = ScriptedClient([
        response(
            [tool_block("first_tool", {}, "tu_1"), tool_block("second_tool", {}, "tu_2")],
            "tool_use",
        ),
        response([text_block("would have replied")]),  # never reached
    ])
    # call 1: iteration 1's boundary (False) · call 2: before first_tool
    # (False, so it runs) · call 3: before second_tool (True, so it's skipped)
    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls),
        should_cancel=_cancel_after(3),
    )
    assert calls == ["first_tool"]           # second_tool never dispatched
    assert result.cancelled is True
    assert [c["tool"] for c in result.tool_calls] == ["first_tool"]
    assert client.remaining() == 1           # no further model call was made


# ---- wire hygiene when cancellation cuts a dispatch list short
#
# ADR 0002 says a cancelled turn is recorded, not discarded, and `messages` is
# what gets recorded — run_loop's own docstring calls it "the full working
# memory of the turn, which is exactly what gets traced". Cancelling used to
# leave that record malformed: the assistant message's `tool_use` blocks kept
# their ids, but the user message that answers them carried results only for
# the calls that ran, so the skipped ones had no `tool_result` at all — and
# cancelling before the FIRST dispatch appended `content: []`, an empty user
# turn. Neither is resent to a provider today (the turn returns immediately and
# the next turn rebuilds `messages` from the conversation record), so this was
# never a live failure — but a trace that shows an exchange no API would accept
# is a trace that lies about what happened.


def _ids(messages: list[dict]) -> tuple[set, set]:
    """Every tool_use id the assistant asked for, and every tool_use_id the
    following user message answered — the pairing the wire format requires."""
    asked, answered = set(), set()
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                answered.add(block["tool_use_id"])
            elif getattr(block, "type", None) == "tool_use":
                asked.add(block.id)
    return asked, answered


def test_cancelling_before_the_first_dispatch_leaves_no_empty_user_turn():
    """Cancelling at the dispatch checkpoint of the very first call used to
    append `{"role": "user", "content": []}` — a user turn saying nothing,
    answering two outstanding tool_use blocks with silence."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {}, "tu_1"),
                  tool_block("second_tool", {}, "tu_2")], "tool_use"),
        response([text_block("unreachable")]),
    ])
    messages: list[dict] = [{"role": "user", "content": "go"}]

    result = run_loop(client=client, model="m", system="s", messages=messages,
                      tools=_registry(calls), should_cancel=_cancel_after(2))

    assert result.cancelled is True
    assert calls == []
    assert not any(m.get("content") == [] for m in messages), \
        "a cancelled turn left an empty user message in the traced working memory"


def test_every_tool_use_is_answered_even_when_cancellation_cuts_in():
    """The wire contract: one tool_result per tool_use, however the turn
    ended. The skipped calls are answered as not-run, so the record shows
    both what ran and what was stopped."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {}, "tu_1"),
                  tool_block("second_tool", {}, "tu_2")], "tool_use"),
        response([text_block("unreachable")]),
    ])
    messages: list[dict] = [{"role": "user", "content": "go"}]

    result = run_loop(client=client, model="m", system="s", messages=messages,
                      tools=_registry(calls), should_cancel=_cancel_after(3))

    assert result.cancelled is True
    assert calls == ["first_tool"]          # the second was stopped before dispatch
    asked, answered = _ids(messages)
    assert asked and asked == answered, f"unanswered tool_use blocks: {asked - answered}"


def test_a_skipped_call_is_not_recorded_as_a_tool_that_ran():
    """`LoopResult.tool_calls` is what ADR 0002 persists as "the tool calls
    that actually executed" — a call stopped before dispatch must not pad it,
    even though the wire record answers it."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {}, "tu_1"),
                  tool_block("second_tool", {}, "tu_2")], "tool_use"),
        response([text_block("unreachable")]),
    ])

    result = run_loop(client=client, model="m", system="s",
                      messages=[{"role": "user", "content": "go"}],
                      tools=_registry(calls), should_cancel=_cancel_after(3))

    assert [c["tool"] for c in result.tool_calls] == ["first_tool"]


def test_an_uncancelled_turn_is_unchanged():
    """Regression guard: nothing above may alter the ordinary path."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {}, "tu_1"),
                  tool_block("second_tool", {}, "tu_2")], "tool_use"),
        response([text_block("done")]),
    ])
    messages: list[dict] = [{"role": "user", "content": "go"}]

    result = run_loop(client=client, model="m", system="s", messages=messages,
                      tools=_registry(calls))

    assert result.cancelled is False
    assert calls == ["first_tool", "second_tool"]
    asked, answered = _ids(messages)
    assert asked == answered
