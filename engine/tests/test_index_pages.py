"""The two tier-3 INDEX pages: /surveys and /collections.

Until this module the portal had no addressable index of any kind. The bare paths 301'd to the SPA
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
import html
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
    assert "Explore on the map" not in page, (
        "the global header's Map tab covers the map action, so the hub must not restate it")
    for slug, title in (("idx-a", "Index A"), ("idx-b", "Index B")):
        assert f'<a href="/surveys/{slug}">{title}</a>' in page, \
            f"{slug}: the title must be the link to its survey page"
        assert (built / "pages" / "surveys" / f"{slug}.html").is_file(), \
            f"{slug}: every row link must resolve to an emitted page"
    assert "Test Org" in page and "South Australia" in page
    # The licence reads in HUMAN form in chrome and the SPDX identifier stays the machine's name
    # for it (LANE-ADDENDUM-HUB-FEEDBACK.md); ranges take the spaced hyphen.
    assert "stations" in page and "CC BY 4.0" in page
    assert re.search(r"[\d,.]+ - [\d,.]+ s", page), "the period range must render"
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
    page: one flag governs the whole tier, so a flagless build stays byte-identical to a earlier
    build."""
    surveys = _make_survey(tmp_path, slug="idx-c", name="Index C")
    bare = _build(surveys, tmp_path / "bare", sitemap=False)
    assert not (bare / "pages").exists(), "no --sitemap-base must mean no pages tree at all"


# The fetched assets a page in this tier may carry, restated (not weakened) per
# LANE-CONTRACT-BRAND-ASSETS.md The rule was "no src at all", which was the right rule while the
# pages had no identity mark: it kept out build-time reads, inlined copies and every external fetch.
# The marks make an exception worth stating precisely rather than loosening the rule to
# "images are fine": same-origin files, served by the portal image, cached once for the whole site.
# The alternative was inlining 180 circles into 2,655 documents. What stays forbidden is everything
# the old rule was actually protecting: no http, no https, no protocol-relative and no data URI may
# ever appear as a src, and no OTHER path may either. The lists below are EXACT and ORDERED, so a
# third asset, or the same asset in the wrong slot, fails here.
#
# ONE mark in the header now: the AusMT identity opening the left zone. The AuScope parent mark
# that could close the right zone is absent from every header on the site (the relationship is
# stated in words, in the footer and in About's Who enables AusMT section), so the header's fetched
# set is a single file.
# The chrome's own fetched assets, in the order a page writes them: the header identity, then the
# footer's AuScope-NCRIS lockup. The lockup arrived with the one-footer rule, which made the parent
# organisation's acknowledgement the footer's right region on every surface; it is the same
# same-origin, vendored, cached-once class of asset as the header mark and is allow-listed on
# the same terms (see LANE-CONTRACT-FOOTER-AUSCOPE.md).
ALLOWED_HEADER_SRCS = ["/vendor/brand/ausmt-mark.svg"]
ALLOWED_FOOTER_SRCS = ["/vendor/auscope-ncris-white.png"]
ALLOWED_PAGE_SRCS = ALLOWED_HEADER_SRCS + ALLOWED_FOOTER_SRCS

# The collection page draws the one thing in this tier that carries a mark in its BODY: the member
# footprint map, which puts the AuScope mark in the panel's bottom-left corner. That mark is a
# CAPTION on a figure, not chrome, and the rule that withdrew the header mark did not reach it, so
# the entry stays and is now the ONLY generated reference to the file. Keyed by the page's own path
# so that no OTHER page kind can quietly grow a body mark.
ALLOWED_BODY_SRCS = {"collections/idxcoll.html": ["/vendor/auscope-icon-white.png"]}

# RESTATED, WHICH MEANS THE SAME SURFACE. The old rule was `"src=" not in page`: a raw substring
# test, blind to nothing. An allow-list parsed from double-quoted attributes alone would be NARROWER
# than the rule it restates, because `src='https://...'` and `src=https://...` would both slip past
# it while failing the old one. So the restatement keeps both halves: the COUNT of the substring is
# held to the allow-list's length (the old rule's exact reach), and the attributes are parsed in
# every quoting form HTML permits and compared to the list itself.
_SRC_ATTR = re.compile(r"""src\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")


def _allowed_srcs(rel):
    """The exact, ordered src list this page kind may carry, in DOCUMENT order: the two header marks,
    then whatever body mark the kind is named for, then the footer's lockup. The order is the
    assertion, so the body mark has to be spliced between the two chrome groups rather than appended
    after them."""
    return ALLOWED_HEADER_SRCS + ALLOWED_BODY_SRCS.get(rel, []) + ALLOWED_FOOTER_SRCS


def _page_srcs(page, rel):
    """Every src on the page, in every quoting form, with the raw-substring count held too."""
    allowed = _allowed_srcs(rel)
    raw = page.count("src=")
    assert raw == len(allowed), (
        f"{rel}: the tier allows exactly {len(allowed)} src attribute(s) and the page "
        f"carries {raw}; the old rule counted the substring itself and this one still does")
    return [m.group(1).strip("\"'") for m in _SRC_ATTR.finditer(page)]


def test_index_pages_carry_no_script_and_only_the_identity_mark(built):
    """FAILS IF an index page grows a script, a stylesheet link, or any fetched asset beyond the one
    allow-listed identity mark. The entity pages' determinism posture (stdlib-only build, everything
    else inline, no network at build) is inherited, not re-litigated; the mark is the single named
    exception and it is same-origin.

    A ld+json block is data, not code: nothing in it executes, and the hub pages carry one so a
    search result can show the trail back to the root. It is stripped before the guard rather than
    excused, so an EXECUTABLE script on a hub still fails on the same line."""
    for rel in ("surveys/index.html", "collections/index.html"):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        assert "<script" not in page.replace('<script type="application/ld+json">', ""), \
            f"{rel}: no executable script may appear on an index page"
        srcs = _page_srcs(page, rel)
        assert srcs == _allowed_srcs(rel), \
            f"{rel}: the only fetched assets may be {_allowed_srcs(rel)}, got {srcs}"
        assert '<img class="brandmark" src="/vendor/brand/ausmt-mark.svg" alt="AusMT"' in page, \
            f"{rel}: the header must carry the AusMT mark as the site identity"
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
            "be a field programme, a data release, an institutional holding, or a compilation of "
            "related surveys.") in page
    assert '<a href="/collections/idxcoll">Index Collection</a>' in page
    assert (built / "pages" / "collections" / "idxcoll.html").is_file()
    assert "Explore collection" in page
    assert "1 survey" in page and "stations" in page
    assert "Member stations of" in page, "the member-coloured footprint scatter must render"


def test_collections_index_truncates_the_description_at_a_sentence(built):
    """FAILS IF the card carries the whole rollup description (an excessively tall card) or cuts it
    mid-word. The full text belongs on the collection page."""
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
                     "n_stations": per, "years": "2013 - 2016",
                     "types": {"LPMT": per}, "period_min_s": 4.0, "period_max_s": 16000.0,
                     "lic": "CC-BY-4.0", "doi": "10.82388/abcdefgh", "points": pts})
    return rows


def test_surveys_index_shares_one_outline_and_stays_inside_the_budget():
    """The shared-geometry technique and the page budget, both asserted as NUMBERS against a
    full-corpus-sized synthetic (27 surveys, 2,625 stations).

    Honest accounting: the derived Natural Earth outline costs about 5.6 KB per card, so sharing it
    across 27 cards saves around 145 KB on a page whose ceiling is 300 KB. That saving is what makes
    the technique load-bearing rather than tidy: carrying the geometry per card would put this page
    through its budget on its own. It was a much closer thing under the hand-simplified outline this
    replaced, which cost 1.6 KB per card and cleared the saving floor below by under 2 KB. FAILS IF
    the outline stops being shared, the saving collapses, or the page passes the 300 KB budget."""
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
    emitted copy names ("27 surveys &#183; 2,625 stations")."""
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
    """Six collections at corpus scale: the emitted copy names six candidates, and the whole
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
    page is already ~100 KB. The emitted copy names six candidate collections, and nothing pinned
    the size of this page at all while its sibling was held to 300 KB. FAILS IF the outline stops
    being shared or the page grows past the same ceiling the surveys hub answers to."""
    pages = _pages_module()
    rows = _synthetic_collections()
    page = pages.collections_index_page(rows=rows, base=BASE)
    size = len(page.encode("utf-8"))
    assert page.count("<symbol") == 1, "the outline geometry must be emitted exactly once"
    assert page.count("<use href=") == len(rows), "every card must reference the shared outline"
    assert size < 300_000, f"the collections index must stay under 300 KB, got {size} bytes"


