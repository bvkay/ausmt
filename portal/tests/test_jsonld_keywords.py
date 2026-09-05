"""One keyword vocabulary, stated in four places and held equal here.

The homepage catalogue, the two hub catalogues and every survey Dataset all carry JSON-LD keywords.
The engine builds three of those from _KEYWORDS_BASE in engine/extract/_pages.py; the portal's
homepage is a hand-edited document with no template step, so its copy is held equal to the engine's
by this module, the same bargain test_footer_regions.py and test_header_geometry_parity.py already
make for the chrome. portal-ci triggers on engine/extract/_pages.py for exactly that reason, so an
edit to either half fires the pin that holds them together.

WHAT A KEYWORD IS FOR, STATED PLAINLY: it describes a document to something reading its markup.
Web search RANKING DOES NOT USE IT, and has not for many years; a catalogue, a federation harvester
or a schema-aware consumer does. Nothing here is written expecting a ranking effect, and no claim of
one belongs in the markup or in this module.

The per-survey list is the base vocabulary plus terms the survey's OWN record supports: the band
classes it actually serves, its region, its organisation and its collection. A survey may never be
described by a word its record does not carry, which is the property the last test holds.

Fails if: the homepage's array drifts from the engine's base list, the two hubs stop carrying a
DataCatalog or stop carrying the base list, a list contains a duplicate, or a survey Dataset carries
a term its record does not support.
"""
import json
import re
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent
ROOT = PORTAL.parent
PAGES = ROOT / "engine" / "extract" / "_pages.py"


def engine_vocabulary():
    """_KEYWORDS_BASE and the two builders, read from the emitter's source.

    _pages.py cannot simply be imported (it sibling-imports _au_outline and _stationcheck, which
    need the engine's own path set up), so the vocabulary block is executed on its own. It is
    stdlib-free by construction, which is what makes that safe, and this test would fail loudly if
    it ever stopped being."""
    src = PAGES.read_text(encoding="utf-8")
    start = src.index("_KEYWORDS_BASE = (")
    end = src.index("def _breadcrumb")
    namespace: dict = {}
    exec(compile(src[start:end], str(PAGES), "exec"), namespace)   # noqa: S102
    return namespace


VOCAB = engine_vocabulary()
BASE = VOCAB["_keywords"]()


def homepage_keywords():
    html = (PORTAL / "index.html").read_text(encoding="utf-8")
    blocks = re.findall(r'(?s)<script type="application/ld\+json">(.*?)</script>', html)
    assert blocks, "index.html carries no JSON-LD at all"
    catalogue = [json.loads(b) for b in blocks]
    catalogue = [n for n in catalogue if n.get("@type") == "DataCatalog"]
    assert len(catalogue) == 1, f"expected exactly one DataCatalog node, found {len(catalogue)}"
    return catalogue[0]["keywords"]


def test_the_homepage_states_the_engines_vocabulary():
    got = homepage_keywords()
    assert got == BASE, (
        "index.html's keywords must equal engine/extract/_pages.py's _KEYWORDS_BASE, term for term "
        f"and in order.\n  homepage: {got}\n  engine:   {BASE}"
    )


def test_the_vocabulary_carries_the_searched_phrases():
    """The phrases the catalogue is looked for by. FAILS if one is dropped."""
    required = [
        "magnetotelluric", "magnetotelluric survey", "magnetotelluric surveys",
        "Australian magnetotelluric data", "Australia MT", "MT data", "MT transfer functions",
        "AusMT", "electromagnetic geophysics", "AusLAMP", "geomagnetic depth sounding", "GDS",
    ]
    missing = [term for term in required if term not in BASE]
    assert not missing, f"the vocabulary has lost {missing}"


def test_the_terms_the_markup_already_carried_are_kept():
    """A sweep may add words; it may not cost a surface one it had."""
    for term in ("magnetotellurics", "MT", "AusLAMP", "transfer functions", "geophysics", "Australia"):
        assert term in BASE, f"{term!r} was in the markup before and must stay in it"


