"""The two tier-3 INDEX pages: /surveys and /collections.

Until this lane the portal had no addressable index of any kind. The bare paths 301'd to the SPA
root, the SPA's Surveys/Collections controls were buttons that set no hash, and every entity page's
back-navigation pointed at a hash route that does not exist. So a crawler that reached a survey page
found no hub above it, and a reader who followed "All surveys" landed on the map.

These pages close that. They are emitted by the same emitter and under the same flag as the entity
pages, render ONLY from the catalogue rollups (mtcat.json / surveys.json / the collections rollup),
and carry no script and no external asset, so the build stays offline and deterministic and the
served document needs nothing but itself.

The surveys index carries 27 minimaps today and grows with the corpus. Emitting the Australian
outline once as a <symbol> and referencing it from every card is what keeps the document small
enough to serve as a hub page; the budget is asserted here against a full-corpus-sized synthetic,
alongside the naive per-card cost that shows the sharing is load-bearing. The collections hub has
its own budget test for the same ceiling: its cost scales with member STATION count rather than
card count, so it is asserted against six collections at corpus scale before that data arrives.
"""
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


def _pages_module():
    sys.path.insert(0, str(REPO / "extract"))
    import _pages
    return _pages


def _make_survey(tmp_path, *, slug, name, extra=""):
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\nregion: South Australia\n"
        f"organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        f"abstract: An index fixture survey.\n{extra}", encoding="utf-8")
    for src in SAMPLE_EDIS:
        (edir / src.name).write_text(src.read_text(encoding="latin-1"), encoding="latin-1")
    return tmp_path / "surveys"


