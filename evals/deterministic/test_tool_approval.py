"""A tool call can be declined before it runs (#24) — the loop's approver,
consulted at the same dispatch-time checkpoint cancellation (#21) uses, and
the regression guard that proves every existing caller (scheduled briefing,
memory arena, compare arena, graph nodes) still runs approval-requiring tools
straight through, since none of them supply `approve`.
"""

from __future__ import annotations

from evals.helpers import ScriptedClient, response, text_block, tool_block
from syrup.loop.agent import ApprovalDecision, _declined_result, run_loop
from syrup.tools.mcp_client import MCPBridge
from syrup.tools.registry import Tool, ToolRegistry


def _registry(calls: list[str], *, gated: tuple[str, ...] = ()) -> ToolRegistry:
    registry = ToolRegistry()
    for name in ("first_tool", "second_tool"):
        registry.register(Tool(
            name=name, description=f"records a call to {name}",
            input_schema={"type": "object", "properties": {}},
            fn=lambda _name=name: (calls.append(_name), "ok")[1],
            needs_approval=name in gated,
        ))
    return registry


def test_needs_approval_field_is_static_and_excluded_from_the_model_schema():
    """Declared at the definition site, but never leaks into what the model
    is sent — same treatment as the existing wants_notify precedent."""
    tool = Tool(
        name="gated_tool", description="d",
        input_schema={"type": "object", "properties": {}},
        fn=lambda: "ok", needs_approval=True,
    )
    assert tool.needs_approval is True
    assert "needs_approval" not in tool.to_api()

    registry = ToolRegistry()
    registry.register(tool)
    for schema in registry.schemas():
        assert "needs_approval" not in schema


def test_tool_without_approval_requirement_never_reaches_the_approver():
    calls: list[str] = []
    approver_calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {})], "tool_use"),
        response([text_block("done")]),
    ])

    def approve(name, args):
        approver_calls.append(name)
        return ApprovalDecision(approved=False, reason="should never be asked")

    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls),  # nothing gated
        approve=approve,
    )
    assert approver_calls == []
    assert calls == ["first_tool"]
    assert result.reply == "done"


def test_approved_call_executes_normally():
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {})], "tool_use"),
        response([text_block("done")]),
    ])
    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls, gated=("first_tool",)),
        approve=lambda name, args: ApprovalDecision(approved=True),
    )
    assert calls == ["first_tool"]
    assert result.reply == "done"


def test_declined_call_does_not_execute_and_model_sees_a_distinct_result():
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {}, "tu_1")], "tool_use"),
        response([text_block("ok, asking what they'd prefer")]),
    ])
    messages = [{"role": "user", "content": "go"}]
    result = run_loop(
        client=client, model="m", system="s",
        messages=messages,
        tools=_registry(calls, gated=("first_tool",)),
        approve=lambda name, args: ApprovalDecision(approved=False, reason="not now"),
    )
    assert calls == []  # never dispatched to the tool's fn
    assert result.reply == "ok, asking what they'd prefer"

    # The decline result arrives as the NEXT turn's tool_result content —
    # exactly the seam the issue names.
    tool_result_messages = [m for m in messages if m["role"] == "user" and isinstance(m["content"], list)
                             and m["content"] and m["content"][0].get("type") == "tool_result"]
    assert len(tool_result_messages) == 1
    content = tool_result_messages[0]["content"][0]["content"]
    assert "not run" in content or "did not run" in content
    assert "not now" in content  # the optional reason made it through
    assert "ask" in content.lower()
    assert not content.lower().startswith("error running")


def test_decline_string_is_visibly_distinct_from_a_tool_error_string():
    """The registry's `Error running <name>: ...` wording is built inside
    execute()'s except clause. A declined call never reaches execute, so the
    two strings must never collide."""
    def boom():
        raise ValueError("kaboom")

    registry = ToolRegistry()
    registry.register(Tool(
        name="explodes", description="d",
        input_schema={"type": "object", "properties": {}}, fn=boom,
    ))
    error_text = registry.execute("explodes", {})
    assert error_text == "Error running explodes: kaboom"

    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {}, "tu_1")], "tool_use"),
        response([text_block("ok")]),
    ])
    messages = [{"role": "user", "content": "go"}]
    run_loop(
        client=client, model="m", system="s", messages=messages,
        tools=_registry(calls, gated=("first_tool",)),
        approve=lambda name, args: ApprovalDecision(approved=False),
    )
    decline_text = messages[-2]["content"][0]["content"]
    assert decline_text != error_text
    assert "Error running" not in decline_text


def test_cancellation_is_consulted_before_approval_at_the_same_checkpoint():
    """When both would fire on the same call, cancellation wins and the
    approver is never even asked."""
    calls: list[str] = []
    approver_calls: list[str] = []
    client = ScriptedClient([response([tool_block("first_tool", {})], "tool_use")])

    def approve(name, args):
        approver_calls.append(name)
        return ApprovalDecision(approved=True)

    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls, gated=("first_tool",)),
        should_cancel=lambda: True,  # fires immediately, at iteration top
        approve=approve,
    )
    assert result.cancelled is True
    assert approver_calls == []
    assert calls == []


