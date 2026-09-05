"""The homepage names itself in a heading, once, and the tour URL is the same document.

Every portal page and the whole static tier carries an h1; the map page carried none, so a crawler
reading the site found one document with no heading of its own to name it. The fix is a heading over
the header's identity mark rather than a second visible title: the page is an application, its first
visible thing is the mark, and a second line of prose above the map would be a heading for the
crawler and clutter for the reader.

  * ONE HEADING, one wording. The h1 wraps the mark and carries the page's name in a visually hidden
    span, so the header's look is unchanged and the heading a crawler reads is the page's own title.
  * THE TITLE AGREES WITH IT, acronym included. "MT data" is how the community searches, and a
    heading and a title that disagree about the name of the page are two claims about one document.
  * THE TOUR URL IS THE SAME DOCUMENT. /?tour=1 is a query on the root, read by the application from
    location.search; it selects no second file, so the one heading covers both URLs.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]          # portal/
INDEX = ROOT / "index.html"
MAIN_JS = ROOT / "src" / "main.js"

H1_TEXT = "AusMT - Australia's Magnetotelluric (MT) Data Portal"
MARK_IMG = ('<img class="brandmark" src="/vendor/brand/ausmt-mark.svg" alt="AusMT" '
            'width="30" height="30">')
OTHER_PAGES = ("about.html", "add-survey.html", "brand.html", "releases.html", "404.html")

_VOID = {"img", "br", "hr", "input", "meta", "link", "source", "area", "base", "col", "embed",
         "param", "track", "wbr"}


class _Headings(HTMLParser):
    """Every heading in the document, as (level, attrs, text). Parsed rather than matched, so a
    heading inside a comment cannot satisfy a pin and a nested element cannot hide from one."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []
        self._open = []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            self._open.append([int(tag[1]), {k: (v or "") for k, v in attrs}, "", 0])
        elif self._open and tag not in _VOID:
            self._open[-1][3] += 1

    def handle_endtag(self, tag):
        if not self._open:
            return
        if re.fullmatch(r"h[1-6]", tag):
            level, at, text, _d = self._open.pop()
            self.found.append((level, at, " ".join(text.split())))
        elif self._open[-1][3]:
            self._open[-1][3] -= 1

    def handle_data(self, data):
        if self._open:
            self._open[-1][2] += data


def _headings(path):
    p = _Headings()
    p.feed(path.read_text(encoding="utf-8"))
    return p.found


def test_the_homepage_carries_exactly_one_h1_and_it_is_the_page_name():
    """FAILS IF the map page ships no h1, ships more than one, or names itself anything but the
    declared wording. More than one is as wrong as none: a crawler reading two top level headings
    has two claims about what the document is."""
    ones = [(at, text) for level, at, text in _headings(INDEX) if level == 1]
    assert len(ones) == 1, f"index.html must carry exactly one h1, found {len(ones)}: {ones}"
    assert ones[0][1] == H1_TEXT, \
        f"the homepage h1 must read {H1_TEXT!r}, got {ones[0][1]!r}"


def test_the_h1_wraps_the_identity_mark_and_hides_its_own_text():
    """FAILS IF the heading becomes a visible line of its own, or stops being the wrapper around the
    header mark. The header's look is the constraint: the heading exists for a crawler and a screen
    reader, and the identity block renders exactly as it did without it."""
    text = INDEX.read_text(encoding="utf-8")
    m = re.search(r"<h1\b[^>]*>(.*?)</h1>", text, re.S)
    assert m, "index.html must carry an h1"
    assert MARK_IMG in m.group(1), \
        "the homepage h1 must wrap the header identity mark, not stand beside it"
    span = re.search(r'<span class="([\w-]+)">' + re.escape(H1_TEXT) + r"</span>", m.group(1))
    assert span, f"the h1's text must sit in a hidden span, got {m.group(1)!r}"
    rule = re.search(r"\." + span.group(1) + r"\{([^}]*)\}", text)
    assert rule, f"index.html must declare a .{span.group(1)} rule"
    for decl in ("position:absolute", "width:1px", "height:1px", "overflow:hidden", "clip"):
        assert decl in rule.group(1), (
            f"the hidden span must be taken out of flow and clipped, {decl} missing from "
            f"{rule.group(1)!r}")


def test_the_title_and_the_heading_agree():
    """FAILS IF the title and the h1 name the page differently. The acronym is in both or in
    neither: two names for one document is what a crawler reports as a conflict."""
    title = re.search(r"<title>(.*?)</title>", INDEX.read_text(encoding="utf-8")).group(1)
    assert title == H1_TEXT, f"the title must read {H1_TEXT!r}, got {title!r}"


def test_the_tour_url_selects_no_second_document():
    """FAILS IF the guided tour ever becomes a page of its own, or if its flag stops being read from
    the query. Both URLs a site scan lists, / and /?tour=1, are one document, so the one heading
    above answers both; a second document would need a heading of its own."""
    assert not [p.name for p in ROOT.glob("*tour*.html")], \
        "the tour is a state of the map page, never a document of its own"
    src = MAIN_JS.read_text(encoding="utf-8")
    assert "location.search" in src and "tour=1" in src, \
        "the tour flag must be read from the root page's own query string"
    assert 'href="/?tour=1"' in (ROOT / "about.html").read_text(encoding="utf-8"), \
        "the one documented way into the tour is a query on the root"


@pytest.mark.parametrize("name", OTHER_PAGES)
def test_no_other_page_changed_heading_level(name):
    """FAILS IF a page other than the map page gains, loses or renames its top level heading. Each
    of them already named itself, and the homepage heading is not a wording any of them borrows."""
    ones = [text for level, _at, text in _headings(ROOT / name) if level == 1]
    assert len(ones) == 1, f"{name} must keep exactly one h1, found {len(ones)}: {ones}"
    assert ones[0] != H1_TEXT, f"{name}: only the map page carries the site's own name as its h1"
