#!/usr/bin/env python3
"""On-demand verification for the AusMT engine: runs the whole flow this repo's CI runs, locally.

  1. the test suite (pytest)
  2. a full build with mt_metadata (the sole extractor since the regex retirement)
  3. mtcat.json schema validation for the build, the manifest and build_report checks, the
     survey-metadata gate (every products/<slug>/survey-metadata.json validates with format checking,
     the slug set equals mtcat's surveys[], and the build skipped no survey) and the station gate
     (every products/<slug>/<station>/station.json validates, holds the semantic layer beyond JSON
     Schema, and its ausmt_id set equals mtcat's stations[])

mt_metadata is REQUIRED to build, so this fails loudly if it is not installed.

Usage (from the repo root, in a CLEAN Python 3.12 all-pip venv; see environments/README.md for the
conda/pip ABI note):

    pip install -r requirements-dev.txt                          # core engine + tests
    pip install -r environments/requirements-mtmetadata-lock.txt # the pinned, reproducible engine
    python scripts/verify.py [--surveys data] [--skip-tests]

Exit code 0 only if every step passed.

--data-dir mode: validate an EXISTING build output dir (e.g. a deploy/Makefile rebuild-data run's
just-produced builds/<timestamp>) in place, WITHOUT rebuilding or running pytest: the post-build gate
`make rebuild-data` runs inside the build-runner container before the atomic `current` symlink swap.
Mutually exclusive with the default self-building invocation (--surveys/--skip-tests are ignored, with
a warning, if --data-dir is also given, because the two modes read from different places and both
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

import _stationcheck as stcheck  # noqa: E402  (stdlib-only; the station gate must not need the ingest stack)


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
    """Recompute the sha256 of every survey.yaml under `surveys_root`, keyed by
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
    """ The cache-INDEPENDENT product-consistency gate.

    Compares out/products/survey_digests.json (the digest-stamp sidecar the build emitted) against the
    LIVE survey.yaml sources under `surveys_root`. FAILS when a served survey's XML was produced under a
    digest that differs from its current source - the incident shape (a stale cache entry
    served a pre-edit product while surveys.json showed the post-edit metadata). Two independent checks
    per served survey:
      * xml_digest_stamped[station] == recomputed live survey.yaml digest (the product-vs-source check);
      * yaml_digest_current == recomputed live digest (sidecar internal self-consistency - it fails
        when the build stamped a digest that does not match the source it claims to have read).

    Returns (ok: bool, lines: list[str]). NOT vacuous (Invariant 10): the live digest is recomputed
    from bytes on disk, an observable independent of anything the build wrote - a build that served a
    stale product cannot make this pass. Never reads the cache dir."""
    ok = True
    lines = []
    sidecar_path = data_dir / "products" / "survey_digests.json"
    if not sidecar_path.exists():
        # A build predating (no sidecar) cannot be consistency-checked; fail LOUD rather than
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


def _duplicate_repo_urls(arts):
    """Repo-tier artifact urls claimed by more than one manifest row, as readable 'url (a <-> b)'
    strings. One served file belongs to exactly one row: the download contract says a row's sha256 is
    the integrity of THAT station's artifact, so two rows over one file make both digests verify while
    one station serves the other's bytes. Recomputing sha256 cannot see this (both rows hash the file
    they name), which is why it is checked separately. Scoped to tier=repo, like the integrity check
    above it: an nci-tier row resolves to a flat remote directory this script cannot observe."""
    seen, dupes = {}, []
    for row in arts:
        url = row.get("url")
        if row.get("tier") != "repo" or not url:
            continue
        who = row.get("ausmt_id") or row.get("slug") or "?"
        if url in seen:
            dupes.append(f"{url} ({seen[url]} <-> {who})")
        else:
            seen[url] = who
    return dupes


