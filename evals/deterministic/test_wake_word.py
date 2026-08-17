"""The wake-word matcher is a pure function — so it gets deterministic evals.
Whisper mangles phrases in predictable ways; these cases pin the fuzziness."""

import pytest

from syrup.gateway.voice import matches_wake

SHOULD_WAKE = [
    ("syrup syrup", "syrup syrup"),
    ("Syrup, syrup!", "syrup syrup"),            # punctuation
    ("syrupsyrup", "syrup syrup"),               # whisper drops the space
    ("so anyway syrup syrup schedule it", "syrup syrup"),  # embedded in speech
    ("sylrup syrup", "syrup syrup"),             # one-letter mangle → fuzzy match
    ("Hey Syrup", "hey syrup"),
    ("hey computer, what's up", "hey computer"),
    # regression from the first live session: whisper wrote the wake word in
    # kana — variants after a comma cover other scripts
    ("わくわく", "syrup syrup,わくわく"),
    ("わくわくわく", "syrup syrup,わくわく"),
    ("小助手你好", "syrup syrup,小助手"),
]

SHOULD_NOT_WAKE = [
    ("what a nice day", "syrup syrup"),
    ("wake up call at nine", "syrup syrup"),
    ("", "syrup syrup"),
    ("syrup syrup", ""),                        # no wake word configured
    ("walk to work", "syrup syrup"),
]


@pytest.mark.parametrize("heard,wake", SHOULD_WAKE, ids=[h for h, _ in SHOULD_WAKE])
def test_wakes(heard, wake):
    assert matches_wake(heard, wake)


@pytest.mark.parametrize("heard,wake", SHOULD_NOT_WAKE, ids=[h or "empty" for h, _ in SHOULD_NOT_WAKE])
def test_stays_asleep(heard, wake):
    assert not matches_wake(heard, wake)
