"""IDCONS D4 (identifier-consolidation, SPEC §5.4): the portal renders a RESERVED identifier HONESTLY —
plain text + a muted "(reserved, not yet active)" note, NEVER an anchor — at every metadata-DOI link
surface, while `ok` / `unknown` render as links exactly as today.

Reuses the real-src VM harness from test_related_identifiers_render (DRIVER + _render): it boots the
shipped src modules against a synthetic one-survey surveys.json and renders the drawer/story. The fixture
carries ONE ok, ONE reserved, and ONE unknown identifier so all three code paths are exercised in one pass.

The resolution facets (doi_resolution / ts_pid_resolution / related_identifiers[].resolution) are exactly
what build_portal.apply_pid_resolution attaches from the pid_status.json cache. Skips without Node (CI has it).
"""
import re
import shutil

import pytest

from test_related_identifiers_render import _render


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_reserved_dataset_doi_renders_as_text_not_anchor(tmp_path):
    """A dataset DOI the cache marks reserved (doi.org's own 404) renders as plain text + the muted note,
    with NO doi.org anchor. FAILS IF a reserved DOI still ships as a live (dead) link."""
    extra = {"doi": "10.25914/reserved-doi", "doi_resolution": "reserved"}
    _station, story, _card = _render(tmp_path, extra)
    assert "(reserved, not yet active)" in story, "the reserved note did not render:\n" + story
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
    assert "(reserved, not yet active)" not in story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_unknown_dataset_doi_links_as_today(tmp_path):
    """No resolution facet (no cache / no entry) -> links as today, byte-for-byte. FAILS IF the absence of
    a cache changes the served rendering (the backward-compatibility contract, SPEC §5.3)."""
    extra = {"doi": "10.25914/unknown-doi"}   # no doi_resolution key at all
    _station, story, _card = _render(tmp_path, extra)
    assert 'href="https://doi.org/10.25914/unknown-doi"' in story, \
        "an unknown (uncached) DOI did not link as today:\n" + story
    assert "(reserved, not yet active)" not in story


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
    assert "(reserved, not yet active)" in story
    # the live sibling row: still a doi.org anchor
    assert 'href="https://doi.org/10.25914/live-rel"' in story, \
        "an ok related identifier stopped linking:\n" + story


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_reserved_ts_pid_collection_renders_as_text(tmp_path):
    """A reserved survey collection PID (ts_pid) -> the Raw time series cell shows text + note, not the
    'survey collection' anchor. FAILS IF a reserved ts_pid ships as a dead collection link."""
    extra = {"ts": "ok", "ts_pid": "10.25914/reserved-coll", "ts_pid_resolution": "reserved"}
    station, _story, _card = _render(tmp_path, extra)
    assert "(reserved, not yet active)" in station, "the reserved ts_pid note did not render:\n" + station
    assert 'href="https://doi.org/10.25914/reserved-coll"' not in station, \
        "a reserved ts_pid still rendered as a collection anchor:\n" + station


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_sweep_no_reserved_identifier_is_ever_an_anchor(tmp_path):
    """IDCONS D4 SWEEP (SPEC §5.4): the load-bearing honesty guard. A single survey carries a RESERVED
    identifier in EVERY metadata-DOI slot at once — the flat dataset DOI (engine fallback), the survey
    collection PID (ts_pid), and a typed related_identifiers DOI row — plus a citation. Across ALL three
    rendered surfaces (station drawer, survey story, survey card), NO anchor's href may point at any
    reserved identifier: a reserved DOI is doi.org's own 404 and must never ship as a live (dead) link.
    FAILS RED if any surface — the Related-identifiers block, the Dataset-DOI row, the ts/source-archive
    lineage, a product tile, the survey-card chip, or the Cite tab — wraps a reserved id in an <a>."""
    reserved_ids = ("10.25914/reserved-flat", "10.25914/reserved-coll", "10.25914/reserved-rel")
    extra = {
        "doi": "10.25914/reserved-flat", "doi_resolution": "reserved",
        "ts": "ok", "ts_pid": "10.25914/reserved-coll", "ts_pid_resolution": "reserved",
        "related_identifiers": [
            {"identifier": "10.25914/reserved-rel", "identifier_type": "DOI", "relation": "IsDerivedFrom",
             "custodian": "NCI", "resolution": "reserved"}],
        # the Cite tab renders an APA string carrying m.doi (as plain text, never an anchor).
        "cite": {"au": "NCI Custodians", "yr": "2024", "ti": "Reserved-slot survey", "pb": "NCI"},
    }
    station, story, card = _render(tmp_path, extra)
    combined = station + story + card
    # Every anchor across all three surfaces; none may resolve a reserved identifier.
    anchors = re.findall(r'<a\b[^>]*\bhref="([^"]*)"', combined)
    offending = [h for h in anchors if any(rid in h for rid in reserved_ids)]
    assert not offending, ("a reserved identifier was wrapped in an anchor href (dead link shipped):\n"
                           + "\n".join(offending) + "\n---\n" + combined)
    # The reserved surfaces DID render (guards against a vacuous pass) — text + the muted honesty note.
    assert combined.count("(reserved, not yet active)") >= 3, \
        "the reserved honesty note did not render on every reserved slot:\n" + combined
    for rid in reserved_ids:
        assert rid in combined, f"the reserved id {rid!r} is not shown as text anywhere:\n" + combined


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_maturity_doi_star_honest_about_reserved(tmp_path):
    """IDCONS D4 (task 3d): the 'DOI' maturity star must NOT light green off a DOI that only 404s at
    doi.org. A survey whose ONLY dataset DOI is reserved shows the star hollow with the honest note
    'reserved (not yet active)'; an ok / unknown DOI lights it 'minted' as before. FAILS RED against the
    pre-fix model, which lit the star off any m.doi regardless of resolution."""
    # reserved-only: flat DOI reserved, no live typed DOI, no ts -> DOI star OFF + reserved wording.
    station, _story, _card = _render(tmp_path, {"doi": "10.25914/only-reserved",
                                                "doi_resolution": "reserved"})
    doi_dim = re.search(r'<li class="matdim (on|off)"><span[^>]*>[^<]*</span><span>DOI: ([^<]*)</span>',
                        station)
    assert doi_dim, "the DOI maturity dimension did not render:\n" + station
    assert doi_dim.group(1) == "off", "a reserved-only DOI still lit the maturity star green:\n" + station
    assert doi_dim.group(2) == "reserved (not yet active)", \
        "a reserved DOI did not read 'reserved (not yet active)':\n" + doi_dim.group(0)
    # ok DOI: the star lights 'minted' exactly as before (the resolve-gate never dims a live DOI).
    station_ok, _s, _c = _render(tmp_path, {"doi": "10.25914/live", "doi_resolution": "ok"})
    ok_dim = re.search(r'<li class="matdim (on|off)"><span[^>]*>[^<]*</span><span>DOI: ([^<]*)</span>',
                       station_ok)
    assert ok_dim and ok_dim.group(1) == "on" and ok_dim.group(2) == "minted", \
        "an ok DOI did not light the maturity star as 'minted':\n" + (ok_dim.group(0) if ok_dim else station_ok)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_maturity_ts_star_keys_off_derived_from_row(tmp_path):
    """IDCONS D1 (task 3d): 'Time series: linked' now lights off a typed IsDerivedFrom relation (the new
    home of the collection PID), not only the retired ts_pid / availability flag. A curator survey whose
    only time-series link is a typed IsDerivedFrom row (m.ts unset, no ts_pid) still reads 'linked'."""
    extra = {"related_identifiers": [
        {"identifier": "10.25914/coll", "identifier_type": "DOI", "relation": "IsDerivedFrom",
         "custodian": "NCI"}]}
    station, _story, _card = _render(tmp_path, extra)
    ts_dim = re.search(r'<li class="matdim (on|off)"><span[^>]*>[^<]*</span><span>Time series: ([^<]*)</span>',
                       station)
    assert ts_dim, "the Time series maturity dimension did not render:\n" + station
    assert ts_dim.group(1) == "on" and ts_dim.group(2) == "linked", \
        "an IsDerivedFrom typed row did not light 'Time series: linked':\n" + (ts_dim.group(0) if ts_dim else station)
