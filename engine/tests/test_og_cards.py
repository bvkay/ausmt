"""The link-preview cards: the signature row every card family carries, and the collection card.

A card is the only thing most people ever see of a page. It is shared into Slack, Teams and X, and
it is resampled to roughly a third of its width on the way, so what it says has to survive at that
size. Two things are pinned here.

THE SIGNATURE ROW. The AuScope mark sits left of the ausmt.auscope.org.au wordmark, on the card's
text margin, at the wordmark's own line height and centred on its ink, so the pair reads as one line
of type rather than as a logo with a caption beside it. The pins are geometric and tolerant: they
measure the rendered PNG rather than trusting the drawing code, and they allow the few pixels that
resampling takes off a mark's edge.

THE COLLECTION CARD. It previews the collection page's own map: every member station, coloured by
member survey in the hub's palette, with NO locator inset (a grouping of surveys has no single place
to point at). Both properties are asserted against the pixels, and the inset pin is checked to have
teeth by measuring the same region on a survey card, which does carry one.
"""
import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("PIL")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402

SAMPLE_EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))
BASE = "https://ausmt.example.test"

# The bottom-left corner of every card: where the signature row is, and nowhere else on any card.
_SIG_REGION = (0, 500, 620, 630)


def _pages_module():
    sys.path.insert(0, str(REPO / "extract"))
    import _pages
    return _pages


def _survey(tmp_path, slug, name, lat, extra=""):
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\nregion: South Australia\n"
        f"organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
        f"abstract: A card fixture survey.\n{extra}", encoding="utf-8")
    for src in SAMPLE_EDIS:
        text = src.read_text(encoding="latin-1")
        # Move each member off its sibling so the members' dots land in different places and the
        # colour pin measures real separation rather than one pile of overlapping circles.
        text = re.sub(r"(?m)^(\s*LAT\s*=\s*)[-\d.:]+", rf"\g<1>{lat}", text)
        (edir / src.name).write_text(text, encoding="latin-1")
    return tmp_path / "surveys"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One corpus whose two surveys are members of one collection, built once with the cards on."""
    tmp = tmp_path_factory.mktemp("ogcards")
    coll = ("collection:\n  id: cardcoll\n  title: Card Collection\n  type: programme\n"
            "  status: active\n")
    surveys = _survey(tmp, "card-a", "Card A", "-30.5", coll)
    _survey(tmp, "card-b", "Card B", "-24.5", coll)
    out = tmp / "out"
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(out), "--bundle-edi",
                            "--no-validate", "--products", str(out / "products"),
                            "--sitemap-base", BASE])
    assert rc == 0, f"build rc={rc}"
    return out


def _boxes(path):
    """(size, mark box, wordmark box) measured from the card's own pixels.

    The mark is the near-white ink in the signature corner and the wordmark is the coral. Both are
    read off the rendered file rather than computed from the drawing code, so a change that moves
    the row fails here even if the constants behind it still look right."""
    from PIL import Image
    with Image.open(path) as im:
        img = im.convert("RGB")
    px = img.load()
    x0, y0, x1, y1 = _SIG_REGION
    white, coral = [], []
    for y in range(y0, min(y1, img.size[1])):
        for x in range(x0, min(x1, img.size[0])):
            r, g, b = px[x, y]
            if min(r, g, b) >= 240:
                white.append((x, y))
            elif r >= 190 and g < 150 and b < 140 and r - b >= 60:
                coral.append((x, y))
    assert white, f"{path}: no mark ink found in the signature corner"
    assert coral, f"{path}: no wordmark ink found in the signature corner"

    def box(pts):
        return (min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts))
    return img.size, box(white), box(coral)


def _assert_signature_row(path, line_h):
    size, mark, word = _boxes(path)
    assert size == (1200, 630), f"{path}: a link-preview card is 1200x630, got {size}"
    assert mark[2] < word[0], \
        f"{path}: the mark must sit entirely left of the wordmark, mark {mark} wordmark {word}"
    mark_cy, word_cy = (mark[1] + mark[3]) / 2, (word[1] + word[3]) / 2
    assert abs(mark_cy - word_cy) <= 2, \
        f"{path}: the pair must read as one line, centres {mark_cy} and {word_cy}"
    mark_h = mark[3] - mark[1] + 1
    assert abs(mark_h - line_h) / line_h <= 0.15, \
        f"{path}: the mark's height must be the wordmark's line height, got {mark_h} for {line_h}"
    # The row starts on the card's text margin, like every other line in the left column.
    assert mark[0] <= _pages_module()._CARD_MARGIN + 2, \
        f"{path}: the row must start on the text margin, got x={mark[0]}"


def _line_h():
    """The wordmark's own line height, from the face the cards actually draw with."""
    pages = _pages_module()
    font = pages._card_font(pages._CARD_WORDMARK_SIZE)
    try:
        return sum(font.getmetrics())
    except AttributeError:
        return 35


