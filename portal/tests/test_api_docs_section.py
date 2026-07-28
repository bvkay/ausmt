"""About's "Fetching data programmatically" section, and the death of the fictional /api tier.

Two related claims are pinned here.

(1) THE SECTION EXISTS AND IS REACHABLE. About gained a seventh answer documenting how to fetch data
    without the UI. It is only useful if a reader can find it, so the section, its entry in the page's
    section-nav strip, and the "API access" card's link into it are all asserted together (parsed DOM,
    so an HTML comment cannot pass any of them).

(2) NOTHING IN THE PORTAL TREE ADVERTISES A /api/... PATH. Before this lane the station drawer offered
    a "Read API (planned)" over /api/station/<id>.json, /api/survey/<slug>.json and
    /api/station/<id>/edi. No AusMT deployment has ever served an /api tier: those three paths were
    fiction, and the section above documents what is actually served instead. This scan FAILS if any
    such path comes back anywhere in the shipped portal tree. RED-proven: run against origin/main it
    reports portal/src/drawer.js.

The CONTENT assertions are deliberately specific about facts that were verified against the live
corpus before being written down, because the failure mode this section must not have is
plausible-looking documentation of endpoints that do not exist:

  * the three bundle URL forms (-edi.zip / -xml.zip / -tf.h5) are the only three the engine emits
    (engine/schema/manifest.schema.json bundles.format enum: edi-zip, xml-zip, mth5);
  * the per-station formats are edi and emtfxml, and ONLY those (files.format enum); mth5 exists per
    SURVEY, never per station, so a reader must not be told to filter station rows by it;
  * artifact bytes are located through the manifest's url + sha256, never by templating a path from a
    station id (in the live corpus, station A1 of vulcan-2022 is served as
    edi/vulcan-2022/Vulcan_A1.edi; the filename is not the id).

PATTERN C (bounding-box fetch, mtcat-v1.2 docs lane) is pinned to two things it cannot be allowed to
drift from, because both would be silently wrong rather than visibly broken:

  * THE COLUMN INDICES. catalogue.json rows are positional, so a bbox example has to name indices, and a
    documented index that no longer matches contract/columns.json points a reader at the wrong column
    (lat at 3 rather than 2 yields a plausible-looking, entirely wrong result set). The indices in the
    prose are compared against the GENERATED src/contract.js, so a reorder fails here.
  * THE TWO COORDINATE-HONESTY CAVEATS. A withheld station carries null lat/lon and a generalised one is
    rounded to a 0.1deg cell; an example that compares without a null guard either raises (Python) or,
    worse, treats null as 0 (JavaScript) and places a withheld station at 0,0. The published example must
    carry the guard and the prose must carry both caveats.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
ABOUT = ROOT / "about.html"
CONTRACT_JS = ROOT / "src" / "contract.js"
BUILDER = ROOT.parent / "engine" / "extract" / "build_portal.py"

# Assembled at runtime so this file's own source never contains the literal it forbids (the scan below
# would otherwise flag its own test module).
FICTIONAL = "/" + "api" + "/"


class _Sections(HTMLParser):
    """Section ids, heading text, and every <a href> on the page, in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.section_ids = []
        self.hrefs = []
        self.headings = {}          # heading text -> tag
        self._h = None

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        if tag == "section" and d.get("id"):
            self.section_ids.append(d["id"])
        if tag == "a" and "href" in d:
            self.hrefs.append(d["href"])
        if tag in ("h1", "h2", "h3"):
            self._h = tag

    def handle_endtag(self, tag):
        if tag == self._h:
            self._h = None

    def handle_data(self, data):
        if self._h and data.strip():
            self.headings[data.strip()] = self._h


def _page():
    p = _Sections()
    p.feed(ABOUT.read_text(encoding="utf-8"))
    return p


