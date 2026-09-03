"""About-page copy batch (owner dictation, 2026-08-02) render pins.

The owner dictated nine changes to portal/about.html in one pass. Three of them make the page say
something NEW and factual, and those are the ones that can rot:

  * the raw-time-series sentence now LINKS the NCI-AuScope MT collection instead of naming it in
    passing, and the DOI it links is pinned against src/state.js's TS_COLLECTION, which is the single
    place that identifier is declared;
  * the API-access card now says stations are SERVED as GeoJSON. That claim is true only because the
    build emits the document, so it is pinned against build_portal.py's emitter and against the path
    the page actually links;
  * the access-level list now enumerates the three levels one per line, and the set it enumerates is
    pinned against the emitter's ACCESS_LEVELS tuple, so a fourth level cannot appear in the engine
    while About keeps telling readers there are three.

The rest are removals and rewordings. Each is pinned in BOTH directions: the retired sentence must be
gone, and the sentence that replaced it must be present, so neither a revert nor an over-delete can
pass. Parsed structurally where structure is the claim (section 1 ending on the card, section 7 down
to a single link, the acknowledgement being one copyable line), and by exact string where the exact
words are the owner's.

A SECOND OWNER BATCH follows it at the foot of this module. That one adds a section rather than
editing one, so the page's SHAPE is pinned with the words: eight numbered answers in a fixed order,
the colophon after them, and a contents box that lists exactly those sections in exactly that order.
A renumbering that leaves the contents box behind is the failure that shape exists to catch.

NOT COVERED HERE (deliberately, and pinned elsewhere): the #api section and its machine-contract
paragraph, which neither batch touches (tests/test_api_docs_section.py,
tests/test_mtcat_machine_contract.py).
"""
import ast
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
REPO = ROOT.parent
ABOUT = ROOT / "about.html"
STATE_JS = ROOT / "src" / "state.js"
BUILDER = REPO / "engine" / "extract" / "build_portal.py"
PAGES_PY = REPO / "engine" / "extract" / "_pages.py"

RAW = ABOUT.read_text(encoding="utf-8")
FLAT = re.sub(r"\s+", " ", RAW)


def _section(sid):
    """The raw HTML of <section id="sid">, opening tag excluded, first </section> as the close.

    about.html nests no <section> inside a <section>, so the first close is the right one; if that
    ever stops being true this helper returns too little and the pins below fail loudly rather than
    silently asserting against a fragment."""
    head = RAW.split(f'<section id="{sid}">', 1)
    assert len(head) == 2, f"about.html lost its #{sid} section"
    body = head[1].split("</section>", 1)
    assert len(body) == 2, f"about.html's #{sid} section is unterminated"
    assert "<section" not in body[0], f"#{sid} unexpectedly nests a section; this helper would truncate"
    return body[0]


def _flat(s):
    return re.sub(r"\s+", " ", s)


