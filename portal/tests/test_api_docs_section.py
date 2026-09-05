"""The programmatic-fetch documentation, and the death of the fictional /api tier.

About's seventh answer once carried three worked patterns: whole-survey bundles, a
manifest-driven per-station loop and a bounding-box fetch. About is now the two-minute front door, so it
keeps a ten-line quickstart and the bundle forms, and the two deep patterns moved to the docs site's API
reference (docs/docs/interoperability/api-reference.md, "Fetching data today"). Every assertion those
patterns had moved with them, so nothing that was guarded before is unguarded now; each one just reads
the markdown instead of the HTML.

Three groups of claim are pinned here.

(1) ABOUT'S QUICKSTART EXISTS, IS REACHABLE, AND IS SHORT. The brief asked for a ten-line programmatic
    quickstart on the front door, so the length is a pin rather than a style note: the whole point is
    that a reader can run it before deciding to read anything else. The section, its entry in the page's
    section-nav strip, and the "API access" card's link into it are asserted together (parsed DOM, so an
    HTML comment cannot pass any of them).

(2) NOTHING IN THE PORTAL TREE ADVERTISES A /api/... PATH. Before the API docs landed, the station drawer
    offered a "Read API (planned)" over /api/station/<id>.json, /api/survey/<slug>.json and
    /api/station/<id>/edi. No AusMT deployment has ever served an /api tier: those three paths were
    fiction. This scan FAILS if any such path comes back anywhere in the shipped portal tree. RED-proven:
    run against origin/main before that change, it reports portal/src/drawer.js.

(3) THE DOCS PATTERNS STAY TRUE OF THE ARTIFACTS THEY DESCRIBE. The content assertions are deliberately
    specific about facts that were verified against the live corpus before being written down, because
    the failure mode this material must not have is plausible-looking documentation of endpoints that do
    not exist:

      * the three bundle URL forms (-edi.zip / -xml.zip / -tf.h5) are the only three the engine emits
        (engine/schema/manifest.schema.json bundles.format enum: edi-zip, xml-zip, mth5);
      * the per-station formats are edi, emtfxml and mth5 (files.format enum). `mth5` is in BOTH
        enums and means a different artifact in each, so the patterns must tell a
        reader to filter on the LIST (files[] vs bundles[]) before the format token;
      * artifact bytes are located through the manifest's url + sha256, never by templating a path from a
        station id (in the live corpus, station A1 of vulcan-2022 is served as
        edi/vulcan-2022/Vulcan_A1.edi; the filename is not the id).

    The bounding-box pattern is pinned to two things it cannot be allowed to drift from, because both
    would be silently wrong rather than visibly broken:

      * THE STATION FIELDS. Public-surface audit: catalogue.json is portal-internal and not
        a contract, so the bbox pattern selects from mtcat.json's stations[] (station_id, survey_id,
        latitude, longitude), which IS the contract. Every field the example reads is checked against
        engine/schema/mtcat.schema.json, so a field nobody writes cannot be documented.
      * THE TWO COORDINATE-HONESTY CAVEATS. A withheld station carries null lat/lon and a generalised one
        is rounded to a 0.1deg cell; an example that compares without a null guard either raises (Python)
        or, worse, treats null as 0 (JavaScript) and places a withheld station at 0,0. The published
        example must carry the guard and the prose must carry both caveats.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
REPO = ROOT.parent                              # the ausmt monorepo root
ABOUT = ROOT / "about.html"
APIDOC = REPO / "docs" / "docs" / "interoperability" / "api-reference.md"
MTCAT_SCHEMA = REPO / "engine" / "schema" / "mtcat.schema.json"
BUILDER = REPO / "engine" / "extract" / "build_portal.py"
# The emitted per-station products tree shared with test_docs_static_api.py (see its header).
STATION_PRODUCTS = ROOT / "tests" / "fixtures" / "station-products"

DOCS_API_URL = "https://ausmt.readthedocs.io/en/latest/interoperability/api-reference/"

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


def _quickstart():
    """The one code block in About's #api section: the ten-line quickstart."""
    body = _api_section_text()
    blocks = re.findall(r'<pre class="code">(.*?)</pre>', body, flags=re.S)
    assert len(blocks) == 1, (
        f"About's #api section must carry exactly ONE code block, the quickstart; found {len(blocks)}. "
        f"The deep patterns live on the docs site now.")
    return blocks[0]


