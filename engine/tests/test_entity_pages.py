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
    # The hub URLs resolve to pages/<kind>/index.html; the static portal pages are shipped with
    # the portal image, not built here, so they are checked against the portal tree WHERE ONE IS
    # VISIBLE. The engine image ships /app/portal holding only src/contract.js (designed topology,
    # engine.Dockerfile), so this leg mirrors the build's own _portal_dir() gate: no checkout, no
    # static-page assertions, exactly as the build reconciliation behaves.
    portal_dir = build_portal._portal_dir()
    for u in entity_locs:
        rel = u.replace(BASE + "/", "")
        if rel in build_portal._SITEMAP_STATIC_PAGES:
            if portal_dir is not None:
                assert (portal_dir / rel).is_file(), \
                    f"sitemap advertises {u} but the portal ships no {rel}"
            continue
        page = (out / "pages" / rel / "index.html") if rel in ("surveys", "collections") \
            else out / "pages" / (rel + ".html")
        assert page.exists(), f"sitemap advertises {u} but no page exists at {page}"
    docs = sorted((out / "products" / "pages-a").glob("*/station.json"))
    for d in docs:
        aid = json.loads(d.read_text(encoding="utf-8"))["ausmt_id"]
        assert (out / "pages" / "stations" / (aid + ".html")).exists(), \
            f"station page for {aid} must exist (the served URL contract), sitemap or not"


def test_the_sitemap_advertises_the_hubs_and_the_static_pages(tmp_path):
    """The sitemap is the crawler's map of the site, and until this lane it carried only the root
    and the entity pages: the two hub pages did not exist, and about/releases/add-survey were
    substantive linked documents that no crawler was pointed at. FAILS IF any of the five is
    missing, or if one of them carries a <lastmod> (none of them has an honest change signal, and
    the lastmod contract is that the field is emitted only where it is true)."""
    surveys = _make_rich_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8").replace("\n", "")
    for rel in ("surveys", "collections", "about.html", "releases.html", "add-survey.html"):
        u = f"{BASE}/{rel}"
        row = re.search(rf"<url><loc>{re.escape(u)}</loc>(.*?)</url>", sitemap)
        assert row, f"the sitemap must advertise {u}"
        assert "<lastmod>" not in row.group(1), \
            f"{u} has no honest change signal, so it must carry no lastmod"


def test_the_build_report_records_the_page_count(tmp_path):
    """FAILS IF build_report.json does not carry the tier-3 page count. pages/ contributes nothing
    to the manifest (it is tier 3, outside the product contract by design), so without this key the
    build's own bookkeeping has no record that the pages were written at all."""
    surveys = _make_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    n_pages = len(list((out / "pages").rglob("*.html")))
    assert report["pages"] == n_pages, \
        f"build_report pages={report.get('pages')} but {n_pages} page files were written"
    bare = _build(surveys, tmp_path / "bare", sitemap=False)
    assert json.loads((bare / "build_report.json").read_text(encoding="utf-8")).get("pages") in (0, None), \
        "a flagless build writes no pages, so it must not claim any"


def test_a_sitemap_page_mismatch_is_a_hard_error(tmp_path, monkeypatch):
    """The reconciliation, RED-proven. build_portal has long CLAIMED that a sitemap URL without a
    page is a hard error, but it only counted the pages and printed the number; nothing compared
    the two, so an advertised 404 could leave the build silently. This drives a synthetic mismatch
    (the emitter writes every page, then one survey page is removed behind the build's back) and
    requires the build to REFUSE. FAILS IF the build completes with a sitemap URL that has no
    page - on the pre-lane engine it completes with rc=0."""
    surveys = _make_survey(tmp_path)
    real = build_portal.pages.emit_pages

    def _lose_one(out, base, **kw):
        n = real(out, base, **kw)
        victim = out / "pages" / "surveys" / "pages-a.html"
        assert victim.is_file(), "fixture must have written the page we are about to lose"
        victim.unlink()
        return n

    monkeypatch.setattr(build_portal.pages, "emit_pages", _lose_one)
    with pytest.raises(RuntimeError, match="surveys/pages-a"):
        build_portal.main(["--surveys", str(surveys), "--out", str(tmp_path / "out"),
                           "--bundle-edi", "--no-validate",
                           "--products", str(tmp_path / "out" / "products"),
                           "--sitemap-base", BASE])


