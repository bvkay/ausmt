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
import re
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

    # The [xml] prefix is what separates this family from its siblings ([frame], [presence]), which
    # print the same one-line-per-distinct-note shape into their own build_report fields.
    notice_lines = [ln for ln in log.splitlines() if "conditioned" not in ln
                    and f"[xml] NOTICE {slug}:" in ln]
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
                "each station keeps its ordered list of note strings - the canonical record is unchanged"

    # station.json also still carries the raw per-station notes (persisted, not just aggregated)
    any_station = False
    for slug in cond:
        for sdir in (prod / slug).iterdir():
            doc = json.loads((sdir / "station.json").read_text(encoding="utf-8"))
            if doc.get("canonical_conditioning"):
                assert isinstance(doc["canonical_conditioning"], list)
                any_station = True
    assert any_station, "at least one station.json must carry its per-station canonical_conditioning list"


def test_per_station_xml_emission_failures_surface_in_build_report(tmp_path, monkeypatch, capsys):
    """RED-PROOF: a per-station EMTF-XML emission failure must be COUNTED in build_report.json (a
    structured xml_failures row with the exception class PLUS a counted survey warning), never left
    invisible behind a printed '[xml] WARN'. This is the gap the 8-survey/~380-station regression hid
    (1182 EDI rows served, only 732 EMTF-XML rows, a green build). We force ONE station's XML emission
    to raise (the others emit normally) and assert the report surfaces it.

    Pre-fix (revert build_portal.py + schema): _emit_served_xml returns no failures, no xml_failures
    field is written, and this test fails on the missing field (and on the un-incremented warning count).

    Runs the build IN-PROCESS (like test_report_does_not_disturb_canonical_provenance) so the module
    attribute _emit_served_xml re-imports can see the monkeypatched normalize."""
    import ausmt_science.ingest.normalize as _ni  # noqa: PLC0415

    real_normalize = _ni.normalize
    victim = "A2"  # sample survey station id (DATAID A2); the sibling station A1 emits normally

    def _fake_normalize(src, out_dir, *, survey_id, station_id=None, **kw):
        if station_id and victim in str(station_id):
            raise RuntimeError("simulated EMTF-XML emission failure")
        return real_normalize(src, out_dir, survey_id=survey_id, station_id=station_id, **kw)

    # _emit_served_xml does `from ausmt_science.ingest.normalize import normalize` at call time, so
    # patching the module attribute is picked up on the next call.
    monkeypatch.setattr(_ni, "normalize", _fake_normalize)

    out = tmp_path / "data"
    prod = tmp_path / "products"
    rc = bp.main(["--surveys", str(SURVEYS), "--out", str(out), "--products", str(prod),
                  "--bundle-edi", "--no-validate"])
    assert rc == 0, "a per-station XML failure must not abort the build (EDI-only serve)"

    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(rep, SCHEMA)  # the new xml_failures field must be schema-valid

    # exactly one survey carries the forced failure; find its structured row
    surveys_with_fail = {slug: s for slug, s in rep["surveys"].items() if s.get("xml_failures")}
    assert len(surveys_with_fail) == 1, f"expected one survey with xml_failures, got {surveys_with_fail}"
    slug, survey = next(iter(surveys_with_fail.items()))
    rows = survey["xml_failures"]
    assert len(rows) == 1, rows
    assert victim in rows[0]["station"], rows[0]
    assert rows[0]["error"] == "RuntimeError", rows[0]  # the exception CLASS is recorded

    # it is ALSO a counted survey warning, so a green build cannot hide it
    xml_warns = [w for w in survey["warnings"] if "EMTF-XML emission failed" in w]
    assert xml_warns, f"xml failure must appear as a counted warning: {survey['warnings']}"
    assert "RuntimeError" in xml_warns[0], xml_warns[0]
    assert rep["totals"]["warnings"] >= 1

    # THE LOG FOLD: the per-file '[xml] WARN <file>: ...' line is replaced by ONE line per survey per
    # distinct fault, carrying the count and one example file; the per-file rows live in the report's
    # product_failures ledger, keyed by producer, with the producer path the fault was first seen in.
    err = capsys.readouterr().err
    warn_lines = [ln for ln in err.splitlines() if "[xml] WARN" in ln]
    assert warn_lines == [
        f"  [xml] WARN {slug}: RuntimeError: simulated EMTF-XML emission failure - 1 file(s), "
        f"e.g. {survey['product_failures']['xml'][0]['file']} (station product)"], warn_lines
    pf = survey["product_failures"]["xml"]
    assert len(pf) == 1 and pf[0]["error"] == "RuntimeError", pf
    assert pf[0]["message"] == "simulated EMTF-XML emission failure", pf
    assert pf[0]["context"] == "station product", pf

    # the victim still served its EDI (EDI-only), but has NO emtfxml manifest row
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    edi_ids = {r["station"] for r in man["files"] if r["format"] == "edi"}
    xml_ids = {r["station"] for r in man["files"] if r["format"] == "emtfxml"}
    assert any(victim in s for s in edi_ids), "victim station should still serve its EDI"
    assert not any(victim in s for s in xml_ids), "victim station must have no EMTF-XML manifest row"


