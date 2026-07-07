"""Approve -> commit to surveys-live (design §5, v2). Demo mode is COMMIT-AND-PUSH ONLY: the gateway
writes the approved package into the surveys-live git history (the publication ledger) and pushes it.
It does NOT build. The operator runs `make rebuild-data` by hand afterward — which is what makes the
C10 §0 no-Docker-socket invariant hold cleanly (the gateway never invokes the build, never needs the
socket). `PUBLISHED` therefore means "committed to surveys-live main and pushed", NOT yet served; the
UI says so explicitly ("Committed to surveys-live. Run make rebuild-data on the server to serve it").

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
    stops a spoofed slug from reaching a path or a branch name (design §5.2/§6)."""
    if not slug or not _SLUG_RE.match(slug):
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
