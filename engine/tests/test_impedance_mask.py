"""The placeholder-impedance mask: the electric half of the channels_recorded declaration.

A survey that states its recorded channels without Ex/Ey measured no electric field, so an
impedance block in one of its released files is a conversion artifact and every product AusMT
derives from it is an invention. The tipper mask (no vertical coil -> no tipper products) is the
shipped precedent this mirrors, but the twin is NOT symmetric and this file pins the three ways it
differs:

  * it nulls TWELVE tf columns, not five: rho_xy/rho_yx, phs_xy/phs_yx_adj, the four phase-tensor
    invariants (computed from Z) and the four errors propagated from the impedance error;
  * it nulls the impedance-derived SCIENCE row too, which the tipper mask has no equivalent for,
    because _edi_science back-derives rho/phase FROM Z when the source carries no RHO/PHS blocks -
    so an unmasked flat placeholder publishes a smooth power law, a flat 45-degree phase and a
    non-zero quality score, which is the thing the rule exists to stop;
  * and part of it has to run at READ time, because a fabricated impedance block whose length
    disagrees with the section's NFREQ makes the whole file unreadable, tipper and all.

Fixtures are MINTED, never custodian bytes; each names in its own >INFO block the staged file whose
shape it reproduces. The negative control is the repo's own Vulcan sample EDI, a real broadband
impedance that the mask must never touch.
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
import cache as cache_mod   # noqa: E402
from _contract import SCI_COLUMNS, TF_COLUMNS   # noqa: E402

PLACEHOLDER = HERE / "fixtures" / "impedance" / "placeholder-impedance-tipper.edi"
BROKEN_Z = HERE / "fixtures" / "impedance" / "zblock-length-mismatch.edi"
REAL_Z = REPO / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"

_SC = {n: i for i, n in enumerate(SCI_COLUMNS)}
_TC = {n: i for i, n in enumerate(TF_COLUMNS)}

SURVEY_YAML = ("schema_version: \"0.1\"\nname: {name}\nslug: {slug}\ncountry: Australia\n"
               "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
               "abstract: Impedance mask fixture survey.\n{channels}")


def _survey(tmp_path, slug, source, channels=None, name="Mask Fixture"):
    """A one-station package around `source`, with or without a channels_recorded declaration."""
    pkg = tmp_path / "surveys" / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        SURVEY_YAML.format(name=name, slug=slug,
                           channels=(f"channels_recorded: [{', '.join(channels)}]\n"
                                     if channels else "")),
        encoding="utf-8")
    shutil.copy(source, edir / source.name)
    return pkg


def _build(tmp_path, extra=()):
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--no-validate", "--products", str(out / "products"), *extra])
    assert rc == 0
    return out


# The flag set that turns on every AusMT-DERIVED rendition of a station: the served EMTF XML (and
# the survey zip built from it), the tier-1 per-station MTH5 and the tier-2 survey MTH5 bundle.
# deploy/Makefile runs the production build with these, so a mask proven only under the default
# flags is proven over a strict subset of what ships.
_DERIVED_RENDITIONS = ("--bundle-edi", "--survey-h5", "--station-h5")


def _rows(out):
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    tf = json.loads((out / "tf.json").read_text(encoding="utf-8"))
    sci = json.loads((out / "sci.json").read_text(encoding="utf-8"))
    return cat[0], tf[0], sci[0]


# ---------------------------------------------------------------------------------------------
# 1. what the placeholder publishes with NO declaration: the state the rule is about.
# ---------------------------------------------------------------------------------------------

def test_an_undeclared_placeholder_publishes_derived_science_from_a_fabricated_impedance(tmp_path):
    """The RED state, pinned as a fact rather than assumed: with no channels_recorded declaration
    the flat Z=1+1i is read as data and the corpus publishes a smooth power-law resistivity, a flat
    45-degree phase and a non-zero quality score. This test must keep PASSING after the mask ships -
    the mask is keyed on the declaration, so a survey that declares nothing is unchanged."""
    _survey(tmp_path, "undeclared", PLACEHOLDER)
    row, trow, srow = _rows(_build(tmp_path))
    assert row[build_portal.CATALOGUE_COLUMNS.index("comps")] == "ZT"
    rho = trow[_TC["rho_xy"]]
    phs = trow[_TC["phs_xy"]]
    assert rho and all(v is not None for v in rho), rho
    assert phs and all(abs(v - 45.0) < 1e-6 for v in phs), phs
    # a smooth power law: rho = 0.2*T*|Z|^2 with |Z| constant, so each doubled period doubles rho
    assert abs(rho[1] / rho[0] - 2.0) < 1e-6, rho[:3]
    assert srow[_SC["q"]] is not None and srow[_SC["q"]] > 0, srow


# ---------------------------------------------------------------------------------------------
# 2. the mask itself: twelve tf columns, the science row, the tipper untouched.
# ---------------------------------------------------------------------------------------------

def test_the_declaration_without_electric_channels_masks_every_impedance_product(tmp_path):
    """The whole mask over BUILT output. FAILS against the pre-fix engine, which publishes comps ZT
    with populated rho/phase columns and a quality score derived from the fabrication."""
    _survey(tmp_path, "masked", PLACEHOLDER, channels=["Bx", "By", "Bz"])
    out = _build(tmp_path)
    row, trow, srow = _rows(out)

    assert row[build_portal.CATALOGUE_COLUMNS.index("comps")] == "T", \
        "the declaration must drop Z from the published components"
    assert row[build_portal.CATALOGUE_COLUMNS.index("type")] == "GDS", \
        "a tipper-only station reclassifies as GDS"

    for col in build_portal._TF_IMPEDANCE_COLUMNS:
        assert all(v is None for v in trow[_TC[col]]), f"{col} survived the mask: {trow[_TC[col]][:3]}"
    for col in ("tip_mag", "tzx_re", "tzx_im", "tzy_re", "tzy_im"):
        assert any(v is not None for v in trow[_TC[col]]), f"the mask took the tipper column {col}"
    assert trow[_TC["periods"]], "the period axis is not derived from Z and must survive"

    for col in ("q", "dim", "p3d", "ellip", "skew", "mre"):
        assert srow[_SC[col]] is None, f"science field {col} survived the mask: {srow[_SC[col]]}"
    assert srow[_SC["decades"]], "decades is the period span and owes nothing to Z"

    doc = json.loads((out / "products" / "masked" / "MASKZ1" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc["diagnostics"]["tipper_available"] is True
    assert doc["diagnostics"]["completeness_smoothness_diagnostic"]["value"] is None, \
        doc["diagnostics"]["completeness_smoothness_diagnostic"]
    assert doc["diagnostics"]["median_relative_error"] is None, doc["diagnostics"]

    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    warnings = report["surveys"]["masked"]["warnings"]
    assert any("impedance masked survey-wide by the channels_recorded declaration" in w
               for w in warnings), warnings


def test_the_masked_columns_are_exactly_the_twelve_the_impedance_gives(tmp_path):
    """The count the audit corrected the handover on, pinned by NAME so a contract reorder cannot
    silently move the mask onto a different column. Twelve go; periods and the five tipper columns
    stay; the two sets partition TF_COLUMNS with nothing left over and nothing counted twice."""
    tipper = ("tip_mag", "tzx_re", "tzx_im", "tzy_re", "tzy_im")
    masked = set(build_portal._TF_IMPEDANCE_COLUMNS)
    assert len(build_portal._TF_IMPEDANCE_COLUMNS) == 12, build_portal._TF_IMPEDANCE_COLUMNS
    assert len(masked) == 12, "the impedance column list repeats a column"
    assert masked.isdisjoint(tipper), masked & set(tipper)
    assert masked | set(tipper) | {"periods"} == set(TF_COLUMNS), \
        set(TF_COLUMNS) - (masked | set(tipper) | {"periods"})
    assert build_portal._TF_IMPEDANCE_INDEXES == tuple(TF_COLUMNS.index(c)
                                                       for c in build_portal._TF_IMPEDANCE_COLUMNS)


def test_the_science_mask_keeps_the_facts_that_do_not_come_from_the_impedance():
    """The sci-row half in isolation. The null convention is _SCI_WITHHELD_SCIENCE's, single-sourced
    from the access gate's, MINUS decades: that gate withholds the period curves as well, this one
    does not, so a tipper-only station keeps its period span. rr/sw/alg are processing metadata."""
    row = [None] * len(SCI_COLUMNS)
    row[_SC["q"]], row[_SC["qb"]] = 4.2, "e"
    row[_SC["dim"]], row[_SC["skew"]] = "2D", 1.5
    row[_SC["rr"]], row[_SC["sw"]], row[_SC["alg"]] = 1, "BIRRP", "remote reference"
    row[_SC["decades"]] = 3.1
    out = build_portal.mask_impedance_sci_row(row)
    assert out[_SC["q"]] is None and out[_SC["dim"]] is None and out[_SC["skew"]] is None
    assert out[_SC["rr"]] == 1 and out[_SC["sw"]] == "BIRRP" and out[_SC["alg"]] == "remote reference"
    assert out[_SC["decades"]] == 3.1
    assert "decades" not in build_portal._SCI_IMPEDANCE_DERIVED
    assert set(build_portal._SCI_IMPEDANCE_DERIVED) | {"decades"} == set(build_portal._SCI_WITHHELD_SCIENCE)


# ---------------------------------------------------------------------------------------------
# 3. the negative control: a REAL impedance is not touched, declaration or no declaration.
# ---------------------------------------------------------------------------------------------

def test_a_real_impedance_survey_is_untouched_when_it_declares_its_electric_channels(tmp_path):
    """The control that keeps the mask a declaration mechanism and not an impedance filter: the
    repo's own Vulcan broadband EDI, published under a declaration that names Ex and Ey, comes
    through with every impedance product intact."""
    _survey(tmp_path, "real-z", REAL_Z, channels=["Ex", "Ey", "Bx", "By"], name="Real Z")
    out = _build(tmp_path)
    row, trow, srow = _rows(out)
    assert "Z" in row[build_portal.CATALOGUE_COLUMNS.index("comps")]
    assert any(v is not None for v in trow[_TC["rho_xy"]])
    assert srow[_SC["q"]] is not None
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    assert not any("impedance masked" in w for w in report["surveys"]["real-z"]["warnings"])


def test_the_same_build_with_and_without_the_declaration_differs_only_where_the_mask_bites(tmp_path):
    """A real-impedance survey built twice, once declaring Ex/Ey and once declaring nothing: the two
    catalogues are identical. The mask is keyed on a POSITIVE declaration of the electric channels,
    so the whole existing corpus - which declares no channels at all - is provably inert under it."""
    _survey(tmp_path / "a", "real-z", REAL_Z, channels=["Ex", "Ey", "Bx", "By"], name="Real Z")
    _survey(tmp_path / "b", "real-z", REAL_Z, name="Real Z")
    a, b = _rows(_build(tmp_path / "a")), _rows(_build(tmp_path / "b"))
    assert a[1] == b[1], "tf rows diverged between a declared and an undeclared survey"
    assert a[2] == b[2], "sci rows diverged between a declared and an undeclared survey"


# ---------------------------------------------------------------------------------------------
# 4. the read-time half: a length-broken impedance block costs the station its tipper today.
# ---------------------------------------------------------------------------------------------

def test_a_length_broken_impedance_block_no_longer_costs_the_station_everything():
    """The read fallback, in isolation. Against the pre-fix reader this file raises ValueError from
    mt_metadata's impedance fill and the station is lost outright; after, the impedance blocks (which
    were unreadable either way) are dropped from a temporary copy and the coordinates, the periods
    and the real tipper all survive. The reason is RECORDED, never silent."""
    tf, reason = mtm.read_with_fallback(BROKEN_Z)
    assert reason == mtm.Z_BLOCK_LENGTH_MISMATCH, reason
    assert not tf.has_impedance(), "the unreadable impedance must not come back"
    assert tf.has_tipper() and tf.period.size == 6
    assert tf.latitude == pytest.approx(-18.443)
    assert str(tf.fn) == str(BROKEN_Z), "TF.fn must point at the custodian's file, never the scratch copy"


def test_the_stripper_removes_the_twelve_impedance_blocks_and_nothing_else():
    """The normaliser in isolation: the twelve data blocks and their values go, every other line
    stays byte for byte, and the section banners (which start with '>') are kept."""
    raw = BROKEN_Z.read_bytes()
    fixed = mtm.strip_impedance_blocks(raw)
    assert fixed is not raw
    gone = [ln for ln in raw.splitlines() if ln not in fixed.splitlines()]
    labels = [ln.strip().split()[0] for ln in gone if ln.strip().startswith(b">")]
    assert sorted(labels) == sorted(mtm._Z_DATA_LABELS), labels
    assert b">!****IMPEDANCES****!" in fixed, "a comment banner is not a data block"
    assert b">FREQ" in fixed and b">TXR.EXP" in fixed and b">HEAD" in fixed
    # idempotent, and a file with no impedance blocks is returned unchanged by identity
    assert mtm.strip_impedance_blocks(fixed) is fixed


def test_the_stripper_never_takes_the_rotation_block():
    """`>ZROT` starts with '>Z' and is a rotation angle, not impedance data. The vocabulary is
    mt_metadata's own _z_labels rather than a '>Z' prefix sweep, so it is kept."""
    raw = (b">=MTSECT\n >ZROT //  2\n  0.0  0.0\n >ZXXR //  2\n  1 1\n >END\n")
    fixed = mtm.strip_impedance_blocks(raw)
    assert b">ZROT" in fixed and b"0.0  0.0" in fixed
    assert b">ZXXR" not in fixed


