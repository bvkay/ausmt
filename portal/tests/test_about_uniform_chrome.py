"""about.html carries the SAME header/footer chrome as index.html.

The ask: About must wear the portal's three-zone header (brand / centre nav / right zone) and
the site's one footer, so chrome is uniform across pages. These are STRUCTURAL assertions parsed
from the real DOM (stdlib html.parser, so no jsdom / node dependency and no substring-vs-comment false
positives — HTML comments are not surfaced as elements by the parser).

Each assertion states its failure criterion:

  * three-zone header — FAILS if about.html's <header> does not contain exactly one element carrying
    each of the .hleft / .hcenter / .hright zone classes (the classes index.html uses). Proven
    non-vacuous: the pre-fix about.html had a flat header with none of these classes.
  * About marked active — FAILS if the centre-zone About link is not rendered in the active state, or if
    any OTHER centre nav item is (only the current page may be active).
  * no APP-STATE counts on a static page: FAILS if about.html carries any of index's live-counts ids
    (nVis/nSel/nTot). Those three report the current map's filter and selection state, and About has
    neither. Non-vacuous: index.html HAS these ids, so a naive copy-the-whole-header would trip this.
    NARROWED by the The API docs section, deliberately: the ban does not extend to the class "counts",
    on the reasoning that a static page has no counts to state. That reasoning covered app state only.
    About now carries a CORPUS-totals block (total stations / total surveys, read from the catalogue at
    load time) in index's right zone, reusing index's .counts styling so the two headers render
    identically (see test_header_parity_about_matches_index). The app-state ids remain banned, which is
    the half of the old assertion that was actually about honesty; the class ban was about styling.
  * NO version chip, anywhere. FAILS if any element carrying data-ver-chip survives on any of the
    four documents. The chip was the last of the About-this-build popover's copy: the popover left
    every footer with the one-footer rule, the chip followed it into about.html's #build section,
    and that section is deleted too. Zero on every surface, held from both ends: the attribute is
    gone, and so is the script that filled it: no page loads it and the tree does not ship it. A
    script whose whole job is to fill an element no page carries reaches no reader.
  * every page script the tree ships is loaded by at least one page, and every script a page
    loads is one the tree ships. FAILS in either direction.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
ABOUT = ROOT / "about.html"
INDEX = ROOT / "index.html"
ADD = ROOT / "add-survey.html"
RELEASES = ROOT / "releases.html"
# The scripts this repository authors under vendor/: the coastline the build generates. A
# third-party library there is somebody else's file and is not held to being loaded.
AUTHORED_VENDOR_SCRIPTS = ("vendor/au-outline.js",)


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


class _FooterCollector(HTMLParser):
    """Records every start tag INSIDE <footer> (running footer-depth flag), the footer analogue of
    _Collector. Backs the footer-chrome pins, asserted against the parsed DOM (comments never reach
    handle_starttag, so a commented-out control cannot satisfy or trip one)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []          # (tag, attrs-dict) for elements inside <footer>
        self._depth = 0             # footer nesting depth

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        if self._depth > 0 and tag != "footer":
            self.elements.append((tag, d))
        if tag == "footer":
            self._depth += 1
        elif self._depth > 0 and tag not in _VOID:
            self._depth += 1

    def handle_endtag(self, tag):
        if self._depth > 0 and tag not in _VOID:
            self._depth -= 1


def _parse(path):
    p = _Collector()
    p.feed(path.read_text(encoding="utf-8"))
    return p.elements


