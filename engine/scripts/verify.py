#!/usr/bin/env python3
"""On-demand verification for the AusMT engine — runs the whole flow this repo's CI runs, locally.

  1. the test suite (pytest)
  2. a full build with mt_metadata (the sole extractor since the regex retirement)
  3. mtcat.json schema validation for the build

mt_metadata is REQUIRED to build, so this fails loudly if it is not installed.

Usage (from the repo root, in a CLEAN Python 3.12 all-pip venv — see environments/README.md for the
conda/pip ABI note):

    pip install -r requirements-dev.txt                          # core engine + tests
    pip install -r environments/requirements-mtmetadata-lock.txt # the pinned, reproducible engine
    python scripts/verify.py [--surveys data] [--skip-tests]

Exit code 0 only if every step passed.

C12 --data-dir mode: validate an EXISTING build output dir (e.g. a deploy/Makefile rebuild-data run's
just-produced builds/<timestamp>) in place, WITHOUT rebuilding or running pytest — the post-build gate
`make rebuild-data` runs inside the build-runner container before the atomic `current` symlink swap.
Mutually exclusive with the default self-building invocation (--surveys/--skip-tests are ignored, with
a warning, if --data-dir is also given — the two modes read from different places and running both
would silently discard whichever result lost):

    python scripts/verify.py --data-dir /out/builds/20260705T120000Z
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "extract")]   # make ausmt_science.* and extract/_* importable


def _build(bp, surveys, extractor):
    out = Path(tempfile.mkdtemp(prefix=f"verify-{extractor}-"))
    # --bundle-edi so the download manifest is exercised end-to-end (served EDI/XML + per-survey zip).
    rc = bp.main(["--surveys", surveys, "--out", str(out), "--extractor", extractor, "--bundle-edi"])
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8")) if (out / "catalogue.json").exists() else []
    mtc = json.loads((out / "mtcat.json").read_text(encoding="utf-8")) if (out / "mtcat.json").exists() else {}
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8")) if (out / "manifest.json").exists() else {}
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8")) if (out / "build_report.json").exists() else None
    return rc, cat, mtc, man, rep, out


def _load_existing(data_dir: Path):
    """Load an ALREADY-BUILT output dir's own JSON (no rebuild) for --data-dir mode. Missing files
    degrade to the same empty defaults _build's post-build read uses, so a partial/pre-C-whatever
    build dir still gets a (failing, informative) validation pass rather than crashing on FileNotFound.
    build_report.json defaults to None (absent) so its presence check can FAIL loudly for a build that
    predates it, rather than silently pass an empty default."""
    def _read(name, default):
        p = data_dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    cat = _read("catalogue.json", [])
    mtc = _read("mtcat.json", {})
    man = _read("manifest.json", {})
    rep = _read("build_report.json", None)
    return cat, mtc, man, rep


def _live_survey_digests(surveys_root: Path) -> dict:
    """C18b (Amendment A3): recompute the sha256 of every survey.yaml under `surveys_root`, keyed by
    the SAME slug the build derives (safe_component(yaml.slug or dir.name)), so a sidecar slug resolves
    to its live source digest regardless of any slug/dir-name divergence. This reads the SOURCE
    survey.yaml files ONLY — never the cache dir; the consistency gate is cache-INDEPENDENT. Reuses
    build_portal's own slug/yaml helpers so the slug can never drift from what the build stamped."""
    import build_portal as bp  # noqa: PLC0415  (lazy: --data-dir mode otherwise never imports it)
    live: dict = {}
    if not surveys_root.is_dir():
        return live
    for d in sorted(surveys_root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        sy = d / "survey.yaml"
        if not sy.exists():
            continue
        y = bp._read_yaml(sy)
        if not isinstance(y, dict):
            continue
        slug = bp.safe_component(y.get("slug", d.name))
        live[slug] = hashlib.sha256(sy.read_bytes()).hexdigest()
    return live


def _check_digest_consistency(data_dir: Path, surveys_root: Path):
    """C18b (Amendment A3) — the cache-INDEPENDENT product-consistency gate.

    Compares out/products/survey_digests.json (the digest-stamp sidecar the build emitted) against the
    LIVE survey.yaml sources under `surveys_root`. FAILS when a served survey's XML was produced under a
    digest that differs from its current source — the 2026-07-07 incident shape (a stale cache entry
    served a pre-edit product while surveys.json showed the post-edit metadata). Two independent checks
    per served survey:
      * xml_digest_stamped[station] == recomputed live survey.yaml digest (the product-vs-source check);
      * yaml_digest_current == recomputed live digest (sidecar internal self-consistency — the build
        stamped a digest that no longer matches the source it claims to have read).

    Returns (ok: bool, lines: list[str]). NOT vacuous (Invariant 10): the live digest is recomputed
    from bytes on disk, an observable independent of anything the build wrote — a build that served a
    stale product cannot make this pass. Never reads the cache dir."""
    ok = True
    lines = []
    sidecar_path = data_dir / "products" / "survey_digests.json"
    if not sidecar_path.exists():
        # A build predating C18b (no sidecar) cannot be consistency-checked; fail LOUD rather than
        # silently pass — an armed gate (--surveys given) that finds no stamps to check is a real gap.
        lines.append(f"   consistency: FAIL — no digest-stamp sidecar at {sidecar_path} (build predates "
                     f"C18b, or products/ was not emitted); cannot verify product-vs-source freshness")
        return False, lines
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        lines.append(f"   consistency: FAIL — could not read {sidecar_path}: {e}")
        return False, lines

    live = _live_survey_digests(surveys_root)
    n_surveys_checked = 0
    for slug, entry in sorted(sidecar.items()):
        recomputed = live.get(slug)
        if recomputed is None:
            # A served survey whose source is not under this surveys_root: the gate cannot vouch for its
            # freshness. This is not the incident (that is a DIGEST mismatch), but an armed gate must not
            # pass a product it cannot source-check — flag it (does not, on its own, fail the run for a
            # legitimately raw/absent source, so keep it a NOTE unless a real mismatch also fires).
            lines.append(f"   consistency: NOTE {slug}: served but no survey.yaml under the surveys root "
                         f"(cannot source-check; raw/moved survey?)")
            continue
        n_surveys_checked += 1
        cur = entry.get("yaml_digest_current")
        stamps = entry.get("xml_digest_stamped") or {}
        if cur != recomputed:
            ok = False
            lines.append(
                f"   consistency: FAIL {slug}: sidecar yaml_digest_current={_s12(cur)} != live "
                f"survey.yaml digest {_s12(recomputed)} — the build stamped a digest that no longer "
                f"matches the source it read. stale cache product — do NOT clear the cache before "
                f"snapshotting it (tar) for forensics.")
        stale = sorted(sid for sid, d in stamps.items() if d != recomputed)
        if stale:
            ok = False
            lines.append(
                f"   consistency: FAIL {slug}: {len(stale)} of {len(stamps)} station(s) served XML keyed "
                f"under stale digest {_s12(stamps_common(stamps, stale))} != live survey.yaml digest "
                f"{_s12(recomputed)} (e.g. {', '.join(stale[:5])}) — stale cache product served past a "
                f"survey.yaml edit. do NOT clear the cache before snapshotting it (tar) for forensics.")
    if ok:
        lines.append(f"   consistency: PASS — {n_surveys_checked} served survey(s); every served XML "
                     f"digest matches its live survey.yaml (cache-independent source check)")
    return ok, lines


def _s12(d):
    """First 12 hex of a digest (or a readable marker for the empty/None cases) for messages."""
    if not d:
        return "<empty>"
    return str(d)[:12]


def stamps_common(stamps: dict, stale_ids) -> str:
    """The single stale digest to name in the message when all stale stations share one (the usual
    stale-cache case); '<mixed>' if the stale stations somehow carry different digests."""
    vals = {stamps[s] for s in stale_ids}
    return next(iter(vals)) if len(vals) == 1 else "<mixed>"


def _check_mtcat_and_manifest(cat, mtc, man, base_dir: Path, jsonschema, schema, man_schema, station_label="stations"):
    """The two post-build checks SHARED by the self-building path (main()) and --data-dir mode
    (_validate_data_dir): (1) mtcat.json schema-conformance + non-empty catalogue, (2) manifest.json
    integrity — every repo-tier artifact's sha256 RECOMPUTED from the bytes at `base_dir / row['url']`
    (an independent observable; a manifest that lies about its bytes is a hard failure) — + schema.
    Returns (ok: bool, lines: list[str]) so the two call sites can print in their own report style."""
    ok = True
    lines = []
    schema_ok = "unchecked"
    if jsonschema and mtc:
        try:
            jsonschema.validate(mtc, schema)
            schema_ok = "PASS"
        except Exception as e:  # noqa: BLE001
            schema_ok = f"FAIL ({str(e)[:80]})"
            ok = False
    step_ok = len(cat) > 0 and not schema_ok.startswith("FAIL")
    ok &= step_ok
    lines.append(f"   {station_label}={len(cat)} mtcat_schema={schema_ok} -> {'ok' if step_ok else 'FAIL'}")

    man_ok = "unchecked"
    arts = man.get("files", []) + man.get("bundles", [])
    if arts:
        bad = [row["url"] for row in arts
               if row.get("tier") == "repo" and row.get("url")
               and (not (base_dir / row["url"]).exists()
                    or hashlib.sha256((base_dir / row["url"]).read_bytes()).hexdigest() != row.get("sha256"))]
        if bad:
            man_ok = f"FAIL (integrity: {bad[:3]})"
            ok = False
        elif jsonschema:
            try:
                jsonschema.validate(man, man_schema)
                man_ok = "PASS"
            except Exception as e:  # noqa: BLE001
                man_ok = f"FAIL ({str(e)[:60]})"
                ok = False
        else:
            man_ok = "integrity-OK (schema unchecked)"
    lines.append(f"   manifest: {len(man.get('files', []))} files + {len(man.get('bundles', []))} bundles "
                 f"-> {man_ok}")
    return ok, lines


def _check_build_report(rep, man, jsonschema, rep_schema):
    """build_report.json presence + schema-validity + a CHEAP cross-count against the manifest.

    The correct cross-count is a SUBSET relation, not equality: the manifest lists only the SERVED
    stations (bytes gated by the licence + C1 access gates), while build_report.stations_built counts
    every station BUILT into the discovery surfaces. An embargoed / non-redistributable survey builds
    stations that are never served, so served <= built (never ==) in general. We assert exactly that —
    every DISTINCT served EDI station must also be counted in totals.stations_built — plus the report's
    internal totals self-consistency (totals == sum over surveys). Both are independent observables: the
    manifest and the report are produced from different build accumulators, so a violation means one is
    wrong. Returns (ok, lines). A build predating build_report.json (rep is None) FAILS loudly."""
    ok = True
    lines = []
    if rep is None:
        lines.append("   build_report: FAIL — build_report.json is absent (build predates it, or was "
                     "not emitted)")
        return False, lines
    schema_ok = "unchecked"
    if jsonschema and rep_schema:
        try:
            jsonschema.validate(rep, rep_schema)
            schema_ok = "PASS"
        except Exception as e:  # noqa: BLE001
            schema_ok = f"FAIL ({str(e)[:80]})"
            ok = False
    # cross-count: DISTINCT served EDI stations in the manifest are a SUBSET of the built count.
    served = {r.get("station") for r in man.get("files", []) if r.get("format") == "edi"}
    built = (rep.get("totals") or {}).get("stations_built")
    count_ok = "PASS"
    if not isinstance(built, int) or len(served) > built:
        count_ok = f"FAIL (manifest-served={len(served)} > report-built={built}; served must be a subset)"
        ok = False
    # internal totals self-consistency (cheap): totals == sum over surveys
    _sum_built = sum(s.get("stations_built", 0) for s in (rep.get("surveys") or {}).values())
    if built != _sum_built:
        count_ok = f"FAIL (totals.stations_built={built} != sum-of-surveys={_sum_built})"
        ok = False
    lines.append(f"   build_report: schema={schema_ok} stations_built={built} "
                 f"(manifest-served={len(served)}) -> {count_ok}")
    return ok, lines


def _validate_data_dir(data_dir: Path, surveys_root: Path | None = None) -> bool:
    """The --data-dir check: mtcat.json schema-conformance + manifest.json integrity/schema, against an
    EXISTING build dir's own files — the same two checks the self-building path runs post-build (via
    _check_mtcat_and_manifest), minus the build step itself. Returns True (PASS) / False (FAIL).

    C18b (Amendment A3): when `surveys_root` is given (the Makefile's rebuild-data now passes
    --surveys), ALSO run the cache-INDEPENDENT digest-consistency gate — the served-product digest
    stamps vs the live survey.yaml sources. When it is None the gate SKIPS with a LOUD note (all
    pre-C18b call sites keep their exact behaviour). The gate never reads the cache dir."""
    if not data_dir.is_dir():
        print(f"ERROR: --data-dir {data_dir} is not an existing directory", file=sys.stderr)
        print("VERIFY:", "FAIL")
        return False

    try:
        import jsonschema
    except ImportError:
        jsonschema = None
        print("note: jsonschema not installed — schema conformance will be unchecked")
    schema = json.loads((ROOT / "schema" / "mtcat.schema.json").read_text(encoding="utf-8"))
    man_schema = json.loads((ROOT / "schema" / "manifest.schema.json").read_text(encoding="utf-8"))
    rep_schema = json.loads((ROOT / "schema" / "build_report.schema.json").read_text(encoding="utf-8"))

    cat, mtc, man, rep = _load_existing(data_dir)
    print(f"== data-dir check ({data_dir}) ==")
    ok, lines = _check_mtcat_and_manifest(cat, mtc, man, data_dir, jsonschema, schema, man_schema,
                                          station_label="stations")
    for ln in lines:
        print(ln)
    rep_ok, rep_lines = _check_build_report(rep, man, jsonschema, rep_schema)
    for ln in rep_lines:
        print(ln)
    ok &= rep_ok

    # C18b consistency gate — armed only with --surveys.
    if surveys_root is not None:
        cons_ok, cons_lines = _check_digest_consistency(data_dir, surveys_root)
        for ln in cons_lines:
            print(ln)
        ok &= cons_ok
    else:
        print("   consistency: SKIPPED — --surveys not given, so the cache-staleness digest gate did "
              "NOT run (C18b/A3). Pass --surveys <root> to compare served products against live "
              "survey.yaml sources; the Makefile's rebuild-data passes it.")

    print("VERIFY:", "PASS" if ok else "FAIL")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # --surveys defaults to None so "absent" is distinguishable from an explicit ./data. The self-build
    # path falls back to ROOT/data below (unchanged default behaviour); --data-dir mode uses it to ARM
    # the C18b digest-consistency gate (absent => the gate skips loudly).
    ap.add_argument("--surveys", default=None,
                    help="survey-package root (default in self-build mode: ./data). In --data-dir mode "
                         "this ARMS the C18b cache-staleness digest gate: the served-product digest "
                         "stamps are compared against the LIVE survey.yaml sources at this root "
                         "(cache-independent). Absent in --data-dir mode => that gate SKIPS loudly.")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--data-dir", default=None,
                    help="C12: validate an EXISTING build output dir in place (mtcat.json schema + "
                         "manifest.json integrity/schema) instead of running pytest + a fresh build. "
                         "For a post-build gate over an already-produced builds/<timestamp> dir (see "
                         "deploy/Makefile's rebuild-data). --skip-tests is ignored here; --surveys, if "
                         "given, ARMS the C18b consistency gate (it is NOT ignored — C18b/A3).")
    a = ap.parse_args(argv)

    if a.data_dir is not None:
        if a.skip_tests:
            print("note: --data-dir ignores --skip-tests (different mode: validates an existing build "
                  "dir, does not rebuild or run pytest)", file=sys.stderr)
        # --surveys is now MEANINGFUL in --data-dir mode (arms the C18b consistency gate); pass it through.
        surveys_root = Path(a.surveys) if a.surveys is not None else None
        return 0 if _validate_data_dir(Path(a.data_dir), surveys_root) else 1

    ok = True
    self_surveys = a.surveys if a.surveys is not None else str(ROOT / "data")

    if not a.skip_tests:
        print("== pytest ==")
        ok &= subprocess.call([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")],
                              cwd=str(ROOT)) == 0

    import build_portal as bp
    import _mtm as mtm
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
        print("note: jsonschema not installed — mtcat conformance will be unchecked")
    schema = json.loads((ROOT / "schema" / "mtcat.schema.json").read_text(encoding="utf-8"))

    if not mtm.available():
        print("ERROR: mt_metadata is not installed; it is REQUIRED to build "
              "(pip install -r environments/requirements-mtmetadata-lock.txt).")
        print("VERIFY:", "FAIL")
        return 1

    man_schema = json.loads((ROOT / "schema" / "manifest.schema.json").read_text(encoding="utf-8"))
    rep_schema = json.loads((ROOT / "schema" / "build_report.schema.json").read_text(encoding="utf-8"))

    print("== build (mt_metadata) ==")
    rc, cat, mtc, man, rep, out = _build(bp, self_surveys, "mt_metadata")
    # station_label includes "exit=" here (the self-build path has a build return code to report;
    # --data-dir mode has no build step, so _validate_data_dir's call omits it) -- otherwise this is
    # the SAME mtcat-schema + manifest-integrity/schema check --data-dir mode runs post-build.
    check_ok, lines = _check_mtcat_and_manifest(cat, mtc, man, out, jsonschema, schema, man_schema,
                                                station_label=f"exit={rc} stations")
    ok &= check_ok and rc == 0
    for ln in lines:
        print(ln)
    rep_ok, rep_lines = _check_build_report(rep, man, jsonschema, rep_schema)
    for ln in rep_lines:
        print(ln)
    ok &= rep_ok

    print("VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