def test_a_missing_station_page_is_a_hard_error(tmp_path, monkeypatch):
    """The other half of the reconciliation: station pages are deliberately NOT advertised in the
    sitemap, so a missing one cannot be caught by the URL sweep - but /stations/<id> is a published
    URL shape that inbound links use, and a missing page 404s it. FAILS IF a station document
    without its page leaves the build."""
    surveys = _make_survey(tmp_path)
    real = build_portal.pages.emit_pages

    def _lose_one(out, base, **kw):
        n = real(out, base, **kw)
        victim = sorted((out / "pages" / "stations").glob("*.html"))[0]
        victim.unlink()
        return n

    monkeypatch.setattr(build_portal.pages, "emit_pages", _lose_one)
    with pytest.raises(RuntimeError, match="station page"):
        build_portal.main(["--surveys", str(surveys), "--out", str(tmp_path / "out"),
                           "--bundle-edi", "--no-validate",
                           "--products", str(tmp_path / "out" / "products"),
                           "--sitemap-base", BASE])


def test_the_report_the_build_leaves_behind_is_the_one_it_validated(tmp_path, monkeypatch):
    """build_report.json is written TWICE on a --sitemap-base build: once before the sitemap block,
    and once again after emit_pages with the page count added. The schema self-check ran on the
    first, pages-less object, so the file actually left on disk was never validated inside the
    build at all - the one artefact the build's own gate did not cover was the one it shipped.

    Driven by an emitter that reports its page count as a string: the report then violates its own
    schema ("pages": {"type": "integer"}) in exactly the write the check could not see. FAILS on
    the pre-fix engine, which completes rc=0 and leaves the non-conforming file on disk."""
    surveys = _make_survey(tmp_path)
    real = build_portal.pages.emit_pages
    monkeypatch.setattr(build_portal.pages, "emit_pages",
                        lambda out, base, **kw: str(real(out, base, **kw)))
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(out), "--bundle-edi",
                            "--no-validate", "--products", str(out / "products"),
                            "--sitemap-base", BASE])
    assert rc == 2, f"a non-conforming build_report must fail the build, got rc={rc}"


def test_the_engine_image_layout_is_not_read_as_a_portal_checkout(tmp_path, monkeypatch):
    """The PRODUCTION build ships no portal, and the static-page leg must know it.

    deploy/docker/engine.Dockerfile copies exactly one portal artifact into the image
    (portal/src/contract.js, so the contract gate can run against real bytes). So <repo>/portal
    EXISTS in the image the box builds with, and contains nothing else. A leg that decides "is a
    portal visible?" by asking whether that directory exists therefore concludes the portal has
    LOST about.html, releases.html and add-survey.html, and `make rebuild-data` aborts on three
    URLs whose documents ship in a different image entirely.

    Modelled by pointing the module at an image-shaped tree and running the deploy's own flags.
    FAILS on the pre-fix engine with "sitemap advertises https://.../about.html but the portal
    ships no about.html" and a RuntimeError out of the reconciliation."""
    image_root = tmp_path / "app"
    (image_root / "portal" / "src").mkdir(parents=True)
    (image_root / "portal" / "src" / "contract.js").write_text("// generated\n", encoding="utf-8")
    monkeypatch.setattr(build_portal, "__file__",
                        str(image_root / "engine" / "extract" / "build_portal.py"))
    surveys = _make_survey(tmp_path)
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(out), "--bundle-edi",
                            "--no-validate", "--products", str(out / "products"),
                            "--sitemap-base", BASE])
    assert rc == 0, f"the image-shaped build must complete, got rc={rc}"
    assert (out / "pages" / "surveys" / "index.html").is_file()
    assert build_portal._portal_dir() is None, (
        "a portal directory holding only the generated contract.js is not a portal checkout")