class _Links(HTMLParser):
    """(href, link text) pairs in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict((k, v or "") for k, v in attrs).get("href", "")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, _flat("".join(self._text)).strip()))
            self._href = None


def _links(html):
    p = _Links()
    p.feed(html)
    return p.links


# ---------------------------------------------------------------- (a) the collection is a link now


def test_the_raw_timeseries_archive_is_named_by_link_not_in_passing():
    """FAILS if the third paragraph of section 1 still names the collection as plain text, or if the
    link is not there. 'usually the NCI-AuScope MT collection' overstated a single archive as the
    default; 'such as' makes it an example, and the link makes it findable."""
    what = _flat(_section("what"))
    assert "usually the NCI-AuScope MT collection" not in what, (
        "the raw-time-series sentence must no longer name one archive as the usual case")
    assert "it links to the archive that holds them, such as the" in what, (
        "the sentence must read 'such as the <linked collection>'")
    assert ("https://doi.org/10.25914/mtjg-jp22", "NCI-AuScope MT collection") in _links(_section("what")), (
        "the NCI-AuScope MT collection must be an anchor on its collection DOI")


def test_the_linked_collection_doi_is_the_one_the_portal_code_declares():
    """Non-vacuity + anti-rot: the DOI in About's link is the SAME identifier src/state.js declares as
    TS_COLLECTION.doi (the deployment-wide raw-time-series collection). FAILS if either moves without
    the other, which is exactly how a hard-coded link in a static page goes stale."""
    m = re.search(r'TS_COLLECTION\s*=\s*\{\s*doi\s*:\s*"([^"]+)"', STATE_JS.read_text(encoding="utf-8"))
    assert m, "src/state.js must declare TS_COLLECTION.doi"
    assert m.group(1) in FLAT, (
        f"about.html links a collection DOI that state.js does not declare (state.js: {m.group(1)})")


# ---------------------------------------------------------------- (b) section 1 ends on the card


def test_section_one_ends_on_the_in_the_catalogue_card():
    """The closing 'Unknown values are shown as ... Scientific Philosophy' paragraph is deleted, so
    the section ends after the card. FAILS if the paragraph comes back, or if the deletion took the
    card with it."""
    what = _section("what")
    assert "Unknown values are shown" not in what, "the retired 'unknown values' paragraph is back"
    assert "Scientific Philosophy" not in what, "the retired Scientific Philosophy link is back"
    assert "scientific-philosophy" not in RAW, (
        "no page-level link to Scientific Philosophy should survive this deletion")
    assert '<div class="card in">' in what and "<h3>In the catalogue</h3>" in what, (
        "the deletion must not take the In-the-catalogue card with it")
    assert what.rstrip().endswith("</div>"), (
        "section 1 must now END on the In-the-catalogue card, not on a paragraph")


# ---------------------------------------------------------------- (c) the Contribute card


def test_the_contribute_card_states_the_formats_and_the_review():
    """The card body is replaced wholesale. FAILS if the old browser-side-validation pitch survives or
    if the new two-sentence body is not rendered word for word.

    POLICY NOTE (reported to the owner, deliberately NOT resolved here): the card names three
    submission input formats. gateway-side, EMTF XML is curator-enabled per submission rather than
    universally accepted, so this wording is ahead of the validator. The owner dictated the wording;
    the reconciliation (validator opens EMTF XML, or the card narrows) is an owner decision and this
    pin will fail the day the card is narrowed, which is the point."""
    howto = _flat(_section("howto"))
    for retired in ("Package and submit your EDIs with guided validation",
                    "Your files never leave your machine until you submit",
                    "Local checks are advisory"):
        assert retired not in howto, f"the retired Contribute-card copy is back: {retired!r}"
    assert ("Submit your survey's transfer functions (EDI, EMTF XML or MTH5). AusMT curators review "
            "every submission before it becomes public.") in howto, (
        "the Contribute card must carry the dictated two-sentence body verbatim")


# ---------------------------------------------------------------- (d) the API-access card


def test_the_api_card_leads_with_mtcat_and_points_at_the_served_geojson():
    """The card no longer opens on 'Machine-readable catalogue exports for GIS and scripts' (a label,
    not a fact), and no longer describes GeoJSON as an in-browser export, because the build now SERVES
    one. FAILS on a revert to either."""
    howto = _flat(_section("howto"))
    assert "Machine-readable catalogue exports for GIS and scripts" not in howto, (
        "the retired API-card lead sentence is back")
    assert "in-browser export" not in howto, (
        "GeoJSON is a served document now, not an in-browser export; the old claim must not return")
    assert ("<b>MTCAT is AusMT's machine-readable catalogue format, one JSON file describing every "
            "survey</b>") in howto, "the API card must lead with the MTCAT sentence"
    assert "Stations are also served as" in howto and "for GIS use" in howto, (
        "the API card must say the stations are SERVED as GeoJSON")
    hrefs = [h for (h, _t) in _links(_section("howto"))]
    assert "data/stations.geojson" in hrefs, (
        "the served-GeoJSON claim must link the document, by portal-relative path")
    assert "#api" in hrefs, (
        "the API card must keep its link into the Fetching-data-via-API section "
        "(pinned by tests/test_api_docs_section.py too)")


def test_the_served_geojson_claim_is_backed_by_the_emitter():
    """Non-vacuity: About may only claim a document the build actually writes. FAILS if the emitter or
    its write site disappears, which would turn this card into the false claim the previous wording was
    retired for making."""
    src = BUILDER.read_text(encoding="utf-8")
    assert "def stations_geojson(" in src, "the build must define the stations GeoJSON emitter"
    assert '(out / "stations.geojson").write_text' in src, (
        "the build must actually serve stations.geojson at the data root About links")


# ---------------------------------------------------------------- (e) the three access levels


def test_the_access_levels_are_enumerated_one_per_line():
    """The run-on access paragraph becomes a lead-in, a three-item list and a closing paragraph.
    FAILS if the old paragraph returns, or if any level's dictated body is missing."""
    access = _section("access")
    flat = _flat(access)
    assert "Access is one of three levels." not in flat, "the retired run-on access paragraph is back"
    assert "Every survey carries one of three access levels:" in flat, (
        "the access list needs its dictated lead-in")
    for body in ("<code>open</code>: the record and the data files are both served.",
                 "<code>metadata_only</code>: the record is served; the files are not distributed.",
                 "<code>embargoed</code>: the record is served; the files are withheld until the "
                 "custodian lifts the embargo."):
        assert body in flat, f"the access list is missing its dictated row: {body!r}"
    assert flat.count("<li>") >= 3, "the three levels must be list items, not a paragraph"