def _flat(s):
    """Collapse whitespace so a prose pin survives the page being re-wrapped at a different column."""
    return re.sub(r"\s+", " ", s)


# ---------------------------------------------------------------- About: the quickstart

def test_about_has_the_api_section_and_it_is_navigable():
    p = _page()
    assert "api" in p.section_ids, (
        "about.html must carry a section with id='api' (the anchor the page's own nav strip links)")
    assert any(h.endswith("Fetching data via API") for h in p.headings), (
        f"the section needs its heading; page headings were {sorted(p.headings)}")
    assert "#api" in p.hrefs, (
        "the section-nav strip must carry an entry pointing at #api, or the section is unreachable")
    # The "API access" card in the What-can-you-do section must route readers there too.
    raw = ABOUT.read_text(encoding="utf-8")
    card = raw.split("<h3>API access</h3>", 1)
    assert len(card) == 2, "about.html lost its 'API access' card"
    card_body = card[1].split("</div>", 1)[0]
    assert 'href="#api"' in card_body, (
        "the 'API access' card must link the Fetching-data-via-API section")


def test_quickstart_is_ten_lines_or_fewer():
    """The stage-2 rule asked for a TEN-LINE programmatic quickstart on the front door. A
    quickstart a reader has to scroll is not one, so the length is the pin."""
    lines = [ln for ln in _quickstart().strip().splitlines() if ln.strip()]
    assert len(lines) <= 10, (
        f"the About quickstart must be ten lines or fewer; it is {len(lines)}:\n" + "\n".join(lines))


def test_quickstart_runs_against_real_served_paths():
    """Every path the quickstart names must be one the build actually serves, and the example must use
    only the standard library so a reader can paste it into a bare interpreter."""
    ex = _quickstart()
    assert "urllib.request" in ex, "the quickstart should be standard library only"
    assert "/data/mtcat.json" in ex, "the quickstart starts from the MTCAT discovery document"
    assert "/data/bundles/" in ex, "the quickstart must show how to pull actual bytes, not just metadata"
    src = BUILDER.read_text(encoding="utf-8")
    assert '"mtcat.json"' in src, "the quickstart names data/mtcat.json, so the build must write it"
    # The keys the loop reads off a survey record must be ones the emitter actually puts there.
    for key in ("survey_id", "access", "license", "title"):
        assert f'"{key}"' in ex, f"the quickstart's survey loop should print {key}"
        assert f'"{key}"' in src, (
            f"the quickstart reads {key} off an mtcat survey record, but build_portal.py never emits it")


def test_about_documents_the_three_bundle_forms():
    body = _api_section_text()
    for form in ("-edi.zip", "-xml.zip", "-tf.h5"):
        assert form in body, f"About must document the /data/bundles/&lt;slug&gt;{form} form"
    assert "/data/bundles/" in body, "About must give the bundles path"


def test_about_states_embargo_by_omission_and_points_at_mtcat():
    body = _flat(_api_section_text())
    assert "no rows in the download manifest" in body, (
        "About must state that an embargoed survey is absent from the manifest by construction "
        "(so there is no access error for a consumer to handle)")
    assert "mtcat.json" in body, "About must point at mtcat.json for survey-level discovery"


