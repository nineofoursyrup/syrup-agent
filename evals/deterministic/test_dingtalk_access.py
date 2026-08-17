"""DETERMINISTIC EVAL — who the DingTalk bot is allowed to answer.

Mirrors test_discord_access.py's shape: `should_answer` is a pure function
precisely so this policy can be pinned here without a DingTalk connection.
Unlike Discord, DingTalk itself only ever delivers a group message to the
bot when the bot was @-mentioned — that gate is enforced by the platform
before this code runs at all — so the only door this module still guards is
the user allowlist, and empty must mean "everyone in the org", matching
Telegram's and Discord's own empty-allowlist default.
"""

from __future__ import annotations

from syrup.gateway.dingtalk import _allowed_ids, _build_agent, should_answer

ME = "111"
STRANGER = "999"


def test_empty_allowlist_answers_anyone():
    assert should_answer(sender_staff_id=STRANGER, allowed=set()) is True
    assert should_answer(sender_staff_id=ME, allowed=set()) is True


def test_allowlist_admits_only_listed_senders():
    assert should_answer(sender_staff_id=ME, allowed={ME}) is True
    assert should_answer(sender_staff_id=STRANGER, allowed={ME}) is False


def test_id_lists_tolerate_the_way_people_actually_write_them(monkeypatch):
    monkeypatch.setenv("DINGTALK_ALLOWED_USER", " 111, 222 ,,333 ")
    assert _allowed_ids() == {"111", "222", "333"}
    monkeypatch.setenv("DINGTALK_ALLOWED_USER", "")
    assert _allowed_ids() == set(), "an empty value must never parse into a wildcard"


def test_the_bot_can_be_given_a_memory_of_its_own(tmp_path, monkeypatch):
    """The allowlist above decides WHO gets an answer; this decides WHOSE
    memory answers them. Shipped without it: the runner was handed the plain
    Syrup class, so every turn came out of the owner's default .syrup, and an
    empty allowlist on an org-wide channel meant any colleague who found the
    bot was talking to the owner's private assistant. Discord already had
    DISCORD_HOME for exactly this (a real 2026-07-26 incident) and Feishu
    shipped FEISHU_HOME in the same change — DingTalk was the one that
    didn't."""
    home = tmp_path / "bot-home"
    monkeypatch.setenv("DINGTALK_HOME", str(home))
    assert _build_agent().settings.home == home, "DINGTALK_HOME did not redirect the memory"
    assert home.exists(), "the bot's own home was never created on disk"

    monkeypatch.delenv("DINGTALK_HOME")
    assert _build_agent().settings.home != home, "unset DINGTALK_HOME must fall back to the default"
