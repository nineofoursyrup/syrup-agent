"""Procedural memory — SKILL.md files: how to act, loaded only when relevant.

Official Anthropic Agent Skills format: YAML frontmatter with `name` and
`description` (the description doubles as the trigger — no custom `triggers:`
field, which launch-agent-skills used before the spec settled).

Progressive disclosure, the part that matters:
  1. frontmatter of every skill is always scanned (cheap)
  2. a skill's BODY is loaded into the prompt only when it matches the message
  3. files a skill references are only read if the model asks
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# CJK Unified Ideographs (plus the common Extension A block) — the range that
# covers everyday Chinese. Chinese has no whitespace between words, so the
# `[a-z0-9]{3,}` word regex below finds zero tokens in a Chinese sentence and
# every message written in Chinese matched no skill at all (#35). There is no
# dependency-free way to segment Chinese into words — that needs a dictionary
# (jieba and friends) the core stdlib-only rule forbids. The standard
# segmentation-free fallback is character bigrams: overlapping runs of two
# characters, so "明天下午" contributes "明天", "天下", "下午". A description
# that contains "明天" then matches a message that contains it, with no word
# list anywhere.
_CJK_RANGE = "一-鿿㐀-䶿"


def _tokenize(text: str) -> set[str]:
    """Latin words (unchanged) plus CJK character bigrams."""
    words = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
    bigrams = set()
    for run in re.findall(f"[{_CJK_RANGE}]+", text):
        bigrams.update(run[i : i + 2] for i in range(len(run) - 1))
    return words | bigrams


# Bigrams over-generate — a 4-character phrase like 安排任务 yields 3 tokens
# (安排, 排任, 任务) for 2 real words, one of which (排任) is a meaningless
# seam between them. Raising the bar to compensate would also raise it for
# the unchanged Latin path, since both share one threshold and one scoring
# function. Kept at 2 (unchanged from the word-only version): a single
# accidental bigram must not be enough to load a skill, and that much is
# guaranteed — a lone overlapping token is either one real word or one seam,
# never two of either. Two IS occasionally reachable by pure coincidence —
# two seam bigrams in a message happening to match two seam bigrams in a
# description, with no real word in common at all (confirmed against an
# early draft of the schedule-pin description in
# evals/deterministic/test_skill_triggers.py, where run-on prose fused a
# conjunction straight onto a noun with no delimiter between them: "...或任
# 务..." and "...某人某事..." each produced a seam a fully unrelated sentence
# went on to reproduce independently). The mitigation lives in how
# descriptions are written, not in the threshold: keep CJK trigger phrases
# as short, delimiter-separated words or quoted terms rather than flowing
# prose, so a seam stays confined inside one legitimate compound instead of
# spanning the join between two unrelated ones. And make every one of them
# CONTENT-bearing: any phrase of three or more characters yields two or more
# bigrams and so clears this bar ON ITS OWN, delimiters or not. A generic
# function phrase is therefore a standing false positive — listing "有没有"
# ("is there / do you have") as a find-skills trigger fired that skill on six
# of eight ordinary sentences that shared nothing else with it, and it obeyed
# the delimiter rule above the whole time. Connective prose is the same
# hazard with none of the upside: it can only ever misfire, never trigger
# correctly, so descriptions carry trigger terms and stop. See the bundled
# skills'
# `description:` lines for the pattern, and
# evals/deterministic/test_skill_triggers.py for the positive/negative cases
# this bar and that pattern were checked against.
MIN_OVERLAP = 2


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path


def _parse_text(text: str, path: Path) -> Skill | None:
    """Validate SKILL.md content (used by the loader AND the create_skill tool)."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return None
    front, body = match.groups()
    fields = {
        k.strip(): v.strip().strip("'\"")
        for k, _, v in (line.partition(":") for line in front.splitlines() if ":" in line)
    }
    if "name" not in fields or "description" not in fields:
        return None
    return Skill(fields["name"], fields["description"], body.strip(), path)


def _parse(path: Path) -> Skill | None:
    return _parse_text(path.read_text(encoding="utf-8"), path)


class SkillLoader:
    """Scans skill directories: the repo's skills/ (built-in + community) and
    SYRUP_HOME/skills (installed or agent-authored). Re-scans automatically
    when any SKILL.md changes, so a skill created mid-session is live next turn."""

    def __init__(self, dirs: list[Path]):
        self.dirs = dirs
        self.skills: list[Skill] = []
        self._sig: tuple = ()
        self.refresh()

    def _scan_sig(self) -> tuple:
        sig = []
        for d in self.dirs:
            if d.is_dir():
                for f in sorted(d.rglob("SKILL.md")):
                    sig.append((str(f), f.stat().st_mtime))
        return tuple(sig)

    def refresh(self) -> None:
        self.skills = []
        for d in self.dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("SKILL.md")):
                skill = _parse(f)
                if skill:
                    self.skills.append(skill)
        self._sig = self._scan_sig()

    def match(self, message: str, max_skills: int = 2) -> list[Skill]:
        """Transparent trigger: keyword overlap between the message and each
        skill's name+description. No embeddings, no magic — you can compute
        the score in your head."""
        if self._scan_sig() != self._sig:   # a skill was added/edited — reload
            self.refresh()
        msg_tokens = _tokenize(message)
        scored = []
        for skill in self.skills:
            skill_tokens = _tokenize(skill.name + " " + skill.description)
            overlap = len(msg_tokens & skill_tokens)
            if overlap >= MIN_OVERLAP:
                scored.append((overlap, skill))
        scored.sort(key=lambda pair: -pair[0])
        return [skill for _, skill in scored[:max_skills]]