def _detail_page(pages, rows, i=0):
    """The collection PAGE for one synthetic row, drawn from the same points its card is."""
    return pages.collection_page(cid=f"coll-{i}", coll={"title": f"Synthetic Collection {i}"},
                                 member_slugs=[(lbl, f"s{j}") for j, lbl
                                               in enumerate(rows[i]["member_labels"])],
                                 member_smeta=[{} for _ in rows[i]["member_labels"]],
                                 base=BASE, member_points=rows[i]["member_points"])


def test_the_hub_card_draws_a_dot_for_every_member_station():
    """A card's map is a COVERAGE claim, so it draws every member station or it misreports one.

    The card must not grid-decimate above a per-card cap split between members and
    then snapped to a grid, so it bit about a third harder than its own number implied: the AusLAMP
    card drew 180 of its 1,354 stations and the legacy GDS card 193 of its 579. The two largest
    programmes in the corpus were the two the card understated most, and a reader comparing cards
    saw sparse reconnaissance where a dense national array sits.

    Every dot is drawn instead, and the per-dot cost carries the page: fill and fill-opacity ride
    on a wrapping <g> per colour run rather than on each circle. That is what the size assertion
    below measures, and it is not decorative. Emitting the same 2,610 dots with the colour repeated
    on every circle is 319,782 bytes, which is through the ceiling; this page holds because the
    repetition is gone, not because the dots are.

    FAILS IF a card draws fewer dots than its members have stations, if a member stops getting its
    own colour, or if the per-dot cost regresses far enough to put the page over budget."""
    pages = _pages_module()
    rows = _synthetic_collections()
    page = pages.collections_index_page(rows=rows, base=BASE)
    cards = page.split('<article class="idxccard">')[1:]
    assert len(cards) == len(rows), f"one card per collection, got {len(cards)}"
    for card, row in zip(cards, rows):
        full = sum(len(v) for v in row["member_points"].values())
        drew = card.count("<circle")
        assert drew == full, f"a card carrying {full} stations must draw {full} dots, drew {drew}"
        # and every member survey is still separable by colour, which is what the map is for
        fills = set(re.findall(r'fill="(#[0-9A-Fa-f]{6})"', card))
        assert len(fills) == len(row["member_labels"]), \
            f"{len(row['member_labels'])} members must draw in {len(row['member_labels'])} " \
            f"colours, got {len(fills)}"
    size = len(page.encode("utf-8"))
    assert size < 300_000, (
        f"the collections hub must draw every station AND stay under 300 KB, got {size} bytes")

    # the collection page draws the same footprint: the card is not a reduced version of it
    detail = _detail_page(pages, rows)
    assert detail.count("<circle") == sum(len(v) for v in rows[0]["member_points"].values()), \
        "the collection page draws the whole footprint"
    assert cards[0].count("<circle") == detail.count("<circle"), \
        "card and page now agree on how many stations the collection has"


def test_no_collection_map_draws_the_single_survey_locator_ring():
    """The ring the brief asked to be rid of: a large grey circle sitting mid-continent on a card.

    The ring is the minimap's stand-in for dots too small to draw, so it says "this one survey is
    here". A collection gathers many surveys and has no one location, and the ring was marking the
    centroid of a continent-spanning programme, a spot no member of it occupies. Rendered it was
    19.8 px across against a 3.1 px station dot, so it read as the most prominent object on the map.

    FAILS IF a ring returns to either collection surface, the card or the page."""
    pages = _pages_module()
    rows = _synthetic_collections()
    page = pages.collections_index_page(rows=rows, base=BASE)
    assert 'stroke="#8FA3B0"' not in page, \
        "no collection card may draw the single-survey locator ring"
    # non-vacuous: the assertion above is only worth anything if these maps drew circles at all
    assert page.count("<circle") == sum(sum(len(v) for v in r["member_points"].values())
                                        for r in rows), \
        "every circle on the collections hub is a station dot and nothing else"
    detail = _detail_page(pages, rows)
    assert 'stroke="#8FA3B0"' not in detail and detail.count("<circle") > 0, \
        "the collection page must not draw it either"


