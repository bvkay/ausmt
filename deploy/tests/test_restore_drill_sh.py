"""Tested-restore half (deploy/scripts/restore-drill.sh) — the Invariant-10 check that an untested
backup is not a backup.

restore-drill.sh takes a snapshot dir (defaults to backups/latest), copies its gateway.sqlite to a
scratch temp, opens it with sqlite3(1) and verifies: PRAGMA integrity_check == ok, the uploader_keys
table EXISTS (schema v2), and prints the table list + uploader_keys row count + newest submission
created_utc for the operator to eyeball. It EXITS NON-ZERO with a loud message if any check fails.

These tests need a REAL sqlite3 (the drill's whole point is integrity_check + a schema probe — a cp
shim cannot do that), so they build genuine DBs with python's stdlib sqlite3 (schema mirrored from
gateway/db.py: a submissions table with created_utc, and the v2 uploader_keys table) and run the drill
against them. The drill is skipped where no sqlite3 binary is on PATH. Every assertion is an
INDEPENDENT OBSERVABLE — the process exit code and the printed report — never the script's self-report.
Each test names its failure criterion (Invariant 10)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "restore-drill.sh"

_SH = shutil.which("sh") or shutil.which("bash")
_SQLITE3 = shutil.which("sqlite3")
pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run restore-drill.sh"),
    pytest.mark.skipif(_SQLITE3 is None, reason="restore-drill needs a real sqlite3(1) on PATH"),
]


def _good_db(path: Path, *, uploader_rows=4, submissions=None) -> None:
    """A schema-v2 DB: uploader_keys present, a submissions table with created_utc rows. user_version
    stamped 2 to mirror the gateway's migration marker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(
            """
            CREATE TABLE submissions (
                id TEXT PRIMARY KEY, slug TEXT, state TEXT NOT NULL,
                created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
                zip_sha256 TEXT NOT NULL, submitter_name TEXT NOT NULL,
                submitter_email TEXT NOT NULL, token_hash TEXT NOT NULL);
            CREATE TABLE uploader_keys (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, email TEXT,
                key_sha256 TEXT NOT NULL UNIQUE, created_utc TEXT NOT NULL,
                created_by TEXT NOT NULL, revoked_utc TEXT, revoked_by TEXT, last_used_utc TEXT);
            """)
        for i in range(uploader_rows):
            con.execute("INSERT INTO uploader_keys (name, key_sha256, created_utc, created_by) "
                        "VALUES (?,?,?,?)", (f"k{i}", f"h{i}", "2026-01-01T00:00:00Z", "curator"))
        for ts in (submissions if submissions is not None else
                   ["2026-07-01T00:00:00Z", "2026-07-08T09:10:11Z", "2026-07-05T00:00:00Z"]):
            con.execute("INSERT INTO submissions (id, state, created_utc, updated_utc, zip_sha256, "
                        "submitter_name, submitter_email, token_hash) VALUES (?,?,?,?,?,?,?,?)",
                        (ts, "RECEIVED", ts, ts, "sha", "n", "e", "t"))
        con.execute("PRAGMA user_version=2")
        con.commit()
    finally:
        con.close()


def _v1_db_no_uploader_keys(path: Path) -> None:
    """A pre-v2 DB: valid + integrity-clean, but WITHOUT the uploader_keys table (the drill must reject
    it — restoring a v1 DB into a v2 gateway loses managed keys)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE submissions (id TEXT PRIMARY KEY, created_utc TEXT NOT NULL)")
        con.execute("INSERT INTO submissions VALUES ('s1','2026-07-08T00:00:00Z')")
        con.execute("PRAGMA user_version=1")
        con.commit()
    finally:
        con.close()


def _corrupt_db(path: Path) -> None:
    """Bytes that are NOT a valid sqlite database (a truncated/garbage file) — integrity_check must
    fail (or the open must fail), and the drill must reject it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Start from a real DB then clobber the middle so the header may survive but pages are corrupt.
    _good_db(path)
    data = bytearray(path.read_bytes())
    for i in range(100, min(len(data), 4000)):
        data[i] = 0xFF
    path.write_bytes(bytes(data))