def _footer_els(path):
    p = _FooterCollector()
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
    """Live APP-STATE counts are meaningless on a static page: none of index's nVis/nSel/nTot may appear
    here. The corpus-totals block About does carry is a different claim (catalogue facts, not the current
    map's filter/selection state) and is pinned separately below; see the module docstring for why the
    old class-level ban was narrowed."""
    els = _parse(ABOUT)
    count_ids = {"nVis", "nSel", "nTot"}
    id_hits = [a.get("id") for (tag, a, inh) in els if a.get("id") in count_ids]
    assert not id_hits, (
        f"about.html must carry no live app-state count ids (nVis/nSel/nTot); found {id_hits}. The "
        f"header's corpus-totals block states catalogue totals and must not borrow these ids.")
    # Whatever .counts element About does carry must be the CORPUS one, marked as such.
    counts = [a for (tag, a, inh) in els if "counts" in _classes(a)]
    assert len(counts) == 1, f"about.html must carry exactly one .counts element; found {len(counts)}"
    assert "corpus" in _classes(counts[0]), (
        "about.html's .counts element must carry the 'corpus' marker class: it states catalogue totals, "
        "not index's live map state, and the two must stay distinguishable at a glance")


def test_no_portal_document_carries_a_ver_chip():
    """FAILS if a version chip survives on any of the four documents. about.html held the last one;
    with its #build section deleted there is no chip on the site, which is what made the script
    that filled one a file no page had a use for."""
    for path in (ABOUT, INDEX, ADD, RELEASES):
        chips = [a for (tag, a, _inh) in _parse(path) if "data-ver-chip" in a]
        assert not chips, (
            f"{path.name}: no surface carries a version chip; the section that held the last one is "
            f"deleted, found {len(chips)}")


def test_about_references_no_nonexistent_federation_doc():
    """Citation honesty. FAILS if about.html names FEDERATION.md: no such file exists anywhere in the
    repository, so the reference sends a reader after a document that is not there. Federation is a
    property of MTCAT itself and docs/docs/developer/data-files.md describes mtcat.json as the
    discovery and federation document, so the claim is stated rather than repointed at a file name.

    Raw-text check ON PURPOSE (unlike this module's parsed-DOM tests): a commented-out reference is
    still a claim waiting to be resurrected, and the parser drops comments. The companion assertion
    pins the HONEST half of the sentence: the spec reference must SURVIVE the removal, so an
    over-deletion fails here too.

    The over-deletion pin is the docs-site URL the bullet links, never the literal string
    "MTCAT v1.0". A version number doing a link's job goes stale on the next schema bump, and the
    version a consumer should trust is the one the document declares about itself, never a number
    typed into this page. The URL is /reference/mtcat-schema/, the one page carrying the schema
    reference."""
    raw = ABOUT.read_text(encoding="utf-8")
    assert "FEDERATION.md" not in raw, (
        "about.html must not reference FEDERATION.md - that file does not exist in the repository")
    assert "https://ausmt.readthedocs.io/en/latest/reference/mtcat-schema/" in raw, (
        "the honest MTCAT specification reference must survive the FEDERATION.md removal (over-deletion)")
    assert "MTCAT v1.0" not in raw, (
        "about.html must not hard-code an MTCAT version that the served schema has moved past; the "
        "served document declares its own version, which is the only copy that cannot go stale")