def _check_mtcat_and_manifest(cat, mtc, man, base_dir: Path, jsonschema, schema, man_schema, station_label="stations"):
    """The two post-build checks SHARED by the self-building path (main()) and --data-dir mode
    (_validate_data_dir): (1) mtcat.json schema-conformance + non-empty catalogue, (2) manifest.json
    integrity — every repo-tier artifact's sha256 RECOMPUTED from the bytes at `base_dir / row['url']`
    (an independent observable; a manifest that lies about its bytes is a hard failure), plus schema,
    plus no served file claimed by two rows (_duplicate_repo_urls: the one integrity failure that
    recomputing digests cannot see).
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
        dupes = _duplicate_repo_urls(arts)
        if bad:
            man_ok = f"FAIL (integrity: {bad[:3]})"
            ok = False
        elif dupes:
            man_ok = f"FAIL (one served file claimed by two rows: {dupes[:3]})"
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
    stations (bytes gated by the licence + access gates), while build_report.stations_built counts
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


DEFAULT_PARSE_FAILURE_ALLOW = ROOT / "scripts" / "parse-failures-allowed.txt"
DEFAULT_STATIONS_DROPPED_ALLOW = ROOT / "scripts" / "stations-dropped-allowed.txt"


def _curator_allow_list(path: Path) -> set:
    """The curator's allow list: one `<survey slug>/<source file name>` per line, `#` comments and
    blank lines ignored. A MISSING file is an EMPTY list, not a pass: the gates below are the point,
    and a deployment that has deleted the file must not thereby allow everything.

    Shared by both lost-station gates, which is what keeps their rules the same rule."""
    if not path.is_file():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")}


def _check_source_parse_failures(rep, allow_path: Path):
    """THE LOST-STATION GATE. build_report.json has recorded `source_parse_failures` since the GDS
    readers arrived -- which source file the reader refused, and what it said -- and until now nothing
    read it. Measured cost: nine files refused, build exit 0,
    no SKIP line, package validator 0 FAIL, and nine transfer functions absent from a corpus nobody
    was told had lost them.

    The BUILD still exits 0 on a parse failure -- one malformed legacy file must not take the whole
    corpus down with it -- so the verifier is where the decision belongs. Any refusal FAILs this run,
    naming the survey and the file, unless the curator has written `<slug>/<file>` into the allow
    file: a reviewed repository artifact, empty today, whose every line is a station the corpus has
    deliberately given up on. Same posture as the loud-skip gate one level up, where a survey the
    validator FAILed stops the swap rather than quietly vanishing.

    Returns (ok, lines). A build predating the field cannot vouch for itself and FAILS, exactly as
    the surveys_skipped_validation and surveys_dropped gates do."""
    lines = []
    if not isinstance(rep, dict):
        return False, ["   source_parse_failures: FAIL - build_report.json is absent, so the build "
                       "cannot vouch that no source file was refused"]
    allow = _curator_allow_list(allow_path)
    missing, offenders = [], []
    for slug, entry in sorted((rep.get("surveys") or {}).items()):
        rows = entry.get("source_parse_failures") if isinstance(entry, dict) else None
        if rows is None:
            missing.append(slug)
            continue
        for row in rows:
            key = f"{slug}/{row.get('file')}"
            if key not in allow:
                offenders.append((key, row.get("error", "")))
    if missing:
        return False, [f"   source_parse_failures: FAIL - {len(missing)} survey(s) carry no "
                       f"source_parse_failures list ({', '.join(missing[:8])}"
                       f"{', ...' if len(missing) > 8 else ''}); the build predates the gate, or the "
                       f"report was not emitted, so it cannot vouch that no station was lost"]
    if offenders:
        lines.append(f"   source_parse_failures: FAIL - the reader REFUSED {len(offenders)} source "
                     f"file(s); each is a station this build does not publish, and none is named in "
                     f"{allow_path}. Fix the file or the reader, or record the loss deliberately in "
                     f"that allow file; never swap this build in.")
        lines.extend(f"      {key}: {error}" for key, error in offenders[:20])
        if len(offenders) > 20:
            lines.append(f"      ... and {len(offenders) - 20} more")
        return False, lines
    return True, [f"   source_parse_failures: PASS (none refused; {len(allow)} allowed by "
                  f"{allow_path.name})"]


def _check_stations_dropped(rep, allow_path: Path):
    """THE LOST-STATION GATE, over the ledger that answers the whole question. `source_parse_failures`
    names the files the READER refused; `stations_dropped` names every station this corpus does not
    publish, whatever refused it: the convention-gate FAILs, the records with no coordinates or no
    periods, the MTH5 read failures, and the parse failures too. Only the first was gated, so a
    station dropped at a gate still reached a green verify with nothing standing in its way.

    Same rule as its sibling, deliberately: any row FAILs this run unless the curator has written
    `<slug>/<file>` into the allow file, and the BUILD still exits 0 either way, because the decision
    belongs to the verifier and not to a build that must survive one bad legacy file.

    Keyed on the FILE. The row's `station` is the id the build settled on BEFORE any station_ids
    override applies, so for a third-party release it is neither the file name nor the published id;
    it is echoed beside the file instead, which is what a curator needs to match a finding to a row.
    A row carrying no file at all comes from an engine older than the field and cannot be allow-listed
    by name; it is reported as an offender rather than passed.

    Returns (ok, lines). A build predating the field cannot vouch for itself and FAILS, exactly as the
    surveys_skipped_validation and surveys_dropped gates do."""
    lines = []
    if not isinstance(rep, dict):
        return False, ["   stations_dropped: FAIL - build_report.json is absent, so the build cannot "
                       "vouch that no station was dropped"]
    allow = _curator_allow_list(allow_path)
    missing, offenders, allowed_seen = [], [], 0
    for slug, entry in sorted((rep.get("surveys") or {}).items()):
        rows = entry.get("stations_dropped") if isinstance(entry, dict) else None
        if rows is None:
            missing.append(slug)
            continue
        for row in rows:
            key = f"{slug}/{row.get('file')}" if row.get("file") else f"{slug}/<file not recorded>"
            if key in allow:
                allowed_seen += 1
            else:
                offenders.append((key, str(row.get("station", "")), str(row.get("reason", ""))))
    if missing:
        return False, [f"   stations_dropped: FAIL - {len(missing)} survey(s) carry no "
                       f"stations_dropped list ({', '.join(missing[:8])}"
                       f"{', ...' if len(missing) > 8 else ''}); the build predates the field, or the "
                       f"report was not emitted, so it cannot vouch that no station was lost"]
    if offenders:
        lines.append(f"   stations_dropped: FAIL - the build DROPPED {len(offenders)} station(s) that "
                     f"this corpus does not publish, and none is named in {allow_path}. Fix the file "
                     f"or the gate, or record the loss deliberately in that allow file; never swap "
                     f"this build in.")
        lines.extend(f"      {key} (station {station}): {reason}"
                     for key, station, reason in offenders[:20])
        if len(offenders) > 20:
            lines.append(f"      ... and {len(offenders) - 20} more")
        return False, lines
    # The count of drops this build actually made is stated, never just "none unlisted": a PASS that
    # reads like "nothing was lost" over a build that lost six stations is the silence this gate exists
    # to end.
    return True, [f"   stations_dropped: PASS ({allowed_seen} dropped, each named in "
                  f"{allow_path.name}, which carries {len(allow)} entry(s))"]


def _scan_nulls_and_empties(doc):
    """Every null and every empty array/object at any depth of one survey-metadata document (it
    defines no null at all); paths as '$.a.b[0]'."""
    nulls, empties = [], []

    def walk(node, path):
        if isinstance(node, dict):
            if not node:
                empties.append(path)
            for k, v in node.items():
                if v is None:
                    nulls.append(f"{path}.{k}")
                else:
                    walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            if not node:
                empties.append(path)
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(doc, "$")
    return nulls, empties


def _check_survey_metadata(base_dir: Path, mtc, rep, jsonschema, sm_schema):
    """The survey-metadata gate (the second public contract), shared by --data-dir mode and the
    self-building path. Three independent checks, any of which FAILs the run:

      1. The LOUD skip: build_report.json's `surveys_skipped_validation` must be PRESENT and EMPTY.
         A non-empty list means the build skipped a survey the validator FAILed; the rest of the corpus
         built and the build exited 0, but that survey is gone from EVERY public surface, so the swap
         must not happen (make rebuild-data reads this exit code). An absent key means a build that
         predates the gate, which cannot vouch for itself either.
      2. every products/<slug>/survey-metadata.json validates against schema/ausmt-survey-metadata.
         schema.json WITH FORMAT CHECKING (date / date-time), carries no null and no empty container,
         and states the survey_id its directory names.
      3. the set of document slugs equals mtcat.json's surveys[].survey_id exactly (one document per
         catalogued survey, no stray document for a survey the catalogue does not list).

    Returns (ok, lines). Reads the files on disk, never a build's in-memory state."""
    ok = True
    lines = []
    skipped = (rep or {}).get("surveys_skipped_validation") if isinstance(rep, dict) else None
    if skipped is None:
        ok = False
        lines.append("   survey-metadata: FAIL - build_report.json carries no surveys_skipped_validation list "
                     "(build predates the loud-skip gate, or the report was not emitted); cannot vouch that "
                     "no survey was silently skipped")
    elif skipped:
        ok = False
        lines.append(f"   survey-metadata: FAIL - the build SKIPPED {len(skipped)} survey(s) the validator FAILed "
                     f"({', '.join(str(s) for s in skipped)}); they are absent from every public surface. Fix the "
                     f"survey.yaml (or withdraw the package deliberately) and rebuild; never swap this build in.")
    # 1b. The same rule for every OTHER survey-granularity drop: unreadable or non-mapping
    #     survey.yaml, invalid coordinate policy or station_ids block, a zero-station parse, an
    #     unserialisable SMETA. A stderr-only drop lets this gate pass a build that silently lost
    #     a survey, which is the exact swap it exists to prevent.
    dropped = (rep or {}).get("surveys_dropped") if isinstance(rep, dict) else None
    if dropped is None:
        ok = False
        lines.append("   survey-metadata: FAIL - build_report.json carries no surveys_dropped list "
                     "(build predates the drop gate, or the report was not emitted); cannot vouch that "
                     "no survey was silently dropped")
    elif dropped:
        ok = False
        _names = ", ".join(str(e.get("survey", e)) + (" (" + str(e.get("reason")) + ")" if isinstance(e, dict) and e.get("reason") else "")
                           for e in dropped)
        lines.append(f"   survey-metadata: FAIL - the build DROPPED {len(dropped)} survey(s): {_names}; they are "
                     f"absent from every public surface. Fix the package (or withdraw it deliberately) and "
                     f"rebuild; never swap this build in.")
    docs = sorted((base_dir / "products").glob("*/survey-metadata.json")) if (base_dir / "products").is_dir() else []
    validator = None
    if jsonschema and sm_schema:
        validator = jsonschema.Draft7Validator(sm_schema, format_checker=jsonschema.FormatChecker())
    bad = []
    slugs = set()
    for p in docs:
        slug = p.parent.name
        slugs.add(slug)
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            bad.append(f"{slug}: unreadable ({type(e).__name__}: {e})")
            continue
        if not isinstance(doc, dict) or doc.get("survey_id") != slug:
            bad.append(f"{slug}: survey_id {doc.get('survey_id') if isinstance(doc, dict) else doc!r} != directory")
        nulls, empties = _scan_nulls_and_empties(doc)
        bad.extend(f"{slug}: null at {n}" for n in nulls[:3])
        bad.extend(f"{slug}: empty container at {n}" for n in empties[:3])
        if validator is not None:
            bad.extend(f"{slug}: {e.message[:80]} (at /{'/'.join(str(x) for x in e.absolute_path)})"
                       for e in list(validator.iter_errors(doc))[:3])
    if bad:
        ok = False
        lines.append(f"   survey-metadata: FAIL - {len(bad)} document violation(s): {bad[:5]}")
    catalogued = {s.get("survey_id") for s in (mtc or {}).get("surveys", []) if isinstance(s, dict)}
    if slugs != catalogued:
        ok = False
        lines.append(f"   survey-metadata: FAIL - document slug set != mtcat surveys[].survey_id "
                     f"(documents without a catalogued survey: {sorted(slugs - catalogued)[:5]}; catalogued "
                     f"surveys without a document: {sorted(catalogued - slugs)[:5]})")
    if ok:
        lines.append(f"   survey-metadata: PASS - {len(docs)} document(s) validated "
                     f"({'format checking on' if validator is not None else 'schema unchecked'}), slug set == "
                     f"mtcat surveys[], surveys_skipped_validation empty")
    return ok, lines


