"""The static data API, documented in depth, and the death of the fictional REST design.

DOCS WAVE, STAGE 3. Until this lane, docs/docs/interoperability/api-overview.md and api-reference.md
specified a REST service that has never existed at any AusMT deployment: `/v1/collections`,
`/v1/surveys`, `/v1/stations`, an authentication section, a "Future Directions" section. Both pages
carried an "Implementation status" callout admitting the whole design was unbuilt, and then spent
several hundred lines describing it anyway, while the interface that DOES exist got a paragraph.

The three pages now describe the real thing: read-only static JSON behind an ordinary file server.
This module pins the claims that would be silently wrong if the code moved underneath them. It
deliberately pins against the SCHEMA and the EMITTER, never against the live corpus: a corpus fact
(which surveys are embargoed, how many stations there are) lives in a different repository and would
turn this file into a tripwire for ordinary curation.

Four groups of claim.

(1) NO FICTION SURVIVES. The `/v1` resource list, the `/api/...` paths and the "planned interface /
    not yet implemented" framing must be gone from all three pages. Scanning for them is cheap and it
    is the one regression that would undo the whole lane. RED-proven: run against HEAD~1 and both
    api-overview.md and api-reference.md report hits.

(2) THE FORMAT VOCABULARIES MATCH THE MANIFEST SCHEMA. Docs that name a format the build cannot emit
    send a reader looking for artifacts that do not exist. The per-station formats and the bundle
    formats are compared against engine/schema/manifest.schema.json's own enums, both directions, so
    adding a format to the schema without documenting it fails here too. The comparison is over
    (token, granularity) PAIRS because `mth5` is in both enums since the tier-1 lane: a files[] row is
    one station, a bundles[] row is the whole survey, and a token-keyed check could not tell the two
    apart or notice that only one of them had been documented.

(3) THE CATALOGUE COLUMN TABLE MATCHES THE CONTRACT. catalogue.json rows are positional, so the page
    that documents them reproduces the column table. A stale table is the worst kind of documentation
    bug: a reader takes an index, gets the wrong column, and the result looks plausible. The table is
    compared name-by-name and index-by-index against contract/columns.json, which is the single
    source the generated maps come from. Public-surface audit (2026-08-22): catalogue.json is
    portal-internal, not a contract, so the table lives on developer/data-files.md (the engine-to-
    portal positional contract) and the public data reference no longer carries it; the pin follows
    the table.

(4) THE HONESTY CLAIMS ARE BACKED BY CODE. Three of them, each pinned to the line in
    build_portal.py that implements it: the three access levels, the withheld station.json marker,
    and the fact that dimensionality.json is not written at all for a withheld station (so a
    consumer must gate the request rather than treat the 404 as a transport error). Plus the
    releases tier, which is documented as DEFINED BUT UNPOPULATED and must keep saying so for as
    long as no release is cut.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
REPO = ROOT.parent                              # the ausmt monorepo root
DOCS = REPO / "docs" / "docs" / "interoperability"
DATAFILES = REPO / "docs" / "docs" / "developer" / "data-files.md"

OVERVIEW = DOCS / "api-overview.md"
REFERENCE = DOCS / "api-reference.md"
INTEGRATION = DOCS / "tool-integration.md"
PAGES = (OVERVIEW, REFERENCE, INTEGRATION)

MKDOCS = REPO / "docs" / "mkdocs.yml"
BUILDER = REPO / "engine" / "extract" / "build_portal.py"
MANIFEST_SCHEMA = REPO / "engine" / "schema" / "manifest.schema.json"
MTCAT_SCHEMA = REPO / "engine" / "schema" / "mtcat.schema.json"
COLUMNS = REPO / "contract" / "columns.json"
# A per-station products tree the REAL build emitted (an open survey with an exact and a generalised
# station, plus an embargoed one), committed so this stackless lane can pin the docs against emitted
# DOCUMENTS rather than against emitter source text.
STATION_PRODUCTS = ROOT / "tests" / "fixtures" / "station-products"
STATION_SCHEMA = REPO / "engine" / "schema" / "ausmt-station.schema.json"

# Assembled at runtime so this module's own source never contains the literals it forbids.
FICTIONAL_API = "/" + "api" + "/"
FICTIONAL_REST = "/" + "v1" + "/"


def _text(p):
    return p.read_text(encoding="utf-8")


def _flat(p):
    return re.sub(r"\s+", " ", _text(p))


# ---------------------------------------------------------------- (1) no fiction survives

def test_no_page_advertises_the_fictional_rest_tier():
    """The `/v1/...` resource list was the centre of the retired design. No AusMT deployment has ever
    served it. FAILS if any of the three pages brings it back."""
    hits = []
    for p in PAGES:
        for lineno, line in enumerate(_text(p).splitlines(), start=1):
            if FICTIONAL_REST in line or FICTIONAL_API in line:
                hits.append(f"{p.relative_to(REPO)}:{lineno}: {line.strip()[:160]}")
    assert not hits, (
        "the interoperability pages must advertise no REST tier: AusMT serves read-only static JSON "
        "under /data/ and has never run one. Found:\n" + "\n".join(hits))


def test_no_page_frames_the_data_api_as_unimplemented():
    """The retired pages opened with a callout saying the interface they described was not built. A
    page that describes what exists must not carry that framing, or a reader stops at the callout."""
    for p in PAGES:
        flat = _flat(p).lower()
        for phrase in ("not yet implemented", "planned interface", "the rest api described"):
            assert phrase not in flat, (
                f"{p.relative_to(REPO)} still frames the data interface as unbuilt ({phrase!r}); it "
                f"documents what is served today")


def test_the_pages_are_reachable_from_the_nav():
    """A page mkdocs does not list is a page nobody finds. All three must be in the Interoperability
    section, and the two retired titles must be gone from the nav."""
    nav = _text(MKDOCS)
    for p in PAGES:
        entry = f"interoperability/{p.name}"
        assert entry in nav, f"{entry} is not in the mkdocs nav"
    for retired in ("API Overview:", "API Reference:"):
        assert retired not in nav, (
            f"the nav still carries {retired!r}, the label of a page that described a service AusMT "
            f"does not run")


def test_the_stable_rtd_path_the_portal_links_still_exists():
    """about.html and src/drawer.js both send readers to the RTD page rendered from api-reference.md.
    Renaming or deleting that file breaks two live surfaces, so the filename is pinned here as well as
    in test_api_docs_section.py."""
    assert REFERENCE.exists(), (
        "docs/docs/interoperability/api-reference.md backs "
        "https://ausmt.readthedocs.io/en/latest/interoperability/api-reference/ , which about.html and "
        "src/drawer.js link verbatim")
    linked = "https://ausmt.readthedocs.io/en/latest/interoperability/api-reference/"
    for surface in (ROOT / "about.html", ROOT / "src" / "drawer.js"):
        assert linked in _text(surface), f"{surface.relative_to(ROOT)} lost its link to the API reference"


# ---------------------------------------------------------------- (2) format vocabularies

def _schema_formats():
    doc = json.loads(_text(MANIFEST_SCHEMA))
    defs = doc["definitions"]
    return (set(defs["file"]["properties"]["format"]["enum"]),
            set(defs["bundle"]["properties"]["format"]["enum"]))


def test_documented_formats_match_the_manifest_schema_exactly():
    """Both directions, as (token, granularity) PAIRS rather than tokens. `mth5` is now in both enums:
    a files[] row is one station, a bundles[] row is the whole survey. A token-keyed check could not
    express that, and would silently accept a table that documented only one of the two. A documented
    pair the build cannot emit sends a reader looking for files that do not exist; an emitted pair
    nobody documented is a distribution surface with no reader."""
    per_station, per_survey = _schema_formats()
    body = _text(REFERENCE)
    table = body.split("## Selecting a format", 1)
    assert len(table) == 2, "the reference must carry a '## Selecting a format' section"
    section = table[1].split("\n## ", 1)[0]
    # The section's own table is the claim under test: first cell = the format token, third = whether
    # it is per station or per survey. Parsed rather than eyeballed so both directions are checked.
    documented = {(tok, gran.strip().lower())
                  for tok, _where, gran in re.findall(
                      r"^\|\s*`([a-z0-9-]+)`\s*\|([^|]*)\|([^|]*)\|", section, flags=re.M)}
    assert documented, "the format section must carry its format table"
    expected = ({(t, "per station") for t in per_station}
                | {(t, "per survey") for t in per_survey})
    assert documented == expected, (
        f"the format table says {sorted(documented)}; manifest.schema.json's enums imply "
        f"{sorted(expected)}")


def test_the_two_mth5_granularities_are_documented_as_two_things():
    """`mth5` is the one format token that means two different artifacts. A reader who filters on the
    token without reading the list it came from fetches a whole survey where they wanted one station,
    or misses the station files entirely. Both pages must say which list distinguishes them, and the
    integration page must not still be warning a tool author off a per-station MTH5 that now exists."""
    per_station, per_survey = _schema_formats()
    assert "mth5" in per_survey and "mth5" in per_station, (
        "this test encodes the schema's own split; if that changed, the docs need rewriting, not this "
        "assertion relaxing")
    ref, integ = _flat(REFERENCE), _flat(INTEGRATION)
    for page_name, flat in (("api-reference.md", ref), ("tool-integration.md", integ)):
        assert "h5/<slug>/<station>.h5" in flat, (
            f"{page_name} must give the served path of a per-station MTH5")
        assert "bundles/<slug>-tf.h5" in flat, (
            f"{page_name} must keep the served path of the per-survey MTH5 bundle")
    assert "one station" in ref and "the whole survey" in ref, (
        "the reference must say what each of the two mth5 rows actually is")
    assert "no per-station MTH5" not in integ, (
        "the integration page still warns a tool author off a per-station MTH5, which now exists")


# ---------------------------------------------------------------- (3) the catalogue column table

def _documented_catalogue_columns():
    """The data-files page's own catalogue table, as {index: name}, parsed out of its `r[i]` rows."""
    body = _text(DATAFILES)
    section = body.split("## `catalogue.json`", 1)
    assert len(section) == 2, "developer/data-files.md must carry a catalogue.json section"
    rows = re.findall(r"^\|\s*`r\[(\d+)\]`\s*\|\s*`([a-z0-9_]+)`\s*\|", section[1], flags=re.M)
    assert rows, "the catalogue section must carry the positional column table"
    return {int(i): name for i, name in rows}


