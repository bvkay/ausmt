"""Runner-side metadata-edit jobs (C31 §1). Runs INSIDE the gw-runner service — the ENGINE image,
network-none — where ruamel.yaml + the real surveys validator live. NEVER in the gateway process
(C31 §0.1, the C10 house rule that the gateway never parses survey content; pinned by the §3.8
source-assertion test AND the subprocess import-hygiene test).

Transport is the C10 file-queue pattern, in its own namespace so the crash-only submission queue is
untouched (adversarial review FIX 1 — the first implementation spawned `sys.executable -m ...` as a
child of the GATEWAY container, whose image deliberately has no ruamel, so every real edit would
have 500'd; tests passed only via an in-process seam):

    jobs/edit/pending/<id>.json   gateway enqueues (tmp+rename, atomic)
    jobs/edit/running/<id>.json   this runner claims via os.replace (the rename IS the lock)
    jobs/edit/done/<id>.json      this runner writes the result (tmp+rename); gateway polls + reads
    jobs/edit/scratch/<id>/       this runner's per-job scratch for validating the patched package

Job files carry a SLUG, never a path: the gateway mounts surveys-live at /srv/surveys-live while
this runner mounts it read-only at /srv/surveys, so an absolute path would not translate across the
containers. The runner resolves the package from its own AUSMT_SURVEYS_ROOT (mirroring the C10 rule
that the runner recomputes paths from its own env and never trusts one handed to it in a job file).

Two job kinds:
  read  — load surveys/<slug>/survey.yaml, return the editable subset as JSON + current version.
  merge — ruamel round-trip load, apply the field patch, enforce the C31 §0.3 semver + no-op rules,
          append the release note, run the REAL validator on a scratch copy of the patched package
          (scratch lives under jobs/edit/scratch/, NEVER under the surveys tree — review FIX 2),
          and return new yaml bytes (base64) + a unified diff + the validator report + the sha256
          the gateway re-hashes at commit time (C31 §0.6).
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

# PyYAML is the reader the DOWNSTREAM pipeline uses (the validator's _load_yaml and the engine's
# build_portal both yaml.safe_load survey.yaml). It decides which patched strings must be quoted
# (review FIX 3): a bare token PyYAML would retype (YAML-1.1 on/off/yes/no booleans, sexagesimal
# ints like 12:34:56, ISO dates) is emitted double-quoted so what the curator confirmed is what the
# pipeline reads. Absent PyYAML (not the case in the engine image), quote everything — conservative.
try:
    import yaml as _pyyaml
except ModuleNotFoundError:  # pragma: no cover -- engine image always ships PyYAML
    _pyyaml = None

logger = logging.getLogger("ausmt.gateway.runner.edit")

# The edit-queue namespace under jobs/. DELIBERATELY disjoint from the C10 submission queue
# (jobs/{pending,running,done}) so the gateway poll loop's done-ingest and dead-job sweep never see
# an edit file and the crash-only submission semantics are untouched.
EDIT_SUBDIR = "edit"

# Same slug charset as gateway.publish._SLUG_RE (kept as a local copy: the check must hold even if
# this module is used standalone in the runner container; a slug is the only untrusted-ish field in
# an edit job and it becomes a path component below).
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# An EDI filename the curator may select for removal must be a bare basename (no path parts, no
# traversal) ending in .edi (case-insensitive). The runner re-validates every selected name against
# this before it becomes a path component — the gateway checked it too, but the runner never trusts
# a field handed to it in a job file (mirrors the slug rule). Deliberately strict: an .edi file with
# an exotic name outside this charset is not removable via the UI (a rename-then-PR is the escape).
_EDI_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.edi$", re.IGNORECASE)

# Where the stations (EDI files) live inside a survey package — the single layout the whole pipeline
# assumes (gateway/runner/intake._station_count globs exactly this; the validator derives its station
# count the same way). There is NO station-list field in survey.yaml: the EDI files ARE the station
# list, so a removal is a git rm of files + a version bump, not a yaml manifest edit.
_EDI_SUBPATH = ("transfer_functions", "edi")

# The editable field set (C31 §2). Scalars, nested maps, and lists the form models; everything else
# in the survey.yaml (slug, coordinate_resolution, geographic_extent, EDI-derived fields, unknown
# keys, comments) is NOT touched by a patch and round-trips byte-for-byte (C31 §0.2/§0.7). `version`
# and `release_notes` are managed by the merge itself (C31 §0.3), not patched directly.
EDITABLE_SCALARS = ("project_name", "name", "region", "abstract", "license")
EDITABLE_MAPS = ("organisation", "identifiers", "collection", "processing", "access",
                 "time_series", "care", "lead_investigator")
EDITABLE_LISTS = ("principal_investigators", "publications", "funding", "instruments")
EDITABLE_KEYS = EDITABLE_SCALARS + EDITABLE_MAPS + EDITABLE_LISTS


class EditError(Exception):
    """A recoverable, curator-facing failure (bad slug, missing file, semver/no-op refusal). The
    message is surfaced verbatim on the gateway preview page (escaped). Distinct from an unexpected
    crash, which is reported as a generic internal error."""


# ---- queue helpers (mirror gateway/runner/runner.py's claim + jobs.py's atomic writes) ----------

def edit_dirs(jobs_dir: Path) -> dict[str, Path]:
    """Ensure + return the edit-queue subdirs. Called by both sides (gateway enqueue / runner claim)
    so whichever starts first creates the tree."""
    root = jobs_dir / EDIT_SUBDIR
    out = {name: root / name for name in ("pending", "running", "done", "scratch")}
    for p in out.values():
        p.mkdir(parents=True, exist_ok=True)
    return out


def claim_edit_job(jobs_dir: Path) -> Path | None:
    """Claim one pending edit job by renaming pending/<id>.json -> running/<id>.json — the atomic
    same-fs rename IS the lock, exactly like runner.claim_one. Sorted glob for deterministic order
    across platforms. Returns the running-file path, or None."""
    dirs = edit_dirs(jobs_dir)
    for src in sorted(dirs["pending"].glob("*.json")):
        dest = dirs["running"] / src.name
        try:
            os.replace(src, dest)
        except OSError:
            continue  # lost the race / vanished
        return dest
    return None


def process_edit_job(cfg, running_file: Path) -> None:
    """Execute one claimed edit job to a done-file. NEVER raises: a handled EditError becomes
    {ok:False, error:<curator-facing>}; an unexpected exception becomes a generic internal error
    (logged here, never leaked verbatim to the page). Edit jobs are request/response — the gateway
    is polling for this result RIGHT NOW — so unlike the C10 submission jobs there is no crash-
    recovery requeue path; a missing result simply times out gateway-side and the curator retries.

    `cfg` is the RunnerConfig: surveys_root locates the package for the job's slug; validator_path
    locates the real validator; jobs_dir hosts the per-job scratch (review FIX 2/FIX 5 — scratch
    NEVER lands under the surveys tree, and each job gets its own dir so concurrent previews cannot
    collide)."""
    job_id = running_file.stem
    dirs = edit_dirs(cfg.jobs_dir)
    try:
        job = json.loads(running_file.read_text(encoding="utf-8"))
        result = _dispatch_edit(cfg, job, dirs["scratch"] / job_id)
    except EditError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- fail closed to a result; the curator sees a retryable error
        logger.exception("edit job %s failed unexpectedly", job_id)
        result = {"ok": False, "error": f"internal error: {type(exc).__name__}"}
    from .. import jobs  # gateway-side atomic tmp+rename writer (shared job protocol)
    jobs._atomic_write_json(dirs["done"] / f"{job_id}.json", result)
    running_file.unlink(missing_ok=True)


def _dispatch_edit(cfg, job: dict, scratch_dir: Path) -> dict:
    slug = str(job.get("slug") or "")
    if not _SLUG_RE.match(slug):
        raise EditError(f"invalid slug in edit job: {slug!r}")
    surveys_root = Path(cfg.surveys_root)
    package_root = (surveys_root / "surveys" / slug).resolve()
    root_resolved = (surveys_root / "surveys").resolve()
    if package_root != root_resolved and root_resolved not in package_root.parents:
        raise EditError("edit job path escapes the surveys tree")
    # Belt-and-braces for review FIX 2: the scratch tree must NEVER resolve under the surveys tree
    # (this runner mounts it read-only, and gateway-side it is the live git checkout a concurrent
    # publish `git add surveys` would stage).
    if surveys_root.resolve() in scratch_dir.resolve().parents:
        raise EditError("scratch dir would land inside the surveys tree — refusing")
    kind = job.get("kind")
    if kind == "read":
        return run_read_job(package_root)
    if kind == "merge":
        return run_merge_job(
            package_root,
            patch=job.get("patch") or {},
            bump=str(job.get("bump") or ""),
            note=str(job.get("note") or ""),
            today=str(job.get("today") or ""),
            validator_path=str(cfg.validator_path or ""),
            scratch_dir=scratch_dir,
        )
    if kind == "list_stations":
        return run_list_stations_job(package_root)
    if kind == "remove_stations":
        return run_remove_stations_job(
            package_root,
            filenames=list(job.get("filenames") or []),
            bump=str(job.get("bump") or ""),
            note=str(job.get("note") or ""),
            today=str(job.get("today") or ""),
            validator_path=str(cfg.validator_path or ""),
            scratch_dir=scratch_dir,
        )
    raise EditError(f"unknown edit-job kind {kind!r}")


# ---- yaml round-trip engine ---------------------------------------------------------------------

def _yaml() -> YAML:
    """The round-trip YAML engine tuned so a well-formed survey.yaml re-emits BYTE-FOR-BYTE (C31
    §0.2). Defaults re-wrap long lines, drop the explicit `null` token, and indent block-sequence
    dashes at column 0 — each a spurious diff. width=2**20 disables line re-wrapping; indent(2,4,2)
    matches the survey template's 2-space dash offset; the None representer re-emits the literal
    `null` the templates and existing surveys write. preserve_quotes keeps quoting styles intact.

    Residual (documented for the adversarial review): intra-node horizontal alignment inside a FLOW
    map (e.g. `{  name: "x",     orcid: "y"}`) is not preserved by any YAML round-tripper — ruamel
    normalises the internal spacing of a flow collection. Block style (the dominant form in the
    templates) round-trips exactly; the merge test uses a well-formed block-style exemplar."""
    y = YAML()
    y.preserve_quotes = True
    y.width = 1 << 20
    y.indent(mapping=2, sequence=4, offset=2)

    class _Repr(RoundTripRepresenter):
        pass

    _Repr.add_representer(
        type(None),
        lambda self, _data: self.represent_scalar("tag:yaml.org,2002:null", "null"))
    y.Representer = _Repr
    return y


def _load_bytes(raw: bytes):
    return _yaml().load(io.BytesIO(raw))


def _dump_bytes(data) -> bytes:
    buf = io.BytesIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


# ---- FIX 3: parser-differential quoting ----------------------------------------------------------

def _needs_quoting(s: str) -> bool:
    """True iff emitting `s` as a bare (plain) scalar would NOT read back as the identical string
    under PyYAML safe_load — the reader the validator and build_portal use. Catches the YAML-1.1
    implicit retypes (on/off/yes/no -> bool, 12:34:56 -> sexagesimal int, 2026-07-06 -> date,
    numerics) plus anything structurally unsafe (empty, leading/trailing space, multiline, '#',
    ': ', ...). Conservative: quote on any doubt."""
    if s == "" or s != s.strip():
        return True
    if _pyyaml is None:  # pragma: no cover -- engine image always ships PyYAML
        return True
    try:
        loaded = _pyyaml.safe_load(s)
    except Exception:  # noqa: BLE001 -- unparseable bare token => must be quoted
        return True
    return not (isinstance(loaded, str) and loaded == s)


def quote_ambiguous(value):
    """Recursively wrap curator-supplied strings that PyYAML would retype in DoubleQuotedScalarString
    so ruamel emits them quoted (review FIX 3, proven failing 2026-07-06: patched `region: on` /
    `name: no` / `abstract: 12:34:56` emitted UNQUOTED; PyYAML safe_load read them back as
    True / False / 45296 while ruamel's own re-read kept them strings — so the diff, the §0.6 sha
    pin, and the confirm re-run all agreed and no guard fired; the portal would have served a
    bool/int the curator never wrote).

    KEYS pass through the same oracle as values (re-review finding, proven failing 2026-07-06: a
    JSON-edited map key 'on'/'no'/'12:34:56' emitted bare and safe_load re-read the KEY as
    True/False/45296 — the identical differential one axis over). No non-str-key rejection path is
    added: the patch arrives via json.loads, whose object keys are ALWAYS str, so a non-str key is
    structurally unreachable through the interface (it would be a programming error in a caller,
    passed through untouched and visible in the diff — not a silent retype)."""
    if isinstance(value, str):
        return DoubleQuotedScalarString(value) if _needs_quoting(value) else value
    if isinstance(value, dict):
        return {quote_ambiguous(k): quote_ambiguous(v) for k, v in value.items()}
    if isinstance(value, list):
        return [quote_ambiguous(v) for v in value]
    return value


# ---- semver (C31 §0.3): a tiny strict MAJOR.MINOR.PATCH comparator, no new dependency ----

def parse_semver(value) -> tuple[int, int, int] | None:
    """Parse a strict MAJOR.MINOR.PATCH into a comparable tuple, or None if it is not exactly three
    dot-separated non-negative integers. Deliberately strict (no pre-release/build metadata): the
    survey-package convention is plain three-part semver (docs/reference/survey-yaml.md)."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(".")
    if len(parts) != 3:
        return None
    out = []
    for p in parts:
        if not p.isdigit():
            return None
        out.append(int(p))
    return (out[0], out[1], out[2])