def _check_station_metadata(base_dir: Path, mtc, jsonschema, st_schema):
    """The station gate (the third public contract), shared by --data-dir mode and the self-building
    path. Two independent checks, either of which FAILs the run:

      1. every products/<slug>/<station>/station.json validates against
         engine/schema/ausmt-station.schema.json WITH FORMAT CHECKING (the run time_period date-times),
         states the survey_id and station its directory names, and holds the SEMANTIC layer JSON
         Schema cannot state (extract/_stationcheck.py, the same one the build ran over the same
         documents: run reference integrity, unique run and resource ids, time_period ordering,
         channel shape per component family, withheld-branch closure, DOI syntax, the 1.x
         distribution.edi_path equivalence pin);
      2. the set of published ausmt_ids equals mtcat.json's stations[].station_id exactly, with no id
         published twice (the station half of the identity chain the sibling check pins for
         surveys).

    Returns (ok, lines). Reads the files on disk, never a build's in-memory state, which is what makes
    it an independent second opinion on the bytes the build just wrote."""
    ok = True
    lines = []
    products = base_dir / "products"
    docs = sorted(products.glob("*/*/station.json")) if products.is_dir() else []
    validator = None
    if jsonschema and st_schema:
        validator = jsonschema.Draft7Validator(st_schema, format_checker=jsonschema.FormatChecker())
    bad, ids, dups = [], set(), []
    for p in docs:
        station, slug = p.parent.name, p.parent.parent.name
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            bad.append(f"{slug}/{station}: unreadable ({type(e).__name__}: {e})")
            continue
        if not isinstance(doc, dict):
            bad.append(f"{slug}/{station}: not a JSON object")
            continue
        if doc.get("survey_id") != slug or doc.get("station") != station:
            bad.append(f"{slug}/{station}: states survey_id={doc.get('survey_id')!r} "
                       f"station={doc.get('station')!r}, which its directory does not name")
        aid = doc.get("ausmt_id")
        if aid in ids:
            dups.append(aid)
        ids.add(aid)
        bad.extend(f"{slug}/{station}: {v}" for v in stcheck.violations(doc)[:3])
        if validator is not None:
            bad.extend(f"{slug}/{station}: {e.message[:80]} (at /{'/'.join(str(x) for x in e.absolute_path)})"
                       for e in list(validator.iter_errors(doc))[:3])
    if bad:
        ok = False
        lines.append(f"   station-metadata: FAIL - {len(bad)} document violation(s): {bad[:5]}")
    if dups:
        ok = False
        lines.append(f"   station-metadata: FAIL - ausmt_id published more than once: {sorted(set(dups))[:5]}")
    catalogued = {s.get("station_id") for s in (mtc or {}).get("stations", []) if isinstance(s, dict)}
    if ids != catalogued:
        ok = False
        lines.append(f"   station-metadata: FAIL - published ausmt_id set != mtcat stations[].station_id "
                     f"(records without a catalogued station: {sorted(x for x in ids - catalogued if x)[:5]}; "
                     f"catalogued stations without a record: {sorted(x for x in catalogued - ids if x)[:5]})")
    if ok:
        lines.append(f"   station-metadata: PASS - {len(docs)} document(s) validated "
                     f"({'format checking on' if validator is not None else 'schema unchecked'}) and hold "
                     f"the semantic layer, ausmt_id set == mtcat stations[]")
    return ok, lines


