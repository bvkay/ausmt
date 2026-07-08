"""Phase-1 canonical ingest: the round-trip acceptance gate, on in-repo fixtures.

Locks that `ausmt_science.ingest.normalize.normalize` produces a canonical EMTF XML whose impedance
survives an EDI -> XML -> re-read round-trip, for BOTH a standard TF EDI and the Phoenix EMpower
spectra-section dialect (the hard case the retired regex extractor could not read). Requires the
core mt_metadata/mth5 engine; importorskips when absent, and runs in the build CI job's full suite.
"""
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))  # make the ausmt_science package importable from a source checkout

from ausmt_science.ingest.normalize import (  # noqa: E402
    condition_tf, normalize, source_station_id_from_geographic_name)

STANDARD = REPO / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
SPECTRA = HERE / "real_dialects" / "phoenix_empower_A01.edi"


@pytest.mark.parametrize("src,survey", [(STANDARD, "vulcan"), (SPECTRA, "jupiter")])
def test_normalize_roundtrip(tmp_path, src, survey):
    assert src.exists(), f"fixture missing: {src}"
    res = normalize(src, tmp_path, survey_id=survey)
    assert res.canonical_xml.exists() and res.canonical_xml.stat().st_size > 0
    assert res.derived_edi.exists() and res.derived_edi.stat().st_size > 0
    assert res.n_periods > 0
    # the QC gate: impedance is preserved through the canonical round-trip
    assert res.roundtrip_maxdiff < 1e-3, res.roundtrip_maxdiff
    assert res.versions.get("mt_metadata")


def test_normalize_raises_on_unreadable(tmp_path):
    bad = tmp_path / "not_an_edi.edi"
    bad.write_text("this is not a transfer function\n", encoding="utf-8")
    with pytest.raises(Exception):
        normalize(bad, tmp_path, survey_id="x")


def test_normalize_rejects_empty_tf(tmp_path):
    """A header-only EDI (valid coords, NO impedance/periods) must NOT be certified: the round-trip
    gate's np.allclose over empty arrays is vacuously True, so without the n>0 guard a 'verified'
    canonical XML with no data would be published. normalize must raise (the engine may reject it on
    read, or the n>0 guard catches a reads-but-empty TF) — either way, no certified artifact."""
    empty = tmp_path / "EMPTY01.edi"
    empty.write_text('>HEAD\nDATAID="EMPTY01"\nLAT=-30:08:45\nLONG=136:58:30\n>END\n', encoding="utf-8")
    with pytest.raises(Exception):
        normalize(empty, tmp_path, survey_id="x", station_id="EMPTY01")


# --- C17: the round-trip gate must not vacuously pass a re-read with fewer periods or a dropped
# tipper (the prefix-`min()`-and-allclose the gate used to run over would happily "verify" either).
# We simulate a broken re-read by monkeypatching TF.read so ONLY the SECOND call inside normalize()
# (the canonical-XML round-trip re-read) is mutated afterward — the first call (reading `src`) is
# untouched. This is the least invasive way to produce "an XML re-read that lost data" without
# hand-authoring a doctored XML fixture (mt_metadata's writer output is not hand-editable EMTF-XML).
from mt_metadata.transfer_functions.core import TF  # noqa: E402


def _second_read_hook(mutate):
    """Return a TF.read replacement that runs the real read, then applies `mutate(self)` ONLY on the
    2nd invocation in this call sequence (the gate's re-read of the canonical XML it just wrote)."""
    orig_read = TF.read
    calls = {"n": 0}

    def _read(self, fn=None, file_type=None, get_elevation=False, **kwargs):
        orig_read(self, fn, file_type=file_type, get_elevation=get_elevation, **kwargs)
        calls["n"] += 1
        if calls["n"] == 2:
            mutate(self)
    return _read


def _drop_last_period(tf) -> None:
    tf._transfer_function = tf._transfer_function.isel(period=slice(0, -1))


def _zero_out_tipper(tf) -> None:
    if tf.has_tipper():
        tf._transfer_function.transfer_function.loc[dict(
            input=tf._ch_input_dict["tipper"], output=tf._ch_output_dict["tipper"])] = 0


def test_normalize_rejects_truncated_roundtrip(tmp_path, monkeypatch):
    """A canonical-XML re-read with FEWER periods than the original must FAIL (shape check), not pass
    on the common prefix. Pre-fix, this was verified to pass VACUOUSLY with roundtrip_maxdiff=0.0."""
    monkeypatch.setattr(TF, "read", _second_read_hook(_drop_last_period))
    with pytest.raises(RuntimeError, match="shape mismatch"):
        normalize(STANDARD, tmp_path, survey_id="vulcan")


