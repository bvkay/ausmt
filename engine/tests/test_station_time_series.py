"""Kind=time_series rows on station.json: the archive's bytes, described but never re-hosted.

The engine projects the verified-resource register through the ONE internal model (`station_document`) as
resource rows that carry a ROUTE and nothing local: `access_url` on the canonical NCI fileServer
host, `repository`, the closed `processing_level`/`packaging` vocabularies crosswalked out of the
station concepts, the D19 role axes, and the R9 fieldnote naming the day the CRAWLER read a 200.
There is no `path`, no checksum and no `service_urls`: AusMT hands the reader off, it does not host.

Four gates decide whether a row exists at all, and each is pinned separately because each fails
differently:

  * `review: verified`. A pending row is an ADJUDICATION QUEUE entry, and best-guess attachment
    of a file to a station is silent scientific error; a retired row is evidence of a resource
    that ceased to exist. Neither projects.
  * `level != level2`. NCI's level_2 tree holds transfer functions, not time
    series: seeding them here would assert a verified TIME SERIES for stations that have none. The
    fixture register carries a VERIFIED level2 row so this exclusion is a tested rule and
    not an accident of the corpus.
  * the station is OPEN. A non-served survey's record is the withheld stub, whose key set is
    closed-world; a coordinate-gated station inside a served survey is excluded by the SAME two
    scalars the C42 byte gate ANDs, because its raw time series carries the position the mask
    withholds.
  * a level with nothing verified produces NO row, never a row with a null `access_url`.

NON-VACUOUS: every assertion reads a BUILT document and validates against the shipped 0.1 schema;
every exclusion is asserted beside the inclusion that proves the emitter was able to see the row.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # engine/
REPO = ROOT.parent                                  # the monorepo root, where docs/ lives
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)
TS_INDEX = HERE / "fixtures" / "ts-index"
SCHEMA = json.loads((ROOT / "schema" / "ausmt-station.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
import _stationcheck as stcheck  # noqa: E402
import _tsindex as tsindex  # noqa: E402
import _tsproject as tsproject  # noqa: E402
import build_portal as bp  # noqa: E402

FILESERVER = "https://thredds.nci.org.au/thredds/fileServer/"

# ---------------------------------------------------------------- the blessed docs surface
# The API reference states ts_access.json's stability promise in prose. engine.Dockerfile COPYs
# contract/ + engine/ and one generated portal file, never docs/, so in the engine image this file
# does not exist and the prose legs below skip on the reason ci_check_skips.py already allow-lists
# For that designed topology. On every checkout workflow the docs tree is present and they assert.
API_REFERENCE = REPO / "docs" / "docs" / "interoperability" / "api-reference.md"
DOCS_SKIP_REASON = ("engine image build: docs tree not shipped "
                    "(designed topology; the docs surface is pinned from checkout lanes)")


def _ts_access_docs_section() -> str:
    """The API reference's ts_access.json section alone: from its own heading to the next one."""
    text = API_REFERENCE.read_text(encoding="utf-8")
    m = re.search(r"^### Time-series routes: ts_access\.json$(.*?)(?=^#{1,3} )", text,
                  re.S | re.M)
    assert m, "the API reference no longer carries the blessed ts_access.json section"
    return m.group(1)


