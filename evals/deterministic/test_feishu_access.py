"""DETERMINISTIC EVAL — who the Feishu bot is allowed to answer, and what it
extracts from a message.

`should_answer` mirrors test_discord_access.py's shape: a pure function so
the policy is pinned without a Feishu connection. Unlike DingTalk, Feishu
has no platform-level mention gate for group chats, so this module enforces
one itself — an unmentioned group message must stay silent, the same
default-deny posture Discord's own regression test exists to protect.
"""

from __future__ import annotations

from syrup.gateway.feishu import _allowed_ids, _clean_text, should_answer

ME = "ou_me"
STRANGER = "ou_stranger"


def test_private_chat_answered_unless_excluded():
    assert should_answer(is_group=False, mentioned=False, sender_open_id=STRANGER, allowed=set()) is True
    assert should_answer(is_group=False, mentioned=False, sender_open_id=ME, allowed={ME}) is True
    assert should_answer(is_group=False, mentioned=False, sender_open_id=STRANGER, allowed={ME}) is False


def test_group_chat_requires_a_mention():
    """The door this module exists to guard: an unmentioned group message —
    allowlisted sender or not — must not produce a turn."""
    assert should_answer(is_group=True, mentioned=False, sender_open_id=ME, allowed=set()) is False
    assert should_answer(is_group=True, mentioned=True, sender_open_id=ME, allowed=set()) is True


def test_group_chat_still_checks_the_allowlist():
    assert should_answer(is_group=True, mentioned=True, sender_open_id=STRANGER, allowed={ME}) is False
    assert should_answer(is_group=True, mentioned=True, sender_open_id=ME, allowed={ME}) is True


def test_id_lists_tolerate_the_way_people_actually_write_them(monkeypatch):
    monkeypatch.setenv("FEISHU_ALLOWED_USER", " ou_1, ou_2 ,,ou_3 ")
    assert _allowed_ids() == {"ou_1", "ou_2", "ou_3"}
    monkeypatch.setenv("FEISHU_ALLOWED_USER", "")
    assert _allowed_ids() == set(), "an empty value must never parse into a wildcard"


def test_clean_text_strips_the_at_mention_placeholder():
    assert _clean_text('{"text":"@_user_1 what is on my calendar?"}') == "what is on my calendar?"
    assert _clean_text('{"text":"no mention here"}') == "no mention here"


def test_clean_text_tolerates_malformed_content():
    assert _clean_text("not json") == ""
    assert _clean_text('{"text":""}') == ""