def test_mtcat_link_in_footer_not_header_across_pages():
    """The machine-readable MTCAT link moved from the header's right zone into the footer's
    bottom-left, applied identically across index / about / add-survey. Each page must carry EXACTLY ONE
    apilink (a.apilink -> data/mtcat.json) INSIDE <footer>, and NONE inside <header>.

    Failure criteria, both non-vacuous and mutually hermetic:
      * footer-PRESENCE — FAILS if a page's <footer> does not carry exactly one a.apilink. This proves the
        link still exists after the move, so the header-absence half below is a real relocation and not a
        vacuous pass on a deleted element.
      * header-ABSENCE — FAILS if any a.apilink survives inside <header>. Proven falsifiable by a git-archive
        red-proof against the pre-move HTML (link in the header): that HTML fails header-ABSENCE here.

    Parsed-DOM (not raw text): about.html also links data/mtcat.json from its <main> body with class 'link'
    (not 'apilink'), which lives in neither <header> nor <footer>, so neither collector counts it — the
    class match ('apilink') is deliberately specific so that body link cannot smuggle a false positive.

    MTCAT 1.2 fix round: the title pin was "MTCAT v1.0 discovery document (JSON)" on all three pages, for
    a document that had already been 1.1 and is now 1.2. Pinning it "verbatim" made this test the thing
    KEEPING the wrong number on the page. The title is now version-free on all three, and the pin also
    asserts NO version number appears in it, so nobody re-introduces a hard-coded one. The version a
    reader needs is in the document itself: mtcat.json declares its own schema_version, generated
    from the single-source MTCAT_VERSION constant in contract/generate.py."""
    for path in (INDEX, ABOUT, ADD):
        header_hits = [a for (tag, a, inh) in _parse(path)
                       if tag == "a" and inh and "apilink" in _classes(a)]
        assert not header_hits, (
            f"{path.name}: the MTCAT apilink must NOT appear in <header> (it moved to the footer); "
            f"found {len(header_hits)}")
        footer_hits = [a for (tag, a) in _footer_els(path)
                       if tag == "a" and "apilink" in _classes(a)]
        assert len(footer_hits) == 1, (
            f"{path.name}: <footer> must carry exactly one MTCAT apilink (bottom-left); found {len(footer_hits)}")
        # The honest link target + title + visible text must survive the move verbatim.
        assert footer_hits[0].get("href") == "data/mtcat.json", (
            f"{path.name}: the footer MTCAT link must point at data/mtcat.json, got {footer_hits[0].get('href')}")
        title = footer_hits[0].get("title") or ""
        assert title == "MTCAT discovery document (JSON)", (
            f"{path.name}: the footer MTCAT link title must be kept verbatim, got {title!r}")
        assert not re.search(r"\bv?\d+\.\d+\b", title), (
            f"{path.name}: the footer MTCAT link title must not hard-code a schema version (it goes stale "
            f"on every bump, and the served document declares its own), got {title!r}")
        assert "Machine-readable record (MTCAT JSON) ↗" in path.read_text(encoding="utf-8"), (
            f"{path.name}: the verbatim MTCAT link text must be preserved")


