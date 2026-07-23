"""IDCONS D4 (identifier-consolidation, SPEC §5.2) — the pid_status.json refresh tool.

The tool is the ONLY network-touching piece; these tests keep the BUILD/CI offline by INJECTING a fake
head function (never a real doi.org HEAD). They pin the alive-rule classifier, the DOI-shape helpers, the
union sweep (typed related_identifiers DOIs + the still-readable flat dataset_doi / collection_pid — SPEC
§8.2 A-C5), and the written cache shape build_portal consumes.
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
_REFRESH_PY = ROOT / "scripts" / "refresh_pid_status.py"


def _load():
    spec = importlib.util.spec_from_file_location("_ausmt_refresh_pid_status", _REFRESH_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load()


def test_classify_alive_rule():
    assert rp.classify(404, False) == rp.STATUS_UNREGISTERED
    for code in (200, 301, 302, 403, 500):
        assert rp.classify(code, False) == rp.STATUS_RESOLVED, code
    assert rp.classify(None, True) == rp.STATUS_ERROR
    assert rp.classify(None, False) == rp.STATUS_ERROR


def test_is_doi_and_normalise():
    assert rp.is_doi("10.25914/x")
    assert not rp.is_doi("hdl:1/2")
    assert rp.normalise_doi("https://doi.org/10.25914/x") == "10.25914/x"
    assert rp.normalise_doi("10.25914/x") == "10.25914/x"


def test_doi_identifiers_of_union_of_typed_and_flat():
    """SPEC §8.2 A-C5: sweep the UNION of DOI-typed related_identifiers rows AND the flat dataset_doi /
    collection_pid, deduped by string. A non-DOI-typed row and a Handle flat value are excluded. FAILS IF
    a flat-only DOI is missed or a non-DOI is swept."""
    y = {"identifiers": {"dataset_doi": "10.25914/flat"},
         "time_series": {"collection_pid": "10.25914/coll"},
         "related_identifiers": [
             {"identifier": "10.25914/typed", "identifier_type": "DOI"},
             {"identifier": "https://hdl.handle.net/1/2", "identifier_type": "Handle"},  # excluded (not DOI)
             {"identifier": "10.25914/typed", "identifier_type": "DOI"},                  # dup -> deduped
         ]}
    assert rp.doi_identifiers_of(y) == {"10.25914/flat", "10.25914/coll", "10.25914/typed"}


def test_doi_identifiers_of_excludes_non_doi_flat():
    y = {"time_series": {"collection_pid": "hdl.handle.net/1234/abc"}}  # a Handle, not a DOI
    assert rp.doi_identifiers_of(y) == set()


def test_refresh_writes_cache_with_mocked_network(tmp_path):
    """End-to-end over a mini corpus with a MOCKED head function (offline). The written pid_status.json is
    exactly the shape build_portal.load_pid_status consumes. FAILS IF the cache shape or classification
    drifts from the alive-rule."""
    # two survey packages: one reserved DOI (doi.org 404), one live DOI (200), one T&F-style 403 (alive)
    (tmp_path / "vulcan-2022").mkdir()
    (tmp_path / "vulcan-2022" / "survey.yaml").write_text(
        "name: Vulcan\nslug: vulcan-2022\n"
        "related_identifiers:\n"
        "  - identifier: 10.25914/reserved\n    identifier_type: DOI\n"
        "identifiers:\n  dataset_doi: 10.1080/tf403\n", encoding="utf-8")
    (tmp_path / "auslamp-sa").mkdir()
    (tmp_path / "auslamp-sa" / "survey.yaml").write_text(
        "name: AusLAMP SA\nslug: auslamp-sa\n"
        "time_series:\n  collection_pid: 10.25914/live\n", encoding="utf-8")

    def fake_head(doi):
        return {"10.25914/reserved": (404, False),
                "10.1080/tf403": (403, False),
                "10.25914/live": (200, False)}[doi]

    out = tmp_path / "cache" / "pid_status.json"
    written = rp.refresh(tmp_path, out, head_fn=fake_head, now="2026-07-22T00:00:00Z")
    assert out.is_file()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == written
    assert on_disk["10.25914/reserved"]["status"] == "unregistered"
    assert on_disk["10.1080/tf403"]["status"] == "resolved"     # 403 is alive (bot-block), not dead
    assert on_disk["10.25914/live"]["status"] == "resolved"
    assert all(v["checked"] == "2026-07-22T00:00:00Z" for v in on_disk.values())


def test_refresh_network_error_is_error_status(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "survey.yaml").write_text(
        "name: S\nslug: s\nidentifiers:\n  dataset_doi: 10.1/unreachable\n", encoding="utf-8")
    out = tmp_path / "pid_status.json"
    written = rp.refresh(tmp_path, out, head_fn=lambda d: (None, True), now="2026-07-22T00:00:00Z")
    assert written["10.1/unreachable"]["status"] == "error"
