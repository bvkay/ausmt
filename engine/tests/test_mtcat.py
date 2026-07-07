"""MTCAT v1.0 emission (Prototype 18).

The build emits mtcat.json — the portal-owned discovery document other portals could harvest.
This validates structure against schema/mtcat.schema.json with a dependency-free checker (jsonschema
is optional; a small recursive validator keeps the core test suite stdlib-only) and confirms the
required Portal / Survey / Station objects are populated from real data.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

# The build now defaults to the mt_metadata engine (slice-#3d regex retirement), so this build-
# integration test requires the stack. Regex parsing itself stays covered by test_real_dialects /
# test_pathological / test_golden_edi during the transition.
pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA = json.loads((ROOT / "schema" / "mtcat.schema.json").read_text(encoding="utf-8"))
SURVEYS = HERE / "fixtures"          # vendored, self-contained (no sibling-repo dependency)


def _check(node, schema, path="$"):
    """Minimal draft-07 subset validator: type, required, const, pattern, items, properties."""
    import re
    t = schema.get("type")
    types = t if isinstance(t, list) else ([t] if t else None)
    if types:
        ok = any(
            (ty == "object" and isinstance(node, dict)) or
            (ty == "array" and isinstance(node, list)) or
            (ty == "string" and isinstance(node, str)) or
            (ty == "number" and isinstance(node, (int, float)) and not isinstance(node, bool)) or
            (ty == "null" and node is None)
            for ty in types)
        assert ok, f"{path}: expected {types}, got {type(node).__name__}"
    if "const" in schema:
        assert node == schema["const"], f"{path}: expected const {schema['const']}"
    if "pattern" in schema and isinstance(node, str):
        assert re.search(schema["pattern"], node), f"{path}: {node!r} fails /{schema['pattern']}/"
    if isinstance(node, dict):
        for req in schema.get("required", []):
            assert req in node, f"{path}: missing required '{req}'"
        for k, sub in (schema.get("properties") or {}).items():
            if k in node:
                _check(node[k], sub, f"{path}.{k}")
    if isinstance(node, list) and "items" in schema:
        for i, el in enumerate(node):
            _check(el, schema["items"], f"{path}[{i}]")


def _build_mtcat(tmp_path):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--no-validate"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads((out / "mtcat.json").read_text(encoding="utf-8"))


def test_mtcat_emitted_and_valid(tmp_path):
    doc = _build_mtcat(tmp_path)
    _check(doc, SCHEMA)
    assert doc["portal"]["portal_id"] == "ausmt"
    assert doc["portal"]["schema"] == "mtcat"
    assert doc["portal"]["version"] == "1.0"
    assert doc["surveys"], "at least one survey"
    assert doc["stations"], "at least one station"


def test_mtcat_carries_served_tool_versions(tmp_path):
    """C32 §2: the MTCAT document gains additive document-level mt_metadata_version / mth5_version keys
    (mtcat.schema.json is additionalProperties:true at the top level, so no schema-version bump). This
    build runs the real stack, so both must be present and equal the installed library __version__ (an
    independent observable). FAILS if a key is missing/None here or disagrees with the library."""
    import mt_metadata
    import mth5
    doc = _build_mtcat(tmp_path)
    _check(doc, SCHEMA)   # additive keys must not break schema conformance
    assert doc.get("mt_metadata_version") == mt_metadata.__version__
    assert doc.get("mth5_version") == mth5.__version__


def test_mtcat_builder_passes_through_lib_versions():
    """Unit-level: mtcat_document folds a supplied lib_vers dict into document-level keys, and defaults
    both to None when not supplied (a --raw/no-stack build) — never crashing, never fabricating."""
    sys.path.insert(0, str(ROOT / "extract"))
    import build_portal as bp
    stations = [(Path("a.edi"), {"survey": "Demo Survey", "ausmt_id": "au.demo-survey.A1", "id": "A1",
                                 "lat": -30.1, "lon": 137.0, "type": "BBMT"})]
    meta = {"Demo Survey": {"org": "UoX", "country": "Australia", "lic": "CC-BY-4.0", "access": "open"}}
    doc = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z",
                           lib_vers={"mt_metadata": "9.9.9", "mth5": "8.8.8"})
    assert doc["mt_metadata_version"] == "9.9.9" and doc["mth5_version"] == "8.8.8"
    doc2 = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z")   # no lib_vers
    assert doc2["mt_metadata_version"] is None and doc2["mth5_version"] is None


def test_mtcat_station_survey_linkage(tmp_path):
    doc = _build_mtcat(tmp_path)
    survey_ids = {s["survey_id"] for s in doc["surveys"]}
    for st in doc["stations"]:
        assert st["survey_id"] in survey_ids, f"orphan station {st['station_id']}"
        assert st["station_id"].startswith("au."), "station_id is an ausmt_id"
    # every survey with stations has a bbox + centroid
    have_stations = {st["survey_id"] for st in doc["stations"]}
    for s in doc["surveys"]:
        if s["survey_id"] in have_stations:
            assert s["bbox"] and s["centroid"], f"{s['survey_id']} missing footprint"


def test_mtcat_builder_unit():
    """mtcat_document is pure and deterministic given a fixed timestamp."""
    sys.path.insert(0, str(ROOT / "extract"))
    import build_portal as bp
    stations = [
        (Path("a.edi"), {"survey": "Demo Survey", "ausmt_id": "au.demo-survey.A1", "id": "A1",
                         "lat": -30.1, "lon": 137.0, "type": "BBMT"}),
        (Path("b.edi"), {"survey": "Demo Survey", "ausmt_id": "au.demo-survey.A2", "id": "A2",
                         "lat": -30.3, "lon": 137.4, "type": "BBMT"}),
    ]
    meta = {"Demo Survey": {"org": "UoX", "country": "Australia", "doi": None,
                            "lic": "CC-BY-4.0", "access": "open"}}
    doc = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z")
    _check(doc, SCHEMA)
    s = doc["surveys"][0]
    assert s["survey_id"] == "demo-survey"
    assert s["bbox"] == {"west": 137.0, "south": -30.3, "east": 137.4, "north": -30.1}
    assert s["centroid"] == {"latitude": -30.2, "longitude": 137.2}
    assert doc["portal"]["generated_at"] == "2026-01-01T00:00:00Z"
    # C7: organisation_ror/raid are additive+optional — absent here, must be null, not missing/crash.
    assert s.get("organisation_ror") is None
    assert s.get("raid") is None


def test_mtcat_builder_emits_org_ror_and_raid_when_declared():
    """C7 task 6: mtcat.schema.json gained additive optional survey fields organisation_ror, raid;
    mtcat_document emits them when the survey's SMETA carries org_ror/raid."""
    sys.path.insert(0, str(ROOT / "extract"))
    import build_portal as bp
    stations = [(Path("a.edi"), {"survey": "Demo Survey", "ausmt_id": "au.demo-survey.A1", "id": "A1",
                                 "lat": -30.1, "lon": 137.0, "type": "BBMT"})]
    meta = {"Demo Survey": {"org": "UoX", "org_ror": "https://ror.org/00892tw58", "country": "Australia",
                            "doi": None, "lic": "CC-BY-4.0", "access": "open",
                            "raid": "https://raid.org/10.12345/AB1234"}}
    doc = bp.mtcat_document(meta, stations, generated_at="2026-01-01T00:00:00Z")
    _check(doc, SCHEMA)
    s = doc["surveys"][0]
    assert s["organisation_ror"] == "https://ror.org/00892tw58"
    assert s["raid"] == "https://raid.org/10.12345/AB1234"
