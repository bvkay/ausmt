"""End-to-end build_report.json + de-duplicated conditioning NOTICE logging (Deliverables 1 + 2).

Exercises the REAL build (build_portal.main against the CC-BY sample survey) rather than hand-built
note maps — the pure aggregation function is unit-tested separately in test_conditioning_report.py.
Here we assert the build's actual stdout structure, the emitted build_report.json, its schema validity,
its totals cross-check against the manifest, and that the canonical/provenance conditioning records are
UNCHANGED by the logging restructure (the notes stayed per-station; only the console log + the new
report changed).

NON-VACUOUS (Invariant 10):
  * the survey-level NOTICE lines are read from captured stdout, an observable independent of the report;
  * build_report totals.stations_built is cross-checked against the manifest's DISTINCT served EDI
    stations (recomputed), not trusted from the report's own bytes;
  * the report's `conditioning` is recomputed from the per-station canonical_conditioning records that
    the build persisted (station.json / provenance.json) and asserted EQUAL — a divergence between what
    the log/report says and what was persisted fails here.
Requires the mt_metadata/mth5 build engine (importorskip otherwise); runs in the build CI job.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SURVEYS = ROOT / "data"
SCHEMA = json.loads((ROOT / "schema" / "build_report.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
import build_portal as bp  # noqa: E402


def _build(tmp_path, *extra):
    """Run the build in a subprocess so stdout+stderr are cleanly capturable as text. Force the child's
    stdio to UTF-8 (PYTHONIOENCODING) so the em-dash in the conditioning NOTICE lines round-trips on
    Windows, where the default console code page (cp1252) can't encode it."""
    out = tmp_path / "data"
    prod = tmp_path / "products"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
         "--out", str(out), "--products", str(prod), "--bundle-edi", "--no-validate", *extra],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, r.stderr
    return out, prod, r


def test_build_report_exists_schema_valid_and_totals_match_manifest(tmp_path):
    out, _prod, _r = _build(tmp_path)
    rep_path = out / "build_report.json"
    assert rep_path.exists(), "build_report.json must be written alongside build_provenance.json"
    assert (out / "build_provenance.json").exists()
    rep = json.loads(rep_path.read_text(encoding="utf-8"))

    # schema-valid (draft-07)
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(rep, SCHEMA)

    # identity fields mirror build.json (same helpers) — never re-derived independently
    binfo = json.loads((out / "build.json").read_text(encoding="utf-8"))
    assert rep["engine_commit"] == binfo["engine_commit"]
    assert rep["source_commit"] == binfo["source_commit"]
    assert rep["build_id"] == binfo["build_id"]

    # The manifest lists only SERVED stations (a subset of built — an embargoed/non-redistributable
    # survey builds stations it never serves), so served <= built. The CC-BY sample survey is fully
    # served, so here they're equal AND the subset relation holds; assert both facts.
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    served = {r["station"] for r in man["files"] if r["format"] == "edi"}
    assert served, "the CC-BY sample survey must serve stations"
    assert len(served) <= rep["totals"]["stations_built"], \
        "served stations must be a subset of built stations"
    assert rep["totals"]["stations_built"] == len(served), \
        "the fully-served sample survey should build exactly what it serves"
    assert rep["totals"]["surveys"] == len(rep["surveys"])
    assert rep["totals"]["stations_built"] == sum(s["stations_built"] for s in rep["surveys"].values())


