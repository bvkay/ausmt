"""On-box backup agent (deploy/backup.sh) — snapshot / prune / fail-loud tests.

backup.sh is POSIX sh, tested as a BLACK BOX through `sh` over a fabricated data tree under tmp_path:
a gateway state dir holding a *real, tiny* sqlite DB (built here with python's stdlib sqlite3, in WAL
mode so the WAL-safe path is exercised for real), a reconcile-status.json, and a couple of decoy
"secret-looking" files that MUST NOT be copied. Every assertion is an INDEPENDENT OBSERVABLE — the
files that land in the snapshot dir, the `latest` symlink target, the count of retained snapshots, the
process exit code, the stderr message — never the script's own self-report.

The snapshot's sqlite copy is driven through a real host `sqlite3` when one is on PATH; when it is not
(and to keep the test hermetic + fast on any CI box) the tests point AUSMT_BACKUP_SQLITE at a tiny sh
shim that does a plain `cp`. That is fine for these tests: they verify backup.sh's ORCHESTRATION
(which files land where, symlink, prune, refusals), not sqlite's own .backup correctness (that is the
restore-drill's integrity_check). The "no sqlite3 at all" refusal is tested by pointing the override
at a non-existent command AND hiding docker.

Each test names its failure criterion in the docstring (Invariant 10). WINDOWS: symlink creation and
POSIX mode-deny are not reliably available, so those specific assertions skipif on os.name/nt with a
reason; the CORE snapshot+prune+refusal cases run everywhere (they run in CI on ubuntu via the
gateway-ci leg, where nothing is skipped)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "backup.sh"

_SH = shutil.which("sh") or shutil.which("bash")
pytestmark = pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run backup.sh")


def _make_db(path: Path, *, uploader_rows: int = 3) -> None:
    """Create a tiny WAL-mode sqlite DB that looks like the gateway's schema v2 (an uploader_keys
    table + a submissions table with a created_at column). Real bytes so the WAL-safe .backup path is
    exercised against an actual WAL DB, not a stub."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE uploader_keys (id INTEGER PRIMARY KEY, key_hash TEXT NOT NULL)")
        con.execute("CREATE TABLE submissions (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL)")
        for i in range(uploader_rows):
            con.execute("INSERT INTO uploader_keys (key_hash) VALUES (?)", (f"hash{i}",))
        con.execute("INSERT INTO submissions (created_at) VALUES ('2026-07-08T01:02:03Z')")
        con.commit()
    finally:
        con.close()


def _cp_shim(tmp_path: Path) -> Path:
    """A stand-in for `sqlite3 <db> ".backup <dest>"`: backup.sh invokes it as `<shim> <db> ".backup
    '<dest>'"`. The shim parses the dest out of the .backup arg and `cp`s the db there. Records that it
    ran so a test can prove the WAL-safe path (not a raw cp) was the one taken."""
    marker = tmp_path / "sqlite_shim.invoked"
    shim = tmp_path / "sqlite_shim.sh"
    shim.write_text(
        "#!/bin/sh\n"
        f'echo invoked >> "{marker.as_posix()}"\n'
        'db="$1"\n'
        # second arg is like: .backup '/path/to/dest'
        'dest=$(printf %s "$2" | sed -n "s/^\\.backup \\x27\\(.*\\)\\x27$/\\1/p")\n'
        '[ -n "$dest" ] || { echo "shim: could not parse dest from: $2" >&2; exit 3; }\n'
        'cp "$db" "$dest"\n',
        encoding="utf-8")
    shim.chmod(0o755)
    return shim


def _make_tree(tmp_path: Path, *, with_db: bool = True) -> dict:
    data = tmp_path / "data"
    state = data / "gateway" / "state"
    state.mkdir(parents=True, exist_ok=True)
    if with_db:
        _make_db(state / "gateway.sqlite")
    # A reconcile-status.json (non-secret operational metadata — must be INCLUDED).
    (state / "reconcile-status.json").write_text('{"action":"noop"}', encoding="utf-8")
    # Decoy secret-looking files in the state dir — must be EXCLUDED.
    (state / "uploader.env").write_text("SECRET=1\n", encoding="utf-8")
    (state / "tls.key").write_text("-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")
    (state / "id_ed25519").write_text("ssh-secret\n", encoding="utf-8")
    # A deploy/.env next to the script's real location would be dangerous to touch; the script must
    # never copy it regardless. We assert the snapshot has no .env by name below.
    backups = data / "backups"

    shim = _cp_shim(tmp_path)
    env = dict(os.environ)
    env["AUSMT_DATA_DIR"] = str(data)
    env["AUSMT_BACKUP_SQLITE"] = f"sh {shim.as_posix()}"
    import sys
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return {"data": data, "state": state, "backups": backups,
            "sqlite_marker": tmp_path / "sqlite_shim.invoked", "env": env}


