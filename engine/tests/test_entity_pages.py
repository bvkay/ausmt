"""Tier-3 entity landing pages (the discoverability lane).

The path-URL contract published /surveys/<slug>, /stations/<ausmt_id> and /collections/<id> as the
permanent URL shapes; tier 1 301'd them into the SPA's hash routes, which crawlers cannot see, so
the whole corpus indexed as one page. Tier 3 keeps every published URL and serves REAL HTML there:
the engine emits one static page per survey, station and collection into <out>/pages/, rendered
ONLY from the already-served public documents (survey-metadata.json / station.json / the
collections rollup), so a page can never disclose anything the gated products do not already
publish - the C42 leak posture is inherited, not re-implemented, and test_coord_access's
whole-tree sweep audits the pages like every other emitter.

Emission rides --sitemap-base exactly as the sitemap does: same flag, same URL base, and the two
outputs must agree (every sitemap URL has a page; no orphan pages), so the sitemap can never
advertise a 404. Without the flag no pages directory exists and the build is byte-identical to a
pre-lane build.
"""
import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402

SAMPLE_EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))

BASE = "https://ausmt.auscope.org.au"


def _make_survey(tmp_path, *, blurb="A test survey.", slug="pages-a", name="Pages A"):
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\norganisation: Test Org\n"
        f"access: open\nlicense: CC-BY-4.0\nabstract: {json.dumps(blurb)}\n", encoding="utf-8")
    for src in SAMPLE_EDIS:
        (edir / src.name).write_text(src.read_text(encoding="latin-1"), encoding="latin-1")
    return tmp_path / "surveys"


def _build(surveys, out, *, sitemap=True, extra=()):
    argv = ["--surveys", str(surveys), "--out", str(out), "--bundle-edi", "--no-validate",
            "--products", str(out / "products")]
    if sitemap:
        argv += ["--sitemap-base", BASE]
    argv += list(extra)
    rc = build_portal.main(argv)
    assert rc == 0, f"build rc={rc}"
    return out


def test_pages_ride_the_sitemap_flag_and_agree_with_it(tmp_path):
    """FAILS IF pages are emitted without --sitemap-base (a flagless build must stay byte-identical
    to a pre-lane build), a sitemap URL lacks a page (an advertised 404), a station URL appears in
    the sitemap (station pages exist for the URL contract but are deliberately unadvertised: 2,625
    templated documents would read as thin content and dilute the pages that carry the ranking),
    or a station PAGE goes missing (the served /stations/<id> shape would 404)."""
    surveys = _make_survey(tmp_path)
    bare = _build(surveys, tmp_path / "bare", sitemap=False)
    assert not (bare / "pages").exists(), "no --sitemap-base must mean no pages directory"

    out = _build(surveys, tmp_path / "out")
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    entity_locs = [u for u in locs if u != BASE + "/"]
    assert entity_locs, "the sitemap must advertise entity URLs"
    assert not any("/stations/" in u for u in entity_locs), \
        "station URLs must stay OUT of the sitemap (unadvertised-but-served posture)"
    for u in entity_locs:
        rel = u.replace(BASE + "/", "")
        page = out / "pages" / (rel + ".html")
        assert page.exists(), f"sitemap advertises {u} but no page exists at {page}"
    docs = sorted((out / "products" / "pages-a").glob("*/station.json"))
    for d in docs:
        aid = json.loads(d.read_text(encoding="utf-8"))["ausmt_id"]
        assert (out / "pages" / "stations" / (aid + ".html")).exists(), \
            f"station page for {aid} must exist (the served URL contract), sitemap or not"


def test_survey_page_content_and_dataset_jsonld(tmp_path):
    """FAILS IF the survey page loses the parts search engines actually read: a title carrying the
    survey name, a canonical link at the published URL, the blurb prose, the interactive-portal
    link, download links only for bundles the manifest actually serves, and a schema.org Dataset
    JSON-LD block whose fields parse and match the page."""
    surveys = _make_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-a.html").read_text(encoding="utf-8")
    assert "<title>Pages A" in page and "AusMT" in page, "title must lead with the survey name"
    assert f'<link rel="canonical" href="{BASE}/surveys/pages-a">' in page, "canonical must be the published URL"
    assert "A test survey." in page, "the survey blurb prose must render"
    assert 'href="/#/survey/pages-a"' in page, "the interactive-portal link must deep-link the SPA"
    m = re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>', page)
    assert m, "a JSON-LD block is required"
    ld = json.loads(m.group(1))
    assert ld["@type"] == "Dataset", ld
    assert ld["name"].startswith("Pages A"), ld["name"]
    assert ld["url"] == f"{BASE}/surveys/pages-a"
    assert "creativecommons.org/licenses/by/4.0" in ld.get("license", ""), \
        "the licence must resolve to the canonical CC URL"
    assert ld.get("includedInDataCatalog", {}).get("name") == "AusMT", ld.get("includedInDataCatalog")
    zips = re.findall(r'href="(/data/bundles/[^"]+)"', page)
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    served = {"/data/" + r["url"] for r in man["bundles"]}
    for z in zips:
        assert z in served, f"page links {z} which the manifest does not serve"
    assert zips, "the survey page must link its served bundles"


