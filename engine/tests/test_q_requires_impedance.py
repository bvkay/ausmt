"""The completeness/smoothness score is withheld wherever there is no impedance to score.

`q` is built from an apparent resistivity and a phase, both of which come from the impedance. On a
tipper-only station there is neither, and the shape-based branch of the formula collapses to period
coverage plus a constant: a number that reads as an assessed diagnostic without being one. The rule
is that such a station publishes no score, uniformly, for whichever reason it lacks an impedance.

Two reasons reach the same physical situation and must not publish differently:

  * a survey that declares its recorded channels WITHOUT Ex/Ey has any impedance in its released
    files masked as a conversion artifact, and the mask nulled q with the rest of the impedance-
    derived science (test_impedance_mask pins that half);
  * a file that never carried an impedance block at all was masked by nothing, so it reached
    _edi_science with a tipper and a period axis and was scored on those alone.

Within one survey both cases occur - a magnetometer array whose registry files were regenerated
without their fabricated impedance, beside siblings still carrying one - so the same array published
some stations with a score and some without. The decision now sits once, in _edi_science, on the
component dict's own impedance presence, which is the catalogue components column's decision carried
through the single parse/science seam rather than a second test of the same fact.

Fixtures are MINTED, never custodian bytes; the tipper-only one names in its own >INFO block the
corpus station whose shape it reproduces. The negative control is the repo's own Vulcan sample EDI
and the Pilbara tipper fixture: real impedances, whose scores this rule must not move by a digit.
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
import _edi_science as sci   # noqa: E402
import _mtm as mtm           # noqa: E402
import build_portal          # noqa: E402
from _contract import SCI_COLUMNS, TF_COLUMNS   # noqa: E402

TIPPER_ONLY = HERE / "fixtures" / "impedance" / "tipper-only-no-impedance.edi"
PLACEHOLDER = HERE / "fixtures" / "impedance" / "placeholder-impedance-tipper.edi"
REAL_Z = REPO / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
REAL_ZT = HERE / "fixtures" / "tipper" / "CP1L01.edi"

_SC = {n: i for i, n in enumerate(SCI_COLUMNS)}
_TC = {n: i for i, n in enumerate(TF_COLUMNS)}

SURVEY_YAML = ("schema_version: \"0.1\"\nname: {name}\nslug: {slug}\ncountry: Australia\n"
               "organisation: Test Org\naccess: open\nlicense: CC-BY-4.0\n"
               "abstract: Impedance-presence fixture survey.\n{channels}")


def _survey(tmp_path, slug, source, channels=None, name="Presence Fixture"):
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


def _build(tmp_path):
    out = tmp_path / "out"
    rc = build_portal.main(["--surveys", str(tmp_path / "surveys"), "--out", str(out),
                            "--no-validate", "--products", str(out / "products")])
    assert rc == 0
    return out


def _rows(out, i=0):
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    tf = json.loads((out / "tf.json").read_text(encoding="utf-8"))
    scirows = json.loads((out / "sci.json").read_text(encoding="utf-8"))
    return cat[i], tf[i], scirows[i]


def _sci_row(path):
    """The science row a source file produces, by name, straight through the library entry."""
    per, comp = mtm.components(path)
    return dict(zip(SCI_COLUMNS, sci.science_from_components(per, comp, mtm.proc_info(path))))


# ---------------------------------------------------------------------------------------------
# 1. the rule, over BUILT output: a station with no impedance publishes no score.
# ---------------------------------------------------------------------------------------------

def test_a_tipper_only_station_publishes_no_completeness_smoothness_score(tmp_path):
    """The fixture declares NOTHING, so no mask can be what withholds the score. FAILS against the
    pre-fix engine, which publishes q 1.5 on this file from its period span alone."""
    _survey(tmp_path, "tipper-only", TIPPER_ONLY)
    out = _build(tmp_path)
    row, trow, srow = _rows(out)

    assert row[build_portal.CATALOGUE_COLUMNS.index("comps")] == "T", \
        "the fixture must reach the science layer as a tipper-only station"
    assert srow[_SC["q"]] is None, \
        f"a station with no impedance published a score: {srow[_SC['q']]}"
    assert srow[_SC["qb"]] == "s", \
        "the withheld basis must match the null convention the empty row and the mask use"

    # what the rule must NOT take with it
    assert srow[_SC["decades"]], "decades is the period span and owes the impedance nothing"
    for col in ("tip_mag", "tzx_re", "tzx_im", "tzy_re", "tzy_im"):
        assert any(v is not None for v in trow[_TC[col]]), f"the rule took the tipper column {col}"
    assert trow[_TC["periods"]], "the period axis must survive"

    doc = json.loads((out / "products" / "tipper-only" / "TIPONLY1" / "station.json")
                     .read_text(encoding="utf-8"))
    assert doc["diagnostics"]["tipper_available"] is True
    assert doc["diagnostics"]["completeness_smoothness_diagnostic"]["value"] is None, \
        doc["diagnostics"]["completeness_smoothness_diagnostic"]


def test_the_score_is_withheld_whether_or_not_a_declaration_masks_the_station(tmp_path):
    """The uniformity the rule asks for, as one assertion over the two ways a station ends up with
    no impedance: a file that never carried one (no declaration to mask it) and a fabricated one the
    channels_recorded declaration masks. Same physical situation, same published row."""
    _survey(tmp_path, "never-had-one", TIPPER_ONLY, name="Never Had One")
    _survey(tmp_path, "masked-away", PLACEHOLDER, channels=["Bx", "By", "Bz"], name="Masked Away")
    out = _build(tmp_path)
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    scirows = json.loads((out / "sci.json").read_text(encoding="utf-8"))
    comps = build_portal.CATALOGUE_COLUMNS.index("comps")

    assert len(cat) == 2, cat
    assert {r[comps] for r in cat} == {"T"}, "both stations must publish as tipper-only"
    assert [s[_SC["q"]] for s in scirows] == [None, None], \
        f"the two paths to 'no impedance' still publish different scores: {scirows}"
    assert {s[_SC["qb"]] for s in scirows} == {"s"}, scirows


def test_a_declaration_over_a_file_with_no_impedance_changes_nothing(tmp_path):
    """The mask is keyed on a POSITIVE declaration of the electric channels and has nothing to bite
    on here, so declaring Bx/By/Bz over the tipper-only file must produce the same row as declaring
    nothing. Pins that the rule is the file's own impedance presence, not the declaration."""
    _survey(tmp_path, "undeclared", TIPPER_ONLY, name="Undeclared")
    plain = json.loads((_build(tmp_path) / "sci.json").read_text(encoding="utf-8"))

    other = tmp_path / "second"
    _survey(other, "declared", TIPPER_ONLY, channels=["Bx", "By", "Bz"], name="Declared")
    declared = json.loads((_build(other) / "sci.json").read_text(encoding="utf-8"))

    assert plain == declared, (plain, declared)


