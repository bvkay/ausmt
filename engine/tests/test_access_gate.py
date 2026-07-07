"""C1 access-level + embargo serving gate (Invariant 10).

access.level (open | metadata_only | embargoed) and embargo_until were ADVERTISED (template, docs,
form, SMETA, mtcat) but enforced by NOTHING: the serving gate was `can_serve = bundle_edi and
redistributable(lic) and kind=="edi"`. A CC-BY survey marked embargoed/metadata_only still had every
EDI byte-copied and every manifest row emitted. C1 makes the gate additionally require the survey be
OPEN and not under an active embargo.

NON-VACUOUS failure criteria (each fails against the pre-C1 gate or a broken helper):

  Pure gate (stack-less — the logic is pure):
    * open + no embargo                       -> SERVED               (regression: must still serve)
    * open + future embargo_until             -> SERVED               (level is the state of record;
                                                                        a stray date doesn't withhold)
    * metadata_only                           -> NOT served           (pre-C1: served)
    * embargoed + FUTURE date                 -> NOT served, active   (pre-C1: served)
    * embargoed + PAST date                   -> NOT served + STALE-embargo warning
                                                  (DECISION: level is state of record; no silent
                                                   auto-publish on a lapsed date — a curator flips it)
    * embargoed + NO date                     -> NOT served, active, indefinite-embargo warning  (b)
    * embargoed + UNPARSEABLE date            -> NOT served, active, fail-closed warning          (a)
    * level normalisation: absent/None/""/"  OPEN " -> "open"; unknown value passes through

  Build path (drives the real pipeline; requires mt_metadata/mth5):
    * CC-BY + embargoed(future)   -> ZERO manifest rows/bytes, edi_available=0, survey STILL in
                                     catalogue/surveys/mtcat (discovery universal)   (pre-C1: served)
    * CC-BY + metadata_only       -> same
    * CC-BY + embargoed(past)     -> STILL not served (lapsed embargo is not auto-publication)
    * open + no embargo (baseline sample) -> served (regression)
"""
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = ROOT / "data"          # data/sample-survey: CC-BY-4.0, access.level=open => served baseline
sys.path.insert(0, str(ROOT / "extract"))
import build_portal as bp        # noqa: E402


# --------------------------------------------------------------------------- pure gate (stack-less)

def test_normalise_access_level():
    assert bp.normalise_access_level("open") == "open"
    assert bp.normalise_access_level("  OPEN ") == "open", "trim + lowercase"
    assert bp.normalise_access_level(None) == "open", "absent => open (legacy-friendly default)"
    assert bp.normalise_access_level("") == "open", "blank => open"
    assert bp.normalise_access_level("metadata_only") == "metadata_only"
    assert bp.normalise_access_level("Embargoed") == "embargoed"
    # unknown value is passed through normalised (the VALIDATOR rejects the enum; the engine must not
    # crash on a legacy value — an unrecognised level is not "open", so it fails CLOSED at serve time)
    assert bp.normalise_access_level("restricted") == "restricted"


_TODAY = date(2026, 7, 5)
_FUT = (_TODAY + timedelta(days=30)).isoformat()
_PAST = (_TODAY - timedelta(days=30)).isoformat()


def _state(level, embargo=None):
    return bp.access_serve_state(level, embargo, today=_TODAY)


def test_open_no_embargo_serves():
    s = _state("open", None)
    assert s["served"] is True and s["embargo_active"] is False and not s["warnings"]


def test_open_with_future_embargo_still_serves():
    # level is the state of record: an OPEN survey serves even if a stray embargo_until is set.
    s = _state("open", _FUT)
    assert s["served"] is True, "open level serves regardless of a stray embargo date"


def test_metadata_only_not_served():
    s = _state("metadata_only", None)
    assert s["served"] is False and s["embargo_active"] is False


def test_embargoed_future_date_not_served_active():
    s = _state("embargoed", _FUT)
    assert s["served"] is False and s["embargo_active"] is True and not s["warnings"], \
        "a normal future-dated embargo is not a warning condition"


