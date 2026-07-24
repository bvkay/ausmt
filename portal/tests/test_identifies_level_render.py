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
    _station, story, _card = _render(tmp_path, extra)
    assert "Raw time series: " in story, "the raw_packed row is not labelled by its level:\n" + story
    assert "Collection: " in story, "the collection row is not labelled by its level:\n" + story
    assert "Entire dataset: " in story, "the entire row is not labelled by its level:\n" + story
    # the level label REPLACES the relation label for an identifies row
    assert "Derived from: " not in story, "an identifies row still showed the relation label:\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_legacy_row_without_identifies_falls_back_to_relation_label(tmp_path):
    """Back-compat: a row with NO identifies keeps its relation label (the fallback). FAILS IF the level
    labelling breaks a legacy relation-only row."""
    extra = {"related_identifiers": [
        {"identifier": "10.25914/legacy", "identifier_type": "DOI", "relation": "Cites", "custodian": "GA"}]}
    _station, story, _card = _render(tmp_path, extra)
    assert "Cites: " in story, "a legacy relation-only row lost its relation label:\n" + story


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
