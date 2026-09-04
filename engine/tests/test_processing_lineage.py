"""LINEAGE PIN: the program that WROTE a transfer-function file is not the program that PROCESSED it.

The portal's lineage graph published "Processing software: Geotools / WinGLink / MTpy" — the EDI HEAD's
PROGVERS, i.e. whatever SERIALISED the file. Measured over the GA AusLAMP holdings, 1743
files carry `PROGVERS="WINGLINK EDI 1.0.22"` and 337 carry `PROGVERS="Geotools 4.0.5.12583"`; none of those
programs estimated a transfer function. The program that did is named ONLY in the >INFO free text
("Processing code: LEMIMT" on 296 of the Geotools files; "processing.software.name = ['Birrp 5.0', ' 5.2']"
on the MTpy-written AusLAMP SA files), which the build never read.

NON-VACUOUS failure criteria — each test states what makes it FAIL:
  * the miner tests fail if a processor named in free text is not recovered, if a version the text carries
    is dropped, or if a writer's own name is returned as a processor without processing evidence;
  * the build tests fail against the PRE-FIX emitter, which wrote processing.software="Geotools
    4.0.5.12583" for a file with no processor evidence, emitted no file_written_by at all, and restated
    the dimensionality call inside station.json's diagnostics.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # engine/
sys.path.insert(0, str(ROOT / "extract"))
import _edi_catalog as cat              # noqa: E402

FIXTURE = HERE / "fixtures" / "example-survey"


# ---------------------------------------------------------------------------------------------
# 1. the vocabulary + the mining, as pure functions
# ---------------------------------------------------------------------------------------------

def test_known_writers_are_matched_as_substrings_and_nothing_else_is():
    """FAILS if a real writer stamp is not recognised (so it would be published as a processor), or if a
    processor name is misclassified as a writer (so it would be suppressed)."""
    for w in ("Geotools 4.0.5.12583", "WINGLINK EDI 1.0.22", "MTpy", "winglink"):
        assert cat.is_known_writer(w), w
    for p in ("LEMIMT", "BIRRP", "EMpower", "Aurora", "", None):
        assert not cat.is_known_writer(p), p


def test_writer_is_split_from_the_header_verbatim():
    """FAILS if the writer name/version split invents, drops or reorders characters the header carries."""
    assert cat.writer_from_text('PROGVERS="Geotools 4.0.5.12583"') == \
        {"name": "Geotools", "version": "4.0.5.12583"}
    assert cat.writer_from_text('PROGVERS="WINGLINK EDI 1.0.22"') == \
        {"name": "WINGLINK EDI", "version": "1.0.22"}
    assert cat.writer_from_text("PROGVERS=MTpy") == {"name": "MTpy", "version": None}
    assert cat.writer_from_text('PROGVERS="EMpower v1.54.2.5"') == \
        {"name": "EMpower", "version": "v1.54.2.5"}
    # PROGNAME, where a dialect writes one, is the name and PROGVERS is then purely the version
    assert cat.writer_from_text('PROGNAME=LEMIMT\nPROGVERS="1.4"') == \
        {"name": "LEMIMT", "version": "1.4"}
    # a header that states neither claims nothing
    assert cat.writer_from_text("LAT=-30.0\nLONG=136.0") == {"name": None, "version": None}


def test_the_processor_is_mined_from_the_info_text_with_its_version():
    """FAILS if the AusLAMP SA / GA free-text forms stop yielding their processor, or if the version token
    the file carries is dropped (the phrase is kept as the file wrote it, never normalised away)."""
    sw, ev = cat.mine_processor("    processing.software.name = ['Birrp 5.0', ' 5.2']", "MTpy")
    assert sw == "Birrp 5.0", sw
    assert "Birrp 5.0" in ev, ev
    sw, ev = cat.mine_processor("  Processing code: LEMIMT\n  Algorithm: Robust Remote Reference", "Geotools")
    assert sw == "LEMIMT", sw
    assert ev == "Processing code: LEMIMT", ev
    assert cat.mine_processor("processed with aurora v0.3.1", "MTpy")[0] == "aurora v0.3.1"
    assert cat.mine_processor("Processed with EMTF (Egbert)", "Geotools")[0] == "EMTF"


def test_no_evidence_yields_no_processor():
    """FAILS if the miner ever answers from the writer's identity instead of the text — the exact
    over-claim this change exists to remove. The WinGLink INFO block below is the real shape of the 1743
    NT/QLD files: it names no processor at all."""
    assert cat.mine_processor("SURVEY ID:AusLAMP_NT\nAREA:AusLAMP_NT_QLD\nROTATION=FIX",
                              "WINGLINK EDI") == (None, None)
    assert cat.mine_processor("", "Geotools") == (None, None)
    assert cat.mine_processor(None, "MTpy") == (None, None)


def test_a_writer_name_echoed_in_the_text_is_not_processing_evidence():
    """FAILS if a known writer's name, appearing in the free text with no processing language, is promoted
    to processor — the same conflation in a different place. WinGLink counts ONLY where the text says it
    processed the data."""
    assert cat.mine_processor("Exported by WinGLink for plotting", "WINGLINK EDI") == (None, None)
    assert cat.mine_processor("data processed in WinGLink", "WINGLINK EDI")[0] == "WinGLink"


def test_distinct_processors_join_in_text_order():
    """FAILS if a multi-stage processing statement collapses to one tool or reorders them."""
    assert cat.mine_processor("Processing: birrp 5.2 then EMTF-FCU", "MTpy")[0] == "birrp 5.2 + EMTF-FCU"
    # a more specific name claims its span: EMTF-FCU is never ALSO reported as a bare EMTF
    assert cat.mine_processor("processed with EMTF-FCU", "Geotools")[0] == "EMTF-FCU"


def test_mtm_stays_importable_by_package_path():
    """FAILS if `_mtm` grows a module-level sibling import. `_mtm` is reached BOTH ways in this tree:
    by bare name (build_portal, which puts extract/ on sys.path) and as `extract._mtm`
    (ausmt_science.ingest.normalize, by package path with engine/ as the root). A module-level
    `import _edi_catalog` resolves under the first and raises ModuleNotFoundError under the second —
    which this test caught while the writer vocabulary was being wired in, because normalize's
    read_with_fallback import and BOTH its fallbacks would then fail for a caller that only wants the
    reader. Run in a subprocess so the check is real: this session already has extract/ on sys.path,
    which would make an in-process import pass vacuously."""
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, '.');"
                        " from extract._mtm import read_with_fallback, proc_info_from_tf"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"extract._mtm is no longer importable by package path:\n{r.stderr}"


class _StubTF:
    """A TF whose structured software block is POPULATED — which no real EDI dialect in the corpus
    gives us (mt_metadata leaves the field empty on all five real-dialect fixtures, measured). Without
    it the writer-leak assertion below would pass on a None and prove nothing."""
    def __init__(self, name, version=None, processing_type=""):
        sw = type("SW", (), {"name": name, "version": version})()
        tfm = type("TFM", (), {"software": sw, "processing_type": processing_type})()
        self.station_metadata = type("SM", (), {"transfer_function": tfm})()


def test_proc_info_from_tf_keeps_its_three_tuple_and_adds_the_writer_on_request():
    """FAILS if the default arity changes — science_from_components unpacks exactly three, positionally
    — or if a populated software block is not split into writer vs processor."""
    pytest.importorskip("mt_metadata")
    import _mtm as mtm                                     # noqa: PLC0415
    p = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
    tf = mtm.read(p)
    assert len(mtm.proc_info_from_tf(tf)) == 3
    full = mtm.proc_info_from_tf(tf, with_writer=True)
    assert len(full) == 4 and set(full[3]) == {"name", "version"}

    # a KNOWN WRITER in the structured field must not become the processor — it becomes the writer
    leak = mtm.proc_info_from_tf(_StubTF("Geotools", "4.0.5.12583"), with_writer=True)
    assert leak[0] is None, f"a known writer leaked into the software slot: {leak[0]!r}"
    assert leak[3] == {"name": "Geotools", "version": "4.0.5.12583"}, leak[3]
    # a program that is NOT a known writer plausibly did process, and stands as the software
    direct = mtm.proc_info_from_tf(_StubTF("LEMIMT", "1.4"), with_writer=True)
    assert direct[0] == "LEMIMT", direct[0]
    assert direct[3] == {"name": "LEMIMT", "version": "1.4"}, direct[3]


# ---------------------------------------------------------------------------------------------
# 2. the emitted product
# ---------------------------------------------------------------------------------------------

def _head_and_info(text, progvers, info_body):
    """Rewrite an EDI's PROGVERS stamp and its whole >INFO body, leaving the data sections untouched."""
    out, in_info = [], False
    for line in text.splitlines():
        if line.startswith("PROGVERS"):
            out.append(f'PROGVERS={progvers}')
            continue
        if line.startswith(">INFO"):
            in_info = True
            out.append(line)
            out.extend(info_body.splitlines())
            continue
        if in_info:
            if line.startswith(">"):
                in_info = False
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def _build(tmp_path):
    """Stage the vendored example survey with two DELIBERATE lineage cases and build --products:
      EXAMPLE01 — MTpy-written, BIRRP named in the free text  (writer != processor)
      EXAMPLE02 — Geotools-written, NO processor evidence     (writer known, processor unknown)"""
    src = tmp_path / "surveys" / "example-survey"
    shutil.copytree(FIXTURE, src)
    edi = src / "transfer_functions" / "edi"
    (edi / "EXAMPLE01.edi").write_text(_head_and_info(
        (edi / "EXAMPLE01.edi").read_text(encoding="utf-8"), "MTpy",
        "    processing.software.name = ['Birrp 5.0', ' 5.2']\n"
        "    processing.processed_by = ['GSSA', ' Uni of Adelaide']\n"), encoding="utf-8")
    (edi / "EXAMPLE02.edi").write_text(_head_and_info(
        (edi / "EXAMPLE02.edi").read_text(encoding="utf-8"), '"Geotools 4.0.5.12583"',
        "SURVEY ID:Example\nAREA:Example\nROTATION=FIX\n"), encoding="utf-8")
    out, prod = tmp_path / "data", tmp_path / "products"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys",
                        str(tmp_path / "surveys"), "--out", str(out), "--products", str(prod),
                        "--no-validate"], cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return prod / "example-survey"