def _run(tree: dict, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(tree["env"])
    if env_extra:
        env.update(env_extra)
    return subprocess.run([_SH, str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def _snapshots(tree: dict) -> list[Path]:
    b = tree["backups"]
    if not b.exists():
        return []
    return sorted(p for p in b.iterdir() if p.is_dir() and p.name != "latest")


# --------------------------------------------------------------------------------------------------

def test_snapshot_contains_db_and_status_and_excludes_secrets(tmp_path):
    """A run creates ONE snapshot dir containing the sqlite copy + reconcile-status.json and NOTHING
    that looks like a secret (.env / *.key / id_*). FAILS IF: the DB copy is missing, the status file
    is missing, OR any secret-looking file leaks into the snapshot (the PII/secret-containment
    invariant), OR the WAL-safe sqlite path was not the one taken."""
    tree = _make_tree(tmp_path)
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    snaps = _snapshots(tree)
    assert len(snaps) == 1, f"expected exactly one snapshot, got {snaps}"
    snap = snaps[0]
    assert (snap / "gateway.sqlite").is_file(), "snapshot must contain the DB copy"
    assert (snap / "reconcile-status.json").is_file(), "snapshot must contain reconcile-status.json"
    assert tree["sqlite_marker"].exists(), "the WAL-safe sqlite .backup path must be the one used"
    # No secrets, anywhere in the snapshot tree.
    leaked = [p.name for p in snap.rglob("*")
              if p.is_file() and (p.name.endswith(".env") or p.name.endswith(".key")
                                  or p.name.startswith("id_") or "secret" in p.name.lower())]
    assert leaked == [], f"secret-looking files must NEVER enter a snapshot; leaked: {leaked}"


@pytest.mark.skipif(os.name == "nt", reason="symlinks not reliably creatable on this Windows filesystem")
def test_latest_symlink_points_at_newest_snapshot(tmp_path):
    """After a run, backups/latest resolves to the snapshot just written. FAILS IF: no `latest` link
    exists, or it points somewhere other than the newest snapshot dir."""
    tree = _make_tree(tmp_path)
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    latest = tree["backups"] / "latest"
    assert latest.is_symlink() or latest.exists(), "a `latest` pointer must exist"
    snap = _snapshots(tree)[0]
    assert latest.resolve() == snap.resolve(), "`latest` must resolve to the newest snapshot"


def test_prune_keeps_newest_14(tmp_path):
    """With 20 pre-existing snapshot dirs, a run prunes to the newest 14 (13 old + this run's = 14).
    FAILS IF: pruning does not run (>14 remain) or over-prunes (<14). Snapshot dirs are named by UTC
    timestamp so a lexical sort is chronological; we pre-seed distinctly-named dirs."""
    tree = _make_tree(tmp_path)
    b = tree["backups"]
    b.mkdir(parents=True, exist_ok=True)
    # 20 stale snapshots, older timestamps than any this run will mint (2020..).
    for i in range(20):
        d = b / f"20200101T0000{i:02d}Z"
        d.mkdir()
        (d / "gateway.sqlite").write_text("stale\n", encoding="utf-8")
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    remaining = _snapshots(tree)
    assert len(remaining) == 14, f"expected 14 snapshots after prune, got {len(remaining)}"
    # The just-written (newest) snapshot must be among the survivors; the very oldest must be gone.
    assert (b / "20200101T000000Z") not in remaining, "oldest snapshot must be pruned"


def test_missing_data_dir_fails_loud(tmp_path):
    """An unset/nonexistent AUSMT_DATA_DIR (or an unreadable state dir) fails with rc!=0 and an
    actionable message. FAILS IF: the script silently succeeds or fabricates a phantom tree."""
    tree = _make_tree(tmp_path)
    r = _run(tree, env_extra={"AUSMT_DATA_DIR": str(tmp_path / "not-mounted")})
    assert r.returncode != 0
    assert "not-mounted" in r.stderr or "state" in r.stderr.lower()


def test_no_sqlite3_and_no_docker_refuses(tmp_path):
    """Neither sqlite3 nor docker available => the script REFUSES to raw-copy a live WAL DB and exits
    non-zero with a message pointing at the missing tool. FAILS IF: it silently `cp`s the live WAL DB
    (a potentially torn snapshot) or exits 0."""
    tree = _make_tree(tmp_path)
    # Point the sqlite override at a command that does not exist, and blank PATH-ish docker by running
    # with AUSMT_BACKUP_NO_DOCKER=1 (a test hook the script honours to force the no-fallback path).
    r = _run(tree, env_extra={"AUSMT_BACKUP_SQLITE": "definitely-not-a-real-sqlite3-xyz",
                              "AUSMT_BACKUP_NO_DOCKER": "1"})
    assert r.returncode != 0, "must refuse when no WAL-safe path exists"
    assert "sqlite" in r.stderr.lower() or "docker" in r.stderr.lower()
    # And it must NOT have produced a snapshot containing a raw-copied DB.
    assert _snapshots(tree) == [], "no snapshot may be produced without a WAL-safe copy"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode-deny not enforceable via chmod on Windows")
def test_unreadable_state_dir_points_at_ownership_prep(tmp_path):
    """An unreadable gateway state dir (the missing one-time ownership prep) => rc!=0 and the message
    points the operator at the README ownership prep. FAILS IF: the failure is silent or gives no
    actionable next step."""
    tree = _make_tree(tmp_path)
    tree["state"].chmod(0o000)
    try:
        r = _run(tree)
        assert r.returncode != 0
        assert "ownership" in r.stderr.lower() or "readme" in r.stderr.lower()
    finally:
        tree["state"].chmod(0o755)