def _api_section_text():
    """The raw markup of the #api section only, so content pins cannot pass on text elsewhere."""
    raw = ABOUT.read_text(encoding="utf-8")
    assert '<section id="api">' in raw, "about.html has no <section id=\"api\">"
    body = raw.split('<section id="api">', 1)[1]
    return body.split("</section>", 1)[0]


def test_about_has_the_api_section_and_it_is_navigable():
    p = _page()
    assert "api" in p.section_ids, (
        "about.html must carry a section with id='api' (the anchor the station drawer links to)")
    assert any(h.endswith("Fetching data programmatically") for h in p.headings), (
        f"the section needs its heading; page headings were {sorted(p.headings)}")
    assert "#api" in p.hrefs, (
        "the section-nav strip must carry an entry pointing at #api, or the section is unreachable")
    # The "API access" card in the What-can-you-do section must route readers there too.
    raw = ABOUT.read_text(encoding="utf-8")
    card = raw.split("<h3>API access</h3>", 1)
    assert len(card) == 2, "about.html lost its 'API access' card"
    card_body = card[1].split("</div>", 1)[0]
    assert 'href="#api"' in card_body, (
        "the 'API access' card must link the new Fetching-data-programmatically section")


def test_api_section_documents_pattern_a_bundles():
    body = _api_section_text()
    for form in ("-edi.zip", "-xml.zip", "-tf.h5"):
        assert form in body, f"Pattern A must document the /data/bundles/&lt;slug&gt;{form} form"
    assert "/data/bundles/" in body, "Pattern A must give the bundles path"
    assert "curl -O https://ausmt.au/data/bundles/" in body, (
        "Pattern A needs its worked curl example")


def test_api_section_documents_pattern_b_manifest_flow():
    body = _api_section_text()
    assert "/data/products/manifest.json" in body, "Pattern B starts at the products manifest"
    assert "sha256" in body, "Pattern B must tell the reader to verify the sha256"
    for fmt in ("<code>edi</code>", "<code>emtfxml</code>"):
        assert fmt in body, f"Pattern B must name the per-station format {fmt}"
    assert "jq -r" in body, "Pattern B needs its curl + jq loop"
    assert "shasum -a 256 -c -" in body, "the shell example must actually verify the checksum"
    assert "hashlib.sha256" in body, "the Python equivalent must actually verify the checksum"
    assert "urllib.request" in body, "the Python equivalent should be standard library only"


def test_api_section_does_not_promise_a_per_station_mth5():
    """files.format is edi|emtfxml (engine/schema/manifest.schema.json); mth5 is a BUNDLE format. FAILS
    if the section tells a reader to filter per-station rows by mth5, which would send them looking for
    artifacts that do not exist."""
    body = _api_section_text()
    assert "per survey rather than per station" in body, (
        "the section must say plainly that mth5 is a per-survey format, not a per-station one")
    for wrong in ('.format=="mth5"', "format == \"mth5\"", "files[] | select(.format==\"mth5\")"):
        assert wrong not in body, f"the section must not filter per-station rows by mth5 ({wrong})"


def test_api_section_states_embargo_by_omission_and_points_at_mtcat():
    body = _api_section_text()
    assert "no rows in the manifest" in body, (
        "the section must state that an embargoed survey is absent from the manifest by construction "
        "(so there is no access error for a consumer to handle)")
    assert "mtcat.json" in body, (
        "the section must point at mtcat.json for survey-level discovery")


def test_api_section_names_the_field_a_slug_is_actually_read_from():
    """Both patterns are keyed by the survey slug, and the section sends the reader to mtcat.json to
    discover surveys. But mtcat's survey records expose the slug under the key `survey_id` (see
    engine/extract/build_portal.py mtcat_document: the entry is built as {"survey_id": slug_of[...]}),
    with NO `slug` key on them at all. A reader who follows the documented pointer looking for `slug`
    finds nothing, which breaks the one property this section is for: being followable end to end.
    FAILS unless the section names the field by its real key."""
    body = _api_section_text()
    assert "survey_id" in body, (
        "the section keys both patterns on the survey slug and points at mtcat.json to find surveys, so "
        "it must name the key mtcat actually carries it under (survey_id), not leave the reader to infer it")
    assert "mtcat.json" in body.split("survey_id")[0][-400:] or "MTCAT" in body, (
        "the survey_id mention must sit with the mtcat pointer it explains")