def _build(surveys, out, *extra):
    return subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate", *extra],
        cwd=str(ROOT), capture_output=True, text=True)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The vendored corpus built WITH the committed register.

    FAILS against the pre-A2 emitter, which read the register and projected nothing from it."""
    pytest.importorskip("mt_metadata")
    out = tmp_path_factory.mktemp("station-ts") / "data"
    r = _build(SURVEYS, out, "--ts-index", str(TS_INDEX))
    assert r.returncode == 0, r.stderr
    return out


def _station(out, slug, station):
    return json.loads((out / "products" / slug / station / "station.json").read_text(encoding="utf-8"))


def _rows(doc):
    return [r for r in (doc.get("resources") or []) if r.get("kind") == "time_series"]


# ---- the rows ------------------------------------------------------------------------------------

def test_a_verified_row_becomes_a_time_series_resource(built):
    """One row per (station, publishable level), appended after the served renditions so no existing
    row moves."""
    doc = _station(built, "example-survey", "EXAMPLE01")
    ids = [r["id"] for r in doc["resources"]]
    assert ids[:4] == ["edi", "emtfxml", "edi-zip", "xml-zip"], "the existing rows keep their order"
    assert ids[4:] == ["ts-raw_packed", "ts-level0", "ts-level1_mth5"], ids


def test_the_access_url_is_the_absolute_percent_encoded_fileserver_route(built):
    """The C5 fixture: NVP_2019 serves `C5 [REMOTE].zip`, whose encoded form is the only string that
    HEADs 200. A literal space in an emitted route is a dead download."""
    rows = {r["id"]: r for r in _rows(_station(built, "example-survey", "EXAMPLE01"))}
    url = rows["ts-raw_packed"]["access_url"]
    assert url.startswith(FILESERVER), url
    assert url.endswith("/EXAMPLE01%20%5BREMOTE%5D.zip"), url
    assert " " not in url and "[" not in url and "]" not in url


def test_no_row_carries_a_local_path_a_checksum_or_a_service_url(built):
    """AusMT proxies nothing and re-hosts nothing, and OPeNDAP 500s on MTH5 at this archive
    (IMPLEMENTATION:23), so no service is advertised at all."""
    for row in _rows(_station(built, "example-survey", "EXAMPLE01")):
        assert "path" not in row and "sha256" not in row, row
        assert "service_urls" not in row, row


def test_repository_names_the_holder_of_the_bytes(built):
    """The deferral trigger has fired and the crawler knows the host with certainty."""
    assert {r["repository"] for r in _rows(_station(built, "example-survey", "EXAMPLE01"))} == {"NCI"}


def test_the_processing_vocabularies_are_the_schema_enums_crosswalked_out(built):
    """Gate 12 in use: this module is STATION_VOCABULARY_CROSSWALK's first consumer, and the tokens it
    emits come from the clean station vocabulary, never from NCI's level names."""
    levels = SCHEMA["definitions"]["resource"]["properties"]["processing_level"]["enum"]
    packagings = SCHEMA["definitions"]["resource"]["properties"]["packaging"]["enum"]
    rows = {r["id"]: r for r in _rows(_station(built, "example-survey", "EXAMPLE01"))}
    assert rows["ts-raw_packed"]["processing_level"] == "raw"
    assert rows["ts-raw_packed"]["packaging"] == "packed_archive"
    assert rows["ts-level0"]["processing_level"] == "level0"
    assert rows["ts-level1_mth5"]["processing_level"] == "level1"
    assert "packaging" not in rows["ts-level0"], "a single served file omits the field"
    assert all(r["processing_level"] in levels for r in rows.values())
    assert all(r["packaging"] in packagings for r in rows.values() if "packaging" in r)


def test_the_role_axes_follow_the_ratified_D19(built):
    """Packed raw is the custodian's own recording in its original form; the level_0 and level_1
    MTH5 are concatenated/resampled/rotated products of it."""
    rows = {r["id"]: r for r in _rows(_station(built, "example-survey", "EXAMPLE01"))}
    assert (rows["ts-raw_packed"]["provenance_role"],
            rows["ts-raw_packed"]["representation_role"]) == ("source", "original")
    for rid in ("ts-level0", "ts-level1_mth5"):
        assert (rows[rid]["provenance_role"], rows[rid]["representation_role"]) == ("derived", "alternate")


def test_a_station_with_no_published_run_links_to_none(built):
    """Open world: the vendored EDIs assert no acquisition fact, so these stations publish no runs
    and a derived row states no link rather than a null one."""
    doc = _station(built, "example-survey", "EXAMPLE01")
    assert doc.get("runs") in (None, []), "the control for the arm below"
    assert all("derived_from_runs" not in r for r in _rows(doc)), doc["resources"]


