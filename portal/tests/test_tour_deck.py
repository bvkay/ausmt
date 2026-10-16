"""The guided tour's DECK, pinned at source: 13 steps, verbatim copy, selectors, computed label.

The deck is the one part of the tour a reader actually reads, so it is pinned as SOURCE TEXT rather
than through the jsdom driver: a copy edit, a dropped step or a retargeted selector fails here with
the exact string that changed, and it fails without booting the portal.

Four properties are load bearing.

* SHAPE. Thirteen entries, in order, each carrying the selector and the copy below. The step counter
  is COMPUTED from the deck length, never typed, so a deck of a different length can never disagree
  with the label a reader sees.
* SUBJECT. The map is the whole tour. The Surveys and Collections navs are spotlighted where they
  sit, so their steps target the nav controls themselves and never the views behind them: a deck
  that pointed at #cardGrid or #collectionsGrid would be walking the reader off the map.
* RESOLUTION. The one step that names live data - the selection demo (survey name + selected count)
  - carries PLACEHOLDERS in source and is filled at enter from the corpus that is actually loaded.
  A literal survey name or count in the deck would be a claim the fixture corpus, the empty corpus
  and every future corpus can each falsify.
* THE SHEET. On the phone layout the panel and the drawer live in a bottom sheet, so every step names
  the sheet height that shows its target: a step whose target is in the sheet takes half or full, and a
  step about the map or the header takes peek, which leaves the map in view. The step sets that height
  after its enter hook (which may open the drawer) and before the spotlight is measured.
* GLYPHS. The copy takes the plain hyphen and the interpunct only; the en dash sweep
  (test_no_en_dash.py) covers the file, and the em dash is checked here so the deck cannot
  reintroduce one through a copied string.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # portal/
TOUR = ROOT / "src" / "tour.js"

# The deck as shipped: (selector, copy). Copy is verbatim; {survey} and {n} are the placeholders the
# selection demo's enter hook resolves against the loaded corpus.
DECK = [
    ("#map",
     "Every dot is an MT station. Click one to see its transfer function."),
    ("aside.filters",
     "Filter by data type; Advanced search adds find, data availability by level "
     "(time series; transfer function)."),
    ("#find",
     "Search stations, surveys or collections. Results update as you type."),
    ("#browseMode",
     "Browse by collection, country, organisation or survey. Tick a level to show or hide it."),
    ("#drawer",
     "The station drawer: response plots and provenance, in tabs."),
    ("#dp-files",
     "Files: what you can fetch for this station, by level - the transfer function served by "
     "AusMT, and time series handed off to NCI where they exist."),
    (".selbox",
     "Select stations: draw an area, or take everything that passes the filters."),
    ("#map",
     "Selecting in action: zoom to {survey}, draw a rectangle, and every station inside is "
     "selected - {n} here."),
    ("#dlLevel2",
     "Level 2 transfer functions, served by AusMT: EDI, EMTF XML and MTH5 zips for your selection."),
    ("#dlTimeSeries",
     "Time series at NCI: download lists by level, handed off through an AusMT redirect. "
     "Metadata and citations follow below."),
    ("#navSurveys",
     "Surveys: every survey with its coverage, years, periods, licence and downloads, as cards "
     "or a compact list."),
    ("#navCollections",
     "Collections: related surveys grouped, such as AusLAMP and the Australia legacy GDS, each "
     "with its combined coverage."),
    ("#map",
     "That's it: find, screen, select, download, cite. To contribute a survey of your own, follow "
     "the link in About."),
]

# The sheet height each step sets on the phone layout, in deck order.
SNAPS = ["peek", "half", "full", "full", "half", "full", "half", "peek", "full", "full", "peek", "peek", "peek"]
# The targets that live in the sheet on the phone layout; the rest are the map and the header's tabs.
IN_SHEET = ("aside.filters", "#find", "#browseMode", "#drawer", "#dp-files", ".selbox", "#dlLevel2",
            "#dlTimeSeries")
SNAP_RE = re.compile(r'\{sel:"([^"]*)",\s*text:"(?:[^"\\]|\\.)*",\s*snap:"([a-z]+)"')

# A step is {sel, text, ...}. `sel` is static for every step: the element a step spotlights is fixed,
# so it is the same whichever direction the walk arrives from, and it can be pinned here.
STEP_RE = re.compile(r'\{sel:"([^"]*)",\s*text:"((?:[^"\\]|\\.)*)"')

# The views the deck must not send the reader to. The tour is about the map; the two nav steps
# spotlight the buttons, they do not press them.
OFF_MAP_SELECTORS = ("#cardGrid", "#collectionsGrid", "#surveysview", "#collectionsview")


def _deck_source():
    src = TOUR.read_text(encoding="utf-8")
    start = src.index("const TOUR_STEPS=[")
    end = src.index("\n];", start)
    return src, src[start:end]


def _parsed_deck():
    return STEP_RE.findall(_deck_source()[1])


def test_deck_has_thirteen_steps():
    parsed = _parsed_deck()
    assert len(parsed) == 13, "the deck must carry 13 steps, parsed %d: %r" % (len(parsed), parsed)


def test_deck_selectors_and_copy_are_verbatim():
    parsed = _parsed_deck()
    assert len(parsed) == len(DECK), "deck length %d does not match the pinned deck" % len(parsed)
    for i, ((got_sel, got_text), (want_sel, want_text)) in enumerate(zip(parsed, DECK), start=1):
        assert got_sel == want_sel, "step %d selector is %r, must be %r" % (i, got_sel, want_sel)
        assert got_text == want_text, "step %d copy is\n  %r\nmust be\n  %r" % (i, got_text, want_text)


def test_deck_never_leaves_the_map():
    for i, (sel, _) in enumerate(_parsed_deck(), start=1):
        for off in OFF_MAP_SELECTORS:
            assert off not in sel, (
                "step %d targets %r, which lives on a view the tour does not visit" % (i, sel)
            )
    src = _deck_source()[0]
    for view in ('setView("surveys")', 'setView("collections")'):
        assert view not in src, "the tour must not navigate off the map, found %s" % view


def test_step_label_is_computed_from_the_deck():
    src = _deck_source()[0]
    assert '"Step "+(_tourStep+1)+" of "+TOUR_STEPS.length' in src, (
        "the step counter must be computed from the deck length, never typed"
    )
    assert not re.search(r'"[^"]*\bof 1[0-9]\b[^"]*"', src), (
        "no step-count literal may appear in a tour.js string; the label is computed"
    )


def test_resolved_copy_carries_placeholders_not_literals():
    parsed = _parsed_deck()
    texts = [t for _, t in parsed]
    assert "{survey}" in texts[7] and "{n}" in texts[7], (
        "the selection-demo step must resolve its survey name and count at enter, got %r" % texts[7]
    )
    joined = " ".join(texts)
    assert "vulcan" not in joined.lower(), "no survey name may be written into the deck copy"
    # The resolved step carries no digit at all: a number there could only be a count, and the count
    # is whatever the drawn rectangle actually took. ("Level 2" and "MTH5" elsewhere are product
    # names, not corpus facts, so the sweep is deliberately narrow.)
    assert not re.search(r"\d", texts[7]), (
        "step 8 resolves its numbers at enter; source copy carries a digit: %r" % texts[7]
    )


# Spelt as escapes so this pin never trips the source sweep it mirrors (test_no_en_dash.py).
EM_DASH = "\u2014"
EN_DASH = "\u2013"


def test_the_closing_step_names_a_route_the_header_still_carries():
    """The Contribute control left the header, so the closing step points at About, which the header
    carries and which links the contribution page from its own body. FAILS IF the step names the
    retired control again."""
    closing = _parsed_deck()[-1][1]
    assert "Contribute a survey" not in closing, "the closing step names the retired header control"
    assert "About" in closing, "the closing step points at About's contribute link"
    about = (ROOT / "about.html").read_text(encoding="utf-8")
    assert 'href="add-survey.html"' in about.split("<main>", 1)[1], "About must carry that link"


def test_deck_copy_takes_plain_hyphens_only():
    for sel, text in _parsed_deck():
        assert EM_DASH not in text, "em dash in the copy for %s: %r" % (sel, text)
        assert EN_DASH not in text, "en dash in the copy for %s: %r" % (sel, text)


def test_every_step_names_the_sheet_height_that_shows_its_target():
    """FAILS if a step stops naming its sheet height, if a target in the sheet would be left at peek
    (hidden below the handle), or if a map or header step would cover the map with the sheet."""
    steps = SNAP_RE.findall(_deck_source()[1])
    assert len(steps) == len(DECK), "every step carries snap right after its copy, parsed %r" % steps
    assert [snap for _, snap in steps] == SNAPS, [snap for _, snap in steps]
    for sel, snap in steps:
        if sel in IN_SHEET:
            assert snap in ("half", "full"), "%s is in the sheet and must not be left at peek" % sel
        else:
            assert snap == "peek", "%s is on the map or the header and takes peek, got %s" % (sel, snap)


def test_the_step_sets_its_height_after_its_enter_hook_and_before_measuring():
    """FAILS if the height is set before the enter hook (which opens the drawer and would reset it to
    half) or after the spotlight is measured, and if the snapshot the tour hands back on close stops
    carrying the sheet's height."""
    src = _deck_source()[0]
    body = src[src.index("function _tourPosition(){"):src.index("function _tourLayout(){")]
    order = [body.index(k) for k in ("step.enter()", "_tourSheetSnap(step)", "_tourScrollIntoView(", "_tourLayout()")]
    assert order == sorted(order), body
    sheet = src[src.index("function _tourSheetSnap("):]
    assert "sheetActive()" in sheet.split("\n}", 1)[0], "the height is set on the phone layout only"
    assert "sheetSnap:" in src[src.index("function _tourTakeSnapshot("):src.index("function _tourRestoreDrawer(")]
    restore = src[src.index("function _tourRestoreSnapshot("):]
    assert restore.index("_tourRestoreDrawer(s)") < restore.index("s.sheetSnap"), (
        "the sheet height is restored after the drawer, whose opening sets half")
