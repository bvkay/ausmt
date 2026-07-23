"""IDCONS D4 (identifier-consolidation, SPEC §5.4): the portal renders a RESERVED identifier HONESTLY —
plain text + a muted "(reserved — not yet active)" note, NEVER an anchor — at every metadata-DOI link
surface, while `ok` / `unknown` render as links exactly as today.

Reuses the real-src VM harness from test_related_identifiers_render (DRIVER + _render): it boots the
shipped src modules against a synthetic one-survey surveys.json and renders the drawer/story. The fixture
carries ONE ok, ONE reserved, and ONE unknown identifier so all three code paths are exercised in one pass.

The resolution facets (doi_resolution / ts_pid_resolution / related_identifiers[].resolution) are exactly
what build_portal.apply_pid_resolution attaches from the pid_status.json cache. Skips without Node (CI has it).
"""
import shutil

import pytest

from test_related_identifiers_render import _render


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_reserved_dataset_doi_renders_as_text_not_anchor(tmp_path):
    """A dataset DOI the cache marks reserved (doi.org's own 404) renders as plain text + the muted note,
    with NO doi.org anchor. FAILS IF a reserved DOI still ships as a live (dead) link."""
    extra = {"doi": "10.25914/reserved-doi", "doi_resolution": "reserved"}
    _station, story, _card = _render(tmp_path, extra)
    assert "(reserved — not yet active)" in story, "the reserved note did not render:\n" + story
    assert 'href="https://doi.org/10.25914/reserved-doi"' not in story, \
        "a reserved dataset DOI still rendered as a doi.org anchor:\n" + story
    assert "10.25914/reserved-doi" in story, "the reserved DOI text is not shown at all:\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_ok_dataset_doi_still_links(tmp_path):
    """resolution 'ok' -> the DOI links exactly as today (the resolve-gate never suppresses a live DOI)."""
    extra = {"doi": "10.25914/live-doi", "doi_resolution": "ok"}
    _station, story, _card = _render(tmp_path, extra)
    assert 'href="https://doi.org/10.25914/live-doi"' in story, \
        "an ok dataset DOI did not render as a link:\n" + story
    assert "(reserved — not yet active)" not in story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_unknown_dataset_doi_links_as_today(tmp_path):
    """No resolution facet (no cache / no entry) -> links as today, byte-for-byte. FAILS IF the absence of
    a cache changes the served rendering (the backward-compatibility contract, SPEC §5.3)."""
    extra = {"doi": "10.25914/unknown-doi"}   # no doi_resolution key at all
    _station, story, _card = _render(tmp_path, extra)
    assert 'href="https://doi.org/10.25914/unknown-doi"' in story, \
        "an unknown (uncached) DOI did not link as today:\n" + story
    assert "(reserved — not yet active)" not in story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_reserved_related_identifier_renders_as_text(tmp_path):
    """A per-entry resolution 'reserved' on a related_identifiers row -> text + note, not an anchor; a
    sibling 'ok' row still links. FAILS IF the related-identifiers block links a reserved DOI."""
    extra = {"related_identifiers": [
        {"identifier": "10.25914/reserved-rel", "identifier_type": "DOI", "relation": "IsDerivedFrom",
         "custodian": "NCI", "resolution": "reserved"},
        {"identifier": "10.25914/live-rel", "identifier_type": "DOI", "relation": "IsVariantFormOf",
         "custodian": "NCI", "resolution": "ok"}]}
    _station, story, _card = _render(tmp_path, extra)
    assert "Related identifiers:" in story, "the related-identifiers block did not render:\n" + story
    # the reserved row: text + note, NO anchor
    assert 'href="https://doi.org/10.25914/reserved-rel"' not in story, \
        "a reserved related identifier still linked:\n" + story
    assert "(reserved — not yet active)" in story
    # the live sibling row: still a doi.org anchor
    assert 'href="https://doi.org/10.25914/live-rel"' in story, \
        "an ok related identifier stopped linking:\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_reserved_ts_pid_collection_renders_as_text(tmp_path):
    """A reserved survey collection PID (ts_pid) -> the Raw time series cell shows text + note, not the
    'survey collection' anchor. FAILS IF a reserved ts_pid ships as a dead collection link."""
    extra = {"ts": "ok", "ts_pid": "10.25914/reserved-coll", "ts_pid_resolution": "reserved"}
    station, _story, _card = _render(tmp_path, extra)
    assert "(reserved — not yet active)" in station, "the reserved ts_pid note did not render:\n" + station
    assert 'href="https://doi.org/10.25914/reserved-coll"' not in station, \
        "a reserved ts_pid still rendered as a collection anchor:\n" + station
