"""What an EPI-KIT file says about its own remote reference, and what AusMT published instead.

An EPI-KIT EDI states the processing it ran as a machine-readable member of its JSON `>INFO` block:
`"ProcessingType": "RemoteH1"` for a remote-reference solution, `"Single"` for a single-site one.
mt_metadata reads none of it (`transfer_function.processing_type` stays empty for this dialect), and
the free-text scrape looks for the phrase "remote reference", which no EPI-KIT file writes. So every
station in every EPI-KIT package published `processing.remote_reference: false`, including the 751
Roxby Downs files whose own >INFO says RemoteH1: three packages contradicting themselves, the served
custodian bytes saying one thing and the AusMT record beside them saying the opposite.

Measured over the three GSSA EPI-KIT packages, 932 files: `RemoteH1` and `Single` are the only two
values that appear. The mapping states exactly those two and NOTHING else: an unrecognised value
leaves the field to the evidence chain that computes it today, because a value nobody has seen is not
a value to guess the meaning of.

Narrow by the file's own writer stamp. The same JSON block shape appears on files a different program
exported, and those keep the answer they publish today: this seam speaks for EPI-KIT-written files
alone, which is why the corpus products are byte-identical across this change.
"""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIX = HERE / "fixtures" / "epikit"
sys.path[:0] = [str(ROOT), str(ROOT / "extract")]

import _edi_catalog as cat     # noqa: E402
import _ediparse as ep         # noqa: E402
import build_portal            # noqa: E402

REMOTE = FIX / "roxby-info-remote-h1.edi"        # >INFO ProcessingType: RemoteH1
SINGLE = FIX / "roxby-info-single.edi"           # >INFO ProcessingType: Single
PHOENIX = HERE / "real_dialects" / "phoenix_empower_A01.edi"
VULCAN = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
WORKFLOW = ROOT.parent / ".github" / "workflows" / "build-products.yml"


def _text(p: Path) -> str:
    return ep.read_norm(p)


# --------------------------------------------------------------------------------------------
# the mapping
# --------------------------------------------------------------------------------------------

def test_the_two_values_the_corpus_carries_map_to_the_two_answers():
    """RemoteH1 is a remote-reference solution and Single is not. FAILS IF the seam reads neither,
    which is what every EPI-KIT station publishes today."""
    assert cat.epikit_remote_reference(_text(REMOTE)) is True
    assert cat.epikit_remote_reference(_text(SINGLE)) is False


def test_the_declared_values_are_the_enumerated_ones():
    """The vocabulary is a closed list, stated in one place, so widening it is a visible edit rather
    than a regex quietly matching something new."""
    assert cat.EPIKIT_PROCESSING_TYPES == {"remoteh1": True, "single": False}


def test_an_unrecognised_processing_type_leaves_the_field_alone(tmp_path):
    """Absence beats a guess: a value nobody has measured yields None, and the build then answers
    exactly as it does today."""
    work = tmp_path / "unknown.edi"
    work.write_text(REMOTE.read_text(encoding="latin-1").replace('"RemoteH1"', '"RemoteXYZ"'),
                    encoding="latin-1")
    assert cat.epikit_remote_reference(_text(work)) is None


def test_a_file_with_no_processing_type_yields_nothing(tmp_path):
    """The member is optional in the dialect, and its absence is not a claim of single-site."""
    work = tmp_path / "noneat.edi"
    work.write_text(re.sub(r'(?m)^\s*"ProcessingType".*$\n', "",
                           REMOTE.read_text(encoding="latin-1")), encoding="latin-1")
    assert cat.epikit_remote_reference(_text(work)) is None


# --------------------------------------------------------------------------------------------
# the boundary: no other dialect's path is touched
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [PHOENIX, VULCAN])
def test_no_other_dialect_reaches_this_seam(path):
    """The negative control. A Phoenix/EMpower spectra file and a plain Geotools-written EDI answer
    None, so their remote-reference facet is decided by exactly what decides it today."""
    assert cat.epikit_remote_reference(_text(path)) is None


