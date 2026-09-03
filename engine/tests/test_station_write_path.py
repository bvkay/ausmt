"""Where the promoted station.json is published, and why it lands in BOTH trees.

station.json is a public contract served at /data/products/<slug>/<station>/station.json, so it must
exist at the served root of every build, exactly as survey-metadata.json does. Until the promotion it
was written ONLY under --products, so a build run without that flag published a data tree with a
documented contract missing from it.

It is not a MOVE, which is what the survey-metadata precedent did (build_portal.py writes that document
to out/products and nowhere else). Five test files build with a --products dir that does NOT coincide
with --out and read station.json back out of it - test_build_report.py, test_canonical_store.py,
test_emtfxml_input.py, test_processing_lineage.py and gateway/tests/test_c43_stage2a_js_parity.py - and
deploy/Makefile makes the two coincide in deployment, so the served path is identical either way. Both
trees keep their copy, and the two copies are the same bytes.

SCOPE, stated because the asymmetry is deliberate: D7 promotes station.json alone. dimensionality.json
is served beside it but is not a contract, so it stays where it has always been written, under
--products. In deployment the two directories are the same one.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # engine/
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)


def _build(tmp_path, products=None):
    out = tmp_path / "data"
    argv = [sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
            "--out", str(out), "--no-validate"]
    if products is not None:
        argv += ["--products", str(products)]
    r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _stations(tree):
    return {p.parent.parent.name + "/" + p.parent.name: p for p in sorted(tree.rglob("station.json"))}


def test_station_json_is_published_in_both_trees_when_products_sits_outside_out(tmp_path):
    """FAILS against the pre-promotion emitter, which wrote station.json under --products only: with
    --products OUTSIDE --out, out/products/ held no station record at all."""
    pytest.importorskip("mt_metadata")
    products = tmp_path / "curator-products"        # deliberately NOT under --out
    out = _build(tmp_path, products=products)
    assert products.resolve() not in out.resolve().parents and products.parent == out.parent

    served = _stations(out / "products")
    curated = _stations(products)
    assert served, "the served root must carry a station.json for every station"
    assert set(served) == set(curated), (
        f"the two trees must publish the same stations; served={sorted(served)} curated={sorted(curated)}")
    for key, path in served.items():
        assert path.read_bytes() == curated[key].read_bytes(), (
            f"{key}: the served copy and the curator copy are the same document, not two renderings")
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["schema"] == "ausmt-station"

    # D7 promotes station.json alone; the dimensionality sidecar keeps its single --products home.
    assert list(products.rglob("dimensionality.json")), "the curator tree keeps the sidecar"
    assert not list((out / "products").rglob("dimensionality.json")), (
        "dimensionality.json is not a contract and is not promoted with station.json")


def test_station_json_is_published_at_the_served_root_with_no_products_flag(tmp_path):
    """FAILS against the pre-promotion emitter, which emitted no station.json whatsoever without
    --products: the flag decided whether a public contract existed."""
    pytest.importorskip("mt_metadata")
    out = _build(tmp_path)
    served = _stations(out / "products")
    assert served, "a build with no --products must still publish the station contract"
    for path in served.values():
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["schema"] == "ausmt-station" and doc["ausmt_id"]
    # the survey document of the same tree is published by the same rule, and this is where it lands
    assert list((out / "products").glob("*/survey-metadata.json")), "precondition: the sibling contract"
