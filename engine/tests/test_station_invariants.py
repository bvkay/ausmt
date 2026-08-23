"""Station invariant suite: the cross-layer proofs over BUILT output, forever.

PERMANENT TEST STAGE (the MTCAT 2.0 rule, inherited by the third public contract): this suite runs on
every later emitter change, so a future feature can never silently break the identity chain, the
build-to-build stability of a published record, the schema routes, the one member the portal drawer
reads, or the CI guard that keeps an email address out of a derived product.

Three layers:

  1. TWO consecutive real builds over the vendored fixture surveys. Proves: catalogue.json and
     surveys.json byte-identical across the two (the promotion touches neither); mtcat.json dict-equal
     minus portal.generated_at; every station.json dict-equal minus provenance.generated, which is the
     only per-build field a same-commit rebuild may move; the schema served at both routes byte-identical
     to the in-tree artifact and across builds; no manifest row names the record.
  2. THE IDENTITY CHAIN (T33): mtcat.json's stations[].station_id set equals the set of published
     ausmt_id values, every ausmt_id is unique, and each record's survey_id joins BOTH the mtcat survey
     row and the survey-metadata.json document beside it. Proven non-vacuous against planted violations.
  3. THE CONSUMER PINS: drawer.js reads exactly two members out of station.json and fetches it at the
     contract path, and the CI PII guard greps every tree the build step writes (it greped one of two,
     which left the whole curator products tree unscanned).

Plus the corpus arm (dev box): when AUSMT_STATION_DATA names a full-corpus build output dir, the same
identity and scan checks run over the REAL corpus documents. No CI lane has a corpus, so it skips
there (allow-listed in ci_check_skips.py); it is the lane's full-corpus proof harness.
"""
import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # engine/
REPO = ROOT.parent                                  # the ausmt monorepo root
FIXTURES = HERE / "fixtures"
DRAWER_JS = REPO / "portal" / "src" / "drawer.js"
WORKFLOW = REPO / ".github" / "workflows" / "build-products.yml"
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(HERE))

from _contract import STATION_SCHEMA_VERSION  # noqa: E402
from test_station_emission import _build, _docs  # noqa: E402

CORPUS_DATA = os.environ.get("AUSMT_STATION_DATA")
corpus_arm = pytest.mark.skipif(
    not CORPUS_DATA,
    reason="AUSMT_STATION_DATA does not name a built corpus data dir")


# ---------------------------------------------------------------- reference chain implementations

def identity_chain_violations(out: Path) -> list:
    """T33 over a built tree: the station join in both directions, id uniqueness, and the survey_id
    chain into mtcat's survey rows and the survey-metadata document beside each record."""
    docs = _docs(out)
    mtcat = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    catalogued = {s.get("station_id"): s for s in mtcat.get("stations", []) if isinstance(s, dict)}
    surveys = {s.get("survey_id") for s in mtcat.get("surveys", []) if isinstance(s, dict)}
    out_lines = []
    ids = [d.get("ausmt_id") for d in docs.values()]
    if len(ids) != len(set(ids)):
        out_lines.append(f"ausmt_id is not unique corpus-wide: {sorted(i for i in ids if ids.count(i) > 1)}")
    if set(ids) != set(catalogued):
        out_lines.append(f"published ausmt_id set != mtcat stations[].station_id "
                         f"(unlisted: {sorted(set(ids) - set(catalogued))[:5]}; "
                         f"uncatalogued: {sorted(set(catalogued) - set(ids))[:5]})")
    for key, doc in docs.items():
        slug = key.split("/")[0]
        row = catalogued.get(doc.get("ausmt_id"))
        if row is not None and row.get("survey_id") != doc.get("survey_id"):
            out_lines.append(f"{key}: survey_id {doc.get('survey_id')!r} != mtcat's {row.get('survey_id')!r}")
        if doc.get("survey_id") not in surveys:
            out_lines.append(f"{key}: survey_id {doc.get('survey_id')!r} names no catalogued survey")
        sm = out / "products" / slug / "survey-metadata.json"
        if sm.is_file():
            stated = json.loads(sm.read_text(encoding="utf-8")).get("survey_id")
            if stated != doc.get("survey_id"):
                out_lines.append(f"{key}: survey_id {doc.get('survey_id')!r} != survey-metadata's {stated!r}")
    return out_lines


