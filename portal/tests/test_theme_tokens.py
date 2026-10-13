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
  * THE CONTROL - FAILS if the appearance row is not the contract row, once, in index.html's welcome
    dialog and in about.html's Appearance section, if any other page or the engine's sheet carries
    it, if src/theme.js stops wiring and checking the radios named "appearance", if it keeps a hook
    for a control no page carries, or if its window.AusmtTheme interface changes.
  * ONE CARD STYLE - FAILS if a card on the page ground loses the --line border, the 4px radius
    or the --shadow token in its base rule. Non-vacuous: the add-survey advisory (6px, no shadow), its
    fieldset and panels and the compact survey list (8px, no shadow) fail before the house style.
  * THE WORDMARK'S FAMILY - FAILS if a header's wordmark stops leading its stack with Calibre over the
    --sans token, or if any page or engine sheet declares an @font-face or names a font file. AuScope's
    licence covers Calibre on this site, but no face is served, so a reader without it installed sees
    --sans; a face declared before its files ship is a request every page makes and loses.

ENCODING: the reads state encoding="utf-8" explicitly. Without it Path.read_text() decodes with the
locale codec, which is cp1252 on a default Windows shell, and index.html carries UTF-8 glyphs. See
test_test_suite_portability.py.
"""
import re
from pathlib import Path

import pytest

from chrome_contract import (ABOUT_APPEARANCE, DARK, LIGHT, RAMP, RETIRED_TOKENS, THEME_SCRIPT,
                             WELCOME_APPEARANCE, WORDMARK_FAMILY, flat, token_blocks)
from engine_chrome import PAGES_PY, function_source, namespace

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


# The appearance row's two homes, and what src/theme.js must do with it. The radios are read on
# change, through one listener on document, and checked to match the stored choice whenever it is
# applied; nothing on any page carries another kind of appearance control.
_HOMES = {"index.html": WELCOME_APPEARANCE, "about.html": ABOUT_APPEARANCE}
_WIRING = ("document.querySelectorAll('input[name=\"appearance\"]')",
           'r.name === "appearance" && r.checked',
           "radios[i].checked = radios[i].value === c")
_RETIRED_HOOKS = ("data-theme-choice", "aria-pressed", "welcomeTheme", '"click"')
_INTERFACE = ("window.AusmtTheme = { get: choice, resolved: function () { return resolve(choice()); }, "
              "set: set };")


@pytest.mark.parametrize("name", PAGES)
def test_the_appearance_row_lives_in_the_welcome_dialog_and_on_about_alone(name):
    """THE CONTROL, page by page. FAILS if index.html's welcome dialog or about.html's Appearance
    section stops carrying the contract row exactly once, or if any other page carries a radio named
    "appearance": the row has two homes, and the footer is not one of them."""
    text = _text(name)
    if name in _HOMES:
        assert flat(text).count(flat(_HOMES[name])) == 1, (
            f"{name}: the appearance row must be the contract row, once:\n  want {_HOMES[name]!r}")
        assert text.count('name="appearance"') == 3, (
            f"{name}: the page carries the three appearance radios and no others")
    else:
        assert 'name="appearance"' not in text, f"{name}: the appearance row lives in two places only"
    if name == "index.html":
        dialog = text.split('<div id="introWelcome"', 1)[1].split("</fieldset>", 1)[0]
        assert flat(WELCOME_APPEARANCE).rsplit("</fieldset>", 1)[0] in flat(dialog), (
            "index.html: the appearance row sits inside the welcome dialog")
    if name == "about.html":
        section = text.split('<section id="appearance">', 1)[1].split("</section>", 1)[0]
        assert flat(ABOUT_APPEARANCE) in flat(section), (
            "about.html: the appearance row sits inside the Appearance section")


def test_the_engine_pages_carry_no_appearance_row():
    """The engine's pages reach the choice through the header's About link. FAILS if the engine's
    source writes a radio named "appearance" or the retired button hook."""
    source = PAGES_PY.read_text(encoding="utf-8")
    for gone in ('name="appearance"', "data-theme-choice", "themectl"):
        assert gone not in source, f"engine/extract/_pages.py: carries {gone!r}"


def test_the_appearance_script_wires_the_radios_and_nothing_else():
    """THE CONTROL, script side. FAILS if src/theme.js stops reading a change on the radios named
    "appearance" or stops checking the one that matches the stored choice, if it keeps a hook for a
    control no page carries (a data-theme-choice element, a pressed state, a click listener, radios
    named welcomeTheme), or if the window.AusmtTheme interface its callers use changes."""
    script = (ROOT / "src" / "theme.js").read_text(encoding="utf-8")
    for wire in _WIRING:
        assert wire in script, f"src/theme.js: the radios must be wired by {wire!r}"
    for gone in _RETIRED_HOOKS:
        assert gone not in script, f"src/theme.js: {gone!r} serves a control no page carries"
    assert script.count(_INTERFACE) == 1, f"src/theme.js: the interface must stay {_INTERFACE!r}"
    accepted = re.search(r'if \(c !== "light" && c !== "dark" && c !== "system"\) return;', script)
    assert accepted, "src/theme.js: set() must accept exactly light, dark and system"
    values = re.findall(r'name="appearance" value="([a-z]+)"', WELCOME_APPEARANCE)
    assert values == ["light", "dark", "system"], (
        f"the row offers exactly the three choices set() accepts, in order: {values}")


# A served font file, by extension, in any slot a page or a sheet could name one: a src, a url() or a
# link. The engine's card renderer reads a bundled face at build time, which no page names; this reads
# the served sheets only, so that read is not one of these.
_FONT_FILE = re.compile(r"\.(?:woff2?|otf|ttf|eot)\b", re.I)


def _wordmark_family(where, text):
    rules = re.findall(r"(?m)^\s*\.wordmark\{([^}]*)\}", text)
    assert len(rules) == 1, f"{where}: expected exactly one .wordmark rule, found {len(rules)}"
    family = re.search(r"(?:^|;)font-family:([^;}]*)", rules[0])
    assert family, f"{where}: the wordmark must declare its own family: {rules[0]!r}"
    return family.group(1)


@pytest.mark.parametrize("name", PAGES)
def test_the_wordmark_leads_with_calibre_and_no_page_ships_a_face(name):
    """THE WORDMARK'S FAMILY, page by page. FAILS if a header's wordmark declares any family but
    Calibre over the --sans token, or if the page declares an @font-face or names a font file. 404.html
    carries no header, so only the second half reaches it."""
    text = _text(name)
    if name != "404.html":
        assert _wordmark_family(name, text) == WORDMARK_FAMILY, (
            f"{name}: the wordmark's stack is {WORDMARK_FAMILY}, falling through to the page's --sans")
    assert "@font-face" not in text, f"{name}: no page declares a face; the Calibre files are not served"
    assert not _FONT_FILE.search(text), f"{name}: no page names a font file: {_FONT_FILE.search(text)}"


def test_the_engine_sheets_lead_the_wordmark_with_calibre_and_ship_no_face():
    """THE WORDMARK'S FAMILY on the generated pages, read from the sheets the engine writes. FAILS if
    the shared sheet's wordmark declares any other family, or if any of the engine's sheets declares an
    @font-face or names a font file."""
    sheets = {k: v for k, v in namespace().items() if k.endswith("_CSS") and isinstance(v, str)}
    assert {"_CSS", "_INDEX_CSS", "_FETCH_CSS"} <= set(sheets), f"the engine's sheets moved: {sorted(sheets)}"
    assert _wordmark_family("engine/extract/_pages.py _CSS", sheets["_CSS"]) == WORDMARK_FAMILY
    for name, sheet in sheets.items():
        assert "@font-face" not in sheet, f"engine/extract/_pages.py {name}: no sheet declares a face"
        assert not _FONT_FILE.search(sheet), f"engine/extract/_pages.py {name}: no sheet names a font file"