class _HeaderShape(HTMLParser):
    """Records the ORDER and nesting of elements inside <header>, so the two pages' headers can be
    compared position-by-position rather than as a bag of classes. Each entry is
    (tag, attrs-dict, in_nav:bool) in document order; in_nav marks the three primary view items, which
    live inside <nav> on both pages."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self._depth = 0        # header nesting depth
        self._nav_at = None    # header-depth at which <nav> opened (None => not inside nav)

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        if self._depth > 0 and tag != "header":
            self.items.append((tag, d, self._nav_at is not None))
        if tag == "header":
            self._depth += 1
        elif self._depth > 0 and tag not in _VOID:
            self._depth += 1
        if self._nav_at is None and tag == "nav":
            self._nav_at = self._depth

    def handle_endtag(self, tag):
        if self._depth > 0 and tag not in _VOID:
            self._depth -= 1
            if self._nav_at is not None and self._depth < self._nav_at:
                self._nav_at = None


def _header_shape(path):
    p = _HeaderShape()
    p.feed(path.read_text(encoding="utf-8"))
    return p.items


def test_header_parity_about_matches_index():
    """Api-docs workflow. About's header must NOT differ from the SPA's in the two visible ways it could: its primary nav
    items carried none of index's ids, and its right zone was empty while index's carried a mono stats
    block. Both are now aligned, and this pins the alignment structurally (parsed DOM, so comments and
    raw-text coincidences cannot pass it).

    Failure criteria:
      * NAV ID ORDER: FAILS if the ids of the elements inside <nav> are not exactly
        [navMap, navSurveys, navCollections], in that order, on BOTH pages. Non-vacuous: before the workflow
        about.html's nav items were bare <a href="index.html"> with no ids at all, so About failed this.
        The TAG is deliberately not compared: index's are <button>s that switch app views in place, About
        is static so its must be links. Ids + order + placement are the parity that matters.
      * CENTRE-ZONE ORDER: FAILS if the five primary items are not in the same order on both pages:
        Map, Surveys, Collections, About, Contribute. It is five, not six: the brief cut
        "How to use AusMT" from every header (the welcome tour and About cover it). The sixth slot is
        pinned SHUT below, so a header that grows a sixth centre item fails here rather than drifting
        back.
      * STATS BLOCK: FAILS if either page's right zone lacks a single .counts element. Non-vacuous: the
        earlier about.html had an empty .hright, so it failed this half.
      * ACTIVE-PAGE HIGHLIGHT NOT REGRESSED: FAILS if adding the ids also made a view button active on
        About (only the current page may be highlighted) or dropped index's active Map button."""
    idx, abt = _header_shape(INDEX), _header_shape(ABOUT)

    nav_ids = {"index.html": [a.get("id") for (tag, a, in_nav) in idx if in_nav and a.get("id")],
               "about.html": [a.get("id") for (tag, a, in_nav) in abt if in_nav and a.get("id")]}
    for name, ids in nav_ids.items():
        assert ids == ["navMap", "navSurveys", "navCollections"], (
            f"{name}: the primary nav must be navMap, navSurveys, navCollections in that order; got {ids}")

    def centre_order(items):
        """The five primary header items in document order, each reduced to a stable label. Anything else
        carrying the .about styling is labelled 'other', which is what fails the pin: it is how a sixth
        header item (the retired How-to-use entry, or a successor to it) shows up here."""
        out = []
        for tag, a, in_nav in items:
            if in_nav and a.get("id") in ("navMap", "navSurveys", "navCollections"):
                out.append(a["id"])
            elif "about" in _classes(a) and a.get("href") == "about.html":
                out.append("about")
            elif "about" in _classes(a):
                out.append("other:" + (a.get("href") or a.get("id") or tag))
            elif "contribute" in _classes(a):
                out.append("contribute")
        return out

    expected = ["navMap", "navSurveys", "navCollections", "about", "contribute"]
    for name, items in (("index.html", idx), ("about.html", abt)):
        assert centre_order(items) == expected, (
            f"{name}: header items must run {expected}; got {centre_order(items)}")

    for name, items in (("index.html", idx), ("about.html", abt)):
        counts = [a for (tag, a, in_nav) in items if "counts" in _classes(a)]
        assert len(counts) == 1, (
            f"{name}: the header must carry exactly one mono stats block (.counts) in its right zone; "
            f"found {len(counts)}")

    # Active-page highlight, both directions: index's Map view stays active; About activates NO view
    # button (its current page is marked on the About link, asserted in
    # test_about_marked_active_and_no_other_center_nav_is).
    idx_active = [a.get("id") for (tag, a, in_nav) in idx if in_nav and "active" in _classes(a)]
    assert idx_active == ["navMap"], f"index.html must still highlight the Map view; active={idx_active}"
    abt_active = [a.get("id") for (tag, a, in_nav) in abt if in_nav and "active" in _classes(a)]
    assert abt_active == [], (
        f"about.html must not highlight a view button (none of them is the current page); active={abt_active}")


def test_no_page_header_keeps_the_retired_how_to_use_entry():
    """The "How to use AusMT" header entry is absent from every page.
    On index it was a <button id="howToUse"> that opened the #introOverlay help panel; on About it was an
    <a href="#howto">, and releases.html arrived on main with an <a href="about.html#howto"> copy of the
    same item. All are pinned absent, by id and by visible text, on all four shipped pages. Non-vacuous:
    run against HTML that still carries the entry, index.html, about.html and releases.html all fail.

    The #howto ANCHOR survives on About (answer 3 keeps that id, so an inbound deep link still lands) and
    is deliberately not what this asserts against; the assertion is about the HEADER entry.

    Comments are stripped before the text check on purpose: both headers carry a comment explaining what
    was removed and why, and a rule that forbids explaining a removal is a rule that loses the reason."""
    for path in (INDEX, ABOUT, ADD, RELEASES):
        raw = path.read_text(encoding="utf-8")
        if "<header>" not in raw:
            continue
        header = raw.split("<header>", 1)[1].split("</header>", 1)[0]
        header = re.sub(r"<!--.*?-->", "", header, flags=re.S)
        assert "How to use AusMT" not in header, (
            f"{path.name}: the 'How to use AusMT' header entry stays out of the header")
        assert 'id="howToUse"' not in raw, (
            f"{path.name}: #howToUse was retired with the help panel it opened")