def test_station_json_names_the_processor_and_the_writer_separately(tmp_path):
    """FAILS against the pre-fix emitter, which had no file_written_by key at all and published
    processing.software="Geotools 4.0.5.12583" for EXAMPLE02 — a file whose text names no processor."""
    pytest.importorskip("mt_metadata")
    base = _build(tmp_path)

    one = json.loads((base / "EXAMPLE01" / "station.json").read_text(encoding="utf-8"))["processing"]
    assert one["software"] == "Birrp 5.0", one["software"]
    assert one["file_written_by"] == {"name": "MTpy", "version": None}, one["file_written_by"]
    assert one["software"] != one["file_written_by"]["name"], "writer and processor must not be conflated"

    two = json.loads((base / "EXAMPLE02" / "station.json").read_text(encoding="utf-8"))["processing"]
    assert two["software"] is None, \
        f"a file with no processor evidence must say so, not name its exporter: {two['software']!r}"
    assert two["file_written_by"] == {"name": "Geotools", "version": "4.0.5.12583"}, two["file_written_by"]


def test_station_json_states_the_dimensionality_call_with_its_caveat(tmp_path):
    """The classification and its skew statistic are FOLDED INTO station.json's
    diagnostics, and the method string and the screening caveat travel with them, so the qualification
    is beside the numbers rather than one file away. FAILS against the emitter one commit ago, which
    carried them in dimensionality.json alone; and against a fold that dropped the caveat, which is the
    failure the removal was guarding against in the first place."""
    pytest.importorskip("mt_metadata")
    base = _build(tmp_path)
    for st in ("EXAMPLE01", "EXAMPLE02"):
        diag = json.loads((base / st / "station.json").read_text(encoding="utf-8"))["diagnostics"]
        assert diag["classification"] and "skew_beta_median_deg" in diag, diag
        assert diag["method"] == "phase-tensor (Caldwell 2004)", diag
        assert diag["note"] == "screening diagnostic, not an interpretation product", diag
        assert "skew_beta_mean_deg" not in diag, "the statistic is a median; the key must say so"
        # the sidecar keeps being written byte-unchanged and states the same call
        dim = json.loads((base / st / "dimensionality.json").read_text(encoding="utf-8"))
        assert dim["classification"] == diag["classification"], (dim, diag)
        assert dim["skew_beta_median_deg"] == diag["skew_beta_median_deg"], (dim, diag)
        assert dim["pct_periods_3d"] == diag["pct_periods_3d"], (dim, diag)


