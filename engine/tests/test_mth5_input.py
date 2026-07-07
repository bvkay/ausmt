"""EDI and MTH5 are first-class inputs that share ONE science pathway: building a survey package
from EDI vs from an MTH5 made of the same transfer functions must yield identical catalogue rows,
diagnostics and derived products. Skips cleanly if mth5/mt_metadata are not installed."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXTRACT = ROOT / "extract"
sys.path.insert(0, str(EXTRACT))

m5 = pytest.importorskip("_mth5")
if not m5.available():
    pytest.skip("mth5/mt_metadata not installed", allow_module_level=True)


def _build(surveys_dir, out, fmt):
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(surveys_dir), "--input-format", fmt,
                    "--out", str(out), "--no-validate"],
                   cwd=str(ROOT), check=True, capture_output=True)
    return {k: json.loads((out / f"{k}.json").read_text(encoding="utf-8"))
            for k in ("catalogue", "sci", "build_provenance")}


def test_edi_and_mth5_inputs_produce_identical_products(tmp_path):
    from _fixtures import EXAMPLE_SURVEY, example_edis
    example = EXAMPLE_SURVEY
    edis = example_edis()
    assert edis, "example EDIs present"

    edi_pkg = tmp_path / "pkg-edi" / "example"
    mh_pkg = tmp_path / "pkg-mth5" / "example"
    (edi_pkg / "transfer_functions" / "edi").mkdir(parents=True)
    (mh_pkg / "transfer_functions" / "mth5").mkdir(parents=True)
    for e in edis:
        shutil.copy(e, edi_pkg / "transfer_functions" / "edi" / e.name)
    shutil.copy(example / "survey.yaml", edi_pkg / "survey.yaml")
    shutil.copy(example / "survey.yaml", mh_pkg / "survey.yaml")
    n = m5.build_mth5_from_edis(edis, mh_pkg / "transfer_functions" / "mth5" / "example.h5", survey_id="example")
    assert n == len(edis)

    A = _build(edi_pkg.parent, tmp_path / "out-edi", "edi")
    B = _build(mh_pkg.parent, tmp_path / "out-mth5", "mth5")

    assert A["build_provenance"]["input_formats"] == ["edi"]
    assert B["build_provenance"]["input_formats"] == ["mth5"]

    ka = {r[0]: r for r in A["catalogue"]}
    kb = {r[0]: r for r in B["catalogue"]}
    assert set(ka) == set(kb) and ka, "same station set from both inputs"
    for s, a in ka.items():
        b = kb[s]
        assert abs(a[2] - b[2]) < 1e-4 and abs(a[3] - b[3]) < 1e-4, f"{s}: coordinates match"
        assert a[6] == b[6], f"{s}: n_periods match"
        assert a[8] == b[8], f"{s}: type match"

    # diagnostics (dimensionality at index 5) identical
    da = [row[5] for row in A["sci"]]
    db = [row[5] for row in B["sci"]]
    assert da == db, "dimensionality labels identical across input formats"
