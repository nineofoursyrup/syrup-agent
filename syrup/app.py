"""Wiring — builds one Syrup from its parts. Gateways call `respond()`.

This file is the assembly diagram in code: config → db → tools → memory →
session → loop. If you want to understand the repo in one place, start here.
"""

from __future__ import annotations

from syrup.config import Settings, load_settings
from syrup.db import connect
from syrup.loop.agent import Approver, CancelCheck, LoopResult, Observer, run_loop
from syrup.loop.models import get_client
from syrup.ops.tracing import Tracer, compose
from syrup.runtime.session import Session
from syrup.tools import build_registry


class Syrup:
    def __init__(self, settings: Settings | None = None, client=None, conn=None):
        # `client` and `conn` are injectable: evals swap in a scripted model,
        # the dashboard injects a cross-thread connection. Same seam either way.
        self.settings = settings or load_settings()
        self.settings.ensure_home()
        self.conn = conn or connect(self.settings.home)
        self.client = client or get_client(self.settings)

        # Memory first: the memory-management tools need it.
        from syrup.memory import Memory

        self.memory = Memory(self.conn, self.settings, self.client)
        self.tools = build_registry(self.conn, self.settings, self.memory)
        self.mcp_bridge = getattr(self.tools, "mcp_bridge", None)
        self.session = Session(self.settings, memory=self.memory)
        self.tracer = Tracer(self.settings)

    def memory_snapshot(self) -> str:
        """Render a bounded, read-only view of Syrup's local memory. Public
        so both terminal surfaces (the line-oriented gateway's /memory
        command, and the TUI's memory modal) call this ONE implementation
        instead of each querying SQLite themselves — sharing a data source
        still lets two renderers drift, sharing the implementation does not."""
        conn = self.conn
        fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        facts = conn.execute(
            "SELECT subject, content FROM facts ORDER BY id DESC LIMIT 8"
        ).fetchall()
        episode_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        episodes = conn.execute(
            "SELECT happened_at, summary FROM episodes ORDER BY happened_at DESC, id DESC LIMIT 5"
        ).fetchall()
        pending = self.pending_consolidation_count()

        lines = [f"Semantic facts ({fact_count})"]
        lines.extend(f"- [{row['subject']}] {row['content']}" for row in facts)
        if not facts:
            lines.append("- none yet")

        lines.extend(["", f"Recent episodes ({episode_count})"])
        lines.extend(f"- {row['happened_at']} - {row['summary']}" for row in episodes)
        if not episodes:
            lines.append("- none yet")

        lines.extend(["", f"Unconsolidated chat messages: {pending}"])
        return "\n".join(lines)

    def list_threads(self, limit: int | None = None) -> list[dict]:
        """Recent conversation threads, most-recent-first, bounded to `limit`.
        Delegates to `Memory.list_sessions`, the ONE
        implementation of "what counts as a thread and how it's summarized"
        (id, title, message count, timestamps) AND the one place its default
        bound (`DEFAULT_SESSION_LIST_LIMIT`) lives — not a second query, or a
        second hardcoded `20`, that could drift from either that default or
        the dashboard's own chat-history picker, which reads the same
        chat_log table through its own `ops/dashboard.py::session_list`
        instead, unbounded, since a web page scrolls and a terminal list
        needs a fixed height."""
        if self.memory is None:
            return []
        if limit is None:
            return self.memory.list_sessions()
        return self.memory.list_sessions(limit=limit)

    def pending_consolidation_count(self) -> int:
        """How many chat_log rows are still waiting for the next
        consolidation pass. Its own read-only query — not a value pulled out
        of `memory_snapshot()`'s rendered text — because a status display
        needs a plain int, and parsing a number back out of prose is a bug
        waiting to happen. `memory_snapshot`
        above calls this same method rather than repeating the SQL, so the
        two callers can never disagree on what "pending" means."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM chat_log WHERE consolidated = 0"
        ).fetchone()[0]

    def close(self) -> None:
        """Release external resources (MCP subprocesses). Called when the
        dashboard rebuilds the agent after a settings change."""
        if self.mcp_bridge is not None:
            self.mcp_bridge.close()

    def respond(self, user_message: str, observer: Observer | None = None,
                source: str = "cli", stream: bool = False,
                should_cancel: CancelCheck | None = None,
                approve: Approver | None = None) -> LoopResult:
        """One full turn: assemble working memory → run the loop → persist.
        `source` tags which gateway the message arrived through (cli / voice /
        telegram / dashboard), so the unified chat can show its origin.
        `stream=True` streams the reply text token by token to the observer.
        Everything that happens is both shown (observer) and recorded (tracer).

        `should_cancel`, if given, reaches run_loop unchanged. A cancelled
        turn is still persisted and traced, never discarded — it already ran
        whatever tools it ran (see docs/adr/0002). No gateway supplies one
        today, and none needs to for this to work: the parameter defaults to
        None here.

        `approve`, if given, reaches run_loop unchanged too. No gateway
        supplies one today either — every caller (the six text gateways, the
        CLI, the dashboard, both arenas, the scheduled briefing) asks for
        none, and a tool marked `needs_approval` just runs straight through.
        Blocking a text gateway on a yes/no answer would mean suspending the
        turn mid-conversation waiting for the next inbound message — a
        different protocol than "a gateway moves text," which is why this
        stays a seam an interactive surface can wire up rather than a second
        thing every gateway must implement.

        Both reach the graph front door identically (#26, see
        `_respond_via_graph` below) — `graph_workflows` must never be the
        thing that decides whether either gate is in play."""
        # capture the gate + graph decisions as they flow by, so we can persist
        # them with the turn (the reopened-thread telemetry the dashboard shows)
        import time
        captured: dict = {}

        def _capture(kind, ev):
            if kind == "gate":
                captured["gate"] = {"decision": ev.get("decision"), "reason": ev.get("reason")}
            if kind == "route":
                captured["graph_route"] = {"target": ev.get("target"), "reason": ev.get("reason")}
            if kind == "triage":
                captured["triage_reason"] = ev.get("reason")
            if kind == "graph_end":
                captured["graph_path"] = ev.get("path")
        notify = compose(observer, self.tracer.event, _capture)
        t0 = time.perf_counter()

        with self.tracer.turn(user_message):
            # The graph front door is optional and can NEVER make Syrup worse:
            # flag off → this is exactly the old code path; flag on → the triage
            # graph decides quick vs full, and any failure anywhere falls open
            # to the plain loop below (same fail-open rule as the retrieval gate).
            result = None
            if self.settings.graph_workflows:
                try:
                    result = self._respond_via_graph(user_message, notify, stream,
                                                      should_cancel, approve)
                except Exception as exc:
                    notify("graph_end", {"workflow": "triage", "ms": 0, "steps": 0,
                                         "path": [], "error": repr(exc)})
                    result = None
            if result is None:
                result = self._run_full_turn(user_message, notify, stream, should_cancel, approve)

            quick = captured.get("graph_route", {}).get("target") == "quick_reply"

            def _status(out: str) -> str:
                low = (out or "").lower()
                return "error" if ("failed" in low or "timed out" in low
                                   or low.startswith("error")) else "ok"
            meta = {
                "gate": captured.get("gate"),
                "graph": ({"workflow": "triage",
                           "route": "quick" if quick else "full",
                           "reason": captured.get("triage_reason", ""),
                           "path": captured.get("graph_path")}
                          if "graph_route" in captured else None),
                "iterations": result.iterations,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "tools": [{"tool": c["tool"], "status": _status(c["output"])}
                          for c in result.tool_calls],
                # which brain answered this turn — so a reopened thread (or a
                # thread you switched models mid-way) shows it per card. A quick
                # graph turn was answered by the small model; say so honestly.
                "model": self.settings.small_model if quick else self.settings.model,
                "provider": self.settings.provider,
                # the existing metadata channel, not a parallel one (#22): a
                # cancelled turn already ran whatever tools are listed above —
                # this just says honestly that the turn didn't run to completion.
                "cancelled": result.cancelled,
            }
            self.session.add_exchange(user_message, result.reply, tool_calls=result.tool_calls,
                                      source=source, meta=meta, cancelled=result.cancelled)
            if self.memory is not None:
                self.memory.maybe_consolidate(notify=notify)
                self.memory.export_markdown()   # keep MEMORY.md in sync

        self.tracer.end_turn(result.reply, result.iterations, cancelled=result.cancelled)
        return result

    def _run_full_turn(self, user_message: str, notify, stream: bool,
                       should_cancel: CancelCheck | None = None,
                       approve: Approver | None = None) -> LoopResult:
        """The classic turn: assemble working memory, run THE loop. Extracted
        verbatim so the graph's full_agent node calls the SAME code as the
        flag-off default — loop-as-a-node can never drift from loop-as-default."""
        system = self.session.build_system(user_message, notify=notify)
        # Working memory is a bounded window: only the last N turns (2 rows
        # each) enter the prompt, so context/cost/latency stay flat no matter
        # how long the conversation runs. Older turns live in state.db and
        # come back via the retrieval gate + episodic memory when relevant.
        window = self.settings.history_turns * 2
        messages = self.session.history[-window:] + [{"role": "user", "content": user_message}]

        return run_loop(
            client=self.client,
            model=self.settings.model,
            system=system,
            messages=messages,
            tools=self.tools,
            max_iterations=self.settings.max_iterations,
            max_tokens=self.settings.max_tokens,
            observer=notify,
            stream=stream,
            should_cancel=should_cancel,
            approve=approve,
        )

    def _respond_via_graph(self, user_message: str, notify, stream: bool,
                           should_cancel: CancelCheck | None = None,
                           approve: Approver | None = None) -> LoopResult | None:
        """One turn through the triage graph workflow. Returns None whenever
        the graph didn't produce an answer — respond() then falls open to the
        plain loop, so this path can only ever ADD speed, never lose a reply.

        `approve` is a pure pass-through to the full_agent node's loop turn
        (#26). The quick route never runs a tool, so approval genuinely does
        not apply to it — nothing to ask about, ever.

        `should_cancel` also reaches the full_agent node's loop turn
        unchanged (#26). The quick route has no loop to thread it into, but
        it is NOT a single model call: it spans two — classify_message, then
        quick_reply — and a person can press Esc during either. #27 consults
        `should_cancel` once, after both calls return and the reply is
        assembled: there's no tool dispatch on this path to protect
        mid-flight, so "the in-flight calls complete" is already the honest
        worst case, same as the plain path. A cancelled quick turn is still
        returned with whatever reply text the model produced — only marked
        cancelled, never discarded (#22)."""
        from syrup.graph import run_graph
        from syrup.graph.workflows.triage import (
            QUICK_REPLY_PROMPT,
            build_triage_graph,
            classify_message,
            todays_events,
        )

        def quick_reply(state: dict) -> str:
            prompt = QUICK_REPLY_PROMPT.format(calendar=state.get("calendar", ""),
                                               message=state["message"])
            # The same bounded window the full path uses. A quick turn is
            # cheap because it skips memory retrieval and tools, not because
            # it forgets the conversation — answering "谢谢" or "第二个" still
            # needs to know what came before (live bug, 2026-08-12).
            window = self.settings.history_turns * 2
            response = self.client.messages.create(
                model=self.settings.small_model, max_tokens=600,
                messages=self.session.history[-window:] + [
                    {"role": "user", "content": prompt}])
            return "".join(b.text for b in response.content if b.type == "text")

        graph = build_triage_graph(
            classify_fn=lambda m: classify_message(
                self.client, self.settings.small_model, m, self.session.history),
            calendar_fn=lambda: todays_events(self.settings.home),
            quick_fn=quick_reply,
            # the full path is the SAME method the flag-off default runs; the
            # engine's tagged notifier stamps its inner events with node=
            full_fn=lambda state: self._run_full_turn(
                state["message"], state.get("_notify", notify), stream,
                should_cancel, approve),
        )
        state = run_graph(graph, {"message": user_message}, observer=notify)
        if isinstance(state.get("result"), LoopResult):
            return state["result"]
        if state.get("reply"):
            # Consulted once, here — not mid-route (#27). Nothing runs between
            # classify and quick_reply that a check could protect, so this is
            # the one point where the turn's outcome is known and can still
            # honestly be marked either way.
            cancelled = bool(should_cancel and should_cancel())
            return LoopResult(reply=state["reply"], tool_calls=[], iterations=1,
                              cancelled=cancelled)
        return None  # graph produced nothing → caller falls open to the loop
