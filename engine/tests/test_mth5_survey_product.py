"""C32 tier 2 survey MTH5 product (SPEC MTH5-PRODUCT): the survey.yaml -> survey_metadata mapping and
the INJECTED dataset DOI (SPEC §3.3 / A5), the SPEC §6 blocking round-trip gate (a faithful build
passes; a corrupted h5 is RED-proven to fail and be withheld), the A2 version-pin recorded on the
manifest, and the tier-3 (designed-but-disabled, SPEC §2.3 / A4) collection producer + its RAM guard.

These exercise the producer directly with the vendored two-station example survey; the manifest/embargo/
coord-access integration of the same producer is covered by test_manifest.py / test_access_gate.py /
test_coord_access.py. Requires the mt_metadata/mth5 build stack; skips cleanly otherwise.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "extract"))
pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")
import build_portal as bp        # noqa: E402
from _fixtures import example_edis  # noqa: E402


def _stations():
    """The vendored two-station example survey as the producer's [(edi_path, record)] input."""
    return [(p, {"id": p.stem}) for p in example_edis()]


# A synthetic SMETA in the exact shape survey_meta_from_yaml emits (cite.ti / blurb / doi / pubs / org /
# lic / investigators / funders). The dataset DOI is a BARE '10.…' on purpose — the producer must lift it
# to a resolvable URL before mt_metadata's HttpUrl-typed citation field will accept it (else it is lost).
_SMETA = {
    "cite": {"ti": "Example MT Survey 2026"},
    "blurb": "Two broadband stations used as a product test fixture.",
    "doi": "10.1234/example.dataset",
    "pubs": [{"doi": "10.1080/journal.paper", "t": "An interpretation paper",
              "j": "Exploration Geophysics", "y": 2024}],
    "org": "Example Organisation",
    "lic": "CC-BY-4.0",
    "investigators": [{"name": "Example Researcher", "orcid": "0000-0002-1825-0097"}],
    "funders": [{"name": "Australian Research Council", "grant_id": "DP000000"}],
}


def _open(hp):
    from mth5.mth5 import MTH5  # noqa: PLC0415
    m = MTH5()
    m.open_mth5(str(hp), mode="r")
    return m


# --------------------------------------------------------------------- metadata mapping + DOI injection

def test_survey_metadata_and_dataset_doi_injected(tmp_path):
    """SPEC §3.3 / A5: the survey.yaml scholarly fields map onto survey_metadata and the DATASET DOI is
    injected (it is the one field genuinely absent from every EDI). The bare '10.…' DOI is normalised to a
    resolvable URL, and all of it survives the write -> reopen round-trip."""
    rel, hp, n = bp.emit_survey_mth5(_stations(), "example-survey", "Example", tmp_path, smeta=_SMETA)
    assert n == 2 and hp and hp.exists() and rel == "bundles/example-survey-tf.h5"
    m = _open(hp)
    try:
        df = m.tf_summary.to_dataframe()
        assert set(df["survey"]) == {"example-survey"}, "every station grouped under the slug, not raw '0'"
        r0 = df.iloc[0]
        tf = m.get_transfer_function(r0["station"], r0.get("tf_id", r0["station"]), survey=r0.get("survey"))
        sm = tf.survey_metadata
        assert sm.id == "example-survey"
        assert str(sm.citation_dataset.doi) == "https://doi.org/10.1234/example.dataset", \
            "dataset DOI injected AND normalised from the bare form"
        assert str(sm.citation_journal.doi) == "https://doi.org/10.1080/journal.paper", "journal DOI single-sourced"
        assert sm.name == "Example MT Survey 2026"
        assert sm.release_license == "CC-BY-4.0"
        assert sm.acquired_by.organization == "Example Organisation"
    finally:
        m.close_mth5()


