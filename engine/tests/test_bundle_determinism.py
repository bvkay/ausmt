"""The published bundle digests are cross-build invariants: same inputs in, same bytes out.

The manifest publishes a SHA-256 for every served file and every bundle, and the download reference
invites a consumer to check one against a previously published one. That is only meaningful if
identical inputs and identical code produce identical bytes, so this module pins BOTH halves of the
claim for the per-survey EMTF-XML zip (the one product the project cannot A/B across builds any
other way) alongside the EDI zip that already held it:

  * three INDEPENDENT full builds of the same package produce one digest, and
  * a byte-changed transfer function moves it.

The second half is what stops the first from being satisfied by a constant. A writer that emitted the
same bytes regardless of input would pass a reproducibility test and publish a useless digest.

The XML zip's members carry the one field that used to break this: mt_metadata assigns
Provenance.create_time = now() inside to_xml(), so an untouched canonical XML re-stamped the build
clock and both the per-station XML row and the whole zip's digest churned on every rebuild. The
served value is now the date the source document declares (ingest.normalize._pin_create_time), so it
is asserted here too: the digest being stable is not evidence on its own that the value is honest.
"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402

SAMPLE_EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))


def _make_survey(root, edis):
    """One survey package (survey.yaml + edi/) from the real sample EDIs. Returns the --surveys root."""
    assert edis, "sample survey fixture missing"
    pkg = root / "det-survey"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "name: Det Survey\nslug: det-survey\ncountry: Australia\norganisation: Test Org\n"
        "access: open\nlicense: CC-BY-4.0\n", encoding="utf-8")
    for src in edis:
        (edir / src.name).write_text(src.read_text(encoding="latin-1"), encoding="latin-1")
    return root


def _build(surveys, out):
    """A full, cache-blind build. The C18 cache is deliberately NOT used: a warm build is trivially
    byte-identical to the build that populated it, so a cached comparison could not see this defect
    (it is why the defect survived). INDEPENDENT full builds are the baseline here."""
    rc = build_portal.main([
        "--surveys", str(surveys), "--out", str(out), "--bundle-edi", "--no-validate"])
    assert rc == 0, f"build rc={rc}"
    return out


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _bundles(out: Path):
    return {p.name: _sha(p) for p in sorted((out / "bundles").glob("*.zip"))}


def _manifest_digests(out: Path):
    doc = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    rows = {}
    for key in ("files", "bundles"):
        for row in doc.get(key, []):
            rows[f"{key}:{row['url']}"] = row["sha256"]
    return rows


def test_xml_bundle_is_byte_identical_across_three_builds(tmp_path):
    """FAILS IF: two full builds of the same package produce different bundle bytes.

    Three builds, not two: a single repeat can be passed by a value that alternates, and the
    published digest has to hold over a deploy series, not a pair. Both bundles are asserted, so the
    EDI zip's existing guarantee cannot regress unnoticed while the XML one is being fixed, and the
    per-station manifest rows are asserted alongside them, because the defect reached those too, so pinning
    only the zip would leave half of it standing.

    Proven able to fail: on origin/main this produced three different xml-zip digests
    (951a4bd1…, 2c08b515…, 98f3bd5b…) against one stable edi-zip digest (feab1ee1…)."""
    surveys = _make_survey(tmp_path / "src", SAMPLE_EDIS)
    outs = [_build(surveys, tmp_path / f"out{i}") for i in range(3)]

    digests = [_bundles(o) for o in outs]
    assert digests[0], "the build produced no bundles (fixture wrong)"
    assert "det-survey-xml.zip" in digests[0], f"no EMTF-XML bundle was built: {sorted(digests[0])}"
    assert "det-survey-edi.zip" in digests[0], f"no EDI bundle was built: {sorted(digests[0])}"
    assert digests[0] == digests[1] == digests[2], \
        f"bundle digests differ across three identical builds: {digests}"

    served = [_manifest_digests(o) for o in outs]
    assert any(k.endswith(".xml") for k in served[0]), "no served XML rows in the manifest"
    assert served[0] == served[1] == served[2], \
        "manifest digests differ across three identical builds"


def test_served_create_time_is_the_source_date_not_the_build_clock(tmp_path):
    """FAILS IF: the served XML's <CreateTime> is a build clock, an epoch, or any value the source
    does not assert. Byte-stability alone cannot see this: a pinned constant would satisfy the
    reproducibility test while publishing a fabricated provenance date.

    The value must equal what the source declares, which is the same value the document's own
    <ProcessDate> carries and the same value the served EDI's FILEDATE is pinned to, so a station's
    two served renditions agree about when its transfer function was created."""
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415

    surveys = _make_survey(tmp_path / "src", SAMPLE_EDIS)
    out = _build(surveys, tmp_path / "out")
    xmls = sorted((out / "xml" / "det-survey").glob("*.xml"))
    assert xmls, "no served XML"

    declared = set()
    for src in SAMPLE_EDIS:
        tf = TF()
        tf.read(str(src))
        declared.add(str(tf.station_metadata.provenance.creation_time))
    assert declared, "fixture parsed no source dates"

    import re  # noqa: PLC0415
    for x in xmls:
        text = x.read_text(encoding="utf-8")
        stamps = re.findall(r"<CreateTime>([^<]*)</CreateTime>", text)
        assert len(stamps) == 1, f"{x.name}: expected one CreateTime, got {stamps}"
        assert stamps[0] in declared, \
            f"{x.name}: CreateTime {stamps[0]} is not a date any source declares ({sorted(declared)})"
        proc = re.findall(r"<ProcessDate>([^<]*)</ProcessDate>", text)
        assert proc == stamps, f"{x.name}: CreateTime {stamps} disagrees with ProcessDate {proc}"


def test_xml_bundle_digest_moves_when_a_member_changes(tmp_path):
    """FAILS IF: a changed transfer function does not move the bundle digest, the failure mode a
    reproducibility fix can introduce (pin the bytes so hard that real change stops showing).

    One impedance value in one source EDI is edited. The station's served XML must carry the new
    value, its own digest must move, the bundle's digest must move, and the OTHER station's XML must
    not, so the change is attributable rather than global."""
    surveys = _make_survey(tmp_path / "src", SAMPLE_EDIS)
    before = _build(surveys, tmp_path / "before")

    edis = sorted((surveys / "det-survey" / "transfer_functions" / "edi").glob("*.edi"))
    assert len(edis) >= 2, "need two stations to prove the change is attributable"
    target = edis[0]
    lines = target.read_text(encoding="latin-1").splitlines()
    hit = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith(">ZXXR"):
            hit = i + 1
            break
    assert hit is not None, "no >ZXXR block in the fixture EDI"
    vals = lines[hit].split()
    assert vals, "empty >ZXXR data line"
    vals[0] = f"{float(vals[0]) + 1.0:.6E}"
    lines[hit] = "  " + "  ".join(vals)
    target.write_text("\n".join(lines) + "\n", encoding="latin-1")

    after = _build(surveys, tmp_path / "after")

    b_before, b_after = _bundles(before), _bundles(after)
    assert b_before["det-survey-xml.zip"] != b_after["det-survey-xml.zip"], \
        "an edited impedance value did NOT move the EMTF-XML bundle digest"

    def _members(out):
        with zipfile.ZipFile(out / "bundles" / "det-survey-xml.zip") as z:
            return {n: hashlib.sha256(z.read(n)).hexdigest() for n in sorted(z.namelist())}

    m_before, m_after = _members(before), _members(after)
    assert sorted(m_before) == sorted(m_after), "the member set changed (the edit was too coarse)"
    moved = [n for n in m_before if m_before[n] != m_after[n]]
    xml_members = [n for n in m_before if n.endswith(".xml")]
    assert len(xml_members) >= 2, f"expected two station XMLs in the bundle: {sorted(m_before)}"
    assert len(moved) == 1, f"expected exactly one changed member, got {moved}"
    assert moved[0].endswith(".xml"), f"the changed member is not a station XML: {moved}"