def test_catalogue_column_table_matches_the_contract():
    """catalogue.json carries no field names, so the table IS the interface for anyone reading it.
    Compared against contract/columns.json, the single file the generated index maps come from."""
    contract = json.loads(_text(COLUMNS))["catalogue"]
    documented = _documented_catalogue_columns()
    expected = dict(enumerate(contract))
    assert documented == expected, (
        "developer/data-files.md's catalogue column table disagrees with contract/columns.json.\n"
        f"  documented: {documented}\n  contract:   {expected}")


def test_the_data_files_page_says_the_rows_are_positional_and_names_the_map():
    flat = _flat(DATAFILES)
    assert "positional arrays, read by index" in flat.lower(), (
        "a reader who treats catalogue rows as objects gets nothing; say it plainly")
    assert "src/contract.js" in flat, (
        "the page must point at the generated column map rather than only quoting indices")


def test_the_public_reference_documents_no_portal_internal_document():
    """Public-surface audit (2026-08-22): the only public metadata contracts are mtcat.json (with its
    schema routes) and station.json, with survey-metadata.json to come; manifest.json is the download
    index. catalogue.json, sci.json, tf.json, surveys.json, collections.json, build.json,
    build_provenance.json and coord_policy.json are portal-internal and documented only under
    Developer; build_report.json, qc_report.json and base_ids.json are operator-only. FAILS if the
    data reference or the architecture page recipes or lists any of them again, or revives the
    /data/products/ mirror of the manifest."""
    internal = ("catalogue.json", "sci.json", "tf.json", "surveys.json", "collections.json",
                "build.json", "build_provenance.json", "coord_policy.json", "build_report.json",
                "qc_report.json", "base_ids.json", "/data/products/manifest.json")
    hits = []
    for p in (OVERVIEW, REFERENCE):
        for lineno, line in enumerate(_text(p).splitlines(), start=1):
            if "/data/releases/<tag>/" in line:
                continue          # the release layout lists the frozen copies by filename
            for name in internal:
                if name in line:
                    hits.append(f"{p.name}:{lineno}: {name}: {line.strip()[:120]}")
    assert not hits, (
        "the public data pages document contracts and downloads only; portal-internal and operator-only "
        "documents live under Developer:\n" + "\n".join(hits))