def _snapshot(tmp_path: Path, maker) -> Path:
    snap = tmp_path / "backups" / "20260708T032000Z"
    snap.mkdir(parents=True, exist_ok=True)
    maker(snap / "gateway.sqlite")
    return snap


def _run(snapshot: Path | None, *, env_extra=None, args=()) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    argv = [_SH, str(_SCRIPT), *args]
    if snapshot is not None and not args:
        argv.append(str(snapshot))
    return subprocess.run(argv, capture_output=True, text=True, env=env)


# --------------------------------------------------------------------------------------------------

def test_passes_on_a_good_snapshot(tmp_path):
    """A healthy schema-v2 snapshot => rc 0, and the report prints the table list, the uploader_keys
    row count, and the NEWEST submission created_utc. FAILS IF: the drill errors on a valid DB, or the
    exit code is non-zero, or the eyeball figures are absent."""
    snap = _snapshot(tmp_path, lambda p: _good_db(p, uploader_rows=4))
    r = _run(snap)
    assert r.returncode == 0, f"a good snapshot must pass; stderr={r.stderr}"
    out = r.stdout + r.stderr
    assert "uploader_keys" in out, "must list/mention the uploader_keys table"
    assert "4" in out, "must print the uploader_keys row count (4)"
    # Newest submission created_utc must be the max, not just any row.
    assert "2026-07-08T09:10:11Z" in out, "must print the NEWEST submission timestamp"


def test_fails_loud_on_corrupt_db(tmp_path):
    """A corrupted DB => integrity_check fails => rc!=0 with a loud message. FAILS IF: the drill passes
    a corrupt DB (the exact false-confidence an untested backup gives)."""
    snap = _snapshot(tmp_path, _corrupt_db)
    r = _run(snap)
    assert r.returncode != 0, "a corrupt DB must fail the drill"
    out = (r.stdout + r.stderr).lower()
    assert "integrity" in out or "corrupt" in out or "malformed" in out, \
        f"must say WHY it failed; got: {out!r}"


def test_fails_when_uploader_keys_table_missing(tmp_path):
    """A v1 DB (integrity-clean but no uploader_keys table) => rc!=0 with a schema message. FAILS IF: a
    pre-v2 DB is accepted (a restore would silently lose curator-managed keys)."""
    snap = _snapshot(tmp_path, _v1_db_no_uploader_keys)
    r = _run(snap)
    assert r.returncode != 0, "a DB missing uploader_keys must fail the drill"
    assert "uploader_keys" in (r.stdout + r.stderr), "must name the missing table"


def test_missing_snapshot_db_fails_loud(tmp_path):
    """A snapshot dir with no gateway.sqlite => rc!=0 with a clear message. FAILS IF: the drill reports
    success against an empty snapshot."""
    snap = tmp_path / "backups" / "20260708T032000Z"
    snap.mkdir(parents=True, exist_ok=True)  # no DB inside
    r = _run(snap)
    assert r.returncode != 0
    assert "gateway.sqlite" in (r.stdout + r.stderr) or "not found" in (r.stdout + r.stderr).lower()


@pytest.mark.skipif(os.name == "nt", reason="symlinks not reliably creatable on this Windows filesystem")
def test_defaults_to_latest_symlink(tmp_path):
    """With no snapshot argument, the drill resolves backups/latest (via AUSMT_BACKUP_DIR). FAILS IF:
    the default path is not honoured and a healthy latest snapshot is not drilled."""
    backups = tmp_path / "backups"
    snap = _snapshot(tmp_path, lambda p: _good_db(p, uploader_rows=2))
    (backups / "latest").symlink_to(snap.name)
    r = _run(None, env_extra={"AUSMT_BACKUP_DIR": str(backups)})
    assert r.returncode == 0, f"default-to-latest must drill the healthy snapshot; stderr={r.stderr}"
    assert "2" in (r.stdout + r.stderr), "must print the uploader_keys row count from latest"
