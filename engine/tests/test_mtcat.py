"""MTCAT emission (2.0 semantics; the field-level 2.0 pins live in test_mtcat20_emission.py).

The build emits mtcat.json — the portal-owned discovery document other portals could harvest.
This validates structure against engine/schema/mtcat.schema.json with a dependency-free checker (jsonschema
is optional; a small recursive validator keeps the core test suite stdlib-only) and confirms the
required Portal / Survey / Station objects are populated from real data.

Covered here: the DERIVED per-survey discovery facets reconcile with the stations[] and manifest the
same build wrote, the legacy top-level tool-version keys stay GONE (removed in 2.0), and the version
the portal block stamps is the one the single-source constant declares (the full cross-surface pin
lives in test_mtcat_version_parity.py).
"""
import json
import re
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
# The MTCAT version these tests expect a build to stamp, read off the schema's own title (its single
# source) rather than typed here. A literal would be a fifth copy of the value, and copies of this
# particular value are what test_mtcat_version_parity.py exists to prevent; that module holds the
# cross-surface pin, these two assertions just check the BUILD agrees.
SCHEMA_VERSION = re.match(r"^MTCAT v(\d+\.\d+):", SCHEMA["title"]).group(1)


def _check(node, schema, path="$"):
    """Minimal draft-07 subset validator: type, required, const, enum, pattern, items, properties.

    MTCAT 1.2 pins the vocabularies (name_type, contributor role, identifier_type, relation,
    identifies, the station band) with `enum`, so this stdlib checker learns `enum` too: without it every
    _check call in this file would silently pass an out-of-vocabulary token through, and the vocab pins
    would only ever be enforced where jsonschema happens to be installed. `integer` is honoured as a
    distinct type for the same reason (a stringified count must not pass as a number)."""
    import re
    t = schema.get("type")
    types = t if isinstance(t, list) else ([t] if t else None)
    if types:
        ok = any(
            (ty == "object" and isinstance(node, dict)) or
            (ty == "array" and isinstance(node, list)) or
            (ty == "string" and isinstance(node, str)) or
            (ty == "integer" and isinstance(node, int) and not isinstance(node, bool)) or
            (ty == "boolean" and isinstance(node, bool)) or
            (ty == "number" and isinstance(node, (int, float)) and not isinstance(node, bool)) or
            (ty == "null" and node is None)
            for ty in types)
        assert ok, f"{path}: expected {types}, got {type(node).__name__}"
    if "const" in schema:
        assert node == schema["const"], f"{path}: expected const {schema['const']}"
    if "enum" in schema:
        assert node in schema["enum"], f"{path}: {node!r} is not in the declared vocab {schema['enum']}"
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


def _build_data_dir(tmp_path, *extra):
    """A build with the distribution flags on, so the download manifest is populated and the MTCAT
    `formats` facet has something real to derive from. Returns the output dir."""
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--no-validate", *extra],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def test_mtcat_emitted_and_valid(tmp_path):
    doc = _build_mtcat(tmp_path)
    _check(doc, SCHEMA)
    assert doc["portal"]["portal_id"] == "ausmt"
    assert doc["portal"]["schema"] == "mtcat"
    assert doc["portal"]["version"] == SCHEMA_VERSION   # the version the served schema declares
    assert doc["surveys"], "at least one survey"
    assert doc["stations"], "at least one station"


def test_portal_config_omitting_schema_version_still_stamps_the_current_version(tmp_path):
    """A readable portal config that OMITS portal.schema_version must stamp the version the served
    schema declares, not a stale one.

    build_portal must not carry THREE independent literal defaults for this single value: the
    no-config/unreadable-config default in load_portal_config, its parsed-config default, and the
    emitter's own p.get fallback. All three now read MTCAT_SCHEMA_VERSION, generated from the schema's
    own title, so the value has one home; engine/tests/test_mtcat_version_parity.py pins every surface
    that states it. What is special about THIS path survives the consolidation: this repo's own
    portal.config.yaml declares schema_version explicitly, so a re-used portal (NZMT, CanadaMT, ...)
    shipping a config without the key is the ONLY caller that reads the parsed-config default, and a
    stale one there publishes a wrong version from those portals while AusMT's own build looks correct.

    This drives that path directly: config present, parseable, key absent. The portal_name assertion is
    load-bearing, since it proves the config was actually READ and this is not silently re-testing the
    no-config default."""
    cfg = tmp_path / "portal.config.yaml"
    cfg.write_text('portal:\n  id: ausmt\n  name: "AusMT re-used portal"\n', encoding="utf-8")
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--no-validate", "--portal-config", str(cfg)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    doc = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    assert doc["portal"]["portal_name"] == "AusMT re-used portal", (
        "the config was not read, so this test is not on the path it claims to cover")
    assert doc["portal"]["version"] == SCHEMA_VERSION, (
        "a config that omits portal.schema_version must default to the version the schema declares "
        f"({SCHEMA_VERSION}); got {doc['portal']['version']!r}")


