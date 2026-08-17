"""LLM-AS-JUDGE EVAL — "was the response good?" This is NOT a unit test.

A judge model scores qualities no assertion can check: helpfulness, whether
Syrup actually used what it remembered, tone. Scores are 0–1 percentages
with a threshold, not 0/1 truths — never confuse the two (that confusion is
exactly what the deterministic suite next door exists to prevent).

Requires the active provider's API key: the judge is a real model call.
"""

from __future__ import annotations

import pytest

from evals.helpers import HAS_KEY, make_syrup

pytestmark = pytest.mark.skipif(not HAS_KEY, reason="LLM-as-judge needs the active provider's API key")


@pytest.fixture(scope="module")
def geval_metrics():
    import os

    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    from evals.judge.anthropic_judge import AnthropicJudge

    # Judging needs a model that is STABLE at scoring, which is not the same
    # axis as being a strong model, and had to be measured rather than assumed.
    # One fixed, manually verified-correct reply, scored four times each:
    #   gpt-5.6-luna (the app's own model)  0.6 0.9 1.0 0.5  <- half at/under 0.6
    #   deepseek-v4-pro (nominally bigger)  1.0 0.5 1.0 0.4  <- worse spread
    #   kimi-k3                             1.0 0.9 1.0 1.0
    # The default here is a catalog id, so override it if the active provider
    # does not serve that model.
    judge = AnthropicJudge(model=os.getenv("SYRUP_EVAL_JUDGE_MODEL", "kimi-k3"))
    helpful = GEval(
        name="Helpfulness",
        criteria=(
            "The assistant reply should directly address the user's request, confirm any "
            "action taken (what/when/who), and be concise and warm."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=0.6,
    )
    # The criteria has to tell the judge what the assistant's JOB is, because
    # the judge only sees input/output/retrieval-context — never the tool call
    # that actually ran. Without the second sentence it read "Friday" resolved
    # to a real date and the morning preference applied as 9:00 AM as INVENTED
    # detail and marked the reply down for hallucinating, scoring the exact
    # same correct answer 0.8 / 0.5 / 0.6 against a 0.6 threshold on three
    # consecutive runs. A gate that fails half the time on right answers stops
    # being a gate: you learn to push through it, and then it protects nothing.
    uses_memory = GEval(
        name="MemoryUse",
        criteria=(
            "Given the retrieval context (the user's stored memories), the reply should "
            "correctly incorporate relevant remembered facts instead of ignoring them. "
            "The assistant books real calendar events via tools, so resolving a vague day "
            "like 'Friday' into a concrete date, and choosing a specific time that honours "
            "a remembered preference, is the expected behaviour being tested — judge "
            "whether the remembered fact was used, and never treat that resolved date or "
            "time as invented or unsupported."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.RETRIEVAL_CONTEXT,
        ],
        model=judge,
        threshold=0.6,
    )
    return helpful, uses_memory


def test_scheduling_reply_is_helpful(tmp_path, geval_metrics):
    from deepeval import assert_test
    from deepeval.test_case import LLMTestCase

    helpful, _ = geval_metrics
    app = make_syrup(tmp_path / "home")
    user_message = "Schedule a coffee with Alex next Tuesday at 9am"
    result = app.respond(user_message)

    assert_test(LLMTestCase(input=user_message, actual_output=result.reply), [helpful])


def test_reply_uses_remembered_preference(tmp_path, geval_metrics):
    from deepeval import assert_test
    from deepeval.test_case import LLMTestCase

    _, uses_memory = geval_metrics
    app = make_syrup(tmp_path / "home")
    app.memory.facts.add("alex", "Alex prefers morning meetings")
    user_message = "Book a catch-up with Alex on Friday"
    result = app.respond(user_message)

    assert_test(
        LLMTestCase(
            input=user_message,
            actual_output=result.reply,
            retrieval_context=["Alex prefers morning meetings"],
        ),
        [uses_memory],
    )
