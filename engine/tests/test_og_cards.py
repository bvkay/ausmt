"""The link-preview cards: what every card family carries, and what the collection card carries.

A card is the only thing most people ever see of a page. It is shared into Slack, Teams and X, and
it is resampled to roughly a third of its width on the way, so what it says has to survive at that
size. These are the properties pinned here, all measured off the rendered PNG rather than read back
out of the drawing code, so a constant that still looks right cannot hide a card that is wrong.

THE ADDRESS LINE. ausmt.auscope.org.au sits on the card's text margin on a line of its own, in the
brand's coral accent and in Inter Bold, the face the hand-made root card's artwork uses, so the card
families sign themselves in one face and one colour.

THE AUSCOPE LOCKUP. AuScope's icon with its wordmark, white, sits last in the left column at a
declared height above the card's bottom edge. It is never taller than the AusMT mark above it, so
the acknowledgement cannot outweigh the resource identity it acknowledges.

THE AUSMT LOCKUP. Survey and collection cards open their left column with the AusMT mark and the
word beside it, on the same text margin the title sits on, at the proportions the brand file
declares. The ROOT card carries no mark: that card's artwork is the mark, and a second copy of it
would read as a duplicate (pinned in portal/tests/test_social_card.py).

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

# The address's own band, and the AuScope lockup's band under it. Each is read across the card's
# left column only, out to the edge the family declares, so the map panel beside them can never
# answer for either.
_ADDRESS_ROWS = (452, 534)
_LOCKUP_ROWS = (535, 630)
# The top-left corner, wide enough to catch a lockup that drifted off the margin and short enough to
# stop above the kind label under it. Nothing but the AusMT lockup may put ink here.
_CORNER_REGION = (0, 0, 400, 110)
# The card's three text inks. A pixel of any of them past the declared column edge is type that has
# crossed into the map panel, which is the failure the column rule exists to prevent.
_TEXT_INKS = ((255, 255, 255), (143, 163, 176), (201, 212, 232), (150, 165, 195))
# The block's fact-line ink, so a pin can render the line it is looking for in the ink the card sets
# it in.
_MUTED_INK = (143, 163, 176)


def _pages_module():
    sys.path.insert(0, str(REPO / "extract"))
    import _pages
    return _pages


def _survey(tmp_path, slug, name, lat, extra="", region="South Australia"):
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\nregion: {region}\n"
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
    """One corpus whose two surveys are members of one collection, built once with the cards on.

    The two surveys carry the two text lengths the column rule has to hold, because a scan over
    cards that all fit anyway would stay green with the rule deleted. card-a is the corpus's worst
    case, shaped on the survey the rule was written for: a name that overflows the 476 px column at
    the top of the size ladder and still overflows it at the bottom, so the title has to step down
    to the smallest size AND wrap; and a region naming three states with a year range, which
    overflows the same column at 29 px, so the fact line has to wrap under it. card-b stays short
    enough that neither happens, so the scan also covers a card the rule leaves alone."""
    tmp = tmp_path_factory.mktemp("ogcards")
    coll = ("collection:\n  id: cardcoll\n  title: Card Collection\n  type: programme\n"
            "  status: active\n")
    surveys = _survey(tmp, "card-a", "AusLAMP Musgraves APY Lands Deployment 2016", "-30.5",
                      coll + "dates: {start: 2016, end: 2018}\n",
                      region="South Australia / Western Australia / Northern Territory")
    _survey(tmp, "card-b", "Card B", "-24.5", coll)
    out = tmp / "out"
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(out), "--bundle-edi",
                            "--no-validate", "--products", str(out / "products"),
                            "--sitemap-base", BASE])
    assert rc == 0, f"build rc={rc}"
    return out


def _brand():
    """The brand's declared truth, read here rather than restated, so a pin cannot agree with a
    card that has drifted from the file both are supposed to follow."""
    return json.loads((REPO.parent / "contract" / "brand.json").read_text(encoding="utf-8"))


def _brand_stop(name):
    """One palette stop's (r, g, b), from the brand file."""
    hexes = {stop["name"]: stop["hex"] for stop in _brand()["palette"]["stops"]}
    h = hexes[name].lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _ink(path, region):
    """(card size, every non-ground pixel in `region` as (x, y, colour)).

    Read off the rendered file rather than computed from the drawing code, so a change that moves a
    band fails here even if the constants behind it still look right."""
    from PIL import Image
    pages = _pages_module()
    with Image.open(path) as im:
        img = im.convert("RGB")
    px = img.load()
    x0, y0, x1, y1 = region
    return img.size, [(x, y, px[x, y])
                      for y in range(y0, min(y1, img.size[1]))
                      for x in range(x0, min(x1, img.size[0]))
                      if px[x, y] != pages._CARD_GROUND]


