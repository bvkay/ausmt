"""The appearance tokens: the AuScope house style as the light theme, the navy palette as the dark.

Every portal page declares the same two :root blocks, copied rather than shared because the portal
ships as classic static pages with no template step, and the engine's pages sheet declares them too.
These pins hold every copy to the contract values (tests/chrome_contract.py) AND to each other, so an
edit to one file's block that forgets the others fails here rather than shipping a split palette.

The theme itself is chosen by src/theme.js, which writes data-theme on <html> before first paint. It
can only do that if it is the FIRST script in <head> and runs before the stylesheet: a later script
paints one frame in the wrong theme. It is a file, not an inline block, because the deployed CSP allows
no inline script on these pages.

Each assertion states its failure criterion:

  * TARGETS - FAILS if any page's light or dark block is missing a token, carries an extra one, or
    holds a value other than the contract's. Non-vacuous: the previous palette (--ink, --panel,
    --copper) fails every line.
  * PARITY - FAILS if the two blocks are not identical across the six pages and the engine's sheet.
  * THE RAMP IS THEME-INDEPENDENT - FAILS if the dark block redeclares a data-type colour.
  * RETIRED TOKENS - FAILS if any page or the engine's sheet still declares or reads --ink, --panel,
    --panel-2 or --copper.
  * THE SCRIPT - FAILS if a page does not load /src/theme.js, loads it anywhere but first in <head>,
    loads it after its <style>, or inlines it.
  * ONE CARD STYLE - FAILS if a card on the page ground loses the --line border, the 4px radius
    or the --shadow token in its base rule. Non-vacuous: the add-survey advisory (6px, no shadow), its
    fieldset and panels and the compact survey list (8px, no shadow) fail before the house style.

ENCODING: the reads state encoding="utf-8" explicitly. Without it Path.read_text() decodes with the
locale codec, which is cp1252 on a default Windows shell, and index.html carries UTF-8 glyphs. See
test_test_suite_portability.py.
"""
import re
from pathlib import Path

import pytest

from chrome_contract import DARK, LIGHT, RAMP, RETIRED_TOKENS, THEME_SCRIPT, token_blocks
from engine_chrome import PAGES_PY, function_source

ROOT = Path(__file__).resolve().parent.parent   # portal/
PAGES = ("index.html", "about.html", "add-survey.html", "brand.html", "releases.html", "404.html")


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_page_set_is_the_one_the_portal_ships():
    """FAILS IF a page is added to portal/ without these pins reaching it."""
    assert sorted(p.name for p in ROOT.glob("*.html")) == sorted(PAGES)


@pytest.mark.parametrize("name", PAGES)
def test_every_page_declares_the_contract_tokens(name):
    light, dark = token_blocks(_text(name))
    assert light == LIGHT, f"{name}: the light block differs from the contract:\n  got  {light}\n  want {LIGHT}"
    assert dark == DARK, f"{name}: the dark block differs from the contract:\n  got  {dark}\n  want {DARK}"


def test_the_engine_sheet_declares_the_contract_tokens():
    """The generated pages wear the same appearance, so their sheet carries the same two blocks."""
    light, dark = token_blocks(PAGES_PY.read_text(encoding="utf-8"))
    assert light == LIGHT, f"engine/extract/_pages.py: the light block differs:\n  got  {light}\n  want {LIGHT}"
    assert dark == DARK, f"engine/extract/_pages.py: the dark block differs:\n  got  {dark}\n  want {DARK}"


def test_cross_file_parity():
    """The blocks are compared with each other as well as with the contract, so a contract edit that
    reaches some copies and not others is a failure here before it is a visible split."""
    seen = {name: token_blocks(_text(name)) for name in PAGES}
    ref = seen[PAGES[0]]
    for name, blocks in seen.items():
        assert blocks == ref, f"{name}: the token blocks diverge from {PAGES[0]}"


def test_the_data_ramp_is_the_same_in_both_themes():
    """A legend must not change meaning with the theme, so the dark block never restates the ramp."""
    for token in RAMP:
        assert token in LIGHT and token not in DARK, token
    for name in PAGES:
        _light, dark = token_blocks(_text(name))
        assert not set(RAMP) & set(dark), f"{name}: the dark block redeclares a data-type colour"


@pytest.mark.parametrize("name", PAGES)
def test_no_page_declares_or_reads_a_retired_token(name):
    text = _text(name)
    for token in RETIRED_TOKENS:
        assert not re.search(re.escape(token) + r"\s*:", text), f"{name}: declares the retired {token}"
        assert f"var({token})" not in text, f"{name}: reads the retired {token}"