def test_gated_tool_executes_normally_when_no_approver_is_supplied():
    """Regression-critical: this is what keeps the scheduled briefing and
    both arenas running unattended. A tool marked needs_approval=True still
    runs straight through when the caller supplies no `approve` at all."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {})], "tool_use"),
        response([text_block("done")]),
    ])
    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls, gated=("first_tool",)),
        # no approve= at all
    )
    assert calls == ["first_tool"]
    assert result.reply == "done"


def test_decline_consumes_no_special_iteration_budget():
    """The existing iteration guardrail is unchanged: a decline just becomes
    a tool_result like any other, and the next model call is iteration 2,
    same as an approved call would be."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {})], "tool_use"),
        response([text_block("done")]),
    ])
    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls, gated=("first_tool",)),
        approve=lambda name, args: ApprovalDecision(approved=False),
    )
    assert result.iterations == 2
    assert result.reply == "done"


def test_tool_event_carries_the_approval_decision_for_a_listener_to_read():
    """A surface rendering the turn needs to tell a declined call apart from
    a real result WITHOUT parsing `_declined_result`'s prose (a string match
    would break the moment that wording changes). The "tool" event itself
    carries the decision, so a listener can branch on a plain bool."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {}, "tu_1")], "tool_use"),
        response([tool_block("first_tool", {}, "tu_2")], "tool_use"),
        response([text_block("done")]),
    ])
    events: list[dict] = []
    answers = iter([False, True])
    result = run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls, gated=("first_tool",)),
        observer=lambda kind, ev: events.append(ev) if kind == "tool" else None,
        approve=lambda name, args: ApprovalDecision(approved=next(answers)),
    )
    assert [e["approved"] for e in events] == [False, True]
    assert calls == ["first_tool"]  # only the approved second call ran
    assert result.reply == "done"


def test_tool_event_defaults_approved_true_when_no_approval_was_required():
    """A tool that never needed approval (the common case, every caller
    today) still gets `approved: True` on its event — so the transcript's
    branch reads one consistent field rather than treating "key absent" as a
    third, undocumented case. `reason` (#32) is the same story: always
    present, `None` here since nothing was ever declined."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {})], "tool_use"),
        response([text_block("done")]),
    ])
    events: list[dict] = []
    run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls),  # nothing gated, no approve= supplied
        observer=lambda kind, ev: events.append(ev) if kind == "tool" else None,
    )
    assert events == [{"tool": "first_tool", "args": {}, "output": "ok",
                        "approved": True, "reason": None}]


def test_tool_event_carries_the_decline_reason_for_the_transcript_to_read():
    """#32's own seam, the same shape as #25's `approved` field just above:
    the transcript needs the reason WITHOUT parsing `_declined_result`'s
    prose, so it rides on the "tool" event directly — `None` when no reason
    was given, the exact text otherwise."""
    calls: list[str] = []
    client = ScriptedClient([
        response([tool_block("first_tool", {}, "tu_1")], "tool_use"),
        response([tool_block("first_tool", {}, "tu_2")], "tool_use"),
        response([text_block("done")]),
    ])
    events: list[dict] = []
    decisions = iter([
        ApprovalDecision(approved=False, reason="wrong calendar"),
        ApprovalDecision(approved=False),
    ])
    run_loop(
        client=client, model="m", system="s",
        messages=[{"role": "user", "content": "go"}],
        tools=_registry(calls, gated=("first_tool",)),
        observer=lambda kind, ev: events.append(ev) if kind == "tool" else None,
        approve=lambda name, args: next(decisions),
    )
    assert [e["reason"] for e in events] == ["wrong calendar", None]


def test_declined_result_does_not_retry_instruction_survives_a_reason():
    """#32's own settled implementation decision: 'a reason never softens
    the do-not-retry instruction.' Asserted directly against
    `_declined_result`, not just eyeballed off the reason's presence in the
    model-facing text — a reason must not change the instruction's wording
    at all, only add its own separate clause alongside it."""
    with_reason = _declined_result("first_tool", "wrong calendar")
    without_reason = _declined_result("first_tool", None)
    assert "do not retry" in with_reason.lower()
    assert "wrong calendar" in with_reason
    assert "do not retry" in without_reason.lower()
    # The reason only ever adds its own clause — strip it back out and the
    # rest of the sentence, including the do-not-retry instruction, is
    # byte-for-byte the plain-decline text.
    assert with_reason.replace(" Reason given: wrong calendar", "") == without_reason


def test_declined_result_treats_an_empty_reason_the_same_as_no_reason():
    """An empty string reaching `_declined_result` (which should never
    happen once `normalize_decline_reason` runs at the surface — this is
    the loop's own belt-and-braces) must not read as a reason that says
    nothing."""
    assert _declined_result("first_tool", "") == _declined_result("first_tool", None)


def test_mcp_registered_tools_require_approval_by_default():
    """Third-party code with an implementation this repo has never read —
    asking is the only honest default."""
    bridge = MCPBridge(config_path=__file__)  # never started; path unused here
    tool = bridge._build_tool("fs", {"name": "read_file", "description": "reads a file"})
    assert tool.needs_approval is True
    assert tool.name == "fs_read_file"