def _box(pts):
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def _line_stamp(pages, text, font, ink, tracking=0):
    """(the glyphs `text` makes on the card's ground, their offset from the draw origin).

    A PNG holds no strings, so a pin that a card SETS a given line has to look for the glyphs that
    line makes. The stamp is drawn with the emitter's own face, ink and ground at an integer origin,
    which is how the card draws it, so a match is exact rather than approximate."""
    from PIL import Image, ImageDraw
    ref = Image.new("RGB", pages._CARD_SIZE, pages._CARD_GROUND)
    rd = ImageDraw.Draw(ref)
    if tracking:
        pages._card_tracked(rd, (pages._CARD_MARGIN, 100), text, font, ink, tracking)
    else:
        rd.text((pages._CARD_MARGIN, 100), text, font=font, fill=ink)
    ground = Image.new("RGB", pages._CARD_SIZE, pages._CARD_GROUND)
    from PIL import ImageChops
    bbox = ImageChops.difference(ref, ground).getbbox()
    assert bbox, f"the stamp for {text!r} carries no ink"
    return ref.crop(bbox), (bbox[0], bbox[1] - 100, bbox[2] - bbox[0], bbox[3] - bbox[1])


def _sets_line(card_img, stamp, offset, rows):
    """The y the card sets that line's glyphs on, or None. Scanned over `rows` because the line
    above it may have wrapped and pushed it down."""
    dx, dy, w, h = offset
    want = stamp.tobytes()
    for y in range(rows[0], rows[1]):
        if card_img.crop((dx, y + dy, dx + w, y + dy + h)).tobytes() == want:
            return y
    return None


def _line_h():
    """The address's own line height, from the face the cards actually set the address in."""
    pages = _pages_module()
    return sum(pages._card_address_font(pages._CARD_WORDMARK_SIZE).getmetrics())


def _assert_address_line(path, edge):
    """The address is a line of its own: coral, on the text margin, inside its declared line box,
    and with no other ink sharing its band."""
    pages = _pages_module()
    size, ink = _ink(path, (0, _ADDRESS_ROWS[0], edge, _ADDRESS_ROWS[1]))
    assert size == (1200, 630), f"{path}: a link-preview card is 1200x630, got {size}"
    assert ink, f"{path}: no address ink in the address band"
    coral = _brand_stop("coral")
    assert any(c == coral for _x, _y, c in ink), \
        f"{path}: the address is set in the brand's coral {coral}, none of it is on the card"
    box = _box(ink)
    # The first glyph's own left side bearing is the only slack: the line starts on the margin.
    assert pages._CARD_MARGIN <= box[0] <= pages._CARD_MARGIN + 2, \
        f"{path}: the address starts on the text margin, its ink starts at x={box[0]}"
    assert box[1] >= pages._CARD_WORDMARK_Y, \
        f"{path}: ink above the address's own line box at y={box[1]}"
    assert box[3] <= pages._CARD_WORDMARK_Y + _line_h(), (
        f"{path}: the address must sit inside its {_line_h()} px line from "
        f"{pages._CARD_WORDMARK_Y}, its ink reaches y={box[3]}")
    assert not [p for p in ink if p[2] in _TEXT_INKS], \
        f"{path}: the block above must not reach into the address band"


def _lockup_slot(pages):
    """The AuScope lockup's declared box, rebuilt from the shipped asset's own aspect."""
    from PIL import Image
    with Image.open(pages._CARD_LOCKUP) as im:
        w = round(pages._CARD_LOCKUP_SIZE * im.width / im.height)
    top = pages._CARD_SIZE[1] - pages._CARD_LOCKUP_BASE - pages._CARD_LOCKUP_SIZE
    return (pages._CARD_MARGIN, top, pages._CARD_MARGIN + w - 1,
            top + pages._CARD_LOCKUP_SIZE - 1)


