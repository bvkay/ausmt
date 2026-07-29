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
  * no APP-STATE counts on a static page: FAILS if about.html carries any of index's live-counts ids
    (nVis/nSel/nTot). Those three report the current map's filter and selection state, and About has
    neither. Non-vacuous: index.html HAS these ids, so a naive copy-the-whole-header would trip this.
    NARROWED by the api-docs lane, deliberately: the ban used to extend to the class "counts" as well,
    on the reasoning that a static page has no counts to state. That reasoning covered app state only.
    About now carries a CORPUS-totals block (total stations / total surveys, read from the catalogue at
    load time) in index's right zone, reusing index's .counts styling so the two headers render
    identically (see test_header_parity_about_matches_index). The app-state ids remain banned, which is
    the half of the old assertion that was actually about honesty; the class ban was about styling.
  * one version chip — FAILS if the number of real elements carrying data-ver-chip is not exactly 1
    (must survive the reverse case too: zero chips, or a duplicated chip, both fail).
"""
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
ABOUT = ROOT / "about.html"
INDEX = ROOT / "index.html"
ADD = ROOT / "add-survey.html"
RELEASES = ROOT / "releases.html"


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
    _Collector. Backs the UX6 Wave B (B3) footer-chrome pins: the 'About this build' popover and the
    version chip nested inside it, asserted against the parsed DOM (comments never reach handle_starttag)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []          # (tag, attrs-dict, in_aboutbuild:bool) for elements inside <footer>
        self._depth = 0             # footer nesting depth
        self._ab_at = None          # footer-depth at which a details.aboutbuild opened (None => not inside)

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        if self._depth > 0 and tag != "footer":
            self.elements.append((tag, d, self._ab_at is not None))
        if tag == "footer":
            self._depth += 1
        elif self._depth > 0 and tag not in _VOID:
            self._depth += 1
        # The About-this-build popover region: its DESCENDANTS (recorded above BEFORE this) are inside it.
        if self._ab_at is None and tag == "details" and "aboutbuild" in _classes(d):
            self._ab_at = self._depth

    def handle_endtag(self, tag):
        if self._depth > 0 and tag not in _VOID:
            self._depth -= 1
            if self._ab_at is not None and self._depth < self._ab_at:
                self._ab_at = None


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


def test_about_footer_carries_exactly_one_ver_chip():
    els = _parse(ABOUT)
    chips = [a for (tag, a, inh) in els if "data-ver-chip" in a]
    assert len(chips) == 1, f"about.html must carry exactly one data-ver-chip element; found {len(chips)}"


def test_about_references_no_nonexistent_federation_doc():
    """C22 citation honesty (2026-07-07). FAILS if about.html references FEDERATION.md — no such file
    exists anywhere in the repository (verified repo-wide before this test was written), so the pre-C22
    line 236 ("see the MTCAT v1.0 specification and FEDERATION.md in the project repositories") pointed
    readers at a fabricated document. Chief-architect ruling: REMOVE the claim, do not repoint (federation
    is documented as a property of MTCAT itself, and docs/docs/developer/data-files.md describes
    mtcat.json as the discovery/federation document). UX6 Wave F (#17): the restructured About now DOES link
    docs-site pages (the "Detailed documentation" answer points at real mkdocs pages, incl. the MTCAT page),
    but the fabricated FEDERATION.md filename must still never reappear here — that is what this guards.

    Raw-text check ON PURPOSE (unlike this module's parsed-DOM tests): even a commented-out reference is
    a stale claim waiting to be resurrected, and the parser drops comments. The companion assertion pins
    the HONEST half of the sentence: the spec reference must SURVIVE the removal, so an over-deletion also
    fails here.

    MTCAT 1.2 fix round: the over-deletion pin used to be the literal string "MTCAT v1.0". That was a
    VERSION NUMBER doing a link's job, and it went stale the moment the served schema moved past 1.0 (it
    was already wrong at 1.1). It is now pinned to the docs-site URL the bullet actually links, which is
    what a reader needs and which does not rot on a schema bump. The version a consumer should trust is
    the one the document declares about itself, never a number typed into this page."""
    raw = ABOUT.read_text(encoding="utf-8")
    assert "FEDERATION.md" not in raw, (
        "about.html must not reference FEDERATION.md — that file does not exist in the repository")
    assert "https://ausmt.readthedocs.io/en/latest/data-model/mtcat/" in raw, (
        "the honest MTCAT specification reference must survive the FEDERATION.md removal (over-deletion)")
    assert "MTCAT v1.0" not in raw, (
        "about.html must not hard-code an MTCAT version that the served schema has moved past; the "
        "document declares its own version and version.js renders it from config")


def test_mtcat_link_in_footer_not_header_across_pages():
    """UX7a (A5). The machine-readable MTCAT link moved from the header's right zone into the footer's
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
    reader needs is already on screen: version.js renders the data-ver-chip from config.js, whose
    schema_version is generated from portal.config.yaml."""
    for path in (INDEX, ABOUT, ADD):
        header_hits = [a for (tag, a, inh) in _parse(path)
                       if tag == "a" and inh and "apilink" in _classes(a)]
        assert not header_hits, (
            f"{path.name}: the MTCAT apilink must NOT appear in <header> (it moved to the footer); "
            f"found {len(header_hits)}")
        footer_hits = [a for (tag, a, _ab) in _footer_els(path)
                       if tag == "a" and "apilink" in _classes(a)]
        assert len(footer_hits) == 1, (
            f"{path.name}: <footer> must carry exactly one MTCAT apilink (bottom-left); found {len(footer_hits)}")
        # The honest Wave-A link target + title + visible text must survive the move verbatim.
        assert footer_hits[0].get("href") == "data/mtcat.json", (
            f"{path.name}: the footer MTCAT link must point at data/mtcat.json, got {footer_hits[0].get('href')}")
        title = footer_hits[0].get("title") or ""
        assert title == "MTCAT discovery document (JSON)", (
            f"{path.name}: the footer MTCAT link title must be kept verbatim, got {title!r}")
        assert not re.search(r"\bv?\d+\.\d+\b", title), (
            f"{path.name}: the footer MTCAT link title must not hard-code a schema version (it goes stale "
            f"on every bump; the data-ver-chip already renders the live one), got {title!r}")
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
    """api-docs lane. About's header used to differ from the SPA's in two visible ways: its primary nav
    items carried none of index's ids, and its right zone was empty while index's carried a mono stats
    block. Both are now aligned, and this pins the alignment structurally (parsed DOM, so comments and
    raw-text coincidences cannot pass it).

    Failure criteria:
      * NAV ID ORDER: FAILS if the ids of the elements inside <nav> are not exactly
        [navMap, navSurveys, navCollections], in that order, on BOTH pages. Non-vacuous: before the lane
        about.html's nav items were bare <a href="index.html"> with no ids at all, so About failed this.
        The TAG is deliberately not compared: index's are <button>s that switch app views in place, About
        is static so its must be links. Ids + order + placement are the parity that matters.
      * CENTRE-ZONE ORDER: FAILS if the five primary items are not in the same order on both pages:
        Map, Surveys, Collections, About, Contribute. It was six until the docs wave, when the owner cut
        "How to use AusMT" from every header (the welcome tour and About cover it). The sixth slot is
        pinned SHUT below, so a header that grows a sixth centre item fails here rather than drifting
        back.
      * STATS BLOCK: FAILS if either page's right zone lacks a single .counts element. Non-vacuous: the
        pre-lane about.html had an empty .hright, so it failed this half.
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
    """Docs wave, stage 2 (owner ruling): the "How to use AusMT" header entry is gone from every page.
    On index it was a <button id="howToUse"> that opened the #introOverlay help panel; on About it was an
    <a href="#howto">, and releases.html arrived on main with an <a href="about.html#howto"> copy of the
    same item. All are pinned absent, by id and by visible text, on all four shipped pages. Non-vacuous:
    run against the pre-wave HTML, index.html, about.html and releases.html all fail.

    The #howto ANCHOR survives on About (answer 2 keeps that id, so an inbound deep link still lands) and
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
            f"{path.name}: the 'How to use AusMT' header entry was retired in the docs wave")
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


def test_footer_about_this_build_control_uniform_across_pages():
    """UX6 Wave B (B3). FAILS if either the app page (index) or the static About page lacks the trimmed
    footer's 'About this build' popover — a <details class="aboutbuild"> with a <summary> control — inside
    <footer>. This is the NEW chrome, asserted identically across pages. Non-vacuous: the pre-wave footer
    was flat text with no <details>, so both pages would fail here on the old chrome."""
    for path in (INDEX, ABOUT):
        els = _footer_els(path)
        details = [a for (tag, a, _ab) in els if tag == "details" and "aboutbuild" in _classes(a)]
        assert len(details) == 1, (
            f"{path.name}: footer must carry exactly one <details class='aboutbuild'> (the "
            f"'About this build' popover); found {len(details)}")
        assert any(tag == "summary" for (tag, a, _ab) in els), (
            f"{path.name}: the About-this-build popover needs a <summary> control to open it")


def test_footer_version_chip_relocated_inside_about_this_build_across_pages():
    """UX6 Wave B (B3). The version chip is RELOCATED into the footer's About-this-build popover on both
    pages. FAILS if the single [data-ver-chip] is not NESTED inside <details class='aboutbuild'> (e.g.
    still floating in the visible footer line, left in the header, or dropped). Non-vacuous: the pre-wave
    chip sat directly in the footer, NOT inside any popover, so this fails on the old chrome."""
    for path in (INDEX, ABOUT):
        els = _footer_els(path)
        chips = [(a, in_ab) for (tag, a, in_ab) in els if "data-ver-chip" in a]
        assert len(chips) == 1, (
            f"{path.name}: exactly one version chip must live inside <footer>; found {len(chips)}")
        assert chips[0][1], (
            f"{path.name}: the version chip must be nested inside the About-this-build popover "
            f"(<details class='aboutbuild'>), not floating in the visible footer line")


def test_about_api_card_makes_no_served_geojson_claim():
    """API-access honesty (feat/api-cors-geojson-honesty). The About API card must NOT claim MTCAT is
    "served alongside GeoJSON": no GeoJSON file is generated or served — the only GeoJSON is the portal's
    in-browser export button (portal/src/exports.js, #dlGeo). FAILS if the false served-GeoJSON claim
    reappears. Non-vacuous: the pre-fix card carried exactly that phrase."""
    text = ABOUT.read_text(encoding="utf-8")
    assert "served alongside GeoJSON" not in text, (
        "about.html must not claim MTCAT is 'served alongside GeoJSON' — no GeoJSON is served; the only "
        "GeoJSON is the portal's in-browser export (src/exports.js)")
    # The card still tells the GIS/GeoJSON story, just truthfully (an in-browser export).
    assert "GeoJSON" in text, "the API card should still mention GeoJSON (as the in-browser export for GIS)"