def semver_greater(new: str, old: str) -> bool:
    """True iff `new` is a valid semver strictly greater than the valid semver `old`. A non-semver on
    either side is False (the merge then refuses — C31 §0.3 requires a semver-greater bump)."""
    n, o = parse_semver(new), parse_semver(old)
    if n is None or o is None:
        return False
    return n > o


def suggest_bump(old: str, kind: str) -> str:
    """The default patch/minor/major suggestion from the current version (C31 §0.3: patch is the
    default suggestion). Falls back to a sane 1.0.1/1.1.0/2.0.0 when the current version is absent or
    non-semver, so the form always has a valid suggestion to prefill."""
    base = parse_semver(old) or (1, 0, 0)
    major, minor, patch = base
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ---- editable-subset extraction (read job) ----

def _plain(node):
    """Recursively convert ruamel round-trip containers to plain dict/list/scalars for JSON. The read
    job returns JSON to the gateway (which must not import yaml), so the CommentedMap/CommentedSeq
    wrappers — which carry the comment/formatting state — are stripped to their data here."""
    if hasattr(node, "items"):
        return {str(k): _plain(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_plain(v) for v in node]
    return node


def editable_subset(data) -> dict:
    """The editable fields present in the document, as plain JSON-able values (C31 §2). Absent fields
    are simply omitted (the form renders them empty); unknown keys are never included."""
    return {k: _plain(data[k]) for k in EDITABLE_KEYS if k in data}


# ---- the field patch (merge job) ----

def apply_patch(data, patch: dict) -> list[str]:
    """Apply the curator's field patch onto the round-trip document IN PLACE, touching only the keys
    in the patch (all of which must be in EDITABLE_KEYS — enforced by the caller). Returns the list
    of top-level keys whose value actually changed. Setting a key to None/"" that was absent is a
    no-op (we do not introduce empty keys the source never had); clearing an existing key sets it to
    None (which re-emits as `null`). Assigned strings pass through quote_ambiguous (FIX 3) so a
    YAML-1.1-retypeable token is emitted quoted."""
    changed = []
    for key, new_val in patch.items():
        had = key in data
        old_val = data.get(key) if had else None
        # Compare on plain values so a CommentedMap old vs plain-dict new compares by data, not identity.
        if _plain(old_val) == new_val:
            continue
        if not had and new_val in (None, "", [], {}):
            continue  # never introduce an empty key the source did not carry
        data[key] = quote_ambiguous(new_val)
        changed.append(key)
    return changed


def append_release_note(data, version: str, date: str, note: str) -> None:
    """Set the top-level `version` and append a {version, date, note} entry to release_notes (C31
    §0.3 — every content edit records one). Creates the release_notes list if the survey had none.
    The entry's strings pass through quote_ambiguous too: the date is exactly the ISO shape PyYAML
    retypes to datetime.date, and the note is curator free text."""
    data["version"] = quote_ambiguous(version)
    rn = data.get("release_notes")
    if not isinstance(rn, list):
        rn = []
        data["release_notes"] = rn
    rn.append({"version": quote_ambiguous(version), "date": quote_ambiguous(date),
               "note": quote_ambiguous(note)})


# ---- validator ------------------------------------------------------------------------------------

def _run_validator(validator_path: str, package_root: Path) -> dict:
    """Run the REAL surveys validator (validate_survey.py --json <file>) over the patched package and
    return its parsed report. The validator writes the machine-readable {counts, items, manifest}
    JSON to the --json FILE (its stdout carries only human `[LEVEL] check msg` lines), so the report
    is read from that file — the authoritative artefact. The report file lives beside the SCRATCH
    copy (never the live tree). Fail-closed: a non-JSON / crashing validator yields a synthetic FAIL
    item so the merge is treated as validator-FAIL (C31 §0.4)."""
    # M7 (code-health review §6): reuse the C10 runner's locator AND the ONE canonical argv builder,
    # so this edit-runner and the submission runner invoke the validator identically. This call site
    # previously assembled the flags --json-first (`--json <file> <folder>`); it now goes through
    # validator_argv (positional-first) — the single form the real-vendored-validator oracles pin.
    from .runner import _validator_file, validator_argv

    vfile = _validator_file(validator_path)
    report_file = package_root.parent / "_edit_validate.json"
    subprocess.run(  # noqa: PLW1510 -- the report file is the authoritative signal, not returncode
        validator_argv(vfile, package_root, report_file),
        capture_output=True, text=True, timeout=300,
    )
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {"items": [{"level": "FAIL", "check": "validator",
                             "message": "validator produced no readable JSON report"}]}
    finally:
        report_file.unlink(missing_ok=True)
    if not isinstance(report, dict):
        report = {"items": [{"level": "FAIL", "check": "validator",
                             "message": "validator report was not an object"}]}
    return report


def report_has_fail(report: dict) -> bool:
    """True iff the validator report carries any FAIL/ERROR item (C31 §0.4 — WARNINGs do not block).
    Mirrors runner._validator_passed's item interpretation, inverted."""
    items = report.get("items") if isinstance(report, dict) else None
    if not isinstance(items, list):
        return True  # an unreadable report is fail-closed
    for it in items:
        if isinstance(it, dict):
            level = str(it.get("level") or it.get("status") or "").upper()
            if level in ("FAIL", "ERROR"):
                return True
    return False


# ---- job bodies ----

def run_read_job(package_root: Path) -> dict:
    """Handle a `read` edit-job: load the survey.yaml and return the editable subset + version."""
    survey_yaml = package_root / "survey.yaml"
    if not survey_yaml.is_file():
        raise EditError(f"survey.yaml not found under {package_root.name}")
    data = _load_bytes(survey_yaml.read_bytes())
    if not hasattr(data, "get"):
        raise EditError("survey.yaml is not a mapping")
    version = data.get("version")
    return {
        "ok": True,
        "fields": editable_subset(data),
        "version": version if isinstance(version, str) else None,
    }


def run_merge_job(package_root: Path, *, patch: dict, bump: str, note: str, today: str,
                  validator_path: str, scratch_dir: Path) -> dict:
    """Handle a `merge` edit-job (C31 §1.3): round-trip load → apply patch → semver + no-op checks →
    append release note → emit new bytes + unified diff → run the real validator on a SCRATCH copy of
    the patched package (under scratch_dir — never the live tree, review FIX 2). Returns
    {ok, changed, diff, new_yaml, new_yaml_b64, new_sha256, validator, has_fail, new_version} or
    raises EditError.

    The version is resolved from the bump KIND (patch/minor/major) against the loaded current
    version — the runner alone owns version logic (C31 §0.3); the dead explicit-version override was
    removed per review FIX 6."""
    survey_yaml = package_root / "survey.yaml"
    if not survey_yaml.is_file():
        raise EditError(f"survey.yaml not found under {package_root.name}")
    original_bytes = survey_yaml.read_bytes()
    data = _load_bytes(original_bytes)
    if not hasattr(data, "get"):
        raise EditError("survey.yaml is not a mapping")

    unknown = [k for k in patch if k not in EDITABLE_KEYS]
    if unknown:
        raise EditError(f"patch contains non-editable field(s): {', '.join(sorted(unknown))}")

    old_version = data.get("version")
    changed = apply_patch(data, patch)
    if not changed:
        raise EditError("no changes — the submitted values match the current survey.yaml")

    old_v_str = old_version if isinstance(old_version, str) else "0.0.0"
    if bump not in ("patch", "minor", "major"):
        raise EditError("no version bump selected")
    new_version = suggest_bump(old_v_str, bump)
    if not semver_greater(new_version, old_v_str):
        # Reachable when the CURRENT version is not strict semver (suggest_bump then falls back to
        # 1.0.x, which cannot be compared against the non-semver current). Fail closed: fix the
        # version through the normal PR path first, then the editor works.
        raise EditError(
            f"cannot bump: current version {old_v_str!r} is not MAJOR.MINOR.PATCH semver — "
            f"fix it via a PR first (a content edit requires a semver-greater bump, C31 §0.3)")

    note = note.strip()
    if not note:
        raise EditError("a release note is required for a metadata edit")
    append_release_note(data, new_version, today, note)

    new_bytes = _dump_bytes(data)
    diff = "".join(difflib.unified_diff(
        original_bytes.decode("utf-8", "replace").splitlines(keepends=True),
        new_bytes.decode("utf-8", "replace").splitlines(keepends=True),
        fromfile=f"a/{survey_yaml.name}", tofile=f"b/{survey_yaml.name}"))

    report = _validate_patched(package_root, new_bytes, validator_path, scratch_dir)

    return {
        "ok": True,
        "changed": changed,
        "diff": diff,
        # A DISPLAY string (lossy decode is fine — it is only rendered, never committed) AND the exact
        # bytes base64-encoded (the artifact that is actually written + hashed at commit time, so a
        # non-UTF8 byte can never be silently mangled through a decode/encode round trip).
        "new_yaml": new_bytes.decode("utf-8", "replace"),
        "new_yaml_b64": base64.b64encode(new_bytes).decode("ascii"),
        "new_sha256": hashlib.sha256(new_bytes).hexdigest(),
        "validator": report,
        "has_fail": report_has_fail(report),
        "new_version": new_version,
    }


def _validate_patched(package_root: Path, new_bytes: bytes, validator_path: str,
                      scratch_dir: Path) -> dict:
    """Copy the package into the per-job scratch dir, drop in the patched survey.yaml, and run the
    real validator on the copy so an EDI-referencing check still sees a complete package. The scratch
    lives under jobs/edit/scratch/<job-id>/ — NEVER under the surveys tree (review FIX 2, proven
    failing 2026-07-06: the first implementation wrote _edit_patched/ + _edit_validate.json under
    surveys-live/surveys/, where a concurrent publish's `git add surveys` would stage them into the
    publication ledger and a leaked scratch would make every later publish preflight refuse; it
    would also have failed outright in production against this runner's READ-ONLY /srv/surveys
    mount). Per-job dir = no collision between concurrent previews (review FIX 5). Returns the
    validator report; an unconfigured validator path yields an empty (non-failing) report so unit
    tests without a real validator still exercise the merge path."""
    if not validator_path:
        return {"items": []}
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir)
    dest = scratch_dir / package_root.name
    shutil.copytree(package_root, dest)
    (dest / "survey.yaml").write_bytes(new_bytes)
    try:
        return _run_validator(validator_path, dest)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


