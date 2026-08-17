"""DETERMINISTIC EVAL — a bundled skill still fires on the words people say,
in the languages people actually say them in.

A skill's description is its trigger: the loader scores token overlap between
the user's message and the skill's name + description, and loads the body only
at an overlap at or above `MIN_OVERLAP`. So the description is not blurb — it
is the matching rule, and rewriting it for readability can silently stop the
skill from ever loading.

That is not hypothetical, twice over:

- Renaming schedule-meeting to schedule-pin came with a rewritten description
  that dropped the word "with". For "Book a catch-up with Alex on Friday" the
  old description matched on `book` + `with`; the new one matched on `book`
  alone, one short of the threshold, so the skill stopped loading entirely.
- Every Chinese message reached zero skills (#35), for a blunter reason: the
  loader tokenized with `[a-z0-9]{3,}`, which finds nothing at all in a
  Chinese sentence — Chinese has no whitespace between words, so there was no
  regex over characters that could produce one. Overlap was always zero, so no
  skill ever loaded, on any surface, in the language DingTalk and Feishu users
  overwhelmingly write in. The fix (`_tokenize` in the loader) adds character
  bigrams for CJK runs alongside the unchanged Latin word tokens — no word
  list, no segmentation dependency, just overlapping character pairs, so
  "明天下午" contributes "明天", "天下", "下午" and a description containing
  "明天" matches. That over-generates (天下 is not a word), which is why the
  Chinese cases below carry as many negative cases as positive ones.

In both cases nothing failed loudly. The assistant still answered — the judge
suite caught the English regression only indirectly, as a scored reply
drifting because the model was answering with no skill at all. A trigger
regression is invisible from the outside: quality moves, nothing errors.

These cases are cheap, offline, and check the thing the expensive suite could
only stumble into.
"""

from __future__ import annotations

import re

import pytest

from syrup.memory import bundled_skill_dirs
from syrup.memory.procedural.loader import _CJK_RANGE, SkillLoader

# Phrasings a person actually types, per skill. Written as they would be said —
# the point is to test the loader against real language, not against the
# description's own vocabulary echoed back at it. Chinese cases sit alongside
# the English ones, not in a second file — "will this skill fire" has exactly
# one table to check, for either language.
TRIGGERS: dict[str, list[str]] = {
    "schedule-pin": [
        "Book a catch-up with Alex on Friday",
        "Schedule a coffee with Alex next Tuesday at 9am",
        "set up a call with the Berlin team next week",
        "remind me to call the dentist tomorrow morning",
        "put a deadline for the report on Thursday",
        # 帮我预约明天下午和张伟见面喝咖啡 — book coffee with Zhang Wei tomorrow afternoon
        "帮我预约明天下午和张伟见面喝咖啡",
        # 帮我安排下周二上午九点跟柏林团队开会 — arrange a meeting with the Berlin team
        "帮我安排下周二上午九点跟柏林团队开会",
        # 提醒我明天早上给牙医打电话 — remind me to call the dentist tomorrow morning
        "提醒我明天早上给牙医打电话",
        # 报告周四截止，帮我设个提醒 — the report is due Thursday, set a reminder
        "报告周四截止，帮我设个提醒",
        # a message that mixes languages mid-sentence should match on whichever
        # tokens are there, English word or Chinese bigram
        "remind me to 开会 with the Berlin team tomorrow",
    ],
    "weekly-brief": [
        "brief me on my week",
        "what should I focus on today",
        # 简报一下我这周的安排 — brief me on my schedule this week
        "简报一下我这周的安排",
        # 我今天应该关注什么重点 — what should I focus on today
        "我今天应该关注什么重点",
    ],
    "find-skills": [
        "is there a skill for expense reports",
        "can you learn to draft my standups",
        "what skills do you have",
        # 有没有报销的技能 — is there a skill for expense reports
        "有没有报销的技能",
        # 你拥有哪些技能 — what skills do you have
        "你拥有哪些技能",
    ],
}

