"""Optional collection/programme support: two survey packages declaring the same collection roll up
into collections.json and MTCAT collections, while each survey keeps its own provenance. Surveys
without a collection are unaffected (backwards compatible)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Build-integration test: the build now defaults to the mt_metadata engine (slice-#3d), so it needs
# the stack. (Collection rollup is extractor-agnostic; regex stays covered by other tests meanwhile.)
pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _member_pkg(base, slug, name, edi, collection_block):
    from _fixtures import EXAMPLE_SURVEY as ex
    y = ex.joinpath("survey.yaml").read_text(encoding="utf-8")
    y = (y.replace("slug: example-survey", f"slug: {slug}")
           .replace('project_name: "Example MT Survey 2026"', f'project_name: "{name}"')
           .replace('name: "Example MT Survey 2026"', f'name: "{name}"'))
    if collection_block:
        y = y.replace("country: Australia\n", "country: Australia\n" + collection_block, 1)
    d = base / slug
    (d / "transfer_functions" / "edi").mkdir(parents=True)
    shutil.copy(edi, d / "transfer_functions" / "edi" / edi.name)
    (d / "survey.yaml").write_text(y)


def test_collection_rollup_and_mtcat(tmp_path):
    from _fixtures import example_edis
    edis = example_edis()
    assert len(edis) >= 2
    cblock = ("collection:\n  id: auslamp\n"
              "  title: Australian Lithospheric Architecture Magnetotelluric Project\n"
              "  type: programme\n  status: active\n  start_year: 2003\n"
              "  last_updated: 2026-06-15\n  description: National MT programme.\n")
    base = tmp_path / "surveys"
    _member_pkg(base, "sa-2017", "SA Campaign 2017", edis[0], cblock)
    _member_pkg(base, "vic-2018", "Victoria 2018", edis[1], cblock)

    out = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(base), "--out", str(out), "--no-validate"],
                   cwd=str(ROOT), check=True, capture_output=True)

    colls = json.loads((out / "collections.json").read_text(encoding="utf-8"))
    assert "auslamp" in colls
    c = colls["auslamp"]
    assert c["type"] == "programme"
    assert c["n_surveys"] == 2
    assert sorted(c["surveys"]) == ["SA Campaign 2017", "Victoria 2018"]
    assert c["bbox"] and c["centroid"]
    # programme metadata (Prototype 25) propagates from member declarations
    assert c["status"] == "active"
    assert c["start_year"] == 2003
    assert c["last_updated"] == "2026-06-15"
    assert c["description"]

    mt = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    mc = [x for x in mt.get("collections", []) if x["collection_id"] == "auslamp"]
    assert mc and mc[0].get("status") == "active" and mc[0].get("start_year") == 2003
    assert all(s.get("collection_id") == "auslamp" for s in mt["surveys"])
    assert all(s.get("version") == "1.0.0" for s in mt["surveys"])


def test_collection_status_out_of_vocab_is_dropped(tmp_path):
    """An out-of-vocabulary collection status must not propagate into the rollup (the validator warns
    separately; the build refuses to surface a non-standard status)."""
    from _fixtures import example_edis
    edis = example_edis()
    cblock = ("collection:\n  id: wamt\n  title: WA MT\n  type: programme\n  status: ongoing\n")
    base = tmp_path / "surveys"
    _member_pkg(base, "wa-2020", "WA 2020", edis[0], cblock)
    out = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(base), "--out", str(out), "--no-validate"],
                   cwd=str(ROOT), check=True, capture_output=True)
    c = json.loads((out / "collections.json").read_text(encoding="utf-8"))["wamt"]
    assert c["status"] is None      # 'ongoing' is not active/completed/archived → not surfaced


def test_no_collection_is_backwards_compatible(tmp_path):
    from _fixtures import example_edis
    edis = example_edis()
    base = tmp_path / "surveys"
    _member_pkg(base, "lone-survey", "Lone Survey", edis[0], None)
    out = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(base), "--out", str(out), "--no-validate"],
                   cwd=str(ROOT), check=True, capture_output=True)
    colls = json.loads((out / "collections.json").read_text(encoding="utf-8"))
    assert colls == {}                      # no collections emitted
    mt = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    assert mt.get("collections") == []      # MTCAT collections always present (empty list when none)