def test_a_visible_portal_checkout_still_has_its_static_pages_reconciled(tmp_path, monkeypatch):
    """The other side of the same gate: where a REAL portal checkout IS visible (CI, a dev box,
    the build-products lane), a sitemap URL for a static page the portal does not ship is still a
    hard error. FAILS IF the image-layout fix turns the static-page leg into a permanent no-op."""
    checkout = tmp_path / "checkout"
    (checkout / "portal").mkdir(parents=True)
    (checkout / "portal" / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    monkeypatch.setattr(build_portal, "__file__",
                        str(checkout / "engine" / "extract" / "build_portal.py"))
    assert build_portal._portal_dir() is not None, "a checkout with index.html IS a portal tree"
    problems = build_portal._reconcile_pages_with_sitemap(
        tmp_path / "out", f"{BASE}/", [f"{BASE}/", f"{BASE}/about.html"], {})
    assert any("about.html" in p for p in problems), (
        f"a missing static page must still be reported on a real checkout: {problems}")


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
    # The station table: the five default columns, sticky first column. The run and instrument
    # columns moved to the station pages in LANE-CONTRACT-PAGE-HIERARCHY.md B5, which could only
    # follow B4 giving those pages a Runs section; the move is followed fact by fact in
    # test_the_station_table_keeps_five_columns_and_the_rest_moved_to_the_stations, and the station
    # page's own rendering is pinned by test_the_station_page_renders_the_runs_its_own_document
    # _publishes. Restated here rather than deleted, so the survey page's own truth stays asserted.
    for h in ("Station", "Lat", "Lon", "T max (s)", "Time series"):
        assert f"<th>{h}</th>" in page, h
    assert "Deployed" not in page and "Bx coil" not in page, \
        "deployment and instrument columns live on the station pages now"
    assert "ahbao8tk" not in page and "c7ea5dpq" not in page, \
        "instrument PIDs moved to the station pages with the columns that carried them"
    assert "position:sticky" in page, "the station column must pin while the table scrolls"
    assert "52 m @ 0&#176;" not in page, "the dipole cell moved to the station page"
    # contributors grouped by person (roles merged), publications with DOI link
    assert page.count('href="https://orcid.org/0000-0002-9738-7277"') == 1, \
        "duplicate contributor rows must group into one person row"
    assert "Project Leader" in page and "Data Collector" in page
    assert "Imaging things" in page and "10.1080/08123985.2024.9999999" in page
    # og tags on the page (image = per-survey card when Pillow rendered one, else the root card).
    # The URL FORM is pinned, not just the file: the cards live inside the DATA volume, which the
    # box serves under /data/*, so the only reachable URL for pages/og/<slug>.png is
    # {base}/data/pages/og/<slug>.png. A {base}/pages/... form advertises a 404 to every crawler
    # and link-preview fetcher (the @entityPage rewrite is the only other route into that tree and
    # it matches the two-segment entity shapes alone).
    assert 'property="og:title"' in page and 'name="twitter:card"' in page
    m = re.search(r'property="og:image" content="([^"]+)"', page)
    assert m, "og:image required"
    assert m.group(1) in (f"{BASE}/data/pages/og/pages-r.png", f"{BASE}/vendor/social-card.png"), \
        f"og:image must be the SERVED URL form (/data/pages/og/...), got {m.group(1)}"
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


def test_the_survey_page_opens_on_geography_and_names_its_sections(tmp_path):
    """The page hierarchy (design brief 11 to 14 and 41), asserted as ORDER rather than as prose.

    The page used to read cite, embargo, hero, tiles, facts, downloads, contributors, publications,
    stations: a citation box and an unlabelled abstract held the top of the document and the map was
    a 240px right rail, so the one thing a reader opens a survey to see arrived below the fold with
    no section it belonged to. FAILS IF the map stops leading the hero, if the lede is not the
    blurb's own first sentence, if a named section loses its heading or its anchor, if the sections
    fall out of the brief's order, or if the machine-readable links drift back out of Identifiers
    and provenance."""
    surveys = _make_rich_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-r.html").read_text(encoding="utf-8")

    for anchor, heading in (("about", "About this survey"),
                            ("data", "Data and downloads"),
                            ("stations", "Stations"),
                            ("contributors", "Contributors and organisations"),
                            ("identifiers", "Identifiers and provenance")):
        assert f'<h2 id="{anchor}">' in page, f"section {anchor} must carry an h2 with an id anchor"
        assert heading in page, f"section {anchor} must be named {heading!r}"
    order = [page.index(f'<h2 id="{a}">')
             for a in ("about", "data", "stations", "contributors", "identifiers")]
    assert order == sorted(order), f"sections must follow the brief's sequence, got {order}"

    # geography leads: the hero map is above the About prose and above every optional stat tile
    hero = page.index('<div class="hero">')
    assert hero < page.index('<h2 id="about">'), "the hero must open the page, not follow the prose"
    assert hero < page.index("channels recorded"), \
        "the fixed metric core sits with the map; the optional tiles follow the hero"
    assert page.index('aria-label="Survey location in Australia"') < page.index('class="herofacts"'), \
        "the map column must LEAD the hero grid (the metric rail follows it)"

    # the lede is the blurb's first sentence, and the full abstract still renders under About
    assert '<p class="lede">A rich test survey.</p>' in page, "the lede is the blurb's first sentence"
    assert page.index('class="lede"') < hero, "the lede introduces the map, it does not follow it"
    assert page.count("A rich test survey.") >= 2, \
        "the full abstract must still render under About this survey"

    # the machine-readable links moved into Identifiers and provenance
    ident = page.index('<h2 id="identifiers">')
    assert ident < page.index("Machine-readable survey record"), \
        "the machine-readable record link belongs under Identifiers and provenance"
    assert page.index("mtcat 2.0") > ident, "the catalogue schema link moves with it"

    # the reading column stays narrow while main widens on a large screen
    assert "@media(min-width:" in page and "max-width:1120px" in page, \
        "main must widen beyond 840px on large screens"
    assert 'class="lede"' in page and ".lede{" in page and "70ch" in page, \
        "prose keeps a narrow measure even when main widens"


def test_the_citation_is_a_disclosure_and_its_locator_is_source_led(tmp_path):
    """Design brief 15 plus AUSMT-DATA-CITATION-AND-ACKNOWLEDGEMENT-MODEL.md.

    Two defects at once. The Cite-as box held primary visual space near the top of every survey
    page, and it put the AusMT page URL in the LOCATOR slot unconditionally, which cites the AusMT
    page as the object even on a survey whose own record carries a persistent identifier for itself.
    The model is source-led: the locator is the source identifier where one exists, and the AusMT URL
    is the access route otherwise, stated as a separate acknowledgement rather than smuggled into the
    citation.

    pages-c carries a source DOI on its `identifies: entire` row; pages-d carries none. FAILS IF the
    citation is not a disclosure, if a survey with a source identifier still prints the AusMT URL as
    its locator, if a survey WITHOUT one loses its access route, or if the acknowledgement stops
    being a separate verbatim line."""
    surveys = _make_survey(tmp_path, slug="pages-c", name="Pages C")
    (surveys / "pages-c" / "survey.yaml").write_text(
        (surveys / "pages-c" / "survey.yaml").read_text(encoding="utf-8")
        + "creators:\n  - name: Kay, Ben\n    name_type: person\n"
          "related_identifiers:\n"
          "  - {identifier: 10.25914/1ncb-xp10, identifier_type: DOI, identifies: entire,"
          " relation: IsVariantFormOf}\n", encoding="utf-8")
    _make_survey(tmp_path, slug="pages-d", name="Pages D")
    (surveys / "pages-d" / "survey.yaml").write_text(
        (surveys / "pages-d" / "survey.yaml").read_text(encoding="utf-8")
        + "creators:\n  - name: Kay, Ben\n    name_type: person\n", encoding="utf-8")
    out = _build(surveys, tmp_path / "out")
    src = (out / "pages" / "surveys" / "pages-c.html").read_text(encoding="utf-8")
    plain = (out / "pages" / "surveys" / "pages-d.html").read_text(encoding="utf-8")

    for page in (src, plain):
        assert '<details class="cite">' in page, "the citation must become a disclosure"
        assert "<summary>Cite this survey</summary>" in page, "the disclosure must say what it holds"
        assert "Cite as:" in page and "Kay, B." in page, "the formatted citation text is unchanged"
        assert ("Data were accessed through the AusMT national magnetotelluric data portal."
                in page), "the AusMT acknowledgement is a separate verbatim line"
        assert page.index('<details class="cite">') < page.index('class="lede"'), \
            "the citation sits near the title, above the lede and the map"

    assert "<code>https://doi.org/10.25914/1ncb-xp10</code>" in src, \
        "a survey whose record identifies itself must cite THAT identifier"
    assert f"<code>{BASE}/surveys/pages-c</code>" not in src, \
        "the AusMT page URL must not hold the locator slot when a source identifier exists"
    assert f"<code>{BASE}/surveys/pages-d</code>" in plain, \
        "with no source identifier the AusMT URL stays as the access route"


def test_the_time_series_levels_speak_the_portal_vocabulary_and_do_not_collide():
    """Design brief 16, and a real collision. _TS_LEVELS gave BOTH level0 and raw_packed the badge
    L0, so a survey carrying both rendered two panels badged L0 and a station cell reading
    "L0 3.2 GB &#183; L0 41 KB" with nothing to tell the reader which was which. level1_netcdf, which
    ts_access.json emits and the SPA's own TS_LEVELS names, had no panel at all.

    FAILS IF a level loses its portal name, if two levels share a badge, or if level1_netcdf goes
    back to rendering nothing for a register that carries it."""
    pages = _pages_module()
    docs = [{"ausmt_id": "au.s.A1", "station": "A1", "survey_id": "s",
             "location": {"lat": -30.0, "lon": 137.0},
             "data": {"type": "BBMT", "period_max_s": 6360.0}}]
    ts = {"au.s.A1": {"raw_packed": {"bytes": 3242000000, "url_path": "x/A1.zip"},
                      "level0": {"bytes": 41000, "url_path": "x/A1.dat"},
                      "level1_mth5": {"bytes": 5e8, "url_path": "y/A1.h5"},
                      "level1_netcdf": {"bytes": 2e8, "url_path": "z/A1.nc"}}}
    page = pages.survey_page(slug="s", label="S", sm_doc=None,
                             smeta={"slug": "s", "blurb": "B.", "org": "O", "lic": "CC-BY-4.0"},
                             station_docs=docs, bundle_rows=[], ts_access=ts,
                             base="https://x.example")
    for name in ("Packed raw", "Level 0", "Level 1 MTH5", "Level 1 NetCDF"):
        assert f'<span class="lvlname">{name}</span>' in page, f"{name} must render its own panel"
    badges = re.findall(r'<span class="lvlbadge">([^<]+)</span>', page)
    assert len(badges) == 4, badges
    assert len(set(badges)) == len(badges), f"two levels share a badge: {badges}"


def test_downloads_carry_an_action_and_move_the_full_checksum_into_integrity_details(tmp_path):
    """Design brief 16: the download section is an interface component, not a run of technical text.
    Every product row gets its own action, and the complete SHA-256 stops competing with format and
    size for attention.

    The page carried only an 8-character prefix, so the one number a reader needs to verify a
    download was not on the page at all; the full value is in manifest.json, which this emitter
    already reads. FAILS IF an action link goes missing, if the truncated prefix comes back as the
    only checksum on the page, or if a digest on the page is not the manifest's own."""
    surveys = _make_survey(tmp_path, slug="pages-p", name="Pages P")
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-p.html").read_text(encoding="utf-8")
    rows = [b for b in json.loads((out / "manifest.json").read_text(encoding="utf-8"))["bundles"]
            if b["slug"] == "pages-p"]
    assert rows, "fixture must serve bundles"
    assert "<summary>Integrity details</summary>" in page, "the checksums need a disclosure"
    for b in rows:
        assert b["sha256"] in page, f"the FULL sha256 of {b['url']} must reach the page"
        assert f"sha256 {b['sha256'][:8]}&#8230;" not in page, \
            "the truncated prefix is replaced by the whole value, not shown beside it"
    assert page.count(">Download &#8595;</a>") == len(rows), \
        "every bundle row carries its own download action"


def test_the_station_page_renders_the_runs_its_own_document_publishes(tmp_path):
    """Design brief 17's precondition. station_page printed five facts and never touched
    doc["runs"], so every deployment window, dipole geometry, logger and coil PID a station record
    publishes existed on the SURVEY page's wide table and nowhere else. Simplifying that table
    before this lands would delete the metadata from served HTML.

    Every fact asserted here is read back out of the station's OWN served station.json, so the page
    is a VIEW of the public document rather than a second derivation. FAILS IF the runs section, a
    run's window, its rate, a dipole geometry or an instrument PID goes missing, or if noindex
    lapses."""
    surveys = _make_rich_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    doc = json.loads((out / "products" / "pages-r" / "A1" / "station.json").read_text(encoding="utf-8"))
    assert doc.get("runs"), "fixture must publish runs"
    page = (out / "pages" / "stations" / (doc["ausmt_id"] + ".html")).read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex">' in page, "station pages stay out of the index"
    assert '<h2 id="runs">Runs</h2>' in page, "a station with runs must carry a Runs section"

    run = doc["runs"][0]
    assert run["id"] in page, "the run id is a published fact"
    for key, label in (("start", "Deployed"), ("end", "Recovered")):
        assert label in page, f"{label} must render"
        assert str(run["time_period"][key])[:16].replace("T", " ") in page, \
            f"the {label} timestamp must come from the served document"
    assert "1,000 Hz" in page, "the run's nominal sample rate must render"
    logger_pid = run["data_logger"]["identifiers"][0]["identifier"]
    assert logger_pid.rsplit("/", 1)[-1] in page, "the logger PID must link from the station page"
    for ch in run["channels"]:
        if ch.get("dipole_length_m") is not None:
            assert f"{ch['dipole_length_m']:g} m" in page, "dipole lengths must render"
            assert f"{ch['measurement_azimuth_deg']:g}&#176;" in page, "azimuths must render"
        for pid in ((ch.get("sensor") or {}).get("identifiers") or []):
            assert pid["identifier"].rsplit("/", 1)[-1] in page, "coil PIDs must link"

    bare = json.loads(sorted((out / "products" / "pages-a").glob("*/station.json"))[0]
                      .read_text(encoding="utf-8")) if (out / "products" / "pages-a").is_dir() else None
    assert bare is None or bare.get("runs") or True   # the no-runs leg is the unit test below


def test_the_station_page_honours_presence_and_the_unit_value_dual_form():
    """The presence rule on the richest page in the corpus. A run that declares no end, no serial
    and no PID must render none of those rows rather than an empty or dashed one, and a station
    whose document publishes no runs must carry no Runs section at all: absent runs[] means run
    metadata NOT ASSERTED, never "no runs occurred".

    contact_resistance is a unit_value, whose source text is never discarded after normalisation.
    Both forms therefore reach the page: the parsed value with its unit, and the source string it
    was read from. FAILS IF either half is dropped, or if a defaults-only document grows sections."""
    pages = _pages_module()
    doc = {"ausmt_id": "au.s.A1", "station": "A1", "survey": "S",
           "location": {"lat": -30.0, "lon": 137.0},
           "data": {"type": "BBMT", "period_min_s": 0.01, "period_max_s": 100.0, "n_periods": 20},
           "runs": [{"id": "A1_001",
                     "time_period": {"start": "2019-08-20T10:53:03+00:00"},
                     "sample_rate_hz": 1000.0,
                     "data_logger": {"manufacturer": "LEMI", "model": "LEMI-423"},
                     "channels": [
                         {"component": "ex", "dipole_length_m": 43.0,
                          "measurement_azimuth_deg": 180.0,
                          "contact_resistance": {"source_value": "1.82 kilo-ohms",
                                                 "value": 1820.0, "unit": "ohm"}},
                         {"component": "hx", "measurement_azimuth_deg": 0.0,
                          "sensor": {"manufacturer": "LEMI", "model": "LEMI-120",
                                     "serial_number": "134"}}]}]}
    page = pages.station_page(
        doc=doc, survey_slug="s", base="https://x.example",
        ts_levels={"raw_packed": {"bytes": 9868836788, "url_path": "my80/x/A1 [REMOTE].zip"}})
    assert "A1_001" in page and "LEMI-423" in page and "LEMI-120" in page
    assert "1,820 ohm" in page and "1.82 kilo-ohms" in page, \
        "a unit_value renders the normalised value AND the source text it came from"
    assert "Deployed" in page and "Recovered" not in page, \
        "a run with no end declares none; an absent key renders nothing"
    assert "serial 134" in page, "a serial the document carries renders"
    assert '<h2 id="time-series">Time series</h2>' in page
    assert "my80/x/A1 [REMOTE].zip" in page, "the archive path renders as text, verbatim"
    assert "https://thredds.nci.org.au/thredds/fileServer/" in page, \
        "the path is relative, so the page must name the host it is relative to"
    assert "9.9 GB" in page, "the size comes from the register"

    bare = pages.station_page(doc={"ausmt_id": "au.s.A2", "station": "A2", "survey": "S",
                                   "location": {}, "data": {}},
                              survey_slug="s", base="https://x.example")
    assert "Runs" not in bare, "no runs[] means no Runs section, not an empty one"
    assert "Time series" not in bare, "no register rows means no time-series section"
    assert "withheld or generalised by the data custodian" in bare, \
        "the withheld-location line is unchanged"


def test_the_station_table_keeps_five_columns_and_the_rest_moved_to_the_stations(tmp_path):
    """Design brief 17, and it can only run AFTER the station pages carry the detail (B4).

    The default table was 13 columns wide inside an 840px column, forced to scroll horizontally by
    an unconditional min-width of 1180px that a 5-column table also paid. The deployment and
    instrument columns are now behind the station pages that carry them, and this test FOLLOWS the
    move: every column removed from the survey table is asserted PRESENT on the station page of the
    station whose row carried it. FAILS IF a default column goes missing, if a moved column comes
    back, if a moved fact is on neither page, or if the width floor returns."""
    surveys = _make_rich_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-r.html").read_text(encoding="utf-8")
    doc = json.loads((out / "products" / "pages-r" / "A1" / "station.json").read_text(encoding="utf-8"))
    stn = (out / "pages" / "stations" / (doc["ausmt_id"] + ".html")).read_text(encoding="utf-8")

    for h in ("Station", "Lat", "Lon", "T max (s)", "Time series"):
        assert f"<th>{h}</th>" in page, f"{h} is a default column"
    for h in ("Deployed", "Recovered", "Rate (Hz)", "Ex", "Ey", "Logger", "Bx coil", "By coil"):
        assert f"<th>{h}</th>" not in page, f"{h} belongs on the station pages now"
    stbl = re.search(r"\.stbl\{([^}]*)\}", page).group(1)
    assert "min-width" not in stbl, \
        f"a five-column table must not be forced into a horizontal scrollbar: .stbl{{{stbl}}}"
    assert "position:sticky" in page, "the station column still pins while the table scrolls"

    # the move, followed fact by fact on the station whose survey row used to carry them
    run = doc["runs"][0]
    for key in ("start", "end"):
        assert str(run["time_period"][key])[:16].replace("T", " ") in stn
    assert f"{run['sample_rate_hz']:,g} Hz" in stn
    for pid in ([run["data_logger"]["identifiers"][0]["identifier"]]
                + [r["identifier"] for ch in run["channels"]
                   for r in ((ch.get("sensor") or {}).get("identifiers") or [])]):
        tail = pid.rsplit("/", 1)[-1]
        assert tail in stn, f"{tail} must be on the station page"
        assert tail not in page, f"{tail} must have left the survey table"
    for ch in run["channels"]:
        if ch.get("dipole_length_m") is not None:
            assert f"{ch['dipole_length_m']:g} m" in stn
            assert f"{ch['dipole_length_m']:g} m" not in page


def test_the_survey_page_links_up_the_site_and_into_its_collection(tmp_path):
    """The entity link graph, all of it at once. Before this lane a survey page had NO way back to
    the site root, its "All surveys" button pointed at a hash route that does not exist (28 links
    site-wide, including the 404 page's own recovery link), and nothing on any survey page named
    the collection it belongs to - so the graph ran collection -> surveys only and the collection
    page had zero inbound links. FAILS IF the site crumb, the working hub link, or the collection
    edge is missing, or if the dead hash route reappears."""
    surveys = _make_rich_survey(tmp_path)
    pkg = surveys / "pages-r"
    y = (pkg / "survey.yaml").read_text(encoding="utf-8")
    (pkg / "survey.yaml").write_text(y + "collection:\n  id: testcoll\n  title: AusLAMP Test\n",
                                     encoding="utf-8")
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-r.html").read_text(encoding="utf-8")
    assert ('<p class="crumb"><a href="/">AusMT</a> / <a href="/surveys">surveys</a> / '
            "Pages R</p>") in page, "the survey page must carry the site crumb"
    assert '<a class="navbtn" href="/surveys">&#8592; All surveys</a>' in page, \
        "the back-nav must reach the surveys hub, not a hash route"
    assert 'href="/#/surveys"' not in page, "the dead hash route must be gone from the page"
    assert 'Part of the <a href="/collections/testcoll">AusLAMP Test</a> collection' in page, \
        "a member survey must link its collection as discovery (not as a citable parent)"
    coll = (out / "pages" / "collections" / "testcoll.html").read_text(encoding="utf-8")
    assert ('<p class="crumb"><a href="/">AusMT</a> / <a href="/collections">collections</a> / '
            "AusLAMP Test</p>") in coll, "the collection crumb must link the collections hub"


def test_a_survey_without_a_collection_says_nothing_about_one(tmp_path):
    """FAILS IF the collection line renders for a survey that declares no membership. The edge is a
    fact from the survey's own record; absence makes no assertion."""
    surveys = _make_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-a.html").read_text(encoding="utf-8")
    assert "Part of the" not in page and "/collections/" not in page


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
    """No placeholder panels (owner ruling): a survey with raw archives gets the packed-raw card and
    per-station sizes; levels the register does not carry render nothing at all.

    Level names and badges follow portal/src/state.js TS_LEVELS as of the download-cards commit
    (LANE-CONTRACT-PAGE-HIERARCHY.md B3), so "Raw time series" is now "Packed raw", "MTH5 time
    series" is "Level 1 MTH5", and the L0 badge is no longer shared by two levels."""
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
    assert "Packed raw" in page and "1 of 1 stations" in page
    assert "Raw 3.2 GB" in page, "the table cell states the level and the real size"
    # The download panel used to send a reader standing on THIS survey's page to the bare map with
    # nothing selected (34 occurrences across 17 pages). It keeps the survey they were reading.
    assert '<a href="/#/survey/s">Build a download script</a>' in page, \
        "the download-script action must keep the survey context, not point at the bare map"
    assert "Level 1 MTH5" not in page, "an absent level must render no panel"
    page2 = pages.survey_page(slug="s", label="S", sm_doc=None,
                              smeta={"slug": "s", "blurb": "B.", "org": "O", "lic": "CC-BY-4.0"},
                              station_docs=docs, bundle_rows=[],
                              ts_access={"au.s.A1": {"level1_mth5": {"bytes": 5e8, "url_path": "y"}}},
                              base="https://x.example")
    assert "Level 1 MTH5" in page2 and '<span class="lvlbadge">L1 MTH5</span>' in page2


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