def test_a_readable_file_never_reaches_the_stripper(monkeypatch):
    """The guard that keeps the fallback a rescue and not a policy: the retry is reached only from a
    failed read, so a file that parses - real impedance included - is never stripped. Pinned by
    making the stripper explode: if it were ever called on a healthy read, this test would error."""
    def _boom(_raw):
        raise AssertionError("strip_impedance_blocks was called for a file that parses")
    monkeypatch.setattr(mtm, "strip_impedance_blocks", _boom)
    tf, reason = mtm.read_with_fallback(REAL_Z)
    assert reason is None
    assert tf.has_impedance()


def test_an_unrelated_failure_is_not_swallowed_by_the_impedance_fallback(tmp_path):
    """The signature guard. A ValueError that is not numpy's broadcast refusal inside the reader's
    impedance fill must surface as itself: the file is declined, not stripped."""
    junk = tmp_path / "junk.edi"
    junk.write_bytes(b">HEAD\n  DATAID=\"X\"\n>END\n")
    with pytest.raises(Exception) as ei:
        mtm.read(junk)
    assert not isinstance(ei.value, ValueError) or "broadcast" not in str(ei.value)


def test_the_rescued_station_builds_and_the_declaration_masks_what_is_left(tmp_path):
    """Read time and mask time together, over a built survey: the file that can yield nothing
    now yields a GDS station, and its (already absent) impedance products stay absent. This is the
    halls-creek shape end to end."""
    _survey(tmp_path, "rescued", BROKEN_Z, channels=["Bx", "By", "Bz"], name="Rescued")
    out = _build(tmp_path)
    row, trow, _srow = _rows(out)
    assert row[build_portal.CATALOGUE_COLUMNS.index("comps")] == "T"
    assert all(v is None for v in trow[_TC["rho_xy"]])
    assert any(v is not None for v in trow[_TC["tzx_re"]])
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    entry = report["surveys"]["rescued"]
    assert entry["stations_built"] == 1
    rows = entry["source_parse_fallbacks"]
    assert rows and rows[0]["file"] == BROKEN_Z.name, rows
    assert "impedance data blocks" in rows[0]["defect"], rows[0]