def test_about_corpus_stats_are_fetched_not_hardcoded():
    """The corpus totals must be READ from the served catalogue, never baked into the HTML, and the block
    must degrade to invisible when the data cannot be read (file://, an unpublished deployment, an empty
    build). FAILS if the block ships visible, if the script that fills it is missing or inlined (the
    deployed CSP for about.html is script-src 'self' with no 'unsafe-inline'), or if a digit is
    hard-coded into the block's markup."""
    raw = ABOUT.read_text(encoding="utf-8")
    assert '<script src="corpus-stats.js"></script>' in raw, (
        "about.html must load corpus-stats.js as an EXTERNAL script (the deployed strict CSP allows no "
        "inline script on this page)")
    assert (ROOT / "corpus-stats.js").exists(), "portal/corpus-stats.js is missing"

    block = [a for (tag, a, inh) in _parse(ABOUT) if "counts" in _classes(a)]
    assert block and "hidden" in block[0], (
        "the corpus-totals block must ship hidden and be revealed only once the data resolves, so a "
        "file:// or unpublished page shows nothing rather than an empty or zero total")

    js = (ROOT / "corpus-stats.js").read_text(encoding="utf-8")
    assert "catalogue.json" in js and "surveys.json" in js, (
        "corpus-stats.js must read the totals from catalogue.json + surveys.json")
    assert ".catch(" in js, "corpus-stats.js must swallow a failed fetch and leave the block hidden"
    # No fabricated number anywhere in the header block markup: the counts spans must be empty in source.
    header_src = raw.split("<header>")[1].split("</header>")[0]
    assert 'id="corpusStations"></b>' in header_src and 'id="corpusSurveys"></b>' in header_src, (
        "the corpus-total spans must be EMPTY in the served HTML: the numbers can only come from the "
        "catalogue at load time, never from a hard-coded value that would silently go stale")


def test_index_still_has_the_count_ids_the_about_guard_forbids():
    # Guards the guard: proves test_about_has_no_live_counts_elements is non-vacuous by confirming the
    # very ids it forbids DO exist on index.html. If index ever drops them this reminds us to re-check
    # what 'no counts' is actually asserting against.
    els = _parse(INDEX)
    ids = {a.get("id") for (tag, a, inh) in els}
    assert {"nVis", "nSel", "nTot"} <= ids, "index.html should still carry the live-count ids (nVis/nSel/nTot)"


def test_no_page_keeps_an_about_this_build_control_in_the_footer():
    """The one-footer rule took Releases and About this build out of the footer on every surface, so
    the disclosure popover goes with them: what a reader saw on opening it was the software licence
    and the build's identity, and about.html carries both in its own body now.

    FAILS if a <details class="aboutbuild"> comes back to any of these four footers. Non-vacuous
    against the pre-rule tree, where all four carried one."""
    for path in (INDEX, ABOUT, ADD, RELEASES):
        els = _footer_els(path)
        details = [a for (tag, a) in els if tag == "details" and "aboutbuild" in _classes(a)]
        assert not details, (
            f"{path.name}: the About-this-build popover is retired from the footer; found "
            f"{len(details)}")