def test_the_documented_levels_are_exactly_the_levels_the_engine_emits():
    """Non-vacuity + anti-rot: the set About enumerates equals build_portal.py's ACCESS_LEVELS. FAILS
    if the engine gains or renames a level while the page keeps saying there are three."""
    m = re.search(r"^ACCESS_LEVELS\s*=\s*\(([^)]*)\)", BUILDER.read_text(encoding="utf-8"), re.M)
    assert m, "build_portal.py must declare ACCESS_LEVELS"
    levels = set(re.findall(r'"([^"]+)"', m.group(1)))
    documented = set(re.findall(r"<code>([a-z_]+)</code>", _section("access")))
    assert levels <= documented, (
        f"About must document every access level the engine emits; missing {sorted(levels - documented)}")
    assert (documented & {"open", "metadata_only", "embargoed", "restricted", "closed",
                          "public", "private", "legacy"}) == levels, (
        f"About documents a level the engine does not emit: {sorted(documented - levels)}")


def test_the_unrecognised_level_and_the_embargo_posture_are_stated():
    """The closing paragraph carries three facts a reader acts on: an unrecognised level is treated as
    closed, an embargo never hides discovery, and a generalised position is rounded. FAILS if the
    rewrite dropped any of them."""
    flat = _flat(_section("access"))
    assert "Anything AusMT does not recognise is treated as closed." in flat, (
        "the fail-closed posture must survive the rewrite")
    assert "An embargo never hides discovery" in flat and "its footprint on the map" in flat, (
        "the embargo-keeps-discovery fact must survive the rewrite")
    assert "a withheld position is served without coordinates" in flat, (
        "the withheld-coordinate posture must survive the rewrite")
    assert "rounded to a 0.1 degree cell" in flat, (
        "the generalisation cell size must survive the rewrite")


# ---------------------------------------------------------------- (f) governance without takedown


def test_the_governance_sentence_drops_the_takedown_mention():
    """FAILS if 'takedown' reappears anywhere on the page, or if the correction route and the
    Governance link were lost with it."""
    assert "takedown" not in RAW, "about.html must no longer mention a takedown route"
    flat = _flat(_section("access"))
    assert "how to request a correction" in flat, "the correction route must survive"
    assert "introduction/governance/" in flat, "the Governance & Operation link must survive"


# ---------------------------------------------------------------- (g) the acknowledgement


def test_the_citation_placement_advice_and_the_copyable_acknowledgement():
    """Section 4 gains a placement paragraph and a copyable acknowledgement line. FAILS if either is
    missing, and (structurally) if the acknowledgement is broken across lines: it sits in a <pre>, so a
    newline inside it is a newline the reader copies."""
    cite = _section("cite")
    flat = _flat(cite)
    assert "the data availability or methods section is the usual home" in flat, (
        "the placement advice must name where a citation usually goes")
    assert "lands in your reference list, not only in the text" in flat, (
        "the placement advice must ask for the reference-list entry, which is the part people skip")
    assert "Please also acknowledge AusMT:" in flat, "the acknowledgement must be introduced"
    m = re.search(r'<pre class="code">(.*?)</pre>', cite, re.S)
    assert m, "the acknowledgement must be a copyable <pre class=\"code\"> block"
    ack = m.group(1)
    assert "\n" not in ack, (
        "the acknowledgement is copied verbatim out of a <pre>, so it must be a single line")
    assert ack == ACKNOWLEDGEMENT, (
        f"the acknowledgement must read exactly as dictated, got: {ack!r}")