def test_embargoed_past_date_not_served_with_stale_warning():
    # DECISION: a lapsed embargo date does NOT auto-publish. The level is authoritative; surface a
    # stale-embargo warning so a curator flips level->open deliberately.
    s = _state("embargoed", _PAST)
    assert s["served"] is False, "lapsed embargo must NOT auto-serve (silent publication)"
    assert s["embargo_active"] is True
    assert any("stale" in w.lower() or "past" in w.lower() or "lapsed" in w.lower() for w in s["warnings"]), s["warnings"]


def test_embargoed_no_date_indefinite_with_warning():
    s = _state("embargoed", None)                         # decision (b)
    assert s["served"] is False and s["embargo_active"] is True
    assert s["warnings"], "embargoed with no date => indefinite embargo + warning"


def test_embargoed_unparseable_date_fails_closed_with_warning():
    s = _state("embargoed", "soon")                       # decision (a)
    assert s["served"] is False and s["embargo_active"] is True, "unparseable + embargoed => fail closed"
    assert s["warnings"], "unparseable embargo_until must warn loudly"


def test_unknown_level_fails_closed():
    # a legacy/typo'd level that survived (e.g. seed data) is NOT open => must not serve.
    s = _state("restricted", None)
    assert s["served"] is False


# --------------------------------------------------------------------------- build path (real pipeline)

def _build(tmp_path, access_block=None, *extra):
    """Copy the CC-BY sample survey, optionally rewrite its access block, build, return out + docs.
    `extra` passes additional build flags (e.g. --survey-h5) so the same withholding gate can be
    exercised across ALL bundle kinds."""
    staged = tmp_path / "surveys_src"
    shutil.copytree(SURVEYS, staged)
    if access_block is not None:
        for y in staged.rglob("survey.yaml"):
            txt = y.read_text(encoding="utf-8")
            # replace the single-line `access: { level: open }` with the requested block
            lines = [ln for ln in txt.splitlines() if not ln.strip().startswith("access:")]
            lines.append(access_block)
            y.write_text("\n".join(lines) + "\n")
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(staged),
                        "--out", str(out), "--bundle-edi", "--no-validate", *extra],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    smeta = json.loads((out / "surveys.json").read_text(encoding="utf-8"))
    mtcat = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    return out, man, cat, smeta, mtcat, r.stderr


def _edi_available_col(cat):
    # catalogue r[13] = edi_available (positional contract; recompute the index, don't hard-code)
    from _contract import CATALOGUE_COLUMNS
    return CATALOGUE_COLUMNS.index("edi_available")


def test_open_baseline_serves(tmp_path):
    """Regression: the unmodified CC-BY open sample survey still serves bytes."""
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    out, man, cat, smeta, mtcat, _err = _build(tmp_path)          # no access rewrite
    assert man["files"], "open CC-BY survey must still be served"
    i = _edi_available_col(cat)
    assert any(row[i] == 1 for row in cat), "at least one station must be edi_available"
    assert (out / "edi").exists(), "served EDI bytes must be written"


@pytest.mark.parametrize("access_block", [
    f"access: {{ level: embargoed, embargo_until: {(date.today()+timedelta(days=365)).isoformat()} }}",
    "access: { level: metadata_only }",
    f"access: {{ level: embargoed, embargo_until: {(date.today()-timedelta(days=365)).isoformat()} }}",
])
def test_withheld_surveys_serve_no_bytes_but_stay_discoverable(tmp_path, access_block):
    """CC-BY + (embargoed future | metadata_only | embargoed past) => ZERO served bytes/rows, yet the
    survey is fully discoverable in catalogue/surveys/mtcat. FAILS against the pre-C1 gate (everything
    with a redistributable licence served)."""
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    out, man, cat, smeta, mtcat, _err = _build(tmp_path, access_block)
    # bytes withheld
    assert man["files"] == [] and man["bundles"] == [], f"withheld survey must have NO manifest rows: {man}"
    assert man["generated_count"] == 0
    assert not (out / "edi").exists(), "no served EDI bytes for a withheld survey"
    i = _edi_available_col(cat)
    assert cat and all(row[i] == 0 for row in cat), "every station must be edi_available=0"
    # discovery universal: the survey is still in every discovery surface
    assert cat, "stations must still be catalogued (discovery is universal)"
    assert smeta, "survey metadata must still be published"
    assert mtcat["surveys"], "survey must still appear in mtcat (federation discovery)"