# ---- station (EDI) listing + removal --------------------------------------------------------------

def list_edi_files(package_root: Path) -> list[Path]:
    """Every .edi file directly under <package>/transfer_functions/edi/, sorted by name for a
    deterministic order across platforms (the same CI OS-portability concern as list_published_slugs).
    A glob, not a parse — the station list is the files themselves. A missing edi/ dir yields []."""
    edi_dir = package_root
    for part in _EDI_SUBPATH:
        edi_dir = edi_dir / part
    if not edi_dir.is_dir():
        return []
    return sorted((p for p in edi_dir.iterdir()
                   if p.is_file() and p.suffix.lower() == ".edi"),
                  key=lambda p: p.name)


def _station_id(filename: str) -> str:
    """The station id derived from an EDI filename: the stem (name without the .edi suffix). This is
    a DISPLAY convenience (intake/build_portal derive the authoritative catalogue id from the file
    contents); the filename stem is the cheap, honest label the curator recognises."""
    return Path(filename).stem


def run_list_stations_job(package_root: Path) -> dict:
    """Handle a `list_stations` edit-job: enumerate the survey's EDI files with their derived station
    ids + the current version. A directory listing, never a content parse (mirrors the read job's
    discipline)."""
    survey_yaml = package_root / "survey.yaml"
    if not survey_yaml.is_file():
        raise EditError(f"survey.yaml not found under {package_root.name}")
    stations = [{"filename": p.name, "station_id": _station_id(p.name)}
                for p in list_edi_files(package_root)]
    data = _load_bytes(survey_yaml.read_bytes())
    version = data.get("version") if hasattr(data, "get") else None
    return {
        "ok": True,
        "stations": stations,
        "version": version if isinstance(version, str) else None,
    }


