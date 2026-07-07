"""Empty-build guarantee: a fresh deployment with no surveys must still produce valid default product
files (so a cloned framework — AusMT, NZMT, CanadaMT — builds and the portal shows its empty state).
This is important for new deployments and international reuse."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

FILES = ["catalogue.json", "tf.json", "sci.json", "surveys.json",
         "collections.json", "mtcat.json", "build_provenance.json", "manifest.json",
         "build.json"]   # C12: build identity — every build writes it, including an empty one


def test_empty_build_generates_valid_json(tmp_path):
    empty_surveys = tmp_path / "surveys"
    empty_surveys.mkdir()
    out = tmp_path / "data"

    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(empty_surveys),
         "--out", str(out), "--allow-empty", "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr        # build succeeds with --allow-empty

    # all seven product files exist and parse
    for f in FILES:
        p = out / f
        assert p.exists(), f"missing {f}"
        json.loads(p.read_text(encoding="utf-8"))             # valid JSON

    catalogue = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    surveys = json.loads((out / "surveys.json").read_text(encoding="utf-8"))
    collections = json.loads((out / "collections.json").read_text(encoding="utf-8"))
    mtcat = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    # empty shapes
    assert catalogue == []
    assert surveys == {}
    assert collections == {}
    # the download manifest has a valid empty shape (no downloadable artifacts yet)
    assert manifest == {"generated_count": 0, "base_url": "", "files": [], "bundles": []}
    assert mtcat["surveys"] == []
    assert mtcat["stations"] == []
    assert mtcat["collections"] == []
    assert mtcat["portal"]["portal_id"]       # MTCAT still carries a valid portal block
    assert mtcat["portal"]["schema"] == "mtcat"


def test_empty_build_fails_without_allow_empty(tmp_path):
    """Without --allow-empty an empty build must FAIL (the trust invariant): a green run that produced
    nothing would make every other green check meaningless."""
    empty_surveys = tmp_path / "surveys"
    empty_surveys.mkdir()
    out = tmp_path / "data"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(empty_surveys),
         "--out", str(out), "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 2
    assert "empty" in (r.stderr + r.stdout).lower()