@pytest.mark.parametrize("access_block", [
    f"access: {{ level: embargoed, embargo_until: {(date.today()+timedelta(days=365)).isoformat()} }}",
    "access: { level: metadata_only }",
])
def test_embargoed_survey_emits_none_of_the_three_bundles(tmp_path, access_block):
    """C32 §1.3 / §4: the two new bundles (EMTF-XML zip, TF MTH5) flow through the IDENTICAL can_serve
    gate as the EDI zip — so a withheld survey emits NONE of the three, even with --survey-h5 ON. FAILS
    if any bundle row is emitted OR any bundle file lands on disk for a withheld survey. (The pre-C32
    generic 'bundles == []' assertion never exercised the flag-gated MTH5 path; this does.)"""
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    out, man, cat, smeta, mtcat, _err = _build(tmp_path, access_block, "--survey-h5")
    assert man["bundles"] == [], f"a withheld survey must emit NO bundle rows (any kind): {man['bundles']}"
    # no bundle bytes on disk either: no edi-zip, no xml-zip, no -tf.h5
    bdir = out / "bundles"
    on_disk = sorted(p.name for p in bdir.glob("*")) if bdir.exists() else []
    assert on_disk == [], f"withheld survey wrote bundle bytes to disk: {on_disk}"
    # survey still fully discoverable (the gate withholds bytes, never discovery)
    assert cat and smeta and mtcat["surveys"], "withheld survey stays in catalogue/surveys/mtcat"


def test_embargoed_survey_smeta_badges_honestly(tmp_path):
    """SMETA must carry access_level + embargo_until so the portal can badge the withholding honestly."""
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    fut = (date.today() + timedelta(days=365)).isoformat()
    out, man, cat, smeta, mtcat, _err = _build(
        tmp_path, f"access: {{ level: embargoed, embargo_until: {fut} }}")
    entry = next(iter(smeta.values()))
    assert entry.get("access") == "embargoed", f"SMETA must carry the normalised level: {entry.get('access')}"
    assert entry.get("embargo_until") == fut, f"SMETA must carry embargo_until: {entry.get('embargo_until')}"
    # mtcat access field carries the normalised level and stays a string (schema-valid)
    sv = mtcat["surveys"][0]
    assert sv["access"] == "embargoed" and isinstance(sv["access"], str)


# --------------------------------------------------------------------------- C1b: DISPLAY-PRODUCT gate
# C1 withholds the BYTES (manifest/edi/xml/bundles); C1b extends the gate to the DERIVED DISPLAY products
# the portal PLOTS. For an embargoed dataset the response curves ARE the data — a portal that plots the
# thinned tf.json curves for an embargoed survey has published the data it withheld from download. So for
# a non-served survey the tf.json series columns become EMPTY ARRAYS and the sci.json science-derived
# fields are nulled; the CATALOGUE row (locations/band/nper/sha256) stays public (discovery is universal),
# and the processing-metadata sci fields (rr/sw/alg) stay (metadata, not data). --products station.json is
# a curator artifact, not a distribution surface, so it is deliberately NOT asserted-empty here.

def _tf_sci(out):
    """Load the emitted portal projections (tf.json, sci.json) from a build's out dir."""
    return (json.loads((out / "tf.json").read_text(encoding="utf-8")),
            json.loads((out / "sci.json").read_text(encoding="utf-8")))


def _sci_idx():
    from _contract import SCI_COLUMNS, TF_COLUMNS
    return SCI_COLUMNS, TF_COLUMNS


# The sci columns split into science-DERIVED (withheld for a non-served survey) and processing-METADATA
# (kept — metadata is not the embargoed data). Mirrors the DESIGN in build_portal's projection loop.
_SCI_SCIENCE = ("q", "qb", "dim", "p3d", "gd", "ellip", "skew", "mre", "decades")
_SCI_METADATA = ("rr", "sw", "alg")


