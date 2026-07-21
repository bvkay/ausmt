"""Approve -> commit to surveys-live (design §5, v2). Publish is COMMIT-AND-PUSH ONLY: the gateway
writes the approved package into the surveys-live git history (the publication ledger) and pushes it.
It does NOT build — which is what makes the C10 §0 no-Docker-socket invariant hold cleanly (the
gateway never invokes the build, never needs the socket). `PUBLISHED` therefore means "committed to
surveys-live main and pushed", NOT yet served. Since C40 the HOST-side serve-reconcile agent closes
that gap automatically on its next tick (~15 min; deploy/scripts/reconcile.sh — still not the
gateway, still no socket); manual `make rebuild-data` remains the fallback, and the UI copy says so.

Runs in-process in the gateway as a background task (the approve request returns immediately with
PUBLISHING; the curator watches the state). Single-flight: ONE module-level asyncio.Lock, because
every publish mutates the shared surveys-live checkout — two at once would corrupt it.

Fail closed at EVERY git step (design §5): the ENTIRE git sequence is wrapped so a failure at ANY
point (dirty tree, a commit-hook rejection, a non-ff merge, a push rejection) rolls surveys-live back
to the captured pre-state (ref AND branch, plus removal of staged untracked files) and lands
PUBLISH_FAILED. No partial publish; a PUBLISH_FAILED submission leaves surveys-live byte-for-byte the
pre-state, so a retry starts from a known-good state.

git is a SUBPROCESS behind an INJECTED SEAM (a git-runner callable on the Gateway, defaulting to the
real subprocess, overridable in tests — like the C10 scanner seam) so tests need no real git.

House rules enforced here: NO submitter email in the commit (PII stays in the DB; the commit records
who CURATED, not private contact). Subprocess args are a LIST, never shell=True; cwd pinned to
surveys-live; explicit SCRUBBED env (the gateway secrets are dropped so git + any hook cannot read
them). The slug is charset-validated before it reaches a path or a branch name.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("ausmt.gateway.publish")

# ONE publish at a time across the whole process (design §5). Module-level so every Gateway instance
# in a process shares it. NOTE: this single-flight + the crash reconciliation both assume ONE gateway
# process — the deployment MUST run single-worker (uvicorn --workers 1); see deploy/README.md. A
# multi-worker deployment would need cross-process coordination this demo deliberately does not build.
PUBLISH_LOCK = asyncio.Lock()

# Fixed commit identity (design §5.3). The commit records the gateway as author — never the
# submitter, whose contact details are PII confined to the DB.
COMMIT_AUTHOR_NAME = "AusMT Gateway"
COMMIT_AUTHOR_EMAIL = "gateway@ausmt.local"

# The env vars that must NEVER reach a git subprocess or a git hook (design §6). Scrubbed from the
# environment handed to the git runner so a hostile/careless hook cannot exfiltrate them.
_SECRET_ENV_VARS = ("AUSMT_SUBMIT_KEY", "AUSMT_CURATOR_KEYS")

# Slug charset for the staged directory + git branch name. A slug is a survey folder name; constrain
# it so it can never form a path traversal or a branch-name injection before it touches the fs/git.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# EDI filename charset for station removal — a bare basename (no path parts, no traversal) ending in
# .edi. Re-checked here before a selected name becomes a path component in `git rm` (the runner
# checked too; this is the last gate before a git/fs op). Mirrors runner.edit._EDI_NAME_RE.
_EDI_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.edi$", re.IGNORECASE)


class PublishError(Exception):
    """A step failed. The message is the operator-facing reason recorded on PUBLISH_FAILED. Carries
    the phase so the caller can log/surface where the publish stopped."""

    def __init__(self, phase: str, message: str):
        super().__init__(f"{phase}: {message}")
        self.phase = phase
        self.message = message


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


def scrubbed_env() -> dict[str, str]:
    """The process environment with the gateway secrets removed (design §6). git + any hook it runs
    inherit PATH/HOME/GIT_*/the credential-helper env, but NOT AUSMT_SUBMIT_KEY/AUSMT_CURATOR_KEYS."""
    env = dict(os.environ)
    for name in _SECRET_ENV_VARS:
        env.pop(name, None)
    return env


def real_git_runner(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> GitResult:
    """The real git seam: `git <args>` with cwd pinned to surveys-live, args as a LIST (never
    shell=True), output captured (never streamed — it could echo submitted bytes). The env is the
    SCRUBBED environment (secrets dropped) unless the caller overrides it; it still carries the
    operator's configured credential helper for the push. A timeout bounds a hung remote."""
    proc = subprocess.run(  # noqa: PLW1510 -- returncode inspected by the caller
        ["git", *args], cwd=str(cwd), env=env if env is not None else scrubbed_env(),
        capture_output=True, text=True, timeout=300,
    )
    return GitResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def validate_slug(slug: str | None) -> str:
    """Return the slug if it matches the safe charset; raise PublishError otherwise. The gate that
    stops a spoofed slug from reaching a path or a branch name (design §5.2/§6). FULLMATCH, not
    match — an anchored `$` matches before a trailing newline, so `.match` accepted "slug\n" (the
    trailing-newline class); this is the last gate before a git/fs op, so the check must be exact."""
    if not slug or not _SLUG_RE.fullmatch(slug):
        raise PublishError("guard", f"invalid or missing slug: {slug!r}")
    return slug