def test_station_page_uses_only_the_served_document(tmp_path):
    """FAILS IF a station page states coordinates that differ from the station.json document's own
    (the served, gated presentation) - the page must be a VIEW of the public document, never a
    second derivation from records."""
    surveys = _make_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    docs = sorted((out / "products" / "pages-a").glob("*/station.json"))
    assert docs, "fixture must serve station documents"
    doc = json.loads(docs[0].read_text(encoding="utf-8"))
    page = (out / "pages" / "stations" / (doc["ausmt_id"] + ".html")).read_text(encoding="utf-8")
    loc = doc["location"]
    assert f"{loc['lat']}" in page and f"{loc['lon']}" in page, \
        "the station page must state the document's own served coordinates"
    assert doc["station"] in page and "Pages A" in page, "station id and survey name must render"
    assert f'href="/#/station/{doc["ausmt_id"]}"' in page, "the SPA deep link must be present"
    assert f'href="{BASE}/surveys/pages-a"' in page.replace("&amp;", "&") or \
           'href="/surveys/pages-a"' in page, "the page must link up to its survey page"
    assert '<meta name="robots" content="noindex">' in page, \
        "station pages must carry noindex (served for the contract, kept out of the index)"


def test_hostile_blurb_is_escaped(tmp_path):
    """FAILS IF curated free text reaches the page unescaped. The blurb is curator-authored YAML,
    but these pages are a public serving surface and the portal's hostile-blurb-inert precedent
    applies here too."""
    surveys = _make_survey(tmp_path, blurb="<script>alert(1)</script> & <b>bold</b>",
                           slug="pages-x", name="Pages X")
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-x.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in page, "hostile blurb must not reach the page live"
    assert "&lt;script&gt;" in page, "the blurb must render escaped, not dropped"


# ---- the design of record (v8): the enriched survey page ----------------------------------------

def _make_rich_survey(tmp_path):
    """One survey exercising every enrichment surface: creators (the citation authors),
    contributors with duplicate-per-role rows, funders with a grant id, publications, typed
    related identifiers (one a full dx.doi.org URL, the corpus shape), a declared geographic
    extent, release notes (the sitemap lastmod source), and curated run metadata with PIDs."""
    surveys = _make_survey(tmp_path, blurb="A rich test survey.", slug="pages-r", name="Pages R")
    pkg = surveys / "pages-r"
    (pkg / "survey.yaml").write_text(
        "name: Pages R\nslug: pages-r\ncountry: Australia\nregion: South Australia\n"
        "version: 1.2.3\norganisation:\n  name: Test Org\n  ror: https://ror.org/00892tw58\n"
        "access: open\nlicense: CC-BY-4.0\nabstract: A rich test survey.\n"
        "processing:\n  software: LEMIMT\n"
        "geographic_extent:\n  west: 136.9\n  east: 137.1\n  south: -30.3\n  north: -30.1\n"
        "creators:\n  - name: Kay, Ben\n    name_type: person\n"
        "  - name: Heinson, Graham\n    name_type: person\n"
        "contributors:\n"
        "  - {name: 'Kay, Ben', name_type: person, role: ProjectLeader, orcid: 0000-0002-9738-7277}\n"
        "  - {name: 'Kay, Ben', name_type: person, role: DataCollector, orcid: 0000-0002-9738-7277}\n"
        "  - {name: 'Heinson, Graham', name_type: person, role: RightsHolder, orcid: 0000-0001-7106-0789}\n"
        "funding:\n  - organisation: Test Survey Office\n    grant_id: ADI RD99-999\n"
        "publications:\n  - {author: 'Kay B', year: '2024', title: Imaging things,"
        " journal: Exploration Geophysics, doi: 10.1080/08123985.2024.9999999}\n"
        "related_identifiers:\n"
        "  - {identifies: collection, identifier: 10.25914/sv5r-zw68, identifier_type: DOI, relation: IsPartOf}\n"
        "  - {identifies: level2, identifier: 'http://dx.doi.org/10.11636/Record.2020.011',"
        " identifier_type: DOI, relation: IsVariantFormOf}\n"
        "release_notes:\n  - {version: 1.0.0, date: '2026-01-05', note: first}\n"
        "  - {version: 1.2.3, date: '2026-03-09', note: latest}\n",
        encoding="utf-8")
    (pkg / "run-ids.yaml").write_text("run_ids:\n  A1: [A1_001]\n  A2: [A2_001]\n", encoding="utf-8")
    (pkg / "run-metadata.csv").write_text(
        "station_id,start,end,sample_rate_hz,dipole_length_ex_m,dipole_length_ey_m,"
        "azimuth_ex_deg,azimuth_ey_deg,logger_manufacturer,logger_model,logger_serial,logger_pid,"
        "sensor_manufacturer,sensor_model,sensor_bx_serial,sensor_bx_pid,sensor_by_serial,sensor_by_pid\n"
        "A1,2022-02-12T07:59:23+00:00,2022-02-14T09:20:24+00:00,1000,52,51.5,0,90,"
        "LEMI,LEMI-423,#0040,https://doi.org/10.82388/c7ea5dpq,LEMI,LEMI-120,"
        "125,https://doi.org/10.82388/ahbao8tk,126,https://doi.org/10.82388/1nhybg3w\n"
        "A2,2022-02-13T08:16:48+00:00,2022-02-15T07:04:12+00:00,1000,50,50,0,90,"
        "LEMI,LEMI-423,#0041,https://doi.org/10.82388/ir7azuq1,LEMI,LEMI-120,"
        "127,,128,\n", encoding="utf-8")
    return surveys