def test_normalize_rejects_dropped_tipper_roundtrip(tmp_path, monkeypatch):
    """A canonical-XML re-read that silently loses the tipper (present on the original, absent after
    re-read) must FAIL — pre-fix, tipper was never compared at all, so this passed VACUOUSLY."""
    monkeypatch.setattr(TF, "read", _second_read_hook(_zero_out_tipper))
    with pytest.raises(RuntimeError, match="tipper.*MISSING"):
        normalize(SPECTRA, tmp_path, survey_id="jupiter")


# --- Fill-mask fix: some real EDIs (Geotools/MT-GFZ producer; all 57 auslamp-tas stations) carry the
# community missing-data sentinel 1.000000E+32 INSIDE impedance blocks at undetermined periods.
# mt_metadata's EDI reader turns those into 0+0j but its EMTF-XML writer faithfully re-emits the 1e32
# sentinel (D6: the canonical XML stays mt_metadata-faithful), which re-reads as (1e32+1e32j). The
# unmasked gate compared orig 0+0j vs re-read (1e32+1e32j) => maxdiff=sqrt(2)*1e32=1.414e+32 and
# refused to publish a canonical XML. The fix masks fill cells (|v|>_FILL_MAX) on EITHER side in the
# impedance and derived-EDI comparisons, exactly as _compare_optional_field already did for the
# error/tipper fields.

def _inject_impedance_fill(edi_text: str, blocks=("ZXYR", "ZXYI")) -> str:
    """Return a copy of `edi_text` with 1.000000E+32 injected into the FIRST numeric value of each
    named >BLOCK. This exact recipe (ZXYR + ZXYI first cell) is verified to reproduce the historical
    'impedance maxdiff=1.414e+32' round-trip failure — the same shape as the real auslamp-tas EDIs."""
    num = re.compile(r"[-+]?\d\.\d+E[-+]\d+")
    text = edi_text
    for blk in blocks:
        out = []
        in_blk = False
        done = False
        for ln in text.splitlines(keepends=True):
            if ln.startswith(">" + blk):
                in_blk = True
                out.append(ln)
                continue
            if in_blk and ln.startswith(">"):
                in_blk = False
            line = ln
            if in_blk and not done and num.search(line):
                line = num.sub("  1.000000E+32", line, count=1)
                done = True
            out.append(line)
        text = "".join(out)
    return text


def test_normalize_masks_impedance_fill(tmp_path):
    """FAILS IF: a real-shaped EDI carrying the 1e32 missing-data sentinel inside its impedance blocks
    cannot produce a canonical XML — i.e. normalize() raises 'impedance maxdiff=1.414e+32' (the pre-fix
    behaviour that blocked all 57 auslamp-tas stations from getting canonical XML). Post-fix, the fill
    cells are masked, normalize() succeeds, and roundtrip_maxdiff is finite and small."""
    poisoned = _inject_impedance_fill(STANDARD.read_text(encoding="utf-8"))
    src = tmp_path / "SENTINEL01.edi"
    src.write_text(poisoned, encoding="utf-8")
    # sanity: the fixture really does carry the sentinel we injected (otherwise the test is vacuous)
    assert "1.000000E+32" in poisoned

    res = normalize(src, tmp_path, survey_id="auslamp-tas", station_id="SENTINEL01")
    assert res.canonical_xml.exists() and res.canonical_xml.stat().st_size > 0
    assert res.derived_edi.exists() and res.derived_edi.stat().st_size > 0
    assert res.n_periods > 0
    # the whole point: masking the 1e32 fills makes the round-trip diff finite/small, not 1.4e32
    assert res.roundtrip_maxdiff < 1e-3, res.roundtrip_maxdiff


def _perturb_impedance_cell(tf) -> None:
    """Drift ONE genuine (non-fill) impedance cell on the re-read TF far beyond rtol: Zxx at period 0
    (input=hx, output=ex), scaled x2. This is a REAL transfer-function corruption — not a 1e32 fill —
    so the fill mask must NOT swallow it and the gate must still fire."""
    cur = tf._transfer_function.transfer_function.loc[dict(period=tf.period[0], input="hx", output="ex")]
    tf._transfer_function.transfer_function.loc[
        dict(period=tf.period[0], input="hx", output="ex")] = complex(cur) * 2.0 + 1.0