def test_no_list_repeats_a_term():
    for label, terms in (("the base list", BASE),
                         ("a survey list", VOCAB["_survey_keywords"](
                             {"LPMT", "BBMT"}, "Australia", "AusMT", {"title": "AusLAMP"}))):
        assert len(terms) == len(set(terms)), f"{label} repeats a term: {terms}"


def test_the_case_rule_holds():
    """Lower case except a proper noun or an initialism, which is what a reader types."""
    proper = {"Australian magnetotelluric data", "Australia MT", "MT data", "MT transfer functions",
              "AusMT", "AusLAMP", "GDS", "MT", "Australia"}
    for term in BASE:
        if term in proper:
            continue
        assert term == term.lower(), f"{term!r} is not a proper noun and must be lower case"


def test_a_survey_is_described_only_by_its_own_record():
    """The base vocabulary plus the survey's own facts, and nothing else."""
    survey = VOCAB["_survey_keywords"]({"LPMT", "GDS"}, "South Australia", "Geoscience Australia",
                                       {"id": "auslamp", "title": "AusLAMP"})
    for term in BASE:
        assert term in survey, f"a survey list must contain the whole base list; {term!r} is missing"
    extra = [term for term in survey if term not in BASE]
    assert set(extra) == {"long-period magnetotelluric", "South Australia", "Geoscience Australia"}, (
        "a survey's extra terms are its own band classes, region, organisation and collection, and "
        f"nothing else (geomagnetic depth sounding and AusLAMP are already in the base list): {extra}"
    )
    assert "broadband magnetotelluric" not in survey, (
        "a survey that serves no broadband stations may not be described as broadband"
    )
    assert "audio-magnetotelluric" not in survey, (
        "a survey that serves no audio-band stations may not be described as audio-magnetotelluric"
    )


def test_a_survey_with_no_facts_of_its_own_gets_the_base_list_exactly():
    assert VOCAB["_survey_keywords"](set(), "", "", None) == BASE


def test_the_band_classes_are_spelt_out():
    """The served type codes, in the words a reader searches for."""
    assert VOCAB["_KEYWORD_FOR_TYPE"] == {
        "LPMT": "long-period magnetotelluric",
        "BBMT": "broadband magnetotelluric",
        "AMT": "audio-magnetotelluric",
        "GDS": "geomagnetic depth sounding",
    }


def test_both_hubs_carry_a_catalogue_with_the_vocabulary():
    """A hub IS a catalogue of what it lists, so it says so and carries the same vocabulary."""
    src = PAGES.read_text(encoding="utf-8")
    assert '"@type": "DataCatalog"' in src.split("def _hub_catalogue", 1)[1].split("\n\n", 1)[0], (
        "the hub node must be a DataCatalog"
    )
    for emitter in ("surveys_index_page", "collections_index_page"):
        body = src.split(f"def {emitter}", 1)[1].split("\ndef ", 1)[0]
        assert "_hub_catalogue(" in body, f"{emitter} must emit the hub catalogue"
        assert body.index("_hub_catalogue(") < body.index("_breadcrumb("), (
            f"{emitter} must put the catalogue BEFORE the breadcrumb, like every other entity node"
        )
    assert "_keywords()" in src.split("def _hub_catalogue", 1)[1].split("\n\n", 1)[0], (
        "the hub catalogue must carry the shared vocabulary, not a copy of it"
    )


def test_the_emitter_says_what_a_keyword_is_for():
    """The honest fact sits beside the vocabulary, so nobody adds a term expecting a ranking effect.

    FAILS if the note goes, or if any surface starts claiming the opposite."""
    src = PAGES.read_text(encoding="utf-8")
    preamble = src.split("_KEYWORDS_BASE = (", 1)[0][-900:]
    assert "not a ranking signal" in preamble, (
        "the vocabulary must be introduced by the fact that a keyword is not a ranking signal"
    )
    for path in (PAGES, PORTAL / "index.html"):
        text = path.read_text(encoding="utf-8").lower()
        for claim in ("keywords improve ranking", "for seo", "boosts search rank"):
            assert claim not in text, f"{path.name} claims a keyword affects ranking: {claim}"