# ---------------------------------------------------------------------------------------------
# 5. what else the fabricated impedance reaches: the sign-convention verdict.
# ---------------------------------------------------------------------------------------------

def test_the_mask_withholds_the_convention_verdict_computed_from_the_fabrication(tmp_path):
    """The sign-convention quadrant check reads the impedance and nothing else, so under the mask
    its verdict IS the withheld phase, restated in degrees. Against the pre-fix build, station.json
    published frame.convention_check = {"verdict": "warn_yx", "phs_xy_median_deg": 45.0,
    "phs_yx_median_deg": 45.0} for the very station whose build_report line says the phase is
    withheld, and the survey warning read that flat 45 degrees as a possible 3D/distortion effect.
    After: the verdict is null and the note is gone, in station.json, in the frame array and in the
    warnings."""
    _survey(tmp_path, "masked", PLACEHOLDER, channels=["Bx", "By", "Bz"])
    out = _build(tmp_path)
    doc = json.loads((out / "products" / "masked" / "MASKZ1" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc["frame"] is not None, "the measured frame facts are not impedance-derived and stay"
    assert doc["frame"]["convention_check"] is None, doc["frame"]["convention_check"]

    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    entry = report["surveys"]["masked"]
    assert not any(w.startswith("convention:") for w in entry["warnings"]), entry["warnings"]
    assert not any("convention:" in n for e in entry["frame"] for n in [e["note"]]), entry["frame"]


def test_an_undeclared_placeholder_still_gets_the_convention_verdict(tmp_path):
    """The other half of the pin: the withholding is the DECLARATION's doing, not a blanket removal.
    With no channels_recorded the same fixture keeps the warn_yx verdict it has always had."""
    _survey(tmp_path, "undeclared", PLACEHOLDER)
    out = _build(tmp_path)
    doc = json.loads((out / "products" / "undeclared" / "MASKZ1" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc["frame"]["convention_check"]["verdict"] == "warn_yx", doc["frame"]["convention_check"]
    assert doc["frame"]["convention_check"]["phs_yx_median_deg"] == 45.0


# ---------------------------------------------------------------------------------------------
# 6. the AusMT-DERIVED renditions: the served EMTF XML and both MTH5 tiers.
# ---------------------------------------------------------------------------------------------

def test_the_mask_withholds_the_derived_xml_and_mth5_renditions(tmp_path):
    """The renditions the mask did not reach. Both emitters RE-READ the source EDI rather than the
    masked record, so against the pre-fix build a masked station republished the fabricated
    Z = 1+1i verbatim in out/xml (Zxy blocks), in its per-station MTH5 and in the survey MTH5
    bundle - all three labelled provenance_role 'derived' in station.json, which is exactly what the
    mask governs. The served EDI keeps the custodian's bytes; the AusMT-derived renditions do not
    ship at all."""
    _survey(tmp_path, "masked", PLACEHOLDER, channels=["Bx", "By", "Bz"])
    out = _build(tmp_path, extra=_DERIVED_RENDITIONS)
    assert not sorted((out / "xml" / "masked").glob("*.xml")), "the derived EMTF XML shipped"
    assert not sorted((out / "h5" / "masked").rglob("*.h5")), "the per-station MTH5 shipped"
    assert not (out / "bundles" / "masked-tf.h5").exists(), "the survey MTH5 bundle shipped"
    # the xml zip is built from the written set, so it goes with the last XML in the survey
    assert not (out / "bundles" / "masked-xml.zip").exists(), "the xml zip shipped"
    # the custodian's own bytes are untouched and still served
    served = out / "edi" / "masked" / PLACEHOLDER.name
    assert served.exists() and served.read_bytes() == PLACEHOLDER.read_bytes()

    manifest = json.loads((out / "products" / "manifest.json").read_text(encoding="utf-8"))
    kinds = {b["kind"] for b in manifest["bundles"] if b.get("survey") == "masked"}
    assert "mth5" not in kinds and "xml-zip" not in kinds, kinds
    assert not [f for f in manifest["files"]
                if str(f.get("path", "")).endswith((".xml", ".h5"))
                and "masked" in str(f.get("path", ""))], "a masked rendition reached the manifest"

    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    assert any("EMTF XML and MTH5 renditions" in w
               for w in report["surveys"]["masked"]["warnings"]), \
        report["surveys"]["masked"]["warnings"]


def test_an_undeclared_placeholder_still_gets_its_derived_renditions(tmp_path):
    """The negative control for the withholding: without the declaration the same fixture ships the
    XML and both MTH5 tiers exactly as it always has, so the withholding cannot be a regression in
    the emitters."""
    _survey(tmp_path, "undeclared", PLACEHOLDER)
    out = _build(tmp_path, extra=_DERIVED_RENDITIONS)
    xml = sorted((out / "xml" / "undeclared").glob("*.xml"))
    assert xml and "Zxy" in xml[0].read_text(encoding="utf-8"), xml
    assert sorted((out / "h5" / "undeclared").glob("*.h5"))
    assert (out / "bundles" / "undeclared-tf.h5").exists()


def test_a_real_impedance_survey_keeps_its_renditions_under_a_full_declaration(tmp_path):
    """The mask is a declaration mechanism, so a survey that declares Ex/Ey keeps every rendition of
    its real impedance. This is the control that stops the withholding drifting into an impedance
    filter."""
    _survey(tmp_path, "real-z", REAL_Z, channels=["Ex", "Ey", "Bx", "By"], name="Real Z")
    out = _build(tmp_path, extra=_DERIVED_RENDITIONS)
    assert sorted((out / "xml" / "real-z").glob("*.xml"))
    assert (out / "bundles" / "real-z-tf.h5").exists()


def test_a_warm_cache_hit_masks_and_withholds_exactly_as_a_cold_build(tmp_path, capfd, monkeypatch):
    """A GUARD on where the mask lives, not a fix for a defect: it passes on both sides of the
    withholding commit and exists to keep passing.

    The whole mask runs AFTER the cache so the cached parse stays survey-independent, and the
    rendition withholding reads a flag stamped at that same seam. Production rebuilds run
    -incremental (deploy/Makefile), so every masked survey after its first build is a cache HIT: if
    that flag ever moved into the cached parse product, a warm rebuild would republish the
    renditions a cold build withholds, and only the warm one would leak. Cold and warm are built
    over one cache dir, the hit is asserted rather than assumed, and the two builds are compared.
    """
    # The cache disables itself on a dirty engine checkout, which every development tree is, so pin
    # the gate's INPUT to clean and the salt's commit to a constant. Same two-line pin as
    # test_build_cache.py's clean_salt fixture, which is file-local to that module.
    monkeypatch.setattr(cache_mod, "_dirty_checkout", lambda cwd: False)
    monkeypatch.setattr(build_portal, "_git_commit_at",
                        lambda cwd: "testpin" if Path(cwd) == build_portal.HERE else None)
    monkeypatch.delenv("AUSMT_ENGINE_COMMIT", raising=False)
    monkeypatch.delenv("AUSMT_CACHE_MAX_MB", raising=False)

    _survey(tmp_path, "masked", PLACEHOLDER, channels=["Bx", "By", "Bz"])
    cache = tmp_path / "cache"
    outs = []
    for name in ("cold", "warm"):
        out = tmp_path / name
        rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                                "--no-validate", "--products", str(out / "products"),
                                *_DERIVED_RENDITIONS,
                                "--incremental", "--cache-dir", str(cache), "--cache-mode", "rw"])
        assert rc == 0
        _cap = capfd.readouterr()
        outs.append((out, _cap.out + _cap.err))
    (cold, _cold_log), (warm, warm_log) = outs
    assert "C18 cache [rw]: hits=1" in warm_log, "the warm build was not a cache hit; guard is vacuous"

    for name in ("catalogue.json", "tf.json", "sci.json"):
        assert (cold / name).read_bytes() == (warm / name).read_bytes(), name
    for out in (cold, warm):
        assert not sorted(out.rglob("*.xml")), f"{out.name}: an EMTF XML shipped"
        assert not sorted(out.rglob("*.h5")), f"{out.name}: an MTH5 shipped"

    def _entry(out):
        e = json.loads((out / "build_report.json").read_text(encoding="utf-8"))["surveys"]["masked"]
        return e["warnings"], e["frame"]
    assert _entry(cold) == _entry(warm)

    def _doc(out):
        d = json.loads((out / "products" / "masked" / "MASKZ1" / "station.json")
                       .read_text(encoding="utf-8"))
        d["provenance"].pop("generated", None)   # the build clock, the one legitimate difference
        return d
    assert _doc(cold) == _doc(warm)
    assert _doc(warm)["frame"]["convention_check"] is None