# Messages that must NOT pull a skill in. A read-only calendar question is
# answered by list_events; loading the pinning skill would spend prompt room
# teaching the model to create something nobody asked for. The Chinese cases
# matter more than the English ones here: bigrams over-generate, so a
# read-only question sharing no real word with a description — only an
# incidental character pair — is the likeliest way this fix goes wrong.
NON_TRIGGERS: list[tuple[str, str]] = [
    ("what's on my calendar this week", "schedule-pin"),
    ("cancel the meeting with Alex", "weekly-brief"),
    # 这周日历上有什么 — what's on my calendar this week
    ("这周日历上有什么", "schedule-pin"),
    # 取消跟张伟的会议 — cancel the meeting with Zhang Wei
    ("取消跟张伟的会议", "weekly-brief"),
    # 今天天气怎么样 — what's the weather like today (nothing here is a skill)
    ("今天天气怎么样", "schedule-pin"),
    # 帮我总结一下这份文档 — summarize this document for me
    ("帮我总结一下这份文档", "weekly-brief"),
    # 帮我翻译这段话 — translate this passage for me
    ("帮我翻译这段话", "find-skills"),
    # 他或任何人某天要请假 — "he or anyone might need a day off sometime", about
    # nothing schedule-pin covers. This one caught a real bug in review: an
    # earlier draft of the schedule-pin description fused a conjunction
    # straight onto a noun with no delimiter ("...或任务...") and another
    # phrase the same way ("...某人某事..."), each producing a seam bigram
    # (或任, 人某) that this fully unrelated sentence reproduces on its own.
    # Two coincidental seams cleared the overlap bar with zero real words in
    # common, and the skill loaded. The fix was in the description, not the
    # threshold: CJK trigger phrases are now delimiter-separated ("、" and
    # quotes) rather than run-on prose, so a seam stays inside one legitimate
    # compound instead of spanning the join between two unrelated ones. See
    # MIN_OVERLAP's comment in loader.py for the full account.
    ("他或任何人某天要请假", "schedule-pin"),
    # The 有没有 family. "有没有" ("is there / do you have") is one of the
    # commonest constructions in Chinese, and an earlier draft listed it as a
    # find-skills trigger. Three characters yield TWO bigrams (有没, 没有), so
    # that one phrase cleared the bar by itself and every sentence below
    # loaded find-skills with nothing whatsoever in common. Six of eight
    # everyday sentences misfired. The rule the delimiter guidance missed:
    # a CJK trigger must be CONTENT-bearing, because any phrase of three or
    # more characters is self-sufficient regardless of how it is punctuated.
    ("这份合同有没有风险", "find-skills"),
    ("有没有人知道密码", "find-skills"),
    ("你有没有空", "find-skills"),
    ("帮我看看这个有没有问题", "find-skills"),
    ("有没有便宜点的方案", "find-skills"),
    ("仓库里有没有货", "find-skills"),
]


@pytest.fixture(scope="module")
def loader() -> SkillLoader:
    return SkillLoader(bundled_skill_dirs())


def test_every_bundled_skill_has_trigger_cases(loader):
    """A skill added without a case here would ship with its trigger
    untested — the exact hole this file exists to close."""
    shipped = {s.name for s in loader.skills}
    assert shipped == set(TRIGGERS), (
        f"skills without trigger cases: {sorted(shipped - set(TRIGGERS))}; "
        f"cases for skills that no longer exist: {sorted(set(TRIGGERS) - shipped)}"
    )


@pytest.mark.parametrize(
    ("skill_name", "message"),
    [(name, msg) for name, msgs in TRIGGERS.items() for msg in msgs],
)
def test_the_skill_loads_for_what_people_say(loader, skill_name, message):
    matched = [s.name for s in loader.match(message)]
    assert skill_name in matched, (
        f"{skill_name!r} did not load for {message!r} (matched: {matched}). "
        "Its description carries the trigger words — check what the rewrite dropped."
    )


@pytest.mark.parametrize(("message", "skill_name"), NON_TRIGGERS)
def test_the_skill_stays_out_of_unrelated_messages(loader, message, skill_name):
    assert skill_name not in [s.name for s in loader.match(message)]


def test_a_chinese_message_about_nothing_matches_nothing(loader):
    """Same guard as below, in the language the bigram tokenizer had to be
    added for — bigrams over-generate, so this is the case most likely to
    regress into matching everything."""
    assert loader.match("今天天气不错") == []


def test_a_message_about_nothing_matches_nothing(loader):
    """Guard that matching is selective at all — if everything matched, the
    positive cases above would pass for the wrong reason."""
    assert loader.match("hey") == []


# Every bundled skill (the ones this repo ships and DingTalk/Feishu users
# actually hit) must carry Chinese trigger vocabulary in its description —
# not just happen to pass the sentences above by accident. Reading the file
# directly, rather than only exercising `match()`, is what catches a rewrite
# that quietly drops the Chinese half of a description the way the English
# "with" got dropped from schedule-pin's — the case study this file opens
# with. Community skills installed later are NOT held to this: only the
# skills this repo ships are promised bilingual triggers (see the "Out of
# Scope" section of #35 — requiring installed community skills to be
# bilingual was explicitly ruled out). An English-only installed skill stays
# reachable from a Chinese message only insofar as the message shares Latin
# words with it — the same "no magic" rule that has always governed matching,
# just not extended to a language that skill's author never wrote for.
def test_every_bundled_skill_description_carries_chinese_trigger_words(loader):
    for skill in loader.skills:
        assert re.search(f"[{_CJK_RANGE}]", skill.description), (
            f"{skill.name!r}'s description has no Chinese trigger words — "
            "a Chinese message can never match it (#35)"
        )