def test_the_locator_ring_follows_extent_not_station_count():
    """The root cause behind the ring on the collection cards, pinned on the minimap itself.

    The ring exists because a footprint under a degree across projects to less than a pixel on a
    continental viewBox: the dots are suppressed there and the ring says where to look instead. The
    gate was a proxy for that, `len(points) < 400`, and a count does not predict an extent. A
    54-station survey spread over 39 degrees sailed under the number and got a ring around the
    middle of Australia, and the collection card inherited the same fault the moment its own
    thinning pushed its count under 400. Both surfaces, one wrong test.

    FAILS IF the ring returns on a wide footprint, goes missing on a compact one, starts tracking
    how many stations were passed, or stops honouring the explicit opt-out."""
    pages = _pages_module()
    ring = 'stroke="#8FA3B0"'
    wide = [(115.0 + i * 0.8, -33.0 - (i % 7) * 0.9, "LPMT") for i in range(40)]
    tight = [(136.97 + i * 0.0004, -30.14 + i * 0.0003, "LPMT") for i in range(40)]
    assert ring not in pages._minimap_svg(wide), \
        "a wide footprint draws its own dots, so it needs nothing to stand in for them"
    assert "<circle" in pages._minimap_svg(wide), "and those dots must actually be there"
    assert ring in pages._minimap_svg(tight), \
        "a sub-degree footprint draws no dots, so the ring is the only thing marking it"

    # count is not the lever it was mistaken for, in either direction
    tight_many = [(136.97 + (i % 25) * 0.0004, -30.14 + (i // 25) * 0.0003, "LPMT")
                  for i in range(500)]
    assert ring in pages._minimap_svg(tight_many), \
        "500 sub-degree stations still draw no dots, so they still need the ring"
    wide_few = [(115.0, -33.0, "LPMT"), (150.0, -25.0, "LPMT")]
    assert ring not in pages._minimap_svg(wide_few), \
        "two stations a continent apart have no centroid worth marking"

    # and a caller that has no single location to mark says so, whatever the extent
    assert ring not in pages._minimap_svg(tight, locator=False)


# ==================================================================================================
# The display grammar on the hubs: the same rules the entity pages answer to
# ==================================================================================================
def test_the_hub_cards_print_ranges_licences_and_periods_the_way_the_entity_pages_do():
    """One display grammar across the whole tier. The hub card is where a reader compares surveys
    side by side, so a range that reads "5 to 100,000 s" on the card and "5 - 100,000 s" on the page
    is two answers to one question. FAILS IF the hub keeps the word form of a range, prints the raw
    SPDX identifier, or lets an exponent reach a card."""
    pages = _pages_module()
    row = dict(_one_survey_row(), years="2016 - 2021", period_min_s=9.6e-05, period_max_s=11651.0)
    page = pages.surveys_index_page(rows=[row], base=BASE)
    assert "0.000096 - 11,651 s" in page, "the card period band takes the shared display helper"
    assert "9.6e-05" not in page, "exponent notation must never reach a hub card"
    assert "2016 - 2021" in page and " to " not in page.split('<div class="idxlist">')[1], \
        "no range on a card may still read as the word form"
    assert "CC BY 4.0" in page, "the licence reads in human form on the card"
    assert "CC-BY-4.0" not in page, "the raw SPDX identifier is the machine's name, not the reader's"


# ==================================================================================================
# The hub as a place to browse, not a list to read
# ==================================================================================================
def test_the_whole_hub_card_is_clickable_and_the_title_is_still_the_only_anchor():
    """The stretched-link pattern. A card is one destination, so the whole card should behave
    like one target; but a card full of overlapping links is a screen-reader's nightmare and a
    button in a row breaks the catalogue -> survey -> data hierarchy the brief set. So the TITLE
    stays the single real anchor and a ::after on it covers the card.

    FAILS IF the card stops being positioned (the overlay would escape to the page), if the overlay
    rule is dropped, if a second anchor appears in a surveys-hub card, if a <button> appears in any
    row, or if the hover affordance goes."""
    pages = _pages_module()
    page = pages.surveys_index_page(rows=[_one_survey_row()], base=BASE)
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    # Scoped to the .idxcard rule itself. An unscoped "position:relative" in css search is satisfied
    # by the collections card's own rule in the same sheet, so dropping it from THIS card passed:
    # the title's inset ::after would then resolve against the page instead, covering the whole
    # document with one anchor and naming the accessibility tree after one survey.
    card_rule = re.search(r"\.idxcard\{([^}]*)\}", css)
    assert card_rule and "position:relative" in card_rule.group(1), \
        f"the card itself must establish the positioning context for the stretched link: {card_rule}"
    assert ".idxt a::after" in css, "the title anchor must carry the card-covering ::after"
    assert ".idxcard:hover" in css, "the card must acknowledge the pointer"
    card = page.split('<article class="idxcard">', 1)[1].split("</article>", 1)[0]
    assert card.count("<a ") == 1, f"exactly one real anchor per surveys card, got {card.count('<a ')}"
    assert "<button" not in page, "no buttons in rows, ever: the hierarchy is catalogue, survey, data"
    assert "&#8594;" in card, "the card reveals a forward arrow for the in-site action"


def test_the_collections_card_keeps_its_explore_link_above_the_stretched_overlay():
    """The collections card carries a second link to the same place ("Explore collection"). Under a
    stretched overlay a link that is covered is a link that does not work, so it is lifted above it.
    FAILS IF the lift is dropped (the visible control would become inert) or the card stops being
    clickable as a whole."""
    pages = _pages_module()
    page = pages.collections_index_page(rows=[_one_collection_row()], base=BASE)
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    # Both assertions scoped to their own rule: checking the two tokens independently against the
    # whole sheet let the lift be replaced by a colour while an unrelated rule supplied the
    # z-index, and a covered control is a control that does not work.
    ccard = re.search(r"\.idxccard\{([^}]*)\}", css)
    assert ccard and "position:relative" in ccard.group(1), \
        f"the collections card must establish its own positioning context: {ccard}"
    lift = re.search(r"\.idxccard \.idxact a\{([^}]*)\}", css)
    assert lift and "position:relative" in lift.group(1) and "z-index" in lift.group(1), \
        f"the Explore control must be lifted above the card-covering overlay: {lift}"
    assert "Explore collection" in page


def test_the_surveys_hub_leads_with_the_owners_lede_and_a_forward_arrow():
    """The hub's own words, verbatim, between the summary line and the
    list; and the map action carries the in-site forward arrow (keeps U+2192 for actions that
    stay on the site and U+2197 for links that leave the page)."""
    pages = _pages_module()
    page = pages.surveys_index_page(rows=[_one_survey_row()], base=BASE)
    assert ("Discover magnetotelluric surveys from across Australia. Browse survey coverage, "
            "acquisition periods and available data.") in page, "the hub lede must read verbatim"
    assert page.index('class="idxsum"') < page.index("Discover magnetotelluric") \
        < page.index('class="idxlist"'), "the lede sits between the summary line and the list"
    assert '<p class="idxact">' not in page.split('class="idxlist"')[0], (
        "no action paragraph survives above the list: the map action is gone and nothing "
        "replaced it (the .idxact CSS stays: the collection cards still use it)")
    coll = pages.collections_index_page(rows=[_one_collection_row()], base=BASE)
    assert "Discover magnetotelluric surveys" not in coll, \
        "the collections hub keeps its own section-20 lede"


def test_the_hub_locator_grows_and_its_container_steps_back():
    """The locator map is the card's only picture and must not be too small to read at a glance;
    it grows about ten percent. The PANEL around it steps toward the card's own fill so the
    Australia outline reads as the object rather than as a box on a box. The shared-symbol geometry
    is untouched, which is what keeps the budget pin honest."""
    pages = _pages_module()
    page = pages.surveys_index_page(rows=_synthetic_rows(), base=BASE)
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "grid-template-columns:115px 1fr" in css, \
        "the hub locator column must be 115px (about +10% on the 104px it carried)"
    assert pages._INDEX_MAP_WIDTH == 230, \
        "the shared symbol geometry does not move: the rendered width grows, not the viewBox"
    assert page.count("<symbol") == 1 and len(page.encode("utf-8")) < 300_000, \
        "the size budget stays green"
    svg = pages._minimap_svg([], width=230)
    assert "background:#18213D" in svg, "the map panel steps to the card's own fill"
    assert "#16242f" not in svg, "the old darker panel shade is gone"


def test_the_card_names_its_organisation_more_loudly_than_its_location():
    """Organisation and location share one line with no labels, so the only thing that can tell
    a reader which is which is weight: two muted shades, the organisation brighter. FAILS IF the two
    collapse back to one colour or a label is introduced."""
    pages = _pages_module()
    page = pages.surveys_index_page(rows=[_one_survey_row()], base=BASE)
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    org_line = page.split('<p class="idxorg">', 1)[1].split("</p>", 1)[0]
    assert '<span class="idxorgn">Test Org</span>' in org_line
    assert '<span class="idxloc">Tasmania</span>' in org_line
    assert "Organisation" not in org_line and "Region" not in org_line, "the org line carries no field labels"
    orgn = re.search(r"\.idxorgn\{color:(#[0-9A-Fa-f]{6})", css)
    loc = re.search(r"\.idxloc\{color:(#[0-9A-Fa-f]{6})", css)
    assert orgn and loc, f"both shades must be declared; got {orgn} / {loc}"
    assert orgn.group(1) != loc.group(1), \
        f"the organisation must not share the location's ink ({orgn.group(1)})"
    def _lum(hexcol):
        return sum(int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    assert _lum(orgn.group(1)) > _lum(loc.group(1)), \
        f"the organisation must read BRIGHTER than the location: {orgn.group(1)} vs {loc.group(1)}"


def test_the_hub_column_is_wider_than_the_reading_column_but_never_full_width():
    """The hub is a scanning surface, not a reading surface, so its column widens about ten
    percent past the 840px prose measure; and it stops near 920px rather than inheriting the entity
    pages' 1120px wide-screen measure, because a hub card stretched across a desktop is a row, not a
    card."""
    pages = _pages_module()
    for page in (pages.surveys_index_page(rows=[_one_survey_row()], base=BASE),
                 pages.collections_index_page(rows=[_one_collection_row()], base=BASE)):
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        assert "max-width:920px" in css, "the hub column must widen to 920px"
        assert css.rindex("max-width:920px") > css.rindex("max-width:1120px"), \
            "the hub width must be declared after (and so override) the entity pages' wide measure"
        assert css.count("max-width:920px") == 2, \
            "the base rule and the wide-screen media query must BOTH be capped at the hub measure"


# ==================================================================================================
# ONE header and ONE footer, across every page kind
# ==================================================================================================
# The page kinds this tier emits, with the tab that must be active, the machine-readable link the
# footer must resolve to, and whether the header's right status slot carries anything. The footer
# column must NOT differ per row, which is exactly what the one-footer rule settles; it is
# kept as a column, one value repeated, so a re-divergence shows up here as rows that disagree.
# LANE-ADDENDUM-HUB-FEEDBACK.md The tokens asserted below are the SPA header's own
# (portal/index.html :root and its nav/about/contribute/counts rules); they are restated as literals
# rather than read across, because the engine image ships engine/ and contract/ and cannot see
# portal/ at all, and a test that reaches out of the image is a test the image cannot run.
_FOOTER_LINK = ("Machine-readable record (MTCAT JSON)", "/data/mtcat.json")

# The parent organisation, as the footer states it on every page: the acknowledgement's URL text and
# the lockup both navigate here, and the lockup itself is served from this site. The address is a
# NAVIGATION target and nothing more; the src is the vendored file, and the src allow-list above is
# what keeps it the only new fetch this rule introduced.
AUSCOPE_URL = "https://www.auscope.org.au"
ORG_LOCKUP_SRC = "/vendor/auscope-ncris-white.png"
# Both anchors to that address leave the site, so both open in a new tab and hand the opened page no
# handle on this one: target="_blank" grants window.opener, from which the opened document can
# navigate the tab it came from. One literal in one order, the spelling the header's own external
# anchor carries, so the generated tier cannot drift from the portal's six documents.
NEW_TAB = 'target="_blank" rel="noopener noreferrer"'


def _kinds(built):
    aid = sorted(p.stem for p in (built / "pages" / "stations").glob("*.html"))[0]
    return {
        "surveys/index.html": ("navSurveys", *_FOOTER_LINK, True),
        "collections/index.html": ("navCollections", *_FOOTER_LINK, False),
        "surveys/idx-a.html": ("navSurveys", *_FOOTER_LINK, False),
        f"stations/{aid}.html": ("navSurveys", *_FOOTER_LINK, False),
        "collections/idxcoll.html": ("navCollections", *_FOOTER_LINK, False),
    }


def test_every_static_page_carries_the_one_global_header(built):
    """The SPA header's three-part division becomes the site's ONE header: AusMT identity on
    the left linking the root, the three filled application tabs in the centre with the CURRENT
    page's tab active, and the two smaller outlined supporting controls beside them. The static
    pages had no header at all above their crumb line, so a reader who landed on a survey page from
    a search result had no route to the map, the hubs, About or Contribute.

    FAILS IF a page kind is missing the header, activates the wrong tab (or more than one), points a
    tab somewhere else, loses a supporting control, or drifts off the SPA's tokens."""
    for rel, (active, _lbl, _href, _slot) in _kinds(built).items():
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        head = page.split("<header", 1)[1].split("</header>", 1)[0]
        assert '<a class="wordmark" href="/">AusMT</a>' in head, f"{rel}: no identity linking the root"
        for nav_id, href in (("navMap", "/"), ("navSurveys", "/surveys"),
                             ("navCollections", "/collections")):
            assert re.search(rf'<a id="{nav_id}"[^>]*href="{re.escape(href)}"', head), \
                f"{rel}: {nav_id} must be a real link to {href}"
        act = re.findall(r'<a id="(nav\w+)"[^>]*class="active"', head)
        assert act == [active], f"{rel}: exactly {active} must be active, got {act}"
        assert '<a class="about" href="/about.html">About</a>' in head, f"{rel}: no About control"
        assert 'href="/add-survey.html">Contribute a survey' in head, f"{rel}: no Contribute control"
        assert "<header" in page.split("<main>", 1)[0], f"{rel}: the header must precede <main>"
        assert '<p class="crumb">' in page, f"{rel}: the crumb line stays beneath the header"
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        for token in ("#EF7256", "#1E2B4F", "#2B3557", "min-width:112px", "min-height:40px"):
            assert token in css, f"{rel}: the header must carry the SPA's {token} token"
        # Scoped, because #E8EDF1 appears elsewhere in this sheet and an unscoped search would pass
        # on the nav tabs' own colour. The SPA's .wordmark declares no colour and so inherits
        # --text #E8EDF1; the static header carried a plain #fff, which is the page tier's heading
        # white and one step brighter than the identity it is meant to be the same object as.
        mark = re.search(r"\.wordmark\{([^}]*)\}", css)
        assert mark and "color:#E8EDF1" in mark.group(1), \
            f"{rel}: the identity carries the SPA header's own text token: {mark}"


def test_the_right_status_slot_is_contextual_and_empty_where_the_owner_ruled(built):
    """The shell is identical everywhere; what rides in the right slot is not. The Map view
    keeps its live counter in the SPA; the surveys hub states the static catalogue counts; every
    other static page shows NOTHING, because a counter that cannot count the page it is on is
    decoration pretending to be data.

    The right zone also closes with the parent-organisation mark, which is chrome and not status: it
    says the same thing on every page and rides every one of them. It is discounted from the slot
    here so that "empty" keeps meaning "no status", and pinned in its own right below."""
    for rel, (_active, _lbl, _href, has_slot) in _kinds(built).items():
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        head = page.split("<header", 1)[1].split("</header>", 1)[0]
        slot = head.split('class="hzone hright"', 1)[1].split("</div>", 1)[0].lstrip(">")
        slot = slot.replace(ORG_MARK_IMG, "")
        if has_slot:
            assert "surveys" in slot and "stations" in slot, \
                f"{rel}: the surveys hub must state its static counts, got {slot!r}"
            assert re.search(r"<b>\d[\d,]*</b> surveys", slot), \
                f"{rel}: the counts must read in the SPA's own grammar, got {slot!r}"
        else:
            assert slot.strip() == "", f"{rel}: the status slot must be empty, got {slot!r}"


def test_one_footer_of_three_regions_on_every_page_kind(built):
    """Restated to the rule: ONE footer, three regions, byte-identical on every page.

    The footer must not be contextual, or a reader cannot learn it once. Left is the catalogue,
    the same document from every page; centre is the AuScope acknowledgement with the attribution
    and the licence note, carrying the one navigation link in the line; right is the AuScope-NCRIS
    lockup, linked where that URL text links. The separator is U+00B7, written as the numeric
    reference so a mis-decoded read of this file cannot smuggle a hyphen past the pin.

    Releases and About this build left the footer on every surface. Nothing is lost: /about.html
    carries the running build's identity and the route to the citable releases in its own body,
    which the portal workflow pins (portal/tests/test_about_uniform_chrome.py). A per-page machine link
    is not lost either: a survey and a station page each carry their own record in the body under
    "Identifiers and provenance", which is asserted separately.

    FAILS IF the one-line footer survives anywhere, if the three regions are not present with the
    the exact strings, if a region's links move or retarget, if the retired controls come back,
    if the footer differs between page kinds, or if the removed build stamp comes back."""
    seen = {}
    for rel, (_active, label, href, _slot) in _kinds(built).items():
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        foot = page.split("\n<footer>", 1)[1].split("</footer>", 1)[0]
        seen[rel] = foot
        assert "AusMT - Australia's Magnetotelluric Data Portal - an AuScope service." not in page, \
            f"{rel}: the one-line footer must be replaced everywhere in pages/"

        # LEFT. One machine-readable link, the whole catalogue, carrying the leaves-this-page arrow.
        left = foot.split('<div class="fzone fleft">', 1)[1].split("</div>", 1)[0]
        assert left == f'<a href="{href}">{label} &#8599;</a>', \
            f"{rel}: left region is not the MTCAT link: {left!r}"
        # /data/* is the served route onto the build's own out dir, so the advertised path is
        # checked against the tree this same build wrote: a footer link is a promise about a file.
        assert href.startswith("/data/") and (built / href[len("/data/"):]).is_file(), \
            f"{rel}: the footer advertises {href}, which this build did not write"

        # CENTRE. The string, carrying exactly one link: the AuScope address under its own
        # URL text. The rest of the line is prose and stays prose.
        centre = foot.split('<div class="fzone fcenter">', 1)[1].split("</div>", 1)[0]
        assert centre == ("AusMT is enabled by AuScope &#183; "
                          f'<a href="{AUSCOPE_URL}" {NEW_TAB}>www.auscope.org.au</a> &#183; '
                          "&#169; 2026 AuScope and the AusMT contributors &#183; "
                          "Data licences vary by survey"), \
            f"{rel}: centre region is not the acknowledgement line: {centre!r}"
        assert centre.count("<a") == 1, \
            f"{rel}: the centre region carries exactly one link: {centre!r}"

        # RIGHT. The parent organisation's full lockup, linked where the centre's URL text links.
        # Same-origin and vendored: the rule adds a navigation anchor, not a runtime dependency.
        right = foot.split('<div class="fzone fright">', 1)[1].split("</div>", 1)[0]
        assert right == (f'<a class="orglogo" href="{AUSCOPE_URL}" {NEW_TAB}>'
                         f'<img src="{ORG_LOCKUP_SRC}" alt="AuScope and NCRIS" '
                         'width="1919" height="325"></a>'), \
            f"{rel}: right region is not the AuScope-NCRIS lockup: {right!r}"

        # The MTCAT record is this site's own document: it stays in the tab the reader is in, so
        # the new-tab behaviour reads as "this link leaves AusMT" and nothing else.
        assert "target=" not in left, \
            f"{rel}: an in-site footer link stays in this tab: {left!r}"

        for gone in (">Releases<", "About this build", "aboutbuild", "/releases.html"):
            assert gone not in foot, \
                f"{rel}: {gone!r} is out of the footer and must not come back: {foot!r}"
        assert "fbuild" not in foot and "Build " not in foot, (
            f"{rel}: the build identity stamp stays out of the footer; "
            f"build_provenance.json still carries it: {foot!r}")
        # The regions are the WHOLE footer: an extra zone, or a stray stamp between them, fails.
        assert foot.count('<div class="fzone ') == 3, \
            f"{rel}: the footer is exactly three regions: {foot!r}"

    assert len(set(seen.values())) == 1, (
        "the footer must be identical on every page kind; it differs:\n"
        + "\n".join(f"  {rel}: {foot!r}" for rel, foot in seen.items()))


def test_the_per_page_machine_record_survives_in_the_body(built):
    """The footer's left link is the whole catalogue on every page, so a survey's and a station's
    OWN machine-readable record is reachable only from the body. That link is what makes the
    uniform footer a simplification rather than a loss, so it is pinned here too.

    FAILS IF a survey or station page stops offering its own record under Identifiers and
    provenance, or points it somewhere this build did not write."""
    aid = sorted(p.stem for p in (built / "pages" / "stations").glob("*.html"))[0]
    for rel, label, href in (
            ("surveys/idx-a.html", "Machine-readable survey record",
             "/data/products/idx-a/survey-metadata.json"),
            (f"stations/{aid}.html", "Machine-readable station record",
             f"/data/products/idx-a/{aid.rsplit('.', 1)[-1]}/station.json")):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        body = page.split("</footer>", 1)[0].split('id="identifiers"', 1)
        assert len(body) == 2, f"{rel}: no Identifiers and provenance section"
        assert f'<a href="{href}">{label}</a>' in body[1], \
            f"{rel}: the body must offer {label} at {href}"
        assert (built / href[len("/data/"):]).is_file(), \
            f"{rel}: the body advertises {href}, which this build did not write"


def test_the_footer_regions_lay_out_side_by_side_and_stack_when_narrow(built):
    """The three regions are a wrapping flex row in which the CENTRE is the region that gives: the
    left link and the right links are short fixed phrases that read badly broken, and the
    attribution line is prose that does not.

    THE QUERIES ASK THE FOOTER'S OWN WIDTH, not the viewport's, and that is the point of them. main
    is 840px on an entity page, 920px on a hub and 1120px above 1180px of viewport, so a viewport
    number answers the question wrongly on two page kinds out of three.

    THE SIDE ZONES TAKE EQUAL ZERO BASIS, which is what page-centres the acknowledgement. Zones that
    size to their own content leave the centre centred in the space LEFT OVER beside them: measured
    in Chrome at 2560px before this, the sentence's midpoint sat 274.66px left of the viewport's on
    this tier. flex:1 1 0 on both sides makes them the same width whatever they hold; min-width:0
    lets a side zone go under its own content rather than force a wrap.

    Below 1421px of footer CONTENT the centre takes a row of its own UNDER the two side regions,
    where it spans the footer and is centred on its axis. Below 520px the side phrases not
    share a row either, so every region takes one and aligns left, which is the 375px stack. Both
    numbers are the portal's, because this tier and the portal now carry ONE rule set: the wider
    surface sets the number and portal/tests/test_footer_regions.py holds the two sides identical.

    FAILS IF the footer stops being a wrapping flex row or stops being a query container, if a side
    zone stops taking the equal zero basis, if the centre stops being content-sized or stops
    centring its text, if either state below one row goes, if one stops following the rules it
    overrides (they tie on specificity, so an override placed above them does nothing at all), or if
    a viewport rule comes back in their place."""
    page = (built / "pages" / "surveys" / "index.html").read_text(encoding="utf-8")
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    rule = re.search(r"\bfooter\{([^}]*)\}", css)
    assert rule and "display:flex" in rule.group(1) and "flex-wrap:wrap" in rule.group(1), \
        f"the footer must be a wrapping flex row: {rule and rule.group(1)!r}"
    assert "align-items:center" in rule.group(1), (
        f"one vertical alignment on every surface: {rule.group(1)!r}")
    assert "container-type:inline-size" in rule.group(1), (
        f"the footer must establish the query container the two states below one row ask about; "
        f"without it neither @container rule can ever match: {rule.group(1)!r}")
    for zone, decls in ((".fleft", ("flex:1 1 0", "min-width:0")),
                        (".fcenter", ("flex:0 1 auto", "min-width:0", "text-align:center")),
                        (".fright", ("flex:1 1 0", "min-width:0", "text-align:right"))):
        m = re.search(re.escape(zone) + r"\{([^}]*)\}", css)
        assert m, f"{zone} carries no rule"
        for decl in decls:
            assert decl in m.group(1), f"{zone} must declare {decl}, got {m.group(1)!r}"

    centre_row = css.find("@container (max-width:1421px){.fcenter{order:1;flex:1 1 100%}}")
    assert centre_row > 0, (
        "below 1421px of footer content the centre must take a full row of its own, or it is "
        "centred in the space left over beside the machine-readable link instead of on the axis")
    stack = css.find("@container (max-width:520px){.fzone{order:0;flex:1 1 100%;text-align:left}}")
    assert stack > centre_row, (
        "below 520px of footer content every region must take a full row and align left, in a rule "
        "that FOLLOWS the centre's own-row rule: the two tie on specificity, so placed above it the "
        "stack would not restore the reading order at 375px")
    assert css.index(".fright{") < centre_row, (
        "both states below one row must follow the zone rules they override; the selectors tie on "
        "specificity and source order alone decides")
    for gone in ("@media(max-width:760px){.fzone", "@media (max-width:760px){.fzone"):
        assert gone not in css, (
            "the footer's width is not the viewport's on this tier, so the stacking rule must not "
            "go back to asking the viewport")
    assert re.search(r"\bmain\{[^}]*padding:1\.6rem 1\.25rem 2\.2rem", css), (
        "the separation above the footer belongs to the reading column, not to the footer: the "
        "footer carries no margin-top of its own (the SPA's footer cannot, its body does not "
        "scroll), so main is where the space is stated")


def test_the_footer_lockup_is_sized_in_css_and_never_outgrows_its_zone(built):
    """The committed lockup is 1919px wide because it is the brand kit's own raster; what a reader
    sees is a 30.8px-high mark, and the width follows from the height.

    FAILS IF the height rule goes (every page would then paint the file at full size and the footer
    would be taller than the document above it), if the width stops following the height, or if the
    max-width cap is lost. The cap is what holds the mark inside the stacked 375px row whatever the
    committed file's own width becomes, and object-fit keeps its proportions where the cap bites."""
    for rel in _kinds(built):
        css = (built / "pages" / rel).read_text(
            encoding="utf-8").split("<style>", 1)[1].split("</style>", 1)[0]
        m = re.search(r"\.orglogo img\{([^}]*)\}", css)
        assert m, f"{rel}: the footer lockup carries no sizing rule"
        for decl in ("height:30.8px", "width:auto", "max-width:100%", "object-fit:contain"):
            assert decl in m.group(1), f"{rel}: the lockup rule must declare {decl}: {m.group(1)!r}"


def test_the_new_chrome_carries_only_the_identity_mark_and_no_script(built):
    """The tier's determinism posture, re-asserted across EVERY page kind, with the one exception this
    workflow names. The pages share the site's identity mark with the SPA, as ONE same-origin file the
    portal image serves and the browser caches once; every other asset stays inline and no build-time
    read or external fetch is introduced. FAILS IF the header smuggles in a script, an external
    stylesheet, or any src beyond the allow-list: an http, https, protocol-relative or data src
    fails on the same line, in every quoting form, and so does an extra src of any kind."""
    for rel in _kinds(built):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        assert "<script" not in page.replace('<script type="application/ld+json">', ""), \
            f"{rel}: no executable script may appear on a static page"
        srcs = _page_srcs(page, rel)
        assert srcs == _allowed_srcs(rel), \
            f"{rel}: the only fetched assets may be {_allowed_srcs(rel)}, got {srcs}"
        assert 'rel="stylesheet"' not in page, f"{rel}: styles stay inline"
        assert "\u2014" not in page and "\u2013" not in page, f"{rel}: no en/em dashes"


def test_every_page_kind_links_the_favicon_and_the_app_icon(built):
    """Brand-assets workflow This tier shipped no icon link at all, so every entity page asked for
    /favicon.ico and got a 404 on every visit. FAILS IF a page kind loses either link, or if either
    href stops being a same-origin portal path (an absolute URL here would be an external fetch on
    2,655 documents, which is exactly what this tier forbids)."""
    for rel in _kinds(built):
        head = (built / "pages" / rel).read_text(encoding="utf-8").split("</head>", 1)[0]
        assert '<link rel="icon" href="/vendor/favicon.svg" type="image/svg+xml">' in head, \
            f"{rel}: no favicon link, so the page 404s /favicon.ico on every visit"
        assert '<link rel="apple-touch-icon" href="/vendor/brand/ausmt-icon-180.png">' in head, \
            f"{rel}: no apple-touch-icon, so a home-screen shortcut renders a page screenshot"
        hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="([^"]+)"', head)
        assert all(h.startswith("/vendor/") for h in hrefs), \
            f"{rel}: icon links must be same-origin portal paths, got {hrefs}"


def test_every_page_kind_carries_the_ausmt_mark_beside_the_wordmark(built):
    """The identity swap itself. Every surface of the site opens with the same mark: the SPA
    header and every generated page. FAILS IF a page kind renders the wordmark without the mark, or
    puts the mark anywhere but the header's left identity zone, or sizes it off the shared rule."""
    for rel in _kinds(built):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        head = page.split("<header", 1)[1].split("</header>", 1)[0]
        assert ('<div class="hzone hleft">'
                '<img class="brandmark" src="/vendor/brand/ausmt-mark.svg" alt="AusMT" '
                'width="30" height="30">'
                '<a class="wordmark" href="/">AusMT</a>') in head, \
            f"{rel}: the mark must open the header's identity zone, beside the wordmark: {head[:300]!r}"
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        assert ".brandmark{height:30px;width:30px;display:block;flex:none}" in css, \
            f"{rel}: the mark must carry the shared sizing rule the SPA header uses"


# The parent-organisation mark, WITHDRAWN. It must not close a header from the right zone; the
# the rule takes it off every surface of the site, so what this asserts is that the emitter
# puts it on NO page kind, in no zone. The portal surface's half of the same rule is held in
# portal/tests/test_header_geometry_parity.py, character for character.
ORG_MARK_IMG = '<a class="orgmark" href="https://www.auscope.org.au" target="_blank" rel="noopener noreferrer" title="AuScope"><img src="/vendor/auscope-icon-white.png" alt="AuScope" width="29" height="30"></a>'
ORG_MARK_CLASS = 'class="orgmark"'
ORG_MARK_RULE = ".orgmark{display:flex;align-items:center;flex:none;margin-left:16px}"
ORG_MARK_IMG_RULE = ".orgmark img{height:30px;width:auto;display:block}"


def test_no_page_kind_carries_the_auscope_org_mark_in_its_header(built):
    """The withdrawal, on every page kind the tier emits. FAILS IF the anchor literal, the .orgmark
    class or either of its two CSS rules survives on any page: those four spellings are how the mark
    would come back, and a header restored from a pre-rule revision carries all four at once.

    The header is emitted from ONE literal, so this is really one assertion made 2,655 times; that
    is exactly the point, because the emitter is also the one place a revert would land."""
    for rel in _kinds(built):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        head = page.split("<header", 1)[1].split("</header>", 1)[0]
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        for label, needle, where in (("the anchor", ORG_MARK_IMG, page),
                                     ("the class", ORG_MARK_CLASS, head),
                                     ("the zone rule", ORG_MARK_RULE, css),
                                     ("the sizing rule", ORG_MARK_IMG_RULE, css)):
            assert needle not in where, (
                f"{rel}: the header's AuScope org-mark is withdrawn from every surface; {label} is "
                f"back as {needle!r}")
        # The right zone survives the withdrawal and keeps the contextual status slot. FAILS IF the
        # zone itself went with the mark: the geometry pins read three zones, and a header with two
        # re-floats the centre tab group on every page in the tier.
        assert 'class="hzone hright"' in head, (
            f"{rel}: the right zone stays; the mark left it, the zone did not")


# The FILE, bounded per page kind, which is the portal surface's pin restated on this one. The mark
# pin above counts the whole anchor literal and the src allow-list holds each kind's src attributes
# Exactly and in order; neither bounds how often the image is NAMED, so a url in the inline CSS or
# a preload link would carry it a second time and pass both.
ORG_ASSET = "auscope-icon-white.png"

# The collection page is now the ONE kind that names it at all: the member-footprint map's corner
# mark, which is a caption on that figure and outside the header rule. Every other kind names the
# file zero times, which is the withdrawal counted rather than spelled.
ORG_ASSET_PER_KIND = {"collections/idxcoll.html": 1}


# The SPA map's watermark, which this tier must NOT grow. The rule puts the AuScope colour
# icon in one place on the site, the Leaflet map container on portal/index.html, because that is the
# surface people screenshot; the generated pages have no such surface, their collection figure draws
# the WHITE icon, and the src allow-list above is deliberately unchanged by that rule. Asserted
# rather than assumed, because a new brand file is exactly the kind of thing that spreads.
COLOUR_ASSET = "auscope-icon-colour.png"


def test_no_page_kind_draws_the_spa_maps_colour_watermark(built):
    """FAILS IF any generated page names the colour icon, in any slot. It would also fail the src
    allow-list, but only as an unexplained count; this says which file and why it may not be here."""
    for rel in _kinds(built):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        assert COLOUR_ASSET not in page, (
            f"{rel}: the AuScope colour icon is the SPA map's watermark and belongs to no page in "
            "this tier; the collection figure draws the white icon")


def test_no_page_kind_names_the_auscope_image_beyond_the_one_figure_that_keeps_it(built):
    """FAILS IF a page kind names the AuScope image more often than the figures it is entitled to,
    or loses the one figure that keeps it. The map mark is drawn into a panel and the retired header
    mark was appended to a zone, so on either surface a careless edit adds rather than replaces, and
    a page naming the file again is the header mark returning by some other markup while every
    spelling-scoped pin above still passes."""
    for rel in _kinds(built):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        want = ORG_ASSET_PER_KIND.get(rel, 0)
        assert page.count(ORG_ASSET) == want, (
            f"{rel}: the AuScope image may be named {want} time(s) on this page kind; "
            f"found {page.count(ORG_ASSET)}")


def test_the_global_header_nav_wraps_rather_than_pushing_the_page_sideways(built):
    """What the narrow-width visual check found. The three tabs carry the SPA's own equal-width
    floor (min-width:112px, min-height:40px), and three of those plus their gaps and the header's
    padding come to more than a 375px phone viewport: measured on the built hub at 375px the
    document scrolled to 468px, so the whole page could be dragged sideways and "Collections" sat
    off the screen.

    The SPA absorbs this because its body does not scroll; a static page's does. The zones already
    wrap, so the nav row wraps too and the tabs stack instead of overflowing. FAILS IF the wrap is
    dropped, or if the zone-level wrap that carries the rest of the header goes."""
    css = (built / "pages" / "surveys" / "index.html").read_text(
        encoding="utf-8").split("<style>", 1)[1].split("</style>", 1)[0]
    nav = re.search(r"header\.site nav\{([^}]*)\}", css)
    assert nav, "the global header must style its own nav row"
    assert "flex-wrap:wrap" in nav.group(1), \
        f"three 112px tabs overflow a 375px viewport; the nav row must wrap: {nav.group(1)}"
    zone = re.search(r"\.hzone\{([^}]*)\}", css)
    assert zone and "flex-wrap:wrap" in zone.group(1), "the header zones must keep wrapping"


# ==================================================================================================
# Hub card fact spacing: the widened gap is CSS, never text
# ==================================================================================================
# The padded separator the hub CARDS carry, exactly as emitted: one plain space each side of a
# span whose horizontal padding supplies the visible gap. Text copied off a card must keep
# reading single-spaced, which is why the gap may never be literal whitespace.
CARD_SEP = '<span class="sep">&#183;</span>'

# Every card fact line both hubs render: /surveys cards carry the org/location line (.idxorg) and
# the stats line (.idxfacts); /collections cards carry their counts line (.idxfacts).
_CARD_LINE = re.compile(r'<p class="(?:idxfacts|idxorg)">(.*?)</p>')


def test_hub_card_fact_separators_are_padded_spans(built):
    """The interpunct separators on the hub cards' fact lines render inside a padded span, so the
    gap between segments widens visibly without a byte of literal whitespace being added. FAILS IF
    a card fact line joins on the bare interpunct again, if the span loses the single plain space
    on each side, or if the padding rule leaves the hub sheet."""
    for rel in ("surveys/index.html", "collections/index.html"):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        assert ".sep{padding:0 .4em}" in css, \
            f"{rel}: the separator padding rule must ride the hub sheet"
        lines = _CARD_LINE.findall(page)
        assert lines, f"{rel}: no card fact lines found"
        seen = 0
        for line in lines:
            n = line.count("&#183;")
            assert line.count(f" {CARD_SEP} ") == n, (
                f"{rel}: every card interpunct must be the padded span with exactly one plain "
                f"space each side, got {line!r}")
            seen += n
        assert seen, f"{rel}: at least one card separator must render, or this pin is vacuous"


def test_hub_card_fact_lines_copy_single_spaced(built):
    """The other half of the same rule: the widened gap must be invisible to selection. Text copied
    off a card reads "1 station &#183; LPMT &#183; ..." with SINGLE spaces, exactly as it did
    before the gap widened. FAILS IF the markup smuggles a double space, a tab or a no-break space
    into any card line's text content, or if the stats line's copied text drifts at all."""
    for rel in ("surveys/index.html", "collections/index.html"):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        for line in _CARD_LINE.findall(page):
            text = html.unescape(re.sub(r"<[^>]+>", "", line))
            assert "  " not in text and "\t" not in text and "\u00a0" not in text, (
                f"{rel}: copied card text must stay single-spaced, got {text!r}")
    pages = _pages_module()
    sv = pages.surveys_index_page(rows=[_one_survey_row()], base=BASE)
    facts = re.search(r'<p class="idxfacts">(.*?)</p>', sv).group(1)
    assert html.unescape(re.sub(r"<[^>]+>", "", facts)) == \
        "1 station · LPMT · 2019 · 4 - 16,000 s · CC BY 4.0"


def test_the_separator_span_stays_on_the_hub_cards_alone(built):
    """The padded span is a CARD affordance. The page-level summary line, the header's counts
    slot, the entity pages' own fact lines and the footer all keep the bare single-spaced join.
    FAILS IF the span leaks into any of them."""
    sv = (built / "pages" / "surveys" / "index.html").read_text(encoding="utf-8")
    summary = re.search(r'<p class="idxsum">(.*?)</p>', sv).group(1)
    assert " &#183; " in summary and 'class="sep"' not in summary, (
        f"the catalogue summary keeps the bare join, got {summary!r}")
    head = sv.split("<header", 1)[1].split("</header>", 1)[0]
    assert 'class="sep"' not in head, "the header counts slot keeps the bare join"
    for rel in ("surveys/idx-a.html", "collections/idxcoll.html"):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        assert 'class="sep"' not in page, f"{rel}: entity pages keep their current spacing"
        assert "&#183;" in page, f"{rel}: the bare interpunct grammar itself must survive"


# ==================================================================================================
# Discoverability: what each page kind says about the site and about where it sits in it
# ==================================================================================================
def _ld_nodes(page):
    """Every JSON-LD block on a page, parsed, in document order."""
    return [json.loads(m) for m in
            re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', page)]


def test_every_page_kind_names_the_site_it_belongs_to(built):
    """Google labelled the whole portal "AuScope" because the only site-level name anywhere in the
    markup was the publisher's. og:site_name is what a link preview prints above the title, so every
    page kind states it, station pages included: an inbound link lands on those most often, and a
    preview card that names the wrong site is wrong wherever it is shared."""
    for rel in _kinds(built):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        assert '<meta property="og:site_name" content="AusMT">' in page, \
            f"{rel}: the page must name the site it belongs to"


def test_the_indexable_page_kinds_carry_the_trail_back_to_the_root(built):
    """A BreadcrumbList is what turns a bare URL in a search result into a labelled path, and the
    entity pages are the ones a reader arrives at cold. The markup matches the VISIBLE crumb word
    for word, which is what Google requires of it.

    FAILS IF a page kind loses its breadcrumb, if a crumb name stops matching the trail the page
    prints, or if a station page grows one: station pages are noindex, so a trail on one describes
    a rich result that can never be rendered and would cost the tier a block per document."""
    expected = {
        "surveys/index.html": ["AusMT", "surveys"],
        "collections/index.html": ["AusMT", "collections"],
        "surveys/idx-a.html": ["AusMT", "surveys", "Index A"],
        "collections/idxcoll.html": ["AusMT", "collections", "Index Collection"],
    }
    for rel, names in expected.items():
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        crumbs = [n for n in _ld_nodes(page) if n.get("@type") == "BreadcrumbList"]
        assert len(crumbs) == 1, f"{rel}: exactly one BreadcrumbList, got {len(crumbs)}"
        items = crumbs[0]["itemListElement"]
        assert [i["name"] for i in items] == names, f"{rel}: {items}"
        assert [i["position"] for i in items] == list(range(1, len(names) + 1)), items
        assert items[0]["item"] == f"{BASE}/", items[0]
        # every crumb name the markup claims is a name the reader is actually shown
        visible = re.search(r'<p class="crumb">(.*?)</p>', page).group(1)
        for name in names:
            assert html.escape(name, quote=True) in visible, \
                f"{rel}: breadcrumb name {name!r} is not in the visible crumb {visible!r}"
    station = [rel for rel in _kinds(built) if rel.startswith("stations/")][0]
    spage = (built / "pages" / station).read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex">' in spage, "station pages stay noindex"
    assert not _ld_nodes(spage), \
        f"{station}: a noindex page carries no structured data at all"


def test_every_json_ld_block_parses_and_the_entity_node_stays_first(built):
    """Order is load-bearing: several pins and any reader taking "the page's structured data" read
    the FIRST block, so the record the page is about must stay in front of its breadcrumb."""
    for rel, entity in (("surveys/idx-a.html", "Dataset"),
                        ("collections/idxcoll.html", "Dataset")):
        nodes = _ld_nodes((built / "pages" / rel).read_text(encoding="utf-8"))
        assert len(nodes) == 2, f"{rel}: entity node plus breadcrumb, got {len(nodes)}"
        assert nodes[0]["@type"] == entity, f"{rel}: the entity node must come first, got {nodes}"
        assert nodes[1]["@type"] == "BreadcrumbList", nodes


# THE CONSTANT FOOTER, over BUILT pages: the emitted document's own structure and CSS, where the
# portal half of this pin (portal/tests/test_footer_regions.py) reads _pages.py's source text.
# The rule and every number the two halves hold it to: LANE-CONTRACT-FOOTER-AUSCOPE.md.
_FLOW_BELOW = 560
_FLOW_RULE = f"@media (max-width:{_FLOW_BELOW}px){{footer{{position:static}}}}"


def test_every_page_kind_holds_its_footer_at_the_viewport_bottom(built):
    """The footer is at the bottom of the VIEWPORT on every page kind, not at the end of the scroll:
    the document is a viewport-tall column, the block above the footer takes the free space, and the
    footer itself is sticky to the bottom edge over the page's own opaque ground.

    A sticky box is never pushed DOWN from its place in flow, so the column and the growing block
    are not decoration around the sticky rule: without them the Collections hub, which is shorter
    than a screen, would show its footer halfway up the page. And because a sticky box keeps that
    place in flow, the last line of a long survey page is never left underneath the footer.

    FAILS if any of the three goes, if the footer stops painting an opaque ground (the content
    passing beneath would show through), or if it stops naming a stacking order above the frozen
    first column of a station table."""
    for rel in _kinds(built):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        assert page.index("</main>") < page.index("<footer>"), \
            f"{rel}: the footer is the page's bottom edge and follows </main>; inside the reading "\
            f"column it is neither a contentinfo landmark nor wide enough for the bold centre line"
        body = re.search(r"(?m)^\s*body\{([^}]*)\}", css)
        assert body, f"{rel}: no body rule"
        for decl in ("min-height:100vh", "display:flex", "flex-direction:column"):
            assert decl in body.group(1), \
                f"{rel}: the page must be a viewport-tall column, missing {decl}: {body.group(1)!r}"
        grows = [r for r in re.findall(r"(?m)^\s*main\{([^}]*)\}", css) if "flex:1 0 auto" in r]
        assert len(grows) == 1 and "width:min(" in grows[0], \
            f"{rel}: exactly one main rule must take the column's free space and state its width; "\
            f"a flex item with auto side margins and an auto width shrinks to its content: {grows!r}"
        foot = re.search(r"(?m)^\s*footer\{([^}]*)\}", css)
        assert foot, f"{rel}: no footer rule"
        for decl in ("position:sticky", "bottom:0", "background:#11182D"):
            assert decl in foot.group(1), \
                f"{rel}: the footer must declare {decl}: {foot.group(1)!r}"
        assert re.search(r"z-index:[1-9]", foot.group(1)), \
            f"{rel}: the footer must name its stacking order: {foot.group(1)!r}"
        assert _FLOW_RULE in css and css.index(_FLOW_RULE) > foot.start(), \
            f"{rel}: below {_FLOW_BELOW}px of viewport the footer returns to flow, in a rule that " \
            f"FOLLOWS the sticky one; the two tie on specificity"
        # THE SEPARATION ABOVE THE FOOTER IS main'S, not the footer's own margin. A
        # footer{margin-top:2.2rem} is what the one rule set cannot carry: the Map's
        # footer is the last child of a column whose body does not scroll, so a margin there takes
        # height from the map itself. It lives in main's bottom padding, where the portal's content
        # pages already keep it. The failure this replaces (a bottom padding lifting the footer off
        # the viewport at the end of the scroll) does not reproduce and is not what guarantees the
        # footer rests on the document's bottom edge; what guarantees it is that the footer is the
        # LAST box in a body with no bottom padding of its own. Measured in Chrome at 900x500,
        # scrolled to the end: the footer's bottom sits at 499.61px of a 500px viewport on a survey
        # page, a hub and 404.html, the 0.39px being the sub-pixel the scroll height rounds.
        assert "padding:1.6rem 1.25rem 2.2rem" in css, (
            f"{rel}: main states the separation above the footer, because the footer no longer "
            f"carries a margin of its own")
        assert "margin-top" not in foot.group(1) and "margin:" not in foot.group(1), (
            f"{rel}: the footer takes no margin; it is not in the one rule set and on the Map it "
            f"would take height from the map: {foot.group(1)!r}")
        assert "padding-bottom" not in body.group(1) and not re.search(
                r"padding:[^;]*\s\S", body.group(1)), (
            f"{rel}: body carries no bottom padding, which is what makes the footer's flow "
            f"position the document's own bottom edge: {body.group(1)!r}")


def test_the_centre_line_is_bold_on_every_page_kind(built):
    """The acknowledgement renders bold, the anchor included, as ONE declaration on the
    centre zone. FAILS if the weight goes, if it is written per span in the markup, or if a second
    declaration appears for the two surfaces to drift on."""
    for rel in _kinds(built):
        css = (built / "pages" / rel).read_text(
            encoding="utf-8").split("<style>", 1)[1].split("</style>", 1)[0]
        centre = re.search(r"(?m)^\s*\.fcenter\{([^}]*)\}", css)
        assert centre and "font-weight:700" in centre.group(1), \
            f"{rel}: the centre zone must declare font-weight:700: {centre and centre.group(1)!r}"
        assert css.count("font-weight:700") == 1, \
            f"{rel}: the weight is one declaration on the zone, not one per surface it reaches"
