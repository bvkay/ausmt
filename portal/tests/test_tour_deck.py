"""The guided tour's DECK, pinned at source: 16 steps, verbatim copy, selectors, computed label.

The deck is the one part of the tour a reader actually reads, so it is pinned as SOURCE TEXT rather
than through the jsdom driver: a copy edit, a dropped step or a retargeted selector fails here with
the exact string that changed, and it fails without booting the portal.

Three properties are load bearing.

* SHAPE. Sixteen entries, in order, each carrying the selector and the copy below. The step counter
  is COMPUTED from the deck length, never typed, so a deck of a different length can never disagree
  with the label a reader sees.
* RESOLUTION. The two steps that name live data - the selection demo (survey name + selected count)
  and the collections step (collection name) - carry PLACEHOLDERS in source and are filled at enter
  from the corpus that is actually loaded. A literal survey name or count in the deck would be a
  claim the fixture corpus, the empty corpus and every future corpus can each falsify.
* GLYPHS. The copy takes the plain hyphen and the interpunct only; the en dash sweep
  (test_no_en_dash.py) covers the file, and the em dash is checked here so the deck cannot
  reintroduce one through a copied string.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # portal/
TOUR = ROOT / "src" / "tour.js"

# The deck as shipped: (selector, copy). Copy is verbatim; {survey}, {n} and {collection} are the
# placeholders the enter hooks resolve against the loaded corpus.
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
     "Surveys lists every survey. Let's look."),
    ("#cardGrid .scard",
     "Each card is a survey at a glance. Switch to Compact for a denser list."),
    ("#drawer",
     "Open a survey for its full record: abstract, stations, downloads and citation. "
     "View survey leads to its shareable page."),
    ("#collectionsGrid .scard",
     "Collections gather related surveys: {collection} here. Open one to explore its members "
     "on the map."),
    ("#navMap",
     "Map brings you back to the stations."),
    ("#map",
     "That's it: find, screen, select, download, cite. Contribute your own survey from "
     "Contribute a survey."),
]

STEP_RE = re.compile(r'\{sel:"([^"]*)",\s*text:"((?:[^"\\]|\\.)*)"')


def _deck_source():
    src = TOUR.read_text(encoding="utf-8")
    start = src.index("const TOUR_STEPS=[")
    end = src.index("\n];", start)
    return src, src[start:end]


def _parsed_deck():
    return STEP_RE.findall(_deck_source()[1])


def test_deck_has_sixteen_steps():
    parsed = _parsed_deck()
    assert len(parsed) == 16, "the deck must carry 16 steps, parsed %d: %r" % (len(parsed), parsed)


def test_deck_selectors_and_copy_are_verbatim():
    parsed = _parsed_deck()
    assert len(parsed) == len(DECK), "deck length %d does not match the pinned deck" % len(parsed)
    for i, ((got_sel, got_text), (want_sel, want_text)) in enumerate(zip(parsed, DECK), start=1):
        assert got_sel == want_sel, "step %d selector is %r, must be %r" % (i, got_sel, want_sel)
        assert got_text == want_text, "step %d copy is\n  %r\nmust be\n  %r" % (i, got_text, want_text)


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
    assert "{collection}" in texts[13], (
        "the collections step must resolve its collection name at enter, got %r" % texts[13]
    )
    joined = " ".join(texts)
    assert "vulcan" not in joined.lower(), "no survey name may be written into the deck copy"
    # The two resolved steps carry no digit at all: a number there could only be a count, and the
    # count is whatever the drawn rectangle actually took. ("Level 2" and "MTH5" elsewhere are
    # product names, not corpus facts, so the sweep is deliberately narrow.)
    for k in (7, 13):
        assert not re.search(r"\d", texts[k]), (
            "step %d resolves its numbers at enter; source copy carries a digit: %r" % (k + 1, texts[k])
        )


# Spelt as escapes so this pin never trips the source sweep it mirrors (test_no_en_dash.py).
EM_DASH = "\u2014"
EN_DASH = "\u2013"


def test_deck_copy_takes_plain_hyphens_only():
    for sel, text in _parsed_deck():
        assert EM_DASH not in text, "em dash in the copy for %s: %r" % (sel, text)
        assert EN_DASH not in text, "en dash in the copy for %s: %r" % (sel, text)