# ---------------------------------------------------------------- (h) the submission section


def test_the_submission_section_drops_the_browser_side_reassurances():
    """Two sentences go: the in-your-browser reassurance (the add-survey page says it where it is
    actionable) and the local-checks-versus-pipeline hedge. FAILS on a revert, and the retained pins
    FAIL if the deletion left a stub section behind."""
    contribute = _section("contribute")
    flat = _flat(contribute)
    for retired in ("Everything runs in your browser and nothing is sent anywhere until you press submit",
                    "The checks in the page are there to save you a round trip",
                    "the pipeline result is the one that counts"):
        assert retired not in flat, f"the retired submission copy is back: {retired!r}"
    assert "Bring your EDI, EMTF XML or MTH5 transfer functions to the" in flat, (
        "the section must still open by pointing at the Contribute page")
    assert "walks you through the metadata AusMT needs." in flat, (
        "the surviving first paragraph must still end on a whole sentence")
    assert "the gateway runs the AusMT validator over the package and a curator reviews it" in flat, (
        "the curator-review fact must survive")
    assert "operations/submission/" in flat, "the Submission Workflow link must survive"
    assert flat.count("<p>") == 2, (
        f"the section must still be two whole paragraphs, found {flat.count('<p>')}")


# ---------------------------------------------------------------- (i) documentation, one line


def test_the_documentation_section_is_two_pointers_and_no_list():
    """The five-bullet topic list is retired: it duplicated the documentation site's own navigation and
    went stale every time a page was renamed. FAILS if a list comes back, or if the dictated sentence
    is not the one there.

    IT IS TWO POINTERS NOW, not one. The section took in the route to the citable releases when the
    #build colophon that had inherited it from the footer was deleted; that page has no other way in
    from the site. The pin still holds the link set EXACTLY and in order, so a third pointer, or
    either of these two moving, still fails here."""
    docs = _section("docs")
    flat = _flat(docs)
    assert "<ul>" not in flat and "<li>" not in flat, (
        "the Documentation section must carry no list; it is a pair of pointers now")
    assert ("<p>For further information, see the" in flat
            and "AusMT documentation</a>.</p>" in flat), (
        "the Documentation section must carry the dictated documentation sentence")
    links = _links(docs)
    assert links == [("https://ausmt.readthedocs.io/en/latest/", "AusMT documentation"),
                     ("releases.html", "releases page")], (
        f"the Documentation section must carry the documentation root then the releases page, got {links}")
    for retired in ("Standards", "Survey Package", "Download Manifest Schema", "Glossary"):
        assert retired not in flat, f"the retired topic bullet is back: {retired!r}"


# ------------------------------------------- (j) the raw-time-series sentence (THREDDS A7)


def test_section_one_states_the_hand_off_beside_the_no_hosting_claim():
    """The "About this build" popover said only that AusMT doesn't host raw time series. That was the
    WHOLE story until a verified per-station route existed; it is now half of one, and a reader who
    stops there concludes the portal cannot help them get the files. FAILS in both directions: the
    no-hosting claim must survive verbatim (a 302 is not hosting, and this lane never claims it is),
    and the hand-off half must be there beside it.

    THE SENTENCE HAS MOVED TWICE and the pin has followed it both times, which is the point of
    holding it by its section. It left the footer's popover for about.html's #build section under the
    one-footer ruling; the owner has now deleted that section, and the two claims are not build
    identity, so they land in section 1, which is where a reader asks what AusMT is. Same two claims,
    read from the section that carries them now."""
    flat = _flat(_section("what"))
    assert "It doesn't host raw time series" in flat, (
        "the no-hosting claim must survive: AusMT hands off, it does not host, and a redirect is not hosting")
    assert "routes you straight to the archive that does" in flat, (
        "the section must state the hand-off beside the no-hosting claim, or it reads as a dead end")
    assert "hosts raw time series" not in flat.replace("doesn't host raw time series", ""), (
        "nothing here may claim AusMT hosts time series")