def _flat(s):
    """Collapse whitespace so a prose pin survives the page being re-wrapped at a different column."""
    return re.sub(r"\s+", " ", s)


def _pattern_c():
    """Just the Pattern C subsection, so its pins cannot pass on Pattern A/B text."""
    body = _api_section_text()
    assert "<h3>Pattern C" in body, 'the #api section has no "<h3>Pattern C" heading'
    return body.split("<h3>Pattern C", 1)[1].split("<h3", 1)[0]


def _pattern_c_example():
    """The worked code block inside Pattern C."""
    frag = _pattern_c()
    assert '<pre class="code">' in frag, "Pattern C must carry a worked example"
    return frag.split('<pre class="code">', 1)[1].split("</pre>", 1)[0]


def _contract_indices():
    """The catalogue column map as GENERATED into src/contract.js from contract/columns.json."""
    src = CONTRACT_JS.read_text(encoding="utf-8")
    m = re.search(r"^var C\s*=\s*\{(.*?)\};", src, flags=re.M | re.S)
    assert m, "could not find the `var C = {...}` catalogue index map in src/contract.js"
    idx = {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", m.group(1))}
    assert {"lat", "lon", "ausmt_id"} <= set(idx), f"contract.js C map looks wrong: {idx}"
    return idx


def test_api_section_documents_pattern_c_bounding_box():
    frag = _flat(_pattern_c())
    assert "bounding-box fetch" in frag, "Pattern C is the bounding-box pattern; say so in the heading"
    assert "/data/catalogue.json" in frag, "Pattern C starts from the positional station catalogue"
    assert "POSITIONAL" in frag and "read by index" in frag, (
        "a reader who treats catalogue rows as objects gets nothing; the section must say the rows are "
        "positional arrays read by index")
    ex = _pattern_c_example()
    assert "/data/products/manifest.json" in ex, (
        "Pattern C joins the catalogue selection to the products manifest")
    assert 'row["sha256"]' in ex and "hashlib.sha256" in ex, (
        "Pattern C fetches artifact bytes, so it must verify them like Pattern B does")
    assert 'row["ausmt_id"] not in ids' in ex, "the manifest join must be on ausmt_id"


def test_pattern_c_column_indices_match_the_generated_contract():
    """catalogue.json carries no field names, so Pattern C has to state indices. A stated index that no
    longer matches contract/columns.json is the worst kind of documentation bug: it produces a plausible
    result set from the wrong column. Compared against the generated map, both in the prose and in the
    example's own constants."""
    idx = _contract_indices()
    frag = _flat(_pattern_c())
    for name in ("lat", "lon", "ausmt_id"):
        assert f"<code>{name}</code> at index <b>{idx[name]}</b>" in frag, (
            f"Pattern C must state {name} at index {idx[name]} (per src/contract.js); the prose disagrees")
    assert "src/contract.js" in frag, (
        "the prose must point at src/contract.js as the authoritative column map, not just quote indices")
    ex = _pattern_c_example()
    assert f"LAT, LON, AUSMT_ID = {idx['lat']}, {idx['lon']}, {idx['ausmt_id']}" in ex, (
        "the example's own index constants must agree with src/contract.js")


def test_pattern_c_null_guards_withheld_coordinates():
    """A custodian-withheld station is served with null lat/lon. Comparing null numerically either raises
    (Python) or coerces to 0 (JavaScript, which silently relocates the station to 0,0 and can pull it INTO
    a box). The published example must guard both columns, and the prose must say why."""
    ex = _pattern_c_example()
    assert "r[LAT] is not None and r[LON] is not None" in ex, (
        "the example must test BOTH coordinate columns for null before comparing them")
    frag = _flat(_pattern_c())
    assert "withholds" in frag and "<code>null</code> in the lat and lon columns" in frag, (
        "the prose must state that a withheld position is served as null")
    assert "0°, 0°" in frag, (
        "the prose must name the JavaScript failure mode concretely: null compares as 0, which places a "
        "withheld station at 0,0 rather than excluding it")


def test_pattern_c_states_the_generalisation_caveat_and_its_marker_file():
    """A generalised position is rounded to a 0.1deg cell by the engine's single rounding function
    (_coordaccess.round_generalised, 1 dp), so a box edge is approximate to within half a cell. The prose
    must say so, and the marker file it names must be one the build really writes."""
    frag = _flat(_pattern_c())
    assert "generalised" in frag and "0.1°" in frag, (
        "the prose must state that a generalised position is rounded to a 0.1 degree cell")
    assert "0.05°" in frag, (
        "half a 0.1 degree cell is the actual edge error; state it rather than leaving a reader to derive it")
    assert "coord_policy.json" in frag, (
        "the prose should name the artifact that tells a consumer WHICH stations are non-exact")
    assert "absent when every served position" in frag, (
        "coord_policy.json is emitted only when a station is non-exact, so its absence is meaningful and "
        "must not read as a missing file")
    src = BUILDER.read_text(encoding="utf-8")
    assert '(out / "coord_policy.json").write_text(' in src, (
        "about.html names data/coord_policy.json, so the build must actually write it")


def test_pattern_c_does_not_flatten_manifest_paths_across_surveys():
    """Pattern B filters to one survey, where a basename is unique, so writing to the basename is safe
    there. A bounding box crosses surveys and the live corpus really does hold two stations named SA225_2
    (auslamp-musgraves-apy-2016 and auslamp-sa-ne-2014), so the same shortcut silently loses one file.
    Pattern C must mirror the manifest path and must say why."""
    ex = _pattern_c_example()
    assert 'pathlib.Path(row["url"])' in ex, (
        "the example must write each artifact under the manifest's own url path")
    assert 'split("/")[-1]' not in ex, (
        "the example must not flatten manifest paths to a basename: two surveys can hold the same station "
        "filename, and the second write would overwrite the first")
    frag = _flat(_pattern_c())
    assert "a box crosses surveys" in frag and "same filename" in frag, (
        "the prose must explain the collision, or a reader will 'simplify' the example back into the bug")


def _shipped_portal_files():
    """Every hand-written file the portal actually ships. vendor/ (third-party bundles), node_modules,
    the generated data tree and tests/ (this file names the forbidden path in order to forbid it) are
    excluded."""
    skip = {"vendor", "node_modules", "data", "tests"}
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix not in (".html", ".js", ".json", ".yaml", ".md"):
            continue
        if skip & set(p.relative_to(ROOT).parts):
            continue
        if p.name in ("package-lock.json", "package.json"):
            continue
        yield p


def test_no_fictional_api_paths_anywhere_in_the_portal_tree():
    hits = []
    for p in _shipped_portal_files():
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if FICTIONAL in line:
                hits.append(f"{p.relative_to(ROOT)}:{lineno}: {line.strip()[:160]}")
    assert not hits, (
        "the portal tree must advertise no " + FICTIONAL + " endpoint: AusMT serves read-only static "
        "JSON under /data/ and has never run an API tier. Found:\n" + "\n".join(hits))


def test_the_scan_actually_looks_at_the_files_that_used_to_carry_the_fiction():
    """Guards the guard. The scan above passes trivially if its file walk collects nothing, so pin that
    it reaches both files this lane changed."""
    seen = {p.relative_to(ROOT).as_posix() for p in _shipped_portal_files()}
    for expected in ("src/drawer.js", "about.html", "index.html"):
        assert expected in seen, f"the fictional-path scan must cover {expected}; it walked {sorted(seen)}"
