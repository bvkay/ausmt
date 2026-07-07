"""Download manifest (slice #4 — the distribution backbone).

The build emits manifest.json: the key-based index of every DOWNLOADABLE artifact (per-station
EDI/EMTF-XML, per-survey EDI-zip/MTH5 bundles) with size + sha256 + a tier-resolved URL.

NON-VACUOUS (Invariant 10): every row's size/sha256 is RECOMPUTED from the artifact on disk — the
independent observable — not trusted from the manifest's own bytes; every manifested file must
satisfy the redistribution license gate; and the positional catalogue must stay 15 columns (the
manifest is additive, not a contract change). Requires the mt_metadata/mth5 stack (the build engine).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = ROOT / "data"          # data/sample-survey: CC-BY-4.0 => redistributable => exercises serving
SCHEMA = json.loads((ROOT / "schema" / "manifest.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "extract"))
import build_portal as bp        # noqa: E402  (the redistributable() license gate)


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _build(tmp_path, *extra):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--bundle-edi", "--no-validate", *extra],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out, json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_integrity_and_license_gate(tmp_path):
    out, man = _build(tmp_path, "--survey-h5")
    assert man["generated_count"] == len(man["files"]) + len(man["bundles"])
    assert man["base_url"] == ""
    assert man["files"] and man["bundles"], "the CC-BY sample survey should yield served artifacts"

    fmts_by_station = {}
    for row in man["files"]:
        for k in ("ausmt_id", "survey", "station", "format", "url", "size", "sha256", "tier"):
            assert k in row, f"file row missing {k}"
        assert row["format"] in ("edi", "emtfxml")
        # the default build (no survey nci_base) serves the repo tier with a resolvable (non-null) url;
        # the tier=nci path (an absolute NCI url) is emitted + asserted by test_manifest_nci_base_flips_tier
        # below, and url_for's repo/base_url branches are unit-tested in test_url_for.py.
        assert row["tier"] == "repo" and row["url"], f"unexpected tier/url: {row['tier']} {row['url']}"
        # license-gate consistency: nothing non-redistributable may be served
        assert bp.redistributable(row["license"]), f"manifested non-redistributable: {row['license']}"
        # INDEPENDENT OBSERVABLE: recompute size + sha256 from the artifact on disk
        artifact = out / row["url"]            # tier=repo => relative url resolves under out/
        assert artifact.exists(), f"missing artifact {row['url']}"
        assert artifact.stat().st_size == row["size"], f"size mismatch {row['url']}"
        assert _sha(artifact) == row["sha256"], f"sha256 mismatch {row['url']}"
        fmts_by_station.setdefault(row["ausmt_id"], set()).add(row["format"])
    assert fmts_by_station and all({"edi", "emtfxml"} <= f for f in fmts_by_station.values()), \
        "every served station should have BOTH an EDI and an EMTF-XML row"

    bfmts = set()
    urls_by_fmt = {}
    for row in man["bundles"]:
        assert bp.redistributable(row["license"])
        artifact = out / row["url"]
        assert artifact.exists(), f"missing bundle {row['url']}"
        assert artifact.stat().st_size == row["size"], f"bundle size mismatch {row['url']}"
        assert _sha(artifact) == row["sha256"], f"bundle sha256 mismatch {row['url']}"
        assert row["n_stations"] >= 1
        bfmts.add(row["format"])
        urls_by_fmt[row["format"]] = row["url"]
    # C32 §1: three bundle kinds for a served survey with the flag on — EDI zip, EMTF-XML zip, TF MTH5.
    assert bfmts == {"edi-zip", "xml-zip", "mth5"}, f"expected all three C32 bundle kinds, got {bfmts}"
    # C32 filename contract: the MTH5 says transfer-functions-only via the -tf suffix, all under bundles/.
    assert urls_by_fmt["edi-zip"].endswith("-edi.zip") and urls_by_fmt["edi-zip"].startswith("bundles/")
    assert urls_by_fmt["xml-zip"].endswith("-xml.zip") and urls_by_fmt["xml-zip"].startswith("bundles/")
    assert urls_by_fmt["mth5"].endswith("-tf.h5"), f"MTH5 bundle must be <slug>-tf.h5: {urls_by_fmt['mth5']}"
    assert urls_by_fmt["mth5"].startswith("bundles/"), "the survey MTH5 now lives under bundles/, not h5/"

    # contract non-disturbance: the manifest is additive; the positional catalogue stays 15 columns
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    assert cat and all(len(row) == 15 for row in cat), "catalogue width must remain 15 (positional contract)"


def test_manifest_survey_h5_off_by_default(tmp_path):
    """survey MTH5 is gated OFF by default (D4): no --survey-h5 => no -tf.h5 artifact and no mth5 bundle
    row. The per-survey EDI zip AND the C32 EMTF-XML zip are BOTH unconditional when served (only the
    MTH5 is flag-gated)."""
    out, man = _build(tmp_path)               # no --survey-h5
    assert not list((out / "bundles").glob("*-tf.h5")), "no survey MTH5 should be produced without the flag"
    assert all(b["format"] != "mth5" for b in man["bundles"]), "no mth5 bundle row when flag off"
    assert any(b["format"] == "edi-zip" for b in man["bundles"]), "edi-zip bundle is unconditional when served"
    assert any(b["format"] == "xml-zip" for b in man["bundles"]), "xml-zip bundle is unconditional when served"


def test_xml_zip_contains_exactly_the_served_xml_set(tmp_path):
    """C32 §1.1 / §4: the per-survey EMTF-XML zip contains EXACTLY the survey's emitted canonical XMLs
    (plus the C6 LICENSE.txt) — no more, no less. INDEPENDENT OBSERVABLE: the on-disk out/xml/<slug>/
    set, compared against the zip's namelist. FAILS if the zip bundles a stale/foreign XML or misses a
    served one."""
    import zipfile
    out, man = _build(tmp_path)
    xrow = next(b for b in man["bundles"] if b["format"] == "xml-zip")
    zpath = out / xrow["url"]
    with zipfile.ZipFile(zpath) as z:
        names = set(z.namelist())
    assert "LICENSE.txt" in names, "the C6 LICENSE.txt must travel inside the XML zip"
    # every served XML on disk for this survey must be in the zip, and vice versa (LICENSE.txt aside)
    slug = xrow["slug"]
    on_disk = {p.name for p in sorted((out / "xml" / slug).glob("*.xml"))}
    assert on_disk, "the sample survey must have emitted served XML"
    assert (names - {"LICENSE.txt"}) == on_disk, (
        f"xml-zip contents drifted from the served XML set: zip={sorted(names)} disk={sorted(on_disk)}")
    assert xrow["n_stations"] == len(on_disk), "n_stations must equal the number of bundled XMLs"


def test_tf_h5_bundle_round_opens_with_served_tfs(tmp_path):
    """C32 §1.2 / §4: the survey MTH5 bundle round-opens under mth5 and holds the served stations'
    TRANSFER FUNCTIONS. Reuses the same _mth5 reader the compare/round-trip tests use. FAILS if the file
    is unreadable, is misnamed (not <slug>-tf.h5), or is missing a served station's TF."""
    import _mth5 as m5  # noqa: PLC0415
    out, man = _build(tmp_path, "--survey-h5")
    hrow = next(b for b in man["bundles"] if b["format"] == "mth5")
    assert hrow["url"].endswith("-tf.h5"), f"MTH5 bundle must be named <slug>-tf.h5, got {hrow['url']}"
    hpath = out / hrow["url"]
    ids_in_h5 = sorted(rec["id"] for rec, _per, _comp in m5.records_and_components(hpath))
    # cross-check against the served EDI stations in the manifest (the served set)
    served_ids = sorted({r["station"] for r in man["files"] if r["format"] == "edi"})
    assert served_ids, "the sample survey must have served stations"
    assert ids_in_h5 == served_ids, f"tf.h5 TFs {ids_in_h5} != served stations {served_ids}"
    assert hrow["n_stations"] == len(ids_in_h5), "n_stations must equal the TFs actually written"


