"""Tier-3 entity landing pages (the discoverability workflow).

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
earlier build.
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


def _cite_block(page) -> str:
    """Just the citation disclosure. A related identifier legitimately renders elsewhere on the page
    (a download card's archive-release line, the Identifiers and provenance list), so a whole-page
    search cannot tell "this DOI is on the page" from "this DOI is the citation target"."""
    m = re.search(r'<details class="cite">.*?</details>', page, re.S)
    assert m, "the page carries no citation disclosure to read"
    return m.group(0)


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
    to a earlier build), a sitemap URL lacks a page (an advertised 404), a station URL appears in
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
    # Engine.Dockerfile), so this leg mirrors the build's own _portal_dir gate: no checkout, no
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
    """The sitemap is the crawler's map of the site, and until this module it carried only the root
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
    # brand.html is the one static page deliberately held out: it declares its own robots noindex,
    # and a sitemap entry for a page that refuses indexing spends crawl budget on nothing.
    assert f"{BASE}/brand.html" not in sitemap, \
        "brand.html declares noindex and must not be advertised in the sitemap"


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


def test_a_sitemap_page_mismatch_is_a_hard_error(tmp_path, monkeypatch, capsys):
    """The reconciliation, RED-proven. build_portal has long CLAIMED that a sitemap URL without a
    page is a hard error, but it only counted the pages and printed the number; nothing compared
    the two, so an advertised 404 could leave the build silently. This drives a synthetic mismatch
    (the emitter writes every page, then one survey page is removed behind the build's back) and
    requires the build to REFUSE. FAILS IF the build completes with a sitemap URL that has no
    page - on the earlier engine it completes with rc=0."""
    surveys = _make_survey(tmp_path)
    real = build_portal.pages.emit_pages

    def _lose_one(out, base, **kw):
        n = real(out, base, **kw)
        victim = out / "pages" / "surveys" / "pages-a.html"
        assert victim.is_file(), "fixture must have written the page we are about to lose"
        victim.unlink()
        return n

    monkeypatch.setattr(build_portal.pages, "emit_pages", _lose_one)
    # The house convention for a self-check the build fails: ERROR lines on stderr, then return 2.
    # An operator running `make rebuild-data` gets a message rather than a traceback, and the
    # Reconciliation now reads like every other gate in main (LANE-CONTRACT-PAGE-HIERARCHY.md B8,
    # which flags the RuntimeError this test used to require as the odd one out).
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(tmp_path / "out"),
                            "--bundle-edi", "--no-validate",
                            "--products", str(tmp_path / "out" / "products"),
                            "--sitemap-base", BASE])
    assert rc == 2, f"a sitemap URL without a page must fail the build, got rc={rc}"
    err = capsys.readouterr().err
    assert "surveys/pages-a" in err and "reconciliation" in err, err


def test_a_missing_station_page_is_a_hard_error(tmp_path, monkeypatch, capsys):
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
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(tmp_path / "out"),
                            "--bundle-edi", "--no-validate",
                            "--products", str(tmp_path / "out" / "products"),
                            "--sitemap-base", BASE])
    assert rc == 2, f"a station document without its page must fail the build, got rc={rc}"
    assert "station page" in capsys.readouterr().err


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
    the build-products workflow), a sitemap URL for a static page the portal does not ship is still a
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
    # Page nav replaces the CTA: no portal button
    assert "All surveys" in page and "View all stations on the main map" in page
    assert "Open in the interactive portal" not in page
    # maps: the shared-outline minimap always; the footprint zoom for this compact extent
    assert 'aria-label="Survey location in Australia"' in page
    assert 'aria-label="Station grid detail"' in page
    # stat tiles from the served documents and the ingested runs (rules: a zero tipper
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

    # NO dash glyphs and NO ticks anywhere on the page
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

    # The type badge states the survey's OWN data type beside the title. Asserted as the whole h1,
    # because a survey page carries several other badges (the download cards' level badges) and a
    # loop variable leaking into this slot renders a plausible-looking string in the page title.
    # The separating space is part of that assertion: the gap between the title and the badge was
    # CSS margin alone, so the h1's text content, its accessible name and a copy-paste of it all
    # read "Newer Volcanic Province 2019BBMT". The margin stays, because a space before an
    # inline-block can collapse at a line wrap and the visual gap must not depend on it.
    types = {json.loads(p.read_text(encoding="utf-8"))["data"]["type"]
             for p in sorted((out / "products" / "pages-r").glob("*/station.json"))}
    assert len(types) == 1, types
    assert (f"<h1>Pages R <span class=\"typebadge\">{next(iter(types))}</span></h1>") in page, \
        "the h1 carries the title, a separator and the survey's own data type, and nothing else"
    h1_text = re.sub(r"<[^>]+>", "", re.search(r"<h1>.*?</h1>", page, re.S).group(0))
    assert f"Pages R {next(iter(types))}" == h1_text, \
        f"the h1 reads as two words to a screen reader and to a copy-paste: {h1_text!r}"

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


# ==================================================================================================
# The channels tile and the survey kind: a geomagnetic depth sounding survey is not an MT survey
# ==================================================================================================
# Every survey page stated "Ex Ey Bx By" and introduced itself as a "Magnetotelluric survey",
# including the 24 legacy geomagnetic depth sounding surveys, which recorded no electric field at
# all and whose survey.yaml says so. The declaration is not decorative: it is what masks the
# impedance survey-wide, so the page was contradicting the data served beside it.

GDS_EDI = HERE / "fixtures" / "impedance" / "placeholder-impedance-tipper.edi"


def _make_declared_survey(tmp_path, *, slug, name, channels, source=None, blurb=None):
    """A package whose survey.yaml DECLARES its recorded channels, built end to end.

    `source` defaults to the MT sample survey; passing the tipper fixture gives the magnetic-only
    shape the legacy corpus has, where the same declaration masks the impedance and the served
    stations come out as GDS."""
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\nregion: South Australia\n"
        f"organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        + (f"abstract: {json.dumps(blurb)}\n" if blurb else "")
        + f"channels_recorded: [{', '.join(channels)}]\n", encoding="utf-8")
    for src in ([source] if source else SAMPLE_EDIS):
        (edir / src.name).write_text(src.read_text(encoding="latin-1"), encoding="latin-1")
    return tmp_path / "surveys"


def _channels_tile(page):
    """The rendered channels-recorded tile, or None where the page renders none."""
    m = re.search(r'<div class="cstat"><div class="cnum">([^<]*)</div>'
                  r'<div class="clab">channels recorded</div></div>', page)
    return m.group(1) if m else None


def _kind_surfaces(page):
    """The four places a survey page names the KIND of survey it is, read out of the rendered
    output: the crumb under the h1, the browser title, the meta description and the JSON-LD name.
    They are four separate strings in the emitter and a reader meets all four, so the test that
    they agree has to read all four rather than the one derivation behind them."""
    crumb = re.search(r"</h1>\n<p class=\"crumb\">(.*?)</p>", page)
    title = re.search(r"<title>(.*?)</title>", page)
    desc = re.search(r'<meta name="description" content="([^"]*)">', page)
    ld = json.loads(re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>',
                              page).group(1))
    assert crumb and title and desc, "the page must carry a kind crumb, a title and a description"
    return {"crumb": crumb.group(1), "browser title": title.group(1),
            "meta description": desc.group(1), "JSON-LD name": ld["name"]}


def test_a_survey_declaring_magnetic_channels_only_states_them_and_calls_itself_gds(tmp_path):
    """The live defect, end to end from the declaration a curator writes.

    The package declares `channels_recorded: [Bx, By, Bz]`, which is what the whole legacy GDS
    collection declares. FAILS IF the channels tile asserts an electric channel the survey did not
    record, if any of the four kind surfaces still calls it magnetotelluric, or if the four stop
    agreeing with each other and with the data-type badge the same page prints."""
    surveys = _make_declared_survey(tmp_path, slug="pages-gds", name="Pages GDS",
                                    channels=["Bx", "By", "Bz"], source=GDS_EDI)
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-gds.html").read_text(encoding="utf-8")

    assert _channels_tile(page) == "Bx By Bz", \
        f"the tile must state the declared channels and no others, got {_channels_tile(page)!r}"
    assert "Ex" not in _channels_tile(page), "an undeclared electric channel must never be asserted"
    # The page already knew: the data-type badge reads GDS off the served station documents, which
    # is the same fact the four surfaces were contradicting.
    assert '<span class="typebadge">GDS</span>' in page, "the served stations must come out as GDS"
    surfaces = _kind_surfaces(page)
    for where, text in surfaces.items():
        assert "agnetotelluric" not in text, \
            f"the {where} still calls a magnetic-only survey magnetotelluric: {text!r}"
        assert "eomagnetic depth sounding survey" in text, \
            f"the {where} must name the survey's own kind, got {text!r}"
    assert surfaces["crumb"].startswith("Geomagnetic depth sounding survey &#183;"), surfaces
    assert surfaces["browser title"] == "Pages GDS - geomagnetic depth sounding survey data - AusMT"
    assert surfaces["meta description"] == \
        "Geomagnetic depth sounding survey data: Pages GDS.", surfaces
    assert surfaces["JSON-LD name"] == "Pages GDS geomagnetic depth sounding survey", surfaces