def test_the_rich_survey_page_carries_the_design_of_record(tmp_path):
    surveys = _make_rich_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-r.html").read_text(encoding="utf-8")

    # citation box: surname-plus-initial authors from the creators-driven cite record
    assert "Cite as:" in page and "Kay, B.; Heinson, G." in page, "cite box with initials"
    assert "Magnetotelluric survey &#183; South Australia &#183; Test Org" in page, \
        "the subtitle carries region and organisation"
    # page nav replaces the CTA (owner ruling: no portal button)
    assert "All surveys" in page and "View all stations on the main map" in page
    assert "Open in the interactive portal" not in page
    # maps: the shared-outline minimap always; the footprint zoom for this compact extent
    assert 'aria-label="Survey location in Australia"' in page
    assert 'aria-label="Station grid detail"' in page
    # stat tiles from the served documents and the ingested runs (owner rulings: a zero tipper
    # count shows the channels-recorded tile instead; the sample rate is a tile; the dipole
    # summary is gone - the station table carries dipoles)
    assert "period coverage" in page
    assert "channels recorded" in page and "Ex Ey Bx By" in page
    assert "tipper stations" not in page, "a zero tipper count must not render a tile"
    assert "sample rate" in page and "1,000 Hz" in page
    assert "Dipoles" not in page, "the dipole summary row is retired (the table carries dipoles)"
    assert "instrument PID" not in page, "the survey-level platform PID is retired"
    # the station table: run columns, PIDs as links, sticky first column
    for h in ("Deployed", "Recovered", "Rate (Hz)", "Logger", "Bx coil", "Time series"):
        assert h.replace(" ", "&#8202;") in page.replace("&#8202;", " ") or h in page.replace("&#8202;", " "), h
    assert "ahbao8tk" in page and "c7ea5dpq" in page, "instrument PIDs must link in the table"
    assert "position:sticky" in page, "the station column must pin while the table scrolls"
    assert "52 m @ 0&#176;" in page, "dipole cells carry length and azimuth"
    # contributors grouped by person (roles merged), publications with DOI link
    assert page.count('href="https://orcid.org/0000-0002-9738-7277"') == 1, \
        "duplicate contributor rows must group into one person row"
    assert "Project Leader" in page and "Data Collector" in page
    assert "Imaging things" in page and "10.1080/08123985.2024.9999999" in page
    # og tags on the page (image = per-survey card when Pillow rendered one, else the root card)
    assert 'property="og:title"' in page and 'name="twitter:card"' in page
    m = re.search(r'property="og:image" content="([^"]+)"', page)
    assert m, "og:image required"
    if "/pages/og/" in m.group(1):
        card = out / "pages" / "og" / "pages-r.png"
        assert card.is_file() and card.read_bytes()[:2] == b"\x89P", "referenced card must exist"

    # NO dash glyphs and NO ticks anywhere on the page (owner rulings)
    assert "–" not in page and "—" not in page, "no en/em dashes"
    assert "✓" not in page and "&#10003;" not in page, "no tick glyphs"

    # JSON-LD enrichment, including the spatialCoverage fix (the declared extent tuple renders)
    ld = json.loads(re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>', page).group(1))
    assert ld["spatialCoverage"]["geo"]["box"] == "-30.3 136.9 -30.1 137.1", \
        "spatialCoverage must render from the DECLARED (west, east, south, north) extent"
    assert ld["identifier"] == f"{BASE}/surveys/pages-r"
    assert "https://doi.org/10.25914/sv5r-zw68" in ld["sameAs"]
    assert "http://dx.doi.org/10.11636/Record.2020.011" in ld["sameAs"], \
        "a full-URL related identifier must pass through as-is, never double-prefixed"
    assert ld["funder"][0]["name"] == "Test Survey Office"
    assert ld["citation"][0]["name"] == "Imaging things"
    assert ld["measurementTechnique"] == "magnetotellurics"
    assert ld["creator"]["sameAs"] == "https://ror.org/00892tw58"
    assert ld["version"] == "1.2.3"


def test_sitemap_lastmod_comes_from_release_notes_only(tmp_path):
    """lastmod is emitted ONLY where it is honest: the survey's latest release-note date. A survey
    without release notes gets none (a per-build stamp on identical content would teach crawlers to
    distrust the field)."""
    surveys = _make_rich_survey(tmp_path)
    _make_survey(tmp_path, slug="pages-b", name="Pages B")   # same tree, no release notes
    out = _build(surveys, tmp_path / "out")
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert "<loc>https://ausmt.auscope.org.au/surveys/pages-r</loc><lastmod>2026-03-09</lastmod>" \
        in sitemap.replace("\n", "")
    row = re.search(r"<url><loc>[^<]*surveys/pages-b</loc>(.*?)</url>", sitemap.replace("\n", ""))
    assert row and "<lastmod>" not in row.group(1), "no release notes must mean no lastmod"


def test_the_embargoed_survey_page_says_so(tmp_path):
    """An embargoed survey currently renders like an open one with silently absent downloads; the
    page must state the embargo instead."""
    surveys = _make_survey(tmp_path, slug="pages-e", name="Pages E")
    pkg = surveys / "pages-e"
    y = (pkg / "survey.yaml").read_text(encoding="utf-8")
    (pkg / "survey.yaml").write_text(
        y.replace("access: open", "access:\n  level: embargoed\n  embargo_until: '2027-02-01'"),
        encoding="utf-8")
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-e.html").read_text(encoding="utf-8")
    assert "under embargo" in page and "2027-02-01" in page
    # The DISCOVERY layer still renders (owner ruling): the catalogue is discovery-universal, so
    # an embargoed survey's page shows its station locations and band even while the science
    # products are withheld.
    minimap = re.search(r'aria-label="Survey location in Australia".*?</svg>', page, re.S)
    assert minimap and "<circle" in minimap.group(0), "embargoed pages must map their stations"
    assert re.search(r"<td>-3\d\.\d+</td>", page), \
        "the station table must carry the catalogue's public coordinates"


# ---- unit pins: time-series levels and the collection rollup ------------------------------------

def _pages_module():
    sys.path.insert(0, str(REPO / "extract"))
    import _pages
    return _pages


def test_ts_panels_and_cells_render_only_the_levels_the_register_carries():
    """No placeholder panels (owner ruling): a survey with raw archives gets the L0 panel and
    per-station sizes; levels the register does not carry render nothing at all."""
    pages = _pages_module()
    docs = [{"ausmt_id": "au.s.A1", "station": "A1", "survey_id": "s",
             "location": {"lat": -30.0, "lon": 137.0},
             "data": {"type": "BBMT", "period_max_s": 6360.0},
             "diagnostics": {"tipper_available": False}}]
    ts = {"au.s.A1": {"raw_packed": {"bytes": 3242000000, "url_path": "x/A1.zip"}}}
    page = pages.survey_page(slug="s", label="S", sm_doc=None,
                             smeta={"slug": "s", "blurb": "B.", "org": "O", "lic": "CC-BY-4.0"},
                             station_docs=docs, bundle_rows=[], ts_access=ts,
                             base="https://x.example")
    assert "Raw time series" in page and "1 of 1 stations" in page
    assert "L0 3.2 GB" in page, "the table cell states the level and the real size"
    assert "MTH5 time series" not in page, "an absent level must render no panel"
    page2 = pages.survey_page(slug="s", label="S", sm_doc=None,
                              smeta={"slug": "s", "blurb": "B.", "org": "O", "lic": "CC-BY-4.0"},
                              station_docs=docs, bundle_rows=[],
                              ts_access={"au.s.A1": {"level1_mth5": {"bytes": 5e8, "url_path": "y"}}},
                              base="https://x.example")
    assert "MTH5 time series" in page2 and "L1" in page2


def test_collection_jsonld_rolls_up_member_licence_creators_and_years():
    pages = _pages_module()
    members = [("A", "a"), ("B", "b")]
    smeta = [{"lic": "CC-BY-4.0", "org": "Org One", "year_start": 2013, "year_end": 2016},
             {"lic": "CC-BY-4.0", "org": "Org Two", "year_start": 2018, "year_end": 2021}]
    page = pages.collection_page(cid="c", coll={"title": "C", "n_stations": 5},
                                 member_slugs=members, member_smeta=smeta,
                                 base="https://x.example")
    import re as _re
    ld = json.loads(_re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>', page).group(1))
    assert ld["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert [o["name"] for o in ld["creator"]] == ["Org One", "Org Two"]
    assert ld["temporalCoverage"] == "2013/2021"
    mixed = smeta[:1] + [{"lic": "CC0-1.0", "org": "Org Two"}]
    page2 = pages.collection_page(cid="c", coll={"title": "C"}, member_slugs=members,
                                  member_smeta=mixed, base="https://x.example")
    ld2 = json.loads(_re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>', page2).group(1))
    assert "license" not in ld2, "mixed member licences must state nothing (never overclaim)"


def test_bundle_labels_speak_the_manifest_vocabulary():
    """The manifest spells the survey-MTH5 bundle's format "mth5" (the station-resource vocabulary
    says "survey-mth5"); the label map must carry BOTH, or the page prints the raw key - the exact
    defect the first full-corpus preview surfaced."""
    pages = _pages_module()
    assert pages._BUNDLE_LABELS["mth5"][0] == "Survey MTH5 bundle"
    assert pages._BUNDLE_LABELS["survey-mth5"][0] == "Survey MTH5 bundle"
    assert pages._BUNDLE_LABELS["mth5"][1] == "application/x-hdf5"


def test_map_upgrades_scale_bar_type_colours_and_collection_scatter(tmp_path):
    """The maps pass (owner rulings 2026-08-28): the footprint zoom carries a scale bar, dots
    speak the portal's type palette, a sub-degree survey's minimap draws the ring only, and the
    collection page carries the member-coloured scatter with its legend."""
    surveys = _make_rich_survey(tmp_path)
    pkg = surveys / "pages-r"
    y = (pkg / "survey.yaml").read_text(encoding="utf-8")
    (pkg / "survey.yaml").write_text(y + "collection:\n  id: testcoll\n  title: Test Collection\n",
                                     encoding="utf-8")
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-r.html").read_text(encoding="utf-8")
    assert "km</text>" in page, "the footprint zoom must carry a scale bar"
    assert "#5B54D6" in page, "dots must speak the type palette (BBMT indigo)"
    minimap = re.search(r'aria-label="Survey location in Australia".*?</svg>', page, re.S).group(0)
    assert "<circle" in minimap and 'stroke="#EF7256"' in minimap
    assert 'fill="#5B54D6"' not in minimap, \
        "a sub-degree survey's minimap draws the ring only; the zoom panel owns the dots"
    coll = (out / "pages" / "collections" / "testcoll.html").read_text(encoding="utf-8")
    assert "Member stations of" in coll, "the collection page must carry the member scatter"
    assert "#2E8FA3" in coll, "member colours use the portal collection palette"
    assert "Pages R" in coll


def test_activity_scope_identifiers_render_as_project_links():
    pages = _pages_module()
    smeta = {"slug": "s", "blurb": "B.", "org": "O", "lic": "CC-BY-4.0",
             "related_identifiers": [
                 {"identifier": "https://www.auscope.org.au/ansir-projects?id=ANSIR-2022-001",
                  "identifier_type": "URL", "scope": "activity", "relation": "IsDocumentedBy"}]}
    page = pages.survey_page(slug="s", label="S", sm_doc=None, smeta=smeta,
                             station_docs=[], bundle_rows=[], ts_access=None,
                             base="https://x.example")
    assert "Project" in page and ">ANSIR-2022-001</a>" in page
    assert 'href="https://www.auscope.org.au/ansir-projects?id=ANSIR-2022-001"' in page
