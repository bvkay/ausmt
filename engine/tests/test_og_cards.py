"""The link-preview cards: what every card family carries, and what the collection card carries.

A card is the only thing most people ever see of a page. It is shared into Slack, Teams and X, and
it is resampled to roughly a third of its width on the way, so what it says has to survive at that
size. These are the properties pinned here, all measured off the rendered PNG rather than read back
out of the drawing code, so a constant that still looks right cannot hide a card that is wrong.

THE SIGNATURE ROW. The AuScope mark sits left of the ausmt.auscope.org.au address, on the card's
text margin, at the address's own line height and centred on its ink, so the pair reads as one line
of type rather than as a logo with a caption beside it. The address is set in Inter Bold, the face
the hand-made root card's artwork uses, so the three card families sign themselves in one face.

THE CORNER MARK. Survey and collection cards carry the AusMT mark in the top-left corner, on the
same text margin the title sits on. The ROOT card does not: that card's artwork is the mark, and a
second copy of it would read as a duplicate (pinned in portal/tests/test_social_card.py).

THE TEXT COLUMN. Every card declares the width its text may occupy, and nothing crosses it: the
title walks the size ladder and wraps, and the fact lines wrap. This is scanned on the pixels of
every card the fixture builds, because the failure it prevents is type running into the map panel.

THE COLLECTION CARD. It previews the collection page's own map at its declared scale: every member
station, coloured by member survey in the hub's palette, with NO locator inset (a grouping of
surveys has no single place to point at).

THE LOCATOR INSET. On a survey card it is composited at _CARD_INSET_ALPHA rather than painted
opaque, so the stations it covers still show through it, and only its centre marker stays solid.
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
# The top-left corner, wide enough to catch a mark that drifted off the margin and short enough to
# stop above the title's own slot. Nothing but the corner mark may put ink here.
_CORNER_REGION = (0, 0, 300, 100)
# The card's three text inks. A pixel of any of them past the declared column edge is type that has
# crossed into the map panel, which is the failure the column rule exists to prevent.
_TEXT_INKS = ((255, 255, 255), (143, 163, 176), (201, 212, 232))


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
    """The address's own line height, from the face the cards actually set the address in."""
    pages = _pages_module()
    return sum(pages._card_address_font(pages._CARD_WORDMARK_SIZE).getmetrics())


def test_the_address_is_set_in_the_pinned_bold_face_at_the_declared_size():
    """The signature row's face and size, held as the numbers they are.

    The address is the one string all three card families carry, and the root card's hand-made
    artwork sets it in Inter Bold; the generated cards read a pinned copy of that same face from
    beside the emitter so the three rows are one row rather than three that agree on the spelling.
    The mark's height follows from the face, so pinning the face pins the row's whole geometry.

    FAILS IF the address falls back to the bundled bitmap face, or the size drifts: either would
    resize the mark beside it and break the row on every card in the corpus at once."""
    pages = _pages_module()
    assert pages._CARD_WORDMARK_SIZE == 31, \
        f"the address is set at 31 px, got {pages._CARD_WORDMARK_SIZE}"
    assert pages._CARD_ADDRESS_FACE.name == "_inter_bold.ttf", \
        f"the address face is the pinned Inter Bold beside the emitter, got {pages._CARD_ADDRESS_FACE}"
    font = pages._card_address_font(pages._CARD_WORDMARK_SIZE)
    assert Path(font.path) == pages._CARD_ADDRESS_FACE, \
        f"the face must be loaded from {pages._CARD_ADDRESS_FACE}, got {font.path}"
    assert sum(font.getmetrics()) == 39, \
        f"the row stands on this face's 39 px line, got {sum(font.getmetrics())}"


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


@pytest.mark.parametrize("engine_name, portal_rel", [
    ("_ausmt_mark.png", "portal/vendor/brand/ausmt-mark-168.png"),
    ("_inter_bold.ttf", "portal/tools/brand_font/Inter-Bold.ttf"),
    ("_inter_bold_OFL.txt", "portal/tools/brand_font/OFL.txt"),
])
def test_the_engine_carries_the_portals_own_card_assets(engine_name, portal_rel):
    """Everything the cards draw with ships beside the emitter, and every copy is the portal's file
    byte for byte. FAILS IF the two ever differ: the corner mark or the address face would then
    render one way on the portal's own surfaces and another on the cards the corpus serves.

    The licence text is on this list because it is not documentation. Inter is Open Font Licence,
    the engine image is a separate distribution from the portal, and a copy of the face shipped
    without its licence is a licence breach rather than an untidy tree."""
    engine_copy = REPO / "extract" / engine_name
    portal_copy = REPO.parent / portal_rel
    assert engine_copy.is_file(), f"the emitter must ship {engine_name}"
    if not portal_copy.is_file():
        pytest.skip("portal tree not shipped in this topology")
    assert engine_copy.read_bytes() == portal_copy.read_bytes(), \
        f"{engine_name} and {portal_rel} must be one asset, byte for byte"