# ---------------------------------------------------------------------------------------------
# 2. the blast radius: q and nothing else.
# ---------------------------------------------------------------------------------------------

def test_the_score_is_the_only_field_a_tipper_only_station_can_lose():
    """Every OTHER science field is already at its withheld value on a station with no impedance -
    the dimensionality call, the phase-tensor statistics and the median relative error all need a Z
    the station does not have, and the galvanic heuristic needs both resistivity modes. So the rule
    can only reach q, and a corpus rebuilt under it can only differ in q. Processing metadata and
    the period span are kept, for the same reason the mask keeps them."""
    row = _sci_row(TIPPER_ONLY)
    assert row["q"] is None and row["qb"] == "s"
    for field in ("dim", "p3d", "ellip", "skew", "mre"):
        assert row[field] is None, f"{field} is not null on a station with no impedance: {row}"
    assert row["gd"] == 0, row
    assert row["rr"] == 0 and row["decades"] == 1.4, row
    # the same statement, read off the mask's own null convention: withholding q here lands the row
    # exactly where mask_impedance_sci_row would, so the two seams cannot disagree.
    masked = build_portal.mask_impedance_sci_row([row[c] for c in SCI_COLUMNS])
    assert masked == [row[c] for c in SCI_COLUMNS], masked


def test_the_impedance_presence_test_is_the_components_columns_own():
    """The rule reuses the decision that fills the catalogue components column rather than making a
    second one: _mtm.components_from_tf writes the Z series only under tf.has_impedance, the same
    test that puts "Z" in components. Pinned in both directions over all four fixtures, so a change
    to either side that breaks the equivalence fails here rather than in a corpus diff."""
    for path in (TIPPER_ONLY, PLACEHOLDER, REAL_Z, REAL_ZT):
        _per, comp = mtm.components(path)
        assert sci.has_impedance(comp) == ("Z" in mtm.parse_edi(path)["components"]), path.name


# ---------------------------------------------------------------------------------------------
# 3. the negative control: a real impedance scores exactly what it scored before.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    # station A1 of vulcan: a clean broadband impedance with error blocks, at the top of the scale.
    (REAL_Z, {"q": 5.0, "qb": "e", "rr": 0, "sw": None, "alg": None, "dim": "2-D", "p3d": 0,
              "gd": 0, "ellip": 0.127, "skew": 0.7, "mre": 0.019, "decades": 6.1}),
    # CP1L01: a noisier Pilbara station, mid-scale, so the pin is not a saturated 5.0 that a
    # recomputation could hit by accident.
    (REAL_ZT, {"q": 1.8, "qb": "e", "rr": 0, "sw": None, "alg": None, "dim": "indeterminate",
               "p3d": 57, "gd": 0, "ellip": 0.428, "skew": 4.4, "mre": 0.649, "decades": 3.5}),
])
def test_a_station_with_an_impedance_scores_what_it_scored_before(path, expected):
    """Value-for-value, the rows these two files produced before the rule existed."""
    assert _sci_row(path) == expected


def test_a_masked_placeholder_still_publishes_no_score(tmp_path):
    """The mask's own case, restated here so the two rules are pinned together: a fabricated flat Z
    under a declaration naming no electric channels publishes no score. This is what
    test_impedance_mask asserts as part of the whole mask; the point of repeating it is that the
    number it must equal is now the SAME null the tipper-only station above publishes."""
    _survey(tmp_path, "masked", PLACEHOLDER, channels=["Bx", "By", "Bz"], name="Masked")
    _row, _trow, srow = _rows(_build(tmp_path))
    assert srow[_SC["q"]] is None and srow[_SC["qb"]] == "s", srow