def _assert_auscope_lockup(path, edge):
    """The lockup is white, sits in its declared bottom-left box, and is never taller than the
    AusMT mark that opens the column."""
    pages = _pages_module()
    assert pages._CARD_LOCKUP_SIZE <= pages._CARD_CORNER_SIZE, (
        f"the AuScope lockup ({pages._CARD_LOCKUP_SIZE} px) must not stand taller than the AusMT "
        f"mark ({pages._CARD_CORNER_SIZE} px)")
    _size, ink = _ink(path, (0, _LOCKUP_ROWS[0], edge, _LOCKUP_ROWS[1]))
    assert ink, f"{path}: no AuScope lockup ink in its declared band"
    slot = _lockup_slot(pages)
    box = _box(ink)
    assert box[0] == slot[0] and box[1] >= slot[1] and box[2] <= slot[2] and box[3] <= slot[3], \
        f"{path}: the lockup's ink {box} must fill its declared slot {slot}"
    assert any(min(c) >= 240 for _x, _y, c in ink), \
        f"{path}: the lockup is drawn white, nothing in its band is"
    bleed = [p for p in ink if p[0] < pages._CARD_MARGIN]
    assert not bleed, \
        f"{path}: the lockup starts on the text margin, found ink at {bleed[:3]}"


def test_the_address_is_set_in_the_pinned_bold_face_at_the_declared_size():
    """The signature row's face and size, held as the numbers they are.

    The address is the one string all three card families carry, and the root card's hand-made
    artwork sets it in Inter Bold; the generated cards read a pinned copy of that same face from
    beside the emitter so the three rows are one row rather than three that agree on the spelling.
    The mark's height follows from the face, so pinning the face pins the row's whole geometry.

    FAILS IF the address falls back to the bundled bitmap face, or the size drifts: either would
    resize the mark beside it and break the row on every card in the corpus at once."""
    pages = _pages_module()
    assert pages._CARD_WORDMARK_SIZE == 34, \
        f"the address is set at 34 px, got {pages._CARD_WORDMARK_SIZE}"
    assert pages._CARD_ADDRESS_FACE.name == "_inter_bold.ttf", \
        f"the address face is the pinned Inter Bold beside the emitter, got {pages._CARD_ADDRESS_FACE}"
    font = pages._card_address_font(pages._CARD_WORDMARK_SIZE)
    assert Path(font.path) == pages._CARD_ADDRESS_FACE, \
        f"the face must be loaded from {pages._CARD_ADDRESS_FACE}, got {font.path}"
    assert sum(font.getmetrics()) == 42, \
        f"the line stands on this face's 42 px line, got {sum(font.getmetrics())}"


def test_the_engine_carries_the_auscope_lockup_the_portal_serves():
    """The engine image ships no portal tree, so the cards draw the AuScope lockup from a copy
    beside the emitter. The pin compares PICTURES: the portal file is cropped the same way here and
    the two RGBA arrays must agree. A byte pin on a re-encoded crop compares one Pillow build's
    encoder against another's rather than comparing the artwork.

    FAILS IF the shipped crop stops being the AuScope half of the lockup the portal serves, or if an
    asset no card draws still ships beside the emitter."""
    pages = _pages_module()
    engine_copy = REPO / "extract" / "_auscope_lockup.png"
    portal_copy = REPO.parent / "portal" / "vendor" / "auscope-ncris-white.png"
    assert engine_copy.is_file(), "the emitter must ship the lockup it draws"
    assert not (REPO / "extract" / "_auscope_mark.png").exists(), \
        "an asset no card draws must not ship beside the emitter"
    if not portal_copy.is_file():
        pytest.skip("engine image build: portal tree not shipped "
                    "(designed topology; the vendored lockup is pinned from the checkout workflows)")
    from PIL import Image
    with Image.open(portal_copy) as src:
        full = src.convert("RGBA")
    assert full.size == (1919, 325), \
        f"the portal lockup moved off the size the crop was measured on, now {full.size}"
    cut = full.crop((0, 0, pages._AUSCOPE_CROP_X, full.height))
    want = cut.crop(cut.getbbox())
    with Image.open(engine_copy) as im:
        got = im.convert("RGBA")
    assert got.size == want.size, \
        f"the shipped crop is {got.size}, the portal file's own crop is {want.size}"
    assert got.tobytes() == want.tobytes(), \
        "the shipped lockup must be the AuScope crop of the portal's lockup, pixel for pixel"


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
        pytest.skip("engine image build: portal tree not shipped "
                    "(designed topology; the vendored mark is pinned from the checkout workflows)")
    assert engine_copy.read_bytes() == portal_copy.read_bytes(), \
        f"{engine_name} and {portal_rel} must be one asset, byte for byte"