def test_mtcat_derived_facets_agree_with_the_document_they_ride_in(tmp_path):
    """MTCAT 1.2: n_stations / data_types / period range / tipper count are DERIVED, so on a real build
    they must reconcile EXACTLY with this document's own stations[] and with the positional catalogue the
    same build wrote. A drift between the survey summary and the station rows is the failure this pins;
    it is also the reason the summary is safe to publish at all."""
    out = _build_data_dir(tmp_path)
    doc = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    _check(doc, SCHEMA)
    by_survey = {}
    for st in doc["stations"]:
        by_survey.setdefault(st["survey_id"], []).append(st)
    # catalogue rows are positional: id, survey, lat, lon, period_min_s, period_max_s, ..., comps(7)
    cat_by_ausmt = {row[12]: row for row in cat}
    for s in doc["surveys"]:
        rows = by_survey.get(s["survey_id"], [])
        assert s["n_stations"] == len(rows), f"{s['survey_id']}: n_stations disagrees with stations[]"
        mix = {}
        for st in rows:
            mix[st["data_type"]] = mix.get(st["data_type"], 0) + 1
        assert s["data_types"] == mix, f"{s['survey_id']}: band mix disagrees with stations[]"
        pmins = [cat_by_ausmt[st["station_id"]][4] for st in rows
                 if cat_by_ausmt[st["station_id"]][4] is not None]
        pmaxs = [cat_by_ausmt[st["station_id"]][5] for st in rows
                 if cat_by_ausmt[st["station_id"]][5] is not None]
        # 2.0: a bound with nothing to derive from is OMITTED, never null.
        assert s.get("period_min_s") == (min(pmins) if pmins else None)
        assert s.get("period_max_s") == (max(pmaxs) if pmaxs else None)
        assert s["n_stations_tipper"] == sum(
            1 for st in rows if "T" in (cat_by_ausmt[st["station_id"]][7] or ""))
        assert 0 <= s["n_stations_tipper"] <= s["n_stations"]
    assert sum(s["n_stations"] for s in doc["surveys"]) == len(doc["stations"])


def test_mtcat_formats_match_the_download_manifest(tmp_path):
    """MTCAT 1.2: `formats` states what is ACTUALLY distributed, so on a real build it must equal the
    set of formats the manifest carries for that survey. Derived from the one authority, never declared:
    a survey whose bytes the access/licence gate withholds has no manifest rows and so serves []."""
    out = _build_data_dir(tmp_path, "--bundle-edi", "--survey-h5")
    doc = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    _check(doc, SCHEMA)
    title_of = {s["survey_id"]: s["title"] for s in doc["surveys"]}
    expected = {}
    for row in man["files"] + man["bundles"]:
        expected.setdefault(row["survey"], set()).add(row["format"])
    for s in doc["surveys"]:
        want = sorted(expected.get(title_of[s["survey_id"]], set()))
        if want:
            assert s["formats"] == want, s["survey_id"]
        else:
            # 2.0: a survey with nothing distributed OMITS the key - [] would
            # falsely assert that no formats are KNOWN for withheld holdings.
            assert "formats" not in s, s["survey_id"]
    assert any(s.get("formats") for s in doc["surveys"]), "this build distributes something, so prove it"


def test_mtcat_schema_served_beside_data(tmp_path):
    """FAIR-I: the build copies the MTCAT schema into the data dir and the portal block's schema_url
    points at it (relative), so mtcat.json can be validated without resolving the canonical $id host.
    FAILS against the pre-fix build (no schema file emitted, no schema_url key)."""
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--no-validate"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    doc = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    url = doc["portal"]["schema_url"]
    assert url == "mtcat.schema.json", url
    served = out / url
    assert served.exists(), "schema must be served beside the data"
    # the served copy is the in-tree schema, byte-for-byte
    assert served.read_bytes() == (ROOT / "schema" / "mtcat.schema.json").read_bytes()
    # MTCAT 2.0 $id policy: the build ALSO serves the version-specific immutable route
    # data/schemas/mtcat/<version>/mtcat.schema.json (what the schema's own $id names), byte-identical
    # to the latest-convenience copy. The version segment is the emitted portal.version, no literal.
    versioned = out / "schemas" / "mtcat" / doc["portal"]["version"] / "mtcat.schema.json"
    assert versioned.exists(), "the versioned immutable schema route must be served"
    assert versioned.read_bytes() == served.read_bytes()


def test_mtcat_carries_metadata_license(tmp_path):
    """FAIR-R: the portal block declares the catalogue-metadata licence (CC0-1.0 by default). Distinct
    from per-survey data licences. FAILS against the pre-fix build (no metadata_license key)."""
    doc = _build_mtcat(tmp_path)
    assert doc["portal"]["metadata_license"] == "CC0-1.0"


def test_mtcat_carries_no_top_level_tool_versions(tmp_path):
    """MTCAT 2.0 removed the legacy document-level mt_metadata_version / mth5_version keys (the
    decision register: legacy 1.x, SHOULD NOT be newly adopted, removed from core in 2.0). A real
    stack-backed build must emit NEITHER; the served-tool versions still live in build.json /
    build_provenance.json / manifest.json, which other tests pin."""
    doc = _build_mtcat(tmp_path)
    _check(doc, SCHEMA)
    assert "mt_metadata_version" not in doc
    assert "mth5_version" not in doc


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
    # 2.0: undeclared optional keys are OMITTED (null-as-undeclared is gone).
    assert "organisation_ror" not in s
    assert "raid" not in s
    assert "doi" not in s


def test_mtcat_builder_emits_org_ror_and_raid_when_declared():
    """Task 6: mtcat.schema.json gained additive optional survey fields organisation_ror, raid;
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