@pytest.fixture(scope="module")
def built_with_runs(tmp_path_factory):
    """The same corpus with every EDI given the LEMIMT logger line, so its stations assert one real
    acquisition fact and publish runs[] under their stored ids."""
    pytest.importorskip("mt_metadata")
    import shutil  # noqa: PLC0415
    from test_run_facts import qualify_lemimt  # noqa: PLC0415
    root = tmp_path_factory.mktemp("station-ts-runs")
    staged = root / "surveys"
    shutil.copytree(SURVEYS, staged)
    for package in sorted(p.parent for p in staged.glob("*/survey.yaml")):
        qualify_lemimt(package)
    out = root / "data"
    r = _build(staged, out, "--ts-index", str(TS_INDEX))
    assert r.returncode == 0, r.stderr
    return out


def test_a_derived_row_links_to_the_runs_this_record_publishes(built_with_runs):
    """SCOPE:337-339's case: a concatenated/resampled/rotated product IS derived from the
    acquisition this record publishes, so the link holds wherever the run id exists. The packed
    raw archive is the SOURCE and derives from nothing."""
    doc = _station(built_with_runs, "example-survey", "EXAMPLE01")
    published = [run["id"] for run in doc["runs"]]
    assert published == ["EXAMPLE01-r01"], "non-vacuity: this arm publishes a run"
    rows = {r["id"]: r for r in _rows(doc)}
    assert rows["ts-level0"]["derived_from_runs"] == published
    assert rows["ts-level1_mth5"]["derived_from_runs"] == published
    assert "derived_from_runs" not in rows["ts-raw_packed"], rows["ts-raw_packed"]
    assert stcheck.violations(doc) == [], "the run reference resolves inside its own record"


def test_the_fieldnote_names_the_crawl_and_not_the_build(built):
    """As amended by rule 14 forbids a network call inside the build, so a build cannot
    say it verified anything. The date is the crawler's, carried through unchanged."""
    for row in _rows(_station(built, "example-survey", "EXAMPLE01")):
        assert row["note"] == "verified against NCI THREDDS on 2026-08-24", row


def test_only_the_hand_off_row_states_a_size(built):
    """`manifest.json` is the size and checksum authority for what AUSMT serves, so a served row
    states neither and references its path instead. There IS no manifest row for a file on another
    host, so the hand-off row carries the archive's own figure: that is the only place the fact can
    live, and it restates nothing. It is a size, never a checksum: nothing here re-hashes a remote
    file, so no integrity claim is made about bytes AusMT has not read."""
    doc = _station(built, "example-survey", "EXAMPLE01")
    served = [r for r in doc["resources"] if r["kind"] != "time_series"]
    assert served, "non-vacuity: this station serves renditions of its own"
    assert all(not {"bytes", "size", "sha256"} & set(r) for r in served), served
    rows = {r["id"]: r for r in _rows(doc)}
    assert rows["ts-raw_packed"]["bytes"] == 9868836788
    assert all(not {"size", "sha256"} & set(r) for r in rows.values()), rows


# ---- what never projects -------------------------------------------------------------------------

def test_a_verified_level2_row_projects_nothing(built):
    """The fixture register carries a VERIFIED level2 row, so this is the
    exclusion rule under test and not a corpus that happens to hold no level_2 files."""
    yaml = pytest.importorskip("yaml")
    register = yaml.safe_load((TS_INDEX / "example-survey" / "ts-index.yaml").read_text(encoding="utf-8"))
    seeded = [row for row in register["ts_index"]["EXAMPLE01"]
              if row["level"] == "level2" and row["review"] == "verified"]
    assert seeded, "non-vacuity: the fixture must carry a verified level2 row for this to mean anything"
    doc = _station(built, "example-survey", "EXAMPLE01")
    assert not [r for r in _rows(doc) if r["id"].endswith("level2")], doc["resources"]
    assert seeded[0]["url_path"] not in json.dumps(doc), "no level2 path reaches the document"