def test_every_card_names_the_kind_of_thing_it_previews(built):
    """The card says what the reader has landed on before the title does: a tracked cap label
    between the lockup and the title, in its own muted ink.

    The label is read as GLYPHS, drawn here with the emitter's own tracked setter, so a card that
    labelled a collection SURVEY fails. The pin is checked to discriminate on the same line: the two
    words do not make the same stamp. The band between the lockup and the label is held empty, so a
    label that drifted up into the lockup's clear space fails here rather than looking tidy."""
    pages = _pages_module()
    from PIL import Image
    font = pages._card_address_font(pages._CARD_KIND_SIZE)
    stamps = {word: _line_stamp(pages, word, font, pages._CARD_KIND_INK,
                                pages._CARD_KIND_TRACKING)
              for word in ("SURVEY", "COLLECTION")}
    assert stamps["SURVEY"][0].tobytes() != stamps["COLLECTION"][0].tobytes(), \
        "the label pin is vacuous unless the two words make different glyphs"
    families = ((sorted((built / "pages" / "og").glob("*.png")), "SURVEY"),
                (sorted((built / "pages" / "og" / "collections").glob("*.png")), "COLLECTION"))
    for cards, word in families:
        assert cards, f"the build must render the cards that carry {word}"
        stamp, offset = stamps[word]
        for card in cards:
            with Image.open(card) as im:
                img = im.convert("RGB")
            at = _sets_line(img, stamp, offset, (pages._CARD_KIND_Y, pages._CARD_KIND_Y + 1))
            assert at == pages._CARD_KIND_Y, \
                f"{card.name}: the label {word} must be set on the card's own label line"
            _size, quiet = _ink(card, (0, pages._CARD_CORNER_Y + pages._CARD_CORNER_SIZE + 1,
                                       400, pages._CARD_KIND_Y))
            assert not quiet, \
                f"{card.name}: the lockup's clear space carries ink at {quiet[:3]}"


def test_the_survey_cards_identity_line_counts_stations_and_names_the_type(built):
    """Level 2 of the block is a count of stations and the instrument type, joined by an
    interpunct, which is the form a reader can scan at preview size.

    Held on the glyphs the card sets rather than on the string the emitter passed, and the count
    comes from the fixture corpus's own EDI files rather than from a number written here."""
    pages = _pages_module()
    from PIL import Image
    stamp, offset = _line_stamp(pages, f"{len(SAMPLE_EDIS)} stations", pages._card_font(29),
                                _MUTED_INK)
    old_stamp, old_offset = _line_stamp(pages, f"{len(SAMPLE_EDIS)}-station",
                                        pages._card_font(29), _MUTED_INK)
    assert stamp.tobytes() != old_stamp.tobytes(), \
        "the pin is vacuous unless the two forms make different glyphs"
    cards = sorted((built / "pages" / "og").glob("*.png"))
    assert cards, "the build must render a card per survey"
    for card in cards:
        with Image.open(card) as im:
            img = im.convert("RGB")
        rows = (pages._CARD_TITLE_Y, pages._CARD_BLOCK_CEILING)
        assert _sets_line(img, stamp, offset, rows) is not None, \
            f"{card.name}: the identity line must count stations"
        assert _sets_line(img, old_stamp, old_offset, rows) is None, \
            f"{card.name}: the identity line must not compound the count into the type"


