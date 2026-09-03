"""A source file the reader could not open must not clear the deploy gate.

build_report.json has recorded `source_parse_failures` since the GDS readers workflow: which FILE the
reader refused and what it said. Nothing read it. The Roxby Downs 2018 measurement is
what that costs end to end: nine files refused, build exit 0, no SKIP line, the curator preview exit
0, the package validator 0 FAIL, and nine transfer functions absent from a corpus nobody was told
had lost them.

The split these tests pin. The BUILD still exits 0 on a parse failure, because one malformed legacy
file must not take the whole corpus down with it. The VERIFIER is the gate: scripts/verify.py FAILs,
naming the survey and the file, unless the curator has written that file into the allow file, a
reviewed repository artifact that is EMPTY over the whole corpus. That is the same posture the
survey-level D20 loud-skip gate already takes one level up.

The rule-8 pin at the end reads .github/workflows/build-products.yml, which the engine image does
not ship; it skips there on the allow-listed image-topology reason and asserts on every checkout workflow.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VERIFY = ROOT / "scripts" / "verify.py"
ALLOW = ROOT / "scripts" / "parse-failures-allowed.txt"
SAMPLE = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi"
WORKFLOW = ROOT.parent / ".github" / "workflows" / "build-products.yml"


def _survey_with_one_unreadable_file(tmp_path):
    """A package of two real EDIs, one of them given a reference latitude mt_metadata's own validator
    refuses. read_measurement sets reflat unguarded, so the read raises and the station is lost; the
    other station builds normally, which is what makes the build's exit 0 meaningful."""
    pkg = tmp_path / "surveys" / "parse-fail-probe"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    good, broken = sorted(SAMPLE.glob("*.edi"))[:2]
    shutil.copy2(good, edir / good.name)
    text = broken.read_text(encoding="latin-1")
    (edir / broken.name).write_text(re.sub(r"REFLAT=.*", "REFLAT=south", text, count=1),
                                    encoding="latin-1")
    (pkg / "survey.yaml").write_text(
        "name: Parse Fail Probe\nslug: parse-fail-probe\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n", encoding="utf-8")
    return tmp_path / "surveys", broken.name


def _build(surveys, out):
    return subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys),
                           "--out", str(out), "--bundle-edi", "--no-validate"],
                          cwd=str(ROOT), capture_output=True, text=True)


def _verify(data_dir, allow=None, dropped=None):
    """`dropped` is the sibling gate's allow file. A refused source file is BOTH a parse failure and a
    dropped station, and the two ledgers are gated independently, so a curator giving up on a file
    rules in both places; the cases below that mean to exercise the parse-failure gate alone hand the
    drop gate its own entry rather than letting it decide the exit code."""
    argv = [sys.executable, str(VERIFY), "--data-dir", str(data_dir)]
    if allow is not None:
        argv += ["--allow-parse-failures", str(allow)]
    if dropped is not None:
        argv += ["--allow-stations-dropped", str(dropped)]
    return subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True)


def test_the_build_still_exits_zero_and_records_the_refusal(tmp_path):
    """The half that must NOT change: one unreadable legacy file costs its own station, never the
    build. The record is what the gate below reads."""
    surveys, broken = _survey_with_one_unreadable_file(tmp_path)
    out = tmp_path / "out"
    r = _build(surveys, out)
    assert r.returncode == 0, r.stderr
    assert "PARSE FAIL" in r.stderr
    entry = json.loads((out / "build_report.json").read_text(
        encoding="utf-8"))["surveys"]["parse-fail-probe"]
    assert [row["file"] for row in entry["source_parse_failures"]] == [broken]
    assert entry["stations_built"] == 1


def test_verify_fails_naming_the_file_the_reader_refused(tmp_path):
    """The defect itself. FAILS IF the deploy gate blesses a build that silently lost a station:
    that is what it does today, and it is how nine Roxby stations would have reached a green swap."""
    surveys, broken = _survey_with_one_unreadable_file(tmp_path)
    out = tmp_path / "out"
    assert _build(surveys, out).returncode == 0
    dropped = tmp_path / "dropped.txt"
    dropped.write_text(f"parse-fail-probe/{broken}\n", encoding="utf-8")
    r = _verify(out, dropped=dropped)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "VERIFY: FAIL" in r.stdout, r.stdout
    assert "source_parse_failures: FAIL" in r.stdout, r.stdout
    assert broken in r.stdout and "parse-fail-probe" in r.stdout, r.stdout


def test_a_clean_build_still_passes(tmp_path):
    """The inertness control: the vendored corpus reads completely, so the new gate changes nothing
    about a build with no refusals."""
    out = tmp_path / "out"
    assert _build(ROOT / "data", out).returncode == 0
    r = _verify(out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "source_parse_failures: PASS" in r.stdout, r.stdout


def test_the_curator_can_allow_a_named_file_and_only_that_file(tmp_path):
    """The escape hatch, and its limit. A file the curator has written into the allow file passes;
    the same build with a DIFFERENT file allowed still fails, so the allow file cannot be a blanket."""
    surveys, broken = _survey_with_one_unreadable_file(tmp_path)
    out = tmp_path / "out"
    assert _build(surveys, out).returncode == 0

    allowed = tmp_path / "allowed.txt"
    allowed.write_text(f"# curator ruling, with its reason\nparse-fail-probe/{broken}\n",
                       encoding="utf-8")
    r = _verify(out, allow=allowed, dropped=allowed)
    assert r.returncode == 0, r.stdout + r.stderr

    other = tmp_path / "other.txt"
    other.write_text("parse-fail-probe/not-this-one.edi\n", encoding="utf-8")
    assert _verify(out, allow=other, dropped=allowed).returncode != 0


def test_the_shipped_allow_file_is_empty():
    """The allow file is a list of stations the corpus has deliberately given up on, and it is meant
    to be read, not grown. It is EMPTY over the whole corpus: the one entry it ever carried was
    capricorn-2010's CP3B21.edi, whose reference latitude repeats its sign character, and the pre-read
    conditioning now collapses that run on a temporary copy so the station publishes.

    This test is a LEDGER, not a policy: an entry here is a station the corpus stopped publishing, and
    whoever adds one has to come here and say so."""
    assert ALLOW.is_file(), f"{ALLOW} must exist so the default gate has a subject"
    entries = [ln.strip() for ln in ALLOW.read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.strip().startswith("#")]
    assert entries == [], entries


@pytest.mark.skipif(not WORKFLOW.is_file(),
                    reason="engine image build: workflow tree not shipped "
                           "(designed topology; the CI guards are pinned from checkout lanes)")
def test_every_epikit_test_file_is_in_the_pr_gate_subset():
    """Rule 8, mechanised over the family rather than over the file added last: the PR gate enumerates
    test files BY NAME, so an EPI-KIT reader test that is not listed runs only on push to main, and
    the reader seam these files guard is the one that decides which numbers the corpus publishes."""
    steps = re.split(r"\n(?=      - name: )", WORKFLOW.read_text(encoding="utf-8"))
    subset = [s for s in steps if "PR gate subset" in s.split("\n")[0]]
    assert len(subset) == 1, [s.split("\n")[0] for s in steps]
    listed = set(re.findall(r"tests/(test_\w+\.py)", subset[0]))
    ours = {p.name for p in sorted(HERE.glob("test_epikit_*.py"))}
    assert len(ours) == 4, sorted(ours)
    assert ours <= listed, f"not in the PR-gate subset: {sorted(ours - listed)}"