def test_the_build_colophon_is_gone_from_about_and_the_releases_route_survives_it():
    """The colophon's deletion, held from every end it could come back through. The rule is
    that about.html states what AusMT IS, what it licenses and where the documentation lives; the
    running build's identity is not one of those, and a chip that has to be kept in step with a
    config file is a maintenance cost for a fact no reader asked for.

    FAILS if the #build section, its heading, its contents entry or its chip returns, and FAILS in
    the other direction if the deletion took the releases page down with it: releases.html has no
    other route in since the footer gave the link up, so a sentence in section 8 must still point
    at it. The chip pin above covers all four documents; this one covers the section that held it."""
    text = ABOUT.read_text(encoding="utf-8")
    assert '<section id="build">' not in text, (
        "the #build colophon is deleted; about.html carries no running-build section")
    assert "This build" not in text, (
        "the colophon's heading and its contents entry go with the section")
    assert 'href="#build"' not in text, (
        "the contents box must not promise a section the page no longer has")
    assert "data-ver-chip" not in text, "the version chip went with the section that held it"
    assert "You are reading the build" not in text, (
        "the build-identity sentence went with the section that held it")

    docs = text.split('<section id="docs">', 1)
    assert len(docs) == 2, "about.html must carry the Documentation section"
    docs = docs[1].split("</section>", 1)[0]
    assert 'href="releases.html"' in docs, (
        "section 8 must keep the route to the citable releases: the footer gave the link up and the "
        "colophon that inherited it is deleted, so this is the page's one way in")


# ------------------------------------------------- the in-page anchor offset follows the header
#
# about.html is the one chrome surface that SCROLLS under its own header, so it is the one that has
# to clear it: the header is position:sticky;top:0, and an in-page anchor that scrolls its section
# to y=0 puts the heading underneath it. scroll-margin-top is the clearance, and it was ONE number,
# 74px, measured at 1280px and applied at every width.
#
# That number is only right above about 1096px. The header WRAPS as the viewport narrows, in two
# ways at once (the identity block drops its tagline onto a second line, the tab group stacks into
# more rows, and under 760px the three zones each take a full-width row), and it does not shrink
# monotonically: measured on this document in Chrome at a device scale factor of 1, its height runs
# 220px below 388, 147px to 614, 111px to 760, 142px to 872 (the zones stop stacking and the tab
# group takes two rows on a shared line), 104px to 957, 89px to 1095, 74px to 1345 and 57px above
# that. At 375px a 74px clearance left a heading 146px under the header, which is off the screen.
#
# THE LADDER IS THE MAXIMUM PER BAND, NOT THE EXACT HEIGHT. Overshooting drops the heading a few
# pixels lower than it needs to be, which a reader will not notice; undershooting hides it, which is
# the defect. So each band carries the tallest header in its own range, which is why the 615 band
# reads 142px rather than the 111px the header measures at 615 itself.
#
# THE FAILURE MODE OF DRIFT IS STATED because it cannot be pinned from source alone: these are
# measurements of THIS header's content at THIS font stack, and a change to the header's wording or
# its nav will move the wrap points. Anything that changes the header's height must re-measure the
# ladder. What this file CAN hold, and does, is that the offset is a variable rather than a constant,
# that the ladder descends, and that it resolves to the measured header height at the two widths the
# Workflow pins.
ANCHOR_VAR = "--about-anchor-offset"

# The measured header height at each pinned width, from the same run the ladder was built from.
MEASURED_HEADER = {375: 220, 1280: 74}


# EVERY DECLARATION OF THE VARIABLE IS ACCOUNTED FOR, because a reader that matches only the shape
# it expects turns a band it cannot parse into a band that is not there. A browser honours a `2rem`
# band and this module would drop it: the ladder pins below would all pass while a heading landed
# 115px behind the header at 400px. So the declarations are COUNTED first and the count is asserted
# against what the two shapes below recognise; an unparseable value then fails on its own line,
# naming the value, instead of vanishing.
_DECL = re.compile(re.escape(ANCHOR_VAR) + r"\s*:")
_BASE = re.compile(r":root\{\s*" + re.escape(ANCHOR_VAR) + r"\s*:\s*([^;}]+)\}")
_BAND = re.compile(r"@media\s*\(min-width:\s*([^)]+?)\s*\)\s*\{\s*:root\{\s*"
                   + re.escape(ANCHOR_VAR) + r"\s*:\s*([^;}]+)\}\s*\}")


def _px(where, raw):
    """A whole-pixel length, or a loud failure naming what was written instead."""
    m = re.fullmatch(r"(\d+)px", raw.strip())
    assert m, (
        f"{where}: the anchor offset is a clearance measured against the header in device pixels, "
        f"so every value in the ladder is a whole px; got {raw.strip()!r}, which this reader cannot "
        f"compare with a measured header height")
    return int(m.group(1))