def test_no_card_sets_the_extent_line(built):
    """The card lost its extent line: a footprint's kilometres are a number the survey PAGE carries,
    and on a card they crowd out the period band a reader can actually use.

    FAILS IF any card sets that line again, and the scan is checked to have teeth on the same line
    against a card drawn with it."""
    pages = _pages_module()
    import inspect
    assert "dims_line" not in inspect.signature(pages._og_card).parameters, \
        "the card takes no extent line any more"
    from PIL import Image, ImageDraw
    stamp, offset = _line_stamp(pages, "about", pages._card_font(26), (201, 212, 232))
    rows = (pages._CARD_TITLE_Y, pages._CARD_BLOCK_CEILING)
    for card in sorted((built / "pages" / "og").rglob("*.png")):
        with Image.open(card) as im:
            img = im.convert("RGB")
        assert _sets_line(img, stamp, offset, rows) is None, \
            f"{card.name}: the extent line is set on this card"
    bad = Image.new("RGB", pages._CARD_SIZE, pages._CARD_GROUND)
    ImageDraw.Draw(bad).text((pages._CARD_MARGIN, 300), "about 118 x 22 km",
                             font=pages._card_font(26), fill=(201, 212, 232))
    assert _sets_line(bad, stamp, offset, rows) == 300, \
        "the extent scan is vacuous unless a card that sets that line fails it"


def test_the_block_rebalances_when_the_survey_discloses_no_years_and_no_periods(tmp_path):
    """Absent means absent: a survey with no years and no period band renders a SHORTER block rather
    than one with holes in it. Measured on the two cards' own ink, so a blank line reserved for an
    undisclosed value fails here."""
    pages = _pages_module()
    pts = [(133.0, -25.0, "mt"), (140.0, -30.0, "mt")]
    full = tmp_path / "full.png"
    bare = tmp_path / "bare.png"
    pages._og_card(full, kind="SURVEY", title="Vulcan", subtitle="2 stations · BBMT",
                   region_year="South Australia · 2016 - 2018", period_line="0.005 - 6310 s",
                   points=pts)
    pages._og_card(bare, kind="SURVEY", title="Vulcan", subtitle="2 stations · BBMT",
                   region_year="", period_line="", points=pts)
    band = (0, pages._CARD_TITLE_Y, pages._CARD_MARGIN + pages._CARD_TEXT_WIDTH,
            pages._CARD_BLOCK_CEILING)
    _s, full_ink = _ink(full, band)
    _s, bare_ink = _ink(bare, band)
    assert _box(bare_ink)[3] < _box(full_ink)[3], \
        "a survey that discloses less must render a shorter block"
    rows = sorted({y for _x, y, _c in bare_ink})
    runs = [r for r in range(1, len(rows)) if rows[r] - rows[r - 1] > 1]
    assert len(runs) == 1, (
        "the shorter block is the title and one fact line with nothing between them, "
        f"found {len(runs) + 1} bands of ink")