# ---------------------------------------------------------------- (4) honesty claims, backed by code

def test_the_three_access_levels_match_the_emitter():
    src = _text(BUILDER)
    m = re.search(r"^ACCESS_LEVELS\s*=\s*\(([^)]*)\)", src, flags=re.M)
    assert m, "could not find ACCESS_LEVELS in build_portal.py"
    levels = re.findall(r'"([a-z_]+)"', m.group(1))
    assert levels, f"ACCESS_LEVELS parsed empty from {m.group(1)!r}"
    flat = _flat(OVERVIEW)
    for level in levels:
        assert f"`{level}`" in flat, (
            f"the architecture page must name the access level {level!r}; the emitter's ACCESS_LEVELS "
            f"is {levels}")


def test_embargo_is_documented_as_omission_not_as_an_access_error():
    """The whole point of the access model, from a client's side: there is no authorisation branch to
    write, because a withheld byte has no manifest row to request."""
    flat = _flat(OVERVIEW)
    assert "not one row in the download manifest" in flat, (
        "the architecture page must state that a withheld survey is absent from the manifest by "
        "construction")
    assert "no authorisation branch" in flat, (
        "state the consequence for a client, not just the mechanism")


def test_the_withheld_station_record_is_documented_as_the_emitter_writes_it():
    """station.json IS written for a withheld station (a stub carrying the access state), and
    dimensionality.json is NOT written at all. Both halves are pinned to EMITTED DOCUMENTS, because a
    doc that swapped them would send a consumer's loop into a 404 it treats as a transport failure.

    The evidence is fixtures/station-products/, a per-station products tree the REAL build emitted. This
    lane installs no engine stack, so the emitter cannot run here; a grep for a source literal pinned
    the emitter's TEXT, which survives no refactor. The emitter's own live gate is the engine suite's
    C1c build (engine/tests/test_access_gate.py), which asserts the same two facts over a real build."""
    held = STATION_PRODUCTS / "withheld-survey" / "SPHELD"
    assert json.loads((held / "station.json").read_text(encoding="utf-8"))["withheld"] is True, (
        "the docs describe a withheld station.json stub; the emitter must write the marker")
    assert not (held / "dimensionality.json").exists(), (
        "the docs say dimensionality.json is never written for a withheld station; that must be what "
        "the emitter does")
    served = STATION_PRODUCTS / "open-survey" / "SPEXACT"
    assert (served / "dimensionality.json").exists(), (
        "non-vacuity: a SERVED station in the same emitted tree does get one, so the absence above is "
        "the access gate and not an empty fixture")
    flat = _flat(REFERENCE)
    assert '`"withheld": true`' in flat, "the reference must name the marker a consumer tests on"
    assert "`404`, never written" in flat, (
        "the reference must say dimensionality.json is absent rather than forbidden for a withheld "
        "station")