def test_a_pending_and_a_retired_row_project_nothing(built):
    """The channel rule and the retired row. EXAMPLE02 carries one of each and nothing else, so its record must carry the
    served renditions alone."""
    doc = _station(built, "example-survey", "EXAMPLE02")
    assert _rows(doc) == [], doc.get("resources")
    assert [r["id"] for r in doc["resources"]] == ["edi", "emtfxml", "edi-zip", "xml-zip"], \
        "sensitivity: EXAMPLE02 is a fully served station, so an empty list here is a decision"


def test_zero_nulls_and_zero_empty_arrays_in_the_new_rows(built):
    """Absence asserts nothing: a level with no verified file produces NO row, never a row with a
    null access_url. Enforced over the WHOLE built tree by the semantic layer this reruns."""
    for path in sorted((built / "products").rglob("station.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert stcheck.violations(doc) == [], path
        for row in _rows(doc):
            assert all(v is not None for v in row.values()), (path, row)
            assert all(v for v in row.values() if isinstance(v, (list, dict))), (path, row)


def test_the_built_documents_validate_against_the_shipped_schema(built):
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft7Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
    seen = 0
    for path in sorted((built / "products").rglob("station.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        validator.validate(doc)
        seen += len(_rows(doc))
    assert seen, "non-vacuity: the arm published time_series rows"


# ---- the access gate -----------------------------------------------------------------------------

def _c42():
    import test_coord_access as c42  # noqa: PLC0415
    return c42


def _register_for(root, package, station_ids):
    """One verified raw_packed row per station, so any exclusion below is the GATE's doing and never
    a missing register row."""
    yaml = pytest.importorskip("yaml")
    (root / package).mkdir(parents=True, exist_ok=True)
    (root / package / "ts-index.yaml").write_text(yaml.safe_dump({"ts_index": {
        sid: [{"level": "raw_packed", "url_path": f"my80/AuScope/Sweep/{sid}.zip",
               "filename": f"{sid}.zip", "bytes": 1042000000, "modified": "2026-03-26T00:04:25Z",
               "verified": "2026-08-24", "match_method": "exact", "review": "verified"}]
        for sid in station_ids}}), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def built_masked(tmp_path_factory):
    """One exact, one generalised and one withheld-position station in ONE open survey, each with a
    verified register row, built by the C42 stager."""
    pytest.importorskip("mt_metadata")
    c42 = _c42()
    root = tmp_path_factory.mktemp("station-ts-masked")
    surveys = root / "surveys"
    surveys.mkdir()
    c42._stage_survey(surveys, [c42.EXACT, c42.GEN, c42.HID])
    index = _register_for(root / "ts-index", "sweep-survey",
                          [c42.EXACT["id"], c42.GEN["id"], c42.HID["id"]])
    out = root / "data"
    r = _build(surveys, out, "--ts-index", str(index))
    assert r.returncode == 0, r.stderr
    return out


def test_a_coordinate_gated_station_gets_no_route(built_masked):
    """The access gate, reusing the SAME two scalars the byte gate ANDs rather than a parallel check: a
    generalised or position-withheld station's raw time series carries the position the mask
    withholds, so it is excluded even though its survey is open and its register row is verified."""
    c42 = _c42()
    docs = {json.loads(p.read_text(encoding="utf-8"))["station"]: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((built_masked / "products").rglob("station.json"))}
    assert len(_rows(docs[c42.EXACT["id"]])) == 1, "non-vacuity: the exact station DOES get its route"
    for station in (c42.GEN["id"], c42.HID["id"]):
        assert _rows(docs[station]) == [], docs[station].get("resources")


# --- ts_access.json, the route-detail boot artifact ------------------------------------------

def _ts_access(out):
    """The emitted artifact, or None when the build wrote none (which is itself an assertion)."""
    path = out / "ts_access.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_ts_access_carries_bytes_and_url_path_per_open_station_and_level(built):
    """`{ausmt_id: {level: {bytes, url_path}}}`. station.json is never fetched on navigation
    (build_portal:5369-5370), so this is the only artifact that can carry the archive's route into a
    manifest the portal builds. `url_path` is the archive's own string VERBATIM, which is the
    form that identifies the file; the encoding happens where it becomes a URL, never in storage."""
    doc = _ts_access(built)
    assert doc, "the fixture register projects three routes, so the artifact must exist"
    aid = _station(built, "example-survey", "EXAMPLE01")["ausmt_id"]
    assert set(doc[aid]) == {"raw_packed", "level0", "level1_mth5"}, doc[aid]
    assert doc[aid]["raw_packed"] == {
        "bytes": 9868836788,
        "url_path": "my80/AuScope_MT_collection/AuScope_Broadband/Example_Survey/"
                    "Packed_Raw_Time_Series_Archive/EXAMPLE01 [REMOTE].zip"}, doc[aid]["raw_packed"]


def test_ts_access_and_the_resource_rows_are_ONE_projection(built):
    """The parity that makes the artifact safe to publish: for every station, the levels here are
    exactly the `ts-<level>` rows in that station's own record, and each states the SAME bytes and
    the SAME route. Two renderings of one predicate, so the manifest a reader downloads cannot name
    a file the record does not describe (nor the reverse)."""
    doc = _ts_access(built)
    seen = 0
    for path in sorted((built / "products").rglob("station.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        rows = {r["id"][len("ts-"):]: r for r in _rows(record)}
        entry = doc.get(record.get("ausmt_id"), {})
        assert set(entry) == set(rows), (path, sorted(entry), sorted(rows))
        for level, row in rows.items():
            assert entry[level].get("bytes") == row.get("bytes"), (path, level)
            assert stcheck.ts_access_url(entry[level]["url_path"]) == row["access_url"], (path, level)
            seen += 1
    assert seen, "non-vacuity: this corpus publishes hand-off rows"


def test_ts_access_holds_the_blessed_row_shape_and_the_additive_rule(built):
    """The STABILITY PROMISE, pinned as its letter rather than as prose.

    ts_access.json is served at /data/ts_access.json and /data/products/ts_access.json and is now a
    stable surface: `url_path` rides every row and is relative to the NCI THREDDS fileServer root,
    `bytes` rides every row whose register entry states a size, and evolution is ADDITIVE ONLY. New
    levels and new per-level keys may appear; neither promised key may change type, `url_path` may
    never leave a row, and absence of a station or a level means no verified route rather than an
    unknown one.

    `bytes` is stated CONDITIONALLY on purpose, because that is what the emitter guarantees. The
    register tolerates a row with no size (_tsindex._row checks the figure only when it is present,
    and the surveys validator mirrors that rule verbatim by design, so requiring it here would make
    the engine stricter than ratified and hard-stop a build on a register surveys CI passed green),
    and _tsproject.route_rows omits the key rather than inventing a zero. Suppressing the whole route
    instead is worse than a missing figure: route_rows also feeds the front door's /go/ts table
    (deploy/scripts/gen_ts_routes.py, which reads only url_path), so a size-less row would cost the
    reader a working download. test_ts_projection.test_route_rows_carry_url_path_and_bytes_per_live_level
    is the negative pin over that emitter answer; this one holds the published surface to it.

    Two legs, because a consumer can be broken from either side. The row leg reads every value dict in
    the BUILT artifact and requires url_path always, bytes with its promised type wherever it appears,
    and a non-vacuity that this fixture's rows do carry both. The identity leg requires every key to
    be an ausmt_id the same build published in mtcat.json, so the file can never name a station the
    catalogue does not carry. The PROSE half is the sibling below, which needs no build and skips in
    the image where docs/ is not shipped; both legs here assert on every topology."""
    doc = _ts_access(built)
    assert doc, "non-vacuity: the fixture register projects routes, so the artifact must exist"
    sized = 0
    for aid, levels in doc.items():
        assert isinstance(levels, dict) and levels, (aid, levels)
        for level, row in levels.items():
            assert isinstance(row, dict), (aid, level, row)
            assert "url_path" in row, (aid, level, sorted(row))
            assert isinstance(row["url_path"], str) and row["url_path"], (aid, level)
            assert not row["url_path"].startswith(("/", "http://", "https://")), (
                f"{aid}/{level}: url_path is relative to the fileServer root, got {row['url_path']}")
            if "bytes" in row:
                sized += 1
                assert isinstance(row["bytes"], int) and not isinstance(row["bytes"], bool) \
                    and row["bytes"] > 0, (aid, level, row["bytes"])
    assert sized, "non-vacuity: this register states sizes, so the built rows must carry them"
    catalogue = json.loads((built / "mtcat.json").read_text(encoding="utf-8"))
    known = {row.get("station_id") for row in (catalogue.get("stations") or [])}
    assert known, "non-vacuity: the catalogue must publish stations to join against"
    assert set(doc) <= known, f"ts_access names stations mtcat does not: {sorted(set(doc) - known)}"


@pytest.mark.skipif(not API_REFERENCE.is_file(), reason=DOCS_SKIP_REASON)
def test_the_blessed_docs_section_promises_what_the_emitter_guarantees():
    """The PROSE half of the blessing, held to the emitter rather than left to age on its own.

    A stability promise is only as good as the weakest statement of it, and the weakest one is the
    sentence a third party reads. That sentence said every row carries at least `bytes` and
    `url_path`. Nothing enforced the `bytes` half at any layer: _tsindex._row validates the figure
    only when it is present, _tsproject.route_rows omits the key when the register states no size,
    and _stationcheck._TS_REQUIRED does not name it either, so a validator-green curator edit could
    publish a document that broke its own published contract with no gate firing. Latent rather than
    live (all 1,671 verified rows in today's corpus carry a size), which is exactly the kind of debt
    a pin exists to hold still.

    Making the register demand the figure was the other way out and is the wrong one twice over: the
    surveys validator mirrors the engine's row reader verbatim BY DESIGN and states that absence
    stays silent, so an engine that refused would be stricter than ratified and would hard-stop a
    build on a register surveys CI passed green; and route_rows also feeds the front door's /go/ts
    table, which reads only url_path, so suppressing a size-less route would cost a reader a working
    download over a missing number. The prose moved to the truth instead.

    The level-token leg is the same debt in the other enumerated fact. The section listed the four
    tokens as a closed set one paragraph above the one promising that new tokens may appear, and no
    pin read the list at all: the B0 pin asserts row shape and the mtcat identity join and never the
    names. So the one enumerated fact on a surface blessed as third-party-stable could go stale in
    silence the next time a level was added. The list is now read out of the emitter's own
    vocabulary rather than restated here, which is what makes the sentence self-maintaining.

    FAILS IF the unconditional promise returns, if the conditional wording stops naming the register
    as the condition, if the enumeration goes back to reading as closed, if a publishable level
    token stops being named, or if the never-projecting one stops being named as excluded. Skipped
    only where the docs tree is not shipped (the engine image); asserted on every checkout workflow."""
    section = _ts_access_docs_section()
    assert "`url_path`" in section, "the blessed section must still name the key it always carries"
    assert not re.search(r"[Ee]very row carries at least `bytes`", section), (
        "the section promised `bytes` unconditionally, which the emitter does not guarantee and "
        "nothing enforces: a validator-green register row with no size publishes a row without the "
        "key, so the promise would be broken by a curator edit with no gate firing")
    assert re.search(r"`bytes`[^.]*\bwhere(?:ver)? the register\b", section), (
        "the section must state `bytes` as conditional on the register carrying the figure, in the "
        "same terms the emitter uses")

    # The vocabulary, read from the emitter: every register level minus the ones that never project.
    publishable = [lv for lv in tsindex.LEVELS if lv not in tsproject.NEVER_PROJECTS]
    assert publishable, "non-vacuity: some register level must be publishable"
    for level in publishable:
        assert f"`{level}`" in section, (
            f"the blessed section must name the level token {level!r} it can publish; the "
            f"enumeration is the one fact on this surface a reader cannot check against the "
            f"document, so a token added to the emitter and not to the prose is a stale promise")
    for level in tsproject.NEVER_PROJECTS:
        assert f"`{level}`" in section, (
            f"the section must keep saying that {level!r} never appears; a reader who finds the "
            f"token in the register and not in this list has no way to learn it is excluded")
    assert not re.search(r"[Tt]he\s+level\s+tokens\s+are\b", section), (
        "the section stated the four tokens as a closed set in the paragraph before the one "
        "promising new tokens may appear; the enumeration is a snapshot of today's vocabulary and "
        "must read as one")


def test_a_station_whose_rows_never_project_is_absent_not_empty(built):
    """EXAMPLE02 carries one pending and one retired row and nothing else. An empty object would
    read as a station with a published-but-empty route set; absence asserts nothing."""
    doc = _ts_access(built)
    assert _station(built, "example-survey", "EXAMPLE02")["ausmt_id"] not in doc, doc


def test_the_artifact_lands_beside_coord_policy_and_in_the_prod_twin(built):
    """Same two write sites as coord_policy.json, byte-identical, because `--products` is a served
    root in deployment and a boot artifact that exists at only one of them is a 404 waiting."""
    twin = built / "products" / "ts_access.json"
    assert twin.exists(), "the prod/ twin is missing"
    assert twin.read_bytes() == (built / "ts_access.json").read_bytes()


def test_a_build_with_no_register_writes_no_artifact_at_all(tmp_path):
    """The zero-change default the boot-artifact precedent promises (:5368-5380): a corpus with no
    verified routes is byte-identical to one built before this artifact existed."""
    pytest.importorskip("mt_metadata")
    out = tmp_path / "data"
    r = _build(SURVEYS, out)
    assert r.returncode == 0, r.stderr
    assert _ts_access(out) is None
    assert not (out / "products" / "ts_access.json").exists()


def test_a_coordinate_gated_station_is_absent_from_the_artifact(built_masked):
    """Stated in the artifact: suppression lives in RESOLUTION, so a masked station is not in the
    file at all. Membership IS the guard here - the shape carries route detail by design."""
    c42 = _c42()
    ids = {json.loads(p.read_text(encoding="utf-8"))["station"]:
           json.loads(p.read_text(encoding="utf-8"))["ausmt_id"]
           for p in sorted((built_masked / "products").rglob("station.json"))}
    doc = _ts_access(built_masked)
    assert ids[c42.EXACT["id"]] in doc, "non-vacuity: the exact station DOES publish its route"
    for station in (c42.GEN["id"], c42.HID["id"]):
        assert ids[station] not in doc, doc


@pytest.fixture(scope="module")
def built_embargoed(tmp_path_factory):
    pytest.importorskip("mt_metadata")
    c42 = _c42()
    root = tmp_path_factory.mktemp("station-ts-embargo")
    surveys = root / "surveys"
    surveys.mkdir()
    pkg = c42._stage_survey(surveys, [c42.EXACT], declare_policy=False)
    yaml_path = pkg / "survey.yaml"
    yaml_path.write_text(yaml_path.read_text(encoding="utf-8").replace(
        "  level: open", "  level: embargoed\n  embargo_until: \"2099-01-01\""), encoding="utf-8")
    index = _register_for(root / "ts-index", "sweep-survey", [c42.EXACT["id"]])
    out = root / "data"
    r = _build(surveys, out, "--ts-index", str(index))
    assert r.returncode == 0, r.stderr
    return out


def test_an_embargoed_survey_publishes_the_withheld_stub_and_no_route(built_embargoed):
    """Structural twice over: the register rows are never captured for a non-served survey, and the
    withheld branch's key set is closed-world and holds no `resources` at all."""
    docs = [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((built_embargoed / "products").rglob("station.json"))]
    assert docs, "non-vacuity: the embargoed survey still publishes a discovery record"
    for doc in docs:
        assert doc.get("withheld") is True, doc
        assert "resources" not in doc, doc
        assert set(doc) <= stcheck.WITHHELD_KEYS, sorted(set(doc) - stcheck.WITHHELD_KEYS)


def test_an_embargoed_survey_writes_no_ts_access_at_all(built_embargoed):
    """The whole corpus is embargoed here, so the artifact has nothing to say and is not written:
    the same only-when-it-carries-information rule coord_policy.json follows."""
    assert _ts_access(built_embargoed) is None


# ---- the emitter, as a unit ----------------------------------------------------------------------

VERIFIED = {"level": "raw_packed", "url_path": "my80/AuScope/X/A1.zip", "filename": "A1.zip",
            "bytes": 12, "verified": "2026-08-24", "match_method": "exact", "review": "verified"}
PRODUCT_DOI = {"scheme": "DOI", "identifier": "10.25914/bzd5-n780", "identifies": "raw_packed"}
COLLECTION_DOI = {"scheme": "DOI", "identifier": "10.25914/zhb7-3e78", "identifies": "collection"}


def test_a_containing_identifier_rides_only_the_level_whose_product_it_names():
    """The AusLAMP SA raw_packed product DOI names the packed raw product, so it places on the
    packed raw row and on nothing else. A survey-scope collection DOI places on no time-series row
    at all: it identifies the collection, not this product, and a route field is the last place a
    reader should have to work out which."""
    rows = bp.station_resources({}, [PRODUCT_DOI, COLLECTION_DOI], [VERIFIED])
    assert [r["id"] for r in rows] == ["ts-raw_packed"]
    assert rows[0]["related_collection_identifiers"] == [PRODUCT_DOI]
    other = bp.station_resources({}, [PRODUCT_DOI], [{**VERIFIED, "level": "level0"}])
    assert "related_collection_identifiers" not in other[0], other[0]


def test_a_survey_with_no_placeable_identifier_emits_no_empty_array():
    rows = bp.station_resources({}, [], [VERIFIED])
    assert "related_collection_identifiers" not in rows[0], rows[0]


def test_the_rows_are_emitted_in_the_level_order_the_table_declares():
    """Two registers listing one station's levels in different orders produce identical documents:
    the emitter iterates its own table, never the file."""
    forward = [VERIFIED, {**VERIFIED, "level": "level0"}, {**VERIFIED, "level": "level1_mth5"}]
    assert ([r["id"] for r in bp.station_resources({}, [], forward)]
            == [r["id"] for r in bp.station_resources({}, [], list(reversed(forward)))]
            == ["ts-raw_packed", "ts-level0", "ts-level1_mth5"])


def test_the_level_tokens_are_derived_from_the_crosswalk_and_exclude_level2():
    """The route table's vocabulary keys ARE crosswalk keys, so a level added to the crosswalk
    cannot be silently unroutable here; level2 is absent by rule, not by omission."""
    assert set(bp._TS_LEVEL_ROUTE) == {"raw_packed", "level0", "level1_mth5", "level1_netcdf"}
    assert "level2" not in bp._TS_LEVEL_ROUTE, "D19: level_2 holds transfer functions, not time series"
    assert {v["vocab"] for v in bp._TS_LEVEL_ROUTE.values()} <= set(bp.STATION_VOCABULARY_CROSSWALK)


def test_a_run_link_is_published_only_where_the_run_is():
    derived = bp.station_resources({}, [], [{**VERIFIED, "level": "level1_mth5"}], ["A1-r01"])
    assert derived[0]["derived_from_runs"] == ["A1-r01"]
    assert "derived_from_runs" not in bp.station_resources({}, [], [VERIFIED], ["A1-r01"])[0], \
        "the packed raw archive IS the source; it derives from nothing"


def test_the_route_prefix_is_stated_once_and_read_by_both_ends():
    """The emitter and the semantic layer read ONE constant AND ONE ENCODER, so neither the
    canonical host nor the escaping can drift between what is published and what is checked. The
    full escape contract is pinned against the shared vector file (tests/test_ts_url_vectors.py),
    which the portal's JS mirror and the front door's generator are held to as well."""
    assert stcheck.ts_access_url("a/b c.zip") == stcheck.TS_ACCESS_PREFIX + "a/b%20c.zip"
    assert stcheck.TS_ACCESS_PREFIX == FILESERVER