def _anchor_ladder(text):
    """The ladder as (min-width, px) pairs in source order, base first at min-width 0."""
    base = _BASE.search(text)
    assert base, "about.html must declare the anchor offset on :root as the base of the ladder"
    bands = _BAND.findall(text)
    declared = len(_DECL.findall(text))
    assert declared == 1 + len(bands), (
        f"about.html declares {ANCHOR_VAR} {declared} time(s) and this reader recognises "
        f"{1 + len(bands)} of them (the :root base and {len(bands)} min-width band(s)); a "
        f"declaration it cannot read would drop out of the ladder silently and leave every pin "
        f"below green while an in-page anchor lands behind the header")
    out = [(0, _px("the :root base", base.group(1)))]
    for width, value in bands:
        out.append((_px(f"the min-width:{width} band's breakpoint", width),
                    _px(f"the min-width:{width} band", value)))
    return out


def _resolve(ladder, width):
    """The value a browser would use at this viewport width: the last matching min-width band."""
    val = ladder[0][1]
    for bp, px in ladder:
        if width >= bp:
            val = px
    return val


def test_the_in_page_anchor_offset_is_a_variable_and_not_one_number():
    """FAILS if the retired static 74px comes back, or if the sections stop reading the ladder.
    One number cannot follow a header that is 220px tall at 375px and 57px tall at 1440px, and the
    direction it is wrong in at the narrow end is the one that hides the heading."""
    text = ABOUT.read_text(encoding="utf-8")
    assert "scroll-margin-top:74px" not in text, (
        "the single-number anchor offset is retired; it was right only above about 1096px")
    assert f"scroll-margin-top:var({ANCHOR_VAR})" in text, (
        "every section's anchor offset must read the ladder rather than a constant")


def test_the_anchor_offset_ladder_descends_and_is_declared_in_px():
    """The ladder's shape. FAILS if a band is out of order, if the base is not the tallest (the
    narrowest viewport has the tallest header), if a band repeats a breakpoint, or if a value stops
    being an absolute length: a percentage or an em here would be measured against something that is
    not the header."""
    ladder = _anchor_ladder(ABOUT.read_text(encoding="utf-8"))
    assert len(ladder) >= 3, f"the ladder must carry a base and at least two bands, got {ladder}"
    widths = [bp for bp, _px in ladder]
    assert widths == sorted(widths) and len(set(widths)) == len(widths), (
        f"the ladder's breakpoints must ascend and not repeat: {widths}")
    values = [px for _bp, px in ladder]
    assert values == sorted(values, reverse=True), (
        f"the offset must shrink as the viewport widens, because the header does: {ladder}")
    assert values[0] == max(values), (
        f"the base band carries the tallest header, at the narrowest viewport: {ladder}")


def test_the_ladder_resolves_to_the_measured_header_height_at_the_pinned_widths():
    """The ladder against the ruler. FAILS if the value a browser would use at 375px or at 1280px is
    smaller than the header measured there: at 375px that is a heading scrolled under 220px of
    header, and the reader sees the section below the one they asked for.

    Held as ">=" and not "==" on purpose, for the reason the ladder is a per-band maximum: a band
    that overshoots is doing its job."""
    ladder = _anchor_ladder(ABOUT.read_text(encoding="utf-8"))
    for width, header in MEASURED_HEADER.items():
        got = _resolve(ladder, width)
        assert got >= header, (
            f"at {width}px the header measures {header}px and the ladder offers {got}px, so an "
            f"in-page anchor lands {header - got}px under it")


