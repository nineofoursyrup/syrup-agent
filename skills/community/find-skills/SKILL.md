---
name: find-skills
description: Find or add a skill Syrup doesn't have yet. Use for "is there a skill for", "can you learn to", "teach yourself", "add a skill", "install a skill", "what skills do you have". 用于"技能"、"学会"、"自学"、"添加"、"安装"、"哪些技能"：查找或添加 Syrup 还没有的技能。
---

A skill is a markdown file that teaches Syrup how to do one thing well. When
someone asks for a behaviour that is missing, there are three honest answers,
in this order: it already exists, someone has written it, or we write it now.

## How to answer

1. **Check what is already live.** The skills loaded into this prompt are the
   installed ones. If one already covers the request, say which and use it —
   the answer is often that nothing needs adding.
2. **If it is specific to this person, write it.** A rule about how *they*
   want something done — their formats, their people, their defaults — is
   nobody else's skill. Call `create_skill`, and it is live on the next turn.
   Draft the frontmatter from their own words so the loader matches the
   phrases they actually use.
3. **If it is general, look for one that exists.** Call `search_web` for a
   published `SKILL.md` covering it.

   **Read it before you recommend it.** A skill is instructions the model will
   follow and tools it will be told to call — installing one is closer to
   running someone's code than to reading their article. Say in one line what
   it will make Syrup do, and name any tool it needs that Syrup does not have.
   Recommending an unread skill is the same mistake as running unread code.

   Then give the link and the exact command:

   ```bash
   python -m syrup skill install <link-to-a-SKILL.md>
   ```

   The user runs that themselves — installing reaches the network and writes
   to their machine, so it is theirs to run, not yours. Say that rather than
   implying you installed anything.
4. **Confirm what changed.** Name the skill and say whether it is live now
   (`create_skill`) or waiting on that command (`skill install`).

## What makes a skill worth adding

- It is a **repeated** job, not a one-off — a one-off is just a request.
- It has **steps or defaults** worth fixing in place, so the answer stops
  varying run to run.
- Its description carries the words the person actually says, because that is
  what the loader matches against.

## Edge cases

| Situation | Do |
|---|---|
| A live skill already covers it | Say which one and run it; adding a second would split the behaviour in two |
| The request is a one-off | Just do the thing, and offer to make it a skill if they expect to repeat it |
| Search finds nothing credible | Say so, then offer `create_skill` from what they described |
| A found skill needs tools Syrup lacks | Say which tools are missing before they install it |
| "What can you do?" | List the live skills in one line each, then offer to add what is missing |
