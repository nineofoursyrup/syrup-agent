"""The triage graph workflow — every message's front door when the flag is on.

The retrieval gate asked one narrow question with a small model ("does this
message need memory?"). Triage generalizes that idea from one gate to a
structure: two things happen AT THE SAME TIME (a small model classifies the
message; today's calendar loads from disk), then a code router picks the path:

    START ── classify ──────┐
         └── check_calendar ┴─► route:  quick → quick_reply (small model) → END
                                        full  → full_agent (THE loop)     → END

"thanks!" never wakes the big model. "schedule a swim Saturday" runs the exact
same loop as always — as one node. The user never chooses a mode; this graph
IS the choice. And every seam fails open: a broken classifier, a broken
engine, anything → the plain loop answers, same as if the flag were off.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from syrup.graph.engine import END, START, Graph, Node
from syrup.graph.nodes import key_router

TRIAGE_PROMPT = """\
You are a triage gate for a personal assistant. Given the user's message,
decide which brain should answer it.

Reply with ONLY this JSON, nothing else:
{{"route": "quick" or "full", "reason": "<5 words>"}}

quick — greetings, thanks, acknowledgements, pure small talk: nothing to do,
        nothing to look up.
full  — anything mentioning tasks, schedules, people, notes, memory, or that
        needs a tool. When unsure, choose full.

A short message that ANSWERS the assistant's last question — "yes", "是", "the
second one", "4pm instead" — continues whatever that question was about. Route
it the way you would route the question. Only a message that stands alone with
nothing pending is small talk.

Conversation so far:
{recent}

User message: {message}"""

QUICK_REPLY_PROMPT = """\
You are Syrup, a warm, concise personal assistant. The user's message needs no
tools or memory — reply in one or two short, natural sentences. If today's
calendar (below) is clearly relevant, you may mention it; otherwise ignore it.

Today's calendar: {calendar}

User message: {message}"""


def format_recent(history: list[dict] | None, exchanges: int = 1) -> str:
    """The last `exchanges` turns, flattened for the triage prompt.

    One exchange by default, which is the minimum that answers the question
    triage actually gets wrong: does this message continue the previous one?
    Triage runs on every single message, so the context it carries is paid for
    every time — enough to recognise a follow-up, not the whole thread."""
    if not history:
        return "(nothing yet — this is the first message)"
    rows = history[-exchanges * 2:]
    return "\n".join(f"{row['role']}: {row['content']}" for row in rows)


def classify_message(client, small_model: str, message: str,
                     history: list[dict] | None = None) -> tuple[str, str]:
    """Returns (route, reason). Fails open to "full": a broken triage must
    cost latency, never capability — mirror of retrieval_gate.should_retrieve.

    `history` is what makes a bare "是" routable. Classified alone it reads as
    an acknowledgement and goes quick, where no tool can run — so a confirmed
    booking silently never happens (live bug, 2026-08-12). Shown the question
    it answers, the same message is plainly a continuation."""
    try:
        response = client.messages.create(
            model=small_model,
            max_tokens=600,  # reasoning models think before the JSON
            messages=[{"role": "user", "content": TRIAGE_PROMPT.format(
                message=message, recent=format_recent(history))}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        if "{" not in text:
            return "full", "no JSON — failing open"
        decision = json.loads(text[text.index("{") : text.rindex("}") + 1])
        route = decision.get("route")
        if route not in ("quick", "full"):
            return "full", f"bad route '{route}' — failing open"
        return route, decision.get("reason", "")
    except Exception as exc:
        return "full", f"triage failed open ({type(exc).__name__})"


def todays_events(home: Path) -> str:
    """Today's events straight from calendar.ics — a local file read, which is
    exactly why it can run in parallel with the classifier's network call."""
    ics = home / "calendar.ics"
    if not ics.exists():
        return "(no calendar)"
    today = datetime.now().strftime("%Y%m%d")
    lines, title = [], ""
    for line in ics.read_text(encoding="utf-8").splitlines():
        if line.startswith("SUMMARY:"):
            title = line[len("SUMMARY:"):]
        elif line.startswith("DTSTART") and today in line and title:
            lines.append(title)
    return "; ".join(lines) or "(nothing today)"


def build_triage_graph(*, classify_fn: Callable[[str], tuple[str, str]],
                       calendar_fn: Callable[[], str],
                       quick_fn: Callable[[dict], str],
                       full_fn: Callable[[dict], object]) -> Graph:
    """Callables injected so evals script them, the dashboard builds it with
    stubs just to describe(), and app.py binds the real client/loop."""
    g = Graph("triage")

    def classify(state: dict) -> dict:
        route, reason = classify_fn(state["message"])
        notify = state.get("_notify")
        if notify:  # the human-readable "why" — traced, and shown on the turn card
            notify("triage", {"route": route, "reason": reason})
        return {"route": route, "triage_reason": reason}

    g.add_node(Node("classify", classify, kind="llm"))
    g.add_node(Node("check_calendar", lambda s: {"calendar": calendar_fn()}, kind="tool"))
    g.add_node(Node("quick_reply", lambda s: {"reply": quick_fn(s)}, kind="llm"))
    g.add_node(Node("full_agent", lambda s: {"result": full_fn(s)}, kind="agent"))
    g.add_edge(START, "classify")
    g.add_edge(START, "check_calendar")
    # the router waits on BOTH parallel branches before deciding
    g.add_node(Node("gather", lambda s: {}, kind="fn"))
    g.add_edge("classify", "gather")
    g.add_edge("check_calendar", "gather")
    g.add_router("gather", key_router("route", default="full"),
                 {"quick": "quick_reply", "full": "full_agent"})
    g.add_edge("quick_reply", END)
    g.add_edge("full_agent", END)
    return g


def triage_topology() -> dict:
    """The topology as data, for the dashboard — built with stubs, never run."""
    noop = lambda *a, **k: ""  # noqa: E731
    return build_triage_graph(classify_fn=lambda m: ("full", ""), calendar_fn=noop,
                              quick_fn=noop, full_fn=noop).describe()
