# Syrup

A local-first personal assistant, built so the four pillars behind every serious agent —
Harness, Loop, Memory, and Eval/LLM-Ops — stay legible on their own. This file is the
glossary: what the words mean here, and which words to stop using.

## Language

### The conversation

**Conversation**:
A named, resumable stretch of dialogue between a person and Syrup. Setting one aside and
starting another is a thing a person does deliberately.
_Avoid_: thread (already means an OS thread here, and both senses appear in the same
files), chat, session (names the working-memory object instead).

**Turn**:
One exchange, from the person's message to the assistant's reply, including any tools that
ran in between.

**Working memory**:
Everything assembled into the prompt for a single turn — the soul, retrieved memory, and
the recent tail of the conversation. Bounded by design; it is not the record.

**Home**:
The one directory holding everything a running Syrup owns — state, calendar, outbox,
traces. Never in version control.

### How a turn happens

**Loop**:
The reason–act–observe cycle that answers a turn. There is exactly one, and structure is
added around it rather than inside it.

**Graph**:
Opt-in structure placed around the loop — nodes and routes — which can change speed and
routing but never capability. A node can itself be a loop turn.

**Triage**:
The decision of which brain answers a turn: a small model for small talk, the full loop for
anything real.

**Retrieval gate**:
The decision of whether a turn needs long-term memory at all, made before the turn runs.

**Observer**:
The single channel by which a turn reports what it is doing while it does it. What a
surface shows and what a trace records are the same events, not two accounts.

**Trace**:
The durable record of what a turn actually did. It is expected to be honest even about
turns that were stopped or refused.

### Stopping and refusing

**Cancellation**:
A person's request that the current turn stop. Cooperative: the turn stops at its next
checkpoint, not instantly, and a turn stopped this way is still recorded.

**Approval**:
The question asked immediately before a tool runs: should this call happen? Only tools that
declare they need it are ever asked about.

**Decline**:
A person's answer that a particular call must not run. Not an error, and not a request to
retry — it is a redirection.

### What Syrup knows and can do

**Tool**:
A capability the model can invoke by name, with a schema it can read. Every registered tool
costs prompt room in every turn, so the set stays small on purpose.

**Skill**:
A capability written as a markdown file rather than code — procedural memory that can be
added without touching the core.

**Pin**:
One thing fixed to one moment — a meeting, a deadline, a task. Pinning it puts it on the
calendar and drafts a reminder; both, or it is not pinned.
_Avoid_: appointment, booking (each names only the calendar half).

**Consolidation**:
Turning recent conversation into durable memory, so old turns stop needing to be in the
prompt to still be known.

**Gateway**:
A surface that carries text in and out — terminal, voice, a messaging app. A gateway moves
text and takes part in no other protocol.

### How it is checked

**Deterministic eval**:
A pass/fail test of behaviour, run offline against scripted models. The default; most
things belong here.

**Judge eval**:
A scored assessment of qualities no assertion can capture, made by a model. Never mixed
with deterministic evals.

**Gate**:
The check that both eval suites pass, run before anything is released.
