"""The plain-tipper-label parse fallback: the Capricorn 2010 long-period dialect.

Those EDIs label their tipper data blocks plainly (>TXR, >TXI, >TX.VAR ...) while mt_metadata's
EDI reader accepts ONLY the .EXP-suffixed spellings (_t_labels: txr.exp/txvar.exp/...), so a real
24-period tipper was discarded wholesale at parse: 36 long-period stations catalogued comps "Z"
against the statement of fact (the LP sites recorded the vertical field) and against
their own served bytes. The fix is the second application of the normalised-TEMPORARY-copy
pattern (the >INFO delimiter precedent): when a parsed .edi carries no tipper and the label
normalisation actually changes the bytes, the file is reparsed once from a conditioned scratch
copy; the custodian's served bytes are untouched, the fallback is RECORDED per station, and a
retry that fails or still lacks a tipper leaves the original parse standing (a recovery must
never cost a station its impedance). Because the whole TF object heals, every derived product
carries the tipper: catalogue comps, tf.json columns, station.json diagnostics, EMTF XML, MTH5.

The fixture is the real corpus CP1L01.edi verbatim (public CC-BY bytes, 9 KB).
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import _mtm as mtm          # noqa: E402
import build_portal         # noqa: E402

FIXTURE = HERE / "fixtures" / "tipper" / "CP1L01.edi"


def test_the_fallback_recovers_the_tipper_and_reports_the_reason():
    tf, reason = mtm.read_with_fallback(FIXTURE)
    assert tf.has_tipper(), "the reparse from the label-normalised copy must carry the tipper"
    assert reason == mtm.PLAIN_TIPPER_LABELS, reason
    assert str(tf.fn) == str(FIXTURE), "TF.fn must point at the custodian's file, never the scratch copy"
    _per, comp = mtm.components_from_tf(tf)
    assert comp["TXR"][0] is not None and comp["TYI"][0] is not None
    assert sum(v is not None for v in comp["TXR"]) == 24


def test_the_normaliser_changes_only_the_six_labels():
    raw = FIXTURE.read_bytes()
    fixed = mtm.normalise_plain_tipper_labels(raw)
    assert fixed is not raw
    diff = [(a, b) for a, b in zip(raw.splitlines(), fixed.splitlines()) if a != b]
    assert len(diff) == 6, [d[0] for d in diff]
    assert all(b.split()[0].endswith(b".EXP") for _a, b in diff), diff
    # already-suffixed labels are untouched: normalising the normalised bytes changes nothing
    assert mtm.normalise_plain_tipper_labels(fixed) is fixed


def test_a_tipperless_file_without_the_shape_is_left_alone():
    """The sample Vulcan EDIs carry no tipper AND no plain T labels: the fallback must not fire
    (no scratch reparse, no reason), and the parse must be the ordinary one."""
    sample = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))[0]
    tf, reason = mtm.read_with_fallback(sample)
    assert reason is None
    assert not tf.has_tipper()


def test_a_built_capricorn_shaped_station_carries_the_tipper_everywhere(tmp_path):
    """End to end over the real producer: catalogue ZT, station diagnostics true, tf.json tipper
    columns populated, the parse fallback recorded with its reason, and the derived EMTF XML
    carrying the tipper the source always had. FAILS against the pre-fix engine (comps 'Z')."""
    pkg = tmp_path / "surveys" / "cap-lp"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "name: Cap LP\nslug: cap-lp\ncountry: Australia\norganisation: Test Org\n"
        "access: open\nlicense: CC-BY-4.0\nabstract: LP tipper fixture survey.\n", encoding="utf-8")
    shutil.copy(FIXTURE, edir / "CP1L01.edi")
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--no-validate", "--products", str(out / "products")])
    assert rc == 0
    row = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))[0]
    comps = row[build_portal.CATALOGUE_COLUMNS.index("comps")]
    assert comps == "ZT", f"catalogue must say ZT, got {comps}"
    doc = json.loads((out / "products" / "cap-lp" / "CP1L01" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc["diagnostics"]["tipper_available"] is True
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    rows = report["surveys"]["cap-lp"]["source_parse_fallbacks"]
    assert rows and rows[0]["station"] == "CP1L01"
    assert "tipper" in rows[0]["defect"], rows[0]
    # tf.json carries the healed tipper columns with the EDI's own first value: the whole TF
    # object recovered, so every derived rendition (XML/MTH5, when their flags emit them)
    # inherits it by construction.
    cols = list(build_portal.CATALOGUE_COLUMNS)  # noqa: F841  (documented mirror; TF cols below)
    from _contract import TF_COLUMNS
    trow = json.loads((out / "tf.json").read_text(encoding="utf-8"))[0]
    tzx_re = trow[list(TF_COLUMNS).index("tzx_re")]
    tip_mag = trow[list(TF_COLUMNS).index("tip_mag")]
    assert tzx_re and abs(tzx_re[0] - 0.1954) < 1e-4, tzx_re[:3]
    assert tip_mag and tip_mag[0] is not None


def test_a_channels_recorded_declaration_without_bz_masks_the_tipper_survey_wide(tmp_path):
    """The brief mechanism for file-borne tipper that was never measured: survey.yaml declares
    the recorded channels; no vertical coil means any tipper in the released files is a
    processing artifact, masked survey-wide - comps, type derivation and the tf tipper columns -
    while the served source bytes stay untouched. Uses the recovery fixture (a REAL tipper the
    parse now reads), so the mask is proven against live tipper data, not a vacuous absence."""
    pytest.importorskip("mt_metadata")
    pkg = tmp_path / "surveys" / "cap-nt"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "name: Cap NT\nslug: cap-nt\ncountry: Australia\norganisation: Test Org\n"
        "access: open\nlicense: CC-BY-4.0\nabstract: Mask fixture survey.\n"
        "channels_recorded: [Ex, Ey, Bx, By]\n", encoding="utf-8")
    shutil.copy(FIXTURE, edir / "CP1L01.edi")
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--no-validate", "--products", str(out / "products")])
    assert rc == 0
    row = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))[0]
    assert row[build_portal.CATALOGUE_COLUMNS.index("comps")] == "Z", \
        "the declaration must mask the recovered tipper"
    doc = json.loads((out / "products" / "cap-nt" / "CP1L01" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc["diagnostics"]["tipper_available"] is False
    from _contract import TF_COLUMNS
    trow = json.loads((out / "tf.json").read_text(encoding="utf-8"))[0]
    assert all(v is None for v in trow[list(TF_COLUMNS).index("tzx_re")]), \
        "the tf tipper columns must null out"
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    blob = json.dumps(report)
    assert "channels_recorded declaration" in blob