def test_the_committed_products_tree_still_matches_the_station_contract():
    """Emitted output can go stale against the contract it illustrates, so the fixture is tied to the
    artifact: each document carries the required set its own branch declares in
    engine/schema/ausmt-station.schema.json. A plain-JSON read, since this lane installs no validator;
    portal-ci triggers on engine/schema/**, so a schema change that renamed a required key fails here
    rather than leaving the pins above resting on a stale tree."""
    branches = {b["title"]: b["required"]
                for b in json.loads(STATION_SCHEMA.read_text(encoding="utf-8"))["oneOf"]}
    full = json.loads((STATION_PRODUCTS / "open-survey" / "SPEXACT" / "station.json")
                      .read_text(encoding="utf-8"))
    held = json.loads((STATION_PRODUCTS / "withheld-survey" / "SPHELD" / "station.json")
                      .read_text(encoding="utf-8"))
    for doc, title in ((full, "full station record"), (held, "withheld station record")):
        missing = [k for k in branches[title] if k not in doc]
        assert not missing, f"the committed {title} is stale against the schema: missing {missing}"
    assert "withheld" not in full, "the marker is schema-forbidden on a full record"


def test_the_committed_products_tree_carries_the_canonical_blocks():
    """The required-set pin above cannot see a block the schema makes OPTIONAL, and both canonical
    blocks are optional, so the tree once went two behaviour changes stale with nothing red. This is
    the pin for that class: the three documents carry the three combinations the reference page
    describes, which is exactly what a regeneration must reproduce.

    Refresh with `portal/tests/fixtures/make_station_products.py` (needs the engine venv), in the
    same commit as the emitter change that moved it."""
    def doc(slug, station):
        return json.loads((STATION_PRODUCTS / slug / station / "station.json")
                          .read_text(encoding="utf-8"))

    served = doc("open-survey", "SPEXACT")
    assert [r["id"] for r in served["runs"]] == ["SPEXACT-r01"], (
        "the exact station's acquisition is published as a run")
    assert {r["id"] for r in served["resources"]} == {"edi", "emtfxml", "edi-zip", "xml-zip"}, (
        "it serves both renditions and is inside both survey archives")
    masked = doc("open-survey", "SPGENERAL")
    assert masked["runs"], "a generalised position withholds bytes, never the acquisition record"
    assert "resources" not in masked, (
        "a generalised station serves no bytes, so it describes no rendition and claims no archive")
    assert "runs" not in doc("withheld-survey", "SPHELD"), "the withheld stub is closed-world"