def test_the_identity_chain_checker_detects_its_violations(tmp_path):
    """Guard on the guard: each arm must CATCH its planted violation, or a green chain proves nothing."""
    tree = tmp_path / "planted"
    (tree / "products" / "s1" / "A1").mkdir(parents=True)
    (tree / "products" / "s1" / "A2").mkdir(parents=True)
    doc = {"schema": "ausmt-station", "version": STATION_SCHEMA_VERSION, "ausmt_id": "au.s1.A1",
           "station": "A1", "survey": "S One", "survey_id": "s1"}
    (tree / "products" / "s1" / "A1" / "station.json").write_text(json.dumps(doc), encoding="utf-8")
    (tree / "products" / "s1" / "A2" / "station.json").write_text(
        json.dumps({**doc, "station": "A2", "ausmt_id": "au.s1.A2"}), encoding="utf-8")
    (tree / "products" / "s1" / "survey-metadata.json").write_text(
        json.dumps({"survey_id": "s1"}), encoding="utf-8")

    def _mtcat(stations, surveys=("s1",)):
        (tree / "mtcat.json").write_text(json.dumps(
            {"stations": stations, "surveys": [{"survey_id": s} for s in surveys]}), encoding="utf-8")

    _mtcat([{"station_id": "au.s1.A1", "survey_id": "s1"}, {"station_id": "au.s1.A2", "survey_id": "s1"}])
    assert identity_chain_violations(tree) == [], "the intact chain must hold"
    _mtcat([{"station_id": "au.s1.A1", "survey_id": "s1"}])
    assert identity_chain_violations(tree), "a station missing from mtcat must be caught"
    _mtcat([{"station_id": "au.s1.A1", "survey_id": "other"},
            {"station_id": "au.s1.A2", "survey_id": "s1"}], surveys=("s1", "other"))
    assert identity_chain_violations(tree), "a survey_id disagreeing with mtcat must be caught"
    (tree / "products" / "s1" / "A2" / "station.json").write_text(
        json.dumps({**doc, "station": "A2"}), encoding="utf-8")   # duplicate ausmt_id
    _mtcat([{"station_id": "au.s1.A1", "survey_id": "s1"}])
    assert any("not unique" in v for v in identity_chain_violations(tree)), "a duplicate id must be caught"


# ---------------------------------------------------------------- layer 1: two builds

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """TWO consecutive real builds over the same corpus, into different output dirs."""
    pytest.importorskip("mt_metadata")
    root = tmp_path_factory.mktemp("station-invariants")
    surveys = root / "surveys"
    surveys.mkdir()
    for pkg in ("example-survey", "pid-survey"):
        shutil.copytree(FIXTURES / pkg, surveys / pkg)
    return [_build(surveys, root / tag) for tag in ("one", "two")]


def _minus_generated(doc):
    d = copy.deepcopy(doc)
    d.get("provenance", {}).pop("generated", None)
    return d


def test_catalogue_and_surveys_are_byte_identical_across_builds_and_mtcat_dict_equal(built):
    """The framing invariant's shape between two builds of this tree: the promotion adds a document
    member set and touches neither the catalogue nor the survey projection."""
    for name in ("catalogue.json", "surveys.json"):
        assert (built[0] / name).read_bytes() == (built[1] / name).read_bytes(), name
    a = json.loads((built[0] / "mtcat.json").read_text(encoding="utf-8"))
    b = json.loads((built[1] / "mtcat.json").read_text(encoding="utf-8"))
    a["portal"]["generated_at"] = b["portal"]["generated_at"] = "NORMALISED"
    assert a == b


def test_every_station_document_is_dict_equal_across_builds_minus_generated(built):
    a, b = _docs(built[0]), _docs(built[1])
    assert a and set(a) == set(b)
    for key in a:
        assert _minus_generated(a[key]) == _minus_generated(b[key]), key


def test_the_schema_is_served_at_both_routes_and_is_byte_stable(built):
    in_tree = (ROOT / "schema" / "ausmt-station.schema.json").read_bytes()
    for out in built:
        latest = (out / "ausmt-station.schema.json").read_bytes()
        versioned = (out / "schemas" / "ausmt-station" / STATION_SCHEMA_VERSION
                     / "ausmt-station.schema.json").read_bytes()
        assert latest == in_tree and versioned == in_tree
        assert next(iter(_docs(out).values()))["version"] == STATION_SCHEMA_VERSION
    a = (built[0] / "schemas" / "ausmt-station" / STATION_SCHEMA_VERSION / "ausmt-station.schema.json")
    b = (built[1] / "schemas" / "ausmt-station" / STATION_SCHEMA_VERSION / "ausmt-station.schema.json")
    assert a.read_bytes() == b.read_bytes()


def test_no_manifest_row_names_the_record(built):
    man = json.loads((built[0] / "manifest.json").read_text(encoding="utf-8"))
    rows = man.get("files", []) + man.get("bundles", [])
    assert rows, "the fixture build distributes something, so the manifest is non-empty"
    assert not any("station.json" in json.dumps(r) for r in rows), (
        "station.json is a metadata contract, not a download artifact; it gets no manifest row")


# ---------------------------------------------------------------- layer 2: the identity chain

def test_the_built_corpus_holds_the_identity_chain(built):
    assert identity_chain_violations(built[0]) == []
    assert len(_docs(built[0])) == len(
        json.loads((built[0] / "mtcat.json").read_text(encoding="utf-8"))["stations"])


# ---------------------------------------------------------------- layer 3: the consumer pins

_DRAWER_FN = re.compile(r"function loadStationFrameLine\(s\)\{[\s\S]*?\n\}\n")


@pytest.mark.skipif(not DRAWER_JS.is_file(),
                    reason="engine image build: portal tree not shipped "
                           "(designed topology; the drawer surface is pinned from checkout lanes)")