def test_the_engine_carries_the_same_mark_the_portal_serves():
    """The engine image ships no portal tree, so the cards read the mark from a copy beside the
    emitter. FAILS IF the two ever differ: one of the two surfaces would then sign itself with an
    asset the other does not have."""
    engine_copy = REPO / "extract" / "_auscope_mark.png"
    portal_copy = REPO.parent / "portal" / "vendor" / "auscope-icon-white.png"
    assert engine_copy.is_file(), "the emitter must ship the mark it draws"
    if not portal_copy.is_file():
        pytest.skip("portal tree not shipped in this topology")
    assert engine_copy.read_bytes() == portal_copy.read_bytes(), \
        "the engine's mark and the portal's vendored mark must be one asset, byte for byte"


def test_every_survey_card_signs_itself_with_the_mark_and_the_wordmark(built):
    cards = sorted((built / "pages" / "og").glob("*.png"))
    assert cards, "the build must render a card per survey"
    for card in cards:
        _assert_signature_row(card, _line_h())


def test_every_collection_card_signs_itself_the_same_way(built):
    cards = sorted((built / "pages" / "og" / "collections").glob("*.png"))
    assert cards, "the build must render a card per collection"
    for card in cards:
        _assert_signature_row(card, _line_h())


def _panel_box(pages):
    """The collection card's map panel, shrunk 24 px per side so an edge pixel of the panel's own
    frame cannot answer either of the pins below."""
    import _au_outline as au
    ext = au.EXTENT
    pw = 510
    ph = round(pw * (ext["n"] - ext["s"]) / (ext["e"] - ext["w"]))
    px0, py0 = 640, 70 + ((560 - 70) - ph) // 2
    return (px0 + 24, py0 + 24, px0 + pw - 24, py0 + ph - 24)


def _panel_stats(path, box, palette):
    from PIL import Image
    with Image.open(path) as im:
        img = im.convert("RGB")
    px = img.load()
    ground, hits = 0, set()
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            c = px[x, y]
            if c == (13, 20, 40):
                ground += 1
            if c in palette:
                hits.add(c)
    return ground, hits


def test_the_collection_card_draws_its_members_in_their_own_colours_and_no_inset(built):
    """The card IS the collection page's map: one colour per member survey, drawn from the hub's
    own palette so a survey is the same colour on all three surfaces, and no locator inset, because
    a collection spanning a continent has no single place to point at.

    The inset pin is checked to have teeth on the same line: the identical region of a SURVEY card,
    which does carry an inset, is measured and must be full of card ground."""
    pages = _pages_module()
    box = _panel_box(pages)
    palette = {pages._rgb(c) for c in pages._COLL_PAL}
    card = built / "pages" / "og" / "collections" / "cardcoll.png"
    assert card.is_file(), "the collection must get a card"
    ground, hits = _panel_stats(card, box, palette)
    assert len(hits) >= 2, \
        f"a two-member collection must draw two member colours, found {sorted(hits)}"
    assert ground == 0, \
        f"an inset would put {ground} card-ground pixels inside the map panel; this card has none"
    survey_card = sorted((built / "pages" / "og").glob("*.png"))[0]
    sground, _ = _panel_stats(survey_card, box, palette)
    assert sground > 1000, (
        "the no-inset pin is vacuous unless the same region on an inset-bearing card fails it; "
        f"the survey card showed only {sground} ground pixels")