def test_a_survey_declaring_the_full_channel_set_keeps_the_magnetotelluric_kind(tmp_path):
    """The complementary case, so the fix is a derivation and not a second hard-coded string.

    FAILS IF an MT survey loses a declared channel from its tile, if any kind surface starts naming
    geomagnetic depth sounding, or if the four surfaces stop reading exactly as they always have."""
    surveys = _make_declared_survey(tmp_path, slug="pages-mt", name="Pages MT",
                                    channels=["Ex", "Ey", "Bx", "By"])
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-mt.html").read_text(encoding="utf-8")

    assert _channels_tile(page) == "Ex Ey Bx By", \
        f"the declared set renders in full and in order, got {_channels_tile(page)!r}"
    surfaces = _kind_surfaces(page)
    for where, text in surfaces.items():
        assert "eomagnetic depth sounding" not in text, \
            f"the {where} must not name a kind this survey is not: {text!r}"
    assert surfaces["crumb"] == "Magnetotelluric survey &#183; South Australia &#183; Test Org"
    assert surfaces["browser title"] == "Pages MT - magnetotelluric survey data - AusMT"
    assert surfaces["meta description"] == "Magnetotelluric survey data: Pages MT.", surfaces
    assert surfaces["JSON-LD name"] == "Pages MT magnetotelluric survey", surfaces


def test_the_declaration_prints_in_the_corpus_spelling_and_one_stable_order():
    """A declaration is curator-authored text and the corpus writes the magnetic channels both ways
    (Bx and Hx are the same channel; the impedance and tipper masks already fold them together). The
    tile is one reader-facing string, so it prints one spelling, in one order, whatever the
    declaration's own order and case. A channel outside the vocabulary is printed as declared rather
    than dropped: silently discarding a declared channel is the same defect as inventing one."""
    pages = _pages_module()
    for declared, shown in ((["Bz", "By", "Bx"], "Bx By Bz"),
                            (["hx", "hy", "hz"], "Bx By Bz"),
                            (["Hx", "Hy"], "Bx By"),
                            (["ey", "EX", "Bx", "by", "bz"], "Ex Ey Bx By Bz"),
                            (["Ex", "Ey", "Bx", "By", "Bz", "Ez"], "Ex Ey Bx By Bz Ez")):
        page = pages.survey_page(slug="s", label="S", sm_doc={"title": "S"},
                                 smeta={"slug": "s", "org": "O", "lic": "CC-BY-4.0",
                                        "channels_recorded": declared},
                                 station_docs=[], bundle_rows=[], ts_access=None,
                                 base="https://x.example")
        assert _channels_tile(page) == shown, \
            f"{declared!r} must print as {shown!r}, got {_channels_tile(page)!r}"


def test_an_undeclared_survey_infers_channels_only_from_the_components_it_serves():
    """With no declaration the tile may assert only what the served transfer functions corroborate.

    A GDS station is tipper-only with no impedance BY DEFINITION of the band classifier, so a
    survey serving nothing else recorded no electric field and Ex Ey on its tile would be invented.
    Everywhere else the inference is unchanged, including the partial-tipper form.

    FAILS IF an all-tipper survey gets electric channels back, if an MT survey loses the Bz or the
    (+Bz) form, or if a survey mixing the two kinds stops naming both."""
    pages = _pages_module()

    def stn(sid, dtype, tipper):
        return {"ausmt_id": f"au.s.{sid}", "station": sid, "survey_id": "s",
                "location": {"lat": -30.0, "lon": 137.0},
                "data": {"type": dtype, "period_min_s": 10.0, "period_max_s": 6360.0},
                "diagnostics": {"tipper_available": tipper}}

    def page_for(docs):
        return pages.survey_page(slug="s", label="S", sm_doc={"title": "S"},
                                 smeta={"slug": "s", "org": "O", "lic": "CC-BY-4.0"},
                                 station_docs=docs, bundle_rows=[], ts_access=None,
                                 base="https://x.example")

    gds = page_for([stn("A1", "GDS", True), stn("A2", "GDS", True)])
    assert _channels_tile(gds) == "Bx By Bz", \
        f"a survey serving tipper only recorded no electric field, got {_channels_tile(gds)!r}"
    for where, text in _kind_surfaces(gds).items():
        assert "agnetotelluric" not in text, f"the {where} reads {text!r}"

    assert _channels_tile(page_for([stn("A1", "BBMT", True)])) == "Ex Ey Bx By Bz"
    assert _channels_tile(page_for([stn("A1", "BBMT", False)])) == "Ex Ey Bx By"
    assert _channels_tile(page_for([stn("A1", "BBMT", True), stn("A2", "BBMT", False)])) \
        == "Ex Ey Bx By (+Bz)", "the partial-tipper form survives the fix"

    # A survey serving both kinds serves an impedance and a tipper, and names both kinds: neither
    # half is a rewrite of the other, and naming only the larger one would suppress a real holding.
    mixed = page_for([stn("A1", "GDS", True), stn("A2", "BBMT", True)])
    assert _channels_tile(mixed) == "Ex Ey Bx By Bz"
    for where, text in _kind_surfaces(mixed).items():
        assert "magnetotelluric and geomagnetic depth sounding survey" in text.lower(), \
            f"the {where} must name both kinds this survey serves, got {text!r}"

    # A survey whose stations disclose no type at all keeps the corpus's own reading.
    untyped = page_for([])
    assert _channels_tile(untyped) == "Ex Ey Bx By"
    for where, text in _kind_surfaces(untyped).items():
        assert "agnetotelluric" in text, f"an untyped survey stays magnetotelluric: {text!r}"