def test_about_names_the_field_a_slug_is_actually_read_from():
    """The quickstart is keyed by the survey slug and sends the reader to mtcat.json to discover surveys.
    But mtcat's survey records expose the slug under the key `survey_id` (see
    engine/extract/build_portal.py mtcat_document: the entry is built as {"survey_id": slug_of[...]}),
    with NO `slug` key on them at all. A reader who follows the documented pointer looking for `slug`
    finds nothing, which breaks the one property this section is for: being followable end to end.
    FAILS unless the section names the field by its real key."""
    body = _api_section_text()
    assert "survey_id" in body, (
        "the section keys downloads on the survey slug and points at mtcat.json to find surveys, so it "
        "must name the key mtcat actually carries it under (survey_id), not leave the reader to infer it")


def test_about_sends_depth_seekers_to_the_docs_api_reference():
    """About and the station drawer both link the docs site's API reference for depth.
    FAILS if About stops linking it, which would strand a reader who needs the per-station or
    bounding-box patterns that moved off this page."""
    assert DOCS_API_URL in _api_section_text(), (
        f"About's #api section must link the docs API reference ({DOCS_API_URL}), which is where the "
        f"worked per-station and bounding-box patterns went")


def test_about_no_longer_carries_the_deep_patterns():
    """The migration must be a MOVE, not a copy. Two copies of a worked example drift, and the one on the
    front door is the one nobody would think to update. FAILS if the manifest loop or the bounding-box
    example reappears on About."""
    body = _api_section_text()
    for gone in ("hashlib.sha256", "jq -r", "shasum -a 256", "LAT, LON, AUSMT_ID"):
        assert gone not in body, (
            f"{gone!r} belongs to the deep patterns, which moved to the docs API reference; About must "
            f"not carry a second copy")


# ---------------------------------------------------------------- the docs API reference

def _docs_fetch_section():
    """The 'Fetching data today' section of the docs API reference, up to the next h2."""
    raw = APIDOC.read_text(encoding="utf-8")
    assert "## Fetching data today" in raw, (
        f"{APIDOC} must carry the worked fetch patterns under '## Fetching data today'")
    return raw.split("## Fetching data today", 1)[1].split("\n## ", 1)[0]


def _docs_sub(*must_contain):
    """The one ### subsection of the fetch section containing all of `must_contain`."""
    hits = [s for s in _docs_fetch_section().split("\n### ")[1:]
            if all(m in s for m in must_contain)]
    assert len(hits) == 1, (
        f"expected exactly one fetch subsection containing all of {must_contain}; found {len(hits)}")
    return hits[0]


def _code_blocks(fragment):
    return re.findall(r"```[a-z]*\n(.*?)```", fragment, flags=re.S)


def test_docs_document_the_bundle_forms_with_a_worked_command():
    """The three bundle forms plus a worked command that actually pulls bytes.

    The command once hard-coded https://ausmt.au. The docs are
    host-relative throughout, and the runnable examples take that root
    from a BASE variable. The pin moved with the convention; what it guards is unchanged, namely that
    the subsection carries a command a reader can run rather than only a path listing."""
    sub = _docs_sub("-tf.h5")
    for form in ("-edi.zip", "-xml.zip", "-tf.h5"):
        assert form in sub, f"the bundles subsection must document the /data/bundles/<slug>{form} form"
    assert 'curl -O "$BASE/data/bundles/' in sub, (
        "the bundles subsection needs its worked curl example, joined onto the BASE portal root")
    assert "BASE=" in sub, (
        "the example must set BASE, or a reader has nothing to join the site-relative path onto")


def test_docs_document_the_manifest_flow():
    sub = _docs_sub("manifest.json", "jq -r")
    assert "/data/manifest.json" in sub, "the per-station pattern starts at the download index"
    assert "/data/products/manifest.json" not in sub, (
        "the products/ mirror of the manifest is not a public surface; the download "
        "index is /data/manifest.json")
    assert "sha256" in sub, "the per-station pattern must tell the reader to verify the sha256"
    for fmt in ("`edi`", "`emtfxml`"):
        assert fmt in sub, f"the per-station pattern must name the format {fmt}"
    assert "shasum -a 256 -c -" in sub, "the shell example must actually verify the checksum"
    assert "hashlib.sha256" in sub, "the Python equivalent must actually verify the checksum"
    assert "urllib.request" in sub, "the Python equivalent should be standard library only"
    assert "not derivable from the station id" in _flat(sub), (
        "the pattern must say why the manifest is mandatory: a served filename cannot be templated from "
        "the station id")


