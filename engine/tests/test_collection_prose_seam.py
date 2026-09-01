"""The collection prose seam, walked end to end: survey.yaml TEXT to the served collection page.

Structured collection prose crosses four stages before a reader sees it: the YAML parser, the
per-survey facet mapper (survey_meta_from_yaml / _collection_of), the programme rollup
(_group_collections) and the renderer (collection_page). Every stage had its own test and the
prose still arrived empty on the served page, because the facet mapper whitelists the collection
subkeys it carries and `prose` was not among them: the rollup merged a key nothing supplied, the
renderer found no slots, and the page silently fell back to the flat description as one paragraph.
A per-stage test cannot see that, so this pin walks the whole seam in one pass and fails when any
stage drops the payload.

The two members are the first-declarer merge: the first declares no prose at all, so the rollup
must take the second member's block rather than letting an absent value latch the field empty.
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402
import _pages  # noqa: E402

BASE = "https://x.example"

# The programme block every member repeats. The first member stops here: it declares the
# collection and its scalar fields and NO prose, which is what a member that has nothing to say
# about the programme looks like.
_COLL_HEAD = (
    "collection:\n"
    "  id: legacy-gds\n"
    "  title: Australia legacy GDS\n"
    "  type: programme\n"
    "  status: completed\n"
    "  start_year: 1966\n"
    '  last_updated: "2026-09-01"\n'
    '  description: "A national programme. It spans several states."\n'
)

# The second member carries the long-form page copy. Five About paragraphs, one of them the '# '
# subheading, plus a members_after slot whose whole point is that it lands BELOW the generated
# member cards rather than above them.
_COLL_PROSE = (
    "  prose:\n"
    "    about:\n"
    '      - "The collection brings together historical surveys."\n'
    '      - "Geomagnetic depth sounding preceded modern magnetotellurics here."\n'
    '      - "# Preservation and reprocessing"\n'
    '      - "A major source is the Australian Electromagnetic Database."\n'
    '      - "The provenance of each data product is retained."\n'
    "    members_after:\n"
    '      - "Where appropriate, surveys may be identified as:"\n'
    '      - "Reprocessed: transfer functions newly estimated."\n'
)

_ABOUT_PARAGRAPHS = ("The collection brings together historical surveys.",
                     "Geomagnetic depth sounding preceded modern magnetotellurics here.",
                     "A major source is the Australian Electromagnetic Database.",
                     "The provenance of each data product is retained.")


def _survey_yaml(tmp_path, slug, name, *, prose: bool) -> Path:
    """One member survey.yaml on disk, as TEXT, so the parser is part of what is under test."""
    d = tmp_path / "surveys" / slug
    d.mkdir(parents=True)
    body = (f"slug: {slug}\n"
            f'name: "{name}"\n'
            "version: 1.0.0\n"
            "country: Australia\n"
            'organisation: {name: "Test Org", ror: "https://ror.org/00000000a"}\n'
            + _COLL_HEAD + (_COLL_PROSE if prose else ""))
    p = d / "survey.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def _rendered_collection(tmp_path):
    """yaml text -> _read_yaml -> survey_meta_from_yaml -> _group_collections -> collection_page."""
    members = [("Member One", "member-one", False), ("Member Two", "member-two", True)]
    surveys_meta, stations = {}, []
    for i, (name, slug, prose) in enumerate(members):
        y = build_portal._read_yaml(_survey_yaml(tmp_path, slug, name, prose=prose))
        assert isinstance(y, dict), f"{slug}: the fixture must parse"
        surveys_meta[name] = build_portal.survey_meta_from_yaml(y)
        stations.append((None, {"survey": name, "lat": -30.0 - i, "lon": 137.0 + i}))

    colls, survey_coll = build_portal._group_collections(surveys_meta, stations)
    assert set(survey_coll.values()) == {"legacy-gds"}, survey_coll

    member_slugs = [(name, slug) for name, slug, _p in members]
    page = _pages.collection_page(
        cid="legacy-gds", coll=colls["legacy-gds"], member_slugs=member_slugs,
        member_smeta=[surveys_meta[name] for name, _s, _p in members], base=BASE,
        member_points={name: [(137.0 + i, -30.0 - i)] for i, (name, _s, _p) in enumerate(members)},
        member_facts={slug: {"title": name, "org": "Test Org", "n_stations": 1}
                      for name, slug, _p in members})
    return colls["legacy-gds"], page


def test_declared_collection_prose_reaches_the_served_about_section(tmp_path):
    """FAILS IF any stage between the survey.yaml text and the rendered page drops the prose: the
    About section then falls back to the flat description as one paragraph, with no subheading and
    no structure, which is exactly what the served page did while every per-stage test passed."""
    coll, page = _rendered_collection(tmp_path)

    # Stage 2 and 3 in one assertion: the facet carried the block and the rollup merged it from the
    # SECOND member, so an absent value on the first member never latched the field empty.
    assert isinstance(coll.get("prose"), dict) and coll["prose"].get("about"), \
        f"the rollup carries no prose, so the renderer has nothing to render: {coll.get('prose')!r}"

    about = page.split('<h2 id="about">About</h2>\n', 1)[1].split('<h2 id="surveys"', 1)[0]
    assert about.count('<p class="collprose">') == len(_ABOUT_PARAGRAPHS), \
        f"expected {len(_ABOUT_PARAGRAPHS)} About paragraphs, got:\n{about}"
    for para in _ABOUT_PARAGRAPHS:
        assert f'<p class="collprose">{para}</p>' in about, f"paragraph lost or merged: {para}"
    assert '<h3 class="collsub">Preservation and reprocessing</h3>' in about, \
        "the '# ' paragraph is the section's subheading, not a paragraph"
    assert "A national programme. It spans several states." not in about, \
        "the flat description is the FALLBACK: a collection with prose must not render both"


def test_declared_members_after_prose_lands_below_the_member_cards(tmp_path):
    """FAILS IF the members_after slot is dropped or rendered above the generated roll-call: the
    curator's 'how to read these cards' text only means anything after the cards it describes."""
    _coll, page = _rendered_collection(tmp_path)

    lead = '<p class="collprose">Where appropriate, surveys may be identified as:</p>'
    assert lead in page, "the members_after prose is missing from the page"
    assert '<p class="collprose">Reprocessed: transfer functions newly estimated.</p>' in page, \
        "every members_after paragraph is its own element"
    assert page.index('<div class="memlist">') < page.index(lead), \
        "members_after must follow the member cards, not precede them"
    assert page.index('href="/surveys/member-two"') < page.index(lead), \
        "the last member card must be written before the prose that explains the cards"