def test_the_generated_cards_stand_on_the_root_cards_ground(built):
    """One ground across all three card families. The root card is hand-made artwork on its own flat
    field, and a generated card a few units off it reads, beside it in a feed, as a near miss rather
    than as the same site. FAILS IF the literal drifts or a card stops using it."""
    from PIL import Image
    pages = _pages_module()
    assert pages._CARD_GROUND == (7, 22, 47), \
        f"the cards' ground is the root card artwork's own, got {pages._CARD_GROUND}"
    cards = sorted((built / "pages" / "og").rglob("*.png"))
    assert cards, "the build must render cards"
    for card in cards:
        with Image.open(card) as im:
            px = im.convert("RGB").load()
        for probe in ((0, 0), (1199, 0), (3, 315)):
            assert px[probe] == pages._CARD_GROUND, \
                f"{card.name}: the field at {probe} is {px[probe]}, not {pages._CARD_GROUND}"


def test_every_generated_card_carries_the_ausmt_mark_in_its_top_left_corner(built):
    """The mark names the site the card belongs to, and it leads rather than trails, so it sits on
    the same text margin the title does with clear space under it.

    Three things are held. The slot is the size and place it was approved at, held against literals
    rather than against the constants that draw it, because a slot rebuilt from _CARD_CORNER_SIZE
    grows with that constant and so would accept a mark of any size. The mark's ink stays inside
    that slot, so it cannot grow into the title. And the slot's LEFT edge has teeth: the strip
    between the card edge and the text margin, across the mark's own rows, must be empty, so a mark
    drawn off the margin fails here rather than quietly sitting in the bleed."""
    pages = _pages_module()
    assert (pages._CARD_CORNER_SIZE, pages._CARD_CORNER_Y) == (42, 44), (
        "the corner mark is drawn 42 px high at y 44, got "
        f"{(pages._CARD_CORNER_SIZE, pages._CARD_CORNER_Y)}")
    slot = (pages._CARD_MARGIN, pages._CARD_CORNER_Y,
            pages._CARD_MARGIN + pages._CARD_CORNER_SIZE, pages._CARD_CORNER_Y
            + pages._CARD_CORNER_SIZE)
    assert slot == (60, 44, 102, 86), f"the corner slot moved off its declared box, now {slot}"
    cards = sorted((built / "pages" / "og").rglob("*.png"))
    assert cards, "the build must render cards"
    from PIL import Image
    for card in cards:
        with Image.open(card) as im:
            px = im.convert("RGB").load()
        x0, y0, x1, y1 = _CORNER_REGION
        ink = [(x, y) for y in range(y0, y1) for x in range(x0, x1)
               if px[x, y] != pages._CARD_GROUND]
        assert ink, f"{card.name}: no mark ink in the card's top-left corner"
        box = (min(p[0] for p in ink), min(p[1] for p in ink),
               max(p[0] for p in ink), max(p[1] for p in ink))
        assert (box[0] >= slot[0] and box[1] >= slot[1]
                and box[2] <= slot[2] and box[3] <= slot[3]), \
            f"{card.name}: the corner mark's ink {box} must stay inside its slot {slot}"
        bleed = [(x, y) for y in range(slot[1], slot[3]) for x in range(0, pages._CARD_MARGIN)
                 if px[x, y] != pages._CARD_GROUND]
        assert not bleed, \
            f"{card.name}: the corner mark must start on the text margin, found ink at {bleed[:3]}"


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


def _panel_geometry(pages):
    """(map box, panel frame box) for the collection card, REBUILT from the constants the emitter
    draws with rather than restated here, so a change to the map scale moves this with it. The pin
    below then holds the arithmetic's answer against the literal geometry the design was drawn on,
    which is what stops a self-consistent change from quietly resizing the card."""
    import _au_outline as au
    ext = au.EXTENT
    pw = pages._COLL_CARD_MAP_PX
    ph = round(pw * (ext["n"] - ext["s"]) / (ext["e"] - ext["w"]))
    px0 = pages._CARD_SIZE[0] - pages._CARD_PANEL_AIR - pages._CARD_PANEL_INSET - pw
    py0 = 70 + ((560 - 70) - ph) // 2
    inset = pages._CARD_PANEL_INSET
    return (px0, py0, pw, ph), (px0 - inset, py0 - inset, px0 + pw + inset, py0 + ph + inset)