@dataclass(frozen=True)
class PreState:
    """The surveys-live state captured BEFORE any mutation (design §5 step 1). _rollback restores
    exactly this — the ref AND the branch — never "whatever is currently checked out" (a prior failed
    publish could have left HEAD on a submit branch)."""

    ref: str | None       # HEAD sha, or None on a repo with no commits yet
    branch: str | None     # the branch name HEAD was on (None if detached)


def preflight(git_runner, surveys_live: Path) -> PreState:
    """Design §5 step 1 pre-flight: the checkout must be CLEAN and on main before we touch it. A
    dirty tree or a HEAD not on main => ABORT (raise), so nothing is staged into an unknown state.
    Returns the captured pre-state (ref + branch) for a byte-exact rollback."""
    status = git_runner(["status", "--porcelain"], cwd=surveys_live)
    if status.returncode != 0:
        raise PublishError("preflight", (status.stderr or "git status failed").strip()[:500])
    if status.stdout.strip():
        raise PublishError("preflight",
                           "surveys-live checkout is dirty (uncommitted changes) — refusing to publish")
    branch = _current_branch(git_runner, surveys_live)
    if branch != "main":
        raise PublishError("preflight",
                           f"surveys-live HEAD is on {branch!r}, not 'main' — refusing to publish")
    return PreState(ref=_capture_head(git_runner, surveys_live), branch=branch)


