"""THE STATION SCHEMA VERSION HAS ONE SOURCE, AND THIS IS THE PIN THAT KEEPS IT THAT WAY.

The sibling of test_survey_metadata_version_parity.py for the third public contract, station.json.
The machinery is the one the MTCAT workflow learned the hard way and the survey-metadata workflow reused, so
no site ever holds a literal.

SINGLE SOURCE: the STATION_VERSION constant in contract/generate.py. The schema artifact's `title`
DISPLAYS the version ("AusMT Station Metadata <MAJOR.MINOR>[-draft]: ...") and is verified against the
constant by contract/generate.py:station_schema_version(), which also emits STATION_SCHEMA_VERSION
into engine/extract/_contract.py (the generated constant the emitter reads), gated by
`generate.py --check` in both CI workflows.

THIS MODULE reads the version back off every surface that states one, INDEPENDENTLY of the shared
function (its own regex over the generate.py source, so the pin cannot agree with itself vacuously):

  1. contract/generate.py STATION_VERSION                 (the authority, read raw from the source text)
  2. the schema title                                     (the DISPLAY, verified against the constant)
  3. contract/generate.py:station_schema_version()        (the one accessor)
  4. engine/extract/_contract.py                          (the generated engine constant)
  5. the schema $id                                       (the version-specific immutable URI)
  6. a REAL BUILD's served schema routes and every emitted document's `version`
  7. the docs current-version display                     (docs/docs/reference/index.md)

Surface 7 lives in docs/, a tree the engine image does not ship, so that read sits behind the same
designed-topology skip the two sibling parity modules take (allow-listed in tests/ci_check_skips.py).
Everything else ships in the image and asserts there.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # engine/
REPO = ROOT.parent                                  # the ausmt monorepo root
SCHEMA_FILE = ROOT / "schema" / "ausmt-station.schema.json"
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)
DOCS_INDEX = REPO / "docs" / "docs" / "reference" / "index.md"

TITLE_RE = re.compile(r"^AusMT Station Metadata (\d+\.\d+)(-draft)?:")


def _authority() -> str:
    """The version as the SINGLE SOURCE declares it, parsed with this module's own regex over the raw
    source text of contract/generate.py (never via the shared accessor)."""
    src = (REPO / "contract" / "generate.py").read_text(encoding="utf-8")
    m = re.search(r'^STATION_VERSION\s*=\s*"(\d+\.\d+)"', src, flags=re.M)
    assert m, 'contract/generate.py must declare STATION_VERSION = "<MAJOR>.<MINOR>" (the single source)'
    return m.group(1)


def _schema_title_display() -> str:
    title = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["title"]
    m = TITLE_RE.match(title)
    assert m, (f"the schema must display its version in its title as "
               f"'AusMT Station Metadata <MAJOR.MINOR>[-draft]: ...'; got {title!r}")
    return m.group(1)


def _shared_parser() -> str:
    sys.path.insert(0, str(REPO / "contract"))
    import generate                                  # the contract package's one version accessor
    return generate.station_schema_version()


def _generated_engine_constant() -> str:
    sys.path.insert(0, str(ROOT / "extract"))
    import _contract                                 # generated; pure literals, so importing it is cheap
    return _contract.STATION_SCHEMA_VERSION


def _assert_agrees(want: str, stated: dict):
    disagree = {k: v for k, v in stated.items() if v != want}
    assert not disagree, (
        f"the station schema version is {want} per contract/generate.py's STATION_VERSION, but these "
        f"surfaces state something else: {disagree}. Change the constant and the schema's displayed "
        f"title together, then run `python contract/generate.py --write`.")


def test_every_engine_surface_that_states_the_station_version_agrees():
    """Statements 1-4: the authority constant, the schema title display, the one accessor and the
    generated constant. All four ship in the engine image, so the release gate proves the image's
    own coherence."""
    want = _authority()
    _assert_agrees(want, {
        "engine/schema/ausmt-station.schema.json (displayed title)": _schema_title_display(),
        "contract/generate.py station_schema_version()": _shared_parser(),
        "engine/extract/_contract.py STATION_SCHEMA_VERSION": _generated_engine_constant(),
    })


def test_the_accessor_refuses_a_title_that_disagrees_with_the_constant(tmp_path, monkeypatch):
    """The verification is what keeps the pin property: a schema whose displayed title disagrees with
    the constant must fail loudly in the accessor (and therefore in `generate.py --check`), never let
    two version claims ship side by side."""
    sys.path.insert(0, str(REPO / "contract"))
    import generate
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    schema["title"] = "AusMT Station Metadata 9.9-draft: a title that disagrees"
    bad = tmp_path / "ausmt-station.schema.json"
    bad.write_text(json.dumps(schema), encoding="utf-8")
    monkeypatch.setattr(generate, "STATION_SRC", bad)
    with pytest.raises(SystemExit):
        generate.station_schema_version()
    schema["title"] = "Station metadata: a title with no version at all"
    bad.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(SystemExit):
        generate.station_schema_version()


def test_the_schema_id_is_the_versioned_immutable_uri():
    """The $id IS a version surface, the version-specific immutable URI under
    /data/schemas/ausmt-station/<version>/, with the unversioned /data/ausmt-station.schema.json as the
    latest-convenience route. The version segment must equal the single-source constant."""
    schema_id = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["$id"]
    want = (f"https://ausmt.auscope.org.au/data/schemas/ausmt-station/{_authority()}/"
            f"ausmt-station.schema.json")
    assert schema_id == want, f"the schema $id must be the version-specific immutable URI {want}; got {schema_id}"


def test_the_generated_constant_is_not_a_hand_typed_literal_in_the_builder():
    """The class guard of the MTCAT pin, applied to the new constant's name: build_portal.py must read
    STATION_SCHEMA_VERSION from _contract and never park a MAJOR.MINOR literal beside it."""
    src = (ROOT / "extract" / "build_portal.py").read_text(encoding="utf-8")
    hits = re.findall(r"STATION[A-Z_]*[^\n]{0,60}?[\"']\d+\.\d+[\"']", src)
    assert not hits, f"a station version literal sits beside the constant's name in build_portal.py: {hits}"
    assert "STATION_SCHEMA_VERSION" in src, "the builder must read the generated constant"


# ---------------------------------------------------------------- the served routes and documents

def _build(tmp_path):
    # --products INSIDE --out, the arrangement deploy/Makefile puts in place, so the version read below
    # is taken off the documents the deployment actually serves.
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--products", str(out / "products"), "--no-validate"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def test_a_real_build_serves_the_schema_at_both_routes_and_stamps_the_version(tmp_path):
    """Statement 6, the surface a consumer actually fetches: the build serves the schema at the
    immutable versioned route and the latest route, byte-identical to the in-tree artifact, and every
    emitted station.json carries the single-source version."""
    pytest.importorskip("mt_metadata")
    out = _build(tmp_path)
    want = _authority()
    in_tree = SCHEMA_FILE.read_bytes()
    latest = out / "ausmt-station.schema.json"
    versioned = out / "schemas" / "ausmt-station" / want / "ausmt-station.schema.json"
    assert latest.is_file(), "the latest-convenience schema route must be served beside the data"
    assert versioned.is_file(), f"the versioned immutable schema route {versioned} must be served"
    assert latest.read_bytes() == in_tree and versioned.read_bytes() == in_tree
    docs = sorted((out / "products").glob("*/*/station.json"))
    assert docs, "a build over the fixture surveys must emit at least one station.json"
    for d in docs:
        doc = json.loads(d.read_text(encoding="utf-8"))
        assert doc["version"] == want, f"{d} stamps {doc['version']!r}, the schema declares {want!r}"
        assert doc["schema"] == "ausmt-station"


# ---------------------------------------------------------------- the docs display

def _docs_display() -> str:
    m = re.search(r"describes station schema version (\d+\.\d+)", DOCS_INDEX.read_text(encoding="utf-8"))
    assert m, ("could not find the station current-version display ('describes station schema "
               f"version X.Y') in {DOCS_INDEX}")
    return m.group(1)


@pytest.mark.skipif(not DOCS_INDEX.is_file(),
                    reason="engine image build: docs tree not shipped "
                           "(designed topology; the docs surface is pinned from the checkout workflows)")
def test_docs_current_version_display_agrees():
    """Statement 7: the docs reference index states which station schema version the documentation
    describes. Skipped only where the docs tree is not shipped (the engine image)."""
    _assert_agrees(_authority(), {"docs/docs/reference/index.md station display": _docs_display()})
