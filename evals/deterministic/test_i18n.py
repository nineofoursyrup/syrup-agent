"""DETERMINISTIC EVAL — the dashboard's bilingual catalog hangs together.

The frontend has no build step and no JS test runner, so a mistyped key in a
`tr("…")` call is invisible until someone opens that tab in that language and
reads a raw key where a sentence should be. These checks are the guard a Python
suite can give without a browser:

  1. every key a `tr("…")` call asks for exists in the catalog,
  2. every catalog entry has BOTH halves, non-empty — a half-translated string
     renders as a blank, which is worse than an obvious untranslated one,
  3. every page the router can reach has an eyebrow and a subtitle, since
     render() builds those keys by string concatenation (`"page." + view`) and
     no grep can see them,
  4. nothing in the catalog is dead weight.

Rule of thumb when one of these fails: the catalog is the thing to fix, not the
test. A string on screen with no key is a string that cannot be translated.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "syrup" / "ops" / "static"
JS_DIR = STATIC / "js"
# Comments stripped first: i18n.js documents its own format with a worked
# example ("some.key": ["中文", "English"]), and a doc comment that parses as a
# catalog entry would be reported as an untranslated string forever.
I18N_SRC = re.sub(r"^\s*//.*$", "", (JS_DIR / "i18n.js").read_text(), flags=re.MULTILINE)
INDEX = (STATIC / "index.html").read_text()
# Every js/ file except the catalog itself — i18n.js contains the definitions,
# and its own doc-comment examples must not count as call sites.
CALLER_SRC = "\n".join(
    f.read_text() for f in sorted(JS_DIR.glob("*.js")) if f.name != "i18n.js"
)

# One catalog entry, both halves, across however many lines it wraps onto:
#     "some.key": ["中文", "English"],
ENTRY = re.compile(
    r'"([\w.]+)":\s*\[\s*("(?:[^"\\]|\\.)*")\s*,\s*("(?:[^"\\]|\\.)*")\s*\]', re.DOTALL
)
# Anything that LOOKS like a key, so the shape check can report an entry the
# pair regex above failed to parse instead of silently skipping it.
ENTRY_KEY = re.compile(r'^\s*"([\w.]+)":', re.MULTILINE)

# A tr() call with a complete literal key — the quote must close onto `)` or a
# comma. `tr("prov." + status)` is a PREFIX, not a key, and matching it would
# report the fragment "prov." as undefined.
CALL = re.compile(r'(?<![.\w$])tr\(\s*"([\w.]+)"\s*[),]')
# Keys assembled at the call site: tr("page." + view + ".sub").
CALL_PREFIX = re.compile(r'(?<![.\w$])tr\(\s*"([\w.]*\.)"\s*\+')
# Some keys are never written inside a tr() call at all — they are stored in a
# lookup (STAGE's label, DB_DESC, CONNECTION_GROUP_LABELS, MA_SLOW) and resolved
# later through a variable. A bare literal that matches a catalog key counts as
# a reference, which is exactly what those are.
LITERAL = re.compile(r'"([\w.]+)"')
# The data-i18n family in index.html, whose values are keys too.
ATTR = re.compile(r'data-i18n(?:-html|-ph|-title)?="([\w.]+)"')

# The views the hash router can land on (main.js falls back to overview for
# anything else). Kept here rather than parsed out of views.js: this list IS the
# contract — add a view, add its two strings.
VIEWS = [
    "overview", "gateway", "loop", "graph", "memory", "tools", "database",
    "ops", "compare", "models", "connections", "settings",
]


def _catalog() -> dict[str, tuple[str, str]]:
    """key -> (中文, English), for every entry that parses as a proper pair."""
    return {m.group(1): (m.group(2)[1:-1], m.group(3)[1:-1])
            for m in ENTRY.finditer(I18N_SRC)}


def _used_keys() -> set[str]:
    """Every catalog key the frontend references, however it does so."""
    return (set(LITERAL.findall(CALLER_SRC)) | set(ATTR.findall(INDEX))) & set(_catalog())


def test_every_key_used_is_defined():
    """A tr("…") for a key that isn't in the catalog renders the key itself —
    visible, but only to whoever opens that tab. Catch it here instead."""
    asked = set(CALL.findall(CALLER_SRC)) | set(ATTR.findall(INDEX))
    missing = sorted(asked - set(_catalog()))
    assert not missing, f"tr() calls a key the catalog doesn't define: {missing}"


def test_every_view_has_a_page_header():
    """render() builds these by concatenation — `tr("page." + view + ".sub")` —
    so no grep over call sites can see them. A view added without its two
    strings shows the literal "page.newthing.sub" above the page."""
    catalog = _catalog()
    missing = [f"page.{v}.{part}"
               for v in VIEWS for part in ("eyebrow", "sub")
               if f"page.{v}.{part}" not in catalog]
    assert not missing, f"views with no header strings: {missing}"


def test_every_entry_has_both_languages():
    """["中文", "English"] — both halves, both non-empty. A missing half is a
    blank on the page, which reads as a layout bug rather than a missing
    translation and so goes unreported."""
    catalog = _catalog()
    # Anything the pair regex could not read is malformed by definition: a
    # single string, three strings, or a stray bracket.
    unparsed = sorted(set(ENTRY_KEY.findall(I18N_SRC)) - set(catalog))
    assert not unparsed, f"entries that are not a pair of strings: {unparsed}"
    blank = sorted(k for k, (zh, en) in catalog.items() if not zh.strip() or not en.strip())
    assert not blank, f"entries with an empty half: {blank}"


def test_no_dead_entries():
    """A key nothing asks for is a string nobody sees — usually the leftover of
    a reworded panel. Keys reached through a call-site prefix (tr("page." +
    view + ".sub"), tr("prov." + status)) are exempt: no grep can resolve them,
    and their own tests pin the ones that matter."""
    prefixes = tuple(CALL_PREFIX.findall(CALLER_SRC))
    used = _used_keys()
    unused = sorted(k for k in _catalog()
                    if k not in used and not k.startswith(prefixes))
    assert not unused, f"catalog entries nothing references: {unused}"


def test_chinese_is_the_first_half():
    """The catalog is ["中文", "English"] and tr() indexes it by that order, so a
    pair written the other way round silently serves English to 中文 readers.
    Checking a sample that MUST contain Han characters pins the order without
    demanding one in every entry (many are model ids, units, or code)."""
    catalog = _catalog()
    for key in ("page.overview.sub", "mem.semBlurb", "gw.blurb", "ops.releaseBody"):
        zh = catalog[key][0]
        assert re.search(r"[一-鿿]", zh), \
            f"{key}: the first half must be the 中文 one, got {zh[:40]!r}"


def test_language_default_is_chinese():
    """The design this page implements is Chinese-first, and the default is the
    one thing a user cannot discover by clicking — it is what they see before
    they know a switch exists."""
    assert 'localStorage.getItem("syrup_lang") === "en" ? "en" : "zh"' in I18N_SRC, \
        "the language default moved away from 中文 (or the guard was rewritten)"