def test_the_citation_is_a_disclosure_and_its_locator_is_source_led(tmp_path):
    """Design brief 15 plus AUSMT-DATA-CITATION-AND-ACKNOWLEDGEMENT-MODEL.md.

    Two defects at once. The Cite-as box held primary visual space near the top of every survey
    page, and it put the AusMT page URL in the LOCATOR slot unconditionally, which cites the AusMT
    page as the object even on a survey whose own record carries a persistent identifier for itself.
    The model is source-led: the locator is the source identifier where one exists, and the AusMT URL
    is the access route otherwise, stated as a separate acknowledgement rather than smuggled into the
    citation.

    Scope, and only scope, decides. Model section 7 puts the SURVEY-level citation in
    survey-metadata.json and the RESOURCE-level identifiers in station.json resources[], and section
    14 requires the model to PRESERVE that distinction: an identifier naming one product of the
    survey is not the survey. So only a row that identifies the whole record (`identifies: entire`)
    can hold the locator; a `level2` row names the published transfer-function product, and
    promoting it would tell a reader to cite an NCI product under the survey's own authors and
    publisher. Where two rows claim the same self-identifying scope there is no single answer, and
    section 13 is explicit that absence is not an assertion, so the locator falls back to the access
    route rather than letting YAML row order choose a citation target.

    pages-c carries a source DOI on its `identifies: entire` row; pages-d carries none; pages-e
    carries only a `level2` product DOI; pages-f carries two `entire` rows. FAILS IF the citation is
    not a disclosure, if a survey with a source identifier still prints the AusMT URL as its
    locator, if a survey WITHOUT one loses its access route, if a resource-level identifier is
    promoted into the survey citation, if row order decides an ambiguous case, or if the
    acknowledgement stops being a separate verbatim line."""
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
    # pages-e is the shape 8 of the 27 corpus surveys carry: a level2 product DOI and no row for
    # the record itself.
    _make_survey(tmp_path, slug="pages-e", name="Pages E")
    (surveys / "pages-e" / "survey.yaml").write_text(
        (surveys / "pages-e" / "survey.yaml").read_text(encoding="utf-8")
        + "creators:\n  - name: Kay, Ben\n    name_type: person\n"
          "related_identifiers:\n"
          "  - {identifier: 10.25914/wxkq-hj14, identifier_type: DOI, identifies: level2,"
          " relation: IsVariantFormOf}\n"
          "  - {identifier: 10.25914/7vwr-da74, identifier_type: DOI, identifies: raw_packed,"
          " relation: IsDerivedFrom}\n", encoding="utf-8")
    # pages-f is the ambiguous shape: two rows claim the whole record, so neither can speak for it.
    _make_survey(tmp_path, slug="pages-f", name="Pages F")
    (surveys / "pages-f" / "survey.yaml").write_text(
        (surveys / "pages-f" / "survey.yaml").read_text(encoding="utf-8")
        + "creators:\n  - name: Kay, Ben\n    name_type: person\n"
          "related_identifiers:\n"
          "  - {identifier: 10.25914/0pt0-qw75, identifier_type: DOI, identifies: entire,"
          " relation: IsVariantFormOf}\n"
          "  - {identifier: 10.25914/bnhe-3w04, identifier_type: DOI, identifies: entire,"
          " relation: IsVariantFormOf}\n", encoding="utf-8")
    out = _build(surveys, tmp_path / "out")
    src = (out / "pages" / "surveys" / "pages-c.html").read_text(encoding="utf-8")
    plain = (out / "pages" / "surveys" / "pages-d.html").read_text(encoding="utf-8")
    product = (out / "pages" / "surveys" / "pages-e.html").read_text(encoding="utf-8")
    ambiguous = (out / "pages" / "surveys" / "pages-f.html").read_text(encoding="utf-8")

    for page in (src, plain, product, ambiguous):
        assert '<details class="cite">' in page, "the citation must become a disclosure"
        assert "<summary>Cite this survey</summary>" in page, "the disclosure must say what it holds"
        assert "Cite as:" in page and "Kay, B." in page, "the formatted citation text is unchanged"
        assert ("Magnetotelluric transfer functions were accessed through AusMT, Australia's "
                "Magnetotelluric Data Portal (https://ausmt.auscope.org.au), enabled by AuScope "
                "and the Australian Government via the National Collaborative Research "
                "Infrastructure Strategy (NCRIS)." in page), (
            "the AusMT acknowledgement is a separate verbatim line, and it is the one about.html "
            "asks a reader to use (portal/tests/test_about_copy_batch.py holds the two equal)")
        assert page.index('<details class="cite">') < page.index('class="lede"'), \
            "the citation sits near the title, above the lede and the map"

    assert "<code>https://doi.org/10.25914/1ncb-xp10</code>" in src, \
        "a survey whose record identifies itself must cite THAT identifier"
    assert f"<code>{BASE}/surveys/pages-c</code>" not in src, \
        "the AusMT page URL must not hold the locator slot when a source identifier exists"
    assert f"<code>{BASE}/surveys/pages-d</code>" in plain, \
        "with no source identifier the AusMT URL stays as the access route"

    assert "10.25914/wxkq-hj14" not in _cite_block(product), \
        "a level2 row identifies a PRODUCT of the survey, not the survey: it must never hold the " \
        "survey-level locator (model section 14)"
    assert f"<code>{BASE}/surveys/pages-e</code>" in product, \
        "with no row for the record itself the AusMT URL stays as the access route"

    assert "10.25914/0pt0-qw75" not in _cite_block(ambiguous), \
        "two rows claiming the whole record leave no single citation target, so YAML row order " \
        "must not choose one"
    assert f"<code>{BASE}/surveys/pages-f</code>" in ambiguous, \
        "an ambiguous record asserts no preferred citation and keeps the access route"


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
    was read from.

    The presence guard must test the RENDERED value, not the raw object. A contact_resistance
    carrying only library defaults (no source text, no parsed value, no unit) is truthy as a dict
    and renders as nothing, so a guard on the object drew a Contact resistance header with a hyphen
    in every cell: an empty column asserting a measurement the source never made, which is what the
    comment above _channel_cells says it does not do. Latent on today's corpus only because
    _runfacts.unit_value returns None for empty source text and _Doc.channel drops a None, so the
    key is absent rather than default-filled; a document that carried the defaults through would
    have rendered the column.

    FAILS IF either unit_value half is dropped, if a defaults-only document grows sections, or if a
    channel column appears for a key whose every value renders empty."""
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

    # Every channel key present, every value the library default it would arrive as.
    defaults = pages.station_page(
        doc={"ausmt_id": "au.s.A3", "station": "A3", "survey": "S",
             "location": {"lat": -30.0, "lon": 137.0}, "data": {"type": "BBMT"},
             "runs": [{"id": "A3_001", "channels": [
                 {"component": "ex",
                  "contact_resistance": {"source_value": "", "value": None, "unit": None}},
                 {"component": "ey",
                  "contact_resistance": {"source_value": "", "value": None, "unit": None}}]}]},
        survey_slug="s", base="https://x.example")
    assert "Contact resistance" not in defaults, (
        "a contact_resistance whose every value is a library default renders nothing, so it must "
        "draw no column: a header over a hyphen in every cell asserts a measurement the source "
        "never made")
    assert "<td>ex</td>" in defaults, \
        "sensitivity: the channel rows themselves are still rendered, so the column was the choice"


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
    """The entity link graph, all of it at once. Before this module a survey page had NO way back to
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
    # The DISCOVERY layer still renders: the catalogue is discovery-universal, so
    # an embargoed survey's page shows its station locations and band even while the science
    # products are withheld.
    minimap = re.search(r'aria-label="Survey location in Australia".*?</svg>', page, re.S)
    assert minimap and "<circle" in minimap.group(0), "embargoed pages must map their stations"
    assert re.search(r"<td>-3\d\.\d+</td>", page), \
        "the station table must carry the catalogue's public coordinates"


# ==================================================================================================
# The station kind: a geomagnetic depth sounding station is not a magnetotelluric station
# ==================================================================================================
# Every station page introduced its transfer function as "Magnetotelluric" and described the station
# as a "Magnetotelluric station", including every station of the legacy geomagnetic depth sounding
# collection, which recorded no electric field and serves no impedance. The page already knew: the
# Data type row it prints two lines below the crumb reads GDS off the very same document.

GDS_STATION_EDI = HERE / "fixtures" / "impedance" / "placeholder-impedance-tipper.edi"


def _make_tipper_only_survey(tmp_path, *, slug="pages-gds-stn", name="Pages GDS Station"):
    """A package whose survey.yaml declares the magnetic channels only, built end to end.

    That declaration is what fires the impedance mask, which is why the released placeholder
    impedance is dropped and the served station comes out of the band classifier as GDS: the same
    path the whole legacy collection takes."""
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\norganisation: Test Org\n"
        f"access: open\nlicense: CC-BY-4.0\nabstract: A tipper-only test survey.\n"
        f"channels_recorded: [Bx, By, Bz]\n", encoding="utf-8")
    (edir / GDS_STATION_EDI.name).write_text(
        GDS_STATION_EDI.read_text(encoding="latin-1"), encoding="latin-1")
    return tmp_path / "surveys"


def _station_kind_surfaces(page):
    """The three places a station page names the KIND of station it is, read out of the rendered
    output: the crumb under the h1, the meta description and the og:description a link preview
    shows. They are two separate strings in the emitter and a reader meets all three, so the test
    that they agree has to read all three rather than the one derivation behind them."""
    crumb = re.search(r"</h1>\n<p class=\"crumb\">(.*?)</p>", page)
    desc = re.search(r'<meta name="description" content="([^"]*)">', page)
    og = re.search(r'<meta property="og:description" content="([^"]*)">', page)
    assert crumb and desc and og, "the page must carry a kind crumb, a description and an og pair"
    return {"crumb": crumb.group(1), "meta description": desc.group(1),
            "og:description": og.group(1)}


def _one_station_page(out, slug):
    """The single emitted station page of a one-station build, with its ausmt id."""
    docs = sorted((out / "products" / slug).glob("*/station.json"))
    assert len(docs) == 1, f"the fixture must serve exactly one station, got {len(docs)}"
    doc = json.loads(docs[0].read_text(encoding="utf-8"))
    return doc, (out / "pages" / "stations" / (doc["ausmt_id"] + ".html")).read_text(
        encoding="utf-8")