def test_manifest_deterministic_for_reproducible_formats(tmp_path):
    """EDI copies and the per-survey EDI zip are byte-reproducible across builds, so their manifest
    sha256 is stable. (EMTF XML and HDF5 embed timestamps and are intentionally not asserted here.)"""
    out1, m1 = _build(tmp_path / "b1")
    out2, m2 = _build(tmp_path / "b2")
    def sha_of(man, fmt, scope):
        rows = man[scope]
        return sorted((r["url"], r["sha256"]) for r in rows if r["format"] == fmt)
    assert sha_of(m1, "edi", "files") == sha_of(m2, "edi", "files"), "EDI hashes must be reproducible"
    assert sha_of(m1, "edi-zip", "bundles") == sha_of(m2, "edi-zip", "bundles"), "EDI-zip must be reproducible"


def test_manifest_jsonschema_when_available(tmp_path):
    """Full draft-07 validation when jsonschema is installed (bonus on top of the explicit checks)."""
    jsonschema = pytest.importorskip("jsonschema")
    _out, man = _build(tmp_path, "--survey-h5")
    jsonschema.validate(man, SCHEMA)


def test_manifest_nci_base_flips_tier(tmp_path):
    """A survey that declares nci_base resolves its served artifacts to NCI (tier=nci, an absolute
    fileServer URL = <nci_base>/<filename>) while the sha256 integrity ledger stays computed from the
    LOCAL bytes. FAILS if nci_base is ignored (rows stay tier=repo), the URL isn't the configured
    absolute base, or the recorded sha256 doesn't match the bytes on disk (Invariant 10)."""
    import shutil
    base = "https://thredds.nci.org.au/thredds/fileServer/test/AusMT_sample"
    staged = tmp_path / "surveys_src"
    shutil.copytree(SURVEYS, staged)
    yamls = list(staged.rglob("survey.yaml"))
    assert yamls, "expected a survey.yaml in the sample data"
    for y in yamls:
        y.write_text(y.read_text(encoding="utf-8").rstrip() + f"\nnci_base: {base}\n")
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(staged),
                        "--out", str(out), "--bundle-edi", "--no-validate"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    rows = man["files"] + man["bundles"]
    assert rows, "the CC-BY sample survey should still yield served artifacts"
    # with nci_base set, EVERY served artifact of that survey is tier=nci at the configured base
    assert all(row["tier"] == "nci" for row in rows), \
        f"nci_base ignored — tiers seen: {sorted({row['tier'] for row in rows})}"
    for row in rows:
        assert "://" in row["url"], f"nci url must be absolute: {row['url']}"
        assert row["url"].startswith(base + "/"), f"nci url not under base: {row['url']}"
        # INDEPENDENT OBSERVABLE: the sha256 still matches the local bytes (recompute from disk)
        fname = row["url"].rsplit("/", 1)[-1]
        local = next(iter(out.rglob(fname)), None)
        assert local and local.exists(), f"no local copy to verify {fname}"
        assert _sha(local) == row["sha256"], f"sha256 mismatch for {fname}"
    # provenance records how many artifacts went to the NCI tier
    prov = json.loads((out / "build_provenance.json").read_text(encoding="utf-8"))
    assert prov.get("nci_tier_artifacts") == len(rows), "provenance nci count must match the manifest"
    # the lightweight portal JSON stays git-side regardless (not in the manifest, no tier)
    assert (out / "catalogue.json").exists() and (out / "tf.json").exists()