def test_the_software_licence_sentence_lives_in_the_licence_section():
    """The colophon's other non-identity paragraph. It is about what is licensed and under what, so
    it belongs with the rest of that answer rather than in a build note at the foot of the page.
    FAILS if it is missing from section 4, and FAILS if it turns up anywhere else on the page:
    a licence stated twice is two things to keep in step.

    THE SELF-REFERENCE IS DROPPED, DELIBERATELY. The sentence carried "(see Licence and access)"
    while it sat in the colophon. It now sits IN Licence and access, so that parenthetical would be
    a link from a section to itself; the claim survives, the pointer to where the claim already is
    does not."""
    access = _flat(_section("access"))
    assert "The portal software is licensed under Apache-2.0." in access, (
        "section 4 must carry the software-licence sentence the colophon gave up")
    assert "Survey data stays licensed by its custodians." in access, (
        "the custodian half of the sentence must survive the move with it")
    assert 'href="#access"' not in _section("access"), (
        "the relocated sentence must not link the section it now lives in")
    for sid, _h in NUMBERED:
        if sid == "access":
            continue
        assert "The portal software is licensed under Apache-2.0." not in _flat(_section(sid)), (
            f"the software-licence sentence belongs to section 4 alone; found a copy in #{sid}")


def test_section_eight_keeps_the_only_route_to_the_releases_page():
    """releases.html has no other way in. The Releases link left every footer with the one-footer
    ruling and the colophon that inherited it is now deleted, so a page of citable snapshots would
    be unreachable from the site unless the Documentation section carried the route.

    FAILS if the sentence or its link is missing, and FAILS if it grows a version chip: the route is
    what section 8 inherited, not the running build's identity, which the owner ruled off the page."""
    docs = _section("docs")
    assert 'href="releases.html"' in docs, (
        "section 8 must link releases.html; it is the page's one entry point")
    flat = _flat(re.sub(r"<[^>]+>", "", docs))
    assert ("Quarterly citable snapshots of the corpus are listed on the releases page; each one is "
            "a frozen tree with its own identifier") in flat, (
        "section 8 must say what the releases page holds, in the words the ruling gives")
    assert "data-ver-chip" not in docs, (
        "section 8 inherited the route, not the chip")


# ============================================================ the second owner batch (2026-09-03)
#
# The page gains a section rather than losing one, so what it needs held is its SHAPE as well as its
# words: a reader who follows contents entry N expects heading N, and a renumbering that leaves the
# contents box behind is silent on the page and obvious to the reader.

# The page in order: eight numbered answers, then the colophon. The number is part of the heading a
# reader sees and part of what the contents box promises, so it is pinned WITH the title rather than
# beside it.
#
# The page is eight sections and nothing else. "This build" used to close it WITHOUT a number, as a
# colophon rather than a ninth answer to "what is this site"; the owner has deleted it. Its two
# paragraphs that were not build identity moved into the numbered sections that own their subjects,
# and the route to the citable releases moved into section 8, so nothing the colophon carried is
# lost except the running build's identity, which is what the owner ruled out.
NUMBERED = [
    ("what", "1 \u00b7 What AusMT is"),
    ("who", "2 \u00b7 Who enables AusMT"),
    ("howto", "3 \u00b7 What you can do here"),
    ("access", "4 \u00b7 Licence and access"),
    ("cite", "5 \u00b7 Citing and credit"),
    ("contribute", "6 \u00b7 Contributing a survey"),
    ("api", "7 \u00b7 Fetching data via API"),
    ("docs", "8 \u00b7 Documentation"),
]
# The lede, carried three times and identically: the page's own subtitle, the meta description and
# og:description. tests/test_page_metadata.py holds the description to being the lede; this holds
# what the lede says.
LEDE = ("Australia's national discovery and access portal for magnetotelluric data, connecting "
        "transfer functions with their provenance, licences, citations and source archives.")

# The acknowledgement a reader copies. It is the AusMT access statement, and there is exactly one of
# it: the engine prints the same sentence on every survey page, held equal in
# test_the_page_and_the_engine_print_one_acknowledgement.
ACKNOWLEDGEMENT = (
    "Magnetotelluric transfer functions were accessed through AusMT, Australia's Magnetotelluric "
    "Data Portal (https://ausmt.auscope.org.au), enabled by AuScope and the Australian Government "
    "via the National Collaborative Research Infrastructure Strategy (NCRIS).")