def test_no_portal_script_reads_a_retired_token():
    for path in sorted((ROOT / "src").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for token in RETIRED_TOKENS:
            assert f"var({token})" not in text, f"src/{path.name}: reads the retired {token}"


def _head(text):
    return text.split("<head>", 1)[1].split("</head>", 1)[0]


@pytest.mark.parametrize("name", PAGES)
def test_the_appearance_script_runs_first_in_head(name):
    head = _head(_text(name))
    opens = re.findall(r"<script\b[^>]*>", head)
    assert opens, f"{name}: <head> carries no script at all"
    assert opens[0] + "</script>" == THEME_SCRIPT and head.count(opens[0] + "</script>") == 1, (
        f"{name}: the first script element in <head> must be {THEME_SCRIPT}, so data-theme is written "
        f"before anything paints; got {opens[0]!r}")
    assert head.count(THEME_SCRIPT) == 1, f"{name}: the appearance script is loaded more than once"
    assert head.index(THEME_SCRIPT) < head.index("<style"), (
        f"{name}: the appearance script must run before the stylesheet")


def test_the_engine_shell_loads_the_appearance_script_first():
    """Read from the document _shell returns, in the order it writes it: the JSON-LD blocks are
    assembled earlier in the function and interpolated into the head, so they must follow the
    appearance script there."""
    shell = function_source("_shell")
    assert "<!DOCTYPE html>" in shell, "engine/extract/_pages.py: _shell no longer writes the document"
    head = shell[shell.index("<!DOCTYPE html>"):].split("</head>", 1)[0]
    assert THEME_SCRIPT in head, "engine/extract/_pages.py: _shell must load /src/theme.js in the head"
    at = head.index(THEME_SCRIPT)
    assert at < head.index("<style>"), (
        "engine/extract/_pages.py: _shell must load /src/theme.js before its stylesheet")
    first_script = re.search(r"<script\b[^>]*>(?:</script>)?", head)
    assert first_script and first_script.group(0) == THEME_SCRIPT, (
        "engine/extract/_pages.py: /src/theme.js must be the first script the head writes")
    if "{ld}" in head:
        assert at < head.index("{ld}"), (
            "engine/extract/_pages.py: the JSON-LD blocks must follow the appearance script")


# Every card on a page ground, by page. A card is a --surface box sitting on --bg; a raised row inside a
# card is --surface-2 and is not listed. A new card joins this list or nothing holds its style.
CARDS = {
    "index.html": (".cstat", ".scard", ".emptystate", ".maplegend", ".cardlist"),
    "about.html": (".card", ".toc"),
    "add-survey.html": (".advisory", "fieldset", ".panel", ".tier"),
    "brand.html": (".usage", ".item", ".swatch", ".hero"),
    "releases.html": (".state", ".rel"),
}
CARD_STYLE = {"border": "1px solid var(--line)", "border-radius": "4px", "box-shadow": "var(--shadow)"}


def _base_rules(text):
    """{selector: declarations} for the top-level rules of a page's <style>, comments stripped and
    every at-rule block skipped, so a narrower-width override cannot stand in for the base rule. A
    selector declared twice merges in source order, as the cascade does."""
    css = text.split("<style>", 1)[1].split("</style>", 1)[0]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = {}, 0
    while True:
        brace = css.find("{", i)
        if brace < 0:
            return out
        prelude = css[i:brace].strip()
        depth, j = 1, brace + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        if not prelude.startswith("@"):
            out.setdefault(prelude, {}).update(_decls_of(css[brace + 1:j - 1]))
        i = j


def _decls_of(body):
    out = {}
    for decl in body.split(";"):
        if ":" in decl:
            name, value = decl.split(":", 1)
            out[name.strip()] = " ".join(value.split())
    return out


def test_the_card_list_covers_every_page_but_the_404():
    """The 404 page carries no card; every other page is enumerated, so a page added later is too."""
    assert sorted(CARDS) == sorted(set(PAGES) - {"404.html"})


@pytest.mark.parametrize("name,selector", [(n, s) for n, sels in CARDS.items() for s in sels])
def test_every_card_takes_the_house_style_card_rules(name, selector):
    rules = _base_rules(_text(name))
    assert selector in rules, f"{name}: no base {selector}{{...}} rule"
    got = {k: rules[selector].get(k) for k in CARD_STYLE}
    assert got == CARD_STYLE, (
        f"{name}: the {selector} card must take the house-style border, radius and shadow:\n"
        f"  got  {got}\n  want {CARD_STYLE}")


def test_the_appearance_script_ships_and_is_never_inlined():
    script = ROOT / "src" / "theme.js"
    assert script.is_file(), "portal/src/theme.js is missing"
    body = script.read_text(encoding="utf-8")
    assert "ausmt:theme" in body and "data-theme" in body, "theme.js must set data-theme and announce it"
    for name in PAGES:
        if name == "add-survey.html":
            continue                     # the one page whose CSP allows its own inline application block
        inline = re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*application/ld\+json)[^>]*>(.*?)</script>",
                            _text(name), re.S)
        assert not [b for b in inline if b.strip()], f"{name}: carries an inline script"
