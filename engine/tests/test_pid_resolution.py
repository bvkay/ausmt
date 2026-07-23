"""IDCONS D4 (identifier-consolidation, SPEC §5.3) — build_portal CONSUMES pid_status.json and annotates
each served identifier's resolution facet (ok|reserved), fully backward-compatible.

Load-bearing invariants:
  * NO cache / no entry / status=error  -> NO facet attached (unknown = link as today) -> byte-identical.
  * status=resolved   -> resolution "ok"      (portal links, as today).
  * status=unregistered -> resolution "reserved" (portal renders plain text + a muted note).
  * the flat dataset_doi (SMETA.doi) + collection_pid (SMETA.ts_pid) get doi_resolution / ts_pid_resolution
    while they are still read during migration; each related_identifiers row gets a per-entry `resolution`.
  * the build NEVER hits the network — the cache is a plain file this test writes/mocks.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from extract import build_portal as bp   # noqa: E402

_MIN = {"name": "X", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0"}

_SURVEY = {**_MIN,
           "identifiers": {"dataset_doi": "10.25914/flat-doi"},
           "time_series": {"collection_pid": "10.25914/coll-pid"},
           "related_identifiers": [
               {"identifier": "10.25914/reserved", "identifier_type": "DOI", "relation": "IsDerivedFrom",
                "custodian": "NCI"},
               {"identifier": "10.25914/live", "identifier_type": "DOI", "relation": "IsVariantFormOf",
                "custodian": "NCI"}]}


def test_no_cache_leaves_smeta_byte_identical():
    """No cache -> apply_pid_resolution attaches NOTHING (unknown = today). FAILS IF a facet leaks in."""
    sm = bp.survey_meta_from_yaml(_SURVEY)
    before = json.dumps(sm, sort_keys=True)
    bp.apply_pid_resolution(sm, {})           # empty cache
    bp.apply_pid_resolution(sm, None)         # no cache at all
    assert json.dumps(sm, sort_keys=True) == before
    assert "doi_resolution" not in sm and "ts_pid_resolution" not in sm
    assert all("resolution" not in r for r in sm["related_identifiers"])


def test_reserved_and_resolved_facets_attached():
    """A cache marking one DOI unregistered and one resolved attaches reserved/ok to the right rows, and
    the flat dataset_doi / collection_pid get their own facets. FAILS IF a facet is mis-keyed or missing."""
    cache = {
        "10.25914/flat-doi": {"status": "resolved", "checked": "2026-07-22T00:00:00Z"},
        "10.25914/coll-pid": {"status": "unregistered", "checked": "2026-07-22T00:00:00Z"},
        "10.25914/reserved": {"status": "unregistered", "checked": "2026-07-22T00:00:00Z"},
        "10.25914/live": {"status": "resolved", "checked": "2026-07-22T00:00:00Z"},
    }
    sm = bp.apply_pid_resolution(bp.survey_meta_from_yaml(_SURVEY), cache)
    assert sm["doi_resolution"] == "ok"
    assert sm["ts_pid_resolution"] == "reserved"
    by_id = {r["identifier"]: r for r in sm["related_identifiers"]}
    assert by_id["10.25914/reserved"]["resolution"] == "reserved"
    assert by_id["10.25914/live"]["resolution"] == "ok"


def test_error_and_absent_entries_attach_nothing():
    """status=error is unknown -> no facet (portal links as today). An identifier absent from the cache
    likewise gets nothing. FAILS IF an error/absent status becomes a (mis)resolution."""
    cache = {"10.25914/flat-doi": {"status": "error", "checked": "2026-07-22T00:00:00Z"}}
    sm = bp.apply_pid_resolution(bp.survey_meta_from_yaml(_SURVEY), cache)
    assert "doi_resolution" not in sm            # error -> unknown
    assert "ts_pid_resolution" not in sm         # absent from cache -> unknown
    assert all("resolution" not in r for r in sm["related_identifiers"])


def test_resolution_of_pure_mapping():
    m = {"10.1/a": {"status": "resolved"}, "10.1/b": {"status": "unregistered"},
         "10.1/c": {"status": "error"}}
    assert bp._resolution_of("10.1/a", m) == "ok"
    assert bp._resolution_of("10.1/b", m) == "reserved"
    assert bp._resolution_of("10.1/c", m) is None
    assert bp._resolution_of("10.1/absent", m) is None
    assert bp._resolution_of("10.1/a", None) is None
    assert bp._resolution_of(None, m) is None


def test_load_pid_status_missing_and_malformed(tmp_path):
    """A missing file -> {}; a malformed file -> {} (never crashes the build). FAILS IF either raises."""
    assert bp.load_pid_status(None) == {}
    assert bp.load_pid_status(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert bp.load_pid_status(bad) == {}
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"10.1/x": {"status": "resolved"}}), encoding="utf-8")
    assert bp.load_pid_status(good) == {"10.1/x": {"status": "resolved"}}


def test_smeta_still_json_serializable_with_facets():
    cache = {"10.25914/reserved": {"status": "unregistered", "checked": "2026-07-22T00:00:00Z"}}
    json.dumps(bp.apply_pid_resolution(bp.survey_meta_from_yaml(_SURVEY), cache))
