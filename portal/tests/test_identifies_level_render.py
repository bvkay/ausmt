"""D-L (identifiers by data level, SPEC §9): the portal labels related-identifier rows by their NCI Table 1
DATA LEVEL when `identifies` is present, links each files-tab level row to its level's DOI, and omits the
station-drawer "Identifiers & instruments" expander entirely when there is nothing to show.

Reuses the real-src VM harness from test_related_identifiers_render (DRIVER + _render): it boots the shipped
src modules against a synthetic one-survey surveys.json and renders the drawer/story. Skips without Node.
"""
import re
import shutil

import pytest

from test_related_identifiers_render import _render


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_related_block_labels_by_level_when_identifies_present(tmp_path):
    """A row with identifies renders its LEVEL label (Raw time series / Collection / Entire dataset), not
    the DataCite relation label. FAILS IF the block still labels by relation when a level is present."""
    extra = {"related_identifiers": [
        {"identifier": "10.25914/raw", "identifier_type": "DOI", "relation": "IsDerivedFrom",
         "custodian": "NCI", "identifies": "raw_packed"},
        {"identifier": "10.25914/parent", "identifier_type": "DOI", "relation": "IsPartOf",
         "custodian": "NCI", "identifies": "collection"},
        {"identifier": "10.25914/whole", "identifier_type": "DOI", "relation": "IsVariantFormOf",
         "custodian": "GA", "identifies": "entire"}]}
    station, story, _card = _render(tmp_path, extra)
    # The rollup block moved to the STATION drawer with the survey drawer; it is unchanged.
    assert "Raw time series: " in station, "the raw_packed row is not labelled by its level:\n" + station
    assert "Collection: " in station, "the collection row is not labelled by its level:\n" + station
    assert "Entire dataset: " in station, "the entire row is not labelled by its level:\n" + station
    # the level label REPLACES the relation label for an identifies row
    assert "Derived from: " not in station, "an identifies row still showed the relation label:\n" + station
    # ---- SURVEY GRID SLOT MAPPING -------------------------------
    # collection -> slot 1, raw_packed -> slot 2. This fixture carries BOTH `collection` and `entire`, so
    # The drawer-polish COLLISION RULE applies: `entire` is an ALIAS for the Collection
    # slot, but the exact `collection` match wins the slot and `entire` falls to the extra-tile bucket -
    # nothing silently dropped, and the header count tallies the SLOT (2 of 6), never both rows.
    tiles = re.findall(r'<div class="prod[^"]*dl-tile"[^>]*>.*?</div></div>', story, re.S)
    assert len(tiles) == 7, f"expected the six fixed slots plus ONE extra tile, got {len(tiles)}:\n{story}"
    assert tiles[0].startswith('<div class="prod dl-tile"') and "10.25914/parent" in tiles[0], \
        "slot 1 (Collection) did not take the collection-identified row:\n" + tiles[0]
    assert "Collection<" in tiles[0], "slot 1 is not the Collection slot:\n" + tiles[0]
    assert "10.25914/raw" in tiles[1] and "Packed Raw Data<" in tiles[1], \
        "slot 2 (Packed Raw Data) did not take the raw_packed-identified row:\n" + tiles[1]
    # slots 3-6 (Level 0..Level 3) record nothing here and must still be VISIBLE, muted.
    for i, name in ((2, "Level 0"), (3, "Level 1"), (4, "Level 2"), (5, "Level 3")):
        assert f"{name}<" in tiles[i] and "not yet recorded" in tiles[i] and "dis" in tiles[i], \
            f"slot {i + 1} ({name}) must render muted-but-visible:\n" + tiles[i]
    # the collision-losing `entire` row is the 7th tile, labelled by the level vocabulary, not dropped
    assert "Entire dataset" in tiles[6] and "10.25914/whole" in tiles[6], \
        "the collision-losing `entire` row was dropped instead of rendering as an extra tile:\n" + story
    assert "2 of 6 recorded" in story, \
        "the header count must tally only the SIX fixed slots (extras excluded):\n" + story
    # A row can never be BOTH a slot and an extra: the collision-losing identifier must occupy exactly ONE
    # tile. FAILS IF a future alias change double-renders the row it did not consume. (Counted over TILES,
    # not substring hits - one tile carries its identifier three times: data-url, href and link text.)
    assert sum("10.25914/whole" in t for t in tiles) == 1, \
        "the collision-losing `entire` row occupies more than one tile (slot AND extra):\n" + story