def test_a_page_only_ever_advertises_a_card_that_was_written(built):
    """FAILS IF a page names a card URL with no file behind it. The page used to derive the URL from
    "is Pillow importable", which is a claim about the environment and not about the file, so a
    failed write shipped an og:image that every link-preview fetcher resolved to a 404."""
    for rel, want in (("surveys/card-a.html", "/data/pages/og/card-a.png"),
                      ("collections/cardcoll.html", "/data/pages/og/collections/cardcoll.png")):
        page = (built / "pages" / rel).read_text(encoding="utf-8")
        m = re.search(r'property="og:image" content="([^"]+)"', page)
        assert m, f"{rel}: og:image required"
        assert m.group(1) == f"{BASE}{want}", \
            f"{rel}: og:image must be the served card URL, got {m.group(1)}"
        onto = built / m.group(1)[len(BASE) + len("/data/"):]
        assert onto.is_file() and onto.read_bytes()[:2] == b"\x89P", \
            f"{rel}: the advertised card {onto} must exist and be a PNG"


def test_a_collection_with_no_disclosed_positions_gets_no_card(tmp_path):
    """A bare coastline would read as a collection with no coverage, which is a claim about the data
    rather than about the map. Nothing is written, and the page falls back to the root card."""
    pages = _pages_module()
    card = tmp_path / "empty.png"
    wrote = pages._og_collection_card(card, title="Empty", facts_line="0 surveys",
                                      taxonomy_line="", member_labels=["A"],
                                      member_points={"A": []})
    assert wrote is False and not card.exists(), "no positions means no card at all"


def test_the_collection_card_keeps_the_whole_title_by_stepping_the_type_down(tmp_path):
    """A title that is silently cut is a title the card gets wrong. The longest name in the corpus
    is a programme's full expansion, and it has to arrive whole."""
    pages = _pages_module()
    long_title = "Australian Lithospheric Architecture Magnetotelluric Project"
    card = tmp_path / "long.png"
    assert pages._og_collection_card(card, title=long_title, facts_line="14 surveys",
                                     taxonomy_line="programme", member_labels=["A"],
                                     member_points={"A": [(133.0, -25.0), (140.0, -30.0)]})
    from PIL import ImageDraw, Image
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for size in pages._CARD_TITLE_SIZES:
        lines, whole = pages._card_lines(d, long_title, pages._card_font(size),
                                         pages._CARD_TEXT_WIDTH, 3)
        if whole:
            assert " ".join(lines) == long_title, f"the title must arrive whole, got {lines}"
            return
    pytest.fail(f"no size in {pages._CARD_TITLE_SIZES} fits {long_title!r} whole")


def test_the_cards_are_reachable_at_the_url_the_pages_name(built):
    """The cards live in the DATA volume, served under /data/*. The pages/ tree has no bare route of
    its own, so {base}/data/pages/og/... is the only URL a crawler can fetch a card at; a
    {base}/pages/... form advertises a 404 to every preview fetcher there is."""
    report = json.loads((built / "build_report.json").read_text(encoding="utf-8"))
    assert report.get("pages"), "the build must record the pages it wrote"
    for page in (built / "pages").rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for url in re.findall(r'property="og:image" content="([^"]+)"', text):
            assert url.startswith(f"{BASE}/data/") or url == f"{BASE}/vendor/social-card.png", \
                f"{page.name}: og:image must be a served URL, got {url}"