# CONTRIBUTOR-CREDIT-SPEC (mth5 follow-up): a SMETA carrying the typed credit lists + a real grant id.
# project_lead is the lead-most credited party (the ProjectLeader contributor here, ahead of the lead
# creator), its ORCID belongs in project_lead.url (a full https URL - AuthorPerson has no serialised id),
# and the grant id rides through funders when the survey declares one.
_CREDIT_SMETA = {
    "cite": {"ti": "Credit MT Survey"},
    "org": "Example Organisation",
    "lic": "CC-BY-4.0",
    "creators": [{"name": "Robertson, Kate", "name_type": "person"}],
    "contributors": [{"name": "Thiel, Stephan", "name_type": "person", "role": "ProjectLeader",
                      "orcid": "0000-0002-1825-0097"}],
    "funders": [{"name": "Australian Research Council", "grant_id": "DP123456"}],
}


def test_project_lead_url_and_grant_id_round_trip(tmp_path):
    """CONTRIBUTOR-CREDIT-SPEC: the mth5 survey_metadata carries the lead-most credited party as
    project_lead (the ProjectLeader contributor, ahead of the lead creator), its ORCID as a full
    https://orcid.org/<id> project_lead.url, and the grant id in funding_source.grant_id. RED against the
    pre-change producer: it seeded project_lead from investigators[0] and wrote the ORCID to a non-
    serialised .id (so no url survived), and _funders_of never carried a grant id at all."""
    rel, hp, n = bp.emit_survey_mth5(_stations(), "credit-survey", "Credit", tmp_path, smeta=_CREDIT_SMETA)
    assert n == 2 and hp and hp.exists()
    m = _open(hp)
    try:
        df = m.tf_summary.to_dataframe()
        r0 = df.iloc[0]
        tf = m.get_transfer_function(r0["station"], r0.get("tf_id", r0["station"]), survey=r0.get("survey"))
        sm = tf.survey_metadata
        assert sm.project_lead.author == "Thiel, Stephan", sm.project_lead.author
        assert str(sm.project_lead.url).rstrip("/") == "https://orcid.org/0000-0002-1825-0097", \
            str(sm.project_lead.url)
        # mt_metadata stores grant_id as a list; the point is the survey's declared id landed (no placeholder).
        assert "DP123456" in str(sm.funding_source.grant_id), sm.funding_source.grant_id
    finally:
        m.close_mth5()


def test_metadata_thin_survey_still_builds_and_groups(tmp_path):
    """SPEC caveat 2: a raw/CSV-only survey with no SMETA still builds a valid TF payload; the slug is
    seeded so stations do NOT collapse into one survey group '0'."""
    rel, hp, n = bp.emit_survey_mth5(_stations(), "thin-survey", "Thin", tmp_path, smeta=None)
    assert n == 2 and hp.exists()
    m = _open(hp)
    try:
        assert set(m.tf_summary.to_dataframe()["survey"]) == {"thin-survey"}, "slug seeded without SMETA"
    finally:
        m.close_mth5()


# --------------------------------------------------------------------- round-trip gate (SPEC §6)

def test_roundtrip_gate_passes_on_faithful_build(tmp_path):
    """SPEC §6: a faithful build is lossless — every impedance + coordinate matches its source EDI to
    float precision (the measured Tumby result was 0.0), the payload is TF-only, and the producer returns
    the bundle."""
    rel, hp, n = bp.emit_survey_mth5(_stations(), "rt", "RT", tmp_path, smeta=None)
    assert n == 2 and hp.exists()
    ok, rep = bp.mth5_survey_roundtrip_ok(hp, _stations())
    assert ok, rep
    assert rep["checked"] == 2 and rep["tf_only"] is True
    assert rep["z_max_abs_diff"] == 0.0 and rep["coord_max_abs_diff"] == 0.0, rep


def test_roundtrip_gate_RED_on_corrupted_impedance(tmp_path):
    """RED proof (SPEC §6): a silently-wrong TF — one impedance element mutated after the write — MUST
    fail the round-trip gate. Without the gate this file would ship byte-clean with a wrong Z."""
    import h5py  # noqa: PLC0415
    rel, hp, n = bp.emit_survey_mth5(_stations(), "red", "RED", tmp_path, smeta=None)
    assert hp.exists()
    targets = []
    with h5py.File(hp, "r+") as f:
        f.visititems(lambda name, obj: targets.append(name)
                     if isinstance(obj, h5py.Dataset) and name.endswith("transfer_function") else None)
        assert targets, "expected transfer_function datasets in the built h5"
        d = f[targets[0]]
        d[0, 1, 0] = d[0, 1, 0] + (1.0e6 + 1.0e6j)   # corrupt one Z element
        f.flush()
    ok, rep = bp.mth5_survey_roundtrip_ok(hp, _stations())
    assert ok is False, "corrupted impedance must FAIL the round-trip gate"
    assert any("impedance" in mm["reason"] for mm in rep["mismatches"]), rep


