"""The appearance tokens: the AuScope house style, the portal's one appearance.

Every portal page declares the same :root block, copied rather than shared because the portal ships
as classic static pages with no template step, and the engine's pages sheet declares it too. These
pins hold every copy to the contract values (tests/chrome_contract.py) AND to each other, so an edit
to one file's block that forgets the others fails here rather than shipping a split palette. That no
surface declares a second appearance is held in test_one_appearance.py.

Each assertion states its failure criterion:

  * TARGETS - FAILS if any page's block is missing a token, carries an extra one, or holds a value
    other than the contract's. Non-vacuous: the previous palette (--ink, --panel, --copper) fails
    every line.
  * PARITY - FAILS if the block is not identical across the six pages and the engine's sheet.
  * RETIRED TOKENS - FAILS if any page or the engine's sheet still declares or reads --ink, --panel,
    --panel-2 or --copper.
  * NO INLINE SCRIPT - FAILS if a page other than add-survey.html carries an inline script block.
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

from chrome_contract import LIGHT, RAMP, RETIRED_TOKENS, WORDMARK_FAMILY, token_block
from engine_chrome import PAGES_PY, namespace

ROOT = Path(__file__).resolve().parent.parent   # portal/
PAGES = ("index.html", "about.html", "add-survey.html", "brand.html", "releases.html", "404.html")


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_page_set_is_the_one_the_portal_ships():
    """FAILS IF a page is added to portal/ without these pins reaching it."""
    assert sorted(p.name for p in ROOT.glob("*.html")) == sorted(PAGES)


@pytest.mark.parametrize("name", PAGES)
def test_every_page_declares_the_contract_tokens(name):
    block = token_block(_text(name))
    assert block == LIGHT, f"{name}: the token block differs from the contract:\n  got  {block}\n  want {LIGHT}"


def test_the_engine_sheet_declares_the_contract_tokens():
    """The generated pages wear the same appearance, so their sheet carries the same block."""
    block = token_block(PAGES_PY.read_text(encoding="utf-8"))
    assert block == LIGHT, f"engine/extract/_pages.py: the token block differs:\n  got  {block}\n  want {LIGHT}"


def test_cross_file_parity():
    """The blocks are compared with each other as well as with the contract, so a contract edit that
    reaches some copies and not others is a failure here before it is a visible split."""
    seen = {name: token_block(_text(name)) for name in PAGES}
    ref = seen[PAGES[0]]
    for name, block in seen.items():
        assert block == ref, f"{name}: the token block diverges from {PAGES[0]}"


def test_the_data_ramp_is_declared_with_the_chrome_tokens():
    for token in RAMP:
        assert token in LIGHT, token


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


def test_no_page_carries_an_inline_script():
    for name in PAGES:
        if name == "add-survey.html":
            continue                     # the one page whose CSP allows its own inline application block
        inline = re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*application/ld\+json)[^>]*>(.*?)</script>",
                            _text(name), re.S)
        assert not [b for b in inline if b.strip()], f"{name}: carries an inline script"


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
