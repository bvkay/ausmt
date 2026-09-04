"""Tier 1: the per-station transfer-function MTH5.

One `<station>.h5` per served station under `out/h5/<slug>/`, beside the `edi/` and `xml/` families
the manifest already keys, written by the SAME writer the tier-2 survey bundle uses. That sharing is
the point of the design rather than an implementation detail: the embargo posture, the coordinate
posture and the section 6 round-trip gate are INHERITED, so there is no second place for any of
the three to be got wrong. These pins are therefore mostly about what the shared writer is handed and
what the caller does with what it returns.

Four things are pinned, each stating what it fails on:

  * a served survey gets exactly one h5 per byte-gated station, and each file really does hold that
    station's transfer function (reopened and read back, not trusted from the filename);
  * an embargoed survey emits NOTHING: no bytes on disk and no manifest rows, identically to its EDI;
  * a non-exact (generalised or withheld) station is byte-gated out, exactly as its EDI and its
    EMTF-XML are, because an MTH5 carries the true position in its station metadata;
  * the producer is FLAG-GATED off by default, so a build that does not ask for tier 1 is unchanged.

Requires the mt_metadata/mth5 build stack; skips cleanly otherwise.
"""
import hashlib
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = ROOT / "data"          # data/sample-survey: CC-BY-4.0, open => bytes are served
SCHEMA = json.loads((ROOT / "schema" / "manifest.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "extract"))
# The module's engine-produced coordinate fixtures (one EDI per station, distinctive positions) and
# its survey.yaml writer. Reused so the byte gate is exercised against the SAME fixture shape the
# coordinate-access workflow proves the gate on.
from test_coord_access import EXACT, GEN, HID, _stage_survey, _sweep_h5_for_non_exact   # noqa: E402


def _build(tmp_path, *extra, surveys=None):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal",
                        "--surveys", str(surveys or SURVEYS), "--out", str(out),
                        "--bundle-edi", "--no-validate", *extra],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out, json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def _h5_rows(man):
    return [r for r in man["files"] if r["format"] == "mth5"]


# --------------------------------------------------------------------------- the produced files

def test_a_served_survey_gets_one_h5_per_served_station(tmp_path):
    """The product itself. Each served station gets `h5/<slug>/<station>.h5`, listed in the manifest's
    files[] as format `mth5`, and the file really holds that station's transfer function when reopened.
    FAILS IF the tree is empty, if a station is missing a file, if a manifest row points at bytes that
    are not there, or if the h5 turns out to hold a different station than its filename claims."""
    from mth5.mth5 import MTH5  # noqa: PLC0415
    out, man = _build(tmp_path, "--station-h5")
    rows = _h5_rows(man)
    assert rows, "a served survey must produce per-station MTH5 rows"
    edi_stations = {r["station"] for r in man["files"] if r["format"] == "edi"}
    assert {r["station"] for r in rows} == edi_stations, (
        "tier 1 covers exactly the stations whose bytes are served, no more and no fewer")
    for row in rows:
        assert row["url"] == f"h5/{'sample-survey'}/{row['station']}.h5", row["url"]
        p = out / row["url"]
        assert p.exists(), f"manifest row points at missing bytes: {row['url']}"
        # INDEPENDENT OBSERVABLE: size + sha256 recomputed from the artifact, never trusted from the row
        assert row["size"] == p.stat().st_size
        assert row["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
        assert row["tier"] == "repo" and row["license"] == "CC-BY-4.0"
        m = MTH5()
        m.open_mth5(str(p), mode="r")
        try:
            df = m.tf_summary.to_dataframe()
            assert len(df) == 1, f"a per-station file holds ONE transfer function, got {len(df)}"
            assert df.iloc[0]["station"] == row["station"], "the file holds a different station"
            assert df.iloc[0]["survey"] == "sample-survey", (
                "the station is grouped under the survey slug, not the raw EDI '0'")
        finally:
            m.close_mth5()


def test_the_emitted_manifest_still_validates_against_its_schema(tmp_path):
    """files[].format gains `mth5`, which means the schema enum had to change with the producer. The
    build self-checks the manifest it writes, so a missed enum would fail the BUILD; this asserts it
    directly too, because the failure mode of getting this wrong is a red build with a confusing
    message rather than a wrong product. FAILS IF the schema and the producer disagree."""
    jsonschema = pytest.importorskip("jsonschema")
    _out, man = _build(tmp_path, "--station-h5")
    assert _h5_rows(man), "the pin is vacuous without at least one mth5 file row"
    jsonschema.validate(man, SCHEMA)
    assert "mth5" in SCHEMA["definitions"]["file"]["properties"]["format"]["enum"], (
        "files[].format must admit mth5; the docs and the portal read this enum as the vocabulary")


def test_the_producer_is_off_by_default(tmp_path):
    """Tier 1 is flag-gated like tier 2. A build that does not ask for it is byte-identical to before.
    FAILS IF the h5 tree or an mth5 file row appears without the flag."""
    out, man = _build(tmp_path, "--survey-h5")
    assert _h5_rows(man) == [], "no --station-h5 => no per-station mth5 rows"
    assert not (out / "h5").exists(), "no --station-h5 => no h5/ tree on disk"
    assert any(b["format"] == "mth5" for b in man["bundles"]), (
        "the tier-2 bundle is unaffected by the tier-1 flag")


# --------------------------------------------------------------------------- the inherited postures

def test_an_embargoed_survey_emits_no_station_h5(tmp_path):
    """The access gate is inherited, not re-implemented: the producer is called from inside the same
    `can_serve` branch the EDI copy and the survey bundle live in. An embargoed survey therefore emits
    NOTHING for tier 1, exactly as it emits no EDI. FAILS IF any h5 byte lands on disk or any mth5 row
    reaches the manifest for a survey whose bytes are withheld."""
    import shutil  # noqa: PLC0415
    staged = tmp_path / "surveys_src"
    shutil.copytree(SURVEYS, staged)
    until = (date.today() + timedelta(days=365)).isoformat()
    for y in staged.rglob("survey.yaml"):
        lines = [ln for ln in y.read_text(encoding="utf-8").splitlines()
                 if not ln.strip().startswith("access:")]
        lines.append(f"access: {{ level: embargoed, embargo_until: {until} }}")
        y.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out, man = _build(tmp_path, "--station-h5", surveys=staged)
    assert _h5_rows(man) == [], "an embargoed survey must have NO per-station mth5 rows"
    assert not (out / "h5").exists(), "an embargoed survey must write no h5 bytes at all"
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    assert cat, "the embargo withholds bytes, never discovery: the stations stay catalogued"


def test_a_non_exact_station_is_byte_gated_out_of_tier_one(tmp_path):
    """An MTH5 carries the station's true latitude, longitude and elevation in its own metadata,
    so it rides the SAME per-station byte gate the EDI and the EMTF-XML ride. Only an `exact` station
    gets a file. FAILS IF a generalised or withheld station gets an h5, which would be the coordinate
    leak the survey-bundle producer already had to be fixed for once."""
    base = tmp_path / "surveys"
    base.mkdir(parents=True)
    _stage_survey(base, [EXACT, GEN, HID], slug="gate-survey", name="Gate Survey")
    out, man = _build(tmp_path, "--station-h5", surveys=base)
    served = {r["station"] for r in _h5_rows(man)}
    assert served == {EXACT["id"]}, f"only the exact station may get an h5, got {served}"
    on_disk = sorted(p.name for p in (out / "h5" / "gate-survey").glob("*"))
    assert on_disk == [f"{EXACT['id']}.h5"], on_disk
    # And the true positions of the two gated stations appear nowhere in the h5 tree. Checked with the
    # leak-sweep's OWN numeric HDF5 leg (the engine's mth5 reader, values compared as floats), not
    # a byte-string search: a search for b"-33.555551" inside an HDF5 file is the check this
    # module documents as structurally blind, because an IEEE-754 double has no decimal spelling
    # in the container.
    hits = _sweep_h5_for_non_exact(out)
    assert not hits, "a byte-gated station's position reached a per-station MTH5:\n" + "\n".join(
        f"  {f}: {h}" for f, h in hits)