def _current_branch(git_runner, cwd: Path) -> str | None:
    res = git_runner(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    name = res.stdout.strip() if res.returncode == 0 else ""
    return name or None


def _capture_head(git_runner, cwd: Path) -> str | None:
    res = git_runner(["rev-parse", "HEAD"], cwd=cwd)
    return res.stdout.strip() if res.returncode == 0 else None


def stage_package(package_dir: Path, surveys_live: Path, slug: str, *, allow_overwrite: bool) -> Path:
    """Copy quarantine/<id>/package/<slug>/ -> surveys-live/surveys/<slug>/. A pre-existing <slug>/
    is a version bump/collision: do NOT overwrite silently (design §5.2) unless the curator confirmed
    it (allow_overwrite, from an EXACT confirm token — not bool(any-string)). Returns the dest path."""
    src = package_dir / slug
    if not src.is_dir():
        raise PublishError("stage", f"package does not contain a {slug!r} directory")
    dest_root = surveys_live / "surveys"
    dest = dest_root / slug
    dest_resolved = dest.resolve()
    root_resolved = dest_root.resolve()
    if dest_resolved != root_resolved and root_resolved not in dest_resolved.parents:
        raise PublishError("stage", "staged path escapes surveys-live/surveys")
    if dest.exists():
        if not allow_overwrite:
            raise PublishError(
                "stage",
                f"survey {slug!r} already exists in surveys-live — confirm 'updates existing survey' "
                "to replace it")
        shutil.rmtree(dest)
    dest_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return dest


def stage_and_commit(git_runner, package_dir: Path, surveys_live: Path, slug: str,
                     submission_id: str, curator_name: str, note: str, pre: PreState,
                     *, allow_overwrite: bool) -> str:
    """Stage the package AND run the full git sequence, ALL inside one rollback guard (design §5 steps
    2-3): a failure at ANY point — a mid-copy stage error, a commit-hook rejection, a non-ff merge, a
    push rejection — rolls surveys-live back to `pre` (ref + branch + staged-untracked cleanup) so it
    is byte-for-byte the pre-state, then raises. Returns the new commit sha on success.

    Staging is inside the guard (not before it) so a partial copytree or an overwrite-abort that
    already removed the old tree is cleaned up too — the whole mutation is atomic-or-rolled-back."""
    branch = f"submit/{slug}-{submission_id}"
    subject = f"Publish survey {slug} ({submission_id})"
    body = (f"Curated-by: curator:{curator_name}\n"
            f"Submission-id: {submission_id}\n"
            f"Decision-note: {note}")
    try:
        stage_package(package_dir, surveys_live, slug, allow_overwrite=allow_overwrite)
        _git(git_runner, ["checkout", "-B", branch], surveys_live, "git-branch")
        _git(git_runner, ["add", "surveys"], surveys_live, "git-add")
        _git(git_runner,
             ["-c", f"user.name={COMMIT_AUTHOR_NAME}", "-c", f"user.email={COMMIT_AUTHOR_EMAIL}",
              "commit", "-m", subject, "-m", body],
             surveys_live, "git-commit")
        new_ref = _capture_head(git_runner, surveys_live) or ""
        _git(git_runner, ["checkout", "main"], surveys_live, "git-checkout-main")
        _git(git_runner, ["merge", "--ff-only", branch], surveys_live, "git-merge")
        push = git_runner(["push", "origin", "main"], cwd=surveys_live)
        if push.returncode != 0:
            raise PublishError("git-push", (push.stderr or push.stdout or "push failed").strip()[:500])
    except PublishError:
        _rollback(git_runner, surveys_live, pre, branch)
        raise
    return new_ref


def commit_metadata_edit(git_runner, surveys_live: Path, slug: str, new_yaml: bytes,
                         expected_sha256: str, curator_name: str, note: str, pre: PreState) -> str:
    """C31 §5: write the confirmed survey.yaml bytes into surveys-live/surveys/<slug>/survey.yaml and
    run the full git sequence inside ONE rollback guard, mirroring stage_and_commit. Fail-closed at
    every step; a failure anywhere rolls surveys-live back byte-for-byte to `pre` and re-raises.
    Returns the new commit sha.

    The §0.6 TOCTOU pin: `expected_sha256` is the sha256 the curator saw in the diff/preview. We
    re-hash the bytes about to be written and REFUSE (409 upstream) on any mismatch — a re-run merge
    or a concurrent edit would change the bytes and invalidate the preview. The bytes themselves are
    the artifact; the gateway does not re-derive them (it never parses yaml), it only re-hashes.

    The commit records `metadata edit by curator:<name>: <note>` (C31 §0.4 — the git history is the
    audit record); NEVER the submitter email (there is none here — this edits a published survey)."""
    actual = hashlib.sha256(new_yaml).hexdigest()
    if actual != expected_sha256:
        raise PublishError("hash-pin",
                           "the previewed yaml no longer matches (stale preview or concurrent edit) "
                           "— re-open the edit and try again")
    dest_root = surveys_live / "surveys"
    dest_dir = dest_root / slug
    dest_dir_resolved = dest_dir.resolve()
    root_resolved = dest_root.resolve()
    if dest_dir_resolved != root_resolved and root_resolved not in dest_dir_resolved.parents:
        raise PublishError("guard", "edited path escapes surveys-live/surveys")
    if not dest_dir.is_dir():
        raise PublishError("guard", f"survey {slug!r} does not exist in surveys-live")
    branch = f"metaedit/{slug}"
    subject = f"metadata edit by curator:{curator_name}: {slug}"
    body = f"Curated-by: curator:{curator_name}\nSurvey: {slug}\nEdit-note: {note}"
    try:
        (dest_dir / "survey.yaml").write_bytes(new_yaml)
        _git(git_runner, ["checkout", "-B", branch], surveys_live, "git-branch")
        _git(git_runner, ["add", "surveys"], surveys_live, "git-add")
        _git(git_runner,
             ["-c", f"user.name={COMMIT_AUTHOR_NAME}", "-c", f"user.email={COMMIT_AUTHOR_EMAIL}",
              "commit", "-m", subject, "-m", body],
             surveys_live, "git-commit")
        new_ref = _capture_head(git_runner, surveys_live) or ""
        _git(git_runner, ["checkout", "main"], surveys_live, "git-checkout-main")
        _git(git_runner, ["merge", "--ff-only", branch], surveys_live, "git-merge")
        push = git_runner(["push", "origin", "main"], cwd=surveys_live)
        if push.returncode != 0:
            raise PublishError("git-push", (push.stderr or push.stdout or "push failed").strip()[:500])
    except PublishError:
        _rollback(git_runner, surveys_live, pre, branch)
        raise
    return new_ref


def commit_station_removal(git_runner, surveys_live: Path, slug: str, new_yaml: bytes,
                           removed: list[str], expected_sha256: str, curator_name: str, note: str,
                           pre: PreState) -> str:
    """Station removal (EDI deletion) commit: git rm the selected EDIs from
    surveys-live/surveys/<slug>/transfer_functions/edi/, write the version-bumped survey.yaml, and run
    the full git sequence inside ONE rollback guard, mirroring commit_metadata_edit. Fail-closed at
    every step; a failure anywhere rolls surveys-live back byte-for-byte to `pre` and re-raises.
    Returns the new commit sha.

    The §0.6 TOCTOU pin holds on the survey.yaml bytes (`expected_sha256` is what the curator saw in
    the preview) — a re-run or concurrent edit changes the bytes and 409s here. The removed EDIs are
    re-checked for existence and re-validated for charset before they become path components (the
    house guard: never trust a name from the request). A removal that would leave ZERO EDIs is refused
    (at least one station must remain — deleting a whole survey is a separate operation). git rm stages
    the deletions AND removes them from the working tree; the survey.yaml write + `git add` stages the
    edit; one commit records both.

    The commit records `station removal by curator:<name>: <slug>` (the git history is the audit
    record — who removed which stations and why lives in the message + the release note); NEVER a
    submitter email (there is none — this edits a published survey)."""
    actual = hashlib.sha256(new_yaml).hexdigest()
    if actual != expected_sha256:
        raise PublishError("hash-pin",
                           "the previewed survey.yaml no longer matches (stale preview or concurrent "
                           "edit) — re-open the stations page and try again")
    dest_root = surveys_live / "surveys"
    dest_dir = dest_root / slug
    dest_dir_resolved = dest_dir.resolve()
    root_resolved = dest_root.resolve()
    if dest_dir_resolved != root_resolved and root_resolved not in dest_dir_resolved.parents:
        raise PublishError("guard", "edited path escapes surveys-live/surveys")
    if not dest_dir.is_dir():
        raise PublishError("guard", f"survey {slug!r} does not exist in surveys-live")

    edi_dir = dest_dir / "transfer_functions" / "edi"
    # Re-validate + re-check every selected name here (defence in depth: the runner validated too, but
    # publish is the last gate before a path/git op). A vanished file => refuse the WHOLE removal (no
    # half-removal). Refuse if the removal would leave no station.
    present = {p.name for p in edi_dir.iterdir()
               if p.is_file() and p.suffix.lower() == ".edi"} if edi_dir.is_dir() else set()
    targets: list[str] = []
    for name in removed:
        if not _EDI_NAME_RE.match(name or ""):
            raise PublishError("guard", f"not a valid EDI filename: {name!r}")
        if name not in present:
            raise PublishError("stale",
                               f"selected file {name!r} no longer exists — re-open the stations page")
        if name not in targets:
            targets.append(name)
    if not targets:
        raise PublishError("guard", "no stations selected for removal")
    if len(present - set(targets)) < 1:
        raise PublishError("guard",
                           "refusing to remove ALL stations — at least one EDI must remain")

    branch = f"stationrm/{slug}"
    subject = f"station removal by curator:{curator_name}: {slug}"
    removed_line = ", ".join(sorted(targets))
    body = (f"Curated-by: curator:{curator_name}\nSurvey: {slug}\n"
            f"Removed-stations: {removed_line}\nEdit-note: {note}")
    rel_edis = [f"surveys/{slug}/transfer_functions/edi/{name}" for name in sorted(targets)]
    try:
        _git(git_runner, ["checkout", "-B", branch], surveys_live, "git-branch")
        # git rm removes the EDIs from the index AND the working tree in one step.
        _git(git_runner, ["rm", "--", *rel_edis], surveys_live, "git-rm")
        (dest_dir / "survey.yaml").write_bytes(new_yaml)
        _git(git_runner, ["add", "surveys"], surveys_live, "git-add")
        _git(git_runner,
             ["-c", f"user.name={COMMIT_AUTHOR_NAME}", "-c", f"user.email={COMMIT_AUTHOR_EMAIL}",
              "commit", "-m", subject, "-m", body],
             surveys_live, "git-commit")
        new_ref = _capture_head(git_runner, surveys_live) or ""
        _git(git_runner, ["checkout", "main"], surveys_live, "git-checkout-main")
        _git(git_runner, ["merge", "--ff-only", branch], surveys_live, "git-merge")
        push = git_runner(["push", "origin", "main"], cwd=surveys_live)
        if push.returncode != 0:
            raise PublishError("git-push", (push.stderr or push.stdout or "push failed").strip()[:500])
    except PublishError:
        _rollback(git_runner, surveys_live, pre, branch)
        raise
    return new_ref


def commit_survey_removal(git_runner, surveys_live: Path, slug: str, curator_name: str, note: str,
                          pre: PreState) -> str:
    """Whole-survey retirement (C41 D2): `git rm -r` the ENTIRE survey package under
    surveys-live/surveys/<slug>/ in ONE commit inside the same rollback guard as the station-removal
    path, then ff-only merge + push. Returns the new commit sha.

    This GENERALISES the station-removal machinery to survey scope (record D2 "Mechanics"): unlike a
    station removal there is NO survey.yaml to re-write and NO validator run (there is nothing left to
    validate) — the whole directory goes. Survey-scope DIFF-MINIMALITY: `git rm -r -- surveys/<slug>`
    touches exactly the slug's paths and nothing else. Fail-closed at every step: a failure anywhere
    (git-rm, commit-hook, non-ff merge, push rejection) rolls surveys-live back byte-for-byte to `pre`
    and re-raises, so a failed retirement leaves the publication ledger untouched.

    The undo (record D2, load-bearing): because this publishes through git, `git revert <this commit>`
    restores the package byte-identically — git IS the soft delete, so no tombstone state machine is
    needed. The commit records who curated and why (author fixed to the gateway identity, curator name
    + retire note in the body per the publish convention); NEVER a submitter email (there is none — a
    published survey has no submitter contact in git)."""
    dest_root = surveys_live / "surveys"
    dest_dir = dest_root / slug
    dest_dir_resolved = dest_dir.resolve()
    root_resolved = dest_root.resolve()
    if dest_dir_resolved != root_resolved and root_resolved not in dest_dir_resolved.parents:
        raise PublishError("guard", "survey path escapes surveys-live/surveys")
    if not dest_dir.is_dir():
        raise PublishError("guard", f"survey {slug!r} does not exist in surveys-live")

    branch = f"retire/{slug}"
    subject = f"retire survey by curator:{curator_name}: {slug}"
    body = (f"Curated-by: curator:{curator_name}\nSurvey: {slug}\n"
            f"Retired: {slug}\nRetire-note: {note}")
    rel_path = f"surveys/{slug}"
    try:
        _git(git_runner, ["checkout", "-B", branch], surveys_live, "git-branch")
        # git rm -r removes the whole survey tree from the index AND the working tree in one step.
        _git(git_runner, ["rm", "-r", "--", rel_path], surveys_live, "git-rm")
        _git(git_runner,
             ["-c", f"user.name={COMMIT_AUTHOR_NAME}", "-c", f"user.email={COMMIT_AUTHOR_EMAIL}",
              "commit", "-m", subject, "-m", body],
             surveys_live, "git-commit")
        new_ref = _capture_head(git_runner, surveys_live) or ""
        _git(git_runner, ["checkout", "main"], surveys_live, "git-checkout-main")
        _git(git_runner, ["merge", "--ff-only", branch], surveys_live, "git-merge")
        push = git_runner(["push", "origin", "main"], cwd=surveys_live)
        if push.returncode != 0:
            raise PublishError("git-push", (push.stderr or push.stdout or "push failed").strip()[:500])
    except PublishError:
        _rollback(git_runner, surveys_live, pre, branch)
        raise
    return new_ref


def commit_collection_batch(git_runner, surveys_live: Path, cid: str, changes: list,
                            curator_name: str, note: str, pre: PreState) -> str:
    """C43 Stage 3b (record D5-A A6, D13 atomicity pin): commit an atomic collection batch as N commits
    (one per CHANGED member survey, each version-bumped) sharing ONE release note, all inside ONE
    rollback guard. This GENERALISES commit_metadata_edit from 1 survey to N — the only write path for
    collection edit / add / remove / move / rename / merge / normalise / create.

    `changes` is the list of CHANGED surveys only, each a dict:
      {slug, new_yaml: bytes, expected_sha256, has_fail, effect}

    ATOMICITY GATE (D13 pin 1, red-then-green) — VALIDATE-ALL-THEN-COMMIT-ALL. If ANY change carries
    `has_fail` True, this REFUSES before touching git: ZERO commits land, nothing is written. The gate
    runs first, so a partial batch (some members committed, then a failing one aborts) can never
    happen. (Proven RED against an interleaved commit-then-validate variant, which lands the passing
    members before hitting the failing one.)

    Each survey's own survey.yaml bytes are written and committed INDIVIDUALLY (`git add` scoped to that
    one path), so each commit's diff touches ONLY that survey's file (diff-minimality, D13 pin 4). The
    §0.6 TOCTOU hash pin holds PER survey: `expected_sha256` is what the curator saw in the preview; we
    re-hash the bytes about to be written and refuse the WHOLE batch on any mismatch (a stale preview or
    a concurrent edit). Fail-closed at EVERY step: a failure anywhere (stale-hash refusal, a write
    error, a commit-hook rejection, a non-ff merge, a push rejection) rolls surveys-live back byte-for-
    byte to `pre` and re-raises — never a partial batch. Returns the new HEAD commit sha.

    The commits record who curated + the batch note (the git history is the audit record); NEVER a
    submitter email (a published survey carries no submitter contact in git)."""
    if not changes:
        raise PublishError("guard", "empty collection batch — nothing to commit")
    # ATOMICITY GATE — checked BEFORE any git verb: a single member's validator FAIL blocks the lot with
    # ZERO commits (all-then-commit-all). This is the load-bearing invariant D13 pin 1 proves.
    failed = sorted(str(c.get("slug")) for c in changes if c.get("has_fail"))
    if failed:
        raise PublishError("validator",
                           "batch blocked: validator FAILED on " + ", ".join(failed)
                           + " — nothing was committed")
    # Re-hash pin (§0.6 TOCTOU) + path/existence guards for EVERY survey BEFORE mutating anything, so a
    # bad member is caught while surveys-live is still pristine (nothing to roll back yet).
    dest_root = surveys_live / "surveys"
    root_resolved = dest_root.resolve()
    prepared: list[tuple[str, bytes, Path, str]] = []
    for c in changes:
        slug = validate_slug(c.get("slug"))
        new_yaml = c.get("new_yaml")
        if not isinstance(new_yaml, (bytes, bytearray)):
            raise PublishError("guard", f"collection batch: missing bytes for {slug!r}")
        new_yaml = bytes(new_yaml)
        if hashlib.sha256(new_yaml).hexdigest() != c.get("expected_sha256"):
            raise PublishError(
                "hash-pin",
                "the previewed batch no longer matches (stale preview or concurrent edit) — re-open "
                "the collection editor and preview again")
        dest_dir = dest_root / slug
        dr = dest_dir.resolve()
        if dr != root_resolved and root_resolved not in dr.parents:
            raise PublishError("guard", "collection-batch path escapes surveys-live/surveys")
        if not dest_dir.is_dir():
            raise PublishError("guard", f"survey {slug!r} does not exist in surveys-live")
        prepared.append((slug, new_yaml, dest_dir, str(c.get("effect") or "edit")))

    branch = "collbatch/" + (re.sub(r"[^A-Za-z0-9._-]", "-", str(cid)) or "collection")[:80]
    try:
        _git(git_runner, ["checkout", "-B", branch], surveys_live, "git-branch")
        for slug, new_yaml, dest_dir, effect in prepared:
            (dest_dir / "survey.yaml").write_bytes(new_yaml)
            # `git add` scoped to THIS survey's file so the commit's diff is minimal (D13 pin 4).
            _git(git_runner, ["add", "--", f"surveys/{slug}/survey.yaml"], surveys_live, "git-add")
            subject = f"collection edit by curator:{curator_name}: {slug} ({effect} -> {cid})"
            body = (f"Curated-by: curator:{curator_name}\nSurvey: {slug}\n"
                    f"Collection: {cid}\nBatch-note: {note}")
            _git(git_runner,
                 ["-c", f"user.name={COMMIT_AUTHOR_NAME}", "-c", f"user.email={COMMIT_AUTHOR_EMAIL}",
                  "commit", "-m", subject, "-m", body],
                 surveys_live, "git-commit")
        new_ref = _capture_head(git_runner, surveys_live) or ""
        _git(git_runner, ["checkout", "main"], surveys_live, "git-checkout-main")
        _git(git_runner, ["merge", "--ff-only", branch], surveys_live, "git-merge")
        push = git_runner(["push", "origin", "main"], cwd=surveys_live)
        if push.returncode != 0:
            raise PublishError("git-push", (push.stderr or push.stdout or "push failed").strip()[:500])
    except PublishError:
        _rollback(git_runner, surveys_live, pre, branch)
        raise
    except Exception as exc:  # noqa: BLE001 -- F3: ANY mid-batch error (an OSError from write_bytes, a
        # subprocess error from the git runner) must still roll the WORKING TREE back — never leave
        # surveys-live on the collbatch/ branch with partial commits. Re-raised AS a PublishError so the
        # caller's fail-closed 409 path holds (main is already protected: the ff-merge is after the loop).
        _rollback(git_runner, surveys_live, pre, branch)
        raise PublishError("batch-write",
                           f"unexpected error mid-batch ({type(exc).__name__}): {exc}"[:500]) from exc
    return new_ref


def _git(git_runner, args: list[str], cwd: Path, phase: str) -> GitResult:
    res = git_runner(args, cwd=cwd)
    if res.returncode != 0:
        raise PublishError(phase, (res.stderr or res.stdout or "git failed").strip()[:500])
    return res


def _rollback(git_runner, surveys_live: Path, pre: PreState, submit_branch: str) -> None:
    """Restore surveys-live to the captured pre-state (design §5 step 3): checkout the pre branch AND
    reset --hard to the pre ref AND drop staged untracked files under surveys/, then delete the submit
    branch we created so a retry starts clean. Restores the CAPTURED branch/ref, never "whatever is
    currently checked out" — a prior failed publish could have left HEAD on a submit branch. Best-
    effort-logged: a rollback failure surfaces to the operator (dirty checkout caught by the next
    pre-flight), never a silently half-published tree."""
    steps: list[list[str]] = []
    if pre.branch:
        # Force-checkout the original branch FIRST (discard any working-tree changes from the failed
        # run) so the reset below lands on the right branch.
        steps.append(["checkout", "-f", pre.branch])
    if pre.ref:
        steps.append(["reset", "--hard", pre.ref])
    else:
        # No prior commit: hard-reset to the empty tree so staged files are removed.
        steps.append(["reset", "--hard"])
    # Remove untracked files/dirs (a staged package tree that failed before commit) under surveys/.
    steps.append(["clean", "-fd", "--", "surveys"])
    # Delete the submit branch we created; benign if it never existed.
    steps.append(["branch", "-D", submit_branch])
    for args in steps:
        res = git_runner(args, cwd=surveys_live)
        if res.returncode != 0 and args[0] != "branch":
            logger.error("publish rollback step %s failed (surveys-live may be dirty): %s",
                         args, (res.stderr or res.stdout or "").strip()[:500])