def test_normalize_still_rejects_genuine_impedance_drift(tmp_path, monkeypatch):
    """ANTI-VACUOUS COMPANION. FAILS IF: the fill mask is so broad that a GENUINE impedance value drift
    between write and re-read no longer raises — i.e. the gate has been neutered into always-pass. We
    perturb one NON-fill impedance cell on the re-read side (Zxx[0], well beyond rtol) and assert the
    round-trip gate STILL raises with the fix in place. A mask that (wrongly) covered every cell would
    make this test fail — proving it guards against over-masking (demonstrated separately in scratchpad
    prove_overmask.py: masking everything makes normalize() silently pass this same drift)."""
    monkeypatch.setattr(TF, "read", _second_read_hook(_perturb_impedance_cell))
    with pytest.raises(RuntimeError, match="impedance maxdiff"):
        normalize(STANDARD, tmp_path, survey_id="vulcan")


# --- C2: canonical EMTF-XML must not FABRICATE metadata; conditioning must be persisted. ----------
def _read_back(res):
    """Re-read the written canonical XML and return its TF (fresh read, not the in-memory object)."""
    rt = TF()
    rt.read(str(res.canonical_xml))
    return rt


def test_citation_authors_are_the_survey_org_not_ausmt(tmp_path):
    """FAILS IF: the canonical XML's citation authors are the portal brand "AusMT" (the fabrication
    defect) instead of the survey custodian passed in survey_meta. The Vulcan fixture is author-less
    (citation.authors is None on read), so pre-fix condition_tf stamped "AusMT"; the fix sources the
    custodian org from survey_meta."""
    sm = {"org": "Geoscience Australia", "cite": {"ti": "Vulcan MT Survey"}, "doi": "10.9999/vulcan"}
    res = normalize(STANDARD, tmp_path, survey_id="vulcan", station_id="A1", survey_meta=sm)
    rt = _read_back(res)
    authors = rt.survey_metadata.citation_dataset.authors
    assert authors == "Geoscience Australia", authors
    assert authors != "AusMT", "citation authors are the portal brand — fabricated attribution"
    # title = survey title + station; DOI carried through (mt_metadata normalises to a doi.org URL)
    assert rt.survey_metadata.citation_dataset.title == "Vulcan MT Survey - A1"
    assert "10.9999/vulcan" in str(rt.survey_metadata.citation_dataset.doi)


def test_citation_prefers_named_investigators_over_org(tmp_path):
    """FAILS IF: named investigators are present in survey_meta but the citation authors fall back to
    the org (or worse, "AusMT"). Investigator attribution is stronger than the custodian org.
    C7: SMETA.investigators is now [{name, orcid}, ...] (ORCID solicited by the schema, no longer
    discarded); the citation author string is built from the names only."""
    sm = {"org": "Geoscience Australia",
          "investigators": [{"name": "A. Researcher", "orcid": "0000-0002-1825-0097"},
                            {"name": "B. Scientist", "orcid": None}],
          "cite": {"ti": "Vulcan MT Survey"}}
    res = normalize(STANDARD, tmp_path, survey_id="vulcan", station_id="A1", survey_meta=sm)
    authors = _read_back(res).survey_metadata.citation_dataset.authors
    assert authors == "A. Researcher, B. Scientist", authors


def test_citation_investigators_tolerates_legacy_bare_strings(tmp_path):
    """Defensive: a caller (or stale data) passing the PRE-C7 bare-string investigators list must not
    crash condition_tf — it still degrades to the same author string, not a stringified dict repr."""
    sm = {"org": "Geoscience Australia", "investigators": ["A. Researcher", "B. Scientist"],
          "cite": {"ti": "Vulcan MT Survey"}}
    res = normalize(STANDARD, tmp_path, survey_id="vulcan", station_id="A1", survey_meta=sm)
    authors = _read_back(res).survey_metadata.citation_dataset.authors
    assert authors == "A. Researcher, B. Scientist", authors


def test_citation_without_survey_meta_is_explicit_unknown_not_ausmt(tmp_path):
    """FAILS IF: with NO survey_meta (bare API use), the author-less fixture is stamped "AusMT". The
    honest fallback is an explicit-unknown (mt_metadata rejects a None citation on read, so silence is
    not an option in this build) — never a fabricated brand."""
    res = normalize(STANDARD, tmp_path, survey_id="vulcan", station_id="A1")   # no survey_meta
    authors = _read_back(res).survey_metadata.citation_dataset.authors
    assert authors != "AusMT", "author-less fixture still fabricates 'AusMT' without survey_meta"
    assert "unknown" in authors.lower(), authors
    assert "not asserted" in authors.lower(), authors