def test_the_stations_geojson_is_documented_the_way_the_emitter_writes_it():
    """The GeoJSON exists so a GIS user never has to read the positional catalogue, so the page has to
    carry an instruction a GIS user can follow, not just a path. Its two membership rules are the
    coordinate-access rules, and both are pinned to the emitter: a WITHHELD station is absent (not a
    null-geometry feature, which parses and draws nothing) and a GENERALISED one is present at the
    0.1 degree cell the catalogue already serves. A page that got either backwards would be telling a
    reader the map is complete when it is not, or that a withheld position is on it when it is not.
    FAILS if the section goes missing, if the QGIS instruction degrades to a bare URL, or if the
    emitter stops implementing what the page claims."""
    src = _text(BUILDER)
    assert "def stations_geojson(" in src, "the reference documents a document the build must emit"
    assert '(out / "stations.geojson").write_text' in src, "the document must actually be served"
    assert "continue   # withheld position => no usable geometry => no feature" in src, (
        "the docs say a withheld station is ABSENT; that must be what the emitter does")
    body = _text(REFERENCE)
    section = body.split("### `stations.geojson`", 1)
    assert len(section) == 2, "the reference must carry a stations.geojson section"
    frag = section[1].split("\n### ", 1)[0]
    flat = re.sub(r"\s+", " ", frag)
    assert "/data/stations.geojson" in _text(REFERENCE), "the served path must be listed"
    assert "QGIS" in frag and "Add Vector Layer" in frag, (
        "the section must carry the GIS instruction, not only the URL")
    assert "FeatureCollection" in frag and "WGS84" in frag
    assert "absent" in flat and "null geometry" in flat, (
        "the section must state that a withheld station is absent rather than null-geometry")
    assert "0.1" in flat, "the section must state the generalised cell size"
    assert "embargo withholds bytes, never discovery" in flat, (
        "an embargoed survey's stations ARE on this layer; say so, because the opposite is the "
        "reader's natural assumption")