def test_producer_withholds_survey_when_gate_fails(tmp_path, monkeypatch):
    """SPEC §6: when the round-trip gate fails, the PRODUCER withholds the whole survey — deletes the h5
    and returns no bundle — so a mismatch never reaches the manifest. Withholds the survey, not the corpus."""
    monkeypatch.setattr(bp, "mth5_survey_roundtrip_ok",
                        lambda *a, **k: (False, {"checked": 2, "z_max_abs_diff": 9.9,
                                                 "coord_max_abs_diff": 0.0, "tf_only": True,
                                                 "mismatches": [{"station": "EXAMPLE01", "reason": "forced"}]}))
    rel, hp, n = bp.emit_survey_mth5(_stations(), "withheld", "Withheld", tmp_path, smeta=None)
    assert (rel, hp, n) == (None, None, 0), "a survey failing the gate yields no bundle"
    assert not (tmp_path / "bundles" / "withheld-tf.h5").exists(), "the withheld h5 must be deleted, not served"


# --------------------------------------------------------------------- tier 3 collection (designed, disabled)

def test_collection_producer_groups_members_distinctly(tmp_path):
    """SPEC §2.3: the tier-3 producer concatenates surveys, each under its OWN survey group keyed by slug,
    so a station id shared across members never collides. Here two members carry the SAME station id and
    must land as two distinct groups, each round-tripping against its own source EDI."""
    edis = example_edis()
    members = [("survey-a", "Survey A", [(edis[0], {"id": "SHARED"})]),
               ("survey-b", "Survey B", [(edis[1], {"id": "SHARED"})])]
    rel, hp, n = bp.emit_collection_mth5(members, "collx", tmp_path)
    assert n == 2 and hp and hp.exists() and rel == "bundles/collx-tf.h5"
    m = _open(hp)
    try:
        df = m.tf_summary.to_dataframe()
        assert set(df["survey"]) == {"survey-a", "survey-b"}, "each member is a DISTINCT survey group"
        assert set(df["station"]) == {"SHARED"}, "the shared station id lives once per group, no collision"
    finally:
        m.close_mth5()


def test_collection_guard_disabled_by_default_and_ram_capped():
    """SPEC A4: the tier-3 producer is disabled by construction (collection_h5_enabled default OFF) and,
    when enabled, refuses a build above max_collection_stations so an AusLAMP-national ~6 GiB build cannot
    OOM the host."""
    off = bp.load_flags(None)
    assert off["collection_h5_enabled"] is False and off["max_collection_stations"] == 600
    allowed, reason = bp.collection_h5_allowed(off, 10)
    assert allowed is False and "OFF" in reason, "designed-but-disabled by default"
    on = {"collection_h5_enabled": True, "max_collection_stations": 600}
    assert bp.collection_h5_allowed(on, 300)[0] is True, "under the cap => allowed when enabled"
    capped, why = bp.collection_h5_allowed(on, 601)
    assert capped is False and "max_collection_stations" in why, "over the cap => refused (RAM gate)"


# --------------------------------------------------------------------- version pin on the manifest (A2)

def test_manifest_records_mth5_version_pin(tmp_path):
    """SPEC A2: the download manifest self-declares the mth5 / mt_metadata pin its served bundles were
    written with, so a consumer reads the exact library version beside the artifact's size/sha256."""
    import mt_metadata  # noqa: PLC0415
    import mth5  # noqa: PLC0415
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(ROOT / "data"),
                        "--out", str(out), "--bundle-edi", "--survey-h5", "--no-validate"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert man.get("mth5_version") == mth5.__version__, "manifest must pin the mth5 version it built with"
    assert man.get("mt_metadata_version") == mt_metadata.__version__
    assert any(b["format"] == "mth5" for b in man["bundles"]), "the --survey-h5 build must serve an mth5 bundle"