def _panel_box(pages):
    """The collection card's map, shrunk 24 px per side so an edge pixel of the panel's own frame
    cannot answer either of the pins below."""
    (px0, py0, pw, ph), _ = _panel_geometry(pages)
    return (px0 + 24, py0 + 24, px0 + pw - 24, py0 + ph - 24)


def _count(path, box, wanted):
    """How many pixels of each wanted colour fall inside `box` on a rendered card."""
    from PIL import Image
    with Image.open(path) as im:
        px = im.convert("RGB").load()
    seen = dict.fromkeys(wanted, 0)
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            c = px[x, y]
            if c in seen:
                seen[c] += 1
    return seen


def test_the_collection_card_draws_its_members_in_their_own_colours_and_no_inset(built, tmp_path):
    """The card IS the collection page's map: one colour per member survey, drawn from the hub's
    own palette so a survey is the same colour on all three surfaces, and no locator inset, because
    a collection spanning a continent has no single place to point at.

    The inset is detected by the colour its own PANEL FILL lands on when composited at
    _CARD_INSET_ALPHA. Two nearer-looking probes do not work. Counting card ground no longer
    separates the families, because a translucent inset punches no ground-coloured hole in a survey
    card either. And the inset's copper centre marker is a member colour in the hub palette, so a
    collection whose member happens to be drawn in copper would fail a marker count for a reason
    that has nothing to do with insets. The blend is a colour only compositing can produce.

    The pin is checked to have teeth on the same line: a survey card built over a footprint the
    inset actually covers must be full of that blend."""
    pages = _pages_module()
    box = _panel_box(pages)
    palette = {pages._rgb(c) for c in pages._COLL_PAL}
    inset_fill = _blend(pages, (17, 26, 51))
    assert inset_fill not in palette, \
        f"the inset probe {inset_fill} must not be a member colour, or it cannot discriminate"
    card = built / "pages" / "og" / "collections" / "cardcoll.png"
    assert card.is_file(), "the collection must get a card"
    seen = _count(card, box, tuple(palette) + (inset_fill,))
    hits = {c for c in palette if seen[c]}
    assert len(hits) >= 2, \
        f"a two-member collection must draw two member colours, found {sorted(hits)}"
    assert seen[inset_fill] == 0, \
        f"an inset would put {seen[inset_fill]} composited pixels in the map; this card has none"
    survey = _grid_card(pages, tmp_path / "inset.png")
    covered = _count(survey, (900, 380, 1200, 630), (inset_fill,))[inset_fill]
    assert covered > 1000, (
        "the no-inset pin is vacuous unless an inset-bearing card fails it; the survey card showed "
        f"only {covered} composited pixels")


def test_the_collection_map_is_drawn_at_the_declared_scale(built):
    """The collection map is the survey card's panel width at _COLL_CARD_MAP_SCALE, and the panel
    around it keeps _CARD_PANEL_AIR on the card's edge. Both the arithmetic and the geometry it
    lands on are held: the constants must multiply out, AND the frame the emitter actually drew must
    be the box the design was drawn on, so a pair of constants cannot be changed in step to move the
    panel while every derived number still agrees with itself."""
    pages = _pages_module()
    assert pages._COLL_CARD_MAP_PX == round(
        pages._COLL_CARD_MAP_WIDTH * pages._COLL_CARD_MAP_SCALE), \
        "the map's pixel width is its base width at the declared scale"
    _, frame = _panel_geometry(pages)
    assert frame == (522, 44, 1166, 586), f"the panel frame's declared box moved, now {frame}"
    from PIL import Image
    card = built / "pages" / "og" / "collections" / "cardcoll.png"
    with Image.open(card) as im:
        px = im.convert("RGB").load()
    frame_ink = (pages._rgb(pages._MAP_PANEL), pages._rgb(pages._MAP_PANEL_LINE))
    pts = [(x, y) for y in range(630) for x in range(400, 1200) if px[x, y] in frame_ink]
    drawn = (min(p[0] for p in pts), min(p[1] for p in pts),
             max(p[0] for p in pts), max(p[1] for p in pts))
    assert drawn == frame, f"the drawn panel {drawn} must be the declared panel {frame}"
    air = pages._CARD_SIZE[0] - 1 - drawn[2]
    assert air == pages._CARD_PANEL_AIR - 1, \
        f"the panel keeps {pages._CARD_PANEL_AIR} px against the card's edge, its ink leaves {air}"


