"""The verified-resource register the build reads offline, and the flag that makes it read one.

R1 puts the register in the survey packages: one row per (survey, product level, station), carrying
the NCI `urlPath` verbatim, because that string cannot be rebuilt from a station id. Rule 14 keeps
the READING offline: the crawler is an out-of-band tool, `--ts-index` names a ROOT of registers the
build consumes as files, and the build itself never reaches the network, so cache.py's
byte-reproducibility invariant survives contact with a remote archive.

Two properties are pinned here and nothing in this file matters more than either:

  * the flag is OPT-IN. A build that does not pass it carries nothing the register could have put
    there, so a deployment that has not wired it sees no change at all.
  * with the flag, the register is validated against the SAME closed vocabularies the surveys
    validator applies (level, review, match_method), and a row naming a station the corpus does not
    publish STOPS the build. A row waved through here publishes bytes as a route a reader follows,
    under an identifier nothing matched them to.

NON-VACUOUS: every rejection is asserted beside the same register with the one offending field
repaired, so a load that failed for an unrelated reason cannot pass as the pin.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # engine/
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)
TS_INDEX = HERE / "fixtures" / "ts-index"           # the committed register root --ts-index reads
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
import _tsindex as tsindex  # noqa: E402

# One well-formed row, so every case below differs from a LOADING register by exactly one field.
GOOD = {"level": "raw_packed", "url_path": "my80/AuScope/Example/EXAMPLE01.zip",
        "filename": "EXAMPLE01.zip", "bytes": 1042000000, "data_size": "1.042 Gbytes",
        "modified": "2026-03-26T00:04:25Z", "verified": "2026-08-24",
        "match_method": "exact", "review": "verified"}


def _register(tmp_path, rows_by_station, slug="example-survey"):
    yaml = pytest.importorskip("yaml")
    root = tmp_path / "ts-index"
    (root / slug).mkdir(parents=True, exist_ok=True)
    (root / slug / tsindex.STORE_NAME).write_text(
        yaml.safe_dump({"ts_index": rows_by_station}, sort_keys=True), encoding="utf-8")
    return root


def _load(tmp_path, rows_by_station, known=("EXAMPLE01", "EXAMPLE02")):
    return tsindex.load(_register(tmp_path, rows_by_station), "example-survey", set(known))


def _build(surveys, out, *extra):
    """--no-validate keeps this lane off the surveys validator: what is under test is the REGISTER
    reader, and the package gate has its own suite."""
    return subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate", *extra],
        cwd=str(ROOT), capture_output=True, text=True)


def _docs(out):
    return {p.relative_to(out).as_posix(): json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((out / "products").rglob("station.json"))}


# ---- the flag ------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def flagless(tmp_path_factory):
    """FAILS against the pre-A1 build_portal only in its flagged sibling below; this arm is the
    control it is measured against."""
    pytest.importorskip("mt_metadata")
    out = tmp_path_factory.mktemp("ts-index-flagless") / "data"
    r = _build(SURVEYS, out)
    assert r.returncode == 0, r.stderr
    return out


def test_the_flag_is_accepted_and_the_register_root_is_read_as_files(tmp_path):
    """FAILS against the pre-A1 build_portal, which does not know --ts-index (argparse exits 2).

    Rule 14 in one assertion: the committed register names an archive host, the build completes, and
    nothing resolved anything - the register is an input file like survey.yaml."""
    pytest.importorskip("mt_metadata")
    r = _build(SURVEYS, tmp_path / "data", "--ts-index", str(TS_INDEX))
    assert r.returncode == 0, r.stderr + r.stdout
    assert (tmp_path / "data" / "catalogue.json").is_file()


def test_a_flagless_build_carries_nothing_the_register_could_have_put_there(flagless):
    """The opt-in pin, over BUILT output: no register-derived row, and no remote route anywhere in
    the served product tree. This holds for the whole lane, not only for the commit that adds it."""
    docs = _docs(flagless)
    assert docs, "non-vacuity: the flagless build wrote station documents"
    for key, doc in docs.items():
        rows = doc.get("resources") or []
        assert not [r for r in rows if r.get("kind") == "time_series"], key
        assert not [r for r in rows if "access_url" in r], key


def test_an_absent_register_for_a_survey_is_not_an_error(tmp_path):
    """A partial register is legal: --ts-index names a ROOT, and a survey with no file under it
    simply projects nothing."""
    assert tsindex.load(_register(tmp_path, {"EXAMPLE01": [GOOD]}), "other-survey", {"X"}) == {}


# ---- the closed vocabularies ---------------------------------------------------------------------

def test_a_well_formed_register_loads_with_its_unknown_row_keys_intact(tmp_path):
    """`data_size` is the archive's own 4-significant-figure string, added to the row shape after the
    first crawl. An unknown row key is TOLERATED and carried, so the register can gain a field
    without every reader having to be taught it in the same commit."""
    loaded = _load(tmp_path, {"EXAMPLE01": [GOOD]})
    assert list(loaded) == ["EXAMPLE01"]
    assert loaded["EXAMPLE01"][0]["data_size"] == "1.042 Gbytes"


@pytest.mark.parametrize("field,value,expect", [
    ("level", "level_1", "level"),
    ("level", "", "level"),
    ("review", "approved", "review"),
    ("review", None, "review"),
    ("url_path", "", "url_path"),
    ("verified", "24/08/2026", "verified"),
    ("verified", "", "verified"),
    ("bytes", -1, "bytes"),
    ("bytes", "1.042 Gbytes", "bytes"),
])
def test_a_row_outside_the_closed_vocabulary_stops_the_load(tmp_path, field, value, expect):
    """The three vocabularies are the surveys validator's, restated in the engine because the build
    must not depend on a sibling checkout. FAILS against the pre-A1 engine, which had no reader."""
    with pytest.raises(tsindex.TsIndexError) as e:
        _load(tmp_path, {"EXAMPLE01": [{**GOOD, field: value}]})
    assert expect in str(e.value), str(e.value)
    assert _load(tmp_path, {"EXAMPLE01": [GOOD]}), "sensitivity: the repaired row loads"


@pytest.mark.parametrize("method", ["exact", "curator", "rule:sa-pad", "rule:j-prefix"])
def test_every_ratified_match_method_loads(tmp_path, method):
    assert _load(tmp_path, {"EXAMPLE01": [{**GOOD, "match_method": method}]})


@pytest.mark.parametrize("method", ["guess", "rule:Not Lower"])
def test_a_malformed_match_method_is_a_curator_warning_and_not_a_build_stop(tmp_path, method):
    """SEVERITY PARITY with the surveys validator, which is the half the vocabulary pin cannot see.

    match_method is PROVENANCE and gates nothing: a row stands or falls on its `review` state, and a
    malformed method costs it only its place in the adjudication queue. The validator says WARNING
    and the ratified FAIL list (S1) does not name the field, so an engine that raised here was
    STRICTER THAN RATIFIED - a register that passed surveys CI green hard-stopped the ausmt build
    (build_portal returns 2 on TsIndexError), which surfaces as a mystery red on a curator's PR.
    The value is carried through verbatim so nothing downstream loses the provenance it does have."""
    loaded = _load(tmp_path, {"EXAMPLE01": [{**GOOD, "match_method": method}]})
    assert loaded["EXAMPLE01"][0]["match_method"] == method, (
        "the row loads AND keeps its stated method; silently normalising it would erase the "
        "curator's own record of how the match was made")


def test_a_retired_row_without_its_dated_reason_stops_the_load(tmp_path):
    """D17: retirement is a dated curator act, not a deletion, and the row stays as evidence
    recording when and why it was withdrawn."""
    with pytest.raises(tsindex.TsIndexError) as e:
        _load(tmp_path, {"EXAMPLE01": [{**GOOD, "review": "retired"}]})
    assert "retired_reason" in str(e.value)
    assert _load(tmp_path, {"EXAMPLE01": [
        {**GOOD, "review": "retired", "retired": "2026-08-24",
         "retired_reason": "the archive removed the file"}]})


def test_two_rows_for_one_station_and_level_stop_the_load(tmp_path):
    """One (station, level) names one file, so a second row leaves nothing able to choose."""
    with pytest.raises(tsindex.TsIndexError) as e:
        _load(tmp_path, {"EXAMPLE01": [GOOD, {**GOOD, "filename": "OTHER.zip"}]})
    assert "raw_packed" in str(e.value)
    assert _load(tmp_path, {"EXAMPLE01": [GOOD, {**GOOD, "level": "level0"}]})


def test_an_unknown_top_level_key_stops_the_load(tmp_path):
    yaml = pytest.importorskip("yaml")
    root = tmp_path / "ts-index"
    (root / "example-survey").mkdir(parents=True)
    (root / "example-survey" / tsindex.STORE_NAME).write_text(
        yaml.safe_dump({"ts_index": {"EXAMPLE01": [GOOD]}, "notes": "hello"}), encoding="utf-8")
    with pytest.raises(tsindex.TsIndexError) as e:
        tsindex.load(root, "example-survey", {"EXAMPLE01"})
    assert "notes" in str(e.value)


def test_a_station_the_survey_does_not_publish_stops_the_load(tmp_path):
    """The loud failure the lane contract names: the register states which remote file belongs to
    which station, so a row nothing in the corpus matches would publish a route under an identifier
    this build never assigned."""
    with pytest.raises(tsindex.TsIndexError) as e:
        _load(tmp_path, {"NOSUCH01": [GOOD]})
    assert "NOSUCH01" in str(e.value)


def test_a_station_the_survey_does_not_publish_stops_the_BUILD(tmp_path):
    """The same rule at the command line: loud, non-zero, and named in the message. A build that
    merely warned would publish the rest of the register as if the bad row had never existed."""
    pytest.importorskip("mt_metadata")
    r = _build(SURVEYS, tmp_path / "out", "--ts-index", str(_register(tmp_path, {"NOSUCH01": [GOOD]})))
    assert r.returncode != 0, r.stdout
    assert "NOSUCH01" in r.stderr, r.stderr
    ok = _build(SURVEYS, tmp_path / "out-ok", "--ts-index", str(TS_INDEX))
    assert ok.returncode == 0, ok.stderr


def test_the_vocabularies_are_the_ratified_tokens():
    """D8's five level tokens, S1's three review states, R10's two match methods plus rule:<name>.
    Restated in the engine, so pin the CONTENT: a silent widening here would let the build project a
    token the surveys validator refuses, and the register is the only record either reads. The two
    copies are reconciled when the vendored validator is resynced (deploy plan, section 7); until
    that lands they live in different repos and this pin is what stands between them."""
    assert tsindex.LEVELS == ("raw_packed", "level0", "level1_mth5", "level1_netcdf", "level2")
    assert tsindex.REVIEW == ("verified", "pending", "retired")
    assert tsindex.MATCH_METHODS == ("exact", "curator")
    assert all(tsindex._MATCH_RULE.match(m) for m in ("rule:sa-pad", "rule:j-prefix", "rule:a1"))
    assert not any(tsindex._MATCH_RULE.match(m)
                   for m in ("rule:Not Lower", "rule:", "rule:with space", "sa-pad", "Rule:x"))
    # CONTENT is only half of it: two readers can hold the same tokens and disagree about what an
    # out-of-vocab value COSTS. The severities are pinned beside the tokens - level and review stop
    # the build, match_method does not - because that is the half that actually differed. The
    # match-method pair is a RECONCILIATION ANCHOR rather than a gate the build applies, which is
    # why its form is asserted here: nothing else in the engine reads it.