LOCKUP_SRC = "/vendor/auscope-ncris-white.png"
LOCKUP_ALT = "AuScope and NCRIS"


def _sections():
    """(id, heading text) for every top-level section, in document order. The heading is taken as a
    reader sees it: tags stripped, entities resolved, spaces collapsed."""
    out = []
    for sid, body in re.findall(r'<section id="([^"]+)">(.*?)</section>', RAW, re.S):
        m = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S)
        assert m, f"about.html's #{sid} section carries no h2"
        out.append((sid, _flat(re.sub(r"<[^>]+>", "", m.group(1))).strip()))
    return out


def test_the_page_is_exactly_eight_numbered_sections():
    """The page's shape, id and heading together, in document order. FAILS IF a section is added,
    removed, reordered, renamed or renumbered without the rest of the page following it: the numbers
    are consecutive by construction here, because they are pinned inside the heading strings rather
    than derived from them, so a page that inserts an answer and forgets to renumber the ones after
    it fails on the first heading that moved. FAILS too if the deleted colophon returns as a ninth
    section, numbered or not: the list is the whole page and not a prefix of it."""
    got = _sections()
    assert got == NUMBERED, (
        "about.html's sections have drifted from the ruled order:\n"
        + "".join(f"  want {w!r}\n  got  {g!r}\n"
                 for w, g in zip(NUMBERED, got + [None] * 9)
                 if w != g))


def test_the_contents_box_lists_every_section_in_order():
    """The contents box is a promise about the page below it. FAILS IF it names a section that is
    not there, omits one that is, or lists them in a different order from the document: a reader who
    follows entry N and lands on a different heading has been told the page is something it is not.

    The entry TEXT is deliberately not compared with the heading: the box abbreviates on purpose
    ("Contributing" for "6 Contributing a survey"), which is a contents box doing its job. What must
    match is the set, the order and that every entry says something."""
    box = RAW.split('<div class="toc">', 1)
    assert len(box) == 2, "about.html must carry a contents box"
    entries = _links(box[1].split("</div>", 1)[0])
    want = [f"#{sid}" for sid, _h in _sections()]
    assert [h for h, _t in entries] == want, (
        f"the contents box must list every section once, in document order: want {want}, "
        f"got {[h for h, _t in entries]}")
    assert all(text for _h, text in entries), (
        f"every contents entry must carry visible text, got {entries}")


def test_the_lede_says_what_the_portal_is_for():
    """The subtitle is rewritten from a description of a CATALOGUE to one of a PORTAL: what a reader
    can do here, and what the transfer functions are connected to. FAILS on a revert, and FAILS if
    the three places that carry the lede stop carrying the same words (the head's two meta tags are
    copies of it, and a description nobody maintains is the defect
    tests/test_page_metadata.py exists to prevent)."""
    assert "A national catalogue of Australian magnetotelluric transfer functions" not in FLAT, (
        "the retired catalogue lede is back")
    assert FLAT.count(LEDE) == 3, (
        "the lede must be carried three times and identically, as the page's own subtitle, the "
        f"meta description and og:description; found {FLAT.count(LEDE)}")


def test_the_transfer_function_sentence_says_what_it_is_derived_from():
    """A reader who does not already know what a transfer function is learns it here, and the
    replacement says where the estimate comes from rather than only what it is not. FAILS on a
    revert to the instrument-independence wording, which described the property and never the
    measurement."""
    what = _flat(_section("what"))
    assert "the processed, instrument-independent response of the Earth at" not in what, (
        "the retired instrument-independence sentence is back")
    assert ("A magnetotelluric transfer function is a processed estimate of the Earth's "
            "electromagnetic response at a site, derived from measured electric and magnetic field "
            "variations.") in what, "the dictated transfer-function sentence is missing"