def test_docs_distinguish_the_two_mth5_granularities():
    """files.format is edi|emtfxml|mth5 and bundles.format is edi-zip|xml-zip|mth5
    (engine/schema/manifest.schema.json), so `mth5` is the one token that appears in both lists and
    means a different artifact in each. The fetch patterns must tell a reader that the LIST is what
    distinguishes them; a reader who filters on the token alone pulls a whole survey where they wanted
    one station. FAILS if the section stops saying so, or if it reverts to the pre-tier-1 claim that a
    per-station MTH5 does not exist."""
    flat = _flat(_docs_fetch_section())
    assert "per survey rather than per station" not in flat, (
        "the section still carries the pre-tier-1 claim; a per-station MTH5 exists now")
    assert "h5/<slug>/<station>.h5" in flat, "the section must give the per-station MTH5 path"
    assert "one station" in flat and "the whole survey" in flat, (
        "the section must say what each of the two mth5 row kinds actually is")
    assert "Filter on the list first" in flat, (
        "the section must tell a reader to filter on files[] vs bundles[] before the format token")


def test_docs_state_embargo_by_omission():
    body = _flat(_docs_fetch_section())
    assert "no rows in the manifest at all" in body, (
        "the docs must state that an embargoed survey is absent from the manifest by construction")


def _bbox():
    return _docs_sub("mtcat.json", "coordinates_state")


def _bbox_example():
    blocks = _code_blocks(_bbox())
    assert blocks, "the bounding-box subsection must carry a worked example"
    return blocks[0]


def _mtcat_station_fields():
    """The station record's properties as the MTCAT schema defines them."""
    schema = json.loads(MTCAT_SCHEMA.read_text(encoding="utf-8"))
    return set(schema["properties"]["stations"]["items"]["properties"])


def test_docs_document_the_bounding_box_pattern():
    frag = _flat(_bbox())
    assert "/data/mtcat.json" in frag, "the pattern starts from the MTCAT discovery document"
    assert "`stations[]`" in frag, (
        "the pattern selects from the catalogue's station records; say which list")
    ex = _bbox_example()
    assert "/data/manifest.json" in ex, (
        "the pattern joins the station selection to the download index")
    assert "/data/products/manifest.json" not in ex, "the products/ mirror of the manifest is retired"
    assert 'row["sha256"]' in ex and "hashlib.sha256" in ex, (
        "the pattern fetches artifact bytes, so it must verify them")
    assert 'row["ausmt_id"] not in ids' in ex, "the manifest join must be on ausmt_id"


def test_bbox_reads_station_fields_the_mtcat_schema_defines():
    """mtcat.json is the contract the pattern reads, so every station field the example and the prose
    name must be a real property of stations[].items, or a reader is told to read a key nobody
    writes."""
    fields = _mtcat_station_fields()
    for name in ("station_id", "survey_id", "latitude", "longitude"):
        assert name in fields, f"the pattern reads stations[].{name}; the schema does not define it"
    frag = _flat(_bbox())
    for name in ("station_id", "survey_id", "latitude", "longitude"):
        assert f"`{name}`" in frag, f"the prose must name the station field {name}"
    ex = _bbox_example()
    assert 'st["station_id"]' in ex and 'cat["stations"]' in ex, (
        "the example must select station_id out of mtcat.json's stations[]")