def test_rotation_unknown_is_noted_not_silently_zeroed(tmp_path):
    """FAILS IF: the spectra-origin Phoenix fixture (whose _rotation_angle is None — frame unknown) is
    zero-filled with NO machine-readable note saying the frame is not asserted. Pre-fix the note was the
    bare 'rotation_angle=zeros', which reads as a claimed 0° frame. The fix records that the frame is
    NOT asserted and surfaces it via the conditioned list."""
    res = normalize(SPECTRA, tmp_path, survey_id="jupiter", station_id="A01")
    rot_notes = [n for n in res.conditioned if n.startswith("rotation:")]
    assert rot_notes, f"no rotation-unknown note in conditioned: {res.conditioned}"
    assert "NOT asserted" in rot_notes[0], rot_notes[0]
    assert "unknown" in rot_notes[0].lower(), rot_notes[0]


def test_true_station_id_recoverable_from_inside_the_xml(tmp_path):
    """FAILS IF: a station id carrying characters the alphanumeric Site.id sanitiser strips
    ('C6_BxByReplaced-01' -> in-XML Site.id 'C6BxByReplaced01', losing the underscore/hyphen structure)
    is not recoverable from INSIDE the written XML. The XML's own <Id> is the lossy sanitised form; the
    fix embeds the unsanitised source id in the Site <Name> (geographic_name), which survives the
    round-trip, so a reader of the XML bytes (not the filename) can still recover the true id."""
    true_id = "C6_BxByReplaced-01"
    res = normalize(STANDARD, tmp_path, survey_id="vulcan", station_id=true_id)
    rt = _read_back(res)
    # the XML's internal Site.id is the LOSSY alphanumeric-only form — this is exactly why the true id
    # must be preserved elsewhere in the artifact.
    assert rt.station_metadata.id == "C6BxByReplaced01", rt.station_metadata.id
    # ...and it IS recoverable, from a FRESH re-read of the XML bytes (not the in-memory object).
    recovered = source_station_id_from_geographic_name(rt.station_metadata.geographic_name)
    assert recovered == true_id, (recovered, rt.station_metadata.geographic_name)
    # the conditioned list records the preservation for provenance
    assert any("source_id_preserved_in_site_name" in n for n in res.conditioned), res.conditioned


def test_clean_station_id_does_not_pollute_site_name(tmp_path):
    """FAILS IF: a station id that needs NO sanitising ('A1') still gets the ausmt_src_id marker glued
    into its Site <Name>. The token must appear ONLY when identity would otherwise be lost."""
    res = normalize(STANDARD, tmp_path, survey_id="vulcan", station_id="A1")
    rt = _read_back(res)
    assert "ausmt_src_id" not in (rt.station_metadata.geographic_name or ""), \
        rt.station_metadata.geographic_name
    assert not any("source_id_preserved" in n for n in res.conditioned), res.conditioned


# --- Final-audit 4.2: library-default metadata the XML asserts must carry conditioning notes. ------
def test_edi_library_defaults_are_noted_not_silently_asserted(tmp_path):
    """FAILS IF: normalize() writes a canonical XML that asserts a sign convention, a declination
    epoch/model, or channel orientations for an EDI source WITHOUT a conditioning note saying the
    source never stated them. This is the LG-2 fabrication class the C2 fix did not cover (final
    hostile audit 4.2, reproduced on this very fixture: Vulcan_A1's XML asserts <SignConvention>+,
    Declination epoch="1995", and Ey orientation 0.0 = NORTH — from zero-length, azimuth-less EMEAS
    lines — none of it source-stated). The values may stay (the writer requires them, exactly like
    the Issue-#4 rotation zero-fill), but each must be flagged NOT-asserted in the conditioned list."""
    res = normalize(STANDARD, tmp_path, survey_id="vulcan", station_id="A1")
    joined = "\n".join(res.conditioned)
    assert "sign_convention" in joined, res.conditioned
    assert "declination" in joined, res.conditioned
    assert "orientation" in joined, res.conditioned
    # each of the new notes must carry the not-asserted marker, same honesty contract as rotation
    for key in ("sign_convention", "declination", "orientation"):
        note = next(n for n in res.conditioned if key in n)
        assert "asserted" in note.lower(), note


def test_default_notes_are_edi_gated(tmp_path):
    """FAILS IF: the library-default notes fire for a non-EDI source. An EMTF-XML source CAN state
    sign convention / declination epoch / orientations, so there they are source-authored and the
    notes would be false. condition_tf without source_format (bare API use) must stay note-free for
    these fields too (backward compatible)."""
    from mt_metadata.transfer_functions.core import TF as _TF
    tf = _TF()
    tf.read(str(STANDARD))
    notes = condition_tf(tf, survey_id="vulcan", station_id="A1")   # no source_format
    joined = "\n".join(notes)
    assert "sign_convention" not in joined, notes
    assert "declination" not in joined, notes