def _grid_card(pages, path, alpha=None):
    """A survey card over a square footprint dense enough that stations land under the locator
    inset. The fixture corpus cannot answer the pin below on its own: the footprint panel's shape
    follows the survey's own aspect, and on a wide survey the inset falls clear of the panel
    entirely, so the card that tests the compositing is built here with the geometry it needs."""
    pts = [(120.0 + 25.0 * i / 19, -35.0 + 24.0 * j / 19, "mt")
           for i in range(20) for j in range(20)]
    saved = pages._CARD_INSET_ALPHA
    if alpha is not None:
        pages._CARD_INSET_ALPHA = alpha
    try:
        pages._og_card(path, title="Grid", subtitle="400 stations", region_year="Test",
                       period_line="period", dims_line="extent", points=pts)
    finally:
        pages._CARD_INSET_ALPHA = saved
    return path


def _blend(pages, over):
    """The colour the inset's own fill lands on when composited over `over` at the declared alpha."""
    return tuple(round(pages._CARD_INSET_ALPHA * g + (1 - pages._CARD_INSET_ALPHA) * o)
                 for g, o in zip(pages._CARD_GROUND, over))


def test_the_locator_inset_lets_the_footprint_show_through(tmp_path):
    """The inset explains WHERE the footprint is, and it sits on top of that footprint to do it. An
    opaque panel there hides exactly the stations a reader is trying to count, so the panel and its
    coastline are composited at _CARD_INSET_ALPHA and only the centre marker stays solid.

    Three properties, all read off the pixels. The inset's fill over the footprint panel is the
    declared blend rather than either of the two flat colours. Stations UNDER the inset survive as
    the blend of the station colour, which is the whole point. And the centre marker is still
    exactly copper, because the one mark that says where must not be halved.

    Teeth: the same card rendered opaque shows none of the second colour at all."""
    pages = _pages_module()
    panel_blend, dot_blend, copper = (_blend(pages, (17, 26, 51)),
                                      _blend(pages, (79, 195, 217)), (239, 114, 86))
    assert panel_blend not in ((17, 26, 51), pages._CARD_GROUND), \
        "a translucent inset cannot land on either flat colour it sits between"
    card = _grid_card(pages, tmp_path / "grid.png")
    inset = (900, 380, 1200, 630)
    seen = _count(card, inset, (panel_blend, dot_blend, copper))
    assert seen[panel_blend] > 1000, \
        f"the inset's fill must be the {panel_blend} blend, found {seen[panel_blend]} pixels"
    assert seen[dot_blend] > 100, (
        f"stations under the inset must show through as {dot_blend}; found {seen[dot_blend]}, so "
        "the inset is hiding the footprint it is explaining")
    assert seen[copper] > 100, \
        f"the centre marker stays opaque copper, found {seen[copper]} pixels"
    opaque = _count(_grid_card(pages, tmp_path / "opaque.png", alpha=1.0), inset, (dot_blend,))
    assert opaque[dot_blend] == 0, (
        "the show-through pin is vacuous unless an opaque inset fails it; the opaque card still "
        f"showed {opaque[dot_blend]} blended pixels")


def _column_overrun(pages, path, edge):
    """Every text-ink pixel on a rendered card that sits past the declared column edge.

    The scan runs BELOW the corner mark and ABOVE the signature row, so it answers for the text
    column and for nothing else; those two rows are pinned by their own tests."""
    from PIL import Image
    with Image.open(path) as im:
        px = im.convert("RGB").load()
    return [(x, y) for y in range(95, 531) for x in range(edge + 1, pages._CARD_SIZE[0])
            if px[x, y] in _TEXT_INKS]