def _validate_data_dir(data_dir: Path, surveys_root: Path | None = None,
                       allow_parse_failures: Path = DEFAULT_PARSE_FAILURE_ALLOW,
                       allow_stations_dropped: Path = DEFAULT_STATIONS_DROPPED_ALLOW) -> bool:
    """The --data-dir check: mtcat.json schema-conformance + manifest.json integrity/schema, against an
    EXISTING build dir's own files — the same two checks the self-building path runs post-build (via
    _check_mtcat_and_manifest), minus the build step itself. Returns True (PASS) / False (FAIL).

    When `surveys_root` is given (the Makefile's rebuild-data passes
    --surveys), ALSO run the cache-INDEPENDENT digest-consistency gate: the served-product digest
    stamps vs the live survey.yaml sources. When it is None the gate SKIPS with a LOUD note (all
    call sites keep their exact behaviour). The gate never reads the cache dir."""
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
    sm_schema = json.loads((ROOT / "schema" / "ausmt-survey-metadata.schema.json").read_text(encoding="utf-8"))
    st_schema = json.loads((ROOT / "schema" / "ausmt-station.schema.json").read_text(encoding="utf-8"))

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
    pf_ok, pf_lines = _check_source_parse_failures(rep, allow_parse_failures)
    for ln in pf_lines:
        print(ln)
    ok &= pf_ok
    sd_ok, sd_lines = _check_stations_dropped(rep, allow_stations_dropped)
    for ln in sd_lines:
        print(ln)
    ok &= sd_ok
    sm_ok, sm_lines = _check_survey_metadata(data_dir, mtc, rep, jsonschema, sm_schema)
    for ln in sm_lines:
        print(ln)
    ok &= sm_ok
    st_ok, st_lines = _check_station_metadata(data_dir, mtc, jsonschema, st_schema)
    for ln in st_lines:
        print(ln)
    ok &= st_ok

    # The cache-consistency gate - armed only with --surveys.
    if surveys_root is not None:
        cons_ok, cons_lines = _check_digest_consistency(data_dir, surveys_root)
        for ln in cons_lines:
            print(ln)
        ok &= cons_ok
    else:
        print("   consistency: SKIPPED, because --surveys was not given, so the cache-staleness "
              "digest gate did NOT run. Pass --surveys <root> to compare served products against "
              "live survey.yaml sources; the Makefile's rebuild-data passes it.")

    print("VERIFY:", "PASS" if ok else "FAIL")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # --surveys defaults to None so "absent" is distinguishable from an explicit ./data. The self-build
    # path falls back to ROOT/data below (unchanged default behaviour); --data-dir mode uses it to ARM
    # the digest-consistency gate (absent => the gate skips loudly).
    ap.add_argument("--surveys", default=None,
                    help="survey-package root (default in self-build mode: ./data). In --data-dir mode "
                         "this ARMS the cache-staleness digest gate: the served-product digest "
                         "stamps are compared against the LIVE survey.yaml sources at this root "
                         "(cache-independent). Absent in --data-dir mode => that gate SKIPS loudly.")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--allow-parse-failures", default=str(DEFAULT_PARSE_FAILURE_ALLOW),
                    help="the curator's allow file for source files the reader refused: one "
                         "`<survey slug>/<file name>` per line, '#' comments ignored. A refusal not "
                         "named there FAILS this run (the build itself still exits 0). Defaults to "
                         "the reviewed in-repo file, which is empty.")
    ap.add_argument("--allow-stations-dropped", default=str(DEFAULT_STATIONS_DROPPED_ALLOW),
                    help="the curator's allow file for stations the build DROPPED, whatever refused "
                         "them: one `<survey slug>/<file name>` per line, '#' comments ignored. A drop "
                         "not named there FAILS this run (the build itself still exits 0). Defaults "
                         "to the reviewed in-repo file.")
    ap.add_argument("--data-dir", default=None,
                    help="validate an EXISTING build output dir in place (mtcat.json schema + "
                         "manifest.json integrity/schema) instead of running pytest + a fresh build. "
                         "For a post-build gate over an already-produced builds/<timestamp> dir (see "
                         "deploy/Makefile's rebuild-data). --skip-tests is ignored here; --surveys, if "
                         "given, ARMS the consistency gate, which is NOT ignored.")
    a = ap.parse_args(argv)

    if a.data_dir is not None:
        if a.skip_tests:
            print("note: --data-dir ignores --skip-tests (different mode: validates an existing build "
                  "dir, does not rebuild or run pytest)", file=sys.stderr)
        # --surveys is now MEANINGFUL in --data-dir mode (arms the consistency gate); pass it through.
        surveys_root = Path(a.surveys) if a.surveys is not None else None
        return 0 if _validate_data_dir(Path(a.data_dir), surveys_root,
                                       Path(a.allow_parse_failures),
                                       Path(a.allow_stations_dropped)) else 1

    ok = True
    self_surveys = a.surveys if a.surveys is not None else str(ROOT / "data")
    allow_parse_failures = Path(a.allow_parse_failures)
    allow_stations_dropped = Path(a.allow_stations_dropped)

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
    sm_schema = json.loads((ROOT / "schema" / "ausmt-survey-metadata.schema.json").read_text(encoding="utf-8"))
    st_schema = json.loads((ROOT / "schema" / "ausmt-station.schema.json").read_text(encoding="utf-8"))

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
    pf_ok, pf_lines = _check_source_parse_failures(rep, allow_parse_failures)
    for ln in pf_lines:
        print(ln)
    ok &= pf_ok
    sd_ok, sd_lines = _check_stations_dropped(rep, allow_stations_dropped)
    for ln in sd_lines:
        print(ln)
    ok &= sd_ok
    sm_ok, sm_lines = _check_survey_metadata(out, mtc, rep, jsonschema, sm_schema)
    for ln in sm_lines:
        print(ln)
    ok &= sm_ok
    st_ok, st_lines = _check_station_metadata(out, mtc, jsonschema, st_schema)
    for ln in st_lines:
        print(ln)
    ok &= st_ok

    print("VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
