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
         "build.json"]   # Build identity - every build writes it, including an empty one


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
    # the download manifest has a valid empty shape (no downloadable artifacts yet). A2 adds the
    # document-level mth5/mt_metadata version pin (additive keys, present even on an empty build so the
    # manifest self-declares the library it was written with — mirroring mtcat/build_provenance); the
    # values are the installed versions, or None when the stack is absent (an EDI-only build env).
    assert {k: manifest[k] for k in ("generated_count", "base_url", "files", "bundles")} == \
        {"generated_count": 0, "base_url": "", "files": [], "bundles": []}
    assert "mth5_version" in manifest and "mt_metadata_version" in manifest
    # MTCAT 2.0 dropped the document-level library-version keys (manifest/build docs keep theirs)
    # and the empty-collections state: no collections => no key.
    assert "mth5_version" not in mtcat and "mt_metadata_version" not in mtcat
    assert mtcat["surveys"] == []
    assert mtcat["stations"] == []
    assert "collections" not in mtcat
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