def test_each_card_family_declares_a_column_that_clears_its_map():
    """The column widths themselves, held against literals and against the panels they sit beside.

    The pixel scan below cannot do this on its own: it derives its edge from the same constant the
    emitter wraps to, so widening the column widens the scan in lockstep and the card runs into the
    map panel with the pin still green. What has to be pinned is the AIR each column leaves.

    The survey column stops 88 px short of the footprint panel's leftmost edge, which is the gutter
    the design argues for: a 64 px title beside a bordered panel needs to read as space rather than
    as a near miss. The collection column gives up width to the enlarged map and keeps exactly
    _CARD_PANEL_AIR, the same air that panel keeps against the card's own edge."""
    pages = _pages_module()
    survey_edge = pages._CARD_MARGIN + pages._CARD_TEXT_WIDTH
    assert (pages._CARD_TEXT_WIDTH, survey_edge) == (476, 536), \
        f"the survey column is 476 px ending at x 536, got {pages._CARD_TEXT_WIDTH} to {survey_edge}"
    # 640 is the footprint panel's map origin and _CARD_PANEL_INSET its frame's outset from it.
    assert 640 - pages._CARD_PANEL_INSET - survey_edge == 88, \
        "the survey column must keep 88 px of gutter against the footprint panel"

    coll_edge = pages._CARD_MARGIN + pages._COLL_CARD_TEXT_WIDTH
    assert (pages._COLL_CARD_TEXT_WIDTH, coll_edge) == (428, 488), (
        f"the collection column is 428 px ending at x 488, got {pages._COLL_CARD_TEXT_WIDTH} "
        f"to {coll_edge}")
    _, frame = _panel_geometry(pages)
    assert frame[0] - coll_edge == pages._CARD_PANEL_AIR, (
        f"the collection column must keep {pages._CARD_PANEL_AIR} px against its panel at "
        f"{frame[0]}, it leaves {frame[0] - coll_edge}")


def test_no_card_lets_its_text_cross_its_declared_column_edge(built):
    """The column rule, measured rather than argued. A survey name is whatever the survey is called,
    and the corpus carries names long enough to run a 64 px title clean across the map panel beside
    it, so the title steps down the ladder and wraps and the fact lines wrap.

    Each family is scanned against ITS OWN declared width, because the collection card gives up
    column to its enlarged map."""
    pages = _pages_module()
    for card in sorted((built / "pages" / "og").glob("*.png")):
        over = _column_overrun(pages, card, pages._CARD_MARGIN + pages._CARD_TEXT_WIDTH)
        assert not over, f"{card.name}: text ink past the survey column edge at {over[:3]}"
    for card in sorted((built / "pages" / "og" / "collections").glob("*.png")):
        over = _column_overrun(pages, card, pages._CARD_MARGIN + pages._COLL_CARD_TEXT_WIDTH)
        assert not over, f"{card.name}: text ink past the collection column edge at {over[:3]}"


def test_the_column_scan_catches_a_title_that_crosses_the_edge(tmp_path):
    """The scan above is vacuous unless it fails on a card that breaks the rule. The corpus has no
    such card any more, by construction, so one is drawn here: the same title the emitter would set,
    put down at the top of the ladder with no wrapping, which is what the old card did."""
    pages = _pages_module()
    from PIL import Image, ImageDraw
    title = "Southwest Western Australia Array registry code 15"
    img = Image.new("RGB", pages._CARD_SIZE, pages._CARD_GROUND)
    ImageDraw.Draw(img).text((pages._CARD_MARGIN, 130), title,
                             font=pages._card_font(pages._CARD_TITLE_SIZES[0]), fill=(255, 255, 255))
    bad = tmp_path / "overrun.png"
    img.save(bad, "PNG")
    over = _column_overrun(pages, bad, pages._CARD_MARGIN + pages._CARD_TEXT_WIDTH)
    assert over, "the column scan must catch a title set at 64 px with no column rule applied"


def test_the_known_offender_fits_the_column_by_stepping_down_and_wrapping(tmp_path):
    """The card the column rule was written for. Its title at 64 px and its three-state region line
    both used to run across the footprint panel; the title now steps down the ladder to fit on one
    line, and the region wraps to a second rather than crossing the edge."""
    pages = _pages_module()
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    size, lines = pages._card_title_block(d, "Musgraves APY 2016", pages._CARD_TEXT_WIDTH, 2)
    assert lines == ["Musgraves APY 2016"], f"the title must stay on one line, got {lines}"
    assert size == 44, f"the title steps down to 44 px to hold that line, got {size}"
    region = "South Australia / Western Australia / Northern Territory - 2016 - 2018"
    wrapped, whole = pages._card_lines(d, region, pages._card_font(29), pages._CARD_TEXT_WIDTH, 2)
    assert whole and len(wrapped) == 2, \
        f"the region line must arrive whole across two lines, got {wrapped}"


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
    size, lines = pages._card_title_block(d, long_title, pages._COLL_CARD_TEXT_WIDTH, 3)
    assert " ".join(lines) == long_title, f"the title must arrive whole, got {lines}"
    assert size in pages._CARD_TITLE_SIZES, f"the title must land on the ladder, got {size}"


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