def run_remove_stations_job(package_root: Path, *, filenames: list[str], bump: str, note: str,
                            today: str, validator_path: str, scratch_dir: Path) -> dict:
    """Handle a `remove_stations` edit-job: refuse the unsafe removals (empty selection, all-stations,
    a vanished/invalid file), bump the version (a content change requires a semver-greater bump), append
    the release note, emit the new survey.yaml bytes + diff, and run the REAL validator over a SCRATCH
    copy of the package MINUS the removed EDIs (so a station-set-sensitive check sees the post-removal
    reality — this reuses the merge scratch machinery, it is NOT a second validation path). Returns
    {ok, removed, station_count_before, station_count_after, diff, new_yaml(+_b64), new_sha256,
    validator, has_fail, new_version} or raises EditError.

    survey.yaml carries NO station-list field, so the yaml diff is only version + release_notes; the
    EDI deletions are a git op the gateway performs at commit time (reported to the curator separately
    via `removed`)."""
    survey_yaml = package_root / "survey.yaml"
    if not survey_yaml.is_file():
        raise EditError(f"survey.yaml not found under {package_root.name}")

    present = [p.name for p in list_edi_files(package_root)]
    present_set = set(present)
    before = len(present)

    # Normalise + validate the selection. Dedupe while preserving the on-disk order so the reported
    # `removed` list is stable and the count is honest.
    requested = []
    for raw in filenames:
        name = str(raw).strip()
        if not name:
            continue
        if not _EDI_NAME_RE.match(name):
            raise EditError(f"not a valid EDI filename: {name!r}")
        if name not in requested:
            requested.append(name)
    if not requested:
        raise EditError("no stations selected for removal")

    # Stale-form guard: a selected file that vanished since the form rendered => refuse the WHOLE
    # removal (never a half-removal). Report every missing name so the curator can re-open once.
    missing = [n for n in requested if n not in present_set]
    if missing:
        raise EditError(
            "these selected files no longer exist in the survey (re-open the stations page): "
            + ", ".join(sorted(missing)))

    # Safety rail: at least one station must remain. Removing every EDI is deleting the survey — a
    # different operation with a different (deliberately separate) blast radius.
    remaining = before - len(requested)
    if remaining < 1:
        raise EditError(
            "refusing to remove ALL stations — at least one EDI must remain "
            "(deleting an entire survey is a separate operation)")

    note = note.strip()
    if not note:
        raise EditError("a release note is required for a station removal")

    # Version bump (a removal is a content change; the caller defaults to at least minor). The runner
    # alone owns version logic (C31 §0.3) — resolve the kind against the current version, enforce
    # semver-greater. Order removals deterministically for the release note / diff.
    removed = sorted(requested)
    data = _load_bytes(survey_yaml.read_bytes())
    if not hasattr(data, "get"):
        raise EditError("survey.yaml is not a mapping")
    original_bytes = survey_yaml.read_bytes()
    old_version = data.get("version")
    old_v_str = old_version if isinstance(old_version, str) else "0.0.0"
    if bump not in ("patch", "minor", "major"):
        raise EditError("no version bump selected")
    new_version = suggest_bump(old_v_str, bump)
    if not semver_greater(new_version, old_v_str):
        raise EditError(
            f"cannot bump: current version {old_v_str!r} is not MAJOR.MINOR.PATCH semver — "
            f"fix it via a PR first (a content edit requires a semver-greater bump, C31 §0.3)")
    append_release_note(data, new_version, today, note)

    new_bytes = _dump_bytes(data)
    diff = "".join(difflib.unified_diff(
        original_bytes.decode("utf-8", "replace").splitlines(keepends=True),
        new_bytes.decode("utf-8", "replace").splitlines(keepends=True),
        fromfile=f"a/{survey_yaml.name}", tofile=f"b/{survey_yaml.name}"))

    report = _validate_removed(package_root, new_bytes, removed, validator_path, scratch_dir)

    return {
        "ok": True,
        "removed": removed,
        "station_count_before": before,
        "station_count_after": remaining,
        "diff": diff,
        "new_yaml": new_bytes.decode("utf-8", "replace"),
        "new_yaml_b64": base64.b64encode(new_bytes).decode("ascii"),
        "new_sha256": hashlib.sha256(new_bytes).hexdigest(),
        "validator": report,
        "has_fail": report_has_fail(report),
        "new_version": new_version,
    }


def _validate_removed(package_root: Path, new_bytes: bytes, removed: list[str], validator_path: str,
                      scratch_dir: Path) -> dict:
    """Copy the package into the per-job scratch dir, DELETE the removed EDIs from the copy, drop in
    the patched survey.yaml, and run the real validator on the result — so the validator sees exactly
    the post-removal package (review FIX 2: scratch NEVER under the surveys tree, per-job dir for no
    collision). Mirrors _validate_patched; an unconfigured validator path yields an empty (non-failing)
    report so unit tests without a real validator still exercise the removal path."""
    if not validator_path:
        return {"items": []}
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir)
    dest = scratch_dir / package_root.name
    shutil.copytree(package_root, dest)
    edi_dir = dest
    for part in _EDI_SUBPATH:
        edi_dir = edi_dir / part
    for name in removed:
        (edi_dir / name).unlink(missing_ok=True)
    (dest / "survey.yaml").write_bytes(new_bytes)
    try:
        return _run_validator(validator_path, dest)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
