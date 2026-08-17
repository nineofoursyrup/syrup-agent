"""THE LOOP — observe → reason → act → repeat. This file is the whole trick.

Every agent framework is ultimately this while-loop with more indirection:

    while not done:
        response = llm(messages, tools)          # reason
        if response asks for tools:
            results = run(tool_calls)            # act
            messages += results                  # observe
        else:
            done                                 # reply to the human

End-loop guardrails (the orange box's exit conditions):
  1. the model stops asking for tools  → natural end of turn
  2. max_iterations reached            → hard stop, never spin forever
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic

from syrup.tools.registry import ToolRegistry

# Observers let the gateway show tool calls live and let ops/tracing record
# them — without either being wired into the loop's logic.
LoopEvent = dict[str, Any]
Observer = Callable[[str, LoopEvent], None]

# Same shape as Observer, deliberately: a plain callable a caller can supply
# to ask "should this turn stop?" without the loop knowing who's asking or
# why. No gateway in this repo wires one up today — it is the seam a surface
# that can interrupt a running turn plugs into. See run_loop's docstring.
CancelCheck = Callable[[], bool]


@dataclass
class ApprovalDecision:
    """What an approver decided about one call. `reason` carries why a person
    declined, for a surface that can ask; it was part of the interface from
    the start so adding the question later never became a breaking change.
    Every caller that just runs tools (scheduled briefing, both arenas, graph
    nodes) leaves it `None`."""

    approved: bool
    reason: str | None = None


# Same shape as CancelCheck, deliberately: a plain callable a caller can
# supply, consulted immediately before dispatch — but only for a tool whose
# static `needs_approval` is True (ToolRegistry.requires_approval); tools
# that don't require approval never reach it. Takes the tool's name and its
# arguments, returns the decision. No surface wires one up yet — #25 is the
# first; every other caller passes None and gets no gate, so a tool that
# requires approval just runs, unchanged from before this ticket.
Approver = Callable[[str, dict[str, Any]], ApprovalDecision]


def _declined_result(name: str, reason: str | None) -> str:
    """The text the model sees for a declined call. Built here, at the
    loop's dispatch site — not inside ToolRegistry.execute, whose `Error
    running <name>: <exc>` wording only exists for a genuine failure a model
    could reasonably retry. A declined call never reaches execute, so it can
    never accidentally read like that string. This one says the opposite:
    it did not run, this isn't an error, don't retry — ask the person what
    they'd prefer instead."""
    why = f" Reason given: {reason}" if reason else ""
    return (
        f"{name} was not run: the person declined this call.{why} "
        "This is not an error — do not retry it. Ask what they'd prefer instead."
    )


_UNRUN_RESULT = (
    "Not run: the person stopped this turn before this call was dispatched."
)


def _unrun_results(skipped: list[Any]) -> list[dict]:
    """One tool_result per tool_use cancellation skipped, so every call the
    assistant asked for is answered. Deliberately NOT recorded as events:
    `LoopResult.tool_calls` is what gets persisted as the calls that actually
    executed, and a call stopped before dispatch must not pad that list — the
    wire record answers it, the turn's record does not claim it ran."""
    return [
        {"type": "tool_result", "tool_use_id": call.id, "content": _UNRUN_RESULT}
        for call in skipped
    ]


@dataclass
class LoopResult:
    reply: str
    tool_calls: list[LoopEvent] = field(default_factory=list)
    iterations: int = 0
    cancelled: bool = False


def _dispatch_tools(
    tool_uses: list[Any],
    tools: ToolRegistry,
    notify: Observer,
    should_cancel: CancelCheck,
    approve: Approver,
) -> tuple[list[LoopEvent], list[dict], bool]:
    """Run each requested tool in order. Checked immediately before every
    dispatch, cancellation first: once should_cancel fires, that call and
    every later one in `tool_uses` are skipped. Next, for a tool whose
    static declaration requires approval, `approve` is consulted; a decline
    skips execute() entirely and the model gets a decline result instead of
    a tool result — it is not counted specially, just another tool_result,
    so the existing iteration guardrail is unchanged. Returns the events to
    record, the tool_results to feed back to the model, and whether
    cancellation cut the list short."""
    events, tool_results = [], []
    for index, call in enumerate(tool_uses):
        if should_cancel():
            # Answer this call and every later one as not-run before leaving.
            # `messages` is what run_loop's own docstring calls the full
            # working memory of the turn, and it is what gets traced (ADR
            # 0002: a cancelled turn is recorded, not discarded) — so it has
            # to stay a well-formed exchange. Returning here without these
            # left the assistant's tool_use blocks unanswered, and cancelling
            # before the first dispatch appended an empty user turn: a record
            # no provider would accept, describing a turn that really did
            # happen. Nothing resends it today; that is not a reason to trace
            # a lie.
            tool_results.extend(_unrun_results(tool_uses[index:]))
            return events, tool_results, True
        decision = (
            approve(call.name, call.input)
            if tools.requires_approval(call.name)
            else ApprovalDecision(approved=True)
        )
        if decision.approved:
            output = tools.execute(call.name, call.input, notify=notify)
        else:
            output = _declined_result(call.name, decision.reason)
        # `approved` rides on the event itself (not just the model-facing
        # `output` text) so a listener can tell a decline apart from a
        # genuine result without parsing `_declined_result`'s prose. True
        # for every call that never needed approval in the first place, so
        # this is one consistent field, not "present only sometimes."
        # `reason` rides alongside it the same way: `None` for every call
        # that wasn't declined with one, so a reader sees one consistent
        # field rather than treating "key absent" as a third, undocumented
        # case — the same channel the decision itself already travels
        # through, not a second one.
        event = {"tool": call.name, "args": call.input, "output": output,
                 "approved": decision.approved, "reason": decision.reason}
        events.append(event)
        notify("tool", event)
        tool_results.append(
            {"type": "tool_result", "tool_use_id": call.id, "content": output}
        )
    return events, tool_results, False


def run_loop(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    messages: list[dict],
    tools: ToolRegistry,
    max_iterations: int = 10,
    max_tokens: int = 2048,
    observer: Observer | None = None,
    stream: bool = False,
    should_cancel: CancelCheck | None = None,
    approve: Approver | None = None,
) -> LoopResult:
    """Run one agent turn. `messages` is mutated in place — after the call it
    contains the full working memory of the turn (assistant thoughts, tool
    calls, tool results), which is exactly what gets traced.

    stream=True emits the assistant's text as it's generated (notify("text",
    {"delta": ...})) so a gateway can show it appear token by token — used by
    the dashboard. Falls back to a single call for clients without streaming.

    should_cancel, if given, is asked at exactly two points: the top of each
    iteration, and immediately before each tool dispatch — never inside the
    streaming delta loop. When it answers True the turn stops and returns
    normally (LoopResult.cancelled=True); it never raises. No caller in this
    repo supplies should_cancel today — every one passes None, so the loop
    behaves exactly as it did before the hook existed.

    approve, if given, is consulted at that same before-each-dispatch point,
    right after should_cancel — cancellation always wins first — but only
    for a tool whose static `needs_approval` is True (registry.requires_
    approval); tools that don't require approval never reach it. A decline
    skips execute() outright and the model receives a result that says so,
    visibly distinct from a tool error, telling it not to retry and to ask
    the person what they'd prefer instead. No surface supplies approve today;
    every caller passes None, so a tool that requires approval just runs —
    unaffected, including the unattended scheduled briefing and both
    arenas."""
    notify = observer or (lambda kind, ev: None)
    cancel_check = should_cancel or (lambda: False)
    approve_check = approve or (lambda name, args: ApprovalDecision(approved=True))
    result = LoopResult(reply="")
    can_stream = stream and hasattr(client.messages, "stream")

    for iteration in range(1, max_iterations + 1):
        if cancel_check():
            result.cancelled = True
            return result
        result.iterations = iteration

        # ---- reason: one LLM call with the current working memory
        response = None
        if can_stream:
            try:
                with client.messages.stream(
                    model=model, system=system, messages=messages,
                    tools=tools.schemas(), max_tokens=max_tokens,
                ) as s:
                    for delta in s.text_stream:
                        notify("text", {"delta": delta})
                    response = s.get_final_message()
            except Exception:
                response = None  # any streaming hiccup → fall back to one call
        if response is None:
            response = client.messages.create(
                model=model,
                system=system,
                messages=messages,
                tools=tools.schemas(),
                max_tokens=max_tokens,
            )
        notify("llm", {"iteration": iteration, "stop_reason": response.stop_reason,
                       "usage": {"in": response.usage.input_tokens, "out": response.usage.output_tokens}})

        # the assistant's turn (text and/or tool requests) joins working memory
        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]

        # ---- guardrail 1: no tool calls → the model is talking to the human
        if not tool_uses:
            result.reply = "".join(b.text for b in response.content if b.type == "text")
            return result

        # ---- act: execute each requested tool; observe: feed results back
        events, tool_results, cancelled = _dispatch_tools(
            tool_uses, tools, notify, cancel_check, approve_check
        )
        result.tool_calls.extend(events)
        messages.append({"role": "user", "content": tool_results})
        if cancelled:
            result.cancelled = True
            return result

    # ---- guardrail 2: ran out of iterations
    result.reply = "(I hit my iteration limit before finishing — try breaking the request into smaller steps.)"
    return result
