"""C6 licence instrument hardening (Invariant 10).

The pre-C6 gate was `redistributable() = s.startswith("CC") or s in {PUBLIC DOMAIN, CC0, ODBL, ODC-BY}`
— so a TYPO'd 'CC-BY-4.O' (letter O) or any 'CC-nonsense' redistributed. C6 replaces the prefix test with
an EXACT, case-insensitive-after-trim/whitespace/de-alias match against contract/licenses.json.

NON-VACUOUS failure criteria (each fails against the OLD prefix gate or a broken emitter):
  * typo 'CC-BY-4.O'  -> NOT redistributable   (OLD gate: startswith('CC') => True — this test would fail pre-fix)
  * 'cc-by-4.0' (case) -> redistributable        (exact match must be case-insensitive)
  * bare aliases 'CC0'/'CC-BY' -> redistributable (legacy survey.yaml values, via licenses.json aliases)
  * a recognised metadata-only id (e.g. 'ALL RIGHTS RESERVED') -> NOT redistributable
  * the served survey EDI zip contains a LICENSE.txt naming the licensor, and the zip stays byte-reproducible.
Requires only stdlib (redistributable/text are pure); the zip test drives the real build.
"""
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = ROOT / "data"          # data/sample-survey: CC-BY-4.0 => redistributable => served
sys.path.insert(0, str(ROOT / "extract"))
import build_portal as bp        # noqa: E402


def test_typo_license_is_not_redistributable():
    # The exact defect C6 closes: a single-character typo (letter O for zero 0) used to pass startswith('CC').
    assert not bp.redistributable("CC-BY-4.O"), "a typo'd CC id must NOT be redistributable (was the prefix hole)"
    assert not bp.redistributable("CC-nonsense"), "arbitrary 'CC…' free text must NOT be redistributable"
    assert not bp.redistributable("CC BY 4.0 or whatever"), "extra words must NOT match"


def test_case_insensitive_exact_match():
    assert bp.redistributable("cc-by-4.0"), "match must be case-insensitive"
    assert bp.redistributable("  CC-BY-4.0  "), "leading/trailing whitespace must be trimmed"
    assert bp.redistributable("CC-BY-4.0"), "canonical id redistributes"


def test_legacy_bare_aliases_redistribute():
    # Legacy survey.yaml values that predate the -X.Y suffix convention, mapped via licenses.json aliases.
    assert bp.redistributable("CC0"), "bare CC0 alias -> CC0-1.0"
    assert bp.redistributable("CC-BY"), "bare CC-BY alias -> CC-BY-4.0"
    assert bp.redistributable("odbl"), "bare ODBL alias (case-insensitive) -> ODBL-1.0"


def test_public_domain_and_odc():
    assert bp.redistributable("PUBLIC DOMAIN")
    assert bp.redistributable("public domain")           # whitespace/case normalised
    assert bp.redistributable("ODC-BY-1.0")


def test_metadata_only_and_unknown_not_redistributable():
    assert not bp.redistributable("ALL RIGHTS RESERVED"), "recognised but metadata-only => NOT served"
    assert not bp.redistributable("CC-BY-NC-3.0"), "recognised metadata-only 3.0 NC => NOT served"
    assert not bp.redistributable(""), "empty => not served"
    assert not bp.redistributable(None), "None => not served"
    assert not bp.redistributable("TBD by uploader"), "placeholder => not served"


def test_license_instrument_text_names_licensor_and_url():
    txt = bp.license_instrument_text("CC-BY-4.0", "Geoscience Australia", "2019")
    assert "CC-BY-4.0" in txt
    assert "Geoscience Australia" in txt
    assert "https://creativecommons.org/licenses/by/4.0/" in txt, "CC id must carry its deed URL"
    assert "2019" in txt
    # bare alias prints its canonical id + URL
    txt2 = bp.license_instrument_text("CC-BY", "Custodian", "")
    assert "CC-BY-4.0" in txt2 and "creativecommons.org" in txt2


def _build(tmp_path, *extra):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--bundle-edi", "--no-validate", *extra],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import json
    return out, json.loads((out / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.usefixtures()
def test_survey_zip_carries_license_txt(tmp_path):
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    out, man = _build(tmp_path)
    zips = list((out / "bundles").glob("*-edi.zip"))
    assert zips, "the CC-BY sample survey should produce a served EDI zip"
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
            assert "LICENSE.txt" in names, f"{zp.name} must carry a LICENSE.txt (rights travel with bytes)"
            body = z.read("LICENSE.txt").decode("utf-8")
        assert "Licence:" in body and "Licensor:" in body, body
        # the sample survey is CC-BY-4.0, so the instrument must name that id + its deed URL
        assert "CC-BY-4.0" in body, body
        assert "creativecommons.org" in body, body


def test_survey_zip_with_license_stays_reproducible(tmp_path):
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    out1, _ = _build(tmp_path / "b1")
    out2, _ = _build(tmp_path / "b2")

    def zsha(out):
        return sorted((p.name, hashlib.sha256(p.read_bytes()).hexdigest())
                      for p in (out / "bundles").glob("*-edi.zip"))
    assert zsha(out1) == zsha(out2), "EDI zip (now including LICENSE.txt) must stay byte-reproducible"