def test_xml_failures_empty_on_clean_build(tmp_path):
    """ANTI-VACUOUS COMPANION: on a clean build (no forced failure) every served station's XML emits,
    so xml_failures is empty for every survey and no 'EMTF-XML emission failed' warning is raised. Guards
    against the field being populated by accident (which would make the RED-proof test above vacuous)."""
    out, _prod, _r = _build(tmp_path)
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    for slug, survey in rep["surveys"].items():
        assert survey.get("xml_failures", []) == [], f"{slug}: clean build must have no xml_failures"
        assert not [w for w in survey["warnings"] if "EMTF-XML emission failed" in w], \
            f"{slug}: clean build must raise no xml-emission-failed warning"
        assert survey.get("product_failures", {}) == {}, \
            f"{slug}: clean build must record no product-emission failures"


def test_identity_rewrite_notes_carry_no_per_station_value(tmp_path):
    """The identity conditioning notes must be CLASS-STABLE in what the build persists and prints: a
    note that interpolates the station id or its source filename is a distinct string per station, so
    the by-note aggregation cannot fold it and the log grows one line per station. The mapping itself
    belongs in build_report's `station_id_rewrites`.

    FAILS IF: 'station.id->', 'source_id_preserved_in_site_name:' or
    'source_file_preserved_in_site_name:' reappears in a persisted note or in the build log."""
    out, prod, r = _build(tmp_path)
    banned = ("station.id->", "source_id_preserved_in_site_name:",
              "source_file_preserved_in_site_name:")
    for bad in banned:
        assert bad not in r.stderr, f"{bad!r} still names a per-station value in the build log"
    for sj in sorted(prod.rglob("station.json")):
        text = json.dumps(json.loads(sj.read_text(encoding="utf-8")).get("canonical_conditioning") or [])
        for bad in banned:
            assert bad not in text, f"{sj}: {bad!r} still names a per-station value"
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    for slug, survey in rep["surveys"].items():
        assert isinstance(survey.get("station_id_rewrites", []), list), slug
        for row in survey.get("station_id_rewrites", []):
            assert row["station"] and row["site_id"], row


def test_coordinate_flag_notices_are_folded_in_a_real_build(tmp_path):
    """The QC coordinate-flag notice is survey-level in the log: one line per survey per flag,
    carrying the count and a bounded set of examples, with every row still in qc_report.json.

    FAILS IF: the QC block prints one '[notice] coordinate flag ...' line per flagged station (a
    corpus build then prints one line per station), or the folded counts do not account for every
    qc_report row."""
    out, _prod, r = _build(tmp_path)
    rows = json.loads((out / "qc_report.json").read_text(encoding="utf-8"))["coord_flags"]
    assert rows, "the sample corpus must flag at least one coordinate, else this pin is vacuous"
    lines = [ln for ln in r.stdout.splitlines() if "[notice] coordinate flag" in ln]
    assert lines, "a flagged coordinate must still be announced"
    pat = re.compile(r"^  \[notice\] coordinate flag '[^']+'( \(resolved\))? in \S+: "
                     r"(?P<n>\d+) station\(s\), e\.g\. \S")
    counts = []
    for ln in lines:
        m = pat.match(ln)
        assert m, f"not a folded coordinate-flag line: {ln!r}"
        counts.append(int(m.group("n")))
    assert sum(counts) == len(rows), (counts, len(rows))
    assert len(lines) <= len(rows), (lines, len(rows))


def test_mth5_write_failures_fold_once_across_both_served_tiers(tmp_path, monkeypatch, capsys):
    """Tier 1 (per-station MTH5) and tier 2 (survey bundle) re-read the SAME source files, so a
    station whose TF write fails fails in both. The fold must report that fault ONCE: one
    '[h5] WARN' line for the survey and one row in product_failures, carrying the producer path it
    was first seen in.

    FAILS IF: the [h5] arm prints one line per failing station per tier, or the second tier adds a
    second ledger row for a file already recorded."""
    victim = "A2"

    real_stamp = bp._stamp_mth5_source_provenance

    def _fake_stamp(station_metadata, record):
        if victim in str(record.get("id") or ""):
            raise RuntimeError("simulated MTH5 station write failure")
        return real_stamp(station_metadata, record)

    monkeypatch.setattr(bp, "_stamp_mth5_source_provenance", _fake_stamp)
    out = tmp_path / "data"
    rc = bp.main(["--surveys", str(SURVEYS), "--out", str(out), "--products", str(tmp_path / "p"),
                  "--bundle-edi", "--no-validate", "--survey-h5", "--station-h5"])
    assert rc == 0, "a per-station MTH5 failure must not abort the build"

    err = capsys.readouterr().err
    warn_lines = [ln for ln in err.splitlines() if "[h5] WARN" in ln and "RuntimeError" in ln]
    assert len(warn_lines) == 1, warn_lines
    assert warn_lines[0].endswith("1 file(s), e.g. Vulcan_A2.edi (station product)"), warn_lines[0]

    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    rows = [r for s in rep["surveys"].values() for r in s.get("product_failures", {}).get("h5", [])]
    assert len(rows) == 1, rows
    assert rows[0]["file"] == "Vulcan_A2.edi" and rows[0]["error"] == "RuntimeError", rows
    assert rows[0]["context"] == "station product", "the first occurrence context is kept"
