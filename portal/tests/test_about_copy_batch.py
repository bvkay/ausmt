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

NOT COVERED HERE (deliberately, and pinned elsewhere): the #api section and its machine-contract
paragraph, which this batch does not touch (tests/test_api_docs_section.py,
tests/test_mtcat_machine_contract.py).
"""
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
REPO = ROOT.parent
ABOUT = ROOT / "about.html"
STATE_JS = ROOT / "src" / "state.js"
BUILDER = REPO / "engine" / "extract" / "build_portal.py"

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
    assert ("https://dx.doi.org/10.25914/mtjg-jp22", "NCI-AuScope MT collection") in _links(_section("what")), (
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
    assert ack == ("Magnetotelluric transfer functions were accessed through AusMT, Australia's "
                   "Magnetotelluric Data Portal (https://ausmt.au), an AuScope-funded initiative."), (
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
    assert "Bring your EDI or MTH5 transfer functions to the" in flat, (
        "the section must still open by pointing at the Contribute page")
    assert "walks you through the metadata AusMT needs." in flat, (
        "the surviving first paragraph must still end on a whole sentence")
    assert "the gateway runs the AusMT validator over the package and a curator reviews it" in flat, (
        "the curator-review fact must survive")
    assert "operations/submission/" in flat, "the Submission Workflow link must survive"
    assert flat.count("<p>") == 2, (
        f"the section must still be two whole paragraphs, found {flat.count('<p>')}")


# ---------------------------------------------------------------- (i) documentation, one line


def test_the_documentation_section_is_a_single_pointer():
    """The five-bullet topic list is retired: it duplicated the documentation site's own navigation and
    went stale every time a page was renamed. FAILS if a list comes back, or if the one remaining
    sentence is not the dictated one."""
    docs = _section("docs")
    flat = _flat(docs)
    assert "<ul>" not in flat and "<li>" not in flat, (
        "the Documentation section must carry no list; it is a single pointer now")
    assert ("<p>For further information, see the" in flat
            and "AusMT documentation</a>.</p>" in flat), (
        "the Documentation section must carry the dictated single sentence")
    links = _links(docs)
    assert links == [("https://ausmt.readthedocs.io/en/latest/", "AusMT documentation")], (
        f"the Documentation section must carry exactly one link, to the documentation root, got {links}")
    for retired in ("Standards", "Survey Package", "Download Manifest Schema", "Glossary"):
        assert retired not in flat, f"the retired topic bullet is back: {retired!r}"