def test_the_same_json_from_another_writer_is_left_alone(tmp_path):
    """Measured boundary, and the reason the corpus framing holds: files carrying this JSON block
    shape but stamped by a different exporter exist ON THE CURRENT CORPUS. They keep the answer they
    publish today, and changing that is a curatorial decision about merged packages, not a reader
    fix."""
    work = tmp_path / "geotools.edi"
    work.write_text(REMOTE.read_text(encoding="latin-1").replace(
        'PROGVERS="EPI-KIT 1.2"', 'PROGVERS="Geotools 3.2.6.12508"'), encoding="latin-1")
    assert cat.epikit_remote_reference(_text(work)) is None


# --------------------------------------------------------------------------------------------
# the build: what the station publishes
# --------------------------------------------------------------------------------------------

def _survey(tmp_path, *sources):
    pkg = tmp_path / "surveys" / "rr-probe"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    for src in sources:
        shutil.copy2(src, edir / src.name)
    (pkg / "survey.yaml").write_text(
        "name: Remote Reference Probe\nslug: rr-probe\ncountry: Australia\n"
        "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n", encoding="utf-8")
    return tmp_path / "surveys"


def _stations(out: Path):
    return {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
            for p in (out / "products" / "rr-probe").glob("*/station.json")}


def test_the_published_station_says_what_its_own_file_says(tmp_path):
    """The whole point, over BUILT output. FAILS IF the remote-reference station publishes false,
    which is what all three EPI-KIT packages do today."""
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(_survey(tmp_path, REMOTE, SINGLE)), "--out", str(out),
                              "--products", str(out / "products"),
                              "--bundle-edi", "--no-validate"]) == 0
    docs = _stations(out)
    assert set(docs) == {"603", "119"}, sorted(docs)
    assert docs["603"]["processing"]["remote_reference"] is True
    assert docs["119"]["processing"]["remote_reference"] is False


def test_the_diagnostics_facet_agrees_with_the_processing_facet(tmp_path):
    """The catalogue's science row and the station document read the same value, so a search facet
    and a station page cannot disagree about the same station."""
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(_survey(tmp_path, REMOTE)), "--out", str(out),
                              "--products", str(out / "products"),
                              "--bundle-edi", "--no-validate"]) == 0
    doc = _stations(out)["603"]
    assert doc["diagnostics"]["remote_reference"] is True


def test_a_phoenix_station_publishes_exactly_what_it_did(tmp_path):
    """The negative control end to end. The EMpower spectra file's facet is decided by the evidence
    chain that decided it before: the seam answers None for it (above), so the published value is the
    measured pre-change one, false, and this test is what says so rather than an argument that it
    must be."""
    out = tmp_path / "out"
    assert build_portal.main(["--surveys", str(_survey(tmp_path, PHOENIX)), "--out", str(out),
                              "--products", str(out / "products"),
                              "--bundle-edi", "--no-validate"]) == 0
    docs = _stations(out)
    assert len(docs) == 1
    doc = next(iter(docs.values()))
    assert doc["processing"]["remote_reference"] is False
    assert doc["diagnostics"]["remote_reference"] is False


@pytest.mark.skipif(not WORKFLOW.is_file(),
                    reason="engine image build: workflow tree not shipped "
                           "(designed topology; the CI guards are pinned from the checkout workflows)")
def test_this_file_is_in_the_pr_gate_subset():
    """Rule 8: the PR gate enumerates test files BY NAME, and this one decides a published facet."""
    steps = re.split(r"\n(?=      - name: )", WORKFLOW.read_text(encoding="utf-8"))
    subset = [s for s in steps if "PR gate subset" in s.split("\n")[0]]
    assert len(subset) == 1, [s.split("\n")[0] for s in steps]
    assert f"tests/{Path(__file__).name}" in subset[0]
