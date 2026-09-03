"""A station the build refused must not clear the deploy gate either.

`source_parse_failures` answers "which FILE did the reader refuse". `stations_dropped` answers the
larger question, "which stations is this corpus NOT publishing", and it carries every drop path the
build has: the convention-gate FAILs, the records with no coordinates or no periods, the MTH5 read
failures, and the parse failures too. Only the first ledger was gated. A station dropped at a gate
therefore reached a green verify and a green swap with nothing standing in its way, which is the same
silence the parse-failure gate was built to end, one ledger over.

The rule these tests pin, and it is the parse-failure file's rule word for word: verify.py FAILs on
any stations_dropped row not named in scripts/stations-dropped-allowed.txt; an entry is
`<survey slug>/<source file name>` with its station and its reason on comment lines above it; a
MISSING allow file is an EMPTY list, never a blanket pass; a build whose survey carries no
stations_dropped list at all predates the field and FAILs, because it cannot vouch for itself; and
--allow-stations-dropped points the gate at another file, exactly as --allow-parse-failures does.

The entries are keyed on the FILE because that is the only identity a curator can act on: the row's
`station` is the id the build settled on BEFORE any station_ids override applies, so for a
third-party release it is neither the file name nor the published id.

The rule-8 pin at the end reads .github/workflows/build-products.yml, which the engine image does
not ship; it skips there on the allow-listed image-topology reason and asserts on every checkout lane.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VERIFY = ROOT / "scripts" / "verify.py"
ALLOW = ROOT / "scripts" / "stations-dropped-allowed.txt"
WORKFLOW = ROOT.parent / ".github" / "workflows" / "build-products.yml"

# The seed, measured over the whole corpus rather than assumed: capricorn-2010's five
# sign-convention FAILs, plus the one row the Roxby Downs 2018 release brings with it.
SEEDED = [
    "capricorn-2010/CP1L05.edi",
    "capricorn-2010/CP2B13.edi",
    "capricorn-2010/CP2L01.edi",
    "capricorn-2010/CP2L02.edi",
    "capricorn-2010/CP2L08.edi",
    "roxby-downs-2018/188_S__2.edi",
]


def _build(out):
    return subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys",
                           str(ROOT / "data"), "--out", str(out), "--bundle-edi", "--no-validate"],
                          cwd=str(ROOT), capture_output=True, text=True)


def _verify(data_dir, allow=None):
    argv = [sys.executable, str(VERIFY), "--data-dir", str(data_dir)]
    if allow is not None:
        argv += ["--allow-stations-dropped", str(allow)]
    return subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True)


def _report(out: Path):
    return json.loads((out / "build_report.json").read_text(encoding="utf-8"))


def _write_report(out: Path, rep):
    (out / "build_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")


@pytest.fixture(scope="module")
def clean_build(tmp_path_factory):
    """One build of the vendored corpus, reused by every case below: each mutates only its own copy
    of build_report.json, which is the document the gate reads."""
    out = tmp_path_factory.mktemp("dropped") / "out"
    r = _build(out)
    assert r.returncode == 0, r.stderr
    return out


def _with_one_drop(clean_build, tmp_path, station="MT99", file="MT99.edi",
                   reason="[sign-convention] BOTH off-diagonal phase medians are out of quadrant"):
    """A copy of the clean build whose report carries one dropped station and nothing else changed."""
    out = tmp_path / "out"
    out.mkdir()
    for src in clean_build.rglob("*"):
        dest = out / src.relative_to(clean_build)
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
    rep = _report(out)
    slug = sorted(rep["surveys"])[0]
    rep["surveys"][slug]["stations_dropped"] = [
        {"station": station, "file": file, "reason": reason}]
    _write_report(out, rep)
    return out, slug


def test_a_clean_build_passes_and_says_the_gate_ran(clean_build):
    """The inertness control: the vendored corpus drops nothing, so the new gate changes nothing
    about a build with no drops, and it says so rather than staying quiet."""
    r = _verify(clean_build)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "stations_dropped: PASS (0 dropped" in r.stdout, r.stdout


def test_a_pass_states_how_many_stations_the_build_actually_dropped(clean_build, tmp_path):
    """A PASS over a build that lost a station must not read like nothing was lost. The allow file
    makes the loss acceptable, not invisible, so the line states the count it let through."""
    out, slug = _with_one_drop(clean_build, tmp_path)
    allowed = tmp_path / "allowed.txt"
    allowed.write_text(f"{slug}/MT99.edi\n", encoding="utf-8")
    r = _verify(out, allow=allowed)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "stations_dropped: PASS (1 dropped" in r.stdout, r.stdout


def test_verify_fails_naming_the_survey_and_the_file(clean_build, tmp_path):
    """R6, the defect itself. FAILS IF the deploy gate blesses a build that dropped a station nobody
    ruled on: that is what it does today, for every drop path the build has."""
    out, slug = _with_one_drop(clean_build, tmp_path)
    r = _verify(out)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "VERIFY: FAIL" in r.stdout, r.stdout
    assert f"{slug}/MT99.edi" in r.stdout, r.stdout


def test_the_row_s_station_is_reported_beside_the_file(clean_build, tmp_path):
    """The station the BUILD wrote is echoed, not re-derived: for a third-party release it is neither
    the file name nor the published id, and a curator matching a finding to a row needs both."""
    out, _slug = _with_one_drop(clean_build, tmp_path, station="188", file="188_S__2.edi")
    r = _verify(out)
    assert r.returncode != 0
    assert "188_S__2.edi" in r.stdout and "188" in r.stdout, r.stdout


def test_the_curator_can_allow_a_named_file_and_only_that_file(clean_build, tmp_path):
    """The escape hatch, and its limit. A file written into the allow file passes; the same build with
    a DIFFERENT file allowed still fails, so the allow file cannot be a blanket."""
    out, slug = _with_one_drop(clean_build, tmp_path)
    allowed = tmp_path / "allowed.txt"
    allowed.write_text(f"# curator ruling, with its reason\n{slug}/MT99.edi\n", encoding="utf-8")
    r = _verify(out, allow=allowed)
    assert r.returncode == 0, r.stdout + r.stderr

    other = tmp_path / "other.txt"
    other.write_text(f"{slug}/not-this-one.edi\n", encoding="utf-8")
    assert _verify(out, allow=other).returncode != 0


def test_a_missing_allow_file_allows_nothing(clean_build, tmp_path):
    """A deployment that has deleted the file must not thereby allow everything: the gate is the
    point, so a missing file is an EMPTY list."""
    out, _slug = _with_one_drop(clean_build, tmp_path)
    assert _verify(out, allow=tmp_path / "not-there.txt").returncode != 0


def test_a_build_predating_the_field_cannot_vouch_for_itself(clean_build, tmp_path):
    """--data-dir validates a report already on disk, which during a rollback can be one an older
    engine wrote. A survey with no stations_dropped list at all FAILs rather than passing by absence."""
    out, slug = _with_one_drop(clean_build, tmp_path)
    rep = _report(out)
    del rep["surveys"][slug]["stations_dropped"]
    _write_report(out, rep)
    r = _verify(out)
    assert r.returncode != 0, r.stdout
    assert "predates" in r.stdout, r.stdout


def test_the_parse_failure_gate_is_unaffected(clean_build, tmp_path):
    """The two ledgers are gated separately, and a drop does not consume the parse-failure allowance:
    a build allowed for its drop still has its own parse-failure gate reporting on itself."""
    out, slug = _with_one_drop(clean_build, tmp_path)
    allowed = tmp_path / "allowed.txt"
    allowed.write_text(f"{slug}/MT99.edi\n", encoding="utf-8")
    r = _verify(out, allow=allowed)
    assert "source_parse_failures: PASS" in r.stdout, r.stdout


def test_the_shipped_allow_file_names_every_row_the_corpus_drops():
    """The LEDGER. Measured over the whole corpus and seeded so the next rebuild does not go red on a
    pre-existing condition: capricorn-2010's five sign-convention FAILs, and the one row the Roxby
    Downs 2018 release brings with it, named ahead of its merge so the corpus PR needs no engine
    change. A seventh entry is a station the corpus stopped publishing, and whoever adds it has to
    come here and say so."""
    assert ALLOW.is_file(), f"{ALLOW} must exist so the default gate has a subject"
    text = ALLOW.read_text(encoding="utf-8")
    entries = [ln.strip() for ln in text.splitlines()
               if ln.strip() and not ln.strip().startswith("#")]
    assert entries == SEEDED, entries
    assert "sign-convention" in text, "every entry carries the reason the build wrote"
    assert '"188"' in text, "the Roxby entry carries the station value the build writes, not its id"


@pytest.mark.skipif(not WORKFLOW.is_file(),
                    reason="engine image build: workflow tree not shipped "
                           "(designed topology; the CI guards are pinned from checkout lanes)")
def test_this_file_is_in_the_pr_gate_subset():
    """Rule 8: the PR gate enumerates test files BY NAME, and this one carries the gate's assertions."""
    steps = re.split(r"\n(?=      - name: )", WORKFLOW.read_text(encoding="utf-8"))
    subset = [s for s in steps if "PR gate subset" in s.split("\n")[0]]
    assert len(subset) == 1, [s.split("\n")[0] for s in steps]
    assert f"tests/{Path(__file__).name}" in subset[0]
