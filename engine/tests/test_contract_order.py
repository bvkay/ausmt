"""Contract ORDER-binding (Invariant 10).

The width asserts in build_portal only check len(row) == len(*_COLUMNS) — they are reorder-blind. These
tests check the built positional rows carry the right KIND of value at each NAMED column position taken
from contract/columns.json. The catalogue row is now PROJECTED from CATALOGUE_COLUMNS (build_portal), so
it follows the contract automatically and these assertions guard that projection; the sci/tf rows are
hand-built, so this is their reorder guard — a same-width reorder of columns.json that the producer does
NOT follow lands a distinctive value (ausmt_id pattern, sha256 hex, a dim enum, …) at the wrong index and
FAILS here, instead of shipping green and silently corrupting the portal.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                   # engine/
COLS = json.loads((ROOT.parent / "contract" / "columns.json").read_text(encoding="utf-8"))


def _build(tmp_path):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(ROOT / "data"),
                        "--out", str(out), "--no-validate"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return (json.loads((out / "catalogue.json").read_text(encoding="utf-8")),
            json.loads((out / "sci.json").read_text(encoding="utf-8")),
            json.loads((out / "tf.json").read_text(encoding="utf-8")))


def test_catalogue_columns_land_at_contract_positions(tmp_path):
    cat, _, _ = _build(tmp_path)
    assert cat, "sample build should yield stations"
    C = {n: i for i, n in enumerate(COLS["catalogue"])}
    row = cat[0]
    assert len(row) == len(COLS["catalogue"])
    assert isinstance(row[C["id"]], str) and row[C["id"]]
    assert isinstance(row[C["survey"]], str)
    assert isinstance(row[C["lat"]], (int, float)) and -90 <= row[C["lat"]] <= 90
    assert isinstance(row[C["lon"]], (int, float)) and -180 <= row[C["lon"]] <= 180
    assert row[C["type"]] in ("AMT", "BBMT", "LPMT", "GDS", "unknown", None)
    assert isinstance(row[C["coord_flag"]], bool)
    assert re.match(r"^au\.[a-z0-9-]+\.", str(row[C["ausmt_id"]])), row[C["ausmt_id"]]
    assert row[C["edi_available"]] in (0, 1)
    assert re.match(r"^[0-9a-f]{64}$", str(row[C["sha256"]])), row[C["sha256"]]


def test_sci_columns_land_at_contract_positions(tmp_path):
    _, sci, _ = _build(tmp_path)
    assert sci, "sample build should yield sci rows"
    SC = {n: i for i, n in enumerate(COLS["sci"])}
    row = sci[0]
    assert len(row) == len(COLS["sci"])
    assert row[SC["q"]] is None or isinstance(row[SC["q"]], (int, float))
    assert row[SC["qb"]] in ("e", "s", None)
    assert row[SC["rr"]] in (0, 1)
    assert row[SC["dim"]] in ("1-D", "2-D", "3-D", "indeterminate", None)
    assert row[SC["decades"]] is None or isinstance(row[SC["decades"]], (int, float))


def test_tf_columns_land_at_contract_positions(tmp_path):
    _, _, tf = _build(tmp_path)
    assert tf, "sample build should yield tf entries"
    T = {n: i for i, n in enumerate(COLS["tf"])}
    entry = tf[0]
    assert len(entry) == len(COLS["tf"])
    periods = entry[T["periods"]]
    assert isinstance(periods, list) and periods, "periods column must be the non-empty period axis"
    for name in ("rho_xy", "phs_xy", "tip_mag", "pt_az", "pt_beta"):
        col = entry[T[name]]
        assert col is None or isinstance(col, list), name
