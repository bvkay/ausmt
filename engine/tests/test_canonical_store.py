"""The ADDITIVE canonical-store emission in build_portal (`--canonical-dir`).

Asserts that the flag emits a per-survey canonical EMTF XML + derived EDI (round-trip verified by
normalize) and a provenance.json stamped with the mt_metadata/mth5 versions, WITHOUT changing the
portal products. The flag is additive: it writes the D6 canonical store alongside the products, it
does not (yet) become their source. Requires the core mt_metadata/mth5 engine; importorskips
otherwise; runs in the build CI job's suite.
"""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402


def test_canonical_store_is_additive(tmp_path):
    out = tmp_path / "out"
    canon = tmp_path / "canon"
    rc = build_portal.main([
        "--surveys", str(REPO / "data"),
        "--out", str(out),
        "--canonical-dir", str(canon),
        "--no-validate",
    ])
    assert rc == 0, f"build exit {rc}"

    # canonical store: per-survey XML + derived EDI + provenance with engine versions
    assert list(canon.rglob("*.xml")), "no canonical EMTF XML written"
    assert list(canon.rglob("*.edi")), "no derived EDI written"
    prov = json.loads((canon / "provenance.json").read_text(encoding="utf-8"))
    assert prov["engine_versions"].get("mt_metadata"), "engine version not stamped"
    assert prov["canonical_written"] >= 1 and prov["failed"] == 0

    # the portal products are still produced and non-empty (the flag is additive, not the source)
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    assert len(cat) >= 1
    # row width still the contract (15 cols) — the additive feature didn't disturb the projection
    assert all(len(row) == 15 for row in cat)


def test_canonical_store_same_dataid_no_overwrite(tmp_path):
    """Two EDIs in one survey sharing a DATAID (the same-site-two-codes case `_disambiguate` exists for)
    must produce TWO distinct canonical XML files, and `canonical_written` must equal the files on disk.
    Regression guard for H1: emit_canonical_store keyed on the PRE-disambiguation DATAID, so both wrote
    the same <DATAID>.xml (one overwritten) while the count incremented twice."""
    import re as _re
    src_edis = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))
    assert len(src_edis) >= 2, "need two sample EDIs"
    pkg = tmp_path / "surveys" / "dup-survey"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "name: Dup Survey\nslug: dup-survey\ncountry: Australia\norganisation: T\n"
        "access: open\nlicense: CC-BY-4.0\n", encoding="utf-8")
    # two distinct files, both rewritten to DATAID="DUP01"
    for i, b in enumerate(src_edis[:2]):
        txt = _re.sub(r'(?im)^(DATAID\s*=\s*).*$', r'\1"DUP01"', b.read_text(encoding="latin-1"))
        (edir / f"dup_{i}.edi").write_text(txt, encoding="latin-1")

    out = tmp_path / "out2"
    canon = tmp_path / "canon2"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--canonical-dir", str(canon), "--no-validate"])
    assert rc == 0, f"build exit {rc}"
    xmls = sorted((canon / "dup-survey").glob("*.xml"))
    prov = json.loads((canon / "provenance.json").read_text(encoding="utf-8"))
    assert len(xmls) == 2, f"same-DATAID survey overwrote a canonical XML: got {[p.name for p in xmls]}"
    assert prov["canonical_written"] == len(xmls), \
        f"canonical_written ({prov['canonical_written']}) != XML files on disk ({len(xmls)})"


# --- C2: conditioning is persisted (provenance.json map + station.json) and the citation is HONEST ---
SPECTRA = HERE / "real_dialects" / "phoenix_empower_A01.edi"


def _spectra_survey(tmp_path):
    """A one-station survey built around the Phoenix EMpower spectra fixture (whose _rotation_angle is
    None -> the rotation-unknown conditioning), with a named custodian org + open licence so the citation
    and served XML are exercised. Returns the surveys root."""
    import shutil
    pkg = tmp_path / "surveys" / "broken-hill"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "name: Broken Hill MT\nslug: broken-hill\ncountry: Australia\n"
        "organisation:\n  name: Geoscience Australia\n"
        "access: open\nlicense: CC-BY-4.0\n", encoding="utf-8")
    shutil.copy(SPECTRA, edir / "phoenix_empower_A01.edi")
    return tmp_path / "surveys"


def test_conditioning_persisted_in_provenance_and_station_json(tmp_path):
    """FAILS IF: a station that had to be conditioned (the spectra fixture's rotation frame is unknown)
    leaves NO trace — i.e. the canonical store's provenance.json records only counts (not a per-station
    conditioning map) and/or the --products station.json carries no `canonical_conditioning`. Pre-fix
    both consumers discarded normalize()'s returned notes entirely."""
    assert SPECTRA.exists(), SPECTRA
    surveys = _spectra_survey(tmp_path)
    out = tmp_path / "out"; canon = tmp_path / "canon"; prod = tmp_path / "prod"
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(out),
                            "--canonical-dir", str(canon), "--products", str(prod), "--no-validate"])
    assert rc == 0, f"build exit {rc}"

    # (a) provenance.json carries a per-station conditioning MAP, not just counts
    prov = json.loads((canon / "provenance.json").read_text(encoding="utf-8"))
    assert "conditioning" in prov, "provenance.json has no per-station conditioning map"
    cond = prov["conditioning"].get("broken-hill") or {}
    assert cond, f"no conditioning recorded for broken-hill: {prov['conditioning']}"
    notes = next(iter(cond.values()))
    assert any(n.startswith("rotation:") and "NOT asserted" in n for n in notes), notes

    # (b) that station's --products station.json carries canonical_conditioning with the same note
    sj = next((prod / "broken-hill").rglob("station.json"))
    st = json.loads(sj.read_text(encoding="utf-8"))
    cc = st.get("canonical_conditioning")
    assert cc, f"station.json has no canonical_conditioning: {list(st)}"
    assert any(n.startswith("rotation:") and "NOT asserted" in n for n in cc), cc


def test_served_and_canonical_xml_citation_is_the_org_not_ausmt(tmp_path):
    """FAILS IF: the served XML (out/xml/<slug>) and the canonical-store XML cite the portal brand
    "AusMT" as authors instead of the survey custodian org. The spectra fixture is author-less, so pre-fix
    condition_tf stamped "AusMT"; the fix sources the org from the survey SMETA passed at BOTH call sites."""
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415
    surveys = _spectra_survey(tmp_path)
    out = tmp_path / "out"; canon = tmp_path / "canon"
    rc = build_portal.main(["--surveys", str(surveys), "--out", str(out),
                            "--canonical-dir", str(canon), "--bundle-edi", "--no-validate"])
    assert rc == 0, f"build exit {rc}"

    def _authors(xml_path):
        tf = TF(); tf.read(str(xml_path))
        return tf.survey_metadata.citation_dataset.authors

    served = list((out / "xml" / "broken-hill").glob("*.xml"))
    canon_xml = list((canon / "broken-hill").glob("*.xml"))
    assert served, "no served XML written (survey should be open + redistributable)"
    assert canon_xml, "no canonical XML written"
    for xp in served + canon_xml:
        a = _authors(xp)
        assert a == "Geoscience Australia", f"{xp.name}: authors={a!r}"
        assert a != "AusMT", f"{xp.name}: citation authors are the portal brand — fabricated"
