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

from ruamel.yaml import YAML, YAMLError
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
    # Whole-corpus read-only jobs carry NO slug — dispatch them BEFORE the per-survey slug validation
    # (which would reject the empty slug). The collections projection enumerates surveys-live from the
    # runner's own mount, reads each `collection` block, and mutates nothing (history-job trust class).
    if job.get("kind") == "collections":
        return run_collections_job(Path(cfg.surveys_root))
    # C43 Stage 3b (record D5-A A6): the atomic collection batch. Whole-corpus too (it names its own
    # affected slugs in the operations list), so it dispatches here before the single-slug gate. The
    # runner is the ONLY place survey.yaml is parsed/patched/emitted (C31 §0.1); this computes each
    # affected member's patched bytes + validator report — the gateway commits them (publish.py).
    if job.get("kind") == "collection_batch":
        return run_collection_batch_job(
            Path(cfg.surveys_root),
            operations=list(job.get("operations") or []),
            note=str(job.get("note") or ""),
            today=str(job.get("today") or ""),
            validator_path=str(cfg.validator_path or ""),
            scratch_dir=scratch_dir)
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
    if kind == "history":
        return run_history_job(package_root, surveys_root=surveys_root)
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
    YAML-1.1-retypeable token is emitted quoted.

    [FC-4] DIFF-MINIMAL MAP MERGE (C43 Stage 1): when the OLD value is a round-trip mapping and the
    NEW value is a dict, the two are merged SURGICALLY into the existing node (_merge_map_into) —
    only the sub-keys whose leaf value actually changed are reassigned, so every UNCHANGED sub-key
    keeps its original comment, quoting, and position and produces NO diff line. The previous
    behaviour replaced the whole CommentedMap with a plain dict rebuilt from JSON, which stripped
    intra-section comments and re-emitted every sibling line (proven failing 2026-07-10 — a single
    organisation.ror edit rewrote the untouched organisation.name line and dropped its comment). This
    makes the editor emit like the station-removal path already does: the removal only ever appends a
    release note, touching nothing it did not change. Scalars and LISTS still replace wholesale (a
    list has no stable per-element identity to merge against; a list edit re-emitting its own block is
    acceptable and matches the pre-C43 contract)."""
    changed = []
    for key, new_val in patch.items():
        had = key in data
        old_val = data.get(key) if had else None
        # Compare on plain values so a CommentedMap old vs plain-dict new compares by data, not identity.
        if _plain(old_val) == new_val:
            continue
        if not had and new_val in (None, "", [], {}):
            continue  # never introduce an empty key the source did not carry
        if had and hasattr(old_val, "items") and isinstance(new_val, dict):
            # Surgical in-place map merge: mutate the existing round-trip node, preserving the
            # comments/quoting/order of every sub-key the curator left alone.
            if _merge_map_into(old_val, new_val):
                changed.append(key)
            continue
        data[key] = quote_ambiguous(new_val)
        changed.append(key)
    return changed


def _merge_map_into(node, new_map: dict) -> bool:
    """Merge `new_map` (a plain dict from the JSON patch) INTO the ruamel round-trip mapping `node`
    IN PLACE, touching only what actually differs. Returns True iff any sub-key changed.

      * a sub-key present in both: recurse if both sides are maps (preserve nested comments); else
        reassign only when the plain values differ (an unchanged leaf is left untouched, so its
        comment/quoting/position survive and it emits no diff line);
      * a sub-key only in new_map: added (quoted per FIX 3);
      * a sub-key only in node: DELETED (the curator's assembled section no longer carries it — the
        editor's _assemble_map already models "cleared" as an explicit None rather than a drop, so a
        real deletion here is an intentional removal, e.g. via the advanced-JSON override).

    Only VALUES flow through quote_ambiguous on (re)assignment; existing untouched values are never
    re-wrapped, so a bare token the source already carried keeps its exact on-disk form."""
    changed = False
    for subkey, new_val in new_map.items():
        if subkey in node:
            old_val = node[subkey]
            if hasattr(old_val, "items") and isinstance(new_val, dict):
                if _merge_map_into(old_val, new_val):
                    changed = True
                continue
            if _plain(old_val) == new_val:
                continue  # unchanged leaf — leave the node (and its comment) exactly as-is
            node[subkey] = quote_ambiguous(new_val)
            changed = True
        else:
            node[subkey] = quote_ambiguous(new_val)
            changed = True
    # ACCEPTED RESIDUAL (review F4): `del node[subkey]` removes the key's line and its INLINE trailing
    # comment cleanly, but a STANDALONE leading comment line above the deleted key is ORPHANED onto the
    # following key — ruamel attaches a leading comment to the node that FOLLOWS it, so deleting the
    # node leaves that comment bound to its successor. Deleting a sub-key via the advanced-JSON path is
    # rare, and the orphaned comment is a cosmetic drift in the surrounding lines, not a data change,
    # so it is left as-is. If it ever matters, the fix is a node.ca.items sweep: before deleting
    # `subkey`, move (or drop) any pre-key comment tokens off the deleted node rather than letting
    # ruamel re-home them on the next key.
    for subkey in [k for k in node if k not in new_map]:
        del node[subkey]
        changed = True
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


# ---- history (read-only git log) job -------------------------------------------------------------
# The runner OWNS the git read for the History tab (record D4 — the gateway process issues NO git verb
# for this beyond what already exists; the runner already mounts surveys-live read-only for the
# validator). The ONLY git verb this job runs is the READ-ONLY `log` — a pin asserts the argv carries
# no mutating verb. Ownership: surveys-live is operator-owned while the runner is uid 10002, so git
# would refuse with "dubious ownership"; we clear it with the INLINE `-c safe.directory=<root>` flag
# (a command-scoped config, NO compose/deploy change, NO persistent config write) rather than a new
# env mount. network_mode:none is irrelevant — `git log` is local.

# A NUL byte terminates each commit record and a Unit-Separator (0x1f) separates the fields inside it,
# so a multi-line release-note body can never be confused with a field/record boundary (neither byte
# can appear in git field output). Fields: full sha, short sha, author name, ISO author date, subject.
_HISTORY_FMT = "%H\x1f%h\x1f%an\x1f%ad\x1f%s\x1e%b\x1f"
_HISTORY_RECORD_SEP = "\x1e"   # between the header-fields chunk and the body, then NUL ends the record

# Only READ-ONLY git verbs may ever appear in a history-job argv. `log` is the whole surface; the
# allowlist exists so a pin (and a future maintainer) can assert no mutating verb leaked in.
_HISTORY_READONLY_VERBS = frozenset({"log"})

# Cap the number of commits returned so a survey with a very long history cannot make the page or the
# job output unbounded. Newest-first, so the cap keeps the most recent releases.
_HISTORY_MAX = 200


def _history_argv(package_root: Path, surveys_root: Path) -> list[str]:
    """The ONE canonical argv for the read-only survey history log. Built here so a pin can assert its
    shape (read-only verb + safe.directory + pathspec). `-C package_root` runs git in the package dir;
    `-- .` limits the log to commits that touched THIS survey's package (its survey.yaml + EDIs), which
    is exactly the per-survey audit trail the History tab shows. `%x00` terminates records."""
    safe_dir = str(surveys_root.resolve())
    return [
        "git",
        "-c", f"safe.directory={safe_dir}",
        "-C", str(package_root),
        "log",
        f"--max-count={_HISTORY_MAX}",
        f"--pretty=format:{_HISTORY_FMT}%x00",
        "--date=iso-strict",
        "--", ".",
    ]


def _parse_history(stdout: str) -> list[dict]:
    """Parse the NUL-delimited git-log output into a list of {sha, short, author, date, subject, body}.
    Records are NUL-separated; within a record the header fields are 0x1f-separated and the body is
    after a 0x1e marker. Robust to a trailing empty record (git appends no final NUL for the last
    line's %x00 in some versions — an empty/blank record is skipped)."""
    out: list[dict] = []
    for raw_rec in stdout.split("\x00"):
        rec = raw_rec.strip("\n")
        if not rec.strip():
            continue
        header, _, body = rec.partition(_HISTORY_RECORD_SEP)
        parts = header.split("\x1f")
        if len(parts) < 5:
            continue
        sha, short, author, date, subject = parts[0], parts[1], parts[2], parts[3], parts[4]
        out.append({
            "sha": sha, "short": short, "author": author, "date": date,
            "subject": subject, "body": body.strip("\x1f").strip("\n"),
        })
    return out


def run_history_job(package_root: Path, *, surveys_root: Path) -> dict:
    """Handle a `history` edit-job: the READ-ONLY git log of the survey's package directory (version,
    release note, when, author) for the History tab. Runs `git log` via a subprocess with the inline
    safe.directory flag; returns {ok, commits:[...]} or {ok:False, error} on a git failure (a survey
    whose package is not under git, or a git error, degrades to a curator-facing message — never a
    crash). The argv carries ONLY the read-only `log` verb (asserted by a pin)."""
    survey_yaml = package_root / "survey.yaml"
    if not survey_yaml.is_file():
        raise EditError(f"survey.yaml not found under {package_root.name}")
    argv = _history_argv(package_root, surveys_root)
    # Defence in depth: this must never carry a mutating verb. The verb is argv[argv.index('log')-agnostic]
    # — find the first bare token after the options that is a git subcommand. Simpler: assert 'log' is
    # present and no known-mutating verb is.
    verb = _history_subcommand(argv)
    if verb not in _HISTORY_READONLY_VERBS:
        raise EditError(f"history job refused: non-read-only git verb {verb!r}")
    try:
        proc = subprocess.run(  # noqa: PLW1510 -- returncode inspected below
            argv, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EditError(f"could not read survey history: {type(exc).__name__}") from exc
    if proc.returncode != 0:
        # Not a git checkout, or git error — surface a clean message, not a crash. stderr is bounded.
        detail = (proc.stderr or "git log failed").strip().splitlines()
        raise EditError("could not read survey history: "
                        + (detail[0][:200] if detail else "git log failed"))
    return {"ok": True, "commits": _parse_history(proc.stdout)}


def _history_subcommand(argv: list[str]) -> str | None:
    """The git SUBCOMMAND (verb) in a history argv: the first token after argv[0]=='git' that is not an
    option (`-x`) and is not the value consumed by `-c`/`-C` (which take a following argument). Used by
    run_history_job's read-only assertion and by the history read-only pin."""
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in ("-c", "-C"):
            i += 2   # skip the flag AND its value
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok   # first bare token = the subcommand/verb
    return None


# ---- collections (whole-corpus read-only projection) job ----------------------------------------
# The C43 Stage-3a collections console (record D5-A) reads EVERY published survey.yaml's `collection`
# block and rolls them up EXACTLY as the engine's build_portal._group_collections does — the SAME
# grouping the portal shows readers — plus the two honesty seams the build only prints to stderr
# today: id near-duplicates and per-field divergence. The grouping/first-declarer/near-dup logic is
# re-implemented LIGHTLY here (the runner must NOT import the heavy build_portal module — it pulls the
# whole mt_metadata extractor stack); correctness is guaranteed by the parity pins in
# gateway/tests/test_collections_runner.py, which assert this output equals _group_collections' on a
# real fixture tree. READ-ONLY: no git verb, no file mutation — the history-job trust class.

# The programme-level fields the rollup carries, in the engine's field order (build_portal.py:396).
_COLLECTION_ROLLUP_FIELDS = ("title", "type", "start_year", "status", "last_updated", "description")
# F2 (D5-C): the fields whose per-member DIVERGENCE the console reports + offers Normalise for.
# EXCLUDES `last_updated`: it is a GATEWAY-MANAGED per-member timestamp (stamped on only the changed
# members in a diff-minimal batch), NOT a curator-reconcilable programme field — including it would
# make the console permanently report "members disagree on last_updated" with a Normalise remedy that
# has no form field to fix it. It stays in _COLLECTION_ROLLUP_FIELDS for engine-rollup parity only.
_COLLECTION_DIVERGENCE_FIELDS = tuple(f for f in _COLLECTION_ROLLUP_FIELDS if f != "last_updated")
# The status vocabulary the engine surfaces (build_portal.py:386). An out-of-vocab rolled-up status is
# DROPPED (build_portal.py:399-400) — never surfaced as a fake status; it still shows as the member's
# raw declared value (and as divergence when members disagree).
_COLLECTION_STATUS_VOCAB = frozenset({"active", "completed", "archived"})


def _json_scalar(v):
    """Coerce a YAML-loaded scalar to a JSON-serialisable value: str/int/float/bool/None pass through;
    anything else (a ruamel date/timestamp — e.g. an unquoted `last_updated: 2026-06-15`) becomes its
    str(). The done-file writer (jobs._atomic_write_json) uses a plain json.dump with no default=, so a
    date object would raise; this keeps the whole result JSON-safe (matching how the engine's
    collections.json stringifies the same date)."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _published_slugs(surveys_root: Path) -> list[str]:
    """The published survey slugs: immediate child dirs of surveys-live/surveys/ holding a survey.yaml,
    SORTED (deterministic + platform-portable — the CI OS-portability concern). Mirrors
    metaedit.list_published_slugs AND the engine build loop's `sorted(iterdir())` order, skipping
    `_`-prefixed scratch dirs exactly as the build does (build_portal.py:1941-1942) — so the runner's
    first-declarer resolves in the SAME order as the portal's rollup."""
    root = surveys_root / "surveys"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith("_") and (p / "survey.yaml").is_file())


def _declared_collection_block(coll) -> dict:
    """A member's raw declared collection block as JSON-safe scalars (dates -> str). The id + the six
    programme fields are surfaced; a member may omit any (an absent field reads as None), so the
    console can compare per-field across members honestly (the Declares column / divergence bands)."""
    out = {"id": _json_scalar(coll.get("id")) if hasattr(coll, "get") else None}
    for k in _COLLECTION_ROLLUP_FIELDS:
        out[k] = _json_scalar(coll.get(k)) if hasattr(coll, "get") else None
    return out


def _collection_divergence(members: list) -> dict:
    """Per-field divergence within one collection id: for each programme field, bucket the members that
    DECLARE a non-empty value by that value; a field with >1 distinct declared value is a divergence
    (members silently disagree — the rollup takes whichever builds first). Returns
    {field: [{value, members:[slug,...]}, ...]} listing every distinct declared value in first-seen
    order; EMPTY {} when every field agrees. A member that omits a field is not an outlier (it inherits
    the rollup value), so only DECLARED values count."""
    out: dict = {}
    for fld in _COLLECTION_DIVERGENCE_FIELDS:   # F2: last_updated excluded (gateway-managed timestamp)
        buckets: dict = {}
        order: list = []
        for m in members:
            v = m["declared"].get(fld)
            if v in (None, ""):
                continue
            key = json.dumps(v, sort_keys=True, default=str)   # a stable hashable key for any scalar
            if key not in buckets:
                buckets[key] = {"value": v, "members": []}
                order.append(key)
            buckets[key]["members"].append(m["slug"])
        if len(buckets) > 1:
            out[fld] = [buckets[k] for k in order]
    return out


def _near_duplicate_ids(ids: list) -> list:
    """Collection ids differing ONLY by case/surrounding whitespace — a typo that splits one programme
    into separate collections (grouping is an EXACT id match). A light re-implementation of the engine's
    build_portal._near_duplicate_collection_ids (pinned to parity): returns each colliding group as a
    sorted list of >1 ids. Today this dies on build stderr; Stage 3a surfaces it on the index band."""
    seen: dict = {}
    for cid in ids:
        seen.setdefault(str(cid).strip().lower(), []).append(cid)
    return [sorted(g) for g in seen.values() if len(g) > 1]


def run_collections_job(surveys_root: Path) -> dict:
    """Handle a `collections` edit-job (record D5-A / Stage 3a): the whole-corpus read-only projection.
    Enumerate published surveys, read each `collection` block via the runner's YAML loader, group by
    exact `collection.id` with the engine's FIRST-DECLARER rollup, count stations per member from the
    EDI files (a directory listing — the list_stations discipline), and surface id near-duplicates +
    per-field divergence. Returns {ok, collections:{id:{...}}, near_duplicates:[[id,...],...]}. An empty
    corpus (or a surveys tree with no collection blocks) returns {collections:{}, near_duplicates:[]}
    — the clean 'no collections yet' state, never an error. READ-ONLY: reads only; mutates nothing."""
    rollup: dict = {}          # id -> first-declarer rollup field dict
    members_by_id: dict = {}   # id -> [member dict] (in slug order)
    order: list = []           # ids in first-seen (sorted-slug) order — matches the engine's order
    all_surveys: list = []     # A6 candidate list: EVERY published survey + its current membership
    for slug in _published_slugs(surveys_root):
        pkg = surveys_root / "surveys" / slug
        # F3 (D5-B): a malformed survey.yaml (ruamel YAMLError) or a non-mapping top-level must drop
        # THIS survey and keep projecting the rest — mirroring build_portal.py:810-817, which warns and
        # drops the one bad package. Catching only OSError before would have let one bad file blank the
        # WHOLE console ({ok:False} -> the gateway's empty state).
        try:
            data = _load_bytes((pkg / "survey.yaml").read_bytes())
        except (OSError, YAMLError):
            continue
        if not hasattr(data, "get"):
            continue  # empty file / list / scalar top-level — not a survey mapping; drop just this one
        name = data.get("name")
        label = str(name) if name not in (None, "") else slug
        n_stations = len(list_edi_files(pkg))
        coll = data.get("collection")
        # F2 (D5-B): membership predicate = the engine's truthiness (build_portal.py:389 `if c and
        # c.get("id")`), so a falsy id (0/False/"") drops exactly as the engine drops it.
        has_membership = bool(hasattr(coll, "get") and coll.get("id"))
        current_cid = str(coll.get("id")) if has_membership else None
        # A6 candidate list (Stage 3b add-picker): every published survey, with its CURRENT membership
        # so the picker can show `no collection` vs `in "<id>" -> moves`. Membership by SLUG (never the
        # rollup's display labels). Read-only; same trust class as the rollup below.
        all_surveys.append({"slug": slug, "label": label, "n_stations": n_stations,
                            "current_collection_id": current_cid})
        if not has_membership:
            continue  # contributes to the candidate list above, but to no collection rollup
        cid = current_cid
        declared = _declared_collection_block(coll)
        if cid not in rollup:
            order.append(cid)
            members_by_id[cid] = []
            # setdefault-equivalent of build_portal.py:391-394: title defaults to id, type from the
            # first member; the other programme fields start empty and fill first-declarer below.
            rollup[cid] = {"title": declared["title"] or cid, "type": declared["type"],
                           "start_year": None, "status": None, "last_updated": None,
                           "description": None}
        e = rollup[cid]
        # first-declarer fill (build_portal.py:396-398): an empty rollup field takes this member's
        # declared value; a later member never overrides a field already set (silent divergence).
        for fld in _COLLECTION_ROLLUP_FIELDS:
            if e.get(fld) in (None, "") and declared.get(fld) not in (None, ""):
                e[fld] = declared.get(fld)
        # F1 (D5-B): drop an out-of-vocab status INSIDE the per-member fold (build_portal.py:399-400),
        # not once at the end — nulling an invalid status here re-opens the slot so a LATER member's
        # VALID status fills it (invalid-first + valid-later => the valid status, matching the engine).
        if e["status"] and e["status"] not in _COLLECTION_STATUS_VOCAB:
            e["status"] = None
        members_by_id[cid].append({"slug": slug, "label": label, "n_stations": n_stations,
                                   "declared": declared})
    collections: dict = {}
    for cid in order:
        e = rollup[cid]
        members = members_by_id[cid]
        collections[cid] = {
            "id": cid,
            "title": e["title"], "type": e["type"], "status": e["status"],
            "start_year": e["start_year"], "last_updated": e["last_updated"],
            "description": e["description"],
            "n_surveys": len(members),
            "n_stations": sum(m["n_stations"] for m in members),
            "members": members,
            "divergence": _collection_divergence(members),
        }
    return {"ok": True, "collections": collections,
            "near_duplicates": _near_duplicate_ids(order), "surveys": all_surveys}


# ---- collection batch (atomic multi-survey collection-block write) job ---------------------------
# C43 Stage 3b (record D5-A A6). The gateway resolves the desired end-state (collection fields + the
# final member set) into a list of per-survey OPERATIONS and hands them here; the runner — the ONLY
# YAML parser (C31 §0.1) — applies each survey's `collection`-block patch, bumps its version (patch),
# appends the ONE shared release note, and validates the patched package on a scratch copy. It returns
# each affected survey's patched bytes + validator report; the gateway's publish.commit_collection_batch
# does the atomic N-commit git write (validate-all-then-commit-all). This computes; it does NOT commit.

# The programme fields (besides id) the collection editor sets; kept in the engine's field order.
_COLLECTION_EDIT_FIELDS = ("title", "type", "start_year", "status", "description")


def _apply_collection_set(data, block: dict, today: str) -> bool:
    """Set the desired collection fields into a member's `collection` block IN PLACE, surgically — only
    fields the desired block DECLARES (non-empty), and only when the value actually differs (an
    unchanged field keeps its exact on-disk form, so it produces NO diff line — diff-minimality). A
    survey that had NO block gets one created (an add/move). Returns True iff anything changed.

    `last_updated` is a PASSENGER: stamped to `today` only when another field actually changed, so an
    already-canonical member is left byte-for-byte untouched (no spurious commit). An EMPTY desired
    field means 'leave the member's own value as-is', NEVER 'clear it' — clearing a programme field
    stays a per-survey metadata edit (the editor never deletes a field a member declares).

    F1 (D5-C): the desired-state form round-trips EVERY value as a string, so the no-op check is
    TYPE-TOLERANT (`str(_plain(cur)) == str(new)` => unchanged), and a numeric field (`start_year`) is
    written as a PLAIN scalar, NOT force-quoted — otherwise a member declaring int `start_year: 2003`,
    edited only on its title, would have `2003` silently re-typed to `"2003"` (a spurious diff line +
    a spurious commit on an untouched member, breaking the D13 diff-minimality / N-commits pins)."""
    coll = data.get("collection")
    created = False
    if not hasattr(coll, "get"):
        from ruamel.yaml.comments import CommentedMap
        coll = CommentedMap()
        data["collection"] = coll
        created = True
    changed = created
    for key in ("id",) + _COLLECTION_EDIT_FIELDS:
        if key not in block:
            continue
        new_val = block[key]
        if new_val in (None, ""):
            continue  # empty desired field: leave the member's own value untouched
        # Type-tolerant no-op: the form hands back "2003" for an on-disk int 2003 — compare as strings
        # so an unchanged numeric is NOT rewritten (keeps its exact on-disk form + type — no diff line).
        if key in coll and str(_plain(coll[key])) == str(new_val):
            continue
        coll[key] = _coerce_collection_value(key, new_val)
        changed = True
    if changed and str(_plain(coll.get("last_updated"))) != str(today):
        coll["last_updated"] = quote_ambiguous(today)
    return changed


# Collection fields written as a PLAIN numeric scalar (not a quoted string) when the value is all-digit
# — the reader-facing year is an int in the engine schema, and force-quoting it re-types 2003 -> "2003".
_COLLECTION_NUMERIC_FIELDS = frozenset({"start_year"})


def _coerce_collection_value(key: str, new_val):
    """Coerce a form-supplied collection value for emission (F1). A numeric field whose value is an
    all-digit string is written as a PLAIN int (unquoted); every other value rides quote_ambiguous
    (FIX 3) so a YAML-1.1-retypeable token is emitted quoted. A non-numeric `start_year` (e.g. a year
    range) still passes through quote_ambiguous as a string."""
    if key in _COLLECTION_NUMERIC_FIELDS and isinstance(new_val, str) and new_val.isdigit():
        return int(new_val)
    return quote_ambiguous(new_val)


def _apply_collection_remove(data) -> bool:
    """Drop a member's `collection` block entirely (remove it from the collection — 'no collection').
    Returns True iff a block was present to remove. The survey stays published; only its programme
    membership goes. A version bump + release note record it like any other content edit."""
    if "collection" in data:
        del data["collection"]
        return True
    return False


def _collection_effect(kind: str, old_cid: str | None, new_cid: str) -> str:
    """A display label for one survey's role in the batch: added / moved / removed / edit. Pure sugar
    for the batch-diff confirm; the git commit records the authoritative before/after."""
    if kind == "remove":
        return "removed"
    if old_cid is None:
        return "added"
    if new_cid and old_cid != new_cid:
        return "moved"
    return "edit"


def run_collection_batch_job(surveys_root: Path, *, operations: list, note: str, today: str,
                             validator_path: str, scratch_dir: Path) -> dict:
    """Handle a `collection_batch` edit-job (record D5-A A6): apply the per-survey collection-block
    operations, returning each AFFECTED survey's patched bytes + unified diff + validator report +
    version bump. NO git, NO commit — the gateway's commit_collection_batch does the atomic write.

    Each operation is `{slug, op: 'set'|'remove', block?: {...}}`. A 'set' patches (or creates) the
    member's `collection` block toward the desired fields; a 'remove' drops the block. A member whose
    block does NOT actually change is returned `changed: False` (no version bump, no commit — diff-
    minimality). A structural problem (bad slug, missing survey.yaml, non-semver current version) raises
    EditError for the WHOLE job so nothing is half-computed. Returns {ok, results: [...]}"""
    note = str(note or "").strip()
    if not note:
        raise EditError("a release note is required for a collection batch")
    if not isinstance(operations, list) or not operations:
        raise EditError("no operations in the collection batch")
    root_resolved = (surveys_root / "surveys").resolve()
    results: list = []
    for i, op in enumerate(operations):
        slug = str(op.get("slug") or "")
        if not _SLUG_RE.match(slug):
            raise EditError(f"invalid slug in collection batch: {slug!r}")
        kind = str(op.get("op") or "")
        pkg = (surveys_root / "surveys" / slug).resolve()
        if pkg != root_resolved and root_resolved not in pkg.parents:
            raise EditError("collection-batch path escapes the surveys tree")
        survey_yaml = pkg / "survey.yaml"
        if not survey_yaml.is_file():
            raise EditError(f"survey.yaml not found under {slug}")
        original_bytes = survey_yaml.read_bytes()
        data = _load_bytes(original_bytes)
        if not hasattr(data, "get"):
            raise EditError(f"survey.yaml is not a mapping: {slug}")
        old_coll = data.get("collection")
        old_cid = (str(old_coll.get("id"))
                   if hasattr(old_coll, "get") and old_coll.get("id") else None)
        if kind == "set":
            block = op.get("block") or {}
            changed = _apply_collection_set(data, block, today)
            effect = _collection_effect(kind, old_cid, str(block.get("id") or ""))
        elif kind == "remove":
            changed = _apply_collection_remove(data)
            effect = "removed"
        else:
            raise EditError(f"unknown collection-batch op {kind!r} for {slug}")
        if not changed:
            results.append({"slug": slug, "op": kind, "changed": False, "effect": "unchanged",
                            "old_collection_id": old_cid})
            continue
        old_version = data.get("version")
        old_v_str = old_version if isinstance(old_version, str) else "0.0.0"
        new_version = suggest_bump(old_v_str, "patch")
        if not semver_greater(new_version, old_v_str):
            raise EditError(
                f"cannot bump {slug}: current version {old_v_str!r} is not MAJOR.MINOR.PATCH semver — "
                f"fix it via a PR first (a content edit requires a semver-greater bump, C31 §0.3)")
        append_release_note(data, new_version, today, note)
        new_bytes = _dump_bytes(data)
        diff = "".join(difflib.unified_diff(
            original_bytes.decode("utf-8", "replace").splitlines(keepends=True),
            new_bytes.decode("utf-8", "replace").splitlines(keepends=True),
            fromfile=f"a/{slug}/survey.yaml", tofile=f"b/{slug}/survey.yaml"))
        report = _validate_patched(pkg, new_bytes, validator_path, scratch_dir / f"{i:03d}-{slug}")
        results.append({
            "slug": slug, "op": kind, "changed": True, "effect": effect,
            "old_collection_id": old_cid, "current_version": old_v_str, "new_version": new_version,
            "diff": diff,
            "new_yaml": new_bytes.decode("utf-8", "replace"),
            "new_yaml_b64": base64.b64encode(new_bytes).decode("ascii"),
            "new_sha256": hashlib.sha256(new_bytes).hexdigest(),
            "validator": report, "has_fail": report_has_fail(report),
        })
    return {"ok": True, "results": results}


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