def test_the_portal_drawer_reads_exactly_two_members_at_the_contract_path():
    """The drawer is UNTOUCHED by the promotion, and this is what keeps it that way in both directions:
    it reads `doc.frame` and `doc.processing.file_written_by` and nothing else, from the served route
    the public-surface audit pins. A promotion that renamed either member, or a drawer that started
    reading `runs` or `location` out of the record, fails here rather than in a browser."""
    body = _DRAWER_FN.search(DRAWER_JS.read_text(encoding="utf-8"))
    assert body, "loadStationFrameLine is gone from drawer.js; the pin has lost its subject"
    text = body.group(0)
    assert set(re.findall(r"doc\.(\w+)", text)) == {"frame", "processing"}, sorted(
        set(re.findall(r"doc\.(\w+)", text)))
    assert "file_written_by" in text, "the writer read is the second of the two members"
    assert '"products/"' in text and '"/station.json"' in text, (
        "the drawer fetches the contract route /data/products/<slug>/<station>/station.json")


def test_the_built_records_carry_both_members_the_drawer_reads(built):
    for key, doc in _docs(built[0]).items():
        if doc.get("withheld"):
            continue                        # the drawer's fetch returns no line for a withheld station
        assert "frame" in doc, f"{key}: the drawer reads doc.frame"
        writer = (doc.get("processing") or {}).get("file_written_by")
        assert isinstance(writer, dict) and set(writer) == {"name", "version"}, f"{key}: {writer!r}"


# The two station-named test files that are NOT part of the promoted contract's family: the survey.yaml
# station-id override and the stations GeoJSON emitter. Both predate the lane and neither gates this
# contract. Naming them is what lets the glob below catch a NEW contract test file that goes unlisted.
_NOT_CONTRACT_FAMILY = {"test_station_ids.py", "test_stations_geojson.py"}


def _workflow_step(name_fragment: str) -> str:
    """One `- name:` step of build-products.yml, by a fragment of its name."""
    steps = re.split(r"\n(?=      - name: )", WORKFLOW.read_text(encoding="utf-8"))
    matches = [s for s in steps if name_fragment in s.split("\n")[0]]
    assert len(matches) == 1, f"{name_fragment!r} matched {len(matches)} steps"
    return matches[0]


@pytest.mark.skipif(not WORKFLOW.is_file(),
                    reason="engine image build: workflow tree not shipped "
                           "(designed topology; the CI guards are pinned from checkout lanes)")
def test_the_ci_pii_guard_greps_every_tree_the_build_writes():
    """D11's second half. The build step writes TWO trees, `--out` and `--products`, and the guard
    greped only the first, so every station.json and dimensionality.json in the curator tree went
    unscanned for the free-text vector the guard exists to catch. The trees are read out of the build
    step's own arguments so this pin cannot drift from what CI actually produces."""
    build = _workflow_step("Build products")
    trees = [re.search(rf"--{flag} (\S+)", build).group(1) for flag in ("out", "products")]
    assert trees == ["site-data", "products"], trees
    guard = _workflow_step("PII guard")
    grep = next(ln for ln in guard.split("\n") if "grep -Rl" in ln)
    for tree in trees:
        assert re.search(rf"(?<![\w/-]){re.escape(tree)}(?![\w/-])", grep), (
            f"the PII guard does not scan {tree!r}: {grep.strip()}")
    assert "--exclude-dir=edi" in guard, "the served original EDI bytes stay out of scope (rule 11)"


@pytest.mark.skipif(not WORKFLOW.is_file(),
                    reason="engine image build: workflow tree not shipped "
                           "(designed topology; the CI guards are pinned from checkout lanes)")
def test_every_station_contract_test_file_is_in_the_pr_gate_subset():
    """Rule 12, mechanised: the PR gate enumerates test files BY NAME, so a station test file that is
    not listed runs only on push to main. Checked over the whole family rather than the file added
    last, because that is the class of gap, not the instance."""
    listed = set(re.findall(r"tests/(test_\w+\.py)", _workflow_step("PR gate subset")))
    ours = {p.name for p in sorted(HERE.glob("test_station*.py"))} - _NOT_CONTRACT_FAMILY
    assert ours, "the glob found no station contract tests; the pin has lost its subject"
    assert ours <= listed, f"not in the PR-gate subset: {sorted(ours - listed)}"


# ---------------------------------------------------------------- the corpus arm (dev box)

@corpus_arm
def test_corpus_documents_hold_the_identity_chain_and_the_schema():
    out = Path(CORPUS_DATA)
    assert identity_chain_violations(out) == []
    docs = _docs(out)
    assert docs, "AUSMT_STATION_DATA names a tree with no station records"
    print(f"corpus arm: {len(docs)} station records, "
          f"{sum(1 for d in docs.values() if d.get('withheld'))} withheld, "
          f"{sum(1 for d in docs.values() if d.get('runs'))} with runs[], "
          f"{sum(1 for d in docs.values() if d.get('resources'))} with resources[]")
