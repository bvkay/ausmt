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