def test_the_releases_tier_is_documented_as_unpopulated():
    """cut_release.py defines the tier and nothing has been cut. Documenting the layout is useful;
    implying a reader can fetch a release is not. FAILS if the honest state disappears."""
    body = _text(REFERENCE)
    section = body.split("## The releases tier", 1)
    assert len(section) == 2, "the reference must carry a releases-tier section"
    frag = re.sub(r"\s+", " ", section[1].split("\n## ", 1)[0])
    assert "No release has been cut yet" in frag, (
        "the releases section must state plainly that nothing is published there; the index really "
        "does 404 on the live site")
    assert "`404`" in frag, "name the status a consumer will actually see"
    assert "mints nothing" in frag, (
        "the release tooling prepares a DataCite record and submits nothing; a page that implies a "
        "minted DOI would be advertising a citation that does not resolve")


def test_the_documented_mtcat_facets_exist_in_the_schema():
    """The reference lists the 1.2 discovery facets by name. Every one must be a real property of
    surveys[].items, or a harvester is told to read a key nobody writes."""
    schema = json.loads(_text(MTCAT_SCHEMA))
    props = set(schema["properties"]["surveys"]["items"]["properties"])
    body = _text(REFERENCE)
    section = body.split("### `mtcat.json`", 1)[1].split("\n### ", 1)[0]
    named = set(re.findall(r"`(n_stations|data_types|period_min_s|period_max_s|"
                           r"n_stations_tipper|formats|year_start|year_end)`", section))
    assert named, "the mtcat subsection must name the derived discovery facets"
    missing = named - props
    assert not missing, f"the reference names mtcat survey fields the schema does not define: {missing}"


# ---------------------------------------------------------------- voice charter

def test_no_absolute_portal_host_on_the_pages_this_lane_wrote():
    """Owner ruling (reference-grade lane): every reference to the portal becomes a path under the
    portal root, so a page cannot go stale when the public name moves. Runnable examples set a BASE
    variable and join the site-relative path onto it. FAILS if an absolute portal URL comes back on any
    of the three pages, which is exactly the regression the DNS cutover would expose.

    Assembled from parts so this module's own source does not contain the literal it forbids."""
    forbidden = "https://" + "ausmt.au"
    hits = []
    for p in PAGES:
        hits += [f"{p.name}:{n}: {line.strip()[:120]}"
                 for n, line in enumerate(_text(p).splitlines(), start=1)
                 if forbidden in line]
    assert not hits, (
        "the interoperability pages must reference the portal by path, not by absolute URL:\n"
        + "\n".join(hits))


def test_no_em_dashes_on_the_pages_this_lane_wrote():
    """The documentation wave's voice charter forbids the em dash outright. These three pages were
    written under it, so the rule is mechanical here rather than a review note. The character is built
    from its code point so that this module, which the same rule covers, does not contain one."""
    em_dash = chr(0x2014)
    for p in PAGES:
        hits = [f"{p.name}:{n}: {line.strip()[:120]}"
                for n, line in enumerate(_text(p).splitlines(), start=1)
                if em_dash in line]
        assert not hits, "em dash (U+2014) found:\n" + "\n".join(hits)