def _build(surveys, out, *, sitemap=True):
    argv = ["--surveys", str(surveys), "--out", str(out), "--bundle-edi", "--no-validate",
            "--products", str(out / "products")]
    if sitemap:
        argv += ["--sitemap-base", BASE]
    rc = build_portal.main(argv)
    assert rc == 0, f"build rc={rc}"
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One two-survey corpus, one of them a collection member, built once."""
    tmp_path = tmp_path_factory.mktemp("idx")
    surveys = _make_survey(tmp_path, slug="idx-a", name="Index A",
                           extra=("collection:\n  id: idxcoll\n  title: Index Collection\n"
                                  "  description: 'A grouping of index fixtures. It exists to "
                                  "exercise the card. And a third sentence that must not render.'\n"
                                  "identifiers:\n  dataset_doi: 10.82388/idxadoi\n"))
    _make_survey(tmp_path, slug="idx-b", name="Index B")
    return _build(surveys, tmp_path / "out")


# ==================================================================================================
# Surveys index
# ==================================================================================================
def test_surveys_index_is_a_document_with_the_hub_chrome(built):
    """FAILS IF the /surveys page loses what makes it a hub: its own title, a canonical at the
    published URL, og tags for a shared link, and NO noindex (this page exists precisely to be
    indexed - it is the crawlable parent the 27 survey pages currently link away from)."""
    page = (built / "pages" / "surveys" / "index.html").read_text(encoding="utf-8")
    assert "<title>Surveys - magnetotelluric survey data - AusMT</title>" in page
    assert f'<link rel="canonical" href="{BASE}/surveys">' in page, "canonical must be the bare path"
    assert f'<meta property="og:url" content="{BASE}/surveys">' in page
    assert f'<meta property="og:image" content="{BASE}/vendor/social-card.png">' in page, \
        "the index has no per-entity card, so it falls back to the portal's own social card"
    assert '<meta name="robots" content="noindex">' not in page, "the hub page must be indexable"
    m = re.search(r'<meta name="description" content="([^"]+)">', page)
    assert m and m.group(1).endswith("."), "the description must be a structured sentence"
    assert "..." not in m.group(1), "the description must not be a truncated abstract"


def test_surveys_index_lists_every_survey_with_its_discovery_facts(built):
    """FAILS IF a survey is missing from the index, its title is not the link to its page, or the
    discovery facts the reader chooses on (organisation, region, station count, acquisition years,
    data type, period range, licence) are absent. The catalogue summary line is the page's headline
    number and is pinned with it."""
    page = (built / "pages" / "surveys" / "index.html").read_text(encoding="utf-8")
    assert "<h1>Surveys</h1>" in page
    assert re.search(r"2 surveys &#183; \d+ stations", page), \
        "the catalogue summary must state surveys and stations, interpunct-separated"
    assert 'href="/"' in page and "Explore on the map" in page, "the map link must be present"
    for slug, title in (("idx-a", "Index A"), ("idx-b", "Index B")):
        assert f'<a href="/surveys/{slug}">{title}</a>' in page, \
            f"{slug}: the title must be the link to its survey page"
        assert (built / "pages" / "surveys" / f"{slug}.html").is_file(), \
            f"{slug}: every row link must resolve to an emitted page"
    assert "Test Org" in page and "South Australia" in page
    assert "stations" in page and "CC-BY-4.0" in page
    assert re.search(r"[\d,.]+ to [\d,.]+ s", page), "the period range must render"
    # No abstract on the cards: the index is a discovery summary, not a page of miniature records.
    assert "An index fixture survey." not in page, "the survey abstract must not ride the index"


def test_surveys_index_marks_a_doi_only_where_the_rollup_carries_one(built):
    """FAILS IF the DOI marker is invented for a survey without one (or dropped for one with).
    The rollup is the only source; nothing here derives or reserves an identifier."""
    page = (built / "pages" / "surveys" / "index.html").read_text(encoding="utf-8")
    rows = re.findall(r'<article class="idxcard">.*?</article>', page, re.S)
    assert len(rows) == 2, f"one card per survey, got {len(rows)}"
    by_slug = {("idx-a" if "/surveys/idx-a" in r else "idx-b"): r for r in rows}
    assert "DOI" in by_slug["idx-a"], "the survey declaring a DOI must carry the marker"
    assert "DOI" not in by_slug["idx-b"], "a survey without a DOI must not be marked"


def test_index_pages_ride_the_sitemap_flag(tmp_path):
    """FAILS IF the index pages are emitted without --sitemap-base. They are tier 3 like every other
    page: one flag governs the whole tier, so a flagless build stays byte-identical to a pre-lane
    build."""
    surveys = _make_survey(tmp_path, slug="idx-c", name="Index C")
    bare = _build(surveys, tmp_path / "bare", sitemap=False)
    assert not (bare / "pages").exists(), "no --sitemap-base must mean no pages tree at all"


def test_index_pages_carry_no_script_and_no_external_asset(built):
    """FAILS IF an index page grows a script, a stylesheet link, an image or any other fetched
    asset. The entity pages' determinism posture (stdlib-only build, everything inline, no network
    at build or at render) is inherited, not re-litigated: a served page must render from itself."""
    for rel in ("surveys/index.html", "collections/index.html"):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        assert "<script" not in page, f"{rel}: no script may appear on an index page"
        assert "src=" not in page, f"{rel}: no fetched asset may appear on an index page"
        assert "rel=\"stylesheet\"" not in page, f"{rel}: styles stay inline"
        assert "\u2014" not in page and "\u2013" not in page, f"{rel}: no en/em dashes"


# ==================================================================================================
# Collections index
# ==================================================================================================
def test_collections_index_explains_the_concept_and_lists_the_rollup(built):
    """FAILS IF the /collections page loses its chrome, the explanatory sentence that tells a reader
    what a collection IS, or a collection card with its title link, counts and Explore action."""
    page = (built / "pages" / "collections" / "index.html").read_text(encoding="utf-8")
    assert "<title>Collections - magnetotelluric survey data - AusMT</title>" in page
    assert f'<link rel="canonical" href="{BASE}/collections">' in page
    assert '<meta name="robots" content="noindex">' not in page
    assert "<h1>Collections</h1>" in page
    assert ("Collections group related surveys for discovery and exploration. A collection may "
            "represent a programme, region, geological province, or thematic dataset.") in page
    assert '<a href="/collections/idxcoll">Index Collection</a>' in page
    assert (built / "pages" / "collections" / "idxcoll.html").is_file()
    assert "Explore collection" in page
    assert "1 survey" in page and "stations" in page
    assert "Member stations of" in page, "the member-coloured footprint scatter must render"


def test_collections_index_truncates_the_description_at_a_sentence(built):
    """FAILS IF the card carries the whole rollup description (the excessively tall card the design
    brief names) or cuts it mid-word. The full text belongs on the collection page."""
    page = (built / "pages" / "collections" / "index.html").read_text(encoding="utf-8")
    assert "A grouping of index fixtures. It exists to exercise the card." in page
    assert "And a third sentence that must not render." not in page, \
        "the card takes the first sentence or two only"


def test_collections_index_states_only_the_fields_the_rollup_carries(built):
    """FAILS IF a type or status chip is rendered for a collection whose rollup declares neither.
    Collections are a discovery layer over the surveys' own records; the page never invents a
    taxonomy the data does not assert."""
    pages = _pages_module()
    bare = pages.collections_index_page(
        rows=[{"cid": "c", "title": "C", "description": None, "n_surveys": 2, "n_stations": 9,
               "type": None, "status": None, "member_labels": [], "member_points": {}}],
        base=BASE)
    assert "idxtype" not in bare, "no type chip may render for a rollup that declares none"
    assert "idxstatus" not in bare, "no status chip may render for a rollup that declares none"
    rich = pages.collections_index_page(
        rows=[{"cid": "c", "title": "C", "description": None, "n_surveys": 2, "n_stations": 9,
               "type": "programme", "status": "active", "member_labels": [], "member_points": {}}],
        base=BASE)
    assert "programme" in rich and "active" in rich


# ==================================================================================================
# The shared-geometry budget
# ==================================================================================================
def _synthetic_rows(n_surveys=27, n_stations=2625):
    """A corpus the size of the served one: 27 surveys, 2,625 stations spread across Australia."""
    rows, per = [], n_stations // n_surveys
    for i in range(n_surveys):
        pts = [(114.0 + (i * 1.37 + k * 0.11) % 38.0, -40.0 + (i * 0.91 + k * 0.07) % 30.0, "LPMT")
               for k in range(per)]
        rows.append({"slug": f"survey-{i:02d}", "title": f"Synthetic Survey {i:02d}",
                     "org": "Geological Survey of Somewhere", "region": "South Australia",
                     "n_stations": per, "years": "2013 to 2016",
                     "types": {"LPMT": per}, "period_min_s": 4.0, "period_max_s": 16000.0,
                     "lic": "CC-BY-4.0", "doi": "10.82388/abcdefgh", "points": pts})
    return rows


def test_surveys_index_shares_one_outline_and_stays_inside_the_budget():
    """The shared-geometry technique and the page budget, both asserted as NUMBERS against a
    full-corpus-sized synthetic (27 surveys, 2,625 stations).

    Honest accounting: the schematic outline costs about 1.8 KB per card and the station dots
    dominate the document, so sharing the geometry buys tens of kilobytes rather than an order of
    magnitude. It is still the difference between a hub page with headroom and one that grows into
    its ceiling as the corpus does. FAILS IF the outline stops being shared, the saving collapses,
    or the page passes the 300 KB budget."""
    pages = _pages_module()
    rows = _synthetic_rows()
    page = pages.surveys_index_page(rows=rows, base=BASE)
    size = len(page.encode("utf-8"))
    assert page.count("<symbol") == 1, "the outline geometry must be emitted exactly once"
    assert page.count("<use href=") == len(rows), "every card must reference the shared outline"
    # Both reference forms, because a reference that a reader's browser does not understand draws
    # NOTHING: `href` on <use> is SVG2 (Safari 12+, Chromium, Firefox), `xlink:href` is the SVG 1.1
    # form every older engine reads. An entity page inlines its geometry and needs neither; a hub
    # page's whole map layer hangs on this one attribute, and the degraded result is 27 panels of
    # dots floating with no coastline behind them.
    assert page.count('xlink:href="#') == len(rows), \
        "every reference must carry the SVG 1.1 companion attribute as well"
    assert page.count("xmlns:xlink=") == len(rows), \
        "an element using xlink: must declare the namespace"
    assert size < 300_000, f"the surveys index must stay under 300 KB, got {size} bytes"
    # Non-vacuous: measure what one card would pay to carry its own copy of the geometry, and
    # require the sharing to be worth real bytes rather than being decorative structure.
    per_card = (len(pages._minimap_svg([], width=230).encode("utf-8"))
                - len(pages._minimap_svg([], width=230, outline_ref="x").encode("utf-8")))
    saved = per_card * (len(rows) - 1)
    assert saved > 40_000, (
        f"sharing must buy real bytes; per-card geometry is {per_card} B, saving only {saved} B")
    assert "<use href=" not in pages._minimap_svg(rows[0]["points"], width=230), \
        "the entity pages keep the inline form (they draw one map, and their bytes are pinned)"


def test_a_survey_slugged_index_is_refused_rather_than_silently_overwritten():
    """FAILS IF a survey whose slug is literally "index" is allowed through: its page and the hub
    page occupy the same file, so one would silently replace the other and /surveys/index would
    serve the wrong document. Loud is the only safe answer."""
    pages = _pages_module()
    with pytest.raises(ValueError, match="index"):
        pages.emit_pages(Path("/dev/null/nope"), BASE,
                         surveys_meta={"Index": {"slug": "index"}}, survey_docs={},
                         station_docs={}, collections={}, bundle_formats={},
                         survey_extent={}, survey_coll={})


def test_the_built_index_matches_the_built_pages(built):
    """FAILS IF the index advertises a survey or collection the build did not emit a page for (an
    advertised 404 on the hub page itself). Every href the index writes is checked against the
    file tree the same build produced."""
    for rel, kind in (("surveys/index.html", "surveys"), ("collections/index.html", "collections")):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        for target in set(re.findall(rf'href="/{kind}/([^"/]+)"', page)):
            assert (built / "pages" / kind / f"{target}.html").is_file(), \
                f"{rel} links /{kind}/{target} but no page was emitted"


# ==================================================================================================
# Counting in prose
# ==================================================================================================
def _one_survey_row():
    return {"slug": "only", "title": "Only Survey", "org": "Test Org", "region": "Tasmania",
            "n_stations": 1, "years": "2019", "types": {"LPMT": 1}, "period_min_s": 4.0,
            "period_max_s": 16000.0, "lic": "CC-BY-4.0", "doi": None,
            "points": [(147.0, -42.0, "LPMT")]}


def _one_collection_row():
    return {"cid": "only", "title": "Only Collection", "description": "One grouping.",
            "n_surveys": 1, "n_stations": 1, "type": None, "status": None,
            "member_labels": ["Only Survey"], "member_points": {"Only Survey": [(147.0, -42.0)]}}


def _description(page):
    m = re.search(r'<meta name="description" content="([^"]+)">', page)
    assert m, "every hub page must carry a meta description"
    return m.group(1)


def test_a_single_row_hub_counts_in_the_singular():
    """FAILS IF a hub page's own prose says "1 surveys" or "1 curated groupings".

    This is not cosmetic. The served corpus carries exactly ONE collection, so the /collections
    description IS the search-result snippet for the hub page, and the /surveys summary line is the
    first thing a reader sees under the h1. The card counts already went through _plural; the
    page-level strings did not."""
    pages = _pages_module()
    sv = pages.surveys_index_page(rows=[_one_survey_row()], base=BASE)
    assert "1 survey &#183; 1 station" in sv, "the catalogue summary must count in the singular"
    assert "1 surveys" not in sv and "1 stations" not in sv
    assert "1 survey and 1 station," in _description(sv), \
        "the surveys description must count in the singular too"
    co = pages.collections_index_page(rows=[_one_collection_row()], base=BASE)
    assert "1 curated grouping of" in _description(co), \
        "one collection is a grouping, not groupings: this is the live snippet today"
    assert "1 curated groupings" not in co


def test_a_many_row_hub_still_counts_in_the_plural():
    """The other side of the same pin: the singular branch must not swallow the plural form the
    design brief names ("27 surveys &#183; 2,625 stations")."""
    pages = _pages_module()
    rows = _synthetic_rows(n_surveys=27, n_stations=2625)
    sv = pages.surveys_index_page(rows=rows, base=BASE)
    assert f"27 surveys &#183; {27 * (2625 // 27):,} stations" in sv
    assert "27 surveys and" in _description(sv)
    co = pages.collections_index_page(rows=[_one_collection_row(), dict(_one_collection_row(),
                                                                       cid="two", title="Two")],
                                      base=BASE)
    assert "2 curated groupings of" in _description(co)


def _synthetic_collections(n_colls=6, n_stations=2625, members_each=5):
    """Six collections at corpus scale: the design brief names six candidates, and the whole
    served corpus of stations spread across their member surveys."""
    per_coll = n_stations // n_colls
    per_member = per_coll // members_each
    rows = []
    for c in range(n_colls):
        labels = [f"Member Survey {c:02d}-{m:02d}" for m in range(members_each)]
        pts = {}
        for m, lbl in enumerate(labels):
            pts[lbl] = [(114.0 + (c * 3.1 + m * 1.7 + k * 0.13) % 38.0,
                         -40.0 + (c * 2.3 + m * 1.1 + k * 0.09) % 30.0)
                        for k in range(per_member)]
        rows.append({"cid": f"coll-{c}", "title": f"Synthetic Collection {c}",
                     "description": "A programme-scale grouping of magnetotelluric surveys. "
                                    "It exists to size the card.",
                     "n_surveys": members_each, "n_stations": per_coll,
                     "type": None, "status": None,
                     "member_labels": labels, "member_points": pts})
    return rows


def test_collections_index_shares_one_outline_and_stays_inside_the_budget():
    """The collections hub's budget, asserted BEFORE the data arrives rather than after.

    Its cost scales with MEMBER STATION COUNT, not with card count: one card carries a full
    member-coloured scatter of every station in the collection, so the served single-collection
    page is already ~100 KB. The design brief names six candidate collections, and nothing pinned
    the size of this page at all while its sibling was held to 300 KB. FAILS IF the outline stops
    being shared or the page grows past the same ceiling the surveys hub answers to."""
    pages = _pages_module()
    rows = _synthetic_collections()
    page = pages.collections_index_page(rows=rows, base=BASE)
    size = len(page.encode("utf-8"))
    assert page.count("<symbol") == 1, "the outline geometry must be emitted exactly once"
    assert page.count("<use href=") == len(rows), "every card must reference the shared outline"
    assert size < 300_000, f"the collections index must stay under 300 KB, got {size} bytes"


def test_the_hub_card_scatter_thins_its_dots_and_keeps_every_member():
    """The hub card is a SUMMARY of a collection's footprint, and it was drawing one dot per member
    station: the six-collection synthetic already spends most of a 300 KB budget on 2,610 circles,
    and the cost scales with station count rather than with card count, so a corpus that grows
    stations rather than collections walks into the ceiling with nothing between it and the wall.

    The card now grid-decimates above a cap, which keeps the SHAPE of the footprint rather than its
    first N points, and decimates per member so a card can never silently drop a survey. The
    collection PAGE is unthinned: it is the large map the design brief asks for, and it carries the
    legend and the per-dot labels that make each colour readable. FAILS IF the cap stops biting, if
    a member disappears from a card, or if the page's own scatter starts being thinned."""
    pages = _pages_module()
    rows = _synthetic_collections()
    page = pages.collections_index_page(rows=rows, base=BASE)
    per_card = [c.count("<circle") for c in page.split('<article class="idxccard">')[1:]]
    assert len(per_card) == len(rows), per_card
    for n, row in zip(per_card, rows):
        full = sum(len(v) for v in row["member_points"].values())
        assert n < full, f"a card carrying {full} stations must thin, drew {n}"
        assert n >= len(row["member_labels"]), \
            f"every member keeps at least one dot: {n} dots for {len(row['member_labels'])} members"
    assert len(page.encode("utf-8")) < 300_000

    # the collection page itself draws every dot: it is the hero map, not a card
    full_pts = rows[0]["member_points"]
    detail = pages.collection_page(cid="coll-0", coll={"title": "Synthetic Collection 0"},
                                   member_slugs=[(lbl, f"s{i}") for i, lbl
                                                 in enumerate(rows[0]["member_labels"])],
                                   member_smeta=[{} for _ in rows[0]["member_labels"]],
                                   base=BASE, member_points=full_pts)
    assert detail.count("<circle") == sum(len(v) for v in full_pts.values()), \
        "the collection page draws the whole footprint"