def test_bbox_null_guards_withheld_coordinates():
    """A custodian-withheld station is served with paired null latitude/longitude. Comparing null
    numerically either raises (Python) or coerces to 0 (JavaScript, which silently relocates the station
    to 0,0 and can pull it INTO a box). The published example must guard both fields, and the prose must
    say why."""
    ex = _bbox_example()
    assert 'st["latitude"] is not None and st["longitude"] is not None' in ex, (
        "the example must test BOTH coordinate fields for null before comparing them")
    frag = _flat(_bbox())
    assert "withholds" in frag and "`null` in `latitude` and `longitude`" in frag, (
        "the prose must state that a withheld position is served as null")
    assert "0°, 0°" in frag, (
        "the prose must name the JavaScript failure mode concretely: null compares as 0, which places a "
        "withheld station at 0,0 rather than excluding it")


def test_bbox_states_the_generalisation_caveat_and_its_contract_fields():
    """A generalised position is rounded to a 0.1deg cell by the engine's single rounding function
    (_coordaccess.round_generalised, 1 dp), so a box edge is approximate to within half a cell. The prose
    must say so, and the fields it names for WHICH positions are non-exact must be the contract's own:
    surveys[].coordinates_state in mtcat.json and coordinate_policy in station.json, both written by the
    emitter."""
    frag = _flat(_bbox())
    assert "generalised" in frag and "0.1°" in frag, (
        "the prose must state that a generalised position is rounded to a 0.1 degree cell")
    assert "0.05°" in frag, (
        "half a 0.1 degree cell is the actual edge error; state it rather than leaving a reader to derive it")
    assert "`coordinates_state`" in frag and "`coordinate_policy`" in frag, (
        "the prose should name the contract fields that tell a consumer WHICH positions are non-exact")
    schema = json.loads(MTCAT_SCHEMA.read_text(encoding="utf-8"))
    state = schema["properties"]["surveys"]["items"]["properties"]["coordinates_state"]
    assert set(state["enum"]) == {"exact", "generalised", "withheld"}, state
    for value in ("`exact`", "`generalised`", "`withheld`"):
        assert value in frag, f"the prose must name the coordinates_state value {value}"
    # The docs name station.json's coordinate_policy, so an EMITTED record must actually carry it, and
    # only where the position is non-exact (an exact record gaining the key would tell a reader every
    # A test module installs nothing; the portal suite is what runs without the engine stack:
    # position is qualified). Emitted documents rather than emitter source text: the portal suite
    # installs no engine stack, and a grep for a source literal survives no refactor of the emitter.
    def _emitted(station):
        return json.loads((STATION_PRODUCTS / "open-survey" / station / "station.json")
                          .read_text(encoding="utf-8"))
    assert _emitted("SPGENERAL").get("coordinate_policy") == "generalised"
    assert "coordinate_policy" not in _emitted("SPEXACT"), (
        "an exact station's record carries no coordinate_policy, so the key means what the docs say")


def test_bbox_does_not_flatten_manifest_paths_across_surveys():
    """The per-station pattern filters to one survey, where a basename is unique, so writing to the
    basename is safe there. A bounding box crosses surveys and the live corpus really does hold two
    stations named SA225_2 (auslamp-musgraves-apy-2016 and auslamp-sa-ne-2014), so the same shortcut
    silently loses one file. The bbox example must mirror the manifest path and must say why."""
    ex = _bbox_example()
    assert 'pathlib.Path(row["url"])' in ex, (
        "the example must write each artifact under the manifest's own url path")
    assert 'split("/")[-1]' not in ex, (
        "the example must not flatten manifest paths to a basename: two surveys can hold the same station "
        "filename, and the second write would overwrite the first")
    frag = _flat(_bbox())
    assert "A box crosses surveys" in frag and "same filename" in frag, (
        "the prose must explain the collision, or a reader will 'simplify' the example back into the bug")


# ---------------------------------------------------------------- the fictional /api tier

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
    """A test module changes no files. State what the scan must reach:
    Guards the guard. The scan above passes trivially if its file walk collects nothing, so pin that
    it reaches both files the change touched."""
    seen = {p.relative_to(ROOT).as_posix() for p in _shipped_portal_files()}
    for expected in ("src/drawer.js", "about.html", "index.html"):
        assert expected in seen, f"the fictional-path scan must cover {expected}; it walked {sorted(seen)}"