def test_the_block_never_reaches_into_the_address_or_the_lockup(built, tmp_path):
    """The two lines that close the column keep their own bands whatever the block above them does.

    FAILS IF a long title plus a wrapped fact line pushes the block down over the address or the
    lockup; the check has teeth on the same line against a card whose block is drawn past the
    ceiling."""
    pages = _pages_module()
    from PIL import Image, ImageDraw
    for card, edge in ([(c, pages._CARD_MARGIN + pages._CARD_TEXT_WIDTH)
                        for c in sorted((built / "pages" / "og").glob("*.png"))]
                       + [(c, pages._CARD_MARGIN + pages._COLL_CARD_TEXT_WIDTH)
                          for c in sorted((built / "pages" / "og" / "collections").glob("*.png"))]):
        slot = _lockup_slot(pages)
        for rows in (_ADDRESS_ROWS, _LOCKUP_ROWS):
            _size, ink = _ink(card, (0, rows[0], edge, rows[1]))
            # The lockup's own slot is the one thing allowed to put white in the lower band.
            crossed = [p for p in ink if p[2] in _TEXT_INKS
                       and not (slot[0] <= p[0] <= slot[2] and slot[1] <= p[1] <= slot[3])]
            assert not crossed, \
                f"{card.name}: block ink in the band at {rows}, at {crossed[:3]}"
    bad = Image.new("RGB", pages._CARD_SIZE, pages._CARD_GROUND)
    ImageDraw.Draw(bad).text((pages._CARD_MARGIN, _ADDRESS_ROWS[0] + 4), "0.005 - 6310 s",
                             font=pages._card_font(26), fill=(201, 212, 232))
    bad.save(tmp_path / "crossed.png", "PNG")
    _size, ink = _ink(tmp_path / "crossed.png", (0, _ADDRESS_ROWS[0], 536, _ADDRESS_ROWS[1]))
    assert [p for p in ink if p[2] in _TEXT_INKS], \
        "the band scan is vacuous unless a block drawn into it fails"


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

    Three things are held. The slot is the size and place it was settled at, held against literals
    rather than against the constants that draw it, because a slot rebuilt from _CARD_CORNER_SIZE
    grows with that constant and so would accept a mark of any size. The mark's ink stays inside
    that slot, so it cannot grow into the title. And the slot's LEFT edge has teeth: the strip
    between the card edge and the text margin, across the mark's own rows, must be empty, so a mark
    drawn off the margin fails here rather than quietly sitting in the bleed."""
    pages = _pages_module()
    assert (pages._CARD_CORNER_SIZE, pages._CARD_CORNER_Y) == (52, 44), (
        "the mark is drawn 52 px high at y 44, got "
        f"{(pages._CARD_CORNER_SIZE, pages._CARD_CORNER_Y)}")
    slot = (pages._CARD_MARGIN, pages._CARD_CORNER_Y,
            pages._CARD_MARGIN + pages._CARD_CORNER_SIZE, pages._CARD_CORNER_Y
            + pages._CARD_CORNER_SIZE)
    assert slot == (60, 44, 112, 96), f"the mark's slot moved off its declared box, now {slot}"
    cards = sorted((built / "pages" / "og").rglob("*.png"))
    assert cards, "the build must render cards"
    for card in cards:
        _size, ink = _ink(card, _CORNER_REGION)
        assert ink, f"{card.name}: no lockup ink in the card's top-left corner"
        mark = _box([p for p in ink if p[0] <= slot[2]])
        assert (mark[0] >= slot[0] and mark[1] >= slot[1]
                and mark[2] <= slot[2] and mark[3] <= slot[3]), \
            f"{card.name}: the mark's ink {mark} must stay inside its slot {slot}"
        word = [p for p in ink if p[0] > slot[2]]
        assert word, f"{card.name}: the mark carries no word beside it"
        wbox = _box(word)
        assert wbox[1] >= slot[1] and wbox[3] <= slot[3], (
            f"{card.name}: the word sits inside the mark's own rows {slot[1]} to {slot[3]}, "
            f"its ink runs {wbox[1]} to {wbox[3]}")
        bleed = [p for p in ink if p[0] < pages._CARD_MARGIN]
        assert not bleed, \
            f"{card.name}: the lockup must start on the text margin, found ink at {bleed[:3]}"


def test_the_ausmt_wordmark_is_set_at_the_brand_files_own_proportions(built):
    """The word beside the mark is sized, spaced and inked from the brand file, scaled by the mark's
    own height. Every number here is READ from that file rather than restated, so a card that drifted
    from it fails even though both sides still look self-consistent.

    FAILS IF the word's size, its gap from the mark, its ink or its centring on the mark change
    without the brand file changing with them."""
    pages = _pages_module()
    brand = _brand()
    prop = brand["proportions"]
    size = round(prop["wordmark_font_size"] * pages._CARD_CORNER_SIZE)
    gap = round(prop["gap_mark_to_wordmark"] * pages._CARD_CORNER_SIZE)
    hexed = brand["palette"]["wordmark_ink"]["on_dark"].lstrip("#")
    want_ink = tuple(int(hexed[i:i + 2], 16) for i in (0, 2, 4))
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    glyphs = d.textbbox((0, 0), brand["brand"], font=pages._card_address_font(size))
    left = pages._CARD_MARGIN + pages._CARD_CORNER_SIZE + gap + glyphs[0]
    mark_mid = pages._CARD_CORNER_Y + pages._CARD_CORNER_SIZE / 2
    edge = pages._CARD_MARGIN + pages._CARD_CORNER_SIZE
    for card in sorted((built / "pages" / "og").rglob("*.png")):
        _size, ink = _ink(card, (edge + 1, 0, _CORNER_REGION[2], _CORNER_REGION[3]))
        assert ink, f"{card.name}: no word beside the mark"
        box = _box(ink)
        assert abs(box[0] - left) <= 1, (
            f"{card.name}: the word starts {gap} px after the mark, at x {left}; its ink starts "
            f"at {box[0]}")
        assert abs((box[3] - box[1] + 1) - (glyphs[3] - glyphs[1])) <= 1, (
            f"{card.name}: the word is set at {size} px, whose ink stands "
            f"{glyphs[3] - glyphs[1]} px; this one stands {box[3] - box[1] + 1}")
        assert abs((box[1] + box[3]) / 2 - mark_mid) <= 2, \
            f"{card.name}: the word centres on the mark at {mark_mid}, it sits at {(box[1] + box[3]) / 2}"
        assert any(c == want_ink for _x, _y, c in ink), \
            f"{card.name}: the word is inked {want_ink}, no pixel of it is"


def test_every_survey_card_signs_itself_with_the_address_and_the_auscope_lockup(built):
    cards = sorted((built / "pages" / "og").glob("*.png"))
    assert cards, "the build must render a card per survey"
    pages = _pages_module()
    edge = pages._CARD_MARGIN + pages._CARD_TEXT_WIDTH
    for card in cards:
        _assert_address_line(card, edge)
        _assert_auscope_lockup(card, edge)


def test_every_collection_card_signs_itself_the_same_way(built):
    cards = sorted((built / "pages" / "og" / "collections").glob("*.png"))
    assert cards, "the build must render a card per collection"
    pages = _pages_module()
    edge = pages._CARD_MARGIN + pages._COLL_CARD_TEXT_WIDTH
    for card in cards:
        _assert_address_line(card, edge)
        _assert_auscope_lockup(card, edge)


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
    _CARD_INSET_ALPHA. Two nearer-looking probes do not work. Counting card ground does not
    separate the families, because a translucent inset punches no ground-coloured hole in a survey
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
        pages._og_card(path, kind="SURVEY", title="Grid", subtitle="400 stations",
                       region_year="Test", period_line="period", points=pts)
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
    return [(x, y) for y in range(pages._CARD_KIND_Y, pages._CARD_BLOCK_CEILING)
            for x in range(edge + 1, pages._CARD_SIZE[0])
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
    ImageDraw.Draw(img).text((pages._CARD_MARGIN, pages._CARD_TITLE_Y), title,
                             font=pages._card_font(pages._CARD_TITLE_SIZES[0]), fill=(255, 255, 255))
    bad = tmp_path / "overrun.png"
    img.save(bad, "PNG")
    over = _column_overrun(pages, bad, pages._CARD_MARGIN + pages._CARD_TEXT_WIDTH)
    assert over, "the column scan must catch a title set at the top of the ladder with no column rule"


def test_the_known_offender_fits_the_column_by_stepping_down_and_wrapping(tmp_path):
    """The card the column rule was written for. Its title at 64 px and its three-state region line
    both once ran across the footprint panel; the title now steps down the ladder to fit on one
    line, and the region wraps to a second rather than crossing the edge."""
    pages = _pages_module()
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    assert pages._CARD_TITLE_SIZES == (70, 57, 48, 40), \
        f"the title ladder's declared steps moved, now {pages._CARD_TITLE_SIZES}"
    size, lines = pages._card_title_block(d, "Musgraves APY 2016", pages._CARD_TEXT_WIDTH, 2)
    assert lines == ["Musgraves APY 2016"], f"the title must stay on one line, got {lines}"
    assert size == 48, f"the title steps down to 48 px to hold that line, got {size}"
    region = "South Australia / Western Australia / Northern Territory - 2016 - 2018"
    wrapped, whole = pages._card_lines(d, region, pages._card_font(29), pages._CARD_TEXT_WIDTH, 2)
    assert whole and len(wrapped) == 2, \
        f"the region line must arrive whole across two lines, got {wrapped}"


def test_a_page_only_ever_advertises_a_card_that_was_written(built):
    """FAILS IF a page names a card URL with no file behind it. The page once derived the URL from
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
    wrote = pages._og_collection_card(card, kind="COLLECTION", title="Empty",
                                      facts_line="0 surveys", taxonomy_line="",
                                      member_labels=["A"], member_points={"A": []})
    assert wrote is False and not card.exists(), "no positions means no card at all"


def test_the_collection_card_keeps_the_whole_title_by_stepping_the_type_down(tmp_path):
    """A title that is silently cut is a title the card gets wrong. The longest name in the corpus
    is a programme's full expansion, and it has to arrive whole."""
    pages = _pages_module()
    long_title = "Australian Lithospheric Architecture Magnetotelluric Project"
    card = tmp_path / "long.png"
    assert pages._og_collection_card(card, kind="COLLECTION", title=long_title,
                                     facts_line="14 surveys", taxonomy_line="programme",
                                     member_labels=["A"],
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