def test_every_script_a_page_loads_is_shipped_and_every_page_script_is_loaded():
    """The two directions of one rule, over every document the portal ships.

    A page that loads a script the tree does not carry sends every visitor after a 404, and a
    script the tree carries that no page loads is a file a reader can open and reason about that
    reaches nobody. The second direction is the one that bites: the version chip was deleted from
    every surface, its script stopped being loaded, and the file went on being shipped, pinned and
    read as though a page still used it.

    Read over the page scripts at the top of portal/ and the coastline this repository generates
    into vendor/. Third-party libraries under vendor/ are somebody else's file and are held only by
    the first direction. FAILS in the other direction too if config.js or corpus-stats.js left
    about.html: corpus-stats.js reads AUSMT_CONFIG.data_base_url from config.js to find the
    catalogue the header's totals come from."""
    loaded = {}
    for path in sorted(ROOT.glob("*.html")):
        for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', path.read_text(encoding="utf-8")):
            if "://" in src:
                continue
            loaded.setdefault(src, []).append(path.name)
    assert loaded, "no page loaded a script, so this pin would pass over nothing"
    absent = ["%s (loaded by %s)" % (src, ", ".join(pages))
              for src, pages in sorted(loaded.items()) if not (ROOT / src).exists()]
    assert not absent, (
        "a page loads a script this tree does not ship, so every visitor pays a 404:\n"
        + "\n".join(absent))
    shipped = [p.name for p in sorted(ROOT.glob("*.js"))] + list(AUTHORED_VENDOR_SCRIPTS)
    dead = [name for name in shipped if name not in loaded]
    assert not dead, (
        "a page script is shipped and loaded by no page, so it reaches no reader and no visitor:\n"
        + "\n".join(dead))
    text = ABOUT.read_text(encoding="utf-8")
    assert '<script src="config.js">' in text, (
        "config.js stays: corpus-stats.js reads AUSMT_CONFIG.data_base_url from it")
    assert '<script src="corpus-stats.js">' in text, (
        "the header's corpus totals are filled by corpus-stats.js and must keep their script")


def test_about_api_card_describes_the_geojson_as_the_served_document_it_now_is():
    """API-access honesty.

    This pin was written when NO GeoJSON was generated or served: the only one was the portal's
    in-browser export button (portal/src/exports.js, #dlGeo), so the card was forbidden from claiming
    MTCAT was "served alongside GeoJSON". That premise is dead. The build now emits
    /data/stations.geojson, so the honest description of the card's GeoJSON is exactly the one the old
    wording had to avoid, and the sentence that WAS honest ("an in-browser export for GIS") is the one
    that would now understate what the site serves.

    The rule did not change, only its direction: the card must describe the GeoJSON as what it is
    today. FAILS if the retired in-browser-export wording returns, or if the card stops linking the
    served document. The full dictated copy batch is pinned in tests/test_about_copy_batch.py."""
    text = ABOUT.read_text(encoding="utf-8")
    # Flattened: the retired sentence was line-wrapped in the source, so a raw substring scan for it
    # would pass vacuously against the very page it is meant to catch.
    flat = re.sub(r"\s+", " ", text)
    assert "in-browser export" not in flat, (
        "about.html must not describe GeoJSON as an in-browser export; the build serves "
        "/data/stations.geojson (engine/extract/build_portal.py: stations_geojson)")
    assert "GeoJSON" in flat, "the API card must still tell the GIS/GeoJSON story"
    assert 'href="data/stations.geojson"' in flat, (
        "the API card must link the served GeoJSON document by portal-relative path")


def test_the_about_button_carries_the_contribute_button_treatment_on_every_page():
    """The header's About link wears the same outlined-button style as
    "Contribute a survey", on every page that renders it, so the two header actions read as siblings.
    FAILS IF any page's .about rule drops the border (the old muted borderless style creeping back) or
    the pages drift apart from each other."""
    rules = {}
    for name in ("index.html", "about.html", "releases.html"):
        css = (ROOT / name).read_text(encoding="utf-8")
        m = re.search(r"^\s*\.about\{([^}]*)\}", css, re.M)
        assert m, f"{name} must style the header About link"
        rules[name] = m.group(1)
    assert "border:1px solid" in rules["index.html"], \
        "the About link must be an outlined button like .contribute, not borderless text"
    assert len(set(rules.values())) == 1, \
        f"the .about rule must be byte-identical on every page, got {rules}"