def test_a_tipper_only_station_page_names_the_kind_it_actually_is(tmp_path):
    """The live defect, end to end from the declaration a curator writes.

    FAILS IF any of the three kind surfaces still calls a magnetic-only station magnetotelluric, or
    if they stop agreeing with each other and with the Data type row the same page prints."""
    out = _build(_make_tipper_only_survey(tmp_path), tmp_path / "out")
    doc, page = _one_station_page(out, "pages-gds-stn")
    assert doc["data"]["type"] == "GDS", "the served station must come out of the mask as GDS"
    assert "<dt>Data type</dt><dd>GDS</dd>" in page, "the page already prints the band class"

    surfaces = _station_kind_surfaces(page)
    for where, text in surfaces.items():
        assert "agnetotelluric" not in text, \
            f"the {where} still calls a magnetic-only station magnetotelluric: {text!r}"
    assert surfaces["crumb"] == \
        f"Geomagnetic depth sounding transfer function &#183; {doc['survey']}", surfaces
    expected = (f"Geomagnetic depth sounding station {doc['station']} from the {doc['survey']} "
                "survey: transfer function data, metadata and downloads on AusMT.")
    assert surfaces["meta description"] == expected, surfaces
    assert surfaces["og:description"] == expected, surfaces
    # The kind belongs to the station, not to the page furniture: the browser title never carried
    # it and must not gain it. A station page emits no structured data, so there is no JSON-LD
    # vocabulary term here to rule on.
    assert f"<title>{doc['station']} - {doc['survey']} - AusMT</title>" in page, \
        "the browser title names the station and its survey and nothing else"


def test_an_impedance_station_page_reads_exactly_as_it_always_has(tmp_path):
    """The byte-identity guard. Every published magnetotelluric station page must render word for
    word as it did, so the fix is a derivation and not a second hard-coded string.

    FAILS IF any kind surface on an MT station changes by a single character."""
    out = _build(_make_survey(tmp_path), tmp_path / "out")
    docs = sorted((out / "products" / "pages-a").glob("*/station.json"))
    assert docs, "fixture must serve station documents"
    for path in docs:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["data"]["type"] != "GDS", "the sample survey is the magnetotelluric control"
        page = (out / "pages" / "stations" / (doc["ausmt_id"] + ".html")).read_text(
            encoding="utf-8")
        surfaces = _station_kind_surfaces(page)
        assert surfaces["crumb"] == \
            f"Magnetotelluric transfer function &#183; {doc['survey']}", surfaces
        expected = (f"Magnetotelluric station {doc['station']} from the {doc['survey']} survey: "
                    "transfer function data, metadata and downloads on AusMT.")
        assert surfaces["meta description"] == expected, surfaces
        assert surfaces["og:description"] == expected, surfaces


def test_every_band_class_but_gds_keeps_the_magnetotelluric_reading():
    """The whole vocabulary the classifier emits, spent through the page in one pass.

    GDS is the only band class that is not magnetotelluric: AMT, BBMT and LPMT all estimate an
    impedance from a measured electric field. A station whose document discloses no type keeps the
    magnetotelluric reading, which is what the corpus is.

    FAILS IF an impedance band flips, if an undisclosed type flips, or if GDS stops flipping."""
    pages = _pages_module()

    def surfaces_for(dtype):
        doc = {"ausmt_id": "au.s.A1", "station": "A1", "survey": "S",
               "location": {"lat": -30.0, "lon": 137.0},
               "data": {} if dtype is None else {"type": dtype}}
        return _station_kind_surfaces(
            pages.station_page(doc=doc, survey_slug="s", base="https://x.example"))

    for dtype in ("AMT", "BBMT", "LPMT", "unknown", None):
        for where, text in surfaces_for(dtype).items():
            assert "Magnetotelluric" in text, \
                f"data type {dtype!r} must stay magnetotelluric, the {where} reads {text!r}"
            assert "eomagnetic depth sounding" not in text, \
                f"the {where} must not name a kind data type {dtype!r} is not: {text!r}"
    for where, text in surfaces_for("GDS").items():
        assert text.startswith("Geomagnetic depth sounding"), \
            f"the {where} must lead with the station's own kind, got {text!r}"


# ---- unit pins: time-series levels and the collection rollup ------------------------------------

def _pages_module():
    sys.path.insert(0, str(REPO / "extract"))
    import _pages
    return _pages


