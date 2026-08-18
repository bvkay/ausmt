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
    # The rollup block moved to the STATION drawer with the survey-drawer lane (ruling 4); it is unchanged.
    assert "Raw time series: " in station, "the raw_packed row is not labelled by its level:\n" + station
    assert "Collection: " in station, "the collection row is not labelled by its level:\n" + station
    assert "Entire dataset: " in station, "the entire row is not labelled by its level:\n" + station
    # the level label REPLACES the relation label for an identifies row
    assert "Derived from: " not in station, "an identifies row still showed the relation label:\n" + station
    # ---- SURVEY GRID SLOT MAPPING (ruling 4 + the slot-mapping ruling) -------------------------------
    # collection -> slot 1, raw_packed -> slot 2. `entire` maps to NO slot, so it must NOT consume one and
    # must NOT vanish: it renders as an EXTRA tile below the six, and the header count stays 2 of 6.
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
    # the unmapped `entire` row is the 7th tile, labelled by the level vocabulary, and NOT counted in the six
    assert "Entire dataset" in tiles[6] and "10.25914/whole" in tiles[6], \
        "the unmapped `entire` row was dropped instead of rendering as an extra tile:\n" + story
    assert "2 of 6 recorded" in story, \
        "the header count must tally only the SIX fixed slots (extras excluded):\n" + story


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
    """D-L4: on the files tab, a level row links the related_identifiers DOI whose identifies matches that
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
    """Card-lane polish: a survey with no identifiers shows NO 'Identifiers & instruments' expander in the
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