# ---- drawer-polish workflow: `entire` FILLS the Collection slot ----------------------
# `entire` is the umbrella record - one deposit covering all levels - which is exactly what the Collection
# slot names. It must not fall through to the extra-tile bucket, or Gawler Phase 2 (its GSSA/SARIG landing
# page + a level3 models record) read "1 of 6 recorded" with an orphan tile hanging under the grid. These
# two pins are the stated acceptance shape.
@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_entire_only_survey_fills_the_collection_slot(tmp_path):
    """Gawler-Phase-2-shaped: an `entire` row and NO `collection` row. The `entire` row FILLS slot 1
    (Collection), the count reads 2 of 6 with its Level 3, and NO extra tile hangs below the six.
    FAILS (RED before the alias) IF `entire` still lands in the extra-tile bucket -> '1 of 6' + an orphan."""
    extra = {"related_identifiers": [
        {"identifier": "https://pid.sarig.sa.gov.au/dataset/mesac487", "identifier_type": "URL",
         "relation": "IsVariantFormOf", "custodian": "GSSA/SARIG", "identifies": "entire"},
        {"identifier": "https://pid.sarig.sa.gov.au/dataset/mesac525", "identifier_type": "URL",
         "relation": "IsSourceOf", "custodian": "GSSA/SARIG", "identifies": "level3"}]}
    _station, story, _card = _render(tmp_path, extra)
    tiles = re.findall(r'<div class="prod[^"]*dl-tile"[^>]*>.*?</div></div>', story, re.S)
    assert len(tiles) == 6, \
        f"the `entire` row must FILL a slot, leaving exactly the six tiles, got {len(tiles)}:\n{story}"
    assert "Collection<" in tiles[0] and "mesac487" in tiles[0], \
        "slot 1 (Collection) did not take the `entire` row:\n" + tiles[0]
    assert "dis" not in tiles[0].split(">")[0], \
        "the Collection slot still renders MUTED despite the `entire` row filling it:\n" + tiles[0]
    assert "Level 3<" in tiles[5] and "mesac525" in tiles[5], \
        "slot 6 (Level 3) did not take the level3 row:\n" + tiles[5]
    assert "2 of 6 recorded" in story, \
        "the count must read '2 of 6 recorded' once `entire` fills the Collection slot:\n" + story
    # the orphan is gone: `entire`'s own vocabulary label must not head a tile of its own
    assert "Entire dataset" not in story, \
        "the `entire` row rendered as an extra tile as well as filling the Collection slot:\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_collection_and_entire_collision_gives_the_slot_to_collection(tmp_path):
    """COLLISION RULE: a survey carrying BOTH `collection` and `entire` gives slot 1 to `collection` (the
    exact match beats the alias) and renders `entire` as an EXTRA tile - nothing silently dropped, and the
    count stays 1 of 6 (one SLOT recorded, not two rows). FAILS IF the alias steals the slot from the exact
    match, IF the losing row vanishes, or IF the count double-tallies the pair."""
    extra = {"related_identifiers": [
        {"identifier": "10.25914/umbrella", "identifier_type": "DOI", "relation": "IsVariantFormOf",
         "custodian": "GA", "identifies": "entire"},
        {"identifier": "10.25914/exact-collection", "identifier_type": "DOI", "relation": "IsPartOf",
         "custodian": "NCI", "identifies": "collection"}]}
    _station, story, _card = _render(tmp_path, extra)
    tiles = re.findall(r'<div class="prod[^"]*dl-tile"[^>]*>.*?</div></div>', story, re.S)
    assert len(tiles) == 7, f"expected the six slots plus ONE extra tile, got {len(tiles)}:\n{story}"
    # declared `entire` FIRST in the list, so a naive "first matching row wins" would hand it the slot
    assert "Collection<" in tiles[0] and "10.25914/exact-collection" in tiles[0], \
        "the exact `collection` row must win slot 1 over the `entire` alias:\n" + tiles[0]
    assert "10.25914/umbrella" not in tiles[0], "the `entire` alias took the slot from the exact match:\n" + tiles[0]
    assert "Entire dataset" in tiles[6] and "10.25914/umbrella" in tiles[6], \
        "the collision-losing `entire` row was dropped instead of rendering as an extra tile:\n" + story
    assert "1 of 6 recorded" in story, \
        "the count must tally the SLOT (1 of 6), never both colliding rows:\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_data_level_section_header_copy(tmp_path):
    """The wording from the design mockup: the grid's section head reads 'Data at every level:
    N of 6 recorded', not the old 'Persistent identifiers:'. The STATION drawer's own identifiers block
    keeps its name - that surface is explicitly untouched. FAILS (RED before the copy change) IF the survey
    grid still heads 'Persistent identifiers:' or IF the station block loses its heading."""
    _station, story, _card = _render(tmp_path, {})
    assert "Data at every level: " in story, "the grid's section head did not take the approved wording:\n" + story
    assert "Persistent identifiers:" not in story, \
        "the old 'Persistent identifiers:' head survives on the survey drawer:\n" + story
    # non-vacuous: the STATION rollup keeps the old name, so the string is not simply gone from the portal
    station2, _s2, _c2 = _render(tmp_path, {"related_identifiers": [
        {"identifier": "10.25914/x", "identifier_type": "DOI", "relation": "IsPartOf",
         "identifies": "collection"}]})
    assert re.search(r"Persistent identifiers (&amp;|&) instruments", station2), \
        "the untouched STATION identifiers block lost its heading:\n" + station2


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_legacy_row_without_identifies_falls_back_to_relation_label(tmp_path):
    """Back-compat: a row with NO identifies keeps its relation label (the fallback). FAILS IF the level
    labelling breaks a legacy relation-only row."""
    extra = {"related_identifiers": [
        {"identifier": "10.25914/legacy", "identifier_type": "DOI", "relation": "Cites", "custodian": "GA"}]}
    station, story, _card = _render(tmp_path, extra)
    assert "Cites: " in station, "a legacy relation-only row lost its relation label:\n" + station
    # On the survey grid a level-less legacy row maps to no slot, so it rides the extra-tile rule with its
    # relation label intact - the count stays 0 of 6 because no FIXED slot is recorded.
    assert "Cites" in story and "10.25914/legacy" in story, \
        "a legacy relation-only row was dropped from the survey grid:\n" + story
    assert "0 of 6 recorded" in story, "an extra tile must not be counted as one of the six slots:\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_files_tab_level_row_links_its_identifies_doi(tmp_path):
    """On the files tab, a level row links the related_identifiers DOI whose identifies matches that
    level — so a user jumps straight to the DOI for the data level. FAILS IF the level row falls back to
    the collection PID instead of its own level's identifier."""
    extra = {"ts": "ok", "ts_levels": ["raw_packed", "level0", "level1"],
             "related_identifiers": [
                 {"identifier": "10.25914/raw-level", "identifier_type": "DOI", "relation": "IsDerivedFrom",
                  "custodian": "NCI", "identifies": "raw_packed"},
                 {"identifier": "10.25914/l1-level", "identifier_type": "DOI", "relation": "IsDerivedFrom",
                  "custodian": "NCI", "identifies": "level1"}]}
    station, _story, _card = _render(tmp_path, extra)
    # the files-tab product tiles carry the level DOI as a data-url (an [data-prod=open] tile)
    assert 'data-url="https://doi.org/10.25914/raw-level"' in station, \
        "the Raw time series file row did not link its own level DOI:\n" + station
    assert 'data-url="https://doi.org/10.25914/l1-level"' in station, \
        "the Level 1 file row did not link its own level DOI:\n" + station


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_files_tab_reserved_level_doi_is_inert(tmp_path):
    """Reserved honesty on the level-linked files rows: a reserved level DOI is left inert (no anchor / no
    data-url to it), with the honest note. FAILS IF a reserved level DOI ships as a live (dead) link."""
    extra = {"ts": "ok", "ts_levels": ["raw_packed"],
             "related_identifiers": [
                 {"identifier": "10.25914/reserved-level", "identifier_type": "DOI",
                  "relation": "IsDerivedFrom", "custodian": "NCI", "identifies": "raw_packed",
                  "resolution": "reserved"}]}
    station, _story, _card = _render(tmp_path, extra)
    assert 'data-url="https://doi.org/10.25914/reserved-level"' not in station, \
        "a reserved level DOI still linked on the files tab:\n" + station
    assert "reserved, not yet active" in station


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_files_tab_hostile_url_level_doi_is_never_an_open_action(tmp_path):
    """SCHEME GUARD (D-L4 files tab): a URL-typed related_identifier is relatedIdHref's RAW value, so a
    javascript: identifier that matches a served level would otherwise ride the level row straight into a
    product-tile open action (data-url -> window.open). The tsLevelRow scheme guard admits ONLY http(s),
    so the hostile level DOI yields NO open action on the files-tab level row; it falls through to the
    collection PID. The related-identifiers block still renders the value inert (escUrl -> href '#').
    FAILS (RED on the unguarded tsLevelRow) IF the javascript: value reaches a data-url on the level row."""
    extra = {"ts": "ok", "ts_levels": ["raw_packed"],
             "related_identifiers": [
                 {"identifier": "javascript:alert(1)", "identifier_type": "URL",
                  "relation": "IsDerivedFrom", "custodian": "NCI", "identifies": "raw_packed"}]}
    station, story, _card = _render(tmp_path, extra)
    # the files-tab level row must NOT carry the hostile value as an open action's data-url (the sink
    # is window.open on a product tile's data-url — see drawer.js prod==="open") ...
    assert 'data-url="javascript:' not in station, \
        "a javascript: level identifier reached a files-tab product-tile open action:\n" + station
    # ... nor as an executable anchor anywhere in the station drawer (the identifiers block also renders here).
    assert 'href="javascript:' not in station, "a hostile identifier became an executable anchor:\n" + station
    # the level row still renders (falls through to the survey/NCI collection PID), not dropped
    assert "Raw time series" in station
    # and the related-identifiers block collapses the URL-typed hostile value to an inert href '#'
    assert 'href="javascript:' not in story, "a hostile identifier became an executable anchor:\n" + story
    assert 'href="#"' in story, "the URL-typed hostile value did not collapse to href '#':\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_zero_identifier_survey_omits_the_identifiers_expander(tmp_path):
    """Card polish: a survey with no identifiers shows NO 'Identifiers & instruments' expander in the
    station drawer (the disclosure is omitted, not rendered empty). FAILS IF the empty expander returns."""
    station, _story, _card = _render(tmp_path, {})   # no doi, no org_ror, no raid, no related_identifiers
    assert "Identifiers &amp; instruments" not in station and "Identifiers & instruments" not in station, \
        "the Identifiers & instruments expander rendered for a zero-identifier survey:\n" + station
    # a survey WITH an identifier DOES render it (guards against a vacuous pass)
    station2, _s2, _c2 = _render(tmp_path, {"related_identifiers": [
        {"identifier": "10.25914/x", "identifier_type": "DOI", "relation": "IsVariantFormOf",
         "identifies": "entire"}]})
    assert re.search(r"Identifiers (&amp;|&) instruments", station2), \
        "the expander did not render for a survey that HAS an identifier:\n" + station2
