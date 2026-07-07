"""about.html carries the SAME header/footer chrome as index.html (fix/about-uniform-chrome).

The owner's ask: About must wear the portal's three-zone header (brand / centre nav / right zone) and a
footer with the version chip, so chrome is uniform across pages. These are STRUCTURAL assertions parsed
from the real DOM (stdlib html.parser, so no jsdom / node dependency and no substring-vs-comment false
positives — HTML comments are not surfaced as elements by the parser).

Each assertion states its failure criterion:

  * three-zone header — FAILS if about.html's <header> does not contain exactly one element carrying
    each of the .hleft / .hcenter / .hright zone classes (the classes index.html uses). Proven
    non-vacuous: the pre-fix about.html had a flat header with none of these classes.
  * About marked active — FAILS if the centre-zone About link is not rendered in the active state, or if
    any OTHER centre nav item is (only the current page may be active).
  * no counts on a static page — FAILS if about.html carries any live-counts element (id nVis/nSel/nTot
    or class "counts"); those are app-state and meaningless on a static page. Non-vacuous: index.html
    HAS these ids, so a naive copy-the-whole-header would trip this.
  * one version chip — FAILS if the number of real elements carrying data-ver-chip is not exactly 1
    (must survive the reverse case too: zero chips, or a duplicated chip, both fail).
"""
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
ABOUT = ROOT / "about.html"
INDEX = ROOT / "index.html"


class _Collector(HTMLParser):
    """Records every start tag with its attributes and a running header-depth flag, so tests can ask
    'which elements are inside <header>' and 'what classes/attrs does each element carry' against the
    parsed DOM rather than raw text (comments never reach handle_starttag)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []          # list of (tag, attrs-dict, in_header:bool)
        self._header_depth = 0

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        in_header = self._header_depth > 0 or tag == "header"
        self.elements.append((tag, d, in_header))
        if tag == "header":
            self._header_depth += 1
        elif self._header_depth > 0 and tag not in _VOID:
            self._header_depth += 1

    def handle_endtag(self, tag):
        if self._header_depth > 0 and tag not in _VOID:
            self._header_depth -= 1


_VOID = {"img", "br", "hr", "input", "meta", "link", "source", "area", "base", "col", "embed",
         "param", "track", "wbr"}


def _parse(path):
    p = _Collector()
    p.feed(path.read_text(encoding="utf-8"))
    return p.elements


def _classes(attrs):
    return set(attrs.get("class", "").split())


def test_about_header_has_three_zone_classes():
    els = _parse(ABOUT)
    for zone in ("hleft", "hcenter", "hright"):
        matches = [e for (tag, a, inh) in els for e in [1]
                   if inh and zone in _classes(a)]
        assert len(matches) == 1, (
            f"about.html header must contain exactly one .{zone} zone (index's three-zone chrome); "
            f"found {len(matches)}")


def test_about_marked_active_and_no_other_center_nav_is():
    els = _parse(ABOUT)
    # The About link: an <a> whose class set includes 'about' and which points at about.html.
    about_links = [a for (tag, a, inh) in els
                   if tag == "a" and inh and "about" in _classes(a) and a.get("href") == "about.html"]
    assert len(about_links) == 1, "expected exactly one centre-zone About link -> about.html"
    assert "active" in _classes(about_links[0]), "the About link must render in the active state (it is the current page)"

    # No OTHER centre-zone link (Map/Surveys/Collections/How-to-use/Contribute) may carry 'active'.
    other_active = [a for (tag, a, inh) in els
                    if tag == "a" and inh and "active" in _classes(a) and a.get("href") != "about.html"]
    assert not other_active, f"only About may be active on about.html; also-active: {[a.get('href') for a in other_active]}"


def test_about_has_no_live_counts_elements():
    # Live counts are app-state and meaningless on a static page — none of index's count ids/classes.
    els = _parse(ABOUT)
    count_ids = {"nVis", "nSel", "nTot"}
    id_hits = [a.get("id") for (tag, a, inh) in els if a.get("id") in count_ids]
    class_hits = [a for (tag, a, inh) in els if "counts" in _classes(a)]
    assert not id_hits, f"about.html must carry no live-counts ids; found {id_hits}"
    assert not class_hits, "about.html must carry no .counts element (live counts are app-state)"


def test_about_footer_carries_exactly_one_ver_chip():
    els = _parse(ABOUT)
    chips = [a for (tag, a, inh) in els if "data-ver-chip" in a]
    assert len(chips) == 1, f"about.html must carry exactly one data-ver-chip element; found {len(chips)}"


def test_index_still_has_the_count_ids_the_about_guard_forbids():
    # Guards the guard: proves test_about_has_no_live_counts_elements is non-vacuous by confirming the
    # very ids it forbids DO exist on index.html. If index ever drops them this reminds us to re-check
    # what 'no counts' is actually asserting against.
    els = _parse(INDEX)
    ids = {a.get("id") for (tag, a, inh) in els}
    assert {"nVis", "nSel", "nTot"} <= ids, "index.html should still carry the live-count ids (nVis/nSel/nTot)"