def test_section_two_states_who_enables_ausmt():
    """The new section's prose, in the dictated order: who enables AusMT and through which national
    programme, then what each of the two organisations provides. FAILS if either sentence is
    missing or reworded. The page said AusMT was AuScope-funded in one line of a citation block and
    nowhere else; this is the section that states the relationship as a fact about the service."""
    flat = _flat(_section("who"))
    assert ("AusMT is enabled by AuScope and the Australian Government via the National "
            "Collaborative Research Infrastructure Strategy (NCRIS).") in flat, (
        "section 2 must open on who enables AusMT and through which programme")
    assert ("AuScope is Australia's national provider of research infrastructure for the geoscience "
            "community. AusMT provides national digital research infrastructure for discovering, "
            "accessing and reusing Australian magnetotelluric data and its provenance.") in flat, (
        "section 2 must say what each of the two provides")
    assert "Learn more about" in flat, "section 2 must offer the route to AuScope's own site"
    assert ("https://www.auscope.org.au", "AuScope") in _links(_section("who")), (
        "the route to AuScope must be an anchor on the organisation's name")


# HOW EVERY OUTBOUND ANCHOR TO AuScope OPENS, as ONE literal in ONE order. It is the spelling
# tests/test_footer_regions.py holds on the two footer anchors across six documents and the engine's
# emitter; section 2's link is the site's third and last one, and three spellings of the same rule
# is how one of them silently loses half of it.
NEW_TAB = 'target="_blank" rel="noopener noreferrer"'


def test_the_route_to_auscope_opens_the_way_every_other_auscope_link_does():
    """The owner's new-tab ruling reaches this anchor too. FAILS if section 2's link to AuScope
    loses target="_blank" or rel="noopener noreferrer", or spells the pair in a different order from
    the footer's.

    BOTH HALVES MATTER AND FOR DIFFERENT REASONS. target="_blank" keeps the reader's place in the
    catalogue rather than navigating the page out from under them, which is the ruling. rel is what
    makes that safe: without noopener the opened document gets window.opener and can navigate this
    tab to a look-alike, and without noreferrer the reader's path through the catalogue leaks to a
    third party. The anchor carried rel alone, which is the half that is useless on its own: rel
    guards a new tab, and there was no new tab."""
    who = _section("who")
    m = re.search(r'<a[^>]*href="https://www\.auscope\.org\.au"[^>]*>', who)
    assert m, f"section 2 must carry the anchor to AuScope's own site: {_flat(who)[:300]!r}"
    tag = m.group(0)
    assert NEW_TAB in tag, (
        f"section 2's AuScope link must open in a new tab with the same pair every other outbound "
        f"AuScope anchor on this site carries, spelled {NEW_TAB!r}; got {tag!r}")


def test_no_auscope_anchor_on_this_page_is_left_half_paired():
    """The guard over the pin above and over the footer's own: a page-wide sweep, so a fourth
    AuScope anchor arriving anywhere on About cannot be the one that carries a bare rel or a bare
    target. FAILS if any anchor on this page reaching auscope.org.au is missing either half."""
    hits = re.findall(r'<a[^>]*href="https://www\.auscope\.org\.au"[^>]*>', RAW)
    assert hits, "about.html must carry at least one anchor to AuScope"
    for tag in hits:
        assert NEW_TAB in tag, (
            f"every auscope.org.au anchor on about.html opens in a new tab with the full pair; "
            f"got {tag!r}")


def test_section_two_carries_the_official_lockup_the_footer_already_ships():
    """The lock-up in the body is the SAME committed file every footer on this site carries, named
    by the same root-relative path. FAILS if it points at a second copy or at a different artwork
    (two files are two things to keep in step, and the official mark is not ours to redraw), if it
    loses the alt text, or if it drops the intrinsic size attributes that reserve its box before it
    loads.

    The width is capped in the page rather than in the file: the committed raster is 1919px wide, so
    without a cap the mark would be five times the reading column. max-width:100% is what keeps it
    inside a narrow column once the declared width no longer fits."""
    who = _section("who")
    m = re.search(r'<img class="orglockup"[^>]*>', who)
    assert m, "section 2 must carry the AuScope-NCRIS lock-up"
    tag = m.group(0)
    assert f'src="{LOCKUP_SRC}"' in tag, (
        f"the body lock-up must name the committed file at {LOCKUP_SRC}, got {tag!r}")
    assert f'alt="{LOCKUP_ALT}"' in tag, f"the lock-up must carry its alt text, got {tag!r}"
    assert 'width="1919" height="325"' in tag, (
        f"the lock-up must declare the committed file's own dimensions, got {tag!r}")
    assert (ROOT / LOCKUP_SRC.lstrip("/")).is_file(), (
        f"section 2 names {LOCKUP_SRC}, which the portal does not ship")
    foot = RAW.split("<footer>", 1)[1].split("</footer>", 1)[0]
    assert LOCKUP_SRC in foot, (
        "the body lock-up and the footer's must be the same file; the footer no longer names it")
    rule = re.search(r"(?m)^\s*\.orglockup\{([^}]*)\}", RAW)
    assert rule, "the body lock-up must carry its own sizing rule"
    body = rule.group(1)
    assert re.search(r"(?:^|;)width:\d+px", body), (
        f"the lock-up must declare a body width; the file is 1919px wide, got {body!r}")
    assert "max-width:100%" in body, (
        f"the lock-up must not outgrow a narrow reading column, got {body!r}")