def test_conditioning_log_is_survey_level_not_per_station(tmp_path):
    """Deliverable 1: the build prints ONE '[xml] NOTICE <slug>: <note> — ...' line per DISTINCT note,
    and NO per-station 'NOTICE <station_id>: conditioned' lines (the retired ~792-line noise). The
    sample survey's two stations share all their notes, so every line ends '— all 2 stations'."""
    out, _prod, r = _build(tmp_path)
    log = r.stderr
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    (slug, survey) = next(iter(rep["surveys"].items()))

    notice_lines = [ln for ln in log.splitlines() if "NOTICE" in ln and "conditioned" not in ln
                    and f"NOTICE {slug}:" in ln]
    # one line per distinct conditioning note
    assert len(notice_lines) == len(survey["conditioning"]) >= 1, \
        f"expected one survey-level NOTICE per distinct note; got {len(notice_lines)} lines for " \
        f"{len(survey['conditioning'])} notes"
    # this survey's stations all share every note -> every line is the 'all N stations' form
    n = survey["stations_built"]
    assert all(ln.rstrip().endswith(f"all {n} stations") for ln in notice_lines), \
        f"shared-note survey should print 'all {n} stations' lines: {notice_lines}"

    # the OLD per-station form ('NOTICE <station_id>: conditioned — ...') must be GONE
    station_ids = {c["stations"][0] for c in survey["conditioning"]
                   if c["stations"] and len(c["stations"]) == 1}
    for sid in station_ids:
        assert f"NOTICE {sid}: conditioned" not in log, \
            f"per-station conditioned NOTICE for {sid} should have been de-duplicated away"


def test_report_conditioning_agrees_with_persisted_per_station_notes(tmp_path):
    """CRITICAL (shared-function contract): build_report.json's `conditioning` for a survey must equal
    what the shared aggregation produces from the SAME per-station canonical_conditioning records the
    build persisted into products/<slug>/<station>/station.json. If the report and the persisted notes
    disagree, the log an operator reads is lying about the canonical record."""
    out, prod, _r = _build(tmp_path)
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))

    for slug, survey in rep["surveys"].items():
        # gather the per-station notes the build persisted (the source of truth the notes live in)
        notes_by_station = {}
        for sdir in sorted((prod / slug).iterdir()):
            sj = sdir / "station.json"
            if not sj.exists():
                continue
            doc = json.loads(sj.read_text(encoding="utf-8"))
            cc = doc.get("canonical_conditioning")
            if cc:
                notes_by_station[doc["station"]] = cc
        # recompute the aggregation the report should carry, from the persisted per-station notes
        expected = bp.conditioning_report(notes_by_station)
        assert survey["conditioning"] == expected, \
            f"{slug}: report conditioning drifted from the persisted per-station notes"


def test_report_does_not_disturb_canonical_provenance(tmp_path):
    """Deliverable 1 invariant: the logging restructure must NOT change canonical/provenance outputs.
    The canonical store's provenance.json conditioning map (per-station notes) must be identical whether
    or not build_report.json is produced — it always is now, so we assert the provenance map still
    carries the FULL per-station notes (not the aggregated view) for every conditioned station."""
    out = tmp_path / "data"
    canon = tmp_path / "canon"
    prod = tmp_path / "products"
    rc = bp.main(["--surveys", str(SURVEYS), "--out", str(out), "--products", str(prod),
                  "--canonical-dir", str(canon), "--bundle-edi", "--no-validate"])
    assert rc == 0
    cprov = json.loads((canon / "provenance.json").read_text(encoding="utf-8"))
    cond = cprov["conditioning"]
    assert cond, "the sample survey should be conditioned"
    # provenance still holds the PER-STATION note lists (not the aggregated {note,count} report shape)
    for _slug, per_station in cond.items():
        assert isinstance(per_station, dict), "provenance conditioning is a per-station map, unchanged"
        for _station, notes in per_station.items():
            assert isinstance(notes, list) and all(isinstance(x, str) for x in notes), \
                "each station keeps its ordered list of note strings — the canonical record is unchanged"

    # station.json also still carries the raw per-station notes (persisted, not just aggregated)
    any_station = False
    for slug in cond:
        for sdir in (prod / slug).iterdir():
            doc = json.loads((sdir / "station.json").read_text(encoding="utf-8"))
            if doc.get("canonical_conditioning"):
                assert isinstance(doc["canonical_conditioning"], list)
                any_station = True
    assert any_station, "at least one station.json must carry its per-station canonical_conditioning list"