def test_proc_info_survives_a_missing_writer_vocabulary():
    """The package-path identity cannot import the bare `_edi_catalog` sibling, and the whole body
    of proc_info_from_tf used to sit inside the try that swallowed that failure - so the SAME
    function on the SAME TF returned rr=0 (a wrong claim in a published sci column) and alg=None
    through `extract._mtm` while the bare copy returned the truth. Only the writer-vocabulary
    claim (`sw`) needs the vocabulary; alg/rr/name/version are computed regardless, and without
    the vocabulary `sw` claims nothing. Run in a subprocess with engine/ alone on sys.path, the
    exact identity normalize reaches."""
    probe = (
        "import sys; sys.path.insert(0, '.');\n"
        "from extract._mtm import proc_info_from_tf\n"
        "class SW:\n"
        "    name='LEMIMT'; version='1.4'\n"
        "class TFM:\n"
        "    software=SW(); processing_type='remote reference birrp 5.2'\n"
        "class SM:\n"
        "    transfer_function=TFM()\n"
        "class TF:\n"
        "    station_metadata=SM()\n"
        "sw, alg, rr, writer = proc_info_from_tf(TF(), with_writer=True)\n"
        "assert rr == 1, ('rr lost: %r' % rr)\n"
        "assert alg == 'remote reference birrp 5.2', ('alg lost: %r' % alg)\n"
        "assert writer == {'name': 'LEMIMT', 'version': '1.4'}, ('writer lost: %r' % writer)\n"
        "assert sw is None, ('no vocabulary means no software claim: %r' % sw)\n"
        "print('OK')\n")
    r = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT),
                       capture_output=True, text=True)
    assert r.returncode == 0 and "OK" in r.stdout, (
        "proc_info degraded under the package-path identity:\n" + r.stdout + r.stderr)