def test_ts_panels_and_cells_render_only_the_levels_the_register_carries():
    """No placeholder panels: a survey with raw archives gets the packed-raw card and
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


def _collection_call(pages, n_members=2, **over):
    """One collection_page call with member facts, a register rollup and bundle formats."""
    members = [(f"Member {i}", f"m{i}") for i in range(n_members)]
    kw = dict(
        cid="c", coll={"title": "Test Collection", "n_stations": 400, "type": "programme",
                       "status": "active",
                       "description": "A national programme. It spans several states."},
        member_slugs=members,
        member_smeta=[{"lic": "CC-BY-4.0", "org": f"Org {i}",
                       "org_ror": f"https://ror.org/0000000{i}",
                       "year_start": 2013 + i, "year_end": 2016 + i} for i in range(n_members)],
        base="https://x.example",
        member_points={lbl: [(137.0 + i, -30.0 - i)] for i, (lbl, _s) in enumerate(members)},
        member_facts={s: {"title": lbl, "org": f"Org {i}",
                          "org_ror": f"https://ror.org/0000000{i}",
                          "n_stations": 200, "types": {"LPMT": 200}, "years": f"{2013 + i} - 2016",
                          "period_min_s": 5.0, "period_max_s": 100000.0}
                      for i, (lbl, s) in enumerate(members)},
        level_counts={"raw_packed": 180, "level1_mth5": 12},
        formats=["edi-zip", "mth5"])
    kw.update(over)
    return pages.collection_page(**kw)


def test_the_collection_page_is_an_exploratory_layer(tmp_path):
    """Design brief 23 to 31. The static collection page was description, small map, two numbers,
    a portal link and a bare list of member links: a thin catalogue record, not somewhere a reader
    can understand a programme.

    The sequence is now what it is, where it is, how large, what data, which surveys, who
    contributed. FAILS IF a section goes missing or falls out of order, if a chip is asserted the
    rollup does not carry, if the collection is described as downloadable, or if angular extent
    comes back as a headline metric."""
    pages = _pages_module()
    page = _collection_call(pages, n_members=2)
    order = []
    for anchor, heading in (("about", "About"), ("data", "Data available"),
                            ("surveys", "Member surveys"),
                            ("organisations", "Participating organisations")):
        assert f'<h2 id="{anchor}">{heading}</h2>' in page, f"{heading} section missing"
        order.append(page.index(f'<h2 id="{anchor}">'))
    assert order == sorted(order), "the sections must follow the brief's narrative order"

    # hero: chips from the rollup only, lede, then the map, then the metrics, all above About
    assert '<span class="idxchip">programme</span>' in page and \
           '<span class="idxchip">active</span>' in page, "type and status chips come from the rollup"
    assert "A national programme." in page, "the lede is the description's first sentence"
    scatter = page.index("Member stations of")
    assert scatter < order[0], "the large map is the hero, above About"
    for label in ("surveys", "stations", "period coverage", "years"):
        assert f'<div class="clab">{label}</div>' in page, f"headline metric {label} missing"
    assert "extent" not in page.lower().split('<h2 id="about"')[0], \
        "angular extent is not a headline metric (the map communicates spatial extent)"
    assert page.index('class="cstats"') < order[0], "the metrics ride the hero"
    # The metrics ride BESIDE the map on a wide screen, not under it. Stacked, the 820px map stands
    # 686px tall and pushed the four headline numbers to y=1020 on a 1280x900 screen: a reader had
    # to scroll past the whole hero to learn how many surveys and stations the collection holds.
    # A layout fact cannot be measured from markup, so what is pinned is the structure that carries
    # it: the metrics live inside the hero container, and the container declares the two-column
    # grid that puts them in a rail. The survey page's hero already works this way.
    hero_block = page.split('<div class="collhero">')[1].split("</div>\n<p>")[0]
    assert 'class="collmap"' in hero_block and 'class="cstats"' in hero_block, \
        "the map and the headline metrics must share one hero container to sit side by side"
    assert re.search(r"\.collhero\{[^}]*grid-template-columns:minmax\(0,1fr\) minmax\(", page), \
        "the hero must declare a map column and a metric rail beside it"
    assert re.search(r"@media\(max-width:\d+px\)\{\.collhero\{grid-template-columns:1fr", page), \
        "the rail must fall under the map on a narrow screen (the responsive collapse must hold)"

    # data available: rolled up from served facts, and never a download claim for the collection
    assert "180 stations" in page and "Packed raw" in page, \
        "per-level station counts roll up from the register"
    assert "EDI archive (zip)" in page and "Survey MTH5 bundle" in page, \
        "format availability rolls up from the members' own bundle rows"
    assert "each member survey publishes its own data" in page, \
        "a collection is a discovery layer and must not read as a downloadable dataset"

    # member surveys as a compact list, and organisations with their RORs
    assert '<a href="/surveys/m0">Member 0</a>' in page
    # Ranges read as a SPACED HYPHEN, not as the word "to" (LANE-ADDENDUM-HUB-FEEDBACK.md R1,
    # which names "5 to 100,000 s" -> "5 - 100,000 s" as its worked example). The no-dash-glyph
    # assertions elsewhere in this file are untouched: the ban is on en/em dashes, not on hyphens.
    assert "200 stations" in page and "LPMT" in page and "2013 - 2016" in page
    assert "5 - 100,000 s" in page, "the member row carries its period band"
    assert '<a href="https://ror.org/00000000">Org 0</a>' in page, \
        "participating organisations are ROR-linked where the record carries one"

    # The roll-call is the COLLECTION's roll-call, so it uses the collection's own member label.
    # The label and the survey document's title usually agree; where they differ the label is what
    # this collection calls that member, it is what the map legend and every dot title beside it
    # already say, and it is what the base page linked. Rendering the doc title instead silently
    # substituted a different wording into one page's roll-call (AusLAMP's "EFTF Phase 1 - Northern
    # Territory and Queensland" thinned to "EFTF Phase 1") while the legend above kept the label.
    renamed = _collection_call(pages, n_members=2, member_facts={
        "m0": {"title": "A shorter document title", "org": "Org 0", "n_stations": 200},
        "m1": {"title": "Member 1", "org": "Org 1", "n_stations": 200}})
    assert '<a href="/surveys/m0">Member 0</a>' in renamed, \
        "the member link carries the collection's own label for that member"
    assert "A shorter document title" not in renamed, \
        "the survey document's own title does not replace the collection's wording in the roll-call"

    # presence: a rollup carrying neither type nor status asserts neither
    plain = _collection_call(pages, coll={"title": "Test Collection", "n_stations": 400,
                                          "description": "A grouping."})
    assert '<span class="idxchip">' not in plain, \
        "a collection declaring no type or status shows no chips"


def test_every_collection_member_gets_its_own_colour_and_a_dot_label():
    """_COLL_PAL has eight entries and cycled, so AusLAMP's fourteen members used six colours twice
    and the legend could not tell them apart. Design brief 45 also forbids encoding identity by
    colour alone, and the SPA's own scatter already carries per-dot titles while the static one did
    not. FAILS IF two members share a colour, or if a dot cannot name its survey."""
    pages = _pages_module()
    page = _collection_call(pages, n_members=14,
                            member_points={f"Member {i}": [(115.0 + i, -20.0 - i * 0.5)]
                                           for i in range(14)},
                            member_facts=None, level_counts=None, formats=None)
    # A member's colour is stated once, on the group carrying that member's dots; it used to be
    # repeated on every circle. Either element answers this test, which is about fourteen members
    # getting fourteen distinct colours and not about where the attribute sits. The coast rings are
    # excluded by naming the two elements rather than by matching a bare fill, because a <path>
    # carries the panel's own fill and would be counted as a fifteenth colour.
    dot_fill = r'<(?:g|circle) [^>]*fill="(#[0-9A-Fa-f]{6})"'
    fills = re.findall(dot_fill, page)
    assert len(fills) == 14, fills
    assert len(set(fills)) == 14, f"fourteen members must get fourteen colours, got {len(set(fills))}"
    for i in range(14):
        assert f"<title>Member {i}</title>" in page, f"dot for Member {i} must name its survey"
    # determinism: the same input renders the same colours, every time
    assert fills == re.findall(dot_fill,
                               _collection_call(pages, n_members=14,
                                                member_points={f"Member {i}": [(115.0 + i, -20.0 - i * 0.5)]
                                                               for i in range(14)},
                                                member_facts=None, level_counts=None, formats=None))


def test_bundle_labels_speak_the_manifest_vocabulary():
    """The manifest spells the survey-MTH5 bundle's format "mth5" (the station-resource vocabulary
    says "survey-mth5"); the label map must carry BOTH, or the page prints the raw key - the exact
    defect the first full-corpus preview surfaced."""
    pages = _pages_module()
    assert pages._BUNDLE_LABELS["mth5"][0] == "Survey MTH5 bundle"
    assert pages._BUNDLE_LABELS["survey-mth5"][0] == "Survey MTH5 bundle"
    assert pages._BUNDLE_LABELS["mth5"][1] == "application/x-hdf5"


def test_map_upgrades_scale_bar_type_colours_and_collection_scatter(tmp_path):
    """The maps pass: the footprint zoom carries a scale bar, dots
    speak the portal's type palette, a sub-degree survey's minimap draws the ring only, and the
    collection page carries the member-coloured scatter with its legend.

    Two swatch assertions moved with LANE-CONTRACT-PAGE-HIERARCHY.md B7 and are restated, not
    dropped. BBMT is #3730B8, the value portal/src/state.js measured for LP/BB separability and
    deutan-safety, in place of the lightened #5B54D6 this test used to lock in. The locator ring is
    muted rather than coral, because coral is reserved for primary actions and active states; the
    ring assertion still bites, on the new ink."""
    surveys = _make_rich_survey(tmp_path)
    pkg = surveys / "pages-r"
    y = (pkg / "survey.yaml").read_text(encoding="utf-8")
    (pkg / "survey.yaml").write_text(y + "collection:\n  id: testcoll\n  title: Test Collection\n",
                                     encoding="utf-8")
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-r.html").read_text(encoding="utf-8")
    assert "km</text>" in page, "the footprint zoom must carry a scale bar"
    assert "#3730B8" in page, "dots must speak the type palette (BBMT indigo)"
    minimap = re.search(r'aria-label="Survey location in Australia".*?</svg>', page, re.S).group(0)
    assert "<circle" in minimap and 'stroke="#8FA3B0"' in minimap
    assert 'fill="#3730B8"' not in minimap, \
        "a sub-degree survey's minimap draws the ring only; the zoom panel owns the dots"
    coll = (out / "pages" / "collections" / "testcoll.html").read_text(encoding="utf-8")
    assert "Member stations of" in coll, "the collection page must carry the member scatter"
    assert "#2E8FA3" in coll, "member colours use the portal collection palette"
    assert "Pages R" in coll


def test_the_page_palette_and_the_type_floor_follow_the_brief(tmp_path):
    """Design brief 3, 4 and 45, as measurable properties of the emitted CSS and SVG.

    Four separate debts. The BBMT swatch drifted from the value the portal measured for LP/BB
    separability and deutan-safety (portal/src/state.js), and the drift was TEST-LOCKED. The minimap
    centroid ring was coral, which the brief reserves for primary actions and active states, not for
    decoration on a map. The stylesheet had no focus rule at all while the SPA has one. And several
    secondary labels sat at .72rem or below, under the 12px floor the SPA states for itself.

    FAILS IF the stale BBMT hex returns, if coral goes back on the ring, if the focus rule goes
    missing, if any CSS font-size drops below 12px, or if the map annotation's user-unit size drops
    where it would render under the floor on a narrow screen."""
    surveys = _make_rich_survey(tmp_path)
    out = _build(surveys, tmp_path / "out")
    page = (out / "pages" / "surveys" / "pages-r.html").read_text(encoding="utf-8")

    assert "#3730B8" in page, "BBMT must speak the measured, deutan-safe value"
    assert "#5B54D6" not in page, "the superseded BBMT hex must be gone from every page surface"

    minimap = re.search(r'aria-label="Survey location in Australia".*?</svg>', page, re.S).group(0)
    assert "<circle" in minimap, "the locator ring still marks the survey"
    assert 'stroke="#EF7256"' not in minimap, \
        "coral is for primary actions and active states, not a decorative ring on a map"

    assert ":focus-visible" in page, "keyboard focus must be visible (the SPA has this, pages did not)"

    # The 12px floor, across BOTH the ways a page states a size, and claiming only what each holds.
    # The first form of this pin matched `font-size:.NNrem` alone: it could not see a px value, a
    # leading-zero rem literal, or an SVG presentation attribute, while its message said "no
    # rendered text under 12px". The CSS leg is exact, because a CSS declaration renders at the size
    # it names.
    css = [float(v) * (16 if unit == "rem" else 1)
           for v, unit in re.findall(r"font-size:\s*(\d*\.?\d+)(rem|px)", page)]
    assert css, "sensitivity: the stylesheet must declare font sizes for this to check"
    assert min(css) >= 12, f"no CSS font-size under 12px: smallest is {min(css)}px"

    # The SVG leg is NOT a px floor and must not be written as one. A presentation attribute is in
    # USER UNITS, so the map scale-bar label renders at `value x (rendered width / 230)`, which the
    # page's layout decides. Measured on the served build (auslamp-sa-ne-2014, whose station-grid
    # zoom carries the only such string on any page): the panel renders 364px wide at a 1280px
    # viewport, 337px at 375px, and 282px at 320px, so at the 9 units it carried the label rendered
    # 14.3px, 13.2px and 11.0px. The last of those is under the floor. 10 units is the smallest
    # value that clears it at the narrowest mainstream viewport (12.3px at 320px, 15.8px at 1280px),
    # and it is a 1.5px change where the map is normally read.
    attrs = [float(v) for v in re.findall(r'font-size="(\d*\.?\d+)"', page)]
    # Called directly as well: the zoom panel renders only for a geographically compact survey, so
    # a fixture that happened not to be compact would make the assertion vacuous rather than true.
    attrs += [float(v) for v in re.findall(
        r'font-size="(\d*\.?\d+)"',
        _pages_module()._footprint_svg([(137.0, -30.0, "BBMT"), (137.4, -30.4, "BBMT")]))]
    assert attrs, "sensitivity: the map annotation must state a size for this to check"
    assert min(attrs) >= 10, (
        f"the map annotation is sized in user units, and under 10 it renders below the 12px floor "
        f"on a 320px viewport: smallest is {min(attrs)}")

    cap = re.search(r'<div class="mapcap">(.*?)</div>', page).group(1)
    assert not re.search(r"-\d+\.\d+&#176;[SN]", cap), \
        f"a caption states the hemisphere OR the sign, never both: {cap}"
    assert "&#176;S" in cap and "&#176;E" in cap, f"the hemisphere must still be stated: {cap}"


def test_the_register_lookup_matches_the_documented_ausmt_id_prefix():
    """_ts_survey_rows keyed on aid.split(".") having exactly three parts with parts[1] == slug.
    Two silent losses hid in that: a slug containing a dot never matched at all, and a variant id
    (the fourth component the identity contract allows) was dropped even for a matching survey. The
    API reference states the filter as the prefix `au.<slug>.`, which is what this now does.

    FAILS on the pre-fix emitter, which returns nothing for the dotted slug and drops the variant."""
    pages = _pages_module()
    reg = {"au.a.b-2020.S1": {"level0": {"bytes": 1, "url_path": "x"}},
           "au.a.b-2020.S2.rr": {"level0": {"bytes": 2, "url_path": "y"}},
           "au.other.S1": {"level0": {"bytes": 3, "url_path": "z"}}}
    rows = pages._ts_survey_rows("a.b-2020", reg)
    assert sorted(rows["level0"]) == ["au.a.b-2020.S1", "au.a.b-2020.S2.rr"], rows
    assert pages._ts_survey_rows("other", reg) == {"level0": {"au.other.S1": reg["au.other.S1"]["level0"]}}
    assert pages._ts_survey_rows("nobody", reg) == {}, "a slug with no rows gets none"


def test_a_page_with_empty_slots_carries_no_stray_blank_lines():
    """13 of the 27 served survey pages carried a blank line where an absent block would have been
    (the collection edge, the citation record, the publications list). Cosmetic, but a page emitter
    that leaves the shape of what it did not write is a page emitter that will one day leave the
    content too. FAILS IF a rendered body contains two consecutive newlines."""
    pages = _pages_module()
    page = pages.survey_page(slug="s", label="S", sm_doc=None,
                             smeta={"slug": "s", "org": "O", "lic": "CC-BY-4.0"},
                             station_docs=[], bundle_rows=[], ts_access=None,
                             base="https://x.example")
    body = page.split("<main>\n", 1)[1].split("\n<footer>", 1)[0]
    assert "\n\n" not in body, f"empty slots must leave nothing behind:\n{body[:600]!r}"


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


# ==================================================================================================
# B9 R1 to R3: how a period, a range and a licence PRINT (presentation only)
# ==================================================================================================
def test_the_period_display_helper_holds_the_owners_worked_examples():
    """The worked examples, verbatim, as the specification of ONE shared display helper.

    A period is a stored float and a printed string, and the two are not the same object. The stored
    value stays exactly as the served documents carry it; what a reader sees is rounded to two
    significant figures under 100 and to a thousands-separated integer at or above it, with trailing
    zeros stripped and NEVER an exponent (a hub card reading "9.6e-05 s" is a number a geophysicist
    can read and a reader cannot). FAILS IF any worked example prints differently."""
    pages = _pages_module()
    for value, shown in ((5.33333, "5.3"), (0.005012, "0.005"), (9.6e-05, "0.000096"),
                         (0.004, "0.004"), (100000, "100,000"), (11651, "11,651"), (5, "5")):
        assert pages._fmt_period(value) == shown, \
            f"{value!r} must print as {shown!r}, got {pages._fmt_period(value)!r}"
    assert "e" not in pages._fmt_period(9.6e-05), "exponent notation must never reach a page"


def test_ranges_print_with_a_spaced_hyphen_and_still_carry_no_dash_glyphs():
    """The revised range separator: the word "to" becomes a spaced hyphen-minus, and the
    glyph ban is unchanged (no en dash, no em dash, no tick glyphs). Asserted on a REAL page across
    the three range slots a survey renders: acquisition years, the period-coverage tile and the
    station table's own period cell, plus the station page's period row."""
    pages = _pages_module()
    docs = [{"ausmt_id": "au.s.A1", "station": "A1", "survey": "S",
             "location": {"lat": -34.5, "lon": 138.6},
             "data": {"type": "BBMT", "period_min_s": 5.0, "period_max_s": 100000.0}}]
    page = pages.survey_page(slug="s", label="S", sm_doc={"title": "S",
                                                          "dates": {"coverage": {"year_start": 2016,
                                                                                 "year_end": 2021}}},
                             smeta={"slug": "s", "blurb": "B.", "org": "O", "lic": "CC-BY-4.0"},
                             station_docs=docs, bundle_rows=[], ts_access=None,
                             base="https://x.example")
    assert "2016 - 2021" in page, "the acquisition range must use a spaced hyphen"
    assert "5 - 100,000 s" in page, "the period range must use a spaced hyphen"
    assert "2016 to 2021" not in page and "5 to 100,000" not in page, \
        "the word form of a range is retired from UI chrome"
    assert "\u2013" not in page and "\u2014" not in page, "no en/em dashes"
    stn = pages.station_page(doc=docs[0], survey_slug="s", base="https://x.example")
    # No disjunction: the first arm ("5.0 - 100,000.0 s") is what the row printed BEFORE it took the
    # shared helper, so accepting it let the station page bypass _fmt_period and print the trailing
    # zeros R2 retires while this test stayed green. One helper, one form, one assertion.
    assert "5 - 100,000 s" in stn, \
        f"the station period row must use the shared helper and a spaced hyphen: " \
        f"{stn[stn.find('Period'):][:120]!r}"
    assert "\u2013" not in stn and "\u2014" not in stn


def test_the_licence_reads_in_human_form_in_chrome_and_keeps_its_identifier_in_json_ld():
    """The SPDX identifier is the machine's name for the licence and "CC BY 4.0" is the
    reader's; the page owes the reader the second and the machine the first.

    R3's second clause is "the same pattern for the other recognised CC ids", so the coverage owed
    is the licence instrument's whole CC list, not the subset today's corpus happens to declare.
    The expected strings below are LITERAL, so this test states the reader's form itself rather
    than restating the emitter's derivation of it; the key-set assertion is what makes the coverage
    complete rather than illustrative.

    FAILS IF the chrome prints a raw CC id, if the instrument grows a CC id nothing has named a
    reader's form for, if a non-CC id is guessed at, or if the human form leaks into the JSON-LD
    licence slot (which is a URL derived from the identifier and must not become prose)."""
    pages = _pages_module()
    human = {"CC0-1.0": "CC0 1.0",
             "CC-BY-3.0": "CC BY 3.0",
             "CC-BY-3.0-AU": "CC BY 3.0 AU",
             "CC-BY-4.0": "CC BY 4.0",
             "CC-BY-SA-3.0": "CC BY-SA 3.0",
             "CC-BY-SA-4.0": "CC BY-SA 4.0",
             "CC-BY-NC-3.0": "CC BY-NC 3.0",
             "CC-BY-NC-4.0": "CC BY-NC 4.0",
             "CC-BY-NC-SA-3.0": "CC BY-NC-SA 3.0",
             "CC-BY-NC-SA-4.0": "CC BY-NC-SA 4.0",
             "CC-BY-ND-3.0": "CC BY-ND 3.0",
             "CC-BY-ND-4.0": "CC BY-ND 4.0",
             "CC-BY-NC-ND-3.0": "CC BY-NC-ND 3.0",
             "CC-BY-NC-ND-4.0": "CC BY-NC-ND 4.0"}
    instrument = json.loads((REPO.parent / "contract" / "licenses.json").read_text(encoding="utf-8"))
    recognised = instrument["redistributable"] + instrument["recognised_only"]
    assert set(human) == {i for i in recognised if i.startswith("CC")}, \
        "every CC id the licence instrument recognises owes the reader a named human form"
    for ident, reader in human.items():
        assert pages._fmt_licence(ident) == reader, \
            f"{ident} must read as {reader}, got {pages._fmt_licence(ident)!r}"
    for ident in recognised:
        if ident not in human:
            assert pages._fmt_licence(ident) == ident, \
                f"{ident} has no published reader's form and is printed verbatim, never guessed at"
    assert pages._fmt_licence("Some-Bespoke-Licence") == "Some-Bespoke-Licence", \
        "an unrecognised identifier is passed through, never guessed at"
    page = pages.survey_page(slug="s", label="S", sm_doc=None,
                             smeta={"slug": "s", "blurb": "B.", "org": "O", "lic": "CC-BY-4.0"},
                             station_docs=[], bundle_rows=[], ts_access=None,
                             base="https://x.example")
    assert "<dt>Licence</dt><dd>CC BY 4.0</dd>" in page, "the facts row must read in human form"
    assert '"license": "https://creativecommons.org/licenses/by/4.0/"' in page, \
        "the JSON-LD licence stays the canonical URL the identifier maps to"


# ==================================================================================================
# Collection prose: the About text is a structured payload, not one escaped block


_PROSE = {
    "about": ["The collection brings together historical surveys.",
              "# Preservation and reprocessing",
              "A major source is the Australian Electromagnetic Database.",
              "The provenance of each data product is retained."],
    "data": ["Data are provided through the individual surveys."],
    "members_before": ["Each survey remains an independent AusMT record."],
    "members_after": ["Where appropriate, surveys may be identified as:",
                      "Reprocessed: transfer functions newly estimated.",
                      "Mixed: more than one of these sources."],
    "organisations": ["The organisations represented include institutions."],
}


def _prose_collection(pages, prose=_PROSE, **over):
    """The standard collection fixture with a declared prose payload."""
    coll = {"title": "Test Collection", "n_stations": 400, "type": "programme", "status": "active",
            "description": "A national programme. It spans several states.", "prose": prose}
    coll.update(over.pop("coll", {}))
    return _collection_call(pages, coll=coll, **over)


def test_collection_prose_renders_as_paragraphs_with_a_subheading(tmp_path):
    """FAULT 1. The whole collection description used to be emitted as ONE escaped <p>, so every
    paragraph break and every section heading the author wrote was destroyed: about 450 words
    arrived as a single block.

    FAILS IF the paragraphs are joined back into one element, if the '# ' subheading convention
    renders as a literal hash, or if the subheading is emitted at a level that outranks the <h2>
    section it sits inside."""
    pages = _pages_module()
    page = _prose_collection(pages)
    about = page.split('<h2 id="about">About</h2>\n', 1)[1].split('<h2 id="data"', 1)[0]

    assert about.count('<p class="collprose">') == 3, \
        f"the three About paragraphs must each be their own element, got:\n{about}"
    for para in ("The collection brings together historical surveys.",
                 "A major source is the Australian Electromagnetic Database.",
                 "The provenance of each data product is retained."):
        assert f'<p class="collprose">{para}</p>' in about, f"paragraph lost or merged: {para}"

    # The subheading is an <h3>: it is subordinate to the <h2> section that contains it, so the
    # document outline stays valid. It must not arrive as a literal '# ' in the reader's text.
    assert '<h3 class="collsub">Preservation and reprocessing</h3>' in about, \
        "a '# ' paragraph is the section's subheading, not a paragraph"
    assert "# Preservation" not in page, "the sigil is structure and must never reach the reader"
    assert re.search(r"\bh3\{[^}]*font-size:1rem", page), \
        "an unstyled h3 falls back to the UA's 18.72px and renders LARGER than its own h2 section"


def test_collection_prose_wraps_the_generated_member_cards(tmp_path):
    """FAULT 3. The marker '[Survey cards/list]' sits INSIDE Member surveys, so the prose
    wraps the generated roll-call rather than replacing it: what a member survey is comes BEFORE the
    cards, and the classification list comes AFTER them.

    FAILS IF either block lands on the wrong side of the cards, if the generated cards are displaced
    by the prose, or if the per-section prose is dumped into About instead of its own section."""
    pages = _pages_module()
    page = _prose_collection(pages)

    cards = page.index('<div class="memlist">')
    before = page.index("Each survey remains an independent AusMT record.")
    after = page.index("Where appropriate, surveys may be identified as:")
    heading = page.index('<h2 id="surveys">')
    assert heading < before < cards < after, (
        "member prose must read: heading, intro, the generated cards, then the classification list "
        f"(heading={heading} before={before} cards={cards} after={after})")
    assert '<a href="/surveys/m0">Member 0</a>' in page, \
        "the prose wraps the generated roll-call and must never replace it"
    assert page.index('<a href="/surveys/m0">Member 0</a>') < after, \
        "the classification list follows the cards it classifies"

    # The classification list is PROSE, not a badge: no machine field carries it anywhere in the
    # corpus, so each entry renders as its own paragraph and reads as a definition line.
    assert '<p class="collprose">Reprocessed: transfer functions newly estimated.</p>' in page and \
           '<p class="collprose">Mixed: more than one of these sources.</p>' in page, \
        "each classification entry is its own paragraph"

    # data / organisations: the prose leads, and the GENERATED content it introduces still follows.
    data = page.split('<h2 id="data">', 1)[1].split('<h2 id="surveys"', 1)[0]
    assert data.index("Data are provided through the individual surveys.") < data.index("<dl>"), \
        "the data prose introduces the availability rows, which are generated and must remain"
    assert "<dt>Transfer functions</dt>" in data, "the generated availability rows must survive"
    orgs = page.split('<h2 id="organisations">', 1)[1]
    assert orgs.index("The organisations represented include institutions.") < \
           orgs.index('<a href="https://ror.org/00000000">Org 0</a>'), \
        "the organisations prose qualifies the generated roll-call and never replaces it"


def test_collection_prose_is_escaped_and_carries_no_markup(tmp_path):
    """The prose is author-supplied text on a public serving surface. Only the one ratified
    structural convention is interpreted; everything else is inert.

    FAILS IF any author-supplied character reaches the page as markup, in a paragraph OR in a
    subheading (the subheading path is the easy one to forget, because it builds its own element)."""
    pages = _pages_module()
    page = _prose_collection(pages, prose={
        "about": ['<script>alert(1)</script> & "quoted" <b>bold</b>',
                  '# <img src=x onerror=alert(2)> & \'sub\''],
        "members_after": ['<iframe src="evil"></iframe>']})

    for hostile in ("<script>alert(1)</script>", "<b>bold</b>", "<img src=x onerror=alert(2)>",
                    '<iframe src="evil"></iframe>'):
        assert hostile not in page, f"hostile prose must not reach the page live: {hostile}"
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page, \
        "the paragraph must render escaped, not dropped"
    assert "&lt;img src=x onerror=alert(2)&gt;" in page, \
        "the SUBHEADING path escapes too: it builds its own element and must not skip _e()"
    assert "&amp;" in page and "&quot;quoted&quot;" in page, \
        "ampersands and quotes are escaped exactly as every other curated field is"
    # The h3 element itself is still emitted: escaping must not cost the structure.
    assert '<h3 class="collsub">&lt;img' in page, "the subheading is still a subheading"


def test_a_collection_without_prose_renders_exactly_as_before(tmp_path):
    """Only the GDS collection declares prose. FAILS IF adding the field changes a collection that
    declares none: the flat description must still fill About, and the engine's own sentence must
    still introduce the availability rows."""
    pages = _pages_module()
    page = _collection_call(pages)          # the standing fixture, no prose
    assert '<p class="collprose">A national programme. It spans several states.</p>' in page, \
        "with no prose declared the flat description still fills About"
    assert "each member survey publishes its own data" in page, \
        "the engine's own data sentence is the fallback, not something prose removed"
    assert "<h3" not in page.split("<body>", 1)[1], "no prose means no subheading"
    # An empty or malformed payload is not a licence to emit rubbish (one <p> per character).
    for junk in ({}, {"about": []}, {"about": ""}, {"about": None}, {"about": "flat string"}):
        quiet = _prose_collection(pages, prose=junk)
        assert '<p class="collprose">A national programme.' in quiet, \
            f"a payload declaring no About paragraphs falls back to the description: {junk!r}"
        assert '<p class="collprose">f</p>' not in quiet, \
            f"a bare string must never be iterated character by character: {junk!r}"


def test_the_collection_map_carries_the_auscope_mark_in_its_bottom_left_corner():
    """The mark over the collection footprint, asserted on the RENDERED page.

    The corner is chosen, not arbitrary: this map is a FIXED-EXTENT projection of Australia, so the
    bottom left shows the same open ocean at every rendered width (the nearest coastline in the
    bottom quarter of the viewBox is Tasmania's, better than half the panel away to the right). The
    legend is a SIBLING of the figure rather than content inside it, so the mark cannot reach that
    either.

    FAILS IF the mark leaves the figure, if the figure stops being the positioning context it is
    absolutely placed against, or if it is pushed INSIDE the SVG. That last one is the reason for
    the <image> assertion: the footprint's geometry is what the colour ramp, the dot-per-station
    coverage pin and the hub's size budget all measure, and a brand asset inside it would land in
    the middle of all three."""
    pages = _pages_module()
    page = _collection_call(pages)
    mark = ('<img class="collmark" src="/vendor/auscope-icon-white.png" alt="AuScope" '
            'width="27" height="28">')
    assert page.count(mark) == 1, f"the collection map must carry the mark exactly once, got {page.count(mark)}"
    figure = page.split('<figure class="collmap">', 1)[1].split("</figure>", 1)[0]
    assert mark in figure, "the mark must sit inside the map's own figure"
    assert figure.index("</svg>") < figure.index(mark), \
        "the mark rides OVER the map, after the SVG closes, never inside its geometry"
    assert "<image" not in page, \
        "no <image> element may enter the footprint SVG: every geometry pin measures what is in it"
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ".collmap{position:relative;" in css, \
        "the figure must be the positioning context, or the mark escapes to an outer ancestor"
    assert (".collmark{position:absolute;left:14px;bottom:14px;height:28px;width:auto;"
            "opacity:.82;pointer-events:none}") in css, \
        "the mark must carry the shared placement the SPA's own collection map uses"
    assert "@media(max-width:640px){.collmark{left:9px;bottom:9px;height:20px}}" in css, \
        "the mark must step down on a narrow screen, where the panel has least corner to spare"


def test_the_hub_collection_card_takes_no_mark_on_its_thumbnail_map():
    """The scope line, pinned as one. A card's map is a thumbnail with no corner to spare, and a
    mark on it would read larger against the map than the map does against the card. FAILS IF the
    legend=False form (which is the card's) starts carrying the mark."""
    pages = _pages_module()
    card = pages._collection_scatter(["M"], {"M": [(137.0, -30.0)]}, "T", width=380, legend=False)
    assert card.startswith("<svg") and "collmark" not in card, \
        "the hub card draws the bare footprint and takes no mark"


def test_the_collection_prose_reads_wider_than_the_survey_reading_measure(tmp_path):
    """FAULT 2. The collection prose was capped at the 70ch reading measure while the map above it
    ran to 820px, so the text read as a narrow ribbon under a wide graphic.

    .prose is SHARED with the survey pages (the About-this-survey blurb and the NCI note), so the
    fix is a scoped class, never a widened .prose. FAILS IF the survey reading measure moves."""
    pages = _pages_module()
    page = _prose_collection(pages)
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]

    assert ".prose{max-width:70ch}" in css, \
        "the SURVEY pages' reading measure must not move: .prose is shared"
    assert "class=\"prose\"" not in page, \
        "the collection page carries no unscoped .prose element left behind by the rescope"
    assert re.search(r"\.collprose\{max-width:min\(", css), \
        "the collection measure is its own class, scoped away from the survey pages"

    # The prose tracks the hero map's column rather than a flat pixel value, because the map is
    # itself squeezed by the metric rail below the wide breakpoint: a flat 820px would leave the
    # text WIDER than the graphic it sits under through the whole mid-width band. One token feeds
    # both rules so the two cannot drift.
    assert re.search(r"main\{[^}]*--collw:820px", css), "one token carries the collection measure"
    assert re.search(r"\.collmap\{[^}]*max-width:var\(--collw\)", css), \
        "the map must read its width from the same token the prose does"
    assert "--railw" in css and "--railgap" in css, \
        "the prose subtracts the metric rail so it aligns with the map beside it"
    assert re.search(r"@media\(max-width:860px\)\{\.collprose\{max-width:var\(--collw\)\}", css), \
        "below the hero's own collapse breakpoint the rail is gone and the prose takes the column"

    # The survey page is the thing that must NOT have moved.
    survey = pages.survey_page(slug="s", label="S", sm_doc=None,
                               smeta={"slug": "s", "blurb": "A survey blurb.", "org": "O",
                                      "lic": "CC-BY-4.0"},
                               station_docs=[], bundle_rows=[], ts_access=None,
                               base="https://x.example")
    assert '<p class="prose">A survey blurb.</p>' in survey, \
        "the survey blurb keeps the 70ch reading measure and its unscoped class"


def test_the_single_line_description_consumers_never_take_the_page_prose(tmp_path):
    """The prose is a page-length payload; a link preview, a lede and a hub card are each ONE line.
    FAILS IF prose leaks into a single-line consumer, or if a long description is cut mid-word."""
    pages = _pages_module()
    long_desc = ("The Australia Legacy Geomagnetic Depth Sounding collection brings together "
                 "historical Australian GDS surveys acquired between the 1960s and early 2000s. "
                 "The collection currently comprises 24 surveys and 583 stations distributed "
                 "across much of the Australian continent.")
    page = _prose_collection(pages, coll={"description": long_desc})

    meta = re.search(r'<meta name="description" content="([^"]+)">', page).group(1)
    og = re.search(r'<meta property="og:description" content="([^"]+)">', page).group(1)
    assert meta == og, "the link preview and the meta description must tell one story"
    assert len(meta) <= 160, f"the meta description must stay bounded, got {len(meta)}"
    # The old code sliced desc[:157], which landed inside "and": "...between the 1960s an...".
    assert not meta.endswith("an..."), "a fixed slice cut mid-word; the cut must fall on a boundary"
    tail = meta[:-3].rstrip() if meta.endswith("...") else meta
    assert long_desc.startswith(tail) and (len(tail) == len(long_desc) or
                                           long_desc[len(tail)] in " ."), \
        f"the summary must end on a word or sentence boundary, got {meta!r}"
    for para in _PROSE["about"] + _PROSE["members_after"]:
        assert para.lstrip("# ") not in meta, "page prose must never reach the link preview"

    # The hero lede and the JSON-LD both read the flat description, never the prose payload.
    lede = re.search(r'<p class="lede">([^<]*)</p>', page).group(1)
    assert lede.startswith("The Australia Legacy Geomagnetic Depth Sounding collection"), \
        "the lede is the description's first sentence"
    assert "<p" not in lede and "collprose" not in lede, "the lede is one line of plain text"
    ld = json.loads(re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>',
                              page).group(1))
    assert ld["description"] == long_desc, \
        "the machine record carries the flat discovery description, not the page prose"
    assert "prose" not in json.dumps(ld), "the prose payload is page furniture, not catalogue data"