def test_section_two_closes_on_operation_and_governance():
    """The sub-heading the owner dictated, and the three facts under it: who maintains AusMT, what
    custodians keep, and where the arrangements are written down. FAILS if the sub-heading goes, if
    a fact is dropped, or if the Governance link stops being the page it names.

    Section 4 links the same document from its own closing paragraph; that is not a duplicate to
    remove, because the two answer different questions (what happens to my data, and who runs
    this)."""
    who = _section("who")
    assert "<h3>Operation and governance</h3>" in who, (
        "section 2 must close on the Operation and governance sub-heading")
    flat = _flat(who)
    assert ("AusMT is maintained by AuScope with contributions from Australia's magnetotelluric "
            "community.") in flat, "the maintenance sentence is missing"
    assert ("Data custodians retain authority over their survey data, licences and "
            "attribution.") in flat, "the custodian-authority sentence is missing"
    assert "governance, correction and preservation arrangements are documented in" in flat, (
        "the sentence naming the governance document is missing")
    assert (("https://ausmt.readthedocs.io/en/latest/introduction/governance/",
             "Governance & Operation") in _links(who)), (
        "Governance & Operation must be an anchor on the documented arrangements")


def test_the_citing_section_asks_for_both_the_citation_and_the_acknowledgement():
    """Cite the survey, not the portal told a reader what NOT to do and left the acknowledgement
    to a paragraph four down. The replacement states both duties in one line, in the order they are
    performed. FAILS on a revert, and FAILS if the acknowledgement half is dropped."""
    cite = _flat(_section("cite"))
    assert "Cite the survey, not the portal." not in cite, (
        "the retired cite-not-the-portal sentence is back")
    assert "Cite the survey; acknowledge AusMT." in cite, (
        "the citing section must open on both duties")


def test_the_page_and_the_engine_print_one_acknowledgement():
    """ONE acknowledgement, on both surfaces that print one. About carries the copyable block a
    reader is asked to use; the engine prints the same sentence in the Cite disclosure of every
    survey page it emits. FAILS IF the two drift, which is the defect this pin exists for: two
    wordings of one statement leave a reader nothing to say which is current, and the engine's copy
    reaches thousands of pages while About's reaches one.

    The engine half is read from _pages.py's SOURCE, parsed rather than imported: the module
    sibling-imports the engine's own path-dependent helpers and cannot simply be loaded from here,
    and ast.literal_eval reads the constant exactly however it is line-wrapped.

    WHY IT LIVES HERE rather than in engine/tests, the same reason the header parity pin's engine
    half does: portal-ci runs on portal/** AND on engine/extract/_pages.py, so an edit to either
    half fires this lane. The engine lane triggers on engine/** alone and cannot see about.html."""
    tree = ast.parse(PAGES_PY.read_text(encoding="utf-8"))
    found = [node.value for node in tree.body
             if isinstance(node, ast.Assign)
             and any(isinstance(x, ast.Name) and x.id == "_ACKNOWLEDGEMENT" for x in node.targets)]
    assert len(found) == 1, (
        f"engine/extract/_pages.py must declare _ACKNOWLEDGEMENT exactly once, found {len(found)}")
    engine = ast.literal_eval(found[0])
    assert engine == ACKNOWLEDGEMENT, (
        "the acknowledgement has drifted between the page a reader copies it from and the survey "
        "pages the engine prints it on:\n"
        f"  portal/about.html          {ACKNOWLEDGEMENT!r}\n"
        f"  engine/extract/_pages.py   {engine!r}")