def test_embargoed_survey_withholds_display_curves(tmp_path):
    """C1b (THIS FAILS pre-fix — the curves are present in tf.json / sci.json for an embargoed survey):
    an embargoed CC-BY survey must have EVERY tf.json series column an EMPTY ARRAY (row width + station
    alignment preserved) and its sci.json science-derived fields WITHHELD, while the processing-metadata
    sci fields (rr/sw/alg) and the whole catalogue row stay public."""
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    fut = (date.today() + timedelta(days=365)).isoformat()
    out, man, cat, smeta, mtcat, _err = _build(
        tmp_path, f"access: {{ level: embargoed, embargo_until: {fut} }}")
    SCI_COLUMNS, TF_COLUMNS = _sci_idx()
    tf, sci = _tf_sci(out)
    assert cat, "the survey must still be catalogued (discovery is universal)"
    # station alignment preserved: one tf row and one sci row per catalogued station.
    assert len(tf) == len(cat) == len(sci), "row alignment must be preserved when curves are withheld"
    for row in tf:
        # width guard: still exactly one entry per TF_COLUMN (an empty [] per series, NOT a dropped column)
        assert len(row) == len(TF_COLUMNS), f"tf row width drifted: {len(row)} != {len(TF_COLUMNS)}"
        for name, series in zip(TF_COLUMNS, row):
            assert series == [], f"tf column {name!r} must be an EMPTY ARRAY for an embargoed survey, got {series!r}"
    sc_i = {n: k for k, n in enumerate(SCI_COLUMNS)}
    for row in sci:
        assert len(row) == len(SCI_COLUMNS), f"sci row width drifted: {len(row)} != {len(SCI_COLUMNS)}"
        # science-derived fields withheld (per each column's null convention: q/mre/skew/... -> None,
        # qb -> 's', dim -> None, p3d/ellip -> None, gd/decades -> 0 — the SAME shape a no-periods row has)
        for name in _SCI_SCIENCE:
            v = row[sc_i[name]]
            assert v in (None, "s", 0, ""), f"sci science field {name!r} must be withheld, got {v!r}"


def test_open_baseline_curves_present(tmp_path):
    """Regression: the unmodified OPEN CC-BY sample survey still emits real curves — at least one tf row
    carries a non-empty periods array and at least one sci row a non-null dimensionality/q. (Guards that
    the C1b withholding is CONDITIONAL on access, not a blanket wipe.)"""
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    out, man, cat, smeta, mtcat, _err = _build(tmp_path)          # no access rewrite => open
    SCI_COLUMNS, TF_COLUMNS = _sci_idx()
    tf, sci = _tf_sci(out)
    peri = TF_COLUMNS.index("periods")
    assert any(row[peri] for row in tf), "an OPEN survey must still emit non-empty period arrays"
    q_i = SCI_COLUMNS.index("q")
    assert any(row[q_i] is not None for row in sci), "an OPEN survey must still emit science-derived q values"


def test_metadata_only_survey_also_withholds_curves(tmp_path):
    """metadata_only is a non-served state too — its display curves are withheld exactly like an embargo."""
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    out, man, cat, smeta, mtcat, _err = _build(tmp_path, "access: { level: metadata_only }")
    _sci_cols, TF_COLUMNS = _sci_idx()
    tf, _sci = _tf_sci(out)
    assert cat, "metadata_only survey stays catalogued"
    assert tf and all(all(series == [] for series in row) for row in tf), \
        "metadata_only survey must have every tf series empty (curves are data)"


def test_withheld_build_passes_verify_data_dir(tmp_path):
    """The embargoed build's emitted products must still pass verify.py --data-dir (the width guard and
    the mtcat/manifest schema self-checks hold with empty curves — a valid, published-minus-the-data build)."""
    pytest.importorskip("mt_metadata")
    pytest.importorskip("mth5")
    fut = (date.today() + timedelta(days=365)).isoformat()
    out, _man, _cat, _smeta, _mtcat, _err = _build(
        tmp_path, f"access: {{ level: embargoed, embargo_until: {fut} }}")
    r = subprocess.run([sys.executable, "scripts/verify.py", "--data-dir", str(out)],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"verify.py --data-dir failed on the withheld build:\n{r.stdout}\n{r.stderr}"
